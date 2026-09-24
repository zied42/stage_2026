"""
Flask Prediction Microservice — Redesigned
============================================
Two separate prediction interfaces + chatbot + graph data.

Endpoints:
  GET  /blueprints                          - List all blueprints
  GET  /blueprints/<id>/predictions         - 4 hardness predictions ONLY
  GET  /blueprints/<id>/bottleneck          - Coordination bottleneck ONLY
  GET  /blueprints/<id>/graph               - Graph JSON data
  POST /blueprints/<id>/chat                - Chatbot
  GET  /health                              - Health check
"""

import os
import sys
import json
import warnings
import numpy as np
import pandas as pd
import joblib
from flask import Flask, jsonify, request
from flask_cors import CORS
from pathlib import Path

warnings.filterwarnings('ignore')

app = Flask(__name__)
CORS(app)

# ============================================================
# Configuration
# ============================================================
DATA_DIR = os.environ.get('DATA_DIR', os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..', '..')
))
MODELS_DIR = os.path.join(os.path.dirname(__file__), 'models')
GRAPH_DIR = os.path.join(DATA_DIR, 'graph_photo', 'graphs_depends_on2')
LLM_DIR = os.path.join(DATA_DIR, 'llm_assistant_start_at_known_specs')
DEP_DIR = os.path.join(DATA_DIR, 'dependencie')

OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY', '')

print(f'[PredictionService] Data: {DATA_DIR}')
print(f'[PredictionService] Models: {MODELS_DIR}')
print(f'[PredictionService] Graphs: {GRAPH_DIR}')
print(f'[PredictionService] LLM Assistant: {LLM_DIR}')

# ============================================================
# Load data at startup
# ============================================================
print('[PredictionService] Loading datasets...')

df_main = pd.read_csv(os.path.join(DATA_DIR, 'hardness_dataset_updated.csv'))
spec_derived = pd.read_csv(os.path.join(DATA_DIR, 'hardness_spec_derived_features.csv'))
spec_derived = spec_derived.rename(columns={'blueprint_name': 'blueprint', 'lp_project': 'project'})

llm_scores = pd.read_csv(os.path.join(DATA_DIR, 'hardness_llm_scores2.csv'))
llm_scores = llm_scores.drop_duplicates(subset=['blueprint_name', 'lp_project'], keep='last')
llm_scores = llm_scores[llm_scores['hardness_score'].notna()].copy()
LLM_SCORE_COLS_RAW = [
    'section_problem_description_score', 'section_proposed_change_score',
    'section_alternatives_score', 'section_data_model_score', 'section_rest_api_score',
    'section_security_impact_score', 'section_testing_score', 'section_dependencies_score',
    'section_documentation_impact_score', 'section_work_items_score',
    'hardness_score', 'complexity', 'ambiguity', 'risk',
]
llm_scores = llm_scores.rename(
    columns={'blueprint_name': 'blueprint', 'lp_project': 'project'}
)[['blueprint', 'project'] + LLM_SCORE_COLS_RAW].rename(
    columns={c: f'llm_{c}' for c in LLM_SCORE_COLS_RAW}
)

hist = pd.read_csv(os.path.join(DATA_DIR, 'hardness_blueprint_history_features.csv'))

# Build unified hardness feature table
df = df_main.copy()
df = df.merge(spec_derived, on=['blueprint', 'project'], how='left', suffixes=('', '_derived'))
df = df.merge(llm_scores, on=['blueprint', 'project'], how='left', suffixes=('', '_llm'))

LEAKY_COLS_TO_DROP = [
    'total_patchsets', 'ci_rerun_recheck_msgs', 'author_count',
    'n_merged', 'total_code_review_plus2', 'ci_successes',
    'n_reviewers', 'total_code_review_minus2', 'code_authors_count',
]
df = df.drop(columns=[c for c in LEAKY_COLS_TO_DROP if c in df.columns], errors='ignore')

# Feature engineering
priority_map = {'Essential': 4, 'High': 3, 'Medium': 2, 'Low': 1, 'Undefined': 0}
df['bp_priority_score'] = df['priority'].map(priority_map).fillna(0)
df['bp_is_approved'] = (df['definition_status'] == 'Approved').astype(int)
df['bp_is_complete'] = df['is_complete'].fillna(False).astype(int)
df['bp_has_goal'] = df['has_accepted_goal'].fillna(False).astype(int)
df['bp_has_full_spec'] = df['has_full_spec'].fillna(False).astype(int)
df['bp_spec_word_count'] = df['spec_word_count'].fillna(0)
df['bp_summary_word_count'] = df['summary_word_count'].fillna(0)
if 'bp_n_topics_urls' not in df.columns:
    df['bp_n_topics_urls'] = df.get('n_topics', pd.Series(0, index=df.index)).fillna(0)

