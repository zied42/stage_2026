"""
train_bottleneck_model.py
=========================
Reproduces coordination_risk_prediction.ipynb logic.
Trains a change-level coordination risk model and saves it.
At prediction time, change-level predictions are aggregated to blueprint level.
"""

import os
import warnings
import numpy as np
import pandas as pd
import joblib
from sklearn.pipeline import Pipeline
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import GroupShuffleSplit
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import roc_auc_score, average_precision_score, f1_score

warnings.filterwarnings('ignore')

RANDOM_STATE = 42
PCT = 0.75  # Threshold percentile (from notebook)
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
DEP_DIR = os.path.join(DATA_DIR, 'dependencie')
MODELS_DIR = os.path.join(os.path.dirname(__file__), 'models')
os.makedirs(MODELS_DIR, exist_ok=True)

print(f'Data directory: {DATA_DIR}')
print(f'Dependencie directory: {DEP_DIR}')

# ============================================================
# 1. Load dataset
# ============================================================
print('\n=== Loading dataset ===')

csv_path = os.path.join(DEP_DIR, 'change_level_dataset.csv')
if not os.path.exists(csv_path):
    csv_path = os.path.join(DATA_DIR, 'change_level_dataset.csv')
df = pd.read_csv(csv_path)
print(f'Change-level dataset: {df.shape[0]:,} rows x {df.shape[1]} cols')
print(f'Columns: {list(df.columns)}')

# ============================================================
# 2. Preprocessing (exact notebook logic)
# ============================================================
print('\n=== Preprocessing ===')

for col in ['work_in_progress', 'mergeable']:
    if col in df.columns:
        if df[col].dtype == object:
            df[col] = df[col].map({'True': 1, 'False': 0, True: 1, False: 0})
        df[col] = df[col].fillna(0).astype(int)

df['first_review_delay_hours'] = df['first_review_delay_hours'].fillna(0)
df['time_open_hours'] = df['time_open_hours'].fillna(0)
df['graph_in_degree'] = df['graph_in_degree'].fillna(0)

# ============================================================
# 3. Topic-aware split (exact notebook logic)
# ============================================================
print('\n=== Train/Test split ===')

df_split = df.copy()
no_topic_mask = df_split['topic'].isna()
df_split.loc[no_topic_mask, '_split_group'] = [f"__no_topic_{i}" for i in df_split.index[no_topic_mask]]
df_split.loc[~no_topic_mask, '_split_group'] = df_split.loc[~no_topic_mask, 'topic']

gss = GroupShuffleSplit(n_splits=1, test_size=0.2, random_state=RANDOM_STATE)
train_idx, test_idx = next(gss.split(df_split, groups=df_split['_split_group']))
train_df = df.iloc[train_idx].copy()
test_df = df.iloc[test_idx].copy()
print(f'Train: {len(train_df)} rows | Test: {len(test_df)} rows')

# ============================================================
# 4. Define target (exact notebook logic)
# ============================================================
print('\n=== Defining target ===')

in_degree_thr = train_df['graph_in_degree'].quantile(PCT)
delay_thr = train_df['first_review_delay_hours'].quantile(PCT)
open_thr = train_df['time_open_hours'].quantile(PCT)

print(f'Threshold graph_in_degree (p{int(PCT*100)}): {in_degree_thr:.2f}')
print(f'Threshold first_review_delay_hours (p{int(PCT*100)}): {delay_thr:.2f}')
print(f'Threshold time_open_hours (p{int(PCT*100)}): {open_thr:.2f}')

def make_coordination_risk(d):
    return (
        (d['graph_in_degree'] >= in_degree_thr) &
        ((d['first_review_delay_hours'] >= delay_thr) | (d['time_open_hours'] >= open_thr)) &
        (d['status'] != 'MERGED')
    ).astype(int)

train_df['coordination_risk'] = make_coordination_risk(train_df)
test_df['coordination_risk'] = make_coordination_risk(test_df)

print(f'Coordination risk rate train: {train_df["coordination_risk"].mean():.2%}')
print(f'Coordination risk rate test: {test_df["coordination_risk"].mean():.2%}')

# ============================================================
# 5. Define features (exact notebook logic)
# ============================================================
LEAKAGE_OR_ID_COLS = [
    'number', 'change_id',
    'graph_in_degree', 'graph_out_degree',
    'first_review_delay_hours', 'time_open_hours',
    'status',
    'coordination_risk',
    'target_is_bottleneck',
]
DATE_COLS = ['created', 'updated', 'submitted']
ID_LIKE_COLS = ['topic', 'node_source', 'project', 'branch']

drop_cols = set(LEAKAGE_OR_ID_COLS + DATE_COLS + ID_LIKE_COLS)
feature_cols = [c for c in df.columns if c not in drop_cols]
numeric_cols = [c for c in feature_cols]

print(f'\n{len(feature_cols)} features: {feature_cols}')

X_train = train_df[feature_cols]
y_train = train_df['coordination_risk']
X_test = test_df[feature_cols]
y_test = test_df['coordination_risk']

# ============================================================
# 6. Build and train pipeline (exact notebook logic)
# ============================================================
print('\n=== Training model ===')

preprocessor = ColumnTransformer([
    ('num', Pipeline([
        ('impute', SimpleImputer(strategy='median')),
        ('scale', StandardScaler()),
    ]), numeric_cols),
])

model = Pipeline([
    ('prep', preprocessor),
    ('clf', RandomForestClassifier(
        n_estimators=300, class_weight='balanced', min_samples_leaf=5,
        random_state=RANDOM_STATE, n_jobs=-1
    ))
])

model.fit(X_train, y_train)

y_pred = model.predict(X_test)
y_proba = model.predict_proba(X_test)[:, 1]

auc = roc_auc_score(y_test, y_proba)
ap = average_precision_score(y_test, y_proba)
f1 = f1_score(y_test, y_pred)
print(f'ROC-AUC: {auc:.4f}')
print(f'PR-AUC: {ap:.4f}')
print(f'F1: {f1:.4f}')

# Feature importances
importances = model.named_steps['clf'].feature_importances_
imp_df = pd.DataFrame({'feature': numeric_cols, 'importance': importances})
imp_df = imp_df.sort_values('importance', ascending=False).head(15)
print(f'\nTop 15 features:')
for _, row in imp_df.iterrows():
    print(f'  {row["feature"]:40s} {row["importance"]:.4f}')

# ============================================================
# 7. Save model and config
# ============================================================
print('\n=== Saving model ===')

model_path = os.path.join(MODELS_DIR, 'coordination_bottleneck_pipeline.pkl')
joblib.dump(model, model_path)
print(f'Saved pipeline: {model_path}')

config = {
    'feature_cols': feature_cols,
    'numeric_cols': numeric_cols,
    'thresholds': {
        'in_degree_thr': float(in_degree_thr),
        'delay_thr': float(delay_thr),
        'open_thr': float(open_thr),
        'percentile': PCT,
    },
    'metrics': {
        'auc': float(auc),
        'ap': float(ap),
        'f1': float(f1),
    },
    'model_name': 'RandomForest',
    'top_features': {row['feature']: float(row['importance']) for _, row in imp_df.iterrows()},
}

config_path = os.path.join(MODELS_DIR, 'coordination_bottleneck_config.pkl')
joblib.dump(config, config_path)
print(f'Saved config: {config_path}')

print('\n=== Done ===')
