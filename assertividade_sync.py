"""
Sincroniza assertividade para o Firestore via GitHub Actions.
1. Lê betMeta do Firestore (quais apostas rastrear)
2. Lê JSONs de dados das ligas (resultados dos jogos)
3. Auto-preenche betOutcomes para jogos já encerrados
4. Recomputa assertHistory e grava no Firestore

Uso:
  FIREBASE_SERVICE_ACCOUNT='<json>' python assertividade_sync.py
"""

import json
import os
import re
import sys
from datetime import date as dt_date
import firebase_admin
from firebase_admin import credentials, firestore

LEAGUES = [
    'brasileirao', 'premier', 'laliga', 'bundesliga',
    'ligue1', 'saudi', 'argentina', 'seriea',
]

BANDS = [
    {'min': 0.90, 'max': 1.01, 'cls': 'rb-90'},
    {'min': 0.85, 'max': 0.90, 'cls': 'rb-85'},
    {'min': 0.80, 'max': 0.85, 'cls': 'rb-80'},
]

TODAY = dt_date.today().isoformat()  # 'yyyy-mm-dd'


# ── Firestore ID encoding ─────────────────────────────────────────────────────

def decode_id(encoded):
    return encoded.replace('__pipe__', '|').replace('__slash__', '/')

def encode_id(bet_id):
    return bet_id.replace('|', '__pipe__').replace('/', '__slash__')


# ── Avaliação de resultado de aposta ─────────────────────────────────────────

def evaluate_bet(label, game):
    """Retorna 'verde', 'vermelho' ou None (dados insuficientes)."""
    score = game.get('score') or {}
    sh, sa = score.get('home'), score.get('away')
    if sh is None or sa is None:
        return None  # jogo não encerrado

    tot   = sh + sa
    btts  = sh > 0 and sa > 0
    stats = (game.get('stats') or {}).get('all') or {}

    if label == 'Vitoria Mandante':  return 'verde' if sh > sa  else 'vermelho'
    if label == 'Empate':            return 'verde' if sh == sa else 'vermelho'
    if label == 'Vitoria Visitante': return 'verde' if sa > sh  else 'vermelho'
    if label == 'BTTS - Sim':        return 'verde' if btts     else 'vermelho'
    if label == 'BTTS - Nao':        return 'verde' if not btts else 'vermelho'

    # Gols
    m = re.match(r'^(Over|Under) (\d+\.5) gols$', label)
    if m:
        line = float(m.group(2))
        return 'verde' if (tot > line if m.group(1) == 'Over' else tot < line) else 'vermelho'

    # Escanteios
    co = stats.get('corners') or {}
    tot_co = (co.get('home') or 0) + (co.get('away') or 0)
    m = re.match(r'^(Over|Under) (\d+\.5) escanteios$', label)
    if m:
        if not (co.get('home') or co.get('away')):
            return None
        line = float(m.group(2))
        return 'verde' if (tot_co > line if m.group(1) == 'Over' else tot_co < line) else 'vermelho'

    # Cartões
    cards = game.get('cards') or []
    tot_cards = len([c for c in cards if isinstance(c, dict) and c.get('minute', -1) >= 0])
    m = re.match(r'^(Over|Under) (\d+\.5) cartoes$', label)
    if m:
        line = float(m.group(2))
        return 'verde' if (tot_cards > line if m.group(1) == 'Over' else tot_cards < line) else 'vermelho'

    # Faltas
    fo = stats.get('fouls') or {}
    m = re.match(r'^(Over|Under) (\d+\.5) faltas$', label)
    if m:
        if not (fo.get('home') or fo.get('away')):
            return None
        tot_fo = (fo.get('home') or 0) + (fo.get('away') or 0)
        line = float(m.group(2))
        return 'verde' if (tot_fo > line if m.group(1) == 'Over' else tot_fo < line) else 'vermelho'

    # Finalizações
    sh2 = stats.get('shots') or {}
    m = re.match(r'^(Over|Under) (\d+\.5) finalizacoes$', label)
    if m:
        if not (sh2.get('home') or sh2.get('away')):
            return None
        tot_sh = (sh2.get('home') or 0) + (sh2.get('away') or 0)
        line = float(m.group(2))
        return 'verde' if (tot_sh > line if m.group(1) == 'Over' else tot_sh < line) else 'vermelho'

    return None


