"""
backfill_meta.py — Reconstrói betMeta para apostas sem metadados.

Para cada betId em betOutcomes (verde/vermelho) que não tem betMeta
ou tem betMeta incompleto (sem 'p', 'date' ou 'leagueKey'), recomputa
p usando o mesmo modelo Poisson do JS e grava no Firestore.

Uso:
  FIREBASE_SERVICE_ACCOUNT='<json>' python backfill_meta.py

  # Modo dry-run (não grava no Firestore, só mostra o que faria):
  FIREBASE_SERVICE_ACCOUNT='<json>' python backfill_meta.py --dry-run
"""

import json
import math
import os
import sys
from datetime import date as dt_date

import firebase_admin
from firebase_admin import credentials, firestore

LEAGUES = [
    'brasileirao', 'premier', 'laliga', 'bundesliga',
    'ligue1', 'saudi', 'argentina', 'seriea', 'mls',
]

LEAGUE_NAMES = {
    'brasileirao': 'Brasileirao Serie A',
    'premier':     'Premier League',
    'laliga':      'La Liga',
    'bundesliga':  'Bundesliga',
    'ligue1':      'Ligue 1',
    'seriea':      'Serie A',
    'argentina':   'Liga Profesional',
    'saudi':       'Saudi Pro League',
    'mls':         'MLS',
}

TODAY    = dt_date.today().isoformat()
DRY_RUN  = '--dry-run' in sys.argv
BATCH_SZ = 400  # Firestore limit é 500; margem de segurança


# ── ID encoding ───────────────────────────────────────────────────────────────

def decode_id(encoded):
    return encoded.replace('__pipe__', '|').replace('__slash__', '/')

def encode_id(bet_id):
    return bet_id.replace('|', '__pipe__').replace('/', '__slash__')


# ── Poisson (espelho exato do JS) ─────────────────────────────────────────────

def poisson_pmf(lam, k):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    log_p = -lam + k * math.log(lam)
    for i in range(1, int(k) + 1):
        log_p -= math.log(i)
    return math.exp(log_p)

def poisson_cdf(lam, k):
    return min(1.0, sum(poisson_pmf(lam, i) for i in range(int(k) + 1)))

def p_over(lam, thr):
    return 1.0 - poisson_cdf(lam, math.floor(thr))

def goal_probs(lH, lA):
    N = 10
    pH = pD = pA = 0.0
    for h in range(N + 1):
        ph = poisson_pmf(lH, h)
        for a in range(N + 1):
            p = ph * poisson_pmf(lA, a)
            if   h > a:  pH += p
            elif h == a: pD += p
            else:        pA += p
    return {'win': pH, 'draw': pD, 'loss': pA}


# ── Agregação de times / médias de liga ───────────────────────────────────────

def aggregate_games(games):
    by_team = {}
    for g in games:
        for is_home in (True, False):
            name = g['homeTeam'] if is_home else g['awayTeam']
            if name not in by_team:
                by_team[name] = {'jH': 0, 'jA': 0,
                                 'gpc': 0, 'gcc': 0, 'gpf': 0, 'gcf': 0,
                                 'esc_c': 0, 'esc_f': 0,
                                 'shots_c': 0, 'shots_f': 0}
            t    = by_team[name]
            side = 'home' if is_home else 'away'
            gs   = g['score']['home'] if is_home else g['score']['away']
            gc   = g['score']['away'] if is_home else g['score']['home']

            if is_home:
                t['jH']  += 1
                t['gpc'] += gs
                t['gcc'] += gc
            else:
                t['jA']  += 1
                t['gpf'] += gs
                t['gcf'] += gc

            sa = (g.get('stats') or {})
            if isinstance(sa, dict):
                sa = sa.get('all') or {}
            else:
                sa = {}

            c = sa.get('corners')
            if c:
                if is_home: t['esc_c'] += c.get(side, 0) or 0
                else:       t['esc_f'] += c.get(side, 0) or 0

            sh = sa.get('shots')
            if sh:
                if is_home: t['shots_c'] += sh.get(side, 0) or 0
                else:       t['shots_f'] += sh.get(side, 0) or 0

    return by_team

