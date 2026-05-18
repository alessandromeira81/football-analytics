"""
Gera endpoints publicos estaticos para consumo externo:
  api/daily-picks/{prob}.json  → picks com probabilidade >= prob (80, 85, 90, 95)
  api/track-record/{period}.json → 7d, 30d, all

Estrategia: abre index.html em headless Chrome (via Playwright), aguarda
o JS computar os insights e extrai via window.computeAllInsights().
Isso garante que os dados batem EXATAMENTE com o que o dashboard mostra.

URLs publicas finais (GitHub Pages, CORS aberto):
  https://alessandromeira81.github.io/football-analytics/api/daily-picks/90.json
  https://alessandromeira81.github.io/football-analytics/api/track-record/7d.json
"""
import json, os, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

REPO_ROOT = Path(__file__).parent.absolute()
HTML_PATH = REPO_ROOT / 'index.html'
API_DIR   = REPO_ROOT / 'api'

CONFIDENCE_BANDS = [
    (95, '95%'),
    (90, '90%'),
    (85, '85%'),
    (80, '80%'),
]


def category_to_market(cat):
    return {
        'Resultado':    'Resultado',
        'BTTS':         'BTTS',
        'Gols':         'Gols',
        'Escanteios':   'Escanteios',
        'Cartoes':      'Cartoes',
        'Faltas':       'Faltas',
        'Finalizacoes': 'Finalizacoes',
    }.get(cat, cat)


def confidence_band(prob_pct):
    for threshold, band in CONFIDENCE_BANDS:
        if prob_pct >= threshold:
            return band
    return None


def extract_via_playwright():
    """Abre index.html em headless Chrome e extrai insights + history."""
    from playwright.sync_api import sync_playwright

    file_url = HTML_PATH.as_uri()
    print(f'  Abrindo {file_url}', flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()

        # Silencia erros do console pra nao poluir log
        page.on('pageerror', lambda e: None)

        # Usa domcontentloaded em vez de networkidle (Firebase listener fica streamando)
        page.goto(file_url, wait_until='domcontentloaded', timeout=30000)

        # Aguarda SCRAPED_DATA e computeAllInsights estarem disponiveis
        page.wait_for_function(
            'window.SCRAPED_DATA && '
            'typeof window.computeAllInsights === "function" && '
            'Object.keys(window.SCRAPED_DATA).length > 0',
            timeout=30000
        )
        # Espera Firestore terminar (best-effort) — 5s e suficiente pra dados embutidos
        page.wait_for_timeout(5000)

        # Extrai todos os insights computados pelo modelo
        all_bets = page.evaluate('computeAllInsights()')
        # Extrai historico (ja agregado por data, bandas e ligas)
        history  = page.evaluate('ASSERT_HISTORY || []')
        # Extrai outcomes
        states   = page.evaluate('ASSERT_STATES || {}')

        browser.close()

    print(f'  Extraidos: {len(all_bets)} bets, {len(history)} entradas historicas', flush=True)
    return all_bets, history, states


def build_daily_picks(all_bets, states, min_prob):
    """Gera lista de picks para hoje filtrada por probabilidade minima."""
    today = date.today().isoformat()
    picks = []

    for b in all_bets:
        if b.get('date') != today:
            continue
        # p eh decimal (0-1); converte pra %
        p = b.get('p', 0)
        if p <= 1:
            prob_pct = round(p * 100)
        else:
            prob_pct = round(p)
        if prob_pct < min_prob:
            continue

        label    = b.get('label', '')
        home     = b.get('home', '')
        away     = b.get('away', '')
        cat      = b.get('cat', '')
        market   = category_to_market(cat)
        odds     = None
        game_odds = b.get('gameOdds') or {}
        # gameOdds pode estar como dict — tenta extrair melhor odd
        if isinstance(game_odds, dict):
            for v in game_odds.values():
                if isinstance(v, (int, float)) and v > 1:
                    odds = v
                    break

        # "pick" e a aposta legivel — derivacao simples a partir do label
        if label == 'Vitoria Mandante':
            pick_text = f'{home} vence'
        elif label == 'Vitoria Visitante':
            pick_text = f'{away} vence'
        elif label == 'Empate':
            pick_text = 'Empate'
        elif label == 'BTTS - Sim':
            pick_text = 'Ambas marcam'
        elif label == 'BTTS - Nao':
            pick_text = 'Pelo menos um time nao marca'
        else:
            pick_text = label

        picks.append({
            'league':          b.get('leagueName', b.get('leagueKey', '')),
            'league_key':      b.get('leagueKey', ''),
            'home_team':       home,
            'away_team':       away,
            'kickoff':         b.get('date', '') + 'T00:00:00Z',
            'market':          market,
            'pick':            pick_text,
            'label':           label,
            'probability':     prob_pct,
            'confidence_band': confidence_band(prob_pct),
            'odds':            odds,
            'bet_id':          b.get('betId', ''),
        })

    # Ordena por probabilidade desc
    picks.sort(key=lambda x: x['probability'], reverse=True)
    return picks


def build_track_record(history, period):
    """Agrega historico por periodo (7d, 30d, all)."""
    today = date.today()

    if period == 'all':
        filtered = history
    else:
        days = int(period.rstrip('d'))
        cutoff = (today - timedelta(days=days)).isoformat()
        filtered = [h for h in history if h.get('date', '') >= cutoff and h.get('date', '') < today.isoformat()]

    total_v = sum((h.get('total') or {}).get('verde', 0) for h in filtered)
    total_r = sum((h.get('total') or {}).get('vermelho', 0) for h in filtered)
    total   = total_v + total_r
    win_rate = round(total_v / total * 100, 1) if total else 0

    # Por liga (agrega leagues de cada entrada)
    league_agg = {}
    for h in filtered:
        for lk, ldata in (h.get('leagues') or {}).items():
            if lk not in league_agg:
                league_agg[lk] = {'name': ldata.get('name', lk), 'wins': 0, 'losses': 0}
            tot = ldata.get('total') or {}
            league_agg[lk]['wins']   += tot.get('verde', 0)
            league_agg[lk]['losses'] += tot.get('vermelho', 0)

    by_league = [
        {'league': v['name'], 'wins': v['wins'], 'losses': v['losses']}
        for v in sorted(league_agg.values(), key=lambda x: x['wins'] + x['losses'], reverse=True)
    ]

    # Por mercado: nao temos breakdown direto, agrega por banda (proxy)
    band_agg = {'rb-95': {'wins': 0, 'losses': 0},
                'rb-90': {'wins': 0, 'losses': 0},
                'rb-85': {'wins': 0, 'losses': 0},
                'rb-80': {'wins': 0, 'losses': 0}}
    for h in filtered:
        for bk, bv in (h.get('bands') or {}).items():
            if bk in band_agg:
                band_agg[bk]['wins']   += bv.get('verde', 0)
                band_agg[bk]['losses'] += bv.get('vermelho', 0)

    by_band = [
        {'band': k.replace('rb-', '') + '%+', 'wins': v['wins'], 'losses': v['losses']}
        for k, v in band_agg.items() if (v['wins'] + v['losses']) > 0
    ]

    return {
        'period':  period,
        'summary': {
            'total':    total,
            'wins':     total_v,
            'losses':   total_r,
            'win_rate': win_rate,
        },
        'by_league': by_league,
        'by_band':   by_band,
    }


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f'  ✓ {path.relative_to(REPO_ROOT)}', flush=True)


