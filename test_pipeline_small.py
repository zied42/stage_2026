"""
test_pipeline_small.py
======================
End-to-end test of the Gerrit topic analytics pipeline on a small data
subset extracted from existing raw_data/.

Validates all features required for the 5 internship prediction tasks:
  #1 Long review delays
  #2 Stall / abandon risk
  #3 Coordination bottleneck (dependency chains)
  #4 CI reruns / excessive patch revisions
  #5 High review effort (early-window / snapshot)

Usage:
    python test_pipeline_small.py
"""

from __future__ import annotations

import csv
import json
import shutil
import statistics
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Source directory with real collected data
SOURCE_RAW_DIR = Path("raw_data")

#: Temporary directory used by the test
TEST_RAW_DIR = Path("test_raw_data")

#: How many changes to extract for the test
SAMPLE_SIZE = 200

#: We only keep changes that have a topic (otherwise aggregation is trivial)
MIN_TOPICS_EXPECTED = 3

# ---------------------------------------------------------------------------
# Colour helpers for terminal output
# ---------------------------------------------------------------------------

def _green(s: str) -> str:
    return f"\033[92m{s}\033[0m"

def _red(s: str) -> str:
    return f"\033[91m{s}\033[0m"

def _yellow(s: str) -> str:
    return f"\033[93m{s}\033[0m"

def _cyan(s: str) -> str:
    return f"\033[96m{s}\033[0m"

def _bold(s: str) -> str:
    return f"\033[1m{s}\033[0m"


# ---------------------------------------------------------------------------
# Step 1: Extract a small sample from existing data
# ---------------------------------------------------------------------------

