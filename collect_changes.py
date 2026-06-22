"""
collect_changes.py
==================
Collects raw Gerrit change data for a scoped set of OpenStack projects and
persists one JSON file per project+status+page under ./raw_data/.

Usage:
    python collect_changes.py [--dry-run]

Options:
    --dry-run   Print the first URL that would be requested and exit immediately.
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
# Configuration constants — edit these to change the pilot scope
# ---------------------------------------------------------------------------

#: Gerrit REST API base URL (no trailing slash)
BASE_URL: str = "https://review.opendev.org"

#: Projects to collect.  Use Gerrit's full project name (owner/repo).
PROJECTS: list[str] = [
    "openstack/nova",
    "openstack/neutron",
    "openstack/cinder",
    "openstack/keystone",
]

#: Only fetch changes *created on or after* this date (ISO 8601 date).
DATE_FROM: str = "2023-01-01"

#: Change statuses to collect.
STATUSES: list[str] = ["merged", "abandoned", "open"]

#: Maximum number of results Gerrit will return in a single request.
PAGE_SIZE: int = 500

#: Seconds to sleep between HTTP requests (0.5 – 1.0 recommended).
REQUEST_DELAY: float = 0.1

#: If the total raw changes collected exceeds this value, warn and pause.
SAFETY_CEILING: int = 50_000

#: Root directory for persisted raw JSON files.
RAW_DATA_DIR: Path = Path("raw_data")

#: Additional change detail options to request from Gerrit.
GERRIT_OPTIONS: list[str] = [
    "ALL_REVISIONS",
    "DETAILED_LABELS",
    "MESSAGES",
    "DETAILED_ACCOUNTS",
    "CURRENT_COMMIT",
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MAGIC_PREFIX = b")]}'\n"


def _strip_gerrit_prefix(raw: bytes) -> bytes:
    """Strip Gerrit's anti-XSSI magic prefix ``)]}'\\n`` if present."""
    if raw.startswith(_MAGIC_PREFIX):
        return raw[len(_MAGIC_PREFIX):]
    return raw


def fetch_changes(url: str, session: requests.Session) -> list[dict[str, Any]]:
    """
    Perform a single GET request to *url*, strip the Gerrit prefix and
    deserialise the JSON body.

    Parameters
    ----------
    url:
        Full URL including query string.
    session:
        Persistent :class:`requests.Session` instance.

    Returns
    -------
    list[dict]
        Parsed list of Gerrit change objects.

    Raises
    ------
    requests.HTTPError
        If the server returns a non-2xx status code.
    """
    response = session.get(url, timeout=30)
    response.raise_for_status()
    payload = _strip_gerrit_prefix(response.content)
    return json.loads(payload)


def build_url(project: str, status: str, before: str | None = None) -> str:
    """
    Construct the Gerrit ``/changes/`` query URL.

    Parameters
    ----------
    project:
        Gerrit project identifier, e.g. ``openstack/nova``.
    status:
        Change status filter: ``merged``, ``abandoned``, or ``open``.
    before:
        If given, append ``before:<timestamp>`` to paginate past results
        already seen.

    Returns
    -------
    str
        Fully-formed URL string ready for an HTTP GET.
    """
    query = f"project:{project}+status:{status}+after:{DATE_FROM}"
    if before:
        query += f"+before:{before}"

    option_params = "&".join(f"o={opt}" for opt in GERRIT_OPTIONS)
    url = f"{BASE_URL}/changes/?q={query}&n={PAGE_SIZE}&{option_params}"
    return url


def page_file_path(project: str, status: str, page: int) -> Path:
    """
    Return the filesystem path for a given project/status/page combination.

    Parameters
    ----------
    project:
        Gerrit project name (slashes replaced with underscores for safety).
    status:
        Change status string.
    page:
        1-based page number.

    Returns
    -------
    Path
        Absolute-ish path under :data:`RAW_DATA_DIR`.
    """
    safe_project = project.replace("/", "_")
    return RAW_DATA_DIR / safe_project / status / f"page_{page}.json"


def save_page(path: Path, data: list[dict[str, Any]]) -> None:
    """
    Persist *data* to *path* as pretty-printed JSON.

    Parameters
    ----------
    path:
        Destination file path.  Parent directories are created automatically.
    data:
        List of Gerrit change dicts to serialise.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _confirm_continue() -> bool:
    """
    Ask the operator interactively whether to continue past the safety ceiling.

    Returns
    -------
    bool
        ``True`` if the user consents, ``False`` otherwise.
    """
    try:
        answer = input(
            "\n⚠  Safety ceiling reached.  Continue collecting? [y/N] "
        ).strip().lower()
    except EOFError:
        answer = "n"
    return answer in {"y", "yes"}


