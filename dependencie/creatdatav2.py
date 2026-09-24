"""
Exporte gerrit_full_dataset.json (nodes + edges) vers un CSV plat, une ligne = 1 change.

Deux groupes de colonnes bien séparés :
  1. FEATURES (signaux précoces, indépendants du graphe) : celles qu'on a calculées dans
     le script d'enrichissement (total_patchsets, n_reviewers, first_review_delay_hours, ...)
     + les métadonnées de base (insertions, deletions, comment_count, ...).
  2. TARGET / colonnes dérivées du GRAPHE (in_degree, out_degree, is_bottleneck) :
     à utiliser UNIQUEMENT comme label, jamais comme feature d'entraînement, sinon fuite
     de données garantie (le target serait littéralement calculé à partir de lui-même).

Le CSV contient les deux groupes, mais avec un préfixe explicite sur les colonnes de
target pour qu'il n'y ait aucune ambiguïté au moment de construire X et y.

Sortie : change_level_dataset.csv
"""

import json
import csv
from collections import defaultdict

INPUT_FILE = "dependencie/gerrit_full_dataset.json"
OUTPUT_CSV = "dependencie/change_level_dataset.csv"

# Si tu veux définir is_bottleneck par un seuil absolu plutôt que "top-1 par topic",
# mets un entier ici (ex: 3) ; sinon laisse None pour utiliser le top-1 par topic.
BOTTLENECK_MIN_IN_DEGREE = None


def main():
    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    nodes = data['nodes']
    edges = data['edges']

    by_number = {str(n['number']): n for n in nodes}

    # --- 1. Calcul des degrés à partir du graphe ---
    # ATTENTION : le sens des edges dépend de comment ton dependencie/gerrit_dependencies.json
    # a été construit à l'origine. Ici on suppose la convention "source dépend de target"
    # (source -> a besoin de -> target), donc :
    #   out_degree(X) = nb de changes dont X dépend (X est source)
    #   in_degree(X)  = nb de changes qui dépendent de X (X est target) -> signal de bottleneck
    # Si ta convention est inversée, échange simplement out_degree et in_degree ci-dessous.
    out_degree = defaultdict(int)
    in_degree = defaultdict(int)
    for e in edges:
        s, t = str(e['source']), str(e['target'])
        out_degree[s] += 1
        in_degree[t] += 1

    # --- 2. Regroupement par topic pour définir le bottleneck relatif à son topic ---
    topic_groups = defaultdict(list)
    for num, n in by_number.items():
        topic = n.get('topic')
        if topic:
            topic_groups[topic].append(num)

    is_bottleneck = {num: False for num in by_number}

    if BOTTLENECK_MIN_IN_DEGREE is not None:
        # Définition par seuil absolu, indépendante du topic
        for num in by_number:
            if in_degree.get(num, 0) >= BOTTLENECK_MIN_IN_DEGREE:
                is_bottleneck[num] = True
    else:
        # Définition "top-1 par topic" : le change avec le plus grand in_degree dans son topic
        # (ties : tous les ex-aequo au max sont marqués bottleneck)
        for topic, members in topic_groups.items():
            if len(members) < 2:
                continue  # pas de notion de bottleneck dans un topic à 1 seul change
            max_deg = max(in_degree.get(m, 0) for m in members)
            if max_deg == 0:
                continue  # personne ne dépend de personne dans ce topic
            for m in members:
                if in_degree.get(m, 0) == max_deg:
                    is_bottleneck[m] = True

    # --- 3. Construction des lignes du CSV ---
    fieldnames = [
        # --- identifiants / métadonnées ---
        'number', 'change_id', 'project', 'branch', 'topic', 'status',
        'created', 'updated', 'submitted', 'work_in_progress', 'mergeable',
        'node_source',  # original_enriched / original_not_enriched / resolved

        # --- FEATURES : signaux précoces indépendants du graphe ---
        'insertions', 'deletions', 'total_comment_count', 'unresolved_comment_count',
        'total_patchsets', 'n_files_changed', 'total_messages', 'n_reviewers',
        'first_review_delay_hours', 'avg_time_between_patchsets_hours',
        'ci_messages_count', 'time_open_hours',

        # --- TARGET / dérivé du graphe : NE JAMAIS UTILISER COMME FEATURE ---
        'graph_in_degree', 'graph_out_degree', 'target_is_bottleneck',
    ]

    rows = []
    n_missing_metrics = 0
    for num, n in by_number.items():
        row = {
            'number': n.get('number'),
            'change_id': n.get('change_id'),
            'project': n.get('project'),
            'branch': n.get('branch'),
            'topic': n.get('topic'),
            'status': n.get('status'),
            'created': n.get('created'),
            'updated': n.get('updated'),
            'submitted': n.get('submitted'),
            'work_in_progress': n.get('work_in_progress'),
            'mergeable': n.get('mergeable'),
            'node_source': n.get('source'),

            'insertions': n.get('insertions'),
            'deletions': n.get('deletions'),
            'total_comment_count': n.get('total_comment_count'),
            'unresolved_comment_count': n.get('unresolved_comment_count'),
            'total_patchsets': n.get('total_patchsets'),
            'n_files_changed': n.get('n_files_changed'),
            'total_messages': n.get('total_messages'),
            'n_reviewers': n.get('n_reviewers'),
            'first_review_delay_hours': n.get('first_review_delay_hours'),
            'avg_time_between_patchsets_hours': n.get('avg_time_between_patchsets_hours'),
            'ci_messages_count': n.get('ci_messages_count'),
            'time_open_hours': n.get('time_open_hours'),

            'graph_in_degree': in_degree.get(num, 0),
            'graph_out_degree': out_degree.get(num, 0),
            'target_is_bottleneck': is_bottleneck.get(num, False),
        }
        if n.get('total_patchsets') is None:
            n_missing_metrics += 1
        rows.append(row)

    with open(OUTPUT_CSV, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    n_bottleneck = sum(1 for r in rows if r['target_is_bottleneck'])

    print("=" * 60)
    print(f"💾 {len(rows)} lignes écrites dans {OUTPUT_CSV}")
    print(f"   dont {n_missing_metrics} lignes avec features de review manquantes (None)")
    print(f"   target_is_bottleneck = True pour {n_bottleneck} changes "
          f"({100 * n_bottleneck / len(rows):.2f}%)")
    print("=" * 60)
    print("\n⚠️ Rappel : les colonnes 'graph_in_degree', 'graph_out_degree' et")
    print("   'target_is_bottleneck' ne doivent JAMAIS servir de features (X).")
    print("   Elles définissent uniquement le label (y) à prédire.")
    print("   X = toutes les colonnes du groupe FEATURES ci-dessus.")


if __name__ == '__main__':
    main()