# Merge history
df['bp_join_key'] = df['project'].astype(str) + '::' + df['blueprint'].astype(str)
if 'blueprint_id' in hist.columns:
    df = df.merge(hist, left_on='bp_join_key', right_on='blueprint_id', how='left', suffixes=('', '_hist'))
    if 'blueprint_id' in df.columns:
        df = df.drop(columns=['blueprint_id'])

df['blueprint_key'] = df['project'].astype(str) + '::' + df['blueprint'].astype(str)
BLUEPRINT_DATA = {}
for _, row in df.iterrows():
    BLUEPRINT_DATA[row['blueprint_key']] = row

print(f'[PredictionService] Loaded {len(BLUEPRINT_DATA)} blueprints with hardness features')

# Blueprint list from bp_final
bp_final = pd.read_csv(os.path.join(DATA_DIR, 'blueprint_dataset_Final.csv'))
bp_final['blueprint_key'] = bp_final['project'].astype(str) + '::' + bp_final['blueprint'].astype(str)
BLUEPRINT_LIST = []
for _, row in bp_final.iterrows():
    BLUEPRINT_LIST.append({
        'id': row['blueprint_key'],
        'name': str(row['blueprint']),
        'title': str(row.get('title', row['blueprint'])),
        'project': str(row['project']),
        'priority': str(row.get('priority', 'Unknown')),
        'definition_status': str(row.get('definition_status', 'Unknown')),
        'implementation_status': str(row.get('implementation_status', 'Unknown')),
        'lifecycle_status': str(row.get('lifecycle_status', 'Unknown')),
        'is_complete': bool(row.get('is_complete', False) == True or str(row.get('is_complete', '')).lower() == 'true'),
        'has_accepted_goal': bool(row.get('has_accepted_goal', False) == True or str(row.get('has_accepted_goal', '')).lower() == 'true'),
        'has_full_spec': bool(row.get('has_full_spec', False) == True or str(row.get('has_full_spec', '')).lower() == 'true'),
        'spec_word_count': int(row['spec_word_count']) if pd.notna(row.get('spec_word_count')) else 0,
        'n_topics': int(row['n_topics']) if pd.notna(row.get('n_topics')) else 0,
        'n_changes': int(row['n_changes']) if pd.notna(row.get('n_changes')) else 0,
    })
BLUEPRINT_LIST.sort(key=lambda x: (x['project'], x['name']))
BLUEPRINT_META = {bp['id']: bp for bp in BLUEPRINT_LIST}

# Load change-level dataset for bottleneck
change_csv = os.path.join(DEP_DIR, 'change_level_dataset.csv')
if not os.path.exists(change_csv):
    change_csv = os.path.join(DATA_DIR, 'change_level_dataset.csv')
CHANGE_DF = pd.read_csv(change_csv)
for col in ['work_in_progress', 'mergeable']:
    if col in CHANGE_DF.columns:
        if CHANGE_DF[col].dtype == object:
            CHANGE_DF[col] = CHANGE_DF[col].map({'True': 1, 'False': 0, True: 1, False: 0})
        CHANGE_DF[col] = CHANGE_DF[col].fillna(0).astype(int)
CHANGE_DF['first_review_delay_hours'] = CHANGE_DF['first_review_delay_hours'].fillna(0)
CHANGE_DF['time_open_hours'] = CHANGE_DF['time_open_hours'].fillna(0)
CHANGE_DF['graph_in_degree'] = CHANGE_DF['graph_in_degree'].fillna(0)
print(f'[PredictionService] Loaded {len(CHANGE_DF):,} changes for bottleneck')

# Build topic-to-blueprint mapping from hardness dataset
TOPIC_TO_BLUEPRINT = {}
for _, row in df_main.iterrows():
    topics = row.get('topics', '')
    bp_key = f"{row['project']}::{row['blueprint']}"
    if pd.notna(topics) and topics:
        for t in str(topics).split(','):
            t = t.strip()
            if t:
                TOPIC_TO_BLUEPRINT[t] = bp_key
    bp_topic = f"bp/{row['blueprint']}"
    TOPIC_TO_BLUEPRINT[bp_topic] = bp_key
    TOPIC_TO_BLUEPRINT[row['blueprint']] = bp_key