def extract_sample() -> list[dict[str, Any]]:
    """
    Load a subset of changes from the first few page files in SOURCE_RAW_DIR.
    Prioritises changes that HAVE a topic field, because that's what the
    pipeline actually processes.
    """
    print(_bold("\n═══ Step 1: Extracting sample data ═══"))

    page_files = sorted(SOURCE_RAW_DIR.rglob("page_*.json"))
    if not page_files:
        print(_red("  ✗ No page_*.json files found under raw_data/"))
        print("    Run collect_changes.py first.")
        sys.exit(1)

    print(f"  Found {len(page_files)} page files in {SOURCE_RAW_DIR}/")

    all_changes: list[dict[str, Any]] = []
    with_topic: list[dict[str, Any]] = []
    without_topic: list[dict[str, Any]] = []

    for path in page_files:
        if len(all_changes) >= SAMPLE_SIZE * 5:
            break  # don't read everything — just enough to find topics
        try:
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"  [WARN] Skipping {path}: {exc}")
            continue

        for change in data:
            if "_more_changes" in change and len(change) == 1:
                continue
            topic = (change.get("topic") or "").strip()
            if topic:
                with_topic.append(change)
            else:
                without_topic.append(change)

    # Build the sample: prefer changes with topics, fill remainder with others
    sample = with_topic[:SAMPLE_SIZE]
    remaining = SAMPLE_SIZE - len(sample)
    if remaining > 0:
        sample.extend(without_topic[:remaining])

    print(f"  Sample: {len(sample)} changes ({len([c for c in sample if (c.get('topic') or '').strip()])} with topics)")

    # Write sample to test directory
    if TEST_RAW_DIR.exists():
        shutil.rmtree(TEST_RAW_DIR)
    TEST_RAW_DIR.mkdir(parents=True, exist_ok=True)

    page_path = TEST_RAW_DIR / "page_0000.json"
    page_path.write_text(
        json.dumps(sample, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"  Wrote {len(sample)} changes → {page_path}")
    return sample


# ---------------------------------------------------------------------------
# Step 2: Run build_topic_dataset on the sample
# ---------------------------------------------------------------------------

def run_build_topic_dataset() -> tuple[list[dict[str, Any]], bool]:
    """
    Run the topic aggregation pipeline on TEST_RAW_DIR.
    Returns (topic_rows, success).
    """
    print(_bold("\n═══ Step 2: Running build_topic_dataset ═══"))

    # Temporarily override the module-level constants
    import build_topic_dataset as btd

    orig_raw = btd.RAW_DATA_DIR
    orig_csv = btd.OUTPUT_CSV
    orig_parquet = btd.OUTPUT_PARQUET

    test_csv = Path("test_topics_dataset.csv")
    test_parquet = Path("test_topics_dataset.parquet")

    btd.RAW_DATA_DIR = TEST_RAW_DIR
    btd.OUTPUT_CSV = test_csv
    btd.OUTPUT_PARQUET = test_parquet

    try:
        btd.build_dataset()
        print(_green("  ✓ build_topic_dataset completed successfully"))
        success = True
    except Exception as exc:
        print(_red(f"  ✗ build_topic_dataset FAILED: {exc}"))
        traceback.print_exc()
        success = False
    finally:
        btd.RAW_DATA_DIR = orig_raw
        btd.OUTPUT_CSV = orig_csv
        btd.OUTPUT_PARQUET = orig_parquet

    # Load the results
    topic_rows: list[dict[str, Any]] = []
    if success and test_csv.exists():
        with test_csv.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                # Convert numeric fields
                parsed: dict[str, Any] = {}
                for k, v in row.items():
                    if v == "" or v is None:
                        parsed[k] = None
                    else:
                        try:
                            if "." in v:
                                parsed[k] = float(v)
                            else:
                                parsed[k] = int(v)
                        except (ValueError, TypeError):
                            parsed[k] = v
                topic_rows.append(parsed)
        print(f"  Loaded {len(topic_rows)} topic rows from {test_csv}")

    # Clean up test output files
    for f in [test_csv, test_parquet]:
        if f.exists():
            f.unlink()

    return topic_rows, success


# ---------------------------------------------------------------------------
# Step 3: Run extract_advanced_features (snapshot) on the sample
# ---------------------------------------------------------------------------

def run_snapshot_features() -> tuple[list[dict[str, Any]], bool]:
    """
    Run the snapshot (early-window) feature builder on TEST_RAW_DIR.
    Returns (snapshot_rows, success).
    """
    print(_bold("\n═══ Step 3: Running extract_advanced_features (snapshot) ═══"))

    import extract_advanced_features as eaf
    import build_topic_dataset as btd

    orig_raw = btd.RAW_DATA_DIR
    orig_eaf_raw = eaf.RAW_DATA_DIR  # eaf has its own imported copy
    orig_out = eaf.OUT_SNAPSHOT_CSV
    test_snapshot_csv = Path("test_topic_snapshot_features.csv")

    btd.RAW_DATA_DIR = TEST_RAW_DIR
    eaf.RAW_DATA_DIR = TEST_RAW_DIR  # must override both copies
    eaf.OUT_SNAPSHOT_CSV = test_snapshot_csv

    try:
        eaf.build_snapshot_dataset(cutoff_hours=48.0)
        print(_green("  ✓ build_snapshot_features completed successfully"))
        success = True
    except Exception as exc:
        print(_red(f"  ✗ build_snapshot_features FAILED: {exc}"))
        traceback.print_exc()
        success = False
    finally:
        btd.RAW_DATA_DIR = orig_raw
        eaf.RAW_DATA_DIR = orig_eaf_raw
        eaf.OUT_SNAPSHOT_CSV = orig_out

    # Load results
    snapshot_rows: list[dict[str, Any]] = []
    if success and test_snapshot_csv.exists():
        with test_snapshot_csv.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                parsed: dict[str, Any] = {}
                for k, v in row.items():
                    if v == "" or v is None:
                        parsed[k] = None
                    else:
                        try:
                            if "." in v:
                                parsed[k] = float(v)
                            else:
                                parsed[k] = int(v)
                        except (ValueError, TypeError):
                            parsed[k] = v
                snapshot_rows.append(parsed)
        print(f"  Loaded {len(snapshot_rows)} snapshot rows from {test_snapshot_csv}")

    if test_snapshot_csv.exists():
        test_snapshot_csv.unlink()

    return snapshot_rows, success


# ---------------------------------------------------------------------------
# Step 4: Run bottleneck feature computation (offline — no network)
# ---------------------------------------------------------------------------

def run_bottleneck_features() -> tuple[list[dict[str, Any]], bool]:
    """
    Run the bottleneck feature builder on TEST_RAW_DIR.
    This works even without relation chain data — it just defaults to
    single-change values, which is fine for testing the computation path.
    """
    print(_bold("\n═══ Step 4: Running extract_advanced_features (bottleneck) ═══"))

    import extract_advanced_features as eaf
    import build_topic_dataset as btd

    orig_raw = btd.RAW_DATA_DIR
    orig_eaf_raw = eaf.RAW_DATA_DIR  # eaf has its own imported copy
    orig_out = eaf.OUT_BOTTLENECK_CSV
    test_bottleneck_csv = Path("test_change_bottleneck_features.csv")

    btd.RAW_DATA_DIR = TEST_RAW_DIR
    eaf.RAW_DATA_DIR = TEST_RAW_DIR  # must override both copies
    eaf.OUT_BOTTLENECK_CSV = test_bottleneck_csv

    try:
        eaf.build_bottleneck_dataset()
        print(_green("  ✓ build_bottleneck_features completed successfully"))
        success = True
    except Exception as exc:
        print(_red(f"  ✗ build_bottleneck_features FAILED: {exc}"))
        traceback.print_exc()
        success = False
    finally:
        btd.RAW_DATA_DIR = orig_raw
        eaf.RAW_DATA_DIR = orig_eaf_raw
        eaf.OUT_BOTTLENECK_CSV = orig_out

    # Load results
    bottleneck_rows: list[dict[str, Any]] = []
    if success and test_bottleneck_csv.exists():
        with test_bottleneck_csv.open("r", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                parsed: dict[str, Any] = {}
                for k, v in row.items():
                    if v == "" or v is None:
                        parsed[k] = None
                    else:
                        try:
                            if "." in v:
                                parsed[k] = float(v)
                            else:
                                parsed[k] = int(v)
                        except (ValueError, TypeError):
                            parsed[k] = v
                bottleneck_rows.append(parsed)
        print(f"  Loaded {len(bottleneck_rows)} bottleneck rows from {test_bottleneck_csv}")

    if test_bottleneck_csv.exists():
        test_bottleneck_csv.unlink()

    return bottleneck_rows, success


# ---------------------------------------------------------------------------
# Step 5: Validate features for each prediction task
# ---------------------------------------------------------------------------

class TestResults:
    """Accumulate pass/fail results with detailed messages."""

    def __init__(self) -> None:
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.warnings: list[str] = []

    def check(self, condition: bool, description: str) -> None:
        if condition:
            self.passed.append(description)
        else:
            self.failed.append(description)

    def warn(self, description: str) -> None:
        self.warnings.append(description)

    @property
    def total(self) -> int:
        return len(self.passed) + len(self.failed)


def _coverage(rows: list[dict[str, Any]], field: str) -> float:
    """Return fraction of rows where field is non-None."""
    if not rows:
        return 0.0
    non_null = sum(1 for r in rows if r.get(field) is not None)
    return non_null / len(rows)


def validate_task1_review_delays(
    topic_rows: list[dict[str, Any]], results: TestResults,
) -> None:
    """Task #1: Predicting long review delays."""
    print(_cyan("\n  ── Task #1: Long Review Delays ──"))

    # Required columns exist
    required = [
        "first_review_delay_hours", "avg_review_delay_hours",
        "avg_active_days", "last_activity_gap_days",
    ]
    for col in required:
        present = any(col in r for r in topic_rows)
        results.check(present, f"Column '{col}' exists in output")

    # No negative delays
    neg_first = sum(
        1 for r in topic_rows
        if r.get("first_review_delay_hours") is not None
        and r["first_review_delay_hours"] < 0
    )
    results.check(neg_first == 0, f"No negative first_review_delay_hours (found {neg_first})")

    neg_avg = sum(
        1 for r in topic_rows
        if r.get("avg_review_delay_hours") is not None
        and r["avg_review_delay_hours"] < 0
    )
    results.check(neg_avg == 0, f"No negative avg_review_delay_hours (found {neg_avg})")

    # Reasonable coverage
    cov = _coverage(topic_rows, "first_review_delay_hours")
    results.check(cov > 0.1, f"first_review_delay_hours coverage > 10% (actual: {cov:.1%})")

    cov2 = _coverage(topic_rows, "avg_active_days")
    results.check(cov2 > 0.1, f"avg_active_days coverage > 10% (actual: {cov2:.1%})")


def validate_task2_stall_risk(
    topic_rows: list[dict[str, Any]], results: TestResults,
) -> None:
    """Task #2: Stall / abandon risk prediction."""
    print(_cyan("\n  ── Task #2: Stall / Abandon Risk ──"))

    required = [
        "outcome", "last_activity_gap_days",
        "n_merged", "n_abandoned", "n_open",
    ]
    for col in required:
        present = any(col in r for r in topic_rows)
        results.check(present, f"Column '{col}' exists in output")

    # Outcome values are from the expected set
    outcomes = {r["outcome"] for r in topic_rows if r.get("outcome")}
    valid_outcomes = {"merged", "abandoned", "stale_open", "mixed"}
    bad_outcomes = outcomes - valid_outcomes
    results.check(len(bad_outcomes) == 0, f"All outcomes are valid (unexpected: {bad_outcomes})")

    # n_merged + n_abandoned + n_open == n_changes
    mismatches = sum(
        1 for r in topic_rows
        if (r.get("n_merged") or 0) + (r.get("n_abandoned") or 0) + (r.get("n_open") or 0)
        != (r.get("n_changes") or 0)
    )
    results.check(mismatches == 0, f"n_merged + n_abandoned + n_open == n_changes (mismatches: {mismatches})")


def validate_task3_bottleneck(
    bottleneck_rows: list[dict[str, Any]], results: TestResults,
) -> None:
    """Task #3: Coordination bottleneck prediction."""
    print(_cyan("\n  ── Task #3: Coordination Bottleneck ──"))

    required = [
        "change_id", "topic", "in_degree_in_chain",
        "chain_length", "is_chain_root", "num_blocked_children",
        "code_review_plus2", "code_review_minus2",
    ]
    for col in required:
        present = any(col in r for r in bottleneck_rows)
        results.check(present, f"Column '{col}' exists in bottleneck output")

    # chain_length >= 1
    bad_chain = sum(
        1 for r in bottleneck_rows
        if r.get("chain_length") is not None and r["chain_length"] < 1
    )
    results.check(bad_chain == 0, f"All chain_length >= 1 (violations: {bad_chain})")

    # in_degree >= 0
    bad_degree = sum(
        1 for r in bottleneck_rows
        if r.get("in_degree_in_chain") is not None and r["in_degree_in_chain"] < 0
    )
    results.check(bad_degree == 0, f"All in_degree_in_chain >= 0 (violations: {bad_degree})")

    # num_blocked_children >= 0
    bad_blocked = sum(
        1 for r in bottleneck_rows
        if r.get("num_blocked_children") is not None and r["num_blocked_children"] < 0
    )
    results.check(bad_blocked == 0, f"All num_blocked_children >= 0 (violations: {bad_blocked})")


def validate_task4_ci_churn(
    topic_rows: list[dict[str, Any]], results: TestResults,
) -> None:
    """Task #4: CI reruns / excessive patch revisions."""
    print(_cyan("\n  ── Task #4: CI Reruns / Patch Revisions ──"))

    required = [
        "ci_runs", "ci_successes", "ci_failures",
        "ci_failure_rate", "ci_retries",
        "total_patchsets", "avg_patchsets_per_change",
        "ci_rerun_verified_drops", "ci_rerun_recheck_msgs",
    ]
    for col in required:
        present = any(col in r for r in topic_rows)
        results.check(present, f"Column '{col}' exists in output")

    # ci_runs == ci_successes + ci_failures
    bad_runs = sum(
        1 for r in topic_rows
        if (r.get("ci_successes") or 0) + (r.get("ci_failures") or 0)
        != (r.get("ci_runs") or 0)
    )
    results.check(bad_runs == 0, f"ci_runs == ci_successes + ci_failures (mismatches: {bad_runs})")

    # ci_failure_rate in [0, 1]
    bad_rate = sum(
        1 for r in topic_rows
        if r.get("ci_failure_rate") is not None
        and not (0.0 <= r["ci_failure_rate"] <= 1.0)
    )
    results.check(bad_rate == 0, f"ci_failure_rate in [0,1] (violations: {bad_rate})")

    # total_patchsets >= 0
    bad_ps = sum(
        1 for r in topic_rows
        if r.get("total_patchsets") is not None and r["total_patchsets"] < 0
    )
    results.check(bad_ps == 0, f"All total_patchsets >= 0 (violations: {bad_ps})")


def validate_task5_high_effort(
    snapshot_rows: list[dict[str, Any]], results: TestResults,
) -> None:
    """Task #5: High review effort (early-window features)."""
    print(_cyan("\n  ── Task #5: High Review Effort (Early Window) ──"))

    required = [
        "topic_id", "cutoff_hours",
        "initial_change_count", "early_comment_count",
        "early_comment_velocity", "early_unique_reviewers",
        "early_patchset_count", "early_human_comment_ratio",
    ]
    for col in required:
        present = any(col in r for r in snapshot_rows)
        results.check(present, f"Column '{col}' exists in snapshot output")

    # early_comment_count >= 0
    bad_comments = sum(
        1 for r in snapshot_rows
        if r.get("early_comment_count") is not None and r["early_comment_count"] < 0
    )
    results.check(bad_comments == 0, f"All early_comment_count >= 0 (violations: {bad_comments})")

    # early_human_comment_ratio in [0, 1] when present
    bad_ratio = sum(
        1 for r in snapshot_rows
        if r.get("early_human_comment_ratio") is not None
        and not (0.0 <= r["early_human_comment_ratio"] <= 1.0)
    )
    results.check(bad_ratio == 0, f"early_human_comment_ratio in [0,1] (violations: {bad_ratio})")

    # early_patchset_count >= 0
    bad_ps = sum(
        1 for r in snapshot_rows
        if r.get("early_patchset_count") is not None and r["early_patchset_count"] < 0
    )
    results.check(bad_ps == 0, f"All early_patchset_count >= 0 (violations: {bad_ps})")


def validate_cross_script_consistency(
    topic_rows: list[dict[str, Any]],
    snapshot_rows: list[dict[str, Any]],
    results: TestResults,
) -> None:
    """Check that topics match between build_topic_dataset and snapshot."""
    print(_cyan("\n  ── Cross-Script Consistency ──"))

    topic_ids_main = {r["topic_id"] for r in topic_rows}
    topic_ids_snap = {r["topic_id"] for r in snapshot_rows}

    results.check(
        topic_ids_main == topic_ids_snap,
        f"Topic IDs match between main and snapshot datasets "
        f"(main={len(topic_ids_main)}, snap={len(topic_ids_snap)}, "
        f"diff={len(topic_ids_main ^ topic_ids_snap)})"
    )


def validate_general_quality(
    topic_rows: list[dict[str, Any]], results: TestResults,
) -> None:
    """General data quality checks."""
    print(_cyan("\n  ── General Quality ──"))

    results.check(len(topic_rows) > 0, "At least 1 topic row produced")
    results.check(
        len(topic_rows) >= MIN_TOPICS_EXPECTED,
        f"At least {MIN_TOPICS_EXPECTED} topics produced (actual: {len(topic_rows)})"
    )

    # No duplicate topic_ids
    topic_ids = [r["topic_id"] for r in topic_rows]
    results.check(
        len(topic_ids) == len(set(topic_ids)),
        f"No duplicate topic_ids (total={len(topic_ids)}, unique={len(set(topic_ids))})"
    )

    # created_at <= last_updated_at (when both present)
    bad_dates = sum(
        1 for r in topic_rows
        if r.get("created_at") and r.get("last_updated_at")
        and r["created_at"] > r["last_updated_at"]
    )
    results.check(bad_dates == 0, f"created_at <= last_updated_at (violations: {bad_dates})")

    # Contributor counts are consistent
    bad_people = sum(
        1 for r in topic_rows
        if (r.get("code_authors_count") or 0) > (r.get("people_involved_count") or 0)
    )
    results.check(bad_people == 0, f"code_authors_count <= people_involved_count (violations: {bad_people})")

    # top_author_changes <= n_changes
    bad_top = sum(
        1 for r in topic_rows
        if (r.get("top_author_changes") or 0) > (r.get("n_changes") or 0)
    )
    results.check(bad_top == 0, f"top_author_changes <= n_changes (violations: {bad_top})")


# ---------------------------------------------------------------------------
# Step 6: Print detailed report
# ---------------------------------------------------------------------------

def print_report(results: TestResults) -> None:
    """Print the final pass/fail report."""
    print(_bold("\n" + "═" * 70))
    print(_bold("  FINAL TEST REPORT"))
    print("═" * 70)

    print(f"\n  {_green('PASSED')}: {len(results.passed)}")
    for msg in results.passed:
        print(f"    ✓ {msg}")

    if results.warnings:
        print(f"\n  {_yellow('WARNINGS')}: {len(results.warnings)}")
        for msg in results.warnings:
            print(f"    ⚠ {msg}")

    if results.failed:
        print(f"\n  {_red('FAILED')}: {len(results.failed)}")
        for msg in results.failed:
            print(f"    ✗ {msg}")

    print("\n" + "═" * 70)
    if results.failed:
        print(_red(f"  RESULT: {len(results.failed)} / {results.total} checks FAILED"))
    else:
        print(_green(f"  RESULT: ALL {results.total} checks PASSED ✓"))
    print("═" * 70 + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Force UTF-8 output on Windows to avoid cp1252 encoding errors
    import io, os
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

    print(_bold("=" * 70))
    print(_bold("  Gerrit Topic Analytics Pipeline -- Small Sample Test"))
    print(_bold("=" * 70))

    results = TestResults()

    # Step 1: Extract sample
    sample = extract_sample()
    results.check(len(sample) > 0, f"Sample extracted ({len(sample)} changes)")

    # Step 2: Run build_topic_dataset
    topic_rows, btd_ok = run_build_topic_dataset()
    results.check(btd_ok, "build_topic_dataset executed without errors")

    # Step 3: Run snapshot features
    snapshot_rows, snap_ok = run_snapshot_features()
    results.check(snap_ok, "build_snapshot_features executed without errors")

    # Step 4: Run bottleneck features
    bottleneck_rows, bn_ok = run_bottleneck_features()
    results.check(bn_ok, "build_bottleneck_features executed without errors")

    # Step 5: Validate all prediction tasks
    print(_bold("\n═══ Step 5: Validating prediction task features ═══"))

    if topic_rows:
        validate_general_quality(topic_rows, results)
        validate_task1_review_delays(topic_rows, results)
        validate_task2_stall_risk(topic_rows, results)
        validate_task4_ci_churn(topic_rows, results)
    else:
        results.failed.append("Cannot validate tasks #1/#2/#4 — no topic rows produced")

    if bottleneck_rows:
        validate_task3_bottleneck(bottleneck_rows, results)
    else:
        results.failed.append("Cannot validate task #3 — no bottleneck rows produced")

    if snapshot_rows:
        validate_task5_high_effort(snapshot_rows, results)
    else:
        results.failed.append("Cannot validate task #5 — no snapshot rows produced")

    if topic_rows and snapshot_rows:
        validate_cross_script_consistency(topic_rows, snapshot_rows, results)

    # Step 6: Print detailed sample stats
    if topic_rows:
        print(_bold("\n═══ Sample Statistics ═══"))
        n = len(topic_rows)
        n_changes_list = [r["n_changes"] for r in topic_rows if r.get("n_changes")]
        outcomes = {}
        for r in topic_rows:
            o = r.get("outcome", "?")
            outcomes[o] = outcomes.get(o, 0) + 1
        print(f"  Topics: {n}")
        if n_changes_list:
            print(f"  Changes per topic: min={min(n_changes_list)}, "
                  f"median={statistics.median(n_changes_list):.0f}, "
                  f"max={max(n_changes_list)}")
        print(f"  Outcome breakdown: {outcomes}")

    # Step 7: Report
    print_report(results)

    # Cleanup
    if TEST_RAW_DIR.exists():
        shutil.rmtree(TEST_RAW_DIR)
        print(f"  Cleaned up {TEST_RAW_DIR}/")

    sys.exit(1 if results.failed else 0)


if __name__ == "__main__":
    main()