def lg_goal_avgs(games):
    if not games: return {'h': 1.35, 'a': 1.20}
    n  = len(games)
    sh = sum(g['score']['home'] for g in games)
    sa = sum(g['score']['away'] for g in games)
    return {'h': sh / n, 'a': sa / n}

def lg_corners_avg(games):
    tc = n = 0
    for g in games:
        c = ((g.get('stats') or {}).get('all') or {}).get('corners')
        if c:
            tc += (c.get('home') or 0) + (c.get('away') or 0)
            n  += 1
    return tc / n if n else 9.5

def lg_foul_avg(games):
    tf = n = 0
    for g in games:
        f = ((g.get('stats') or {}).get('all') or {}).get('fouls')
        if f:
            tf += (f.get('home') or 0) + (f.get('away') or 0)
            n  += 1
    return tf / n if n else 26.0

def lg_shots_avg(games):
    ts = n = 0
    for g in games:
        s = ((g.get('stats') or {}).get('all') or {}).get('shots')
        if s:
            ts += (s.get('home') or 0) + (s.get('away') or 0)
            n  += 1
    return ts / n if n else 24.0

def lg_cards_avg(games):
    if not games: return 3.5
    total = sum(len(g.get('cards') or []) for g in games)
    return total / len(games)


# ── Motor de probabilidades (espelho de computeMatchInsights) ─────────────────

def compute_bet_p(label, home_team, away_team, games):
    """
    Retorna p (float 0–1) para o label dado usando o modelo Poisson bivariado.
    Usa médias de liga como prior para cartões/faltas (sem dado de árbitro).
    Retorna None se label desconhecido ou times sem dados.
    """
    by_team = aggregate_games(games)
    H = by_team.get(home_team)
    A = by_team.get(away_team)
    if not H or not A:
        return None

    lg = lg_goal_avgs(games)
    jH = H['jH']
    jA = A['jA']
    k  = 5  # Bayesian shrinkage

    lH_raw = (H['gpc'] / jH / lg['h']) * (A['gcf'] / max(1, jA) / lg['h']) * lg['h'] if jH > 0 else lg['h']
    lA_raw = (A['gpf'] / jA / lg['a']) * (H['gcc'] / max(1, jH) / lg['a']) * lg['a'] if jA > 0 else lg['a']
    lH = (max(1, jH) * lH_raw + k * lg['h']) / (max(1, jH) + k)
    lA = (max(1, jA) * lA_raw + k * lg['a']) / (max(1, jA) + k)
    lTot = lH + lA

    lgC   = lg_corners_avg(games)
    nC    = min(max(1, jH), max(1, jA))
    cornH = H['esc_c'] / max(1, jH) if H['esc_c'] > 0 else lgC / 2
    cornA = A['esc_f'] / max(1, jA) if A['esc_f'] > 0 else lgC / 2
    lC    = (nC * (cornH + cornA) + k * lgC) / (nC + k)

    lgCards = max(1.0, lg_cards_avg(games))
    lCards  = lgCards  # sem dado de árbitro → usa média da liga

    lgFouls = lg_foul_avg(games)
    lFouls  = lgFouls

    lgS    = lg_shots_avg(games)
    _jH    = max(1, jH)
    _jA    = max(1, jA)
    shotH  = H['shots_c'] / _jH if H['shots_c'] > 0 else lgS / 2
    shotA  = A['shots_f'] / _jA if A['shots_f'] > 0 else lgS / 2
    lShots = (min(_jH, _jA) * (shotH + shotA) + k * lgS) / (min(_jH, _jA) + k)

    pBTTS = (1 - poisson_cdf(lH, 0)) * (1 - poisson_cdf(lA, 0))
    res   = goal_probs(lH, lA)

    TABLE = {
        'Over 1.5 gols':           p_over(lTot, 1.5),
        'Under 1.5 gols':          1 - p_over(lTot, 1.5),
        'Over 2.5 gols':           p_over(lTot, 2.5),
        'Under 2.5 gols':          1 - p_over(lTot, 2.5),
        'Over 3.5 gols':           p_over(lTot, 3.5),
        'Under 3.5 gols':          1 - p_over(lTot, 3.5),
        'BTTS - Sim':              pBTTS,
        'BTTS - Nao':              1 - pBTTS,
        'Vitoria Mandante':        res['win'],
        'Empate':                  res['draw'],
        'Vitoria Visitante':       res['loss'],
        'Over 8.5 escanteios':     p_over(lC, 8.5),
        'Over 9.5 escanteios':     p_over(lC, 9.5),
        'Over 10.5 escanteios':    p_over(lC, 10.5),
        'Over 11.5 escanteios':    p_over(lC, 11.5),
        'Under 8.5 escanteios':    1 - p_over(lC, 8.5),
        'Over 3.5 cartoes':        p_over(lCards, 3.5),
        'Over 4.5 cartoes':        p_over(lCards, 4.5),
        'Over 5.5 cartoes':        p_over(lCards, 5.5),
        'Under 3.5 cartoes':       1 - p_over(lCards, 3.5),
        'Over 20.5 faltas':        p_over(lFouls, 20.5),
        'Over 22.5 faltas':        p_over(lFouls, 22.5),
        'Over 24.5 faltas':        p_over(lFouls, 24.5),
        'Over 26.5 faltas':        p_over(lFouls, 26.5),
        'Over 28.5 faltas':        p_over(lFouls, 28.5),
        'Over 30.5 faltas':        p_over(lFouls, 30.5),
        'Under 22.5 faltas':       1 - p_over(lFouls, 22.5),
        'Under 26.5 faltas':       1 - p_over(lFouls, 26.5),
        'Over 20.5 finalizacoes':  p_over(lShots, 20.5),
        'Over 22.5 finalizacoes':  p_over(lShots, 22.5),
        'Over 24.5 finalizacoes':  p_over(lShots, 24.5),
        'Over 26.5 finalizacoes':  p_over(lShots, 26.5),
        'Over 28.5 finalizacoes':  p_over(lShots, 28.5),
        'Under 20.5 finalizacoes': 1 - p_over(lShots, 20.5),
        'Under 22.5 finalizacoes': 1 - p_over(lShots, 22.5),
    }

    return TABLE.get(label)


