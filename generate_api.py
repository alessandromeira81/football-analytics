"""
Gera endpoints publicos estaticos para consumo externo:
  api/daily-picks/{prob}.json         → picks com probabilidade >= prob
  api/track-record/{period}.json      → track-record TOTAL (todas probs)
  api/track-record-90/{period}.json   → track-record SO 90%+

Estrategia: abre index.html em headless Chrome (via Playwright), aguarda
o JS computar os insights e extrai via window.computeAllInsights() +
ASSERT_META + ASSERT_STATES. Isso garante que os dados batem 100% com
o que o dashboard mostra.

URLs publicas finais (jsDelivr CDN, CORS aberto):
  https://cdn.jsdelivr.net/gh/alessandromeira81/football-analytics@main/api/<path>
"""
import json, os, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

REPO_ROOT = Path(__file__).parent.absolute()
HTML_PATH = (REPO_ROOT / 'app.html' if (REPO_ROOT / 'app.html').exists() else REPO_ROOT / 'index.html')
API_DIR   = REPO_ROOT / 'api'

CONFIDENCE_BANDS = [
    (95, '95%+'),
    (90, '90%+'),
    (85, '85%+'),
    (80, '80%+'),
]

# Mapeamento label → chaves gameOdds (mesmo do app.html BET_TO_MARKET_KEYS)
BET_TO_MARKET_KEYS = {
    'Vitoria Mandante':         ['Full time_1'],
    'Empate':                   ['Full time_X'],
    'Vitoria Visitante':        ['Full time_2'],
    'BTTS - Sim':               ['Both teams to score_Yes'],
    'BTTS - Nao':               ['Both teams to score_No'],
    'Over 1.5 gols':            ['Match goals_1.5_Over'],
    'Under 1.5 gols':           ['Match goals_1.5_Under'],
    'Over 2.5 gols':            ['Match goals_2.5_Over'],
    'Under 2.5 gols':           ['Match goals_2.5_Under'],
    'Over 3.5 gols':            ['Match goals_3.5_Over'],
    'Under 3.5 gols':           ['Match goals_3.5_Under'],
    'Over 8.5 escanteios':      ['Corners 2-Way_8.5_Over'],
    'Over 9.5 escanteios':      ['Corners 2-Way_9.5_Over'],
    'Over 10.5 escanteios':     ['Corners 2-Way_10.5_Over'],
    'Over 11.5 escanteios':     ['Corners 2-Way_11.5_Over'],
    'Under 8.5 escanteios':     ['Corners 2-Way_8.5_Under'],
    'Over 3.5 cartoes':         ['Cards in match_3.5_Over'],
    'Over 4.5 cartoes':         ['Cards in match_4.5_Over'],
    'Over 5.5 cartoes':         ['Cards in match_5.5_Over'],
    'Under 3.5 cartoes':        ['Cards in match_3.5_Under'],
}


def get_category(label):
    if label in ('Vitoria Mandante', 'Empate', 'Vitoria Visitante'): return 'Resultado'
    if label.startswith('BTTS'): return 'BTTS'
    ll = label.lower()
    if 'gols' in ll: return 'Gols'
    if 'escanteios' in ll: return 'Escanteios'
    if 'cartoes' in ll: return 'Cartoes'
    if 'faltas' in ll: return 'Faltas'
    if 'finalizacoes' in ll: return 'Finalizacoes'
    return 'Outros'


def confidence_band(prob_pct):
    for threshold, band in CONFIDENCE_BANDS:
        if prob_pct >= threshold:
            return band
    return None


