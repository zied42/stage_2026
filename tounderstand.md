# OpenStack Gerrit Topic Analytics & Prediction Pipeline

## What is this, in plain English?

This is a data pipeline that downloads code-review history from OpenStack's Gerrit
server, organizes it, and turns it into spreadsheets (CSV files) that can be used to
train machine learning models. Those models try to answer questions like:

- "Is this code review going to take forever?"
- "Is this code review going to get abandoned?"
- "Which specific change is the one blocking everyone else?"
- "Is this going to need a ton of back-and-forth fixes before it's mergeable?"
- "Can we tell any of this within the first 2 days, instead of waiting weeks?"

If you have never touched Gerrit before, the next section explains the basic
vocabulary. If you already know what a "change" and a "+2 vote" are, skip ahead to
**Pipeline Architecture**.

---

## Background: Gerrit vocabulary, explained simply

Gerrit is a code review tool. Before code gets merged into a real project (like
OpenStack), it has to go through Gerrit and get reviewed and approved.

- **Change**: One proposed code edit, like a pull request on GitHub. It has an owner
  (the person who wrote it) and goes through review.
- **Patchset / Revision**: Every time the author updates their code in response to
  feedback, that's a new patchset. A change can have 1 patchset (perfect first try) or
  20 (lots of back-and-forth).
- **Topic**: A label that groups several related changes together. Big features
  usually need multiple changes (e.g. one for the backend, one for the API, one for
  tests), and they all share the same topic name so people can track them as one unit.
  This pipeline mostly analyzes data at the **topic** level, not the individual change
  level, because that's the unit of work people actually care about.
- **Vote**: Reviewers leave a score on a change. In Gerrit, the scores that matter are
  **+2** (approved, ready to merge) and **-2** (blocked, do not merge). +1 and -1 exist
  too, but they're just opinions — they don't actually gate anything.
- **CI bot**: An automated system (OpenStack uses one called "Zuul") that runs tests on
  every patchset automatically and leaves a comment with the result. These are not
  human reviewers, so this pipeline is careful to separate "a bot commented" from "a
  human commented."
- **Recheck**: When CI fails, a human can comment "recheck" to ask CI to try again
  (maybe it was a flaky test, not a real bug). This is one signal of wasted effort /
  friction in a review.
- **Relation chain / stacked changes**: Sometimes change B depends on change A (B can't
  merge until A merges). If five changes are stacked like this, and the bottom one (A)
  is stuck, all five are stuck. This pipeline maps out those stacks to find the change
  that's actually causing the holdup.
- **Outcome states**: A change ends up **merged** (accepted), **abandoned** (rejected
  or given up on), or stays **open** (still in progress). A whole *topic* can be a mix
  of these.

---

## What internship problem does this solve?

This pipeline was built for the internship: *"Intelligent Topic Analytics and
Prediction for Gerrit Code Review."* That internship has three parts:

1. **Temporal trends** — how do review delays, patchset growth, staleness, and CI
   failures change over time?
2. **Dependency structure** — which changes in a stack are blocking other changes?
3. **Prediction + AI recommendations** — can we predict risk early, and can an LLM
   explain the risk and suggest what to do about it?

This pipeline currently covers parts 1 (partially — full-lifetime totals plus one
early-window snapshot, not yet a full week-by-week trend) and 2 (fully), and builds the
raw feature tables that part 3's prediction models will be trained on. The LLM
recommendation layer and the React/Node.js dashboard integration are separate, later
pieces of the internship — not part of what this pipeline produces.

### The 5 prediction tasks this data is built for

| # | Task | Plain-English question |
|---|------|------------------------|
| 1 | Long Review Delays | Will reviewers take a long time to even look at this? |
| 2 | Stall & Abandon Risk | Will this topic merge, get abandoned, or just rot (90+ days idle)? |
| 3 | Coordination Bottleneck Detection | Which exact change is blocking the others stacked on top of it? |
| 4 | CI Churn & Patch Revisions | Will this need excessive CI reruns or rewrites before it's mergeable? |
| 5 | High Review Effort (Early Warning) | Can we predict the above using only the first 48 hours of activity? |

---

## Pipeline Architecture

The pipeline runs as four scripts, in this order:

1. **`collect_changes.py`** — Downloads raw change data from the public Gerrit API at
   `review.opendev.org`, for whichever OpenStack projects you specify (nova, neutron,
   cinder, etc.), going back to a chosen start date. It saves everything as local JSON
   files. It can resume if interrupted, and it deliberately pauses between requests so
   it doesn't get rate-limited by the server.

2. **`build_topic_dataset.py`** — Reads the raw JSON, groups changes by their `topic`
   field, and computes full-lifetime statistics for each topic (review delays, CI
   stats, contributor counts, final outcome). Produces `topics_dataset.csv`.

3. **`extract_advanced_features.py`** — Has two independent jobs, both also reading
   from the raw JSON collected in step 1:
   - `fetch-relations` + `build-bottleneck-features`: calls Gerrit's `/related`
     endpoint for every change to discover stacked/dependent changes, then computes
     which changes are blocking others. Produces `change_bottleneck_features.csv`.
   - `build-snapshot-features --cutoff-hours N`: re-reads the raw data but only counts
     activity that happened before hour N of the topic's life. Produces
     `topic_snapshot_features.csv`.

