"""
Version PARALLÉLISÉE + ENRICHIE : récupère les infos détaillées de tous les changements
référencés dans les edges (source ET target) qui manquent au dataset.

Nouveauté vs la version précédente :
  - Récupère désormais aussi : total_patchsets, nb de fichiers modifiés, nb de messages,
    nb de reviewers distincts, délai avant la première review humaine, délai moyen entre
    patchsets (proxy de "churn"/révisions demandées), et un compteur d'activité CI
    (heuristique basée sur les messages de bots CI type Zuul/Jenkins).
  - Ces champs sont des SIGNAUX PRÉCOCES au niveau du change : ils ne dépendent PAS du
    graphe de dépendances (in_degree/out_degree), donc ils peuvent servir de FEATURES
    pour prédire un target basé sur le graphe (ex: bottleneck) sans fuite de données.

Sortie : gerrit_full_dataset.json
"""

import json
import re
import time
import os
import threading
from datetime import datetime
import requests
from requests.adapters import HTTPAdapter, Retry
from concurrent.futures import ThreadPoolExecutor, as_completed

INPUT_FILE = "dependencie/gerrit_full_dataset.json"
OUTPUT_FILE = "gerrit_full_dataset.json"
CHECKPOINT_FILE = "checkpoint_missing_nodes.json"
BASE_URL = "https://review.opendev.org"

CHANGE_ID_RE = re.compile(r'^I[0-9a-f]{40}$', re.IGNORECASE)
NUMBER_RE = re.compile(r'^\d+$')
SHA_RE = re.compile(r'^[0-9a-f]{40}$', re.IGNORECASE)

# ---- Paramètres de vitesse ----
MAX_WORKERS = 16              # nombre de requêtes en parallèle (Gerrit tolère bien 10-20)
CHECKPOINT_EVERY = 200        # sauvegarde tous les N changements résolus
REQUEST_TIMEOUT = 20          # un peu plus long car on demande plus de données par change

# Options Gerrit à demander : on ajoute ALL_REVISIONS, MESSAGES, DETAILED_LABELS, CURRENT_FILES
CHANGE_OPTIONS = "&".join([
    "o=DETAILED_ACCOUNTS",
    "o=CURRENT_REVISION",
    "o=CURRENT_COMMIT",
    "o=CURRENT_FILES",
    "o=ALL_REVISIONS",     # nécessaire pour compter total_patchsets et leurs dates
    "o=DETAILED_LABELS",   # nécessaire pour lister les reviewers
    "o=MESSAGES",          # nécessaire pour total_messages, délai de 1ère review, activité CI
])

# Mots-clés heuristiques pour repérer les messages émis par des bots CI
CI_BOT_NAME_KEYWORDS = ("zuul", "jenkins", "ci bot", "build bot")
CI_MESSAGE_KEYWORDS = ("build failed", "build succeeded", "build superseded")

# Champs ajoutés par l'enrichissement : utilisés pour garder un schéma homogène
# même quand un node n'a pas pu être enrichi (change supprimé/privé/erreur API)
METRIC_FIELDS = [
    'total_patchsets', 'n_files_changed', 'total_messages', 'n_reviewers',
    'first_review_delay_hours', 'avg_time_between_patchsets_hours',
    'ci_messages_count', 'time_open_hours',
]


# ============================================================
# SESSION HTTP (pool de connexions dimensionné pour le parallélisme)
# ============================================================