# ---------------------------------------------------------------------------
# Core collection logic
# ---------------------------------------------------------------------------

def collect_project_status(
    project: str,
    status: str,
    session: requests.Session,
    total_collected: list[int],
    request_counter: list[int],
) -> int:
    """
    Collect all pages of changes for a single *project* + *status* pair.

    Pages already persisted on disk are skipped (resumability).

    Parameters
    ----------
    project:
        Gerrit project name.
    status:
        Change status (``merged`` / ``abandoned`` / ``open``).
    session:
        Shared HTTP session.
    total_collected:
        Single-element list used as a mutable counter for the global total.
    request_counter:
        Single-element list used as a mutable counter for HTTP requests made.

    Returns
    -------
    int
        Number of changes collected for this project+status pair (new only).
    """
    page = 1
    before: str | None = None
    local_count = 0
    ceiling_warned = False

    while True:
        path = page_file_path(project, status, page)

        # --- Resumability: reuse existing pages ---
        if path.exists():
            print(f"  [SKIP] {project} / {status} / page {page} already on disk.")
            with path.open("r", encoding="utf-8") as fh:
                changes = json.load(fh)
            has_more = any(c.get("_more_changes") for c in changes)
            if changes:
                before = changes[-1]["updated"]
            page += 1
            # Don't add to total_collected for already-cached pages
            if not has_more:
                break
            continue

        # --- Fetch ---
        url = build_url(project, status, before)
        print(
            f"  [FETCH] {project} / {status} / page {page} "
            f"(request #{request_counter[0] + 1}) …",
            end="",
            flush=True,
        )

        try:
            changes = fetch_changes(url, session)
        except requests.RequestException as exc:
            print(f"\n  [ERROR] {exc}")
            raise

        request_counter[0] += 1
        save_page(path, changes)

        # Strip the sentinel entry Gerrit uses to signal more pages
        actual_changes = [c for c in changes if not c.get("_more_changes")]
        # Gerrit may attach _more_changes to the last real item, not a separate entry
        has_more = any(c.get("_more_changes") for c in changes)

        count_on_page = len(actual_changes)
        local_count += count_on_page
        total_collected[0] += count_on_page

        print(f" {count_on_page} items (total so far: {total_collected[0]})")

        # --- Safety ceiling ---
        if total_collected[0] >= SAFETY_CEILING and not ceiling_warned:
            ceiling_warned = True
            print(
                f"\n⚠  WARNING: Total raw changes collected has reached "
                f"{total_collected[0]:,}, which meets or exceeds the "
                f"safety ceiling of {SAFETY_CEILING:,}."
            )
            if not _confirm_continue():
                print("Stopping at user request.")
                sys.exit(0)

        if not has_more or not actual_changes:
            break

        before = changes[-1]["updated"]
        page += 1
        time.sleep(REQUEST_DELAY)

    return local_count


def collect_all(dry_run: bool = False) -> None:
    """
    Main entry point: iterate over every configured project and status,
    collect all pages, and log progress.

    Parameters
    ----------
    dry_run:
        If ``True``, print the first URL that would be requested and exit.
    """
    if dry_run:
        url = build_url(PROJECTS[0], STATUSES[0])
        print(f"[DRY RUN] First URL: {url}")
        return

    session = requests.Session()
    session.headers.update({"Accept": "application/json"})

    total_collected: list[int] = [0]
    request_counter: list[int] = [0]

    print("=" * 70)
    print("Gerrit Change Collection — pilot phase")
    print(f"  Projects : {PROJECTS}")
    print(f"  Statuses : {STATUSES}")
    print(f"  After    : {DATE_FROM}")
    print(f"  Page size: {PAGE_SIZE}")
    print("=" * 70)

    for project in PROJECTS:
        for status in STATUSES:
            print(f"\n→ Collecting {project!r} / {status!r} …")
            try:
                n = collect_project_status(
                    project,
                    status,
                    session,
                    total_collected,
                    request_counter,
                )
                print(f"  ✓ {n} new changes collected for {project}/{status}")
            except requests.RequestException:
                print(f"  ✗ Failed for {project}/{status} — skipping.")

    print("\n" + "=" * 70)
    print(f"Collection complete.")
    print(f"  Total HTTP requests : {request_counter[0]:,}")
    print(f"  Total changes (new) : {total_collected[0]:,}")
    print("=" * 70)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    """Parse CLI arguments and invoke :func:`collect_all`."""
    parser = argparse.ArgumentParser(
        description="Collect raw Gerrit changes for OpenStack pilot analytics.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the first request URL and exit without fetching.",
    )
    args = parser.parse_args()
    collect_all(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
