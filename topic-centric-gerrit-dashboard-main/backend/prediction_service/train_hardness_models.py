"""
train_hardness_models.py — CORRECTED
=====================================
Reproduces the EXACT logic from hardness_final_v4 notebook.
Key corrections vs previous version:
  - Uses 49 features (Feature Set F), NOT 77
  - SNAPSHOT_COLS and BP_SNAPSHOT_COLS are EMPTY (as in notebook)
  - Uses per-task BEST model (not RF for all):
      is_slow       → RandomForest
      at_risk       → XGBoost
      excessive_rework → RandomForest
      high_effort   → LogisticRegression (with StandardScaler pipeline)
"""

import os
import sys
import warnings
import numpy as np
import pandas as pd
import joblib
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.metrics import roc_auc_score, average_precision_score

try:
    from xgboost import XGBClassifier
    HAS_XGB = True
except ImportError:
    HAS_XGB = False
    print("[WARN] xgboost not installed, at_risk will use RandomForest fallback")

warnings.filterwarnings('ignore')

RANDOM_STATE = 42
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
MODELS_DIR = os.path.join(os.path.dirname(__file__), 'models')
os.makedirs(MODELS_DIR, exist_ok=True)

print(f'Data directory: {DATA_DIR}')
print(f'Models directory: {MODELS_DIR}')

# ============================================================
# 1. Load datasets
# ============================================================
print('\n=== Loading datasets ===')

df = pd.read_csv(os.path.join(DATA_DIR, 'hardness_dataset_updated.csv'))
print(f'Main dataset: {df.shape[0]:,} rows x {df.shape[1]} cols')

hist = pd.read_csv(os.path.join(DATA_DIR, 'hardness_blueprint_history_features.csv'))
HIST_KEY = 'blueprint_id' if 'blueprint_id' in hist.columns else 'topic_id'
print(f'History: {hist.shape[0]:,} rows, key={HIST_KEY}')

spec_derived = pd.read_csv(os.path.join(DATA_DIR, 'hardness_spec_derived_features.csv'))
print(f'Spec-derived: {spec_derived.shape[0]:,} rows')

llm_scores = pd.read_csv(os.path.join(DATA_DIR, 'hardness_llm_scores2.csv'))
print(f'LLM scores: {llm_scores.shape[0]:,} rows')

# ============================================================
# 2. Merge datasets (notebook logic — NO bp_snapshot merge)
# ============================================================
print('\n=== Merging datasets ===')

# Merge spec-derived
spec_derived_renamed = spec_derived.rename(
    columns={'blueprint_name': 'blueprint', 'lp_project': 'project'}
)
df = df.merge(spec_derived_renamed, on=['blueprint', 'project'], how='left', suffixes=('', '_derived'))
print(f'After spec-derived merge: {df.shape}')

# Merge LLM scores (NO bp_snapshot merge — Feature Set E is skipped in notebook)
llm_scores = llm_scores.drop_duplicates(subset=['blueprint_name', 'lp_project'], keep='last')
llm_scores = llm_scores[llm_scores['hardness_score'].notna()].copy()
LLM_SCORE_COLS_RAW = [
    'section_problem_description_score', 'section_proposed_change_score',
    'section_alternatives_score', 'section_data_model_score', 'section_rest_api_score',
    'section_security_impact_score', 'section_testing_score', 'section_dependencies_score',
    'section_documentation_impact_score', 'section_work_items_score',
    'hardness_score', 'complexity', 'ambiguity', 'risk',
]
llm_scores_renamed = llm_scores.rename(
    columns={'blueprint_name': 'blueprint', 'lp_project': 'project'}
)[['blueprint', 'project'] + LLM_SCORE_COLS_RAW].rename(
    columns={c: f'llm_{c}' for c in LLM_SCORE_COLS_RAW}
)
df = df.merge(llm_scores_renamed, on=['blueprint', 'project'], how='left', suffixes=('', '_llm'))
print(f'After LLM merge: {df.shape}')

# ============================================================
# 3. Feature engineering (exact notebook logic)
# ============================================================
print('\n=== Feature engineering ===')