def make_session():
    session = requests.Session()
    retries = Retry(total=4, backoff_factor=1.0,
                     status_forcelist=[429, 500, 502, 503, 504],
                     allowed_methods=["GET"])
    adapter = HTTPAdapter(max_retries=retries, pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


SESSION = make_session()


def gerrit_get(url):
    r = SESSION.get(url, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    text = r.text
    if text.startswith(")]}'"):
        text = text[4:]
    return json.loads(text)


# ============================================================
# NORMALISATION DES IDS
# ============================================================

def normalize_raw_id(raw_id):
    raw_id = raw_id.strip().rstrip('.,;')

    m = re.search(r'/\+/(\d+)', raw_id)
    if m:
        return m.group(1), 'number'

    m = re.match(r'^#?/c/(\d+)$', raw_id)
    if m:
        return m.group(1), 'number'

    m = re.match(r'^https?://[^/]+/(\d+)$', raw_id)
    if m:
        return m.group(1), 'number'

    if CHANGE_ID_RE.match(raw_id):
        return raw_id, 'change_id'

    if NUMBER_RE.match(raw_id):
        return raw_id, 'number'

    if SHA_RE.match(raw_id):
        return raw_id, 'commit_sha'

    m = re.match(r'^[\w\-/]+~[\w\-.]+~(I[0-9a-f]{40})$', raw_id, re.IGNORECASE)
    if m:
        return m.group(1), 'change_id'

    return raw_id, 'unknown'


# ============================================================
# PARSING DES DATES GERRIT
# ============================================================

def parse_gerrit_time(ts):
    """Gerrit renvoie des timestamps type '2021-01-01 12:34:56.123456789'."""
    if not ts:
        return None
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return None


# ============================================================
# CALCUL DES FEATURES DE REVIEW (signaux précoces, indépendants du graphe)
# ============================================================

def compute_review_metrics(ch):
    revisions = ch.get('revisions', {}) or {}
    total_patchsets = len(revisions)

    current_rev = ch.get('current_revision')
    cur_rev_data = revisions.get(current_rev, {}) if current_rev else {}
    files = cur_rev_data.get('files', {}) or {}
    n_files_changed = len(files)

    messages = ch.get('messages', []) or []
    total_messages = len(messages)

    created = parse_gerrit_time(ch.get('created'))
    owner_id = (ch.get('owner') or {}).get('_account_id')

    # Délai avant la première réaction humaine (hors auteur) : proxy du "temps de réponse review"
    first_review_delay_hours = None
    for m in messages:
        author_id = (m.get('author') or {}).get('_account_id')
        if author_id is not None and author_id != owner_id:
            m_time = parse_gerrit_time(m.get('date'))
            if m_time and created:
                first_review_delay_hours = round((m_time - created).total_seconds() / 3600, 2)
            break

    # Délai moyen entre patchsets successifs : proxy du "churn" / nb de révisions demandées
    patchset_times = sorted(
        t for t in (parse_gerrit_time(rev.get('created')) for rev in revisions.values()) if t
    )
    avg_time_between_patchsets_hours = None
    if len(patchset_times) > 1:
        deltas = [
            (patchset_times[i + 1] - patchset_times[i]).total_seconds() / 3600
            for i in range(len(patchset_times) - 1)
        ]
        avg_time_between_patchsets_hours = round(sum(deltas) / len(deltas), 2)

    # Reviewers distincts (via les votes détaillés sur tous les labels : Code-Review, Verified, etc.)
    reviewers = set()
    for label_data in (ch.get('labels', {}) or {}).values():
        for entry in label_data.get('all', []) or []:
            acc_id = entry.get('_account_id')
            if acc_id is not None and acc_id != owner_id:
                reviewers.add(acc_id)
    n_reviewers = len(reviewers)

    # Activité CI : heuristique basée sur les auteurs de messages / contenu des messages
    ci_messages_count = 0
    for m in messages:
        author_name = ((m.get('author') or {}).get('name') or '').lower()
        msg_text = (m.get('message') or '').lower()
        if any(k in author_name for k in CI_BOT_NAME_KEYWORDS) or \
           any(k in msg_text for k in CI_MESSAGE_KEYWORDS):
            ci_messages_count += 1

    # Durée d'ouverture du change (créé -> dernière mise à jour), utile comme signal de "vie" du change
    updated = parse_gerrit_time(ch.get('updated'))
    time_open_hours = None
    if created and updated:
        time_open_hours = round((updated - created).total_seconds() / 3600, 2)

    return {
        'total_patchsets': total_patchsets,
        'n_files_changed': n_files_changed,
        'total_messages': total_messages,
        'n_reviewers': n_reviewers,
        'first_review_delay_hours': first_review_delay_hours,
        'avg_time_between_patchsets_hours': avg_time_between_patchsets_hours,
        'ci_messages_count': ci_messages_count,
        'time_open_hours': time_open_hours,
    }


# ============================================================
# RÉCUPÉRATION D'UN CHANGEMENT
# ============================================================

def fetch_change_detail(query):
    url = f"{BASE_URL}/changes/?q={query}&n=1&{CHANGE_OPTIONS}"
    result = gerrit_get(url)
    return result[0] if result else None


def change_to_node(ch, source_tag):
    metrics = compute_review_metrics(ch)
    node = {
        'number': ch.get('_number'),
        'change_id': ch.get('change_id'),
        'project': ch.get('project'),
        'branch': ch.get('branch'),
        'subject': ch.get('subject', ''),
        'status': ch.get('status'),
        'topic': ch.get('topic'),
        'created': ch.get('created'),
        'updated': ch.get('updated'),
        'submitted': ch.get('submitted'),
        'insertions': ch.get('insertions', 0),
        'deletions': ch.get('deletions', 0),
        'total_comment_count': ch.get('total_comment_count', 0),
        'unresolved_comment_count': ch.get('unresolved_comment_count', 0),
        'work_in_progress': ch.get('work_in_progress', False),
        'mergeable': ch.get('mergeable', False),
        'source': source_tag,
    }
    node.update(metrics)
    return node


def resolve_one(val, kind):
    """Fonction exécutée par chaque thread : renvoie (val, node_dict_ou_None)."""
    if kind == 'number':
        query = val
    elif kind == 'change_id':
        query = val
    elif kind == 'commit_sha':
        query = f"commit:{val}"
    else:
        return val, None

    try:
        ch = fetch_change_detail(query)
        if ch:
            return val, change_to_node(ch, 'resolved')
        return val, None
    except Exception:
        return val, None


# ============================================================
# CHECKPOINT (thread-safe)
# ============================================================

checkpoint_lock = threading.Lock()


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'resolved_nodes': {}, 'failed_ids': []}


def save_checkpoint(state):
    with checkpoint_lock:
        with open(CHECKPOINT_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f)


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print(f"🚀 COMPLÉTION DU DATASET ENRICHI (parallèle, {MAX_WORKERS} workers)")
    print("=" * 60)

    with open(INPUT_FILE, 'r', encoding='utf-8') as f:
        data = json.load(f)

    nodes = data['nodes']
    edges = data['edges']

    known_by_number = {str(n['number']): n for n in nodes}
    known_by_change_id = {n['change_id']: n for n in nodes if n.get('change_id')}
    known_numbers = set(known_by_number.keys())

    print(f"Nodes déjà connus : {len(nodes)}")
    print(f"Edges à analyser  : {len(edges)}")

    # --- 1. IDs uniques référencés ---
    all_refs = set()
    for e in edges:
        all_refs.add(e['source'])
        all_refs.add(e['target'])
    print(f"IDs uniques référencés (source+target) : {len(all_refs)}")

    # --- 2. Normalisation ---
    normalized = {raw: normalize_raw_id(raw) for raw in all_refs}

    # IMPORTANT : on enrichit aussi les nodes ORIGINAUX (pas seulement les IDs manquants
    # référencés dans les edges). Sinon les nodes 'original' gardent un schéma incomplet
    # (pas de total_messages/n_reviewers/etc.) alors que les nodes 'resolved' les ont —
    # deux schémas différents dans le même fichier, ce qu'on veut éviter.
    to_fetch = {}

    # 2a. Tous les nodes déjà connus dans le fichier d'entrée -> à enrichir aussi
    for num in known_numbers:
        to_fetch[num] = 'number'

    # 2b. Les IDs référencés par les edges mais absents du fichier d'entrée
    for raw, (val, kind) in normalized.items():
        if kind == 'number' and val in known_numbers:
            continue  # déjà ajouté en 2a
        if kind == 'change_id' and val in known_by_change_id:
            # déjà présent via son change_id -> son 'number' est déjà dans to_fetch (2a)
            continue
        to_fetch[val] = kind

    print(f"Nodes originaux à enrichir            : {len(known_numbers)}")
    print(f"IDs supplémentaires à récupérer (edges) : {len(to_fetch) - len(known_numbers)}")
    print(f"Total d'IDs à traiter via l'API         : {len(to_fetch)}")

    # --- 3. Reprise du checkpoint ---
    state = load_checkpoint()
    resolved_nodes = state['resolved_nodes']
    failed_ids = set(state['failed_ids'])

    todo = [(v, k) for v, k in to_fetch.items() if v not in resolved_nodes and v not in failed_ids]
    print(f"Restant après reprise du checkpoint : {len(todo)}")

    # --- 4. Récupération PARALLÈLE ---
    if todo:
        start_time = time.time()
        done_count = 0

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(resolve_one, val, kind): val for val, kind in todo}

            for future in as_completed(futures):
                val = futures[future]
                try:
                    _, node = future.result()
                except Exception:
                    node = None

                if node:
                    resolved_nodes[val] = node
                else:
                    failed_ids.add(val)

                done_count += 1

                if done_count % CHECKPOINT_EVERY == 0:
                    save_checkpoint({'resolved_nodes': resolved_nodes, 'failed_ids': list(failed_ids)})
                    elapsed = time.time() - start_time
                    rate = done_count / elapsed if elapsed > 0 else 0
                    remaining = (len(todo) - done_count) / rate if rate > 0 else 0
                    print(f"  💾 {done_count}/{len(todo)} traités "
                          f"({rate:.1f}/s, ~{remaining/60:.1f} min restantes) "
                          f"[{len(resolved_nodes)} résolus, {len(failed_ids)} échecs]")

        save_checkpoint({'resolved_nodes': resolved_nodes, 'failed_ids': list(failed_ids)})
        total_time = time.time() - start_time
        print(f"\n⏱️ Résolution terminée en {total_time/60:.1f} min "
              f"({len(todo)/total_time:.1f} req/s en moyenne)")

    # --- 5. Construction du dataset final ---
    # Index des nodes enrichis par numéro (peu importe si la clé de fetch était un number,
    # un change_id ou un sha — on retrouve tout via node['number'])
    resolved_by_number = {str(node['number']): node for node in resolved_nodes.values()}

    final_nodes_by_number = {}

    # 5a. Nodes originaux : priorité à la version enrichie si elle existe, sinon on garde
    # les champs d'origine et on complète les métriques manquantes avec None (schéma homogène)
    for n in nodes:
        num = str(n['number'])
        if num in resolved_by_number:
            node = dict(resolved_by_number[num])
            node['source'] = 'original_enriched'
        else:
            node = dict(n)
            node['source'] = 'original_not_enriched'  # enrichissement impossible (change supprimé/privé/erreur API)
            for field in METRIC_FIELDS:
                node.setdefault(field, None)
        final_nodes_by_number[num] = node

    # 5b. Nodes découverts uniquement via les edges (absents du fichier d'entrée)
    for num, node in resolved_by_number.items():
        if num not in final_nodes_by_number:
            final_nodes_by_number[num] = node

    def to_number(raw):
        val, kind = normalized.get(raw, normalize_raw_id(raw))
        if kind == 'number':
            return val
        if kind == 'change_id':
            node = known_by_change_id.get(val) or resolved_nodes.get(val)
            return str(node['number']) if node else None
        if kind == 'commit_sha':
            node = resolved_nodes.get(val)
            return str(node['number']) if node else None
        return None

    final_edges = []
    unresolved = []
    for e in edges:
        s = to_number(e['source'])
        t = to_number(e['target'])
        if s and t:
            final_edges.append({'source': s, 'target': t, 'type': e['type']})
        else:
            unresolved.append(e)

    final_edges = [dict(t) for t in {tuple(sorted(d.items())) for d in final_edges}]

    output = {
        'generated_at': data.get('generated_at'),
        'source': data.get('source'),
        'total_nodes': len(final_nodes_by_number),
        'total_edges': len(final_edges),
        'nodes': list(final_nodes_by_number.values()),
        'edges': final_edges,
        'unresolved_edges': unresolved,
    }

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    n_enriched = sum(1 for n in final_nodes_by_number.values() if n['source'] == 'original_enriched')
    n_not_enriched = sum(1 for n in final_nodes_by_number.values() if n['source'] == 'original_not_enriched')
    n_new = sum(1 for n in final_nodes_by_number.values() if n['source'] == 'resolved')

    print("\n📊 Résumé final :")
    print(f"  Nodes total                        : {len(final_nodes_by_number)}")
    print(f"    dont originaux enrichis           : {n_enriched}")
    print(f"    dont originaux NON enrichis        : {n_not_enriched} (schéma complété avec None)")
    print(f"    dont nouveaux (via edges)          : {n_new}")
    print(f"  Edges normalisés                    : {len(final_edges)}")
    print(f"  Edges toujours non résolus           : {len(unresolved)}")
    print(f"\n💾 Sauvegardé dans {OUTPUT_FILE}")


if __name__ == '__main__':
    main()