# ── Carga dos JSONs ───────────────────────────────────────────────────────────

def load_league_data():
    data = {}
    for lk in LEAGUES:
        for fname in (f'{lk}_2026_data.json', f'{lk}_data.json', f'{lk}_league_data.json'):
            if os.path.exists(fname):
                try:
                    with open(fname, encoding='utf-8') as f:
                        data[lk] = json.load(f)
                    print(f'  [{lk}] {len(data[lk].get("games", []))} jogos', flush=True)
                except Exception as e:
                    print(f'  [{lk}] erro ao ler: {e}', flush=True)
                break
    return data


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if DRY_RUN:
        print('⚠️  Modo DRY-RUN: nenhuma escrita no Firestore.', flush=True)

    sa_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT', '')
    if not sa_json:
        print('FIREBASE_SERVICE_ACCOUNT não definida.', flush=True)
        sys.exit(1)

    cred = credentials.Certificate(json.loads(sa_json))
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    print('\n── Carregando JSONs das ligas ───────────────────────────────', flush=True)
    league_data = load_league_data()

    # Índice rápido: liga → "home_away" → game
    game_idx = {}
    for lk, d in league_data.items():
        game_idx[lk] = {
            g['homeTeam'] + '_' + g['awayTeam']: g
            for g in d.get('games', []) if 'homeTeam' in g and 'awayTeam' in g
        }

    print('\n── Lendo Firestore ──────────────────────────────────────────', flush=True)
    outcomes = {}
    for doc in db.collection('betOutcomes').stream():
        val = doc.to_dict().get('value', 'cinza')
        if val in ('verde', 'vermelho'):
            outcomes[decode_id(doc.id)] = val
    print(f'  {len(outcomes)} betOutcomes verde/vermelho', flush=True)

    meta_map = {}
    for doc in db.collection('betMeta').stream():
        meta_map[decode_id(doc.id)] = doc.to_dict()
    print(f'  {len(meta_map)} betMeta existentes', flush=True)

    print('\n── Identificando apostas sem metadados completos ───────────', flush=True)
    to_backfill = []
    for bet_id in outcomes:
        m = meta_map.get(bet_id, {})
        if m.get('p') and m.get('date') and m.get('leagueKey'):
            continue  # metadados completos
        to_backfill.append(bet_id)
    print(f'  {len(to_backfill)} apostas precisam de backfill', flush=True)
    print(f'  {len(outcomes) - len(to_backfill)} já têm metadados completos', flush=True)

    if not to_backfill:
        print('\n✅ Nenhuma aposta precisa de backfill.', flush=True)
        return

    print('\n── Recomputando e gravando metadados ────────────────────────', flush=True)
    writes  = []  # lista de (ref, meta) para commit em lotes
    n_ok    = 0
    n_no_game   = 0
    n_no_label  = 0
    n_no_band   = 0
    n_future    = 0

    for bet_id in to_backfill:
        parts = bet_id.split('|')
        if len(parts) < 4:
            n_no_game += 1
            continue

        lk    = parts[0]
        home  = parts[1]
        away  = parts[2]
        label = '|'.join(parts[3:])

        games = league_data.get(lk, {}).get('games', [])
        if not games:
            n_no_game += 1
            continue

        # Busca jogo no índice
        game = game_idx.get(lk, {}).get(home + '_' + away)
        if not game or not game.get('date'):
            n_no_game += 1
            continue

        game_date = game['date']
        if game_date > TODAY:
            n_future += 1
            continue

        # Recomputa p
        p = compute_bet_p(label, home, away, games)
        if p is None:
            n_no_label += 1
            continue

        # Verifica se p cairia numa banda (≥80%)
        p_r = round(p * 100) / 100
        in_band = any(b['min'] <= p_r < b['max']
                      for b in [{'min':0.95,'max':1.01},{'min':0.90,'max':0.95},
                                 {'min':0.85,'max':0.90},{'min':0.80,'max':0.85}])

        existing_meta = meta_map.get(bet_id, {})
        new_meta = {
            'p':          p,
            'date':       existing_meta.get('date') or game_date,
            'leagueKey':  lk,
            'leagueName': LEAGUE_NAMES.get(lk, lk),
        }

        band_tag = f'{round(p*100)}%' + ('' if in_band else ' [fora das bandas]')
        print(f'  {"DRY " if DRY_RUN else ""}{home} x {away} | {label[:40]:<40} → p={p:.3f} ({band_tag}) {game_date}', flush=True)

        if not in_band:
            n_no_band += 1
            if not DRY_RUN:
                # Grava mesmo assim — betMeta precisa existir para _saveAssertMeta funcionar
                ref = db.collection('betMeta').document(encode_id(bet_id))
                writes.append((ref, new_meta))
        else:
            n_ok += 1
            if not DRY_RUN:
                ref = db.collection('betMeta').document(encode_id(bet_id))
                writes.append((ref, new_meta))

    # Grava em lotes de BATCH_SZ
    if not DRY_RUN and writes:
        for start in range(0, len(writes), BATCH_SZ):
            chunk = writes[start:start + BATCH_SZ]
            batch = db.batch()
            for ref, meta in chunk:
                batch.set(ref, meta)
            batch.commit()
            print(f'  Lote {start//BATCH_SZ + 1}: {len(chunk)} gravados.', flush=True)

    total_written = len(writes)
    print(f'\n{"[DRY-RUN] " if DRY_RUN else ""}Resultado:', flush=True)
    print(f'  ✅ {n_ok} apostas com banda válida (≥80%)', flush=True)
    print(f'  ⚠️  {n_no_band} apostas com p fora das bandas (<80%) — gravadas mas não contabilizadas no histórico', flush=True)
    print(f'  ⏭️  {n_no_game} ignoradas (jogo não encontrado no JSON)', flush=True)
    print(f'  ⏭️  {n_no_label} ignoradas (label desconhecido)', flush=True)
    print(f'  ⏭️  {n_future} ignoradas (data futura)', flush=True)
    if not DRY_RUN:
        print(f'  📝 {total_written} documentos gravados no Firestore', flush=True)
        if n_ok > 0:
            print(f'\n  👉 Execute assertividade_sync.py para recomputar assertHistory com os novos metadados.', flush=True)


if __name__ == '__main__':
    main()