# Load LLM specs
SPECS = {}
specs_path = os.path.join(LLM_DIR, 'full_specs.json')
if os.path.exists(specs_path):
    with open(specs_path, 'r', encoding='utf-8') as f:
        specs_list = json.load(f)
    for s in specs_list:
        SPECS[s.get('blueprint_name', '')] = s
    print(f'[PredictionService] Loaded {len(SPECS)} blueprint specs for chatbot')

# ============================================================
# Load models
# ============================================================
print('[PredictionService] Loading models...')

# Hardness models
hardness_config = joblib.load(os.path.join(MODELS_DIR, 'hardness_feature_config.pkl'))
HARDNESS_MODELS = {}
for task, info in hardness_config['tasks'].items():
    model_path = os.path.join(MODELS_DIR, info['model_file'])
    HARDNESS_MODELS[task] = {
        'model': joblib.load(model_path),
        'feature_cols': info['feature_cols'],
        'display_name': info['display_name'],
        'model_name': info['model_name'],
        'top_features': info['top_features'],
        'auc': info['auc'],
    }
    print(f'  Loaded: {info["display_name"]} ({info["model_name"]}, AUC={info["auc"]:.3f})')

# Bottleneck model
bottleneck_pipeline_path = os.path.join(MODELS_DIR, 'coordination_bottleneck_pipeline.pkl')
bottleneck_config_path = os.path.join(MODELS_DIR, 'coordination_bottleneck_config.pkl')
BOTTLENECK_PIPELINE = joblib.load(bottleneck_pipeline_path)
BOTTLENECK_CONFIG = joblib.load(bottleneck_config_path)
print(f'  Loaded: Coordination Bottleneck ({len(BOTTLENECK_CONFIG["feature_cols"])} features)')

print(f'[PredictionService] Ready! {len(HARDNESS_MODELS) + 1} models loaded.')

# ============================================================
# Helper functions
# ============================================================

def get_risk_status(probability, threshold=0.5):
    if probability >= 0.7:
        return 'High Risk'
    elif probability >= threshold:
        return 'Medium Risk'
    else:
        return 'Low Risk'


def predict_hardness(blueprint_key):
    if blueprint_key not in BLUEPRINT_DATA:
        return None

    row = BLUEPRINT_DATA[blueprint_key]
    results = {}
    task_to_api_key = {
        'is_slow': 'review_delay',
        'at_risk': 'stall_abandonment',
        'excessive_rework': 'excessive_rework',
        'high_effort': 'high_review_effort',
    }

    for task, info in HARDNESS_MODELS.items():
        api_key = task_to_api_key[task]
        feature_cols = info['feature_cols']
        model = info['model']

        features = {}
        for col in feature_cols:
            val = row.get(col, 0)
            if pd.isna(val):
                val = 0
            features[col] = float(val)

        X = pd.DataFrame([features])[feature_cols].fillna(0)
        probability = float(model.predict_proba(X)[0, 1])
        prediction = bool(probability >= 0.5)

        results[api_key] = {
            'prediction': prediction,
            'probability': round(probability, 4),
            'status': get_risk_status(probability),
            'model_name': info['model_name'],
            'display_name': info['display_name'],
            'top_features': [
                {'name': name, 'importance': round(imp, 4)}
                for name, imp in sorted(info['top_features'].items(), key=lambda x: -x[1])[:8]
            ],
            'model_auc': round(info['auc'], 3),
        }

    return results