# ── Carrega JSONs das ligas ───────────────────────────────────────────────────

def load_league_games():
    """Retorna dict: league_key → { 'homeTeam_awayTeam': game }"""
    game_idx = {}
    for league in LEAGUES:
        fname = f'{league}_2026_data.json'
        if not os.path.exists(fname):
            fname_alt = f'{league}_data.json'
            if not os.path.exists(fname_alt):
                continue
            fname = fname_alt
        try:
            with open(fname, encoding='utf-8') as f:
                data = json.load(f)
            games = data.get('games') or []
            game_idx[league] = {
                g['homeTeam'] + '_' + g['awayTeam']: g
                for g in games if 'homeTeam' in g and 'awayTeam' in g
            }
            print(f'  [{league}] {len(game_idx[league])} jogos encerrados', flush=True)
        except Exception as e:
            print(f'  [{league}] erro ao ler JSON: {e}', flush=True)
    return game_idx


def find_game_date(bet_id, game_idx):
    """Tenta recuperar a data real do jogo a partir do JSON."""
    parts = bet_id.split('|')
    if len(parts) < 4:
        return None
    league_key, home, away = parts[0], parts[1], parts[2]
    game = (game_idx.get(league_key) or {}).get(home + '_' + away)
    if game and game.get('date'):
        return game['date']
    return None


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    sa_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT', '')
    if not sa_json:
        print('FIREBASE_SERVICE_ACCOUNT não definida.', flush=True)
        sys.exit(1)

    cred = credentials.Certificate(json.loads(sa_json))
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    print('\n── Carregando JSONs das ligas ───────────────────────────────', flush=True)
    game_idx = load_league_games()

    print('\n── Lendo Firestore ──────────────────────────────────────────', flush=True)

    # betOutcomes existentes
    outcomes = {}
    for doc in db.collection('betOutcomes').stream():
        bet_id = decode_id(doc.id)
        val = doc.to_dict().get('value', 'cinza')
        outcomes[bet_id] = val
    print(f'  {len(outcomes)} betOutcomes lidos', flush=True)

    # betMeta
    meta_map = {}
    for doc in db.collection('betMeta').stream():
        bet_id = decode_id(doc.id)
        meta_map[bet_id] = doc.to_dict()
    print(f'  {len(meta_map)} betMeta lidos', flush=True)

    print('\n── Auto-fill de resultados ──────────────────────────────────', flush=True)
    batch = db.batch()
    n_filled = 0

    for bet_id, meta in meta_map.items():
        # Pula apostas com data futura (evita fantasmas)
        bet_date = meta.get('date', '')
        if bet_date > TODAY:
            continue
        # Pula se já tem resultado
        if outcomes.get(bet_id) in ('verde', 'vermelho'):
            continue

        parts = bet_id.split('|')
        if len(parts) < 4:
            continue
        league_key = parts[0]
        home       = parts[1]
        away       = parts[2]
        label      = '|'.join(parts[3:])

        games_for_league = game_idx.get(league_key, {})
        game = games_for_league.get(home + '_' + away)
        if not game:
            continue

        result = evaluate_bet(label, game)
        if not result:
            continue

        outcomes[bet_id] = result
        ref = db.collection('betOutcomes').document(encode_id(bet_id))
        batch.set(ref, {'value': result})
        print(f'  {home} x {away} | {label} → {result}', flush=True)
        n_filled += 1

    if n_filled > 0:
        batch.commit()
        print(f'  {n_filled} resultado(s) preenchido(s) automaticamente.', flush=True)
    else:
        print('  Nenhum resultado novo para preencher.', flush=True)

    print('\n── Recomputando assertHistory ───────────────────────────────', flush=True)

    # DEBUG: verifica correspondência de betIds entre outcomes e meta_map
    outcome_ids = set(outcomes.keys())
    meta_ids    = set(meta_map.keys())
    matched     = outcome_ids & meta_ids
    only_out    = outcome_ids - meta_ids
    only_meta   = meta_ids - outcome_ids
    print(f'  [DEBUG] outcomes com resultado verde/vermelho: {sum(1 for v in outcomes.values() if v in ("verde","vermelho"))}', flush=True)
    print(f'  [DEBUG] meta_map entries: {len(meta_ids)}', flush=True)
    print(f'  [DEBUG] betIds com resultado E meta: {len(matched)}', flush=True)
    print(f'  [DEBUG] betIds apenas em outcomes (sem meta): {len(only_out)}', flush=True)
    print(f'  [DEBUG] betIds apenas em meta (sem outcome): {len(only_meta)}', flush=True)
    # Mostra exemplos dos primeiros 5 de cada caso para comparação
    for bid in list(outcome_ids)[:5]:
        has_meta = bid in meta_map
        meta_p   = meta_map[bid].get('p', '—') if has_meta else '—'
        meta_dt  = meta_map[bid].get('date', '—') if has_meta else '—'
        print(f'  [SAMPLE OUT] {bid[:80]} → {outcomes[bid]} | meta={has_meta} p={meta_p} date={meta_dt}', flush=True)
    if only_out:
        print(f'  [SAMPLE ONLY_OUT] {list(only_out)[:3]}', flush=True)
    if only_meta:
        print(f'  [SAMPLE ONLY_META] {list(only_meta)[:3]}', flush=True)

    date_map = {}

    for bet_id, state in outcomes.items():
        if state not in ('verde', 'vermelho'):
            continue
        b = meta_map.get(bet_id, {})
        bet_date = b.get('date', '—')
        # Se a data do meta é futura, tenta recuperar do JSON
        if bet_date > TODAY:
            real_date = find_game_date(bet_id, game_idx)
            if real_date and real_date <= TODAY:
                bet_date = real_date
                # Corrige no Firestore para não repetir esse problema
                updated_meta = dict(b)
                updated_meta['date'] = real_date
                meta_map[bet_id] = updated_meta
                db.collection('betMeta').document(encode_id(bet_id)).set(updated_meta)
                print(f'  Corrigida data: {bet_id.split("|")[1]} x {bet_id.split("|")[2]} → {real_date}', flush=True)
            else:
                continue  # ainda futura, pula
        p           = b.get('p', 0) or 0
        league_key  = b.get('leagueKey', '')
        league_name = b.get('leagueName', league_key)

        band_key = None
        for band in BANDS:
            if band['min'] <= p < band['max']:
                band_key = band['cls']
                break
        if not band_key:
            if p > 0:  # só loga se realmente tem p, mas fora das bandas
                print(f'  [SKIP] p={p} fora das bandas (0.70-1.00): {bet_id[:60]}', flush=True)
            continue

        if bet_date not in date_map:
            date_map[bet_date] = {'bands': {}, 'leagues': {}}

        bands = date_map[bet_date]['bands']
        bands.setdefault(band_key, {'verde': 0, 'vermelho': 0})[state] += 1

        leagues = date_map[bet_date]['leagues']
        if league_key not in leagues:
            leagues[league_key] = {'name': league_name, 'bands': {}, 'total': {'verde': 0, 'vermelho': 0}}
        lg = leagues[league_key]
        lg['bands'].setdefault(band_key, {'verde': 0, 'vermelho': 0})[state] += 1
        lg['total'][state] += 1

    hist_batch = db.batch()
    for d, data in sorted(date_map.items()):
        bands = data['bands']
        tv = sum(b.get('verde', 0) for b in bands.values())
        tr = sum(b.get('vermelho', 0) for b in bands.values())
        entry = {
            'date':    d,
            'bands':   bands,
            'total':   {'verde': tv, 'vermelho': tr},
            'leagues': data['leagues'],
        }
        ref = db.collection('assertHistory').document(d)
        hist_batch.set(ref, entry)
        pct = round(tv / (tv + tr) * 100) if (tv + tr) else 0
        print(f'  {d}: {tv}V / {tr}R = {pct}%', flush=True)

    # Remove entradas fantasmas de datas futuras do Firestore
    for doc in db.collection('assertHistory').stream():
        if doc.id > TODAY:
            hist_batch.delete(doc.reference)
            print(f'  Removido entrada futura: {doc.id}', flush=True)

    hist_batch.commit()
    print(f'\n✅ {len(date_map)} dia(s) sincronizado(s) no Firestore.', flush=True)


if __name__ == '__main__':
    main()
