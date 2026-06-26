"""
collect_changes.py
===================
Pulls raw change data from a Gerrit instance (default: review.opendev.org)
via the REST API and caches it to disk as paginated JSON files under
``raw_data/``, ready for build_topic_dataset.py to consume.

This is step 1 of the pipeline:

    1. collect_changes.py            <- this script (network, resumable)
    2. build_topic_dataset.py        <- topic-level aggregation (no network)
    3. extract_advanced_features.py  <- relation chains + snapshot features

Usage:
    # First run -- scope it with --project/--since or it will try to pull
    # every change on the whole instance.
    python collect_changes.py --project openstack/nova --since 2023-01-01

    # Re-run later with the SAME query -- picks up where it left off.
    python collect_changes.py --project openstack/nova --since 2023-01-01

    # Start this query over from scratch.
    python collect_changes.py --project openstack/nova --fresh

    # Quick test on a small slice before committing to a big pull.
    python collect_changes.py --project openstack/nova --max-pages 2

Output:
    raw_data/page_0000.json, raw_data/page_0001.json, ...
        Each file is the raw JSON array Gerrit returned for one page
        (after stripping the ")]}'" XSSI-protection prefix), exactly as
        the API sent it. build_topic_dataset.load_all_changes() consumes
        these directly via raw_dir.rglob("page_*.json").
    raw_data/.checkpoint.json
        Resume state: {"query", "next_start", "next_page", "done"}.
        Cleared by --fresh. If you change --query/--project/--since
        between runs without --fresh, the script refuses to mix scopes.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

#: Gerrit instance to query.
BASE_URL: str = "https://review.opendev.org"

#: Output directory -- must match build_topic_dataset.RAW_DATA_DIR.
RAW_DATA_DIR: Path = Path("raw_data")

#: Gerrit options requested on every change. These match exactly what
#: build_topic_dataset.py and extract_advanced_features.py expect to find:
#:   MESSAGES           -> review delay / CI-rerun / stall features
#:   DETAILED_LABELS     -> vote details + tags, used for bot detection
#:   ALL_REVISIONS        -> patchset stats (count, files-changed)
#:   DETAILED_ACCOUNTS  -> account ids/usernames/emails for contributor features
#:   CURRENT_FILES        -> files-changed size proxy
#:   TRACKING_IDS        -> spec/bug references
GERRIT_OPTIONS: tuple[str, ...] = (
    "MESSAGES",
    "DETAILED_LABELS",
    "ALL_REVISIONS",
    "DETAILED_ACCOUNTS",
    "CURRENT_FILES",
    "TRACKING_IDS",
)

#: Max page size Gerrit's REST API will honor (server-enforced ceiling).
GERRIT_MAX_PAGE_SIZE: int = 500

#: Seconds to sleep between page requests -- be polite to a public instance.
REQUEST_DELAY: float = 0.5

#: Retry policy for transient network errors.
MAX_RETRIES: int = 5
RETRY_BACKOFF_BASE: float = 2.0

_MAGIC_PREFIX = b")]}'\n"


def _strip_prefix(raw: bytes) -> bytes:
    """Strip Gerrit's XSSI-protection prefix from a raw response body."""
    return raw[len(_MAGIC_PREFIX):] if raw.startswith(_MAGIC_PREFIX) else raw


# ---------------------------------------------------------------------------
# Query construction
# ---------------------------------------------------------------------------

def build_query(query: str, since: str | None, project: list[str] | None) -> str:
    """
    Combine the base query with optional --since / --project filters.

    Gerrit ANDs space-separated predicates together, so we just append
    each one (parenthesising the OR'd project list so it binds correctly).
    """
    parts = [query] if query else []
    if since:
        parts.append(f"after:{since}")
    if project:
        proj_clause = " OR ".join(f"project:{p}" for p in project)
        parts.append(f"({proj_clause})")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Checkpoint handling (resumability)
# ---------------------------------------------------------------------------

def load_checkpoint(checkpoint_path: Path, query: str) -> dict[str, Any]:
    """
    Load resume state if it exists and matches *query*.

    A mismatched query means the on-disk pages were collected for a
    different scope -- refuse to silently mix them; tell the user to use
    --fresh or point --output-dir at a new directory instead.
    """
    if not checkpoint_path.exists():
        return {"query": query, "next_start": 0, "next_page": 0, "done": False}

    state = json.loads(checkpoint_path.read_text())
    if state.get("query") != query:
        print(
            "✗ Existing checkpoint was collected with a DIFFERENT query:\n"
            f"    on disk : {state.get('query')!r}\n"
            f"    this run: {query!r}\n"
            "Refusing to mix scopes. Re-run with --fresh to start over, or "
            "point --output-dir at a new directory."
        )
        sys.exit(1)
    return state


def save_checkpoint(checkpoint_path: Path, state: dict[str, Any]) -> None:
    checkpoint_path.write_text(json.dumps(state, indent=2))


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