def predict_bottleneck(blueprint_key):
    """Run coordination bottleneck: find changes for this blueprint, predict each, aggregate."""
    blueprint_name = blueprint_key.split('::')[1] if '::' in blueprint_key else blueprint_key

    # Find changes belonging to this blueprint's topics
    matching_topics = []
    for topic, bp_key in TOPIC_TO_BLUEPRINT.items():
        if bp_key == blueprint_key:
            matching_topics.append(topic)

    # Also try common topic patterns
    matching_topics.extend([f'bp/{blueprint_name}', blueprint_name])
    matching_topics = list(set(matching_topics))

    changes = CHANGE_DF[CHANGE_DF['topic'].isin(matching_topics)]

    if len(changes) == 0:
        return {
            'prediction': False,
            'probability': 0.0,
            'status': 'Low Risk',
            'model_name': 'RandomForest',
            'display_name': 'Coordination Bottleneck',
            'top_features': [
                {'name': k, 'importance': round(v, 4)}
                for k, v in sorted(BOTTLENECK_CONFIG['top_features'].items(), key=lambda x: -x[1])[:8]
            ],
            'change_breakdown': {'total_changes': 0, 'risky_changes': 0, 'max_probability': 0.0},
            'note': 'No changes found for this blueprint in the dataset',
        }

    feature_cols = BOTTLENECK_CONFIG['feature_cols']
    X = changes[feature_cols].copy()
    probas = BOTTLENECK_PIPELINE.predict_proba(X)[:, 1]

    max_prob = float(probas.max())
    risky_count = int((probas >= 0.5).sum())

    blueprint_probability = max_prob
    blueprint_prediction = bool(risky_count > 0)

    return {
        'prediction': blueprint_prediction,
        'probability': round(blueprint_probability, 4),
        'status': get_risk_status(blueprint_probability),
        'model_name': 'RandomForest',
        'display_name': 'Coordination Bottleneck',
        'top_features': [
            {'name': k, 'importance': round(v, 4)}
            for k, v in sorted(BOTTLENECK_CONFIG['top_features'].items(), key=lambda x: -x[1])[:8]
        ],
        'change_breakdown': {
            'total_changes': len(changes),
            'risky_changes': risky_count,
            'max_probability': round(max_prob, 4),
        },
        'thresholds': BOTTLENECK_CONFIG.get('thresholds', {}),
    }


def get_graph_data(blueprint_name):
    """Load graph JSON for a blueprint."""
    json_path = os.path.join(GRAPH_DIR, f'{blueprint_name}.json')
    if not os.path.exists(json_path):
        return None
    with open(json_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def chat_with_blueprint(blueprint_key, user_message, predictions=None):
    """Use LLM assistant to answer questions about a blueprint."""
    blueprint_name = blueprint_key.split('::')[1] if '::' in blueprint_key else blueprint_key

    # Build context
    spec = SPECS.get(blueprint_name, {})
    bp_meta = BLUEPRINT_META.get(blueprint_key, {})

    # Try to load cached topic context
    cached_context = None
    cache_path = os.path.join(LLM_DIR, 'topic_context_cache', f'{blueprint_name}.json')
    if os.path.exists(cache_path):
        with open(cache_path, 'r', encoding='utf-8') as f:
            cached_context = json.load(f)

    # Build the prompt with context
    context_parts = []
    context_parts.append(f"Blueprint: {blueprint_name}")
    if bp_meta:
        context_parts.append(f"Project: {bp_meta.get('project', 'Unknown')}")
        context_parts.append(f"Priority: {bp_meta.get('priority', 'Unknown')}")
        context_parts.append(f"Definition: {bp_meta.get('definition_status', 'Unknown')}")
        context_parts.append(f"Implementation: {bp_meta.get('implementation_status', 'Unknown')}")
        context_parts.append(f"Topics: {bp_meta.get('n_topics', 0)}, Changes: {bp_meta.get('n_changes', 0)}")
        context_parts.append(f"Has spec: {bp_meta.get('has_full_spec', False)}, Spec words: {bp_meta.get('spec_word_count', 0)}")

    if predictions:
        context_parts.append("\nPrediction Results:")
        for key, pred in predictions.items():
            if isinstance(pred, dict):
                context_parts.append(f"  {pred.get('display_name', key)}: {pred.get('status', 'Unknown')} (probability: {pred.get('probability', 0):.1%})")

    if cached_context:
        changes_info = cached_context.get('changes', [])
        if changes_info:
            context_parts.append(f"\nGerrit Changes: {len(changes_info)} changes found")
            for c in changes_info[:5]:
                context_parts.append(f"  - {c.get('subject', 'N/A')} [{c.get('status', 'N/A')}]")

    context_text = '\n'.join(context_parts)

    prompt = f"""You are a software engineering risk analyst assistant. You help explain blueprint development risks based on data.

BLUEPRINT CONTEXT:
{context_text}

The user asks about this specific blueprint. Answer based ONLY on the provided context data. If you don't have enough information, say so clearly.

Distinguish between:
- Model predictions (quantitative risk scores)
- Blueprint/specification information (factual data)
- Your analysis/explanation (clearly mark as interpretation)

USER QUESTION: {user_message}

Provide a concise, professional answer."""

    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        response = client.chat.completions.create(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.2,
        )
        return response.choices[0].message.content or "No response generated."
    except Exception as e:
        return f"Chatbot error: {str(e)}. Please check that OPENAI_API_KEY is configured."


# ============================================================
# API Endpoints
# ============================================================

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'ok': True,
        'models_loaded': len(HARDNESS_MODELS) + 1,
        'blueprints_available': len(BLUEPRINT_LIST),
        'chatbot_ready': bool(OPENAI_API_KEY),
        'graph_dir_exists': os.path.isdir(GRAPH_DIR),
    })


