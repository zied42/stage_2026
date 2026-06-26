# Mining Instructions — Gerrit Topic Analytics Pipeline

Complete step-by-step guide to activate the environment, run all scripts,
and mine data for the 5 internship prediction tasks.

---

## Prerequisites

- **Python 3.11+** (this project uses 3.14)
- **Internet access** to `review.opendev.org` (public, no auth required)
- Virtual environment already created at `venv/`

---

## Step 0: Activate the Virtual Environment

```powershell
# Windows (PowerShell)
cd C:\Users\ziedd\PycharmProjects\stage_2026
venv\Scripts\activate
```

```bash
# Linux / macOS
cd /path/to/stage_2026
source venv/bin/activate
```

Verify:
```bash
pip list
# Should show: requests, pyarrow, ijson (at minimum)
```

---

## Step 1: Collect Raw Changes from Gerrit

### Quick test (2 pages only — ~1 minute)
```bash
python collect_changes.py --project openstack/nova --since 2024-01-01 --max-pages 2
```

### Full collection for a single project
```bash
python collect_changes.py --project openstack/nova --since 2023-01-01
```

### Full collection for multiple projects (recommended for the internship)
```bash
python collect_changes.py \
  --project openstack/nova \
  --project openstack/neutron \
  --project openstack/cinder \
  --project openstack/keystone \
  --since 2023-01-01
```

### Resume an interrupted collection
Just re-run the same command — it picks up from the checkpoint automatically.

### Start over from scratch
```bash
python collect_changes.py --project openstack/nova --since 2023-01-01 --fresh
```

**Output:** `raw_data/page_0000.json`, `page_0001.json`, ...

> **Note:** The current `raw_data/` already contains ~15 GB of collected data
> (72 page files = ~44,000 changes). You can skip this step if you want to
> use the existing data.

---

## Step 2: Build the Topic-Level Dataset

```bash
python build_topic_dataset.py
```

**Output:**
- `topics_dataset.csv` — topic-level metrics (all 35 columns)
- `topics_dataset.parquet` — same data, Parquet format (Snappy-compressed)

This script:
- Loads all `page_*.json` files from `raw_data/`
- Groups changes by their `topic` field
- Computes features for **all 5 prediction tasks**
- Prints a feature quality verification report

---

## Step 3: Extract Advanced Features

### 3a. Fetch Relation Chains (network required)

```bash
python extract_advanced_features.py fetch-relations
```

This fetches the `/related` endpoint for every change to get dependency
chain data. **This is slow** (one API call per change with 0.5s delay).
It is resumable — cached files are skipped on re-run.

**Output:** `raw_data_relations/*.json` (one file per change)

### 3b. Build Bottleneck Features (no network)

```bash
python extract_advanced_features.py build-bottleneck-features
```

**Output:** `change_bottleneck_features.csv` — one row per change with:
- `in_degree_in_chain` — how many changes depend on this one
- `chain_length` — total changes in the relation chain
- `is_chain_root` — whether this is the base of the chain
- `num_blocked_children` — non-merged changes stacked on top

### 3c. Build Snapshot / Early-Window Features (no network)

```bash
python extract_advanced_features.py build-snapshot-features --cutoff-hours 48
```

**Output:** `topic_snapshot_features.csv` — one row per topic with features
computed using **only the first 48 hours** of activity (leakage-safe for
early prediction).

You can vary the cutoff:
```bash
# 24-hour window
python extract_advanced_features.py build-snapshot-features --cutoff-hours 24

# 72-hour window
python extract_advanced_features.py build-snapshot-features --cutoff-hours 72
```

---

## Step 4: Run the Small-Sample Test (optional verification)

```bash
python test_pipeline_small.py
```

This extracts 200 changes from your existing data, runs the full pipeline
on them, and validates all 60 checks across the 5 prediction tasks.

---

## Feature Coverage by Prediction Task

| Task | Features | Source File |
|---|---|---|
| **#1 Long review delays** | `first_review_delay_hours`, `avg_review_delay_hours`, `avg_active_days`, `last_activity_gap_days` | `topics_dataset.csv` |
| **#2 Stall/abandon risk** | `outcome` (stale_open/abandoned/mixed), `last_activity_gap_days`, `n_open`, `n_abandoned` | `topics_dataset.csv` |
| **#3 Coordination bottleneck** | `in_degree_in_chain`, `chain_length`, `is_chain_root`, `num_blocked_children` | `change_bottleneck_features.csv` |
| **#4 CI reruns/revisions** | `ci_runs`, `ci_failures`, `ci_failure_rate`, `ci_retries`, `total_patchsets`, `avg_patchsets_per_change` | `topics_dataset.csv` |
| **#5 High review effort** | `early_comment_count`, `early_comment_velocity`, `early_unique_reviewers`, `early_patchset_count`, `early_human_comment_ratio` | `topic_snapshot_features.csv` |

---

## Full Pipeline Summary (copy-paste ready)

```powershell
# Activate environment
venv\Scripts\activate

# 1. Collect data (skip if raw_data/ already populated)
python collect_changes.py --project openstack/nova --project openstack/neutron --project openstack/cinder --project openstack/keystone --since 2023-01-01

# 2. Build topic dataset
python build_topic_dataset.py

# 3. Fetch relation chains (slow — one API call per change)
python extract_advanced_features.py fetch-relations

# 4. Build bottleneck features
python extract_advanced_features.py build-bottleneck-features

# 5. Build snapshot features (48h window)
python extract_advanced_features.py build-snapshot-features --cutoff-hours 48

# 6. (Optional) Verify everything works
python test_pipeline_small.py
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `FileNotFoundError: No page_*.json files` | Run `collect_changes.py` first |
| HTTP 429 / connection errors | Increase `REQUEST_DELAY` in `collect_changes.py` |
| Empty `topics_dataset.*` | Normal if no changes have a `topic` field |
| Parquet write fails | `pip install pyarrow` |
| Checkpoint mismatch error | Use `--fresh` or change `--output-dir` |
| Unicode errors on Windows | Use `python -X utf8` flag |