# Drop leaky columns
LEAKY_COLS_TO_DROP = [
    'total_patchsets', 'ci_rerun_recheck_msgs', 'author_count',
    'n_merged', 'total_code_review_plus2', 'ci_successes',
    'n_reviewers', 'total_code_review_minus2', 'code_authors_count',
]
df = df.drop(columns=[c for c in LEAKY_COLS_TO_DROP if c in df.columns], errors='ignore')

# Encode blueprint metadata
priority_map = {'Essential': 4, 'High': 3, 'Medium': 2, 'Low': 1, 'Undefined': 0}
df['bp_priority_score'] = df['priority'].map(priority_map).fillna(0)
df['bp_is_approved'] = (df['definition_status'] == 'Approved').astype(int)
df['bp_is_complete'] = df['is_complete'].fillna(False).astype(int)
df['bp_has_goal'] = df['has_accepted_goal'].fillna(False).astype(int)
df['bp_has_full_spec'] = df['has_full_spec'].fillna(False).astype(int)
df['bp_spec_word_count'] = df['spec_word_count'].fillna(0)
df['bp_summary_word_count'] = df['summary_word_count'].fillna(0)

# bp_n_topics_urls — create if missing
if 'bp_n_topics_urls' not in df.columns:
    df['bp_n_topics_urls'] = df.get('n_topics', pd.Series(0, index=df.index)).fillna(0)

print(f'After feature engineering: {df.shape}')

# ============================================================
# 4. Define feature sets (EXACT notebook definitions)
# ============================================================

# SNAPSHOT_COLS is EMPTY in the notebook
SNAPSHOT_COLS = []

HISTORY_COLS = [
    'author_past_topic_count', 'author_past_blueprint_count', 'author_past_merge_rate',
    'author_tenure_days', 'repo_historical_topic_count', 'repo_historical_blueprint_count',
    'repo_historical_abandon_rate',
]

LAUNCHPAD_COLS = ['bp_priority_score', 'bp_is_approved', 'bp_is_complete', 'bp_has_goal']

SPEC_COLS = ['bp_has_full_spec', 'bp_spec_word_count', 'bp_summary_word_count', 'bp_n_topics_urls']

SPEC_DERIVED_COLS = [c for c in [
    'has_section_problem_description', 'has_section_proposed_change',
    'has_section_alternatives', 'has_section_data_model', 'has_section_rest_api',
    'has_section_security_impact', 'has_section_testing', 'has_section_dependencies',
    'has_section_documentation_impact', 'work_items_count', 'codeblock_count',
    'uncertainty_marker_count', 'url_count', 'xref_count', 'image_count',
    'sentence_count', 'avg_sentence_len_words', 'avg_touch_count', 'max_touch_count',
    'days_topic_to_bp_creation', 'elaboration_ratio',
] if c in df.columns]

# BP_SNAPSHOT_COLS is EMPTY in the notebook
BP_SNAPSHOT_COLS = []

LLM_SCORE_COLS = [c for c in [
    'llm_section_problem_description_score', 'llm_section_proposed_change_score',
    'llm_section_alternatives_score', 'llm_section_data_model_score',
    'llm_section_rest_api_score', 'llm_section_security_impact_score',
    'llm_section_testing_score', 'llm_section_dependencies_score',
    'llm_section_documentation_impact_score', 'llm_section_work_items_score',
    'llm_hardness_score', 'llm_complexity', 'llm_ambiguity',
] if c in df.columns]

# Build cumulative feature sets (same as notebook)
FEATURE_SETS = {
    'A_baseline': SNAPSHOT_COLS + HISTORY_COLS,
    'B_plus_launchpad': SNAPSHOT_COLS + HISTORY_COLS + LAUNCHPAD_COLS,
    'C_plus_spec_meta': SNAPSHOT_COLS + HISTORY_COLS + LAUNCHPAD_COLS + SPEC_COLS,
}
if SPEC_DERIVED_COLS:
    FEATURE_SETS['D_plus_spec_derived'] = (
        SNAPSHOT_COLS + HISTORY_COLS + LAUNCHPAD_COLS + SPEC_COLS + SPEC_DERIVED_COLS
    )