4. **`test_pipeline_small.py`** — A dry run on a small sample (~200 changes) that
   checks the whole pipeline works end-to-end, no values are broken (e.g. negative
   counts), and all expected columns are present. Doesn't touch production data.

### Why three separate output files instead of one big table?

Because of a machine learning problem called **label leakage**. If you tried to
predict "will this topic stall?" using a feature like "total number of comments ever
posted," your model would be cheating — that total only exists *after* the topic is
already finished. To predict things early and honestly, you need a clean split:

- `topics_dataset.csv` = the final answers (full lifetime outcomes). Use this as your
  labels (`y`), never as input features for early prediction.
- `topic_snapshot_features.csv` = only what was knowable in the first 48 hours. Use
  this as your input features (`X`) for early prediction (Task #5). Join the two on
  `topic_id` to train a model.
- `change_bottleneck_features.csv` = a completely different unit of analysis (one row
  per individual change, not per topic), because "is this one change blocking others"
  is a property of a single change inside a dependency graph, not something you can
  meaningfully average across a whole topic.

---

## Quick Start

```bash
# 1. Set up environment
venv\Scripts\activate
pip install -r requirements.txt

# 2. Sanity-check the pipeline on a small sample
python test_pipeline_small.py

# 3. Run for real
python collect_changes.py --project openstack/nova --project openstack/neutron --since 2023-01-01
python build_topic_dataset.py
python extract_advanced_features.py fetch-relations
python extract_advanced_features.py build-bottleneck-features
python extract_advanced_features.py build-snapshot-features --cutoff-hours 48
```

---

## Dataset 1: `topics_dataset.csv` — full lifetime, one row per topic

35 columns total: 1 identifier + 34 features/outcomes.

### Identifiers & timing
| Column | Meaning |
|---|---|
| `topic_id` | The topic name. The key used to join all datasets together. |
| `created_at` | When the topic's earliest change was created. |
| `last_updated_at` | When anything in the topic last changed. |
| `time_to_completion_hours` | Hours from creation to the topic being merged or abandoned. The main "how long did this take" number. |

### Outcome / stall risk (Task #2)
| Column | Meaning |
|---|---|
| `outcome` | One of `merged`, `abandoned`, `mixed`, or `stale_open`. The overall classification target. |
| `n_merged`, `n_abandoned`, `n_open` | How many of the topic's individual changes ended up in each state. A topic with 5 changes might have 3 merged, 1 abandoned, 1 still open — these raw counts are what `outcome` is actually derived from, and they're kept separately so a model can see *how* mixed a topic's progress is, not just the final label. |
| `last_activity_gap_days` | Days since anything last happened. A topic with no activity for 90+ days is labeled `stale_open`. |

### Review delays (Task #1)
| Column | Meaning |
|---|---|
| `first_review_delay_hours` | Hours until the first real human (non-bot) comment. The core "how long did people wait for a response" metric. |
| `avg_review_delay_hours` | Average gap between human responses across the topic's whole life. |
| `avg_active_days` | Average lifespan of the individual changes in the topic. Helps tell apart "fast review but slow merge" from "everything was slow." |

### CI churn & rework (Task #4)
| Column | Meaning |
|---|---|
| `ci_runs`, `ci_successes`, `ci_failures` | Raw counts of automated test runs and their results. |
| `ci_failure_rate` | `ci_failures / ci_runs`. Normalized so topics of different sizes are comparable. |
| `ci_rerun_verified_drops` | Number of times CI auto-retried itself (no human asked for it). |
| `ci_rerun_recheck_msgs` | Number of times a human explicitly typed "recheck" to ask CI to try again. |
| `ci_retries` | `ci_rerun_verified_drops + ci_rerun_recheck_msgs`. One combined churn number, while the two components above are kept separately so you can tell "CI itself is flaky" apart from "humans don't trust CI's first result." |
| `total_patchsets` | Total number of revisions (code updates) across all changes in the topic. |
| `avg_patchsets_per_change` | `total_patchsets / n_changes`. Rework per change. |
| `max_files_changed` | The largest number of files touched in any single patchset. Bigger diffs tend to review more slowly. |

### Binding review votes
| Column | Meaning |
|---|---|
| `total_code_review_plus2` | Count of binding "approved, ready to merge" votes. In Gerrit, only +2/-2 actually gate merging — +1/-1 are just opinions. |
| `total_code_review_minus2` | Count of binding "blocked, do not merge" votes. Any -2 is a strong signal of real disagreement, useful for predicting delay or abandonment. |

### Scale & scope
| Column | Meaning |
|---|---|
| `n_changes` | How many individual changes belong to this topic. |
| `n_repos` | How many different code repositories the topic touches. |
| `n_branches` | How many different git branches are involved. |
| `total_revisions` | Total count of revision *events* recorded across all changes in the topic (this is a raw event count, distinct from `total_patchsets` below — they're computed from different source data and can differ slightly). |
| `total_messages` | Total comment count, humans and bots combined. (The human/bot split is handled elsewhere — see `early_human_comment_ratio` below.) |
| `n_reviewers` | Number of distinct reviewer accounts, no bot filtering applied here. |

### Contributors
| Column | Meaning |
|---|---|
| `code_authors_count` | Strict count: only people who actually wrote/uploaded code (change owners + patchset uploaders). The size of the core engineering team. |
| `people_involved_count` | Broad count: everyone above, *plus* anyone who left a comment. The size of the whole social/review network around the topic. |
| `author_count` | An exact alias of `people_involved_count`, kept for backward compatibility with older scripts that used this column name before the strict/broad split existed. Always identical to `people_involved_count` — never compute it differently. |
| `authors_per_change` | `code_authors_count / n_changes`. Flags topics where one person is doing all the coding work alone. |
| `top_author_changes` | The largest number of changes authored by any single contributor. A concentration / "bus factor" signal. |

A useful pattern: a big gap between `code_authors_count` (small) and
`people_involved_count` (large) means a small amount of code is generating a lot of
discussion — often a sign of disagreement or a tricky review, which tends to correlate
with delay or stalling.

---

## Dataset 2: `topic_snapshot_features.csv` — early warning window, one row per topic

8 columns total: 2 identifiers/parameters + 6 features. This is the *only* dataset
that's safe to use as model input for Task #5 (early prediction), because everything
in it is information that genuinely existed by the cutoff time — nothing here can leak
the eventual outcome.

| Column | Meaning |
|---|---|
| `topic_id` | Join key back to `topics_dataset.csv` for the actual outcome labels. |
| `cutoff_hours` | How many hours after topic creation this snapshot was measured (e.g. 48). |
| `initial_change_count` | How many changes existed in the topic by the cutoff (topics can grow after creation, so this can be smaller than `n_changes` in the full dataset). |
| `early_comment_count` | Total comments posted before the cutoff. |
| `early_comment_velocity` | Comments per hour in the early window. A topic with 10 comments in 2 hours is a very different situation from 10 comments spread across 48 — the raw count alone wouldn't show that. |
| `early_unique_reviewers` | Number of distinct human reviewers active before the cutoff. Low breadth this early is a predictor of stalling later. |
| `early_patchset_count` | Number of revisions uploaded before the cutoff — same idea as `total_patchsets`, but bounded to the early window only. |
| `early_human_comment_ratio` | What fraction of early comments came from humans rather than CI bots. A topic dominated by bot noise in hour 1 looks very different from one with real early human engagement, even if the raw comment count is the same. |

**How to use this dataset:** join it to `topics_dataset.csv` on `topic_id`, use the
snapshot columns as your `X` (input features) and the outcome columns from the full
dataset as your `y` (label). Never train Task #5 using columns from
`topics_dataset.csv` directly as input — that's the leakage trap this whole split
exists to avoid.

---

## Dataset 3: `change_bottleneck_features.csv` — one row per individual change

11 columns total: 4 identifiers + 7 features. Unlike the other two datasets, this one
is at the **change** level, not the topic level, because "is this specific patch
blocking others" is a property of one node in a dependency graph — averaging it up to
the topic would destroy exactly the information (which change is the actual root
cause) that this dataset exists to capture.

| Column | Meaning |
|---|---|
| `change_id` | The individual change's ID. |
| `topic` | Which topic this change belongs to (links back to the other datasets). |
| `project` | Which code repository this change is in. |
| `status` | Current state of this individual change (merged / abandoned / open). |
| `chain_length` | How many changes are stacked together in this change's dependency chain. |
| `is_chain_root` | True if this change is the bottom of the stack — the one everything else depends on. |
| `in_degree_in_chain` | How many other changes are stacked directly on top of this one. |
| `num_blocked_children` | Of those changes stacked on top, how many are *currently* still open (i.e. actively blocked right now, not just historically dependent). |
| `submittable` | Gerrit's own flag for whether this change is currently ready to merge. A cheap sanity-check feature. |
| `code_review_plus2` | Whether this specific change currently has a binding approval vote. |
| `code_review_minus2` | Whether this specific change currently has a binding block vote. At the change level, this can pinpoint exactly which change in a stack has the `-2` that's freezing everything above it. |

---

## Configuration & Extension

- **Change which projects or dates are mined**: edit the defaults in
  `collect_changes.py`, or pass them on the command line:
  ```bash
  python collect_changes.py --project openstack/cinder --since 2024-01-01
  ```
- **Adjust bot detection**: bot username patterns and CI vote tag prefixes are
  configurable in `build_topic_dataset.py` via `CI_TAG_PREFIXES` and
  `BOT_USERNAME_HINTS`.

---

## Known scope limits (honest gaps, not bugs)

- This pipeline gives full-lifetime totals and **one** early snapshot (48h by
  default). It does not yet produce a true time series (e.g. weekly trend lines) — if
  that's needed for the "temporal evolution" part of the internship brief, it would
  require running `build-snapshot-features` at multiple cutoffs (e.g. 24h, 48h, 7d,
  30d) or building a separate per-period rollup.
(hata nthbatou fiha )
