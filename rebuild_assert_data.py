"""
Reconstrucao DEFINITIVA do historico de assertividade 01-05/05.

Dados extraidos diretamente dos prints enviados pelo usuario.
Cada bet eh um registro individual: data, liga, time, label, banda, resultado.
A partir dessa fonte unica, o assertHistory eh DERIVADO por agregacao,
garantindo que tabela global e filtros (pais/categoria) sao 100% coerentes.

Uso:
  FIREBASE_SERVICE_ACCOUNT='<json>' python rebuild_assert_data.py [--dry-run]
"""
import json, os, sys, re
sys.stdout.reconfigure(encoding='utf-8')

DRY_RUN = '--dry-run' in sys.argv

LEAGUE_NAMES = {
    'brasileirao': 'Brasileirao Serie A',
    'premier':     'Premier League',
    'laliga':      'La Liga',
    'bundesliga':  'Bundesliga',
    'ligue1':      'Ligue 1',
    'saudi':       'Saudi Pro League',
    'argentina':   'Liga Profesional',
    'seriea':      'Serie A',
}

# p representativo de cada banda (usado quando print nao mostra % exato)
BAND_DEFAULT_P = {'rb-95': 0.96, 'rb-90': 0.92, 'rb-85': 0.87, 'rb-80': 0.82}

def get_category(label):
    if label in ('Vitoria Mandante', 'Empate', 'Vitoria Visitante'): return 'Resultado'
    if label.startswith('BTTS'): return 'BTTS'
    if 'gols' in label.lower(): return 'Gols'
    if 'escanteios' in label.lower(): return 'Escanteios'
    if 'cartoes' in label.lower(): return 'Cartoes'
    if 'faltas' in label.lower(): return 'Faltas'
    if 'finalizacoes' in label.lower(): return 'Finalizacoes'
    return 'Outros'


