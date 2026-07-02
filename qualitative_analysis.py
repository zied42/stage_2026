"""
Qualitative Analysis of Extreme Gerrit Topics
===============================================
Pipeline:
  1. Select top-100 topics per category (slowest, abandoned/stale, most rework, most effort)
  2. Query Gerrit REST API for qualitative data (subjects, projects, branches, files)
  3. Classify subjects (bugfix, feature, refactoring, CI/infra, docs, other)
  4. Generate enriched CSV + markdown report

Usage:
  python qualitative_analysis.py
"""

import os
import json
import time
import re
import urllib.parse
import urllib.request
import urllib.error
import ssl
import csv
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd
import numpy as np

# ─────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────
DATASET_PATH = "topics_dataset.csv"
CACHE_DIR = Path("raw_data/gerrit_topics_cache")
OUTPUT_CSV = "topics_enriched.csv"
OUTPUT_REPORT = "qualitative_analysis_report.md"
GERRIT_BASE = "https://review.opendev.org/changes/"
REQUEST_DELAY = 0.35  # seconds between API calls
TOP_N = 100

# ─────────────────────────────────────────────────────────────
# PHASE 1: TOPIC SELECTION
# ─────────────────────────────────────────────────────────────

def load_dataset():
    """Load the topics dataset and print basic info."""
    df = pd.read_csv(DATASET_PATH)
    print(f"[Phase 1] Loaded {len(df)} topics with {len(df.columns)} columns")
    return df


def select_extreme_topics(df):
    """
    Select top-100 topics for each of 4 categories.
    Returns a dict {category: DataFrame} and the set of unique topic_ids.
    """
    categories = {}

    # 1. Slowest (merged only, by time_to_completion_hours)
    merged = df[df["outcome"] == "merged"].copy()
    slowest = merged.nlargest(TOP_N, "time_to_completion_hours")
    categories["slowest"] = slowest
    print(f"  [slowest] {len(slowest)} topics, "
          f"min={slowest['time_to_completion_hours'].min():.1f}h, "
          f"max={slowest['time_to_completion_hours'].max():.1f}h")

    # 2. Abandoned/stale — top 100 by total_revisions (proxy for "most invested before dying")
    # (6115 abandoned+stale_open > 200, so we pick top 100 by total_revisions)
    non_merged = df[df["outcome"].isin(["abandoned", "stale_open"])].copy()
    abandoned_stale = non_merged.nlargest(TOP_N, "total_revisions")
    categories["abandoned_stale"] = abandoned_stale
    print(f"  [abandoned_stale] {len(abandoned_stale)} topics "
          f"(from {len(non_merged)} abandoned+stale_open), "
          f"total_revisions range: [{abandoned_stale['total_revisions'].min()}, "
          f"{abandoned_stale['total_revisions'].max()}]")

    # 3. Most rework — rank-based composite of ci_retries and total_revisions
    df_rework = df.copy()
    df_rework["rank_ci_retries"] = df_rework["ci_retries"].rank(ascending=False, method="min")
    df_rework["rank_total_revisions"] = df_rework["total_revisions"].rank(ascending=False, method="min")
    df_rework["rework_composite_rank"] = (
        df_rework["rank_ci_retries"] + df_rework["rank_total_revisions"]
    ) / 2.0
    most_rework = df_rework.nsmallest(TOP_N, "rework_composite_rank")
    categories["most_rework"] = most_rework
    print(f"  [most_rework] {len(most_rework)} topics, "
          f"ci_retries range: [{most_rework['ci_retries'].min()}, {most_rework['ci_retries'].max()}], "
          f"total_revisions range: [{most_rework['total_revisions'].min()}, "
          f"{most_rework['total_revisions'].max()}]")

    # 4. Most review effort — top 100 by total_messages
    most_effort = df.nlargest(TOP_N, "total_messages")
    categories["most_effort"] = most_effort
    print(f"  [most_effort] {len(most_effort)} topics, "
          f"total_messages range: [{most_effort['total_messages'].min()}, "
          f"{most_effort['total_messages'].max()}]")

    # Deduplicate
    all_topic_ids = set()
    for cat_name, cat_df in categories.items():
        all_topic_ids.update(cat_df["topic_id"].tolist())

    print(f"\n  Total unique topic IDs across all categories: {len(all_topic_ids)}")

    # Build category membership map
    topic_categories = defaultdict(set)
    for cat_name, cat_df in categories.items():
        for tid in cat_df["topic_id"]:
            topic_categories[tid].add(cat_name)

    return categories, all_topic_ids, topic_categories