def main():
    print('=== generate_api.py ===', flush=True)
    print('Extraindo dados via Playwright headless...', flush=True)
    all_bets, history, states = extract_via_playwright()

    today = date.today().isoformat()
    generated_at = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    # ─── DAILY PICKS (4 variantes: 80, 85, 90, 95) ────────────────────
    print('\n→ Gerando daily-picks...', flush=True)
    for min_prob in [80, 85, 90, 95]:
        picks = build_daily_picks(all_bets, states, min_prob)
        write_json(API_DIR / 'daily-picks' / f'{min_prob}.json', {
            'date':         today,
            'generated_at': generated_at,
            'min_prob':     min_prob,
            'count':        len(picks),
            'picks':        picks,
        })

    # Default: min_prob = 90 (atalho)
    default_picks = build_daily_picks(all_bets, states, 90)
    write_json(API_DIR / 'daily-picks.json', {
        'date':         today,
        'generated_at': generated_at,
        'min_prob':     90,
        'count':        len(default_picks),
        'picks':        default_picks,
    })

    # ─── TRACK RECORD (3 variantes: 7d, 30d, all) ─────────────────────
    print('\n→ Gerando track-record...', flush=True)
    for period in ['7d', '30d', 'all']:
        tr = build_track_record(history, period)
        tr['generated_at'] = generated_at
        write_json(API_DIR / 'track-record' / f'{period}.json', tr)

    # Default: 7d (atalho)
    write_json(API_DIR / 'track-record.json', {
        **build_track_record(history, '7d'),
        'generated_at': generated_at,
    })

    # ─── Index README listando endpoints ──────────────────────────────
    write_json(API_DIR / 'index.json', {
        'service':     'Football Analytics Public API',
        'base_url':    'https://alessandromeira81.github.io/football-analytics/api',
        'cors':        'open (Access-Control-Allow-Origin: *)',
        'auth':        'none',
        'updated_at':  generated_at,
        'endpoints': [
            {
                'name': 'daily-picks',
                'description': 'Picks do dia filtrados por probabilidade minima',
                'urls': {
                    'default (90%+)': '/daily-picks.json',
                    '80%+':           '/daily-picks/80.json',
                    '85%+':           '/daily-picks/85.json',
                    '90%+':           '/daily-picks/90.json',
                    '95%+':           '/daily-picks/95.json',
                },
            },
            {
                'name': 'track-record',
                'description': 'Historico de assertividade agregado por periodo',
                'urls': {
                    'default (7d)': '/track-record.json',
                    '7 dias':       '/track-record/7d.json',
                    '30 dias':      '/track-record/30d.json',
                    'completo':     '/track-record/all.json',
                },
            },
        ],
    })

    print('\n✅ API gerada com sucesso.', flush=True)


if __name__ == '__main__':
    main()