def fetch_page(
    session: requests.Session,
    query: str,
    start: int,
    page_size: int,
) -> list[dict[str, Any]]:
    """
    Fetch a single page of changes starting at offset *start*.

    Retries transient errors (timeouts, 5xx, connection resets) with
    exponential backoff; raises after MAX_RETRIES.
    """
    params: list[tuple[str, str]] = [
        ("q", query), ("n", str(page_size)), ("S", str(start)),
    ]
    for opt in GERRIT_OPTIONS:
        params.append(("o", opt))

    url = f"{BASE_URL}/changes/"
    last_exc: Exception | None = None

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, params=params, timeout=60)
            if resp.status_code >= 500:
                raise requests.HTTPError(f"{resp.status_code} server error")
            resp.raise_for_status()
            return json.loads(_strip_prefix(resp.content))
        except (requests.RequestException, json.JSONDecodeError) as exc:
            last_exc = exc
            wait = RETRY_BACKOFF_BASE ** attempt
            print(
                f"  [WARN] attempt {attempt}/{MAX_RETRIES} failed ({exc}); "
                f"retrying in {wait:.0f}s"
            )
            time.sleep(wait)

    raise RuntimeError(
        f"Giving up on start={start} after {MAX_RETRIES} attempts"
    ) from last_exc


# ---------------------------------------------------------------------------
# Main collection loop
# ---------------------------------------------------------------------------

def collect(
    query: str,
    page_size: int,
    output_dir: Path,
    max_pages: int | None,
    fresh: bool,
) -> None:
    """Run the full paginated collection loop, resumable across runs."""
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / ".checkpoint.json"

    if fresh and checkpoint_path.exists():
        checkpoint_path.unlink()
        print("Cleared existing checkpoint (--fresh).")

    state = load_checkpoint(checkpoint_path, query)
    if state["done"]:
        print(
            "✓ Collection already marked complete for this query. "
            "Use --fresh to re-run from scratch."
        )
        return

    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    start_page = state["next_page"]
    page = start_page
    start = state["next_start"]
    n_changes_this_run = 0

    print(f"Query : {query!r}")
    print(f"{'Resuming' if start else 'Starting'} at page={page}, S={start}")

    while True:
        if max_pages is not None and (page - start_page) >= max_pages:
            print(f"Reached --max-pages={max_pages}; stopping early (resumable).")
            break

        print(f"Fetching page {page} (S={start}) …")
        changes = fetch_page(session, query, start, page_size)

        page_path = output_dir / f"page_{page:04d}.json"
        page_path.write_text(
            json.dumps(changes, ensure_ascii=False),
            encoding="utf-8"
        )
        n_changes_this_run += len(changes)
        print(f"  ✓ wrote {len(changes)} changes → {page_path}")

        more = bool(changes) and bool(changes[-1].get("_more_changes"))
        page += 1
        start += len(changes)

        save_checkpoint(checkpoint_path, {
            "query": query,
            "next_start": start,
            "next_page": page,
            "done": not more,
        })

        if not more:
            print("✓ No more pages -- collection complete.")
            break

        time.sleep(REQUEST_DELAY)

    print(f"\nDone. {n_changes_this_run:,} changes fetched this run → {output_dir}/")
    print("Next: python build_topic_dataset.py")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--query",
        default="status:open OR status:merged OR status:abandoned",
        help=(
            "Raw Gerrit query string (default: every status, i.e. no "
            "status filter at all). On a multi-project instance like "
            "review.opendev.org this is enormous on its own -- scope it "
            "down with --project and/or --since."
        ),
    )
    parser.add_argument(
        "--project", action="append", default=None,
        help=(
            "Limit to one project (repeatable for multiple), e.g. "
            "--project openstack/nova --project openstack/keystone"
        ),
    )
    parser.add_argument(
        "--since", default=None,
        help="Only changes created after this date, e.g. 2023-01-01",
    )
    parser.add_argument(
        "--page-size", type=int, default=GERRIT_MAX_PAGE_SIZE,
        help=f"Changes per page (server max {GERRIT_MAX_PAGE_SIZE}).",
    )
    parser.add_argument("--output-dir", type=Path, default=RAW_DATA_DIR)
    parser.add_argument(
        "--max-pages", type=int, default=None,
        help=(
            "Stop after fetching this many pages THIS RUN (resumable -- "
            "handy for testing on a small slice before a full pull)."
        ),
    )
    parser.add_argument(
        "--fresh", action="store_true",
        help="Discard the existing checkpoint and start this query over.",
    )
    args = parser.parse_args()

    if args.page_size > GERRIT_MAX_PAGE_SIZE:
        print(f"--page-size capped at server max {GERRIT_MAX_PAGE_SIZE}")
        args.page_size = GERRIT_MAX_PAGE_SIZE

    if not args.project and not args.since and args.query.startswith("status:"):
        print(
            "⚠  No --project or --since given -- this will try to pull "
            "every change on the entire instance. Ctrl-C now if that's "
            "not what you want, or pass --max-pages to test first.\n"
        )

    full_query = build_query(args.query, args.since, args.project)
    collect(full_query, args.page_size, args.output_dir, args.max_pages, args.fresh)


if __name__ == "__main__":
    main()