# ─────────────────────────────────────────────────────────────
# PHASE 2: GERRIT API ENRICHMENT
# ─────────────────────────────────────────────────────────────

def build_gerrit_url(topic_id):
    """Build the Gerrit REST API URL for a given topic."""
    encoded = urllib.parse.quote(topic_id, safe="")
    return (
        f"{GERRIT_BASE}?q=topic:{encoded}"
        f"&o=CURRENT_REVISION&o=CURRENT_FILES&o=CURRENT_COMMIT"
    )


def fetch_gerrit_topic(topic_id, cache_dir):
    """
    Fetch Gerrit changes for a topic. Uses cache if available.
    Returns (list_of_changes, was_cached, error_message).
    """
    # Check cache
    cache_file = cache_dir / f"{urllib.parse.quote(topic_id, safe='')}.json"
    if cache_file.exists():
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data, True, None
        except (json.JSONDecodeError, IOError):
            pass  # re-fetch

    # Fetch from API
    url = build_gerrit_url(topic_id)

    # Create SSL context that doesn't verify (some corporate envs need this)
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    max_retries = 3
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                raw = resp.read().decode("utf-8")

            # Gerrit prefixes JSON with )]}' — strip it
            if raw.startswith(")]}'"):
                raw = raw[4:].lstrip()

            data = json.loads(raw)

            # Cache the result
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f)

            return data, False, None

        except urllib.error.HTTPError as e:
            if e.code == 429 or e.code >= 500:
                wait = (attempt + 1) * 2
                print(f"    HTTP {e.code} for '{topic_id}', retrying in {wait}s...")
                time.sleep(wait)
                continue
            return [], False, f"HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            if attempt < max_retries - 1:
                time.sleep((attempt + 1) * 2)
                continue
            return [], False, str(e)
        except json.JSONDecodeError as e:
            return [], False, f"JSON parse error: {e}"

    return [], False, "max retries exceeded"


def parse_gerrit_changes(changes):
    """
    Parse a list of Gerrit change objects into structured data.
    Returns a dict with: subjects, projects, branches, insertions, deletions,
                         files_count, files_list
    """
    subjects = []
    projects = set()
    branches = set()
    total_insertions = 0
    total_deletions = 0
    all_files = set()

    for change in changes:
        # Subject
        subjects.append(change.get("subject", ""))

        # Project & branch
        projects.add(change.get("project", "unknown"))
        branches.add(change.get("branch", "unknown"))

        # Insertions / deletions
        total_insertions += change.get("insertions", 0)
        total_deletions += change.get("deletions", 0)

        # Files from current revision
        revisions = change.get("revisions", {})
        for rev_id, rev_data in revisions.items():
            files = rev_data.get("files", {})
            all_files.update(files.keys())

            # Also grab commit message subject as backup
            commit = rev_data.get("commit", {})
            if commit and not subjects[-1]:
                subjects[-1] = commit.get("subject", "")

    return {
        "subjects": subjects,
        "projects": sorted(projects),
        "branches": sorted(branches),
        "insertions": total_insertions,
        "deletions": total_deletions,
        "files_count": len(all_files),
        "files_list": sorted(all_files)[:50],  # cap to avoid huge lists
        "n_changes_api": len(changes),
    }


