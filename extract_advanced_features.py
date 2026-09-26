"""
extract_advanced_features.py
=============================
Companion to collect_changes.py + build_topic_dataset.py.

build_topic_dataset.py already gives strong topic-level aggregates over the
FULL lifetime of a topic (review delay, CI, patchsets, contributors). It is
sufficient for tasks #1 (delay), #2 (stall), and #4 (CI churn) IF you accept
full-lifetime features. It does NOT yet provide:

  (A) Relation-chain / dependency data needed for task #3 (bottleneck
      prediction) — Gerrit's /changes/ list endpoint never returns this,
      it requires one extra call per change.

  (B) Snapshot ("as of N hours after creation") features needed for any
      *early* prediction — task #5 by definition, and the "early-warning"
      framing of #1/#2. Using full-lifetime aggregates to predict an early
      outcome is label leakage: e.g. "total CI failures" already contains
      information from after the prediction point.

This script adds exactly those two pieces, as separate functions you can
import or run standalone. It does not re-implement bot detection, CI
counting, etc. — import those from build_topic_dataset.py directly.

Usage:
    # Step 1 (network required): fetch relation chains for every change
    # already on disk under raw_data/
    python extract_advanced_features.py fetch-relations

    # Step 2 (no network): build per-change bottleneck feature rows using
    # the relation data fetched above
    python extract_advanced_features.py build-bottleneck-features

    # Step 3 (no network): build snapshot/early-window topic features at a
    # configurable cutoff (default 48h after topic creation)
    python extract_advanced_features.py build-snapshot-features --cutoff-hours 48
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

# Re-use the parsing/bot-detection logic already validated in your script
# rather than duplicating it.
sys.path.insert(0, str(Path(__file__).parent))
from build_topic_dataset import (  # noqa: E402
    RAW_DATA_DIR,
    parse_gerrit_ts,
    load_all_changes,
    discover_zuul_accounts,
    _is_bot_message,
    extract_code_review_labels,
)

BASE_URL = "https://review.opendev.org"
RELATIONS_DIR = Path("raw_data_relations")
REQUEST_DELAY = 0.5  # be polite — this is N requests, one per change

OUT_BOTTLENECK_CSV = Path("change_bottleneck_features.csv")
OUT_SNAPSHOT_CSV = Path("topic_snapshot_features.csv")

_MAGIC_PREFIX = b")]}'\n"


def _strip_prefix(raw: bytes) -> bytes:
    return raw[len(_MAGIC_PREFIX):] if raw.startswith(_MAGIC_PREFIX) else raw


# ---------------------------------------------------------------------------
# (A) Relation-chain fetching
# ---------------------------------------------------------------------------

def relation_file_path(change_id: str) -> Path:
    safe_id = change_id.replace("/", "_").replace("~", "_")
    return RELATIONS_DIR / f"{safe_id}.json"


def fetch_relation_chain(
    change_id: str,
    current_revision: str,
    session: requests.Session,
) -> dict[str, Any] | None:
    """
    Call GET /changes/{id}/revisions/{rev}/related for one change.

    Returns the parsed JSON (a dict with key "changes": [...]) or None on
    failure. Each entry in "changes" describes a change in the same
    relation chain, including its own commit/status, so you can determine
    which siblings are merged vs. still open ("blocking" the rest).
    """
    url = f"{BASE_URL}/changes/{change_id}/revisions/{current_revision}/related"
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return json.loads(_strip_prefix(resp.content))
    except requests.RequestException as exc:
        print(f"  [WARN] related-changes fetch failed for {change_id}: {exc}")
        return None


def fetch_all_relations() -> None:
    """
    Walk every change already collected under RAW_DATA_DIR, fetch its
    relation chain, and cache one JSON file per change under
    RELATIONS_DIR. Skips changes already cached (resumable, like
    collect_changes.py).
    """
    RELATIONS_DIR.mkdir(parents=True, exist_ok=True)
    all_changes = load_all_changes(RAW_DATA_DIR)

    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    n_fetched = 0
    n_skipped = 0
    n_no_revision = 0

    for change in all_changes:
        change_id = change.get("id")
        current_rev = change.get("current_revision")
        if not change_id or not current_rev:
            n_no_revision += 1
            continue

        out_path = relation_file_path(change_id)
        if out_path.exists():
            n_skipped += 1
            continue

        data = fetch_relation_chain(change_id, current_rev, session)
        if data is not None:
            out_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            n_fetched += 1
        time.sleep(REQUEST_DELAY)

        if (n_fetched) % 50 == 0 and n_fetched:
            print(f"  ... fetched {n_fetched} relation chains so far")

    print(
        f"\nDone. fetched={n_fetched}  already_cached={n_skipped}  "
        f"missing_revision={n_no_revision}"
    )


# ---------------------------------------------------------------------------
# (A continued) Bottleneck feature computation, per change
# ---------------------------------------------------------------------------

def load_relation_data() -> dict[str, dict[str, Any]]:
    """Load every cached relation-chain file into {change_id: data}."""
    out: dict[str, dict[str, Any]] = {}
    if not RELATIONS_DIR.exists():
        return out
    for path in RELATIONS_DIR.glob("*.json"):
        try:
            out[path.stem] = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
    return out


def compute_bottleneck_features(
    change: dict[str, Any],
    relation_data: dict[str, Any] | None,
    bot_accounts: set[int],
) -> dict[str, Any]:
    """
    Compute per-change bottleneck-candidate features.

    Fields
    ------
    in_degree_in_chain     : number of sibling changes in the relation chain
                              that come AFTER this one (i.e. depend on it,
                              directly or transitively, per Gerrit's
                              chain ordering).
    chain_length           : total number of changes in the relation chain
                              (1 if this change has no relations).
    is_chain_root          : True if this change has no changes before it
                              in the chain (a candidate root dependency).
    num_blocked_children   : number of NOT-merged changes after this one
                              in the chain — i.e. changes that cannot land
                              until this one does.
    submittable            : Gerrit's own mergeable-right-now flag, if the
                              collector requested SUBMITTABLE.
    code_review_plus2      : reuse from build_topic_dataset for convenience.
    """
    plus2, minus2 = extract_code_review_labels(change)

    if not relation_data or "changes" not in relation_data:
        return {
            "change_id": change.get("id"),
            "topic": (change.get("topic") or "").strip(),
            "project": change.get("project"),
            "status": change.get("status"),
            "in_degree_in_chain": 0,
            "chain_length": 1,
            "is_chain_root": True,
            "num_blocked_children": 0,
            "submittable": change.get("submittable"),
            "code_review_plus2": plus2,
            "code_review_minus2": minus2,
        }

    chain = relation_data["changes"]
    chain_length = len(chain)

    current_commit = change.get("current_revision")
    # Gerrit returns the chain in dependency order (oldest/root first).
    # Find this change's position by matching its current commit hash.
    my_index = None
    for idx, entry in enumerate(chain):
        if entry.get("commit", {}).get("commit") == current_commit:
            my_index = idx
            break
        # Fallback: match by change number if commit hash isn't present
        if entry.get("_change_number") == change.get("_number"):
            my_index = idx
            break

    if my_index is None:
        # Couldn't locate self in the chain — fall back to neutral values
        in_degree = 0
        is_root = True
        num_blocked = 0
    else:
        in_degree = chain_length - my_index - 1  # changes stacked on top
        is_root = my_index == 0
        num_blocked = sum(
            1 for entry in chain[my_index + 1:]
            if entry.get("status") not in ("MERGED", "ABANDONED")
        )

    return {
        "change_id": change.get("id"),
        "topic": (change.get("topic") or "").strip(),
        "project": change.get("project"),
        "status": change.get("status"),
        "in_degree_in_chain": in_degree,
        "chain_length": chain_length,
        "is_chain_root": is_root,
        "num_blocked_children": num_blocked,
        "submittable": change.get("submittable"),
        "code_review_plus2": plus2,
        "code_review_minus2": minus2,
    }


def build_bottleneck_dataset() -> None:
    """Build one CSV row per change with bottleneck-candidate features."""
    all_changes = load_all_changes(RAW_DATA_DIR)
    bot_accounts = discover_zuul_accounts(all_changes)
    relation_data = load_relation_data()

    if not relation_data:
        print(
            "⚠  No cached relation data found under "
            f"{RELATIONS_DIR}/. Run `fetch-relations` first — "
            "bottleneck features will default to single-change values."
        )

    rows = []
    for change in all_changes:
        change_id = change.get("id")
        rel = relation_data.get(change_id)
        rows.append(compute_bottleneck_features(change, rel, bot_accounts))

    fieldnames = list(rows[0].keys()) if rows else []
    with OUT_BOTTLENECK_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    n_with_children = sum(1 for r in rows if r["num_blocked_children"] > 0)
    print(f"✓ Wrote {len(rows)} change rows → {OUT_BOTTLENECK_CSV}")
    print(f"  Changes blocking at least one sibling: {n_with_children}")


# ---------------------------------------------------------------------------
# (B) Snapshot / early-window features — leakage-safe
# ---------------------------------------------------------------------------

def snapshot_topic_features(
    topic: str,
    changes: list[dict[str, Any]],
    bot_accounts: set[int],
    cutoff_hours: float,
) -> dict[str, Any]:
    """
    Compute topic-level features using ONLY events that happened within
    `cutoff_hours` of the topic's earliest change creation time.

    This is the leakage-safe counterpart to aggregate_topic() in
    build_topic_dataset.py, which uses each change's FULL lifetime.
    Use this version as the FEATURE set, and a separately-computed
    full-lifetime outcome (e.g. final `outcome`, `ci_failure_rate`,
    `time_to_completion_hours` from build_topic_dataset.py) as the LABEL.

    Fields mirror task #5 (early high-review-effort) and the "early"
    framing of #1/#2, but restricted to the cutoff window:
      - early_comment_count / early_comment_velocity (comments per hour)
      - early_unique_reviewers
      - early_patchset_count
      - initial_change_count   : # of changes already linked at cutoff
      - early_human_comment_ratio (vs. bot comments)
    """
    created_dts = [
        parse_gerrit_ts(c.get("created")) for c in changes
    ]
    created_dts = [d for d in created_dts if d is not None]
    if not created_dts:
        return {
            "topic_id": topic,
            "cutoff_hours": cutoff_hours,
            "initial_change_count": len(changes),
            "early_comment_count": 0,
            "early_comment_velocity": None,
            "early_unique_reviewers": 0,
            "early_patchset_count": 0,
            "early_human_comment_ratio": None,
        }

    topic_start = min(created_dts)
    cutoff_dt = topic_start
    from datetime import timedelta
    cutoff_dt = topic_start + timedelta(hours=cutoff_hours)

    early_comments = 0
    early_human_comments = 0
    early_reviewers: set[int] = set()
    early_patchsets = 0

    for change in changes:
        # Only count this change at all if it existed by the cutoff
        c_created = parse_gerrit_ts(change.get("created"))
        if c_created is None or c_created > cutoff_dt:
            continue

        for msg in change.get("messages") or []:
            msg_time = parse_gerrit_ts(msg.get("date"))
            if msg_time is None or msg_time > cutoff_dt:
                continue
            early_comments += 1
            if not _is_bot_message(msg, bot_accounts):
                early_human_comments += 1
                author = msg.get("author") or {}
                acct_id = author.get("_account_id")
                if acct_id is not None:
                    early_reviewers.add(int(acct_id))

        for rev in (change.get("revisions") or {}).values():
            rev_created = parse_gerrit_ts(rev.get("created"))
            if rev_created is not None and rev_created <= cutoff_dt:
                early_patchsets += 1

    velocity = (
        early_comments / cutoff_hours if cutoff_hours > 0 else None
    )
    human_ratio = (
        early_human_comments / early_comments if early_comments > 0 else None
    )

    return {
        "topic_id": topic,
        "cutoff_hours": cutoff_hours,
        "initial_change_count": len(
            [c for c in changes
             if (parse_gerrit_ts(c.get("created")) or topic_start) <= cutoff_dt]
        ),
        "early_comment_count": early_comments,
        "early_comment_velocity": (
            round(velocity, 4) if velocity is not None else None
        ),
        "early_unique_reviewers": len(early_reviewers),
        "early_patchset_count": early_patchsets,
        "early_human_comment_ratio": (
            round(human_ratio, 3) if human_ratio is not None else None
        ),
    }


def build_snapshot_dataset(cutoff_hours: float) -> None:
    """Build snapshot features for every topic at the given cutoff."""
    all_changes = load_all_changes(RAW_DATA_DIR)
    bot_accounts = discover_zuul_accounts(all_changes)

    topic_map: dict[str, list[dict[str, Any]]] = {}
    for change in all_changes:
        topic = (change.get("topic") or "").strip()
        if topic:
            topic_map.setdefault(topic, []).append(change)

    rows = [
        snapshot_topic_features(topic, changes, bot_accounts, cutoff_hours)
        for topic, changes in sorted(topic_map.items())
    ]

    fieldnames = list(rows[0].keys()) if rows else []
    with OUT_SNAPSHOT_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(
        f"✓ Wrote {len(rows)} topic rows (cutoff={cutoff_hours}h) "
        f"→ {OUT_SNAPSHOT_CSV}"
    )
    print(
        "  NOTE: join this on topic_id with the full-lifetime "
        "outcome/ci_failure_rate/etc. columns from topics_dataset.csv "
        "to get a leakage-safe (features-at-cutoff -> final outcome) "
        "training table."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser(
        "fetch-relations",
        help="Fetch /related relation chains for every collected change (network).",
    )
    sub.add_parser(
        "build-bottleneck-features",
        help="Build per-change bottleneck feature CSV from cached relation data.",
    )
    p_snap = sub.add_parser(
        "build-snapshot-features",
        help="Build leakage-safe early-window topic features.",
    )
    p_snap.add_argument(
        "--cutoff-hours",
        type=float,
        default=48.0,
        help="Hours after topic creation to cut off feature computation (default 48).",
    )

    args = parser.parse_args()

    if args.command == "fetch-relations":
        fetch_all_relations()
    elif args.command == "build-bottleneck-features":
        build_bottleneck_dataset()
    elif args.command == "build-snapshot-features":
        build_snapshot_dataset(args.cutoff_hours)


if __name__ == "__main__":
    main()