@app.route('/blueprints', methods=['GET'])
def list_blueprints():
    search = request.args.get('search', '').strip().lower()
    project = request.args.get('project', '').strip().lower()
    filtered = BLUEPRINT_LIST
    if search:
        filtered = [bp for bp in filtered if search in bp['id'].lower() or search in bp['title'].lower()]
    if project:
        filtered = [bp for bp in filtered if project in bp['project'].lower()]
    return jsonify({'total': len(filtered), 'blueprints': filtered})


@app.route('/blueprints/<blueprint_id>', methods=['GET'])
def get_blueprint(blueprint_id):
    if blueprint_id not in BLUEPRINT_META:
        return jsonify({'error': f'Blueprint not found: {blueprint_id}'}), 404
    return jsonify({'blueprint': BLUEPRINT_META[blueprint_id]})


@app.route('/blueprints/<blueprint_id>/predictions', methods=['GET'])
def get_predictions(blueprint_id):
    """4 hardness predictions ONLY — no bottleneck."""
    if blueprint_id not in BLUEPRINT_META:
        return jsonify({'error': f'Blueprint not found: {blueprint_id}'}), 404

    hardness = predict_hardness(blueprint_id)
    if hardness is None:
        hardness = {}
        for api_key, display in [
            ('review_delay', 'Review Delay'), ('stall_abandonment', 'Stall / Abandonment Risk'),
            ('excessive_rework', 'Excessive Rework'), ('high_review_effort', 'High Review Effort'),
        ]:
            hardness[api_key] = {
                'prediction': None, 'probability': None, 'status': 'Unavailable',
                'model_name': 'N/A', 'display_name': display, 'top_features': [],
                'note': 'Blueprint not in hardness dataset',
            }

    return jsonify({
        'blueprint': BLUEPRINT_META[blueprint_id],
        'predictions': hardness,
    })


@app.route('/blueprints/<blueprint_id>/bottleneck', methods=['GET'])
def get_bottleneck(blueprint_id):
    """Coordination bottleneck prediction ONLY — separate from hardness."""
    if blueprint_id not in BLUEPRINT_META:
        return jsonify({'error': f'Blueprint not found: {blueprint_id}'}), 404

    bottleneck = predict_bottleneck(blueprint_id)
    return jsonify({
        'blueprint': BLUEPRINT_META[blueprint_id],
        'bottleneck': bottleneck,
    })


@app.route('/blueprints/<blueprint_id>/graph', methods=['GET'])
def get_graph(blueprint_id):
    """Graph JSON data for visualization."""
    blueprint_name = blueprint_id.split('::')[1] if '::' in blueprint_id else blueprint_id
    graph = get_graph_data(blueprint_name)
    if graph is None:
        return jsonify({'error': f'No graph data for: {blueprint_name}'}), 404
    return jsonify(graph)


@app.route('/blueprints/<blueprint_id>/chat', methods=['POST'])
def chat(blueprint_id):
    """Chatbot endpoint."""
    if blueprint_id not in BLUEPRINT_META:
        return jsonify({'error': f'Blueprint not found: {blueprint_id}'}), 404

    data = request.get_json() or {}
    message = data.get('message', '').strip()
    predictions = data.get('predictions', None)

    if not message:
        return jsonify({'error': 'No message provided'}), 400

    response = chat_with_blueprint(blueprint_id, message, predictions)
    return jsonify({'response': response})


# ============================================================
# Main
# ============================================================
if __name__ == '__main__':
    port = int(os.environ.get('PREDICTION_PORT', 5001))
    print(f'[PredictionService] Starting on port {port}...')
    app.run(host='0.0.0.0', port=port, debug=False)