# Feature Set E SKIPPED (BP_SNAPSHOT_COLS is empty)
if LLM_SCORE_COLS:
    richest = list(FEATURE_SETS.values())[-1]
    FEATURE_SETS['F_plus_llm_scores'] = richest + LLM_SCORE_COLS

BEST_FEATURE_SET = list(FEATURE_SETS.keys())[-1]
best_features = FEATURE_SETS[BEST_FEATURE_SET]

for name, cols in FEATURE_SETS.items():
    print(f'{name:22s}: {len(cols)} features')
print(f'\nBest feature set: {BEST_FEATURE_SET} ({len(best_features)} features)')

# ============================================================
# 5. Define targets (exact notebook logic)
# ============================================================
print('\n=== Defining targets ===')

df_completed = df[df['time_to_completion_hours'].notna()].copy()
df_completed['time_to_completion_days'] = df_completed['time_to_completion_hours'] / 24.0
P90_DAYS = df_completed['time_to_completion_days'].quantile(0.90)
df_completed['is_slow'] = (df_completed['time_to_completion_days'] >= P90_DAYS).astype(int)

df['at_risk'] = (~df['outcome'].astype(str).str.lower().isin(['merged'])).astype(int)

ci_p90 = df['ci_retries'].quantile(0.90)
rev_p90 = df['total_revisions'].quantile(0.90)
df['excessive_rework'] = (
    (df['ci_retries'].fillna(0) > ci_p90) | (df['total_revisions'].fillna(0) > rev_p90)
).astype(int)

df['msgs_per_revision'] = df['total_messages'] / df['total_revisions'].replace(0, np.nan)
msg_per_rev_p90 = df['msgs_per_revision'].quantile(0.90)
df['high_effort'] = (df['msgs_per_revision'].fillna(0) > msg_per_rev_p90).astype(int)

TASKS = {'is_slow': df_completed, 'at_risk': df, 'excessive_rework': df, 'high_effort': df}

print(f'[is_slow]          n={len(df_completed):,}  P90={P90_DAYS:.1f}d')
print(f'[at_risk]          n={len(df):,}  positive={df["at_risk"].mean()*100:.2f}%')
print(f'[excessive_rework] n={len(df):,}  positive={df["excessive_rework"].mean()*100:.2f}%')
print(f'[high_effort]      n={len(df):,}  positive={df["high_effort"].mean()*100:.2f}%')

# ============================================================
# 6. Merge history for each task (exact notebook logic)
# ============================================================
print('\n=== Merging history per task ===')

task_data = {}
for task, base_df in TASKS.items():
    if 'bp_join_key' not in base_df.columns:
        base_df['bp_join_key'] = base_df['project'].astype(str) + '::' + base_df['blueprint'].astype(str)
    if HIST_KEY == 'blueprint_id':
        merged = base_df.merge(hist, left_on='bp_join_key', right_on='blueprint_id', how='left', suffixes=('', '_hist'))
        if 'blueprint_id' in merged.columns:
            merged = merged.drop(columns=['blueprint_id'])
    else:
        merged = base_df.merge(hist, on='topic_id', how='left')
    task_data[task] = merged
    print(f'  [{task:16s}] merged: {len(merged):,} rows')

# ============================================================
# 7. Define per-task best models (from notebook comparison)
# ============================================================

def get_model_for_task(task_name):
    """Return the best model per task as identified by the notebook."""
    if task_name == 'is_slow':
        return RandomForestClassifier(
            n_estimators=300, max_depth=10, min_samples_leaf=5,
            class_weight='balanced', random_state=RANDOM_STATE, n_jobs=-1
        ), 'RandomForest'
    elif task_name == 'at_risk':
        if HAS_XGB:
            return XGBClassifier(
                n_estimators=200, max_depth=5, learning_rate=0.05,
                eval_metric='logloss', random_state=RANDOM_STATE, n_jobs=-1
            ), 'XGBoost'
        else:
            return RandomForestClassifier(
                n_estimators=300, max_depth=10, min_samples_leaf=5,
                class_weight='balanced', random_state=RANDOM_STATE, n_jobs=-1
            ), 'RandomForest'
    elif task_name == 'excessive_rework':
        return RandomForestClassifier(
            n_estimators=300, max_depth=10, min_samples_leaf=5,
            class_weight='balanced', random_state=RANDOM_STATE, n_jobs=-1
        ), 'RandomForest'
    elif task_name == 'high_effort':
        return Pipeline([
            ('scaler', StandardScaler()),
            ('clf', LogisticRegression(
                class_weight='balanced', max_iter=1000, random_state=RANDOM_STATE
            ))
        ]), 'LogisticRegression'
    else:
        raise ValueError(f'Unknown task: {task_name}')