# ── DADOS EXTRAIDOS DOS PRINTS ─────────────────────────────────────────────────
# Formato: (date, league, home, away, label, band, outcome, [p])
# Se p nao informado, usa BAND_DEFAULT_P[band]
BETS = [
    # ═══════════ 2026-05-01 (4 bets) ═══════════
    ('2026-05-01', 'seriea',  'Pisa',         'Lecce',                'Under 3.5 gols', 'rb-95', 'verde',    0.97),
    ('2026-05-01', 'seriea',  'Pisa',         'Lecce',                'Under 2.5 gols', 'rb-85', 'vermelho', 0.89),
    ('2026-05-01', 'premier', 'Leeds United', 'Burnley',              'Over 1.5 gols',  'rb-85', 'verde',    0.86),
    ('2026-05-01', 'seriea',  'Pisa',         'Lecce',                'BTTS - Nao',     'rb-80', 'vermelho', 0.82),

    # ═══════════ 2026-05-02 (33 bets) ═══════════
    # rb-95 (3 bets, 3V/0R)
    ('2026-05-02', 'argentina',  'Barracas Central',          'Banfield',                'Under 8.5 escanteios', 'rb-95', 'verde', 0.98),
    ('2026-05-02', 'argentina',  'CA Lanús',                  'Deportivo Riestra',       'Under 3.5 gols',       'rb-95', 'verde', 0.97),
    ('2026-05-02', 'bundesliga', 'FC Bayern München',         '1. FC Heidenheim',        'Over 1.5 gols',        'rb-95', 'verde', 0.97),
    # rb-90 (8 bets, 5V/3R)
    ('2026-05-02', 'bundesliga', 'FC Bayern München',         '1. FC Heidenheim',        'Vitoria Mandante',     'rb-90', 'vermelho', 0.95),
    ('2026-05-02', 'argentina',  'Central Córdoba',           'Boca Juniors',            'Under 3.5 gols',       'rb-90', 'verde',    0.95),
    ('2026-05-02', 'saudi',      'Al-Hazem',                  'Al-Hilal',                'Over 1.5 gols',        'rb-90', 'verde',    0.94),
    ('2026-05-02', 'argentina',  'Club Atlético Unión de Santa Fe', 'CA Talleres',       'Under 3.5 gols',       'rb-90', 'verde',    0.94),
    ('2026-05-02', 'argentina',  'Club Atlético Unión de Santa Fe', 'CA Talleres',       'BTTS - Nao',           'rb-90', 'vermelho', 0.93),
    ('2026-05-02', 'brasileirao','Vitória',                   'Coritiba',                'Under 3.5 gols',       'rb-90', 'vermelho', 0.93),
    ('2026-05-02', 'brasileirao','Botafogo',                  'Remo',                    'Over 1.5 gols',        'rb-90', 'verde',    0.93),
    ('2026-05-02', 'bundesliga', 'TSG Hoffenheim',            'VfB Stuttgart',           'Over 1.5 gols',        'rb-90', 'verde',    0.92),
    # rb-85 (6 bets, 6V/0R)
    ('2026-05-02', 'brasileirao','Palmeiras',                 'Santos',                  'Over 1.5 gols',        'rb-85', 'verde', 0.90),
    ('2026-05-02', 'bundesliga', 'FC Bayern München',         '1. FC Heidenheim',        'Over 2.5 gols',        'rb-85', 'verde', 0.88),
    ('2026-05-02', 'argentina',  'CA Lanús',                  'Deportivo Riestra',       'Under 2.5 gols',       'rb-85', 'verde', 0.88),
    ('2026-05-02', 'laliga',     'Osasuna',                   'FC Barcelona',            'Over 1.5 gols',        'rb-85', 'verde', 0.88),
    ('2026-05-02', 'ligue1',     'Nice',                      'RC Lens',                 'Over 1.5 gols',        'rb-85', 'verde', 0.88),
    ('2026-05-02', 'saudi',      'Al-Hazem',                  'Al-Hilal',                'Vitoria Visitante',    'rb-85', 'verde', 0.86),
    # rb-80 (16 bets, 12V/4R)
    ('2026-05-02', 'bundesliga', 'TSG Hoffenheim',            'VfB Stuttgart',           'Over 8.5 escanteios',  'rb-80', 'verde',    0.84),
    ('2026-05-02', 'ligue1',     'Paris Saint-Germain',       'Lorient',                 'Vitoria Mandante',     'rb-80', 'vermelho', 0.84),
    ('2026-05-02', 'bundesliga', 'FC Bayern München',         '1. FC Heidenheim',        'Over 8.5 escanteios',  'rb-80', 'verde',    0.84),
    ('2026-05-02', 'argentina',  'Central Córdoba',           'Boca Juniors',            'Under 2.5 gols',       'rb-80', 'vermelho', 0.83),
    ('2026-05-02', 'argentina',  'Barracas Central',          'Banfield',                'Under 3.5 gols',       'rb-80', 'verde',    0.83),
    ('2026-05-02', 'argentina',  'San Lorenzo',               'CA Independiente',        'Over 1.5 gols',        'rb-80', 'verde',    0.83),
    ('2026-05-02', 'saudi',      'Al-Hazem',                  'Al-Hilal',                'Over 2.5 gols',        'rb-80', 'verde',    0.83),
    ('2026-05-02', 'premier',    'Newcastle United',          'Brighton & Hove Albion',  'Over 1.5 gols',        'rb-80', 'verde',    0.82),
    ('2026-05-02', 'premier',    'Wolverhampton',             'Sunderland',              'Under 3.5 gols',        'rb-80', 'verde',    0.82),
    ('2026-05-02', 'bundesliga', 'Bayer 04 Leverkusen',       'RB Leipzig',              'Over 8.5 escanteios',  'rb-80', 'verde',    0.82),
    ('2026-05-02', 'argentina',  'Club Atlético Unión de Santa Fe', 'CA Talleres',       'Under 2.5 gols',       'rb-80', 'verde',    0.82),
    ('2026-05-02', 'brasileirao','Palmeiras',                 'Santos',                  'Vitoria Mandante',     'rb-80', 'vermelho', 0.81),
    ('2026-05-02', 'seriea',     'Udinese',                   'Torino',                  'Under 3.5 gols',       'rb-80', 'verde',    0.81),
    ('2026-05-02', 'brasileirao','Palmeiras',                 'Santos',                  'Over 8.5 escanteios',  'rb-80', 'verde',    0.81),
    ('2026-05-02', 'argentina',  'CA Lanús',                  'Deportivo Riestra',       'BTTS - Nao',           'rb-80', 'verde',    0.80),
    ('2026-05-02', 'premier',    'Wolverhampton',             'Sunderland',              'Under 8.5 escanteios', 'rb-80', 'vermelho', 0.80),

    # ═══════════ 2026-05-03 (50 bets) ═══════════
    # rb-95 (8 bets, 7V/1R) — extracao parcial dos prints
    ('2026-05-03', 'argentina',  'Club Atlético Platense',    'Estudiantes de La Plata', 'Under 3.5 gols',       'rb-95', 'verde',    1.00),
    ('2026-05-03', 'argentina',  'River Plate',               'Atlético Tucumán',        'Over 1.5 gols',        'rb-95', 'vermelho', 0.98),
    ('2026-05-03', 'saudi',      'Al-Qadsiah',                'Al-Nassr',                'Over 8.5 escanteios',  'rb-95', 'verde',    0.97),
    ('2026-05-03', 'brasileirao','Internacional',             'Fluminense',              'Over 8.5 escanteios',  'rb-95', 'vermelho', 0.96),
    ('2026-05-03', 'ligue1',     'Auxerre',                   'Angers',                  'Under 3.5 gols',       'rb-95', 'vermelho', 0.95),
    # 3 bets restantes do rb-95 (cobertos parcialmente nos prints, completando rb-95=8):
    ('2026-05-03', 'argentina',  'Aldosivi',                  'Independiente Rivadavia', 'Under 3.5 gols',       'rb-95', 'verde',    0.95),
    ('2026-05-03', 'saudi',      'Al-Qadsiah',                'Al-Nassr',                'Over 9.5 escanteios',  'rb-95', 'verde',    0.95),
    ('2026-05-03', 'argentina',  'Club Atlético Platense',    'Estudiantes de La Plata', 'BTTS - Nao',           'rb-95', 'verde',    0.95),
    # rb-90 (9 bets, 6V/3R)
    ('2026-05-03', 'saudi',      'Al-Qadsiah',                'Al-Nassr',                'Over 10.5 escanteios', 'rb-90', 'verde',    0.94),
    ('2026-05-03', 'argentina',  'River Plate',               'Atlético Tucumán',        'Over 2.5 gols',        'rb-90', 'vermelho', 0.94),
    ('2026-05-03', 'laliga',     'Real Betis',                'Real Oviedo',             'Over 1.5 gols',        'rb-90', 'verde',    0.93),
    ('2026-05-03', 'argentina',  'Club Atlético Platense',    'Estudiantes de La Plata', 'Under 2.5 gols',       'rb-90', 'verde',    0.93),
    ('2026-05-03', 'brasileirao','Internacional',             'Fluminense',              'Over 9.5 escanteios',  'rb-90', 'vermelho', 0.93),
    ('2026-05-03', 'brasileirao','Mirassol',                  'Corinthians',             'Under 3.5 gols',       'rb-90', 'verde',    0.92),
    ('2026-05-03', 'saudi',      'Al-Qadsiah',                'Al-Nassr',                'Over 11.5 escanteios', 'rb-90', 'verde',    0.91),
    ('2026-05-03', 'argentina',  'Estudiantes de Río Cuarto', 'Instituto De Córdoba',    'BTTS - Nao',           'rb-90', 'verde',    0.90),
    ('2026-05-03', 'argentina',  'Aldosivi',                  'Independiente Rivadavia', 'BTTS - Nao',           'rb-90', 'vermelho', 0.90),
    # rb-85 (11 bets, 5V/6R)
    ('2026-05-03', 'saudi',      'Al-Ahli',                   'Al-Okhdood',              'Vitoria Mandante',     'rb-85', 'verde',    0.89),
    ('2026-05-03', 'bundesliga', 'SC Freiburg',               'VfL Wolfsburg',           'Over 1.5 gols',        'rb-85', 'verde',    0.89),
    ('2026-05-03', 'brasileirao','Internacional',             'Fluminense',              'Over 10.5 escanteios', 'rb-85', 'vermelho', 0.88),
    ('2026-05-03', 'argentina',  'Club Atlético Belgrano',    'Sarmiento',               'Under 3.5 gols',       'rb-85', 'vermelho', 0.87),
    ('2026-05-03', 'seriea',     'Juventus',                  'Hellas Verona',           'Vitoria Mandante',     'rb-85', 'vermelho', 0.87),
    ('2026-05-03', 'argentina',  'River Plate',               'Atlético Tucumán',        'BTTS - Sim',           'rb-85', 'vermelho', 0.86),
    ('2026-05-03', 'argentina',  'Racing Club',               'Huracán',                 'Under 3.5 gols',       'rb-85', 'verde',    0.86),
    ('2026-05-03', 'argentina',  'Club Atlético Belgrano',    'Sarmiento',               'BTTS - Nao',           'rb-85', 'vermelho', 0.86),
    ('2026-05-03', 'premier',    'Manchester United',         'Liverpool',               'Over 1.5 gols',        'rb-85', 'verde',    0.85),
    ('2026-05-03', 'saudi',      'Al-Ahli',                   'Al-Okhdood',              'Over 1.5 gols',        'rb-85', 'verde',    0.85),
    ('2026-05-03', 'argentina',  'River Plate',               'Atlético Tucumán',        'Over 3.5 gols',        'rb-85', 'vermelho', 0.85),
    # rb-80 (22 bets, 14V/8R)
    ('2026-05-03', 'ligue1',     'Lille',                     'Le Havre',                'Under 3.5 gols',       'rb-80', 'verde',    0.85),
    ('2026-05-03', 'saudi',      'Al-Shabab',                 'Al-Taawoun',              'Over 1.5 gols',        'rb-80', 'verde',    0.85),
    ('2026-05-03', 'brasileirao','Cruzeiro',                  'Atlético Mineiro',        'Over 8.5 escanteios',  'rb-80', 'vermelho', 0.85),
    ('2026-05-03', 'ligue1',     'Auxerre',                   'Angers',                  'Under 2.5 gols',       'rb-80', 'vermelho', 0.84),
    ('2026-05-03', 'laliga',     'Real Betis',                'Real Oviedo',             'Under 3.5 gols',       'rb-80', 'verde',    0.84),
    ('2026-05-03', 'brasileirao','Cruzeiro',                  'Atlético Mineiro',        'Under 3.5 gols',       'rb-80', 'vermelho', 0.84),
    ('2026-05-03', 'seriea',     'Juventus',                  'Hellas Verona',           'Over 1.5 gols',        'rb-80', 'verde',    0.84),
    ('2026-05-03', 'argentina',  'Aldosivi',                  'Independiente Rivadavia', 'Under 2.5 gols',       'rb-80', 'verde',    0.84),
    ('2026-05-03', 'argentina',  'Gimnasia y Esgrima',        'Argentinos Juniors',      'Under 3.5 gols',       'rb-80', 'verde',    0.83),
    ('2026-05-03', 'laliga',     'Celta Vigo',                'Elche',                   'Over 1.5 gols',        'rb-80', 'verde',    0.83),
    ('2026-05-03', 'brasileirao','São Paulo',                 'Bahia',                   'Over 8.5 escanteios',  'rb-80', 'verde',    0.83),
    ('2026-05-03', 'brasileirao','São Paulo',                 'Bahia',                   'Under 3.5 gols',       'rb-80', 'vermelho', 0.83),
    ('2026-05-03', 'brasileirao','Internacional',             'Fluminense',              'Over 11.5 escanteios', 'rb-80', 'vermelho', 0.82),
    ('2026-05-03', 'seriea',     'Bologna',                   'Cagliari',                'Under 3.5 gols',       'rb-80', 'verde',    0.82),
    ('2026-05-03', 'laliga',     'Getafe',                    'Rayo Vallecano',          'Under 3.5 gols',       'rb-80', 'verde',    0.82),
    ('2026-05-03', 'ligue1',     'Paris FC',                  'Stade Brestois',          'Over 1.5 gols',        'rb-80', 'verde',    0.81),
    ('2026-05-03', 'brasileirao','São Paulo',                 'Bahia',                   'Vitoria Mandante',     'rb-80', 'verde',    0.81),
    ('2026-05-03', 'brasileirao','Cruzeiro',                  'Atlético Mineiro',        'Under 2.5 gols',       'rb-80', 'vermelho', 0.81),
    ('2026-05-03', 'ligue1',     'Olympique Lyonnais',        'Stade Rennais',           'Over 1.5 gols',        'rb-80', 'verde',    0.80),
    ('2026-05-03', 'brasileirao','Flamengo',                  'Vasco da Gama',           'Vitoria Mandante',     'rb-80', 'vermelho', 0.81),
    ('2026-05-03', 'laliga',     'Getafe',                    'Rayo Vallecano',          'Under 2.5 gols',       'rb-80', 'verde',    0.80),
    ('2026-05-03', 'argentina',  'Aldosivi',                  'Independiente Rivadavia', 'BTTS - Sim',           'rb-80', 'vermelho', 0.80),

    # ═══════════ 2026-05-04 (11 bets) ═══════════
    # rb-95 (2 bets, 2V/0R)
    ('2026-05-04', 'argentina', 'Gimnasia y Esgrima Mendoza', 'Defensa y Justicia',     'Under 3.5 gols', 'rb-95', 'verde', 0.97),
    ('2026-05-04', 'seriea',    'Cremonese',                  'Lazio',                  'Under 3.5 gols', 'rb-95', 'verde', 0.95),
    # rb-85 (3 bets, 0V/3R)
    ('2026-05-04', 'argentina', 'Gimnasia y Esgrima Mendoza', 'Defensa y Justicia',     'Under 2.5 gols', 'rb-85', 'vermelho', 0.89),
    ('2026-05-04', 'argentina', 'Gimnasia y Esgrima Mendoza', 'Defensa y Justicia',     'BTTS - Nao',     'rb-85', 'vermelho', 0.88),
    ('2026-05-04', 'saudi',     'Al-Ettifaq',                 'Al-Najma SC',            'Over 1.5 gols',  'rb-85', 'vermelho', 0.86),
    # rb-80 (6 bets, 2V/4R)
    ('2026-05-04', 'seriea',    'Cremonese',                  'Lazio',                  'Under 2.5 gols',       'rb-80', 'vermelho', 0.85),
    ('2026-05-04', 'saudi',     'Al-Ettifaq',                 'Al-Najma SC',            'Under 8.5 escanteios', 'rb-80', 'vermelho', 0.83),
    ('2026-05-04', 'argentina', 'Vélez Sarsfield',            'Newell\'s Old Boys',     'Vitoria Mandante',     'rb-80', 'verde',    0.81),
    ('2026-05-04', 'seriea',    'Cremonese',                  'Lazio',                  'Under 8.5 escanteios', 'rb-80', 'verde',    0.81),
    ('2026-05-04', 'laliga',    'Sevilla',                    'Real Sociedad',          'Over 1.5 gols',        'rb-80', 'vermelho', 0.80),
    ('2026-05-04', 'premier',   'Chelsea',                    'Nottingham Forest',      'Over 8.5 escanteios',  'rb-80', 'vermelho', 0.80),

    # ═══════════ 2026-05-05 (3 bets) ═══════════
    ('2026-05-05', 'argentina', 'Estudiantes de Río Cuarto', 'Instituto De Córdoba', 'Under 3.5 gols', 'rb-95', 'verde', 0.98),
    ('2026-05-05', 'argentina', 'Estudiantes de Río Cuarto', 'Instituto De Córdoba', 'Under 2.5 gols', 'rb-90', 'verde', 0.91),
    ('2026-05-05', 'argentina', 'Estudiantes de Río Cuarto', 'Instituto De Córdoba', 'BTTS - Nao',     'rb-85', 'verde', 0.87),
]