def enrich_topics_from_gerrit(topic_ids):
    """
    Fetch and parse Gerrit data for all topic IDs.
    Returns a dict {topic_id: parsed_data_dict}.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    enriched = {}
    errors = {}
    cached_count = 0
    fetched_count = 0

    total = len(topic_ids)
    sorted_ids = sorted(topic_ids)

    print(f"\n[Phase 2] Enriching {total} unique topics from Gerrit API...")

    for i, tid in enumerate(sorted_ids):
        if (i + 1) % 25 == 0 or i == 0:
            print(f"  Progress: {i+1}/{total} "
                  f"(cached: {cached_count}, fetched: {fetched_count}, errors: {len(errors)})")

        changes, was_cached, error = fetch_gerrit_topic(tid, CACHE_DIR)

        if error:
            errors[tid] = error
            enriched[tid] = {
                "subjects": [], "projects": [], "branches": [],
                "insertions": 0, "deletions": 0, "files_count": 0,
                "files_list": [], "n_changes_api": 0, "api_error": error,
            }
        else:
            parsed = parse_gerrit_changes(changes)
            parsed["api_error"] = None
            enriched[tid] = parsed
            if was_cached:
                cached_count += 1
            else:
                fetched_count += 1
                time.sleep(REQUEST_DELAY)

    print(f"  Done: {cached_count} cached, {fetched_count} fetched, {len(errors)} errors")
    if errors:
        print(f"  Errors: {list(errors.items())[:5]}...")

    return enriched


# ─────────────────────────────────────────────────────────────
# PHASE 3: SUBJECT CLASSIFICATION
# ─────────────────────────────────────────────────────────────

CATEGORY_KEYWORDS = {
    "release_mgmt": [
        r"update \.gitreview", r"update tox_constraints", r"update upper_constraints",
        r"\bgitreview\b", r"\bstable/", r"\bunmaintained/",
        r"\bbump sha", r"\bbump version", r"update master for stable",
        r"\brelease\b.*\bprep", r"\bprepare\b.*\brelease",
        r"\bcreate.*branch\b", r"\bbranch.*creat",
        r"^bump\b", r"\btag\b.*\brelease\b",
    ],
    "translation": [
        r"\btranslat", r"\bzanata\b", r"\bweblate\b", r"\bi18n\b", r"\bl10n\b",
    ],
    "upgrade_migration": [
        r"\bupgrad\b", r"\bmigrat\b", r"\breplace\b.*\burl", r"\burl\b.*\breplace",
        r"\bsqlalchemy\b", r"\beventlet\b", r"\bpython\s*3\b", r"\bpy3\b",
        r"\bcentos\b", r"\bubuntu\b", r"\bnoble\b", r"\bjammy\b",
        r"\bmod_wsgi\b", r"\budev\b",
    ],
    "bugfix": [
        r"\bfix\b", r"\bbug\b", r"\bpatch\b", r"\bresolve[sd]?\b",
        r"\bissue\b", r"\berror\b", r"\bcrash\b", r"\bregression\b",
        r"\bworkaround\b", r"\bhotfix\b",
    ],
    "feature": [
        r"\badd\b", r"\bimplement\b", r"\bsupport\b", r"\benable\b",
        r"\bintroduce\b", r"\bnew\b", r"\bcreate\b", r"\ballow\b",
    ],
    "refactoring": [
        r"\brefactor\b", r"\bcleanup\b", r"\bclean.?up\b", r"\breorganize\b",
        r"\bsimplify\b", r"\bmove\b", r"\brename\b", r"\bremove\b",
        r"\bdelete\b", r"\bdeprecate\b", r"\bdrop\b",
    ],
    "ci_infra": [
        r"\bci\b", r"\bgate\b", r"\bzuul\b", r"\btest\b", r"\btox\b",
        r"\brequirement\b", r"\bpin\b", r"\bjob\b", r"\bplaybook\b",
        r"\bansible\b", r"\bdevstack\b", r"\btempest\b", r"\bhacking\b",
    ],
    "docs": [
        r"\bdoc\b", r"\bdocs\b", r"\breadme\b", r"\brelease.note\b",
        r"\breno\b", r"\breleasenote\b", r"\bcontributor\b.*\bdocument",
    ],
}


def classify_subject(subject):
    """Classify a single commit subject into a category."""
    s = subject.lower().strip()
    for category, patterns in CATEGORY_KEYWORDS.items():
        for pattern in patterns:
            if re.search(pattern, s):
                return category
    return "other"


def classify_topic_subjects(subjects):
    """
    Classify all subjects for a topic.
    Returns the dominant category and the full distribution.
    """
    if not subjects:
        return "unknown", {}
    cats = [classify_subject(s) for s in subjects]
    dist = Counter(cats)
    dominant = dist.most_common(1)[0][0]
    return dominant, dict(dist)


# ─────────────────────────────────────────────────────────────
# PHASE 4: BUILD ENRICHED DATASET + REPORT
# ─────────────────────────────────────────────────────────────

def build_enriched_dataframe(df, categories, topic_categories, enriched_data):
    """
    Build the enriched DataFrame combining original metrics with API data.
    Only includes the selected extreme topics.
    """
    # Get all unique topic IDs from categories
    all_ids = set()
    for cat_df in categories.values():
        all_ids.update(cat_df["topic_id"].tolist())

    # Filter original df to selected topics
    selected = df[df["topic_id"].isin(all_ids)].copy()

    # Add category membership
    selected["categories"] = selected["topic_id"].apply(
        lambda tid: "|".join(sorted(topic_categories.get(tid, set())))
    )

    # Add Gerrit enrichment columns
    selected["gerrit_subjects"] = selected["topic_id"].apply(
        lambda tid: " ||| ".join(enriched_data.get(tid, {}).get("subjects", []))
    )
    selected["gerrit_projects"] = selected["topic_id"].apply(
        lambda tid: " | ".join(enriched_data.get(tid, {}).get("projects", []))
    )
    selected["gerrit_branches"] = selected["topic_id"].apply(
        lambda tid: " | ".join(enriched_data.get(tid, {}).get("branches", []))
    )
    selected["gerrit_insertions"] = selected["topic_id"].apply(
        lambda tid: enriched_data.get(tid, {}).get("insertions", 0)
    )
    selected["gerrit_deletions"] = selected["topic_id"].apply(
        lambda tid: enriched_data.get(tid, {}).get("deletions", 0)
    )
    selected["gerrit_files_count"] = selected["topic_id"].apply(
        lambda tid: enriched_data.get(tid, {}).get("files_count", 0)
    )
    selected["is_multi_project"] = selected["topic_id"].apply(
        lambda tid: len(enriched_data.get(tid, {}).get("projects", [])) > 1
    )
    selected["api_error"] = selected["topic_id"].apply(
        lambda tid: enriched_data.get(tid, {}).get("api_error", None)
    )

    # Subject classification
    def _classify(tid):
        subjects = enriched_data.get(tid, {}).get("subjects", [])
        dominant, _ = classify_topic_subjects(subjects)
        return dominant

    selected["subject_category"] = selected["topic_id"].apply(_classify)

    return selected


def analyze_category(cat_name, cat_df, enriched_data, topic_categories):
    """
    Produce analysis for a single category.
    Returns a dict with analysis results.
    """
    topic_ids = cat_df["topic_id"].tolist()

    # Project frequency
    all_projects = []
    for tid in topic_ids:
        projs = enriched_data.get(tid, {}).get("projects", [])
        all_projects.extend(projs)
    project_counts = Counter(all_projects).most_common(15)

    # Subject classification
    all_categories = []
    for tid in topic_ids:
        subjects = enriched_data.get(tid, {}).get("subjects", [])
        dominant, _ = classify_topic_subjects(subjects)
        all_categories.append(dominant)
    cat_dist = Counter(all_categories)
    total_classified = sum(cat_dist.values())

    # Multi-project %
    multi_proj = sum(
        1 for tid in topic_ids
        if len(enriched_data.get(tid, {}).get("projects", [])) > 1
    )
    multi_proj_pct = (multi_proj / len(topic_ids) * 100) if topic_ids else 0

    # Churn stats
    churns = []
    for tid in topic_ids:
        ins = enriched_data.get(tid, {}).get("insertions", 0)
        dels = enriched_data.get(tid, {}).get("deletions", 0)
        churns.append(ins + dels)
    avg_churn = np.mean(churns) if churns else 0
    median_churn = np.median(churns) if churns else 0

    # API errors
    errors = sum(
        1 for tid in topic_ids
        if enriched_data.get(tid, {}).get("api_error") is not None
    )

    # Cross-category overlap
    overlaps = Counter()
    for tid in topic_ids:
        other_cats = topic_categories.get(tid, set()) - {cat_name}
        for oc in other_cats:
            overlaps[oc] += 1

    return {
        "n_topics": len(topic_ids),
        "project_counts": project_counts,
        "subject_categories": cat_dist,
        "total_classified": total_classified,
        "multi_project_pct": multi_proj_pct,
        "multi_project_count": multi_proj,
        "avg_churn": avg_churn,
        "median_churn": median_churn,
        "api_errors": errors,
        "overlaps": overlaps,
    }


def generate_report(categories, enriched_data, topic_categories, selected_df):
    """Generate the full markdown report."""
    lines = []
    lines.append("# Qualitative Analysis of Extreme Gerrit Topics\n")
    lines.append("## Overview\n")
    lines.append(f"This report analyzes the **extreme topics** from the OpenStack Gerrit ")
    lines.append(f"code review dataset ({len(selected_df)} unique topics selected across 4 categories).\n")
    lines.append(f"For each category, we selected the top {TOP_N} topics and enriched them ")
    lines.append(f"with qualitative data from the Gerrit REST API (subjects, projects, branches, ")
    lines.append(f"file changes).\n\n")

    # Summary table
    lines.append("### Category Summary\n")
    lines.append("| Category | Selection Criteria | Count |")
    lines.append("|---|---|---|")
    lines.append(f"| Slowest | Top {TOP_N} by `time_to_completion_hours` (merged only) | {len(categories['slowest'])} |")
    lines.append(f"| Abandoned/Stale | Top {TOP_N} by `total_revisions` among abandoned+stale_open | {len(categories['abandoned_stale'])} |")
    lines.append(f"| Most Rework | Top {TOP_N} by composite rank (ci_retries + total_revisions) | {len(categories['most_rework'])} |")
    lines.append(f"| Most Review Effort | Top {TOP_N} by `total_messages` | {len(categories['most_effort'])} |")
    lines.append("")

    # Overlap matrix
    lines.append("### Category Overlap\n")
    lines.append("Some topics appear in multiple categories:\n")
    cat_names = ["slowest", "abandoned_stale", "most_rework", "most_effort"]
    for cn in cat_names:
        tids = set(categories[cn]["topic_id"])
        overlaps = []
        for cn2 in cat_names:
            if cn2 != cn:
                tids2 = set(categories[cn2]["topic_id"])
                common = len(tids & tids2)
                if common > 0:
                    overlaps.append(f"{cn2} ({common})")
        if overlaps:
            lines.append(f"- **{cn}** overlaps with: {', '.join(overlaps)}")
    lines.append("")

    # Per-category analysis
    lines.append("---\n")

    cat_labels = {
        "slowest": "Slowest Topics (Longest Time to Completion)",
        "abandoned_stale": "Abandoned/Stale Topics (Most Invested Before Dying)",
        "most_rework": "Most Rework Topics (Highest CI Retries + Revisions)",
        "most_effort": "Most Review Effort Topics (Highest Message Count)",
    }

    cat_descriptions = {
        "slowest": "merged topics with the longest `time_to_completion_hours`",
        "abandoned_stale": "abandoned or stale topics with the most `total_revisions` (proxy for investment before death)",
        "most_rework": "topics with the highest composite rank across `ci_retries` and `total_revisions`",
        "most_effort": "topics with the highest `total_messages` count",
    }

    for cat_name in cat_names:
        cat_df = categories[cat_name]
        analysis = analyze_category(cat_name, cat_df, enriched_data, topic_categories)

        lines.append(f"## {cat_labels[cat_name]}\n")
        lines.append(f"Selection: Top {TOP_N} {cat_descriptions[cat_name]}.\n")

        if analysis["api_errors"] > 0:
            lines.append(f"> **Note**: {analysis['api_errors']}/{analysis['n_topics']} topics "
                         f"could not be enriched via the Gerrit API.\n")

        # Key metrics
        lines.append("### Key Metrics\n")
        lines.append(f"- **Multi-project topics**: {analysis['multi_project_count']}/{analysis['n_topics']} "
                      f"({analysis['multi_project_pct']:.1f}%)")
        lines.append(f"- **Average code churn** (insertions+deletions): {analysis['avg_churn']:,.0f}")
        lines.append(f"- **Median code churn**: {analysis['median_churn']:,.0f}")
        lines.append("")

        # Top projects
        lines.append("### Top Projects\n")
        lines.append("| Project | Occurrences | % of Topics |")
        lines.append("|---|---|---|")
        for proj, count in analysis["project_counts"][:10]:
            pct = count / analysis["n_topics"] * 100
            lines.append(f"| `{proj}` | {count} | {pct:.1f}% |")
        lines.append("")

        # Subject classification
        lines.append("### Subject Classification\n")
        lines.append("| Category | Count | % |")
        lines.append("|---|---|---|")
        for scat, scount in sorted(analysis["subject_categories"].items(),
                                    key=lambda x: -x[1]):
            pct = scount / analysis["total_classified"] * 100 if analysis["total_classified"] else 0
            lines.append(f"| {scat} | {scount} | {pct:.1f}% |")
        lines.append("")

        # Observations
        lines.append("### Observations\n")
        obs = generate_observations(cat_name, analysis, cat_df)
        for o in obs:
            lines.append(f"- {o}")
        lines.append("")
        lines.append("---\n")

    # Cross-category insights
    lines.append("## Cross-Category Insights\n")
    cross = generate_cross_category_insights(categories, enriched_data, topic_categories)
    for c in cross:
        lines.append(f"- {c}")
    lines.append("")

    # Methodology
    lines.append("---\n")
    lines.append("## Methodology\n")
    lines.append("- **Dataset**: `topics_dataset.csv` (89,266 topics)\n")
    lines.append("- **API**: Gerrit REST API at `review.opendev.org` "
                  "(public, no authentication required)\n")
    lines.append("- **Subject classification**: Keyword-based heuristic matching against "
                  "commit subjects. Categories (in priority order): release_mgmt, translation, "
                  "upgrade_migration, bugfix, feature, refactoring, ci_infra, docs, other.\n")
    lines.append("- **Rework composite**: Average of independent ranks on `ci_retries` and "
                  "`total_revisions` (lower composite rank = more rework).\n")
    lines.append("- **Abandoned/stale selection**: Since `last_activity_gap_days` was found to be "
                  "a proxy for topic age (92% correlation), we used `total_revisions` as a proxy "
                  "for 'most invested before dying'.\n")

    return "\n".join(lines)


def generate_observations(cat_name, analysis, cat_df):
    """Generate narrative observations for a category."""
    obs = []
    n = analysis["n_topics"]

    # Multi-project observation
    mp = analysis["multi_project_pct"]
    if mp > 50:
        obs.append(f"A majority ({mp:.0f}%) of these topics span multiple projects, "
                   f"suggesting large cross-cutting changes.")
    elif mp > 20:
        obs.append(f"A significant minority ({mp:.0f}%) of topics involve multiple projects.")
    else:
        obs.append(f"Most topics ({100-mp:.0f}%) are single-project, with only {mp:.0f}% "
                   f"spanning multiple repositories.")

    # Top project observation
    if analysis["project_counts"]:
        top_proj, top_count = analysis["project_counts"][0]
        top_pct = top_count / n * 100
        obs.append(f"The most frequent project is `{top_proj}` "
                   f"(appearing in {top_pct:.0f}% of topics).")

    # Subject categories
    sc = analysis["subject_categories"]
    total_sc = analysis["total_classified"]
    if total_sc > 0:
        dominant_cat = max(sc, key=sc.get)
        dominant_pct = sc[dominant_cat] / total_sc * 100
        obs.append(f"Subjects are predominantly classified as **{dominant_cat}** ({dominant_pct:.0f}%).")

        # Feature vs bugfix comparison
        feat = sc.get("feature", 0)
        bugf = sc.get("bugfix", 0)
        if feat > 0 and bugf > 0:
            obs.append(f"Feature-related subjects ({feat/total_sc*100:.0f}%) vs. "
                       f"bugfix-related ({bugf/total_sc*100:.0f}%).")

    # Churn observation
    if analysis["avg_churn"] > 1000:
        obs.append(f"Average code churn is very high ({analysis['avg_churn']:,.0f} lines), "
                   f"indicating large, sweeping changes.")
    elif analysis["avg_churn"] > 100:
        obs.append(f"Moderate average code churn ({analysis['avg_churn']:,.0f} lines).")

    # Category-specific observations
    if cat_name == "slowest":
        min_days = cat_df["time_to_completion_hours"].min() / 24
        max_days = cat_df["time_to_completion_hours"].max() / 24
        median_days = cat_df["time_to_completion_hours"].median() / 24
        obs.append(f"Completion times range from {min_days:.0f} to {max_days:.0f} days "
                   f"(median: {median_days:.0f} days).")

    if cat_name == "abandoned_stale":
        outcome_dist = cat_df["outcome"].value_counts()
        for outcome, count in outcome_dist.items():
            obs.append(f"{count} topics have outcome=`{outcome}`.")

    if cat_name == "most_rework":
        med_ci = cat_df["ci_retries"].median()
        med_rev = cat_df["total_revisions"].median()
        obs.append(f"Median CI retries: {med_ci:.0f}, median total revisions: {med_rev:.0f}.")

    if cat_name == "most_effort":
        med_msg = cat_df["total_messages"].median()
        obs.append(f"Median message count: {med_msg:.0f} messages per topic.")

    return obs


def generate_cross_category_insights(categories, enriched_data, topic_categories):
    """Generate cross-cutting insights across all categories."""
    insights = []

    # Find topics in multiple categories
    multi_cat_topics = {
        tid: cats for tid, cats in topic_categories.items() if len(cats) > 1
    }
    if multi_cat_topics:
        insights.append(f"**{len(multi_cat_topics)}** topics appear in multiple categories, "
                        f"suggesting correlation between slowness, rework, and review effort.")

        # Most-overlapping topic
        max_cats_tid = max(multi_cat_topics, key=lambda t: len(multi_cat_topics[t]))
        max_cats = multi_cat_topics[max_cats_tid]
        insights.append(f"Topic `{max_cats_tid}` appears in {len(max_cats)} categories: "
                        f"{', '.join(sorted(max_cats))}.")

    # Global project frequency across all categories
    all_projects = Counter()
    for cat_df in categories.values():
        for tid in cat_df["topic_id"]:
            for p in enriched_data.get(tid, {}).get("projects", []):
                all_projects[p] += 1
    if all_projects:
        top3 = all_projects.most_common(3)
        proj_str = ", ".join(f"`{p}` ({c})" for p, c in top3)
        insights.append(f"Most frequently involved projects across all categories: {proj_str}.")

    # Subject category across all
    all_subj_cats = Counter()
    all_topic_ids = set()
    for cat_df in categories.values():
        all_topic_ids.update(cat_df["topic_id"].tolist())
    for tid in all_topic_ids:
        subjects = enriched_data.get(tid, {}).get("subjects", [])
        dominant, _ = classify_topic_subjects(subjects)
        all_subj_cats[dominant] += 1
    if all_subj_cats:
        total = sum(all_subj_cats.values())
        dist_str = ", ".join(f"{c}: {n}/{total} ({n/total*100:.0f}%)"
                             for c, n in all_subj_cats.most_common())
        insights.append(f"Overall subject classification: {dist_str}.")

    return insights


# ─────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("QUALITATIVE ANALYSIS OF EXTREME GERRIT TOPICS")
    print("=" * 60)

    # Phase 1
    df = load_dataset()
    categories, all_topic_ids, topic_categories = select_extreme_topics(df)

    # Phase 2
    enriched_data = enrich_topics_from_gerrit(all_topic_ids)

    # Phase 3
    print(f"\n[Phase 3] Classifying subjects...")
    for tid in all_topic_ids:
        subjects = enriched_data.get(tid, {}).get("subjects", [])
        dominant, dist = classify_topic_subjects(subjects)
        enriched_data[tid]["dominant_category"] = dominant
        enriched_data[tid]["category_distribution"] = dist
    print(f"  Classified subjects for {len(all_topic_ids)} topics")

    # Phase 4
    print(f"\n[Phase 4] Building enriched dataset and report...")
    selected_df = build_enriched_dataframe(df, categories, topic_categories, enriched_data)

    # Save enriched CSV
    selected_df.to_csv(OUTPUT_CSV, index=False)
    print(f"  Saved enriched dataset: {OUTPUT_CSV} ({len(selected_df)} rows)")

    # Generate report
    report = generate_report(categories, enriched_data, topic_categories, selected_df)
    with open(OUTPUT_REPORT, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  Saved report: {OUTPUT_REPORT}")

    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    main()