# ============================================================
# 8. Train and save models
# ============================================================
print('\n=== Training models (per-task best) ===')

TASK_TO_FILENAME = {
    'is_slow': 'model_review_delay.pkl',
    'at_risk': 'model_stall_abandonment.pkl',
    'excessive_rework': 'model_excessive_rework.pkl',
    'high_effort': 'model_high_review_effort.pkl',
}
TASK_TO_DISPLAY = {
    'is_slow': 'Review Delay',
    'at_risk': 'Stall / Abandonment Risk',
    'excessive_rework': 'Excessive Rework',
    'high_effort': 'High Review Effort',
}

feature_config = {
    'thresholds': {
        'P90_DAYS': float(P90_DAYS),
        'ci_p90': float(ci_p90),
        'rev_p90': float(rev_p90),
        'msg_per_rev_p90': float(msg_per_rev_p90),
    },
    'feature_set_name': BEST_FEATURE_SET,
    'feature_set_size': len(best_features),
    'tasks': {},
}

for task, data in task_data.items():
    model, model_name = get_model_for_task(task)
    print(f'\n--- Training: {task} ({TASK_TO_DISPLAY[task]}) using {model_name} ---')

    avail = [c for c in best_features if c in data.columns]
    work = data.dropna(subset=[task]).copy()

    if 'created_at' in work.columns and work['created_at'].notna().any():
        work = work.sort_values('created_at')

    X = work[avail].fillna(0)
    y = work[task].astype(int)

    if y.nunique() < 2 or y.sum() < 5:
        print(f'  [SKIP] {task}: insufficient positives')
        continue

    split = int(len(work) * 0.75)
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]

    if y_train.nunique() < 2 or y_test.nunique() < 2:
        print(f'  [SKIP] {task}: single class after temporal split')
        continue

    model.fit(X_train, y_train)

    y_prob = model.predict_proba(X_test)[:, 1]
    auc = roc_auc_score(y_test, y_prob)
    ap = average_precision_score(y_test, y_prob)
    print(f'  AUC={auc:.3f}  AP={ap:.3f}  features={len(avail)}  model={model_name}')

    # Get feature importances
    if model_name == 'LogisticRegression':
        # Pipeline: extract coefs from the clf step
        coefs = np.abs(model.named_steps['clf'].coef_[0])
        importances = pd.Series(coefs, index=avail)
    else:
        importances = pd.Series(model.feature_importances_, index=avail)
    top_features = importances.sort_values(ascending=False).head(10)
    print(f'  Top features: {list(top_features.index[:5])}')

    model_path = os.path.join(MODELS_DIR, TASK_TO_FILENAME[task])
    joblib.dump(model, model_path)
    print(f'  Saved: {model_path}')

    feature_config['tasks'][task] = {
        'display_name': TASK_TO_DISPLAY[task],
        'model_file': TASK_TO_FILENAME[task],
        'model_name': model_name,
        'feature_cols': avail,
        'n_train': len(X_train),
        'n_test': len(X_test),
        'auc': float(auc),
        'ap': float(ap),
        'top_features': {k: float(v) for k, v in top_features.items()},
    }

config_path = os.path.join(MODELS_DIR, 'hardness_feature_config.pkl')
joblib.dump(feature_config, config_path)
print(f'\nSaved feature config: {config_path}')

print('\n=== Training complete ===')
for task, info in feature_config['tasks'].items():
    print(f'  {info["display_name"]:30s} {info["model_name"]:20s} AUC={info["auc"]:.3f}')