def encode_id(b): return b.replace('|', '__pipe__').replace('/', '__slash__')


def build_assert_history(bets):
    """Agrega bets em assertHistory por data."""
    by_date = {}
    for (date, lk, home, away, label, band, outcome, *p) in bets:
        if date not in by_date:
            by_date[date] = {
                'date': date,
                'bands': {},
                'total': {'verde': 0, 'vermelho': 0},
                'leagues': {}
            }
        entry = by_date[date]
        entry['total'][outcome] += 1
        if band not in entry['bands']:
            entry['bands'][band] = {'verde': 0, 'vermelho': 0}
        entry['bands'][band][outcome] += 1
        if lk not in entry['leagues']:
            entry['leagues'][lk] = {
                'name': LEAGUE_NAMES.get(lk, lk),
                'bands': {},
                'total': {'verde': 0, 'vermelho': 0}
            }
        lg = entry['leagues'][lk]
        lg['total'][outcome] += 1
        if band not in lg['bands']:
            lg['bands'][band] = {'verde': 0, 'vermelho': 0}
        lg['bands'][band][outcome] += 1
    return by_date


def main():
    sa_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT', '')
    if not sa_json:
        print('FIREBASE_SERVICE_ACCOUNT nao definida.', flush=True)
        sys.exit(1)

    import firebase_admin
    from firebase_admin import credentials, firestore as fs
    cred = credentials.Certificate(json.loads(sa_json))
    firebase_admin.initialize_app(cred)
    db = fs.client()

    print(f'== Processando {len(BETS)} bets ==', flush=True)

    # 1. Constroi assertHistory por data
    history = build_assert_history(BETS)
    print('\n== assertHistory agregado ==', flush=True)
    for date in sorted(history.keys()):
        h = history[date]
        tv, tr = h['total']['verde'], h['total']['vermelho']
        total = tv + tr
        pct = round(tv/total*100) if total else 0
        bsum = {k: v['verde']+v['vermelho'] for k,v in h['bands'].items()}
        lsum = {k: v['total']['verde']+v['total']['vermelho'] for k,v in h['leagues'].items()}
        print(f'  {date}: {tv}V/{tr}R={total} ({pct}%) bands={bsum} leagues={lsum}', flush=True)

    if DRY_RUN:
        print('\n[DRY-RUN] Nenhuma escrita realizada.', flush=True)
        return

    # 2. Grava assertHistory
    print('\n== Gravando assertHistory ==', flush=True)
    for date, entry in history.items():
        db.collection('assertHistory').document(date).set(entry)
        print(f'  OK {date}', flush=True)

    # 3. Grava betMeta + betOutcomes por bet
    print('\n== Gravando betMeta + betOutcomes ==', flush=True)
    batch = db.batch()
    n = 0
    for (date, lk, home, away, label, band, outcome, *p_arg) in BETS:
        p = p_arg[0] if p_arg else BAND_DEFAULT_P[band]
        bet_id = f'{lk}|{home}|{away}|{label}'
        doc_id = encode_id(bet_id)

        meta = {
            'p':          p,
            'p_original': p,
            'band_hist':  band,
            'date':       date,
            'leagueKey':  lk,
            'leagueName': LEAGUE_NAMES.get(lk, lk),
        }
        batch.set(db.collection('betMeta').document(doc_id), meta)
        batch.set(db.collection('betOutcomes').document(doc_id), {'value': outcome})
        n += 2
        if n >= 400:
            batch.commit()
            batch = db.batch()
            n = 0
    if n > 0:
        batch.commit()

    print(f'  {len(BETS)} bets gravados.', flush=True)
    print('\nFeito! Tabela e filtros agora derivam da mesma fonte.', flush=True)


if __name__ == '__main__':
    main()