def extract_via_playwright():
    """Abre index.html em headless Chrome e extrai dados granulares."""
    from playwright.sync_api import sync_playwright

    file_url = HTML_PATH.as_uri()
    print(f'  Abrindo {file_url}', flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.on('pageerror', lambda e: None)

        page.goto(file_url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_function(
            'window.SCRAPED_DATA && '
            'typeof window.computeAllInsights === "function" && '
            'Object.keys(window.SCRAPED_DATA).length > 0',
            timeout=30000
        )
        page.wait_for_timeout(5000)

        all_bets    = page.evaluate('computeAllInsights()')
        assert_meta = page.evaluate('ASSERT_META || {}')
        states      = page.evaluate('ASSERT_STATES || {}')

        browser.close()

    print(f'  Extraidos: {len(all_bets)} bets atuais, {len(assert_meta)} meta, {len(states)} states', flush=True)
    return all_bets, assert_meta, states


def get_bet_p(meta):
    """Retorna p (decimal 0-1) priorizando p_original."""
    p = meta.get('p_original') or meta.get('p', 0) or 0
    if p > 1:
        p = p / 100
    return p


def _format_pick(b, prob_pct):
    """Formata um bet em um pick legivel."""
    label  = b.get('label', '')
    home   = b.get('home', '')
    away   = b.get('away', '')
    cat    = b.get('cat', '') or get_category(label)

    # Odd: usa mapeamento label → chave gameOdds para pegar a odd correta
    odds = None
    label  = b.get('label', '')
    game_odds = b.get('gameOdds') or {}
    if isinstance(game_odds, dict) and label in BET_TO_MARKET_KEYS:
        for key in BET_TO_MARKET_KEYS[label]:
            v = game_odds.get(key)
            if isinstance(v, (int, float)) and v > 1.01:
                odds = v
                break

    # Pick legivel
    if   label == 'Vitoria Mandante':  pick_text = f'{home} vence'
    elif label == 'Vitoria Visitante': pick_text = f'{away} vence'
    elif label == 'Empate':            pick_text = 'Empate'
    elif label == 'BTTS - Sim':        pick_text = 'Ambas marcam'
    elif label == 'BTTS - Nao':        pick_text = 'Pelo menos um time nao marca'
    else:                              pick_text = label

    return {
        'league':          b.get('leagueName', b.get('leagueKey', '')),
        'league_key':      b.get('leagueKey', ''),
        'home_team':       home,
        'away_team':       away,
        'kickoff':         b.get('date', '') + 'T00:00:00Z',
        'date':            b.get('date', ''),
        'market':          cat,
        'pick':            pick_text,
        'label':           label,
        'probability':     prob_pct,
        'confidence_band': confidence_band(prob_pct),
        'odds':            odds,
        'bet_id':          b.get('betId', ''),
    }


def build_daily_picks(all_bets, min_prob):
    """Picks de HOJE filtrados por min_prob (ordenado por probabilidade desc)."""
    today = date.today().isoformat()
    picks = []

    for b in all_bets:
        if b.get('date') != today:
            continue
        p = b.get('p', 0)
        if p > 1: p = p / 100
        prob_pct = round(p * 100)
        if prob_pct < min_prob:
            continue
        picks.append(_format_pick(b, prob_pct))

    picks.sort(key=lambda x: x['probability'], reverse=True)
    return picks


def build_upcoming_picks(all_bets, days, min_prob):
    """
    Picks dos PROXIMOS N dias (hoje inclusive ate hoje+days-1) filtrados por min_prob.
    Ordem: data asc, depois probabilidade desc.
    """
    today      = date.today()
    end_date   = today + timedelta(days=days - 1)
    today_str  = today.isoformat()
    end_str    = end_date.isoformat()

    picks = []
    for b in all_bets:
        bet_date = b.get('date', '')
        if not bet_date or bet_date < today_str or bet_date > end_str:
            continue
        p = b.get('p', 0)
        if p > 1: p = p / 100
        prob_pct = round(p * 100)
        if prob_pct < min_prob:
            continue
        picks.append(_format_pick(b, prob_pct))

    picks.sort(key=lambda x: (x['date'], -x['probability']))
    return picks


def normalize_bets(assert_meta, states):
    """
    Combina ASSERT_META + ASSERT_STATES em uma lista de bets resolvidos.
    Filtra para apenas bets com probabilidade >= 80% (mesma logica do dashboard).
    Retorna lista de dicts: {date, league_key, league_name, label, market, state, p_pct}
    """
    bets = []
    for bet_id, meta in assert_meta.items():
        state = states.get(bet_id)
        if state not in ('verde', 'vermelho'):
            continue
        date_str = meta.get('date') or ''
        if not date_str:
            continue
        parts = bet_id.split('|')
        if len(parts) < 4:
            continue
        label = '|'.join(parts[3:])
        league_key = parts[0]

        p = get_bet_p(meta)
        p_pct = round(p * 100)
        # Sistema so rastreia bets >= 80% como insights. Bets abaixo
        # podem estar no ASSERT_META por outros motivos mas nao contam.
        if p_pct < 80:
            continue

        bets.append({
            'date':        date_str,
            'league_key':  league_key,
            'league_name': meta.get('leagueName', league_key),
            'label':       label,
            'market':      get_category(label),
            'state':       state,
            'p_pct':       p_pct,
        })
    return bets


def build_track_record(bets, period, min_prob=None):
    """
    bets: lista normalizada (de normalize_bets)
    period: '7d', '30d', 'all' — periodo termina ONTEM (hoje exclusivo)
    min_prob: int (filtra bets com p_pct >= min_prob) ou None
    """
    today    = date.today()
    yesterday = today - timedelta(days=1)

    if period == 'all':
        start_date = None
        end_date   = yesterday  # exclui hoje
        day_list   = None
    else:
        days = int(period.rstrip('d'))
        end_date   = yesterday                       # ultimo dia = ontem
        start_date = yesterday - timedelta(days=days - 1)
        # Lista completa de dias (oldest -> newest), N dias terminando ontem
        day_list = [(start_date + timedelta(days=i)).isoformat() for i in range(days)]

    # Filtra bets pelo periodo e min_prob
    filtered = []
    for b in bets:
        try:
            d = date.fromisoformat(b['date'])
        except (ValueError, TypeError):
            continue
        if start_date and d < start_date:
            continue
        if d > end_date:
            continue
        if min_prob is not None and b['p_pct'] < min_prob:
            continue
        filtered.append(b)

    # Agregacoes
    summary    = {'total': 0, 'wins': 0, 'losses': 0, 'win_rate': 0.0}
    league_agg = {}  # league_key -> {league, total, wins, losses}
    market_agg = {}  # market -> {market, total, wins, losses}
    daily_agg  = {}  # date -> {date, wins, losses}
    # by_band: faixas de confianca (80%+, 85%+, 90%+, 95%+)
    band_order = ['95%+', '90%+', '85%+', '80%+']
    band_agg   = {k: {'band': k, 'total': 0, 'wins': 0, 'losses': 0} for k in band_order}

    for b in filtered:
        is_win = b['state'] == 'verde'

        summary['total'] += 1
        if is_win: summary['wins']   += 1
        else:      summary['losses'] += 1

        # by_league
        lk = b['league_key']
        if lk not in league_agg:
            league_agg[lk] = {'league': b['league_name'], 'total': 0, 'wins': 0, 'losses': 0}
        league_agg[lk]['total'] += 1
        if is_win: league_agg[lk]['wins']   += 1
        else:      league_agg[lk]['losses'] += 1

        # by_market
        mk = b['market']
        if mk not in market_agg:
            market_agg[mk] = {'market': mk, 'total': 0, 'wins': 0, 'losses': 0}
        market_agg[mk]['total'] += 1
        if is_win: market_agg[mk]['wins']   += 1
        else:      market_agg[mk]['losses'] += 1

        # daily
        ds = b['date']
        if ds not in daily_agg:
            daily_agg[ds] = {'date': ds, 'wins': 0, 'losses': 0}
        if is_win: daily_agg[ds]['wins']   += 1
        else:      daily_agg[ds]['losses'] += 1

        # by_band
        p = b['p_pct']
        if   p >= 95: bk = '95%+'
        elif p >= 90: bk = '90%+'
        elif p >= 85: bk = '85%+'
        else:         bk = '80%+'
        band_agg[bk]['total'] += 1
        if is_win: band_agg[bk]['wins']   += 1
        else:      band_agg[bk]['losses'] += 1

    # win_rate em decimal (0.81 = 81%)
    def wr(w, t): return round(w / t, 2) if t else 0.0
    summary['win_rate'] = wr(summary['wins'], summary['total'])

    by_league = []
    for v in league_agg.values():
        v['win_rate'] = wr(v['wins'], v['total'])
        by_league.append(v)
    by_league.sort(key=lambda x: (x['total'], x['wins']), reverse=True)

    by_market = []
    for v in market_agg.values():
        v['win_rate'] = wr(v['wins'], v['total'])
        by_market.append(v)
    by_market.sort(key=lambda x: (x['total'], x['wins']), reverse=True)

    by_band = []
    for k in band_order:
        v = band_agg[k]
        v['win_rate'] = wr(v['wins'], v['total'])
        by_band.append(v)

    # daily_results: para periodos N dias, garante TODOS os dias presentes
    if day_list is not None:
        daily_results = [
            daily_agg.get(d, {'date': d, 'wins': 0, 'losses': 0})
            for d in day_list
        ]
    else:
        # 'all': so dias com dados, oldest -> newest
        daily_results = sorted(daily_agg.values(), key=lambda x: x['date'])

    return {
        'period':        period,
        'min_prob':      min_prob,
        'summary':       summary,
        'by_band':       by_band,
        'by_league':     by_league,
        'by_market':     by_market,
        'daily_results': daily_results,
    }


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'  ✓ {path.relative_to(REPO_ROOT)}', flush=True)


def main():
    print('=== generate_api.py ===', flush=True)
    print('Extraindo dados via Playwright headless...', flush=True)
    all_bets, assert_meta, states = extract_via_playwright()

    today = date.today().isoformat()
    generated_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # ─── DAILY PICKS ──────────────────────────────────────────────────
    print('\n→ Gerando daily-picks...', flush=True)
    for min_prob in [80, 85, 90, 95]:
        picks = build_daily_picks(all_bets, min_prob)
        write_json(API_DIR / 'daily-picks' / f'{min_prob}.json', {
            'date':         today,
            'generated_at': generated_at,
            'min_prob':     min_prob,
            'count':        len(picks),
            'picks':        picks,
        })

    default_picks = build_daily_picks(all_bets, 90)
    write_json(API_DIR / 'daily-picks.json', {
        'date':         today,
        'generated_at': generated_at,
        'min_prob':     90,
        'count':        len(default_picks),
        'picks':        default_picks,
    })

    # ─── UPCOMING PICKS (proximos N dias) ─────────────────────────────
    print('\n→ Gerando upcoming-picks (proximos dias)...', flush=True)
    today_d   = date.today()
    for days in [3, 7]:
        end_d = today_d + timedelta(days=days - 1)
        for min_prob in [80, 85, 90, 95]:
            picks = build_upcoming_picks(all_bets, days, min_prob)
            write_json(API_DIR / 'upcoming-picks' / f'{days}d' / f'{min_prob}.json', {
                'from_date':    today_d.isoformat(),
                'to_date':      end_d.isoformat(),
                'days':         days,
                'generated_at': generated_at,
                'min_prob':     min_prob,
                'count':        len(picks),
                'picks':        picks,
            })

    # Default: 3 dias, 90%+
    default_upcoming = build_upcoming_picks(all_bets, 3, 90)
    write_json(API_DIR / 'upcoming-picks.json', {
        'from_date':    today_d.isoformat(),
        'to_date':      (today_d + timedelta(days=2)).isoformat(),
        'days':         3,
        'generated_at': generated_at,
        'min_prob':     90,
        'count':        len(default_upcoming),
        'picks':        default_upcoming,
    })

    # ─── TRACK RECORD ─────────────────────────────────────────────────
    print('\n→ Normalizando bets para track-record...', flush=True)
    bets_norm = normalize_bets(assert_meta, states)
    print(f'  {len(bets_norm)} bets resolvidos (verde/vermelho com meta)', flush=True)

    print('\n→ Gerando track-record (TOTAL — todas probabilidades)...', flush=True)
    for period in ['7d', '30d', 'all']:
        tr = build_track_record(bets_norm, period, min_prob=None)
        tr['generated_at'] = generated_at
        write_json(API_DIR / 'track-record' / f'{period}.json', tr)

    # Default: 7d
    tr_default = build_track_record(bets_norm, '7d', min_prob=None)
    tr_default['generated_at'] = generated_at
    write_json(API_DIR / 'track-record.json', tr_default)

    print('\n→ Gerando track-record-90 (apenas 90%+)...', flush=True)
    for period in ['7d', '30d', 'all']:
        tr = build_track_record(bets_norm, period, min_prob=90)
        tr['generated_at'] = generated_at
        write_json(API_DIR / 'track-record-90' / f'{period}.json', tr)

    tr90_default = build_track_record(bets_norm, '7d', min_prob=90)
    tr90_default['generated_at'] = generated_at
    write_json(API_DIR / 'track-record-90.json', tr90_default)

    # ─── INDEX descobrir endpoints ────────────────────────────────────
    write_json(API_DIR / 'index.json', {
        'service':    'Football Analytics Public API',
        'base_url':   'https://cdn.jsdelivr.net/gh/alessandromeira81/football-analytics@main/api',
        'cors':       'open (Access-Control-Allow-Origin: *)',
        'auth':       'none',
        'updated_at': generated_at,
        'endpoints': [
            {
                'name': 'daily-picks',
                'description': 'Picks do dia filtrados por probabilidade minima',
                'urls': {
                    'default (90%+)': '/daily-picks.json',
                    '80%+': '/daily-picks/80.json',
                    '85%+': '/daily-picks/85.json',
                    '90%+': '/daily-picks/90.json',
                    '95%+': '/daily-picks/95.json',
                },
            },
            {
                'name': 'upcoming-picks',
                'description': 'Picks dos proximos dias filtrados por probabilidade minima',
                'urls': {
                    'default (3d, 90%+)': '/upcoming-picks.json',
                    '3 dias 80%+': '/upcoming-picks/3d/80.json',
                    '3 dias 85%+': '/upcoming-picks/3d/85.json',
                    '3 dias 90%+': '/upcoming-picks/3d/90.json',
                    '3 dias 95%+': '/upcoming-picks/3d/95.json',
                    '7 dias 80%+': '/upcoming-picks/7d/80.json',
                    '7 dias 85%+': '/upcoming-picks/7d/85.json',
                    '7 dias 90%+': '/upcoming-picks/7d/90.json',
                    '7 dias 95%+': '/upcoming-picks/7d/95.json',
                },
            },
            {
                'name': 'track-record',
                'description': 'Historico de desempenho — TODAS as probabilidades',
                'urls': {
                    'default (7d)': '/track-record.json',
                    '7 dias':  '/track-record/7d.json',
                    '30 dias': '/track-record/30d.json',
                    'tudo':    '/track-record/all.json',
                },
            },
            {
                'name': 'track-record-90',
                'description': 'Historico de desempenho — APENAS picks 90%+',
                'urls': {
                    'default (7d)': '/track-record-90.json',
                    '7 dias':  '/track-record-90/7d.json',
                    '30 dias': '/track-record-90/30d.json',
                    'tudo':    '/track-record-90/all.json',
                },
            },
        ],
    })

    print('\n✅ API gerada com sucesso.', flush=True)


if __name__ == '__main__':
    main()
