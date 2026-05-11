"""
Corrige assertHistory no Firestore com dados do gabarito (extraidos do HTML salvo).
Grava p_original em betMeta para congelar o p historico de cada aposta.
Dados embutidos diretamente — nao depende do arquivo HTML.

Uso:
  FIREBASE_SERVICE_ACCOUNT='<json>' python fix_history_bands.py [--dry-run]
"""
import json, os, sys

sys.stdout.reconfigure(encoding='utf-8')

DRY_RUN = '--dry-run' in sys.argv

# --------------------------------------------------------------------------
# Gabarito extraido do arquivo "football_analytics_01 a 05.html"
# Estes sao os dados CORRETOS que devem estar no Firestore.
# Para 02/05: Firestore tinha rb-95:5/rb-90:6 (errado). Correto: rb-95:3/rb-90:8.
# --------------------------------------------------------------------------
HISTORY_GABARITO = [
    {
        "date": "2026-05-01",
        "bands": {
            "rb-95": {"verde": 1, "vermelho": 0},
            "rb-85": {"verde": 1, "vermelho": 1},
            "rb-80": {"verde": 0, "vermelho": 1}
        },
        "total": {"verde": 2, "vermelho": 2},
        "leagues": {
            "seriea":  {"name": "Serie A",         "bands": {"rb-95": {"verde": 1, "vermelho": 0}, "rb-85": {"verde": 0, "vermelho": 1}, "rb-80": {"verde": 0, "vermelho": 1}}, "total": {"verde": 1, "vermelho": 2}},
            "premier": {"name": "Premier League",  "bands": {"rb-85": {"verde": 1, "vermelho": 0}},                                                                              "total": {"verde": 1, "vermelho": 0}}
        }
    },
    {
        "date": "2026-05-02",
        "bands": {
            "rb-95": {"verde": 3, "vermelho": 0},
            "rb-90": {"verde": 5, "vermelho": 3},
            "rb-85": {"verde": 6, "vermelho": 0},
            "rb-80": {"verde": 12, "vermelho": 4}
        },
        "total": {"verde": 26, "vermelho": 7},
        "leagues": {
            "argentina":   {"name": "Liga Profesional",    "bands": {"rb-95": {"verde": 2, "vermelho": 0}, "rb-90": {"verde": 2, "vermelho": 1}, "rb-85": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 4, "vermelho": 1}}, "total": {"verde": 9,  "vermelho": 2}},
            "bundesliga":  {"name": "Bundesliga",          "bands": {"rb-95": {"verde": 1, "vermelho": 0}, "rb-90": {"verde": 1, "vermelho": 1}, "rb-85": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 3, "vermelho": 0}}, "total": {"verde": 6,  "vermelho": 1}},
            "saudi":       {"name": "Saudi Pro League",    "bands": {"rb-90": {"verde": 1, "vermelho": 0}, "rb-85": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 1, "vermelho": 0}},                                       "total": {"verde": 3,  "vermelho": 0}},
            "brasileirao": {"name": "Brasileirao Serie A", "bands": {"rb-90": {"verde": 1, "vermelho": 1}, "rb-85": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 1, "vermelho": 1}},                                       "total": {"verde": 3,  "vermelho": 2}},
            "ligue1":      {"name": "Ligue 1",             "bands": {"rb-85": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 0, "vermelho": 1}},                                                                              "total": {"verde": 1,  "vermelho": 1}},
            "laliga":      {"name": "La Liga",             "bands": {"rb-85": {"verde": 1, "vermelho": 0}},                                                                                                                    "total": {"verde": 1,  "vermelho": 0}},
            "premier":     {"name": "Premier League",      "bands": {"rb-80": {"verde": 2, "vermelho": 1}},                                                                                                                    "total": {"verde": 2,  "vermelho": 1}},
            "seriea":      {"name": "Serie A",             "bands": {"rb-80": {"verde": 1, "vermelho": 0}},                                                                                                                    "total": {"verde": 1,  "vermelho": 0}}
        }
    },
    {
        "date": "2026-05-03",
        "bands": {
            "rb-95": {"verde": 3, "vermelho": 3},
            "rb-90": {"verde": 6, "vermelho": 3},
            "rb-85": {"verde": 5, "vermelho": 6},
            "rb-80": {"verde": 14, "vermelho": 8}
        },
        "total": {"verde": 28, "vermelho": 20},
        "leagues": {
            "saudi":       {"name": "Saudi Pro League",    "bands": {"rb-95": {"verde": 1, "vermelho": 0}, "rb-90": {"verde": 2, "vermelho": 0}, "rb-85": {"verde": 2, "vermelho": 0}, "rb-80": {"verde": 1, "vermelho": 1}}, "total": {"verde": 6,  "vermelho": 1}},
            "argentina":   {"name": "Liga Profesional",    "bands": {"rb-95": {"verde": 3, "vermelho": 1}, "rb-90": {"verde": 1, "vermelho": 2}, "rb-85": {"verde": 2, "vermelho": 1}, "rb-80": {"verde": 3, "vermelho": 3}}, "total": {"verde": 9,  "vermelho": 7}},
            "laliga":      {"name": "La Liga",             "bands": {"rb-90": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 3, "vermelho": 0}},                                                                              "total": {"verde": 4,  "vermelho": 0}},
            "bundesliga":  {"name": "Bundesliga",          "bands": {"rb-85": {"verde": 1, "vermelho": 0}},                                                                                                                    "total": {"verde": 1,  "vermelho": 0}},
            "seriea":      {"name": "Serie A",             "bands": {"rb-85": {"verde": 0, "vermelho": 1}, "rb-80": {"verde": 2, "vermelho": 0}},                                                                              "total": {"verde": 2,  "vermelho": 1}},
            "brasileirao": {"name": "Brasileirao Serie A", "bands": {"rb-95": {"verde": 0, "vermelho": 1}, "rb-90": {"verde": 1, "vermelho": 1}, "rb-85": {"verde": 0, "vermelho": 1}, "rb-80": {"verde": 1, "vermelho": 6}}, "total": {"verde": 2,  "vermelho": 9}},
            "ligue1":      {"name": "Ligue 1",             "bands": {"rb-95": {"verde": 0, "vermelho": 1}, "rb-85": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 2, "vermelho": 1}},                                       "total": {"verde": 3,  "vermelho": 2}}
        }
    },
    {
        "date": "2026-05-04",
        "bands": {
            "rb-95": {"verde": 2, "vermelho": 0},
            "rb-85": {"verde": 0, "vermelho": 3},
            "rb-80": {"verde": 2, "vermelho": 4}
        },
        "total": {"verde": 4, "vermelho": 7},
        "leagues": {
            "argentina": {"name": "Liga Profesional",   "bands": {"rb-95": {"verde": 1, "vermelho": 0}, "rb-85": {"verde": 0, "vermelho": 2}, "rb-80": {"verde": 0, "vermelho": 1}}, "total": {"verde": 1, "vermelho": 3}},
            "saudi":     {"name": "Saudi Pro League",   "bands": {"rb-85": {"verde": 0, "vermelho": 1}, "rb-80": {"verde": 0, "vermelho": 1}},                                        "total": {"verde": 0, "vermelho": 2}},
            "seriea":    {"name": "Serie A",            "bands": {"rb-95": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 1, "vermelho": 1}},                                        "total": {"verde": 2, "vermelho": 1}},
            "laliga":    {"name": "La Liga",            "bands": {"rb-80": {"verde": 0, "vermelho": 1}},                                                                              "total": {"verde": 0, "vermelho": 1}},
            "premier":   {"name": "Premier League",     "bands": {"rb-80": {"verde": 1, "vermelho": 0}},                                                                              "total": {"verde": 1, "vermelho": 0}}
        }
    },
    {
        "date": "2026-05-05",
        "bands": {
            "rb-95": {"verde": 1, "vermelho": 0},
            "rb-90": {"verde": 1, "vermelho": 0},
            "rb-85": {"verde": 1, "vermelho": 0}
        },
        "total": {"verde": 3, "vermelho": 0},
        "leagues": {
            "argentina": {"name": "Liga Profesional", "bands": {"rb-95": {"verde": 1, "vermelho": 0}, "rb-90": {"verde": 1, "vermelho": 0}, "rb-85": {"verde": 1, "vermelho": 0}}, "total": {"verde": 3, "vermelho": 0}}
        }
    }
]

# p_original de cada aposta (congelado na data de apresentacao)
META_P_ORIGINAL = {
    "argentina|Barracas Central|Banfield|Under 3.5 gols":                             {"p": 0.83, "date": "2026-05-02", "leagueKey": "argentina",   "leagueName": "Liga Profesional"},
    "argentina|Barracas Central|Banfield|Under 8.5 escanteios":                       {"p": 0.98, "date": "2026-05-02", "leagueKey": "argentina",   "leagueName": "Liga Profesional"},
    "argentina|CA Lanús|Deportivo Riestra|BTTS - Nao":                                {"p": 0.80, "date": "2026-05-02", "leagueKey": "argentina",   "leagueName": "Liga Profesional"},
    "argentina|CA Lanús|Deportivo Riestra|Under 2.5 gols":                            {"p": 0.88, "date": "2026-05-02", "leagueKey": "argentina",   "leagueName": "Liga Profesional"},
    "argentina|CA Lanús|Deportivo Riestra|Under 3.5 gols":                            {"p": 0.97, "date": "2026-05-02", "leagueKey": "argentina",   "leagueName": "Liga Profesional"},
    "argentina|Central Córdoba|Boca Juniors|Under 2.5 gols":                          {"p": 0.83, "date": "2026-05-02", "leagueKey": "argentina",   "leagueName": "Liga Profesional"},
    "argentina|Central Córdoba|Boca Juniors|Under 3.5 gols":                          {"p": 0.949,"date": "2026-05-02", "leagueKey": "argentina",   "leagueName": "Liga Profesional"},
    "argentina|Club Atlético Unión de Santa Fe|CA Talleres|BTTS - Nao":               {"p": 0.93, "date": "2026-05-02", "leagueKey": "argentina",   "leagueName": "Liga Profesional"},
    "argentina|Club Atlético Unión de Santa Fe|CA Talleres|Under 2.5 gols":           {"p": 0.82, "date": "2026-05-02", "leagueKey": "argentina",   "leagueName": "Liga Profesional"},
    "argentina|Club Atlético Unión de Santa Fe|CA Talleres|Under 3.5 gols":           {"p": 0.94, "date": "2026-05-02", "leagueKey": "argentina",   "leagueName": "Liga Profesional"},
    "argentina|San Lorenzo|CA Independiente|Over 1.5 gols":                           {"p": 0.83, "date": "2026-05-02", "leagueKey": "argentina",   "leagueName": "Liga Profesional"},
    "brasileirao|Botafogo|Remo|Over 1.5 gols":                                        {"p": 0.93, "date": "2026-05-02", "leagueKey": "brasileirao", "leagueName": "Brasileirao Serie A"},
    "brasileirao|Palmeiras|Santos|Over 1.5 gols":                                     {"p": 0.88, "date": "2026-05-02", "leagueKey": "brasileirao", "leagueName": "Brasileirao Serie A"},
    "brasileirao|Palmeiras|Santos|Over 8.5 escanteios":                               {"p": 0.82, "date": "2026-05-02", "leagueKey": "brasileirao", "leagueName": "Brasileirao Serie A"},
    "brasileirao|Palmeiras|Santos|Vitoria Mandante":                                  {"p": 0.81, "date": "2026-05-02", "leagueKey": "brasileirao", "leagueName": "Brasileirao Serie A"},
    "brasileirao|Vitória|Coritiba|Under 3.5 gols":                                    {"p": 0.93, "date": "2026-05-02", "leagueKey": "brasileirao", "leagueName": "Brasileirao Serie A"},
    "bundesliga|Bayer 04 Leverkusen|RB Leipzig|Over 8.5 escanteios":                  {"p": 0.83, "date": "2026-05-02", "leagueKey": "bundesliga",  "leagueName": "Bundesliga"},
    "bundesliga|FC Bayern München|1. FC Heidenheim|Over 1.5 gols":                    {"p": 0.97, "date": "2026-05-02", "leagueKey": "bundesliga",  "leagueName": "Bundesliga"},
    "bundesliga|FC Bayern München|1. FC Heidenheim|Over 2.5 gols":                    {"p": 0.88, "date": "2026-05-02", "leagueKey": "bundesliga",  "leagueName": "Bundesliga"},
    "bundesliga|FC Bayern München|1. FC Heidenheim|Over 8.5 escanteios":              {"p": 0.84, "date": "2026-05-02", "leagueKey": "bundesliga",  "leagueName": "Bundesliga"},
    "bundesliga|FC Bayern München|1. FC Heidenheim|Vitoria Mandante":                 {"p": 0.949,"date": "2026-05-02", "leagueKey": "bundesliga",  "leagueName": "Bundesliga"},
    "bundesliga|TSG Hoffenheim|VfB Stuttgart|Over 1.5 gols":                          {"p": 0.92, "date": "2026-05-02", "leagueKey": "bundesliga",  "leagueName": "Bundesliga"},
    "bundesliga|TSG Hoffenheim|VfB Stuttgart|Over 8.5 escanteios":                    {"p": 0.84, "date": "2026-05-02", "leagueKey": "bundesliga",  "leagueName": "Bundesliga"},
    "laliga|Osasuna|FC Barcelona|Over 1.5 gols":                                      {"p": 0.87, "date": "2026-05-02", "leagueKey": "laliga",      "leagueName": "La Liga"},
    "laliga|Sevilla|Real Sociedad|Over 1.5 gols":                                     {"p": 0.82, "date": "2026-05-04", "leagueKey": "laliga",      "leagueName": "La Liga"},
    "ligue1|Nice|RC Lens|Over 1.5 gols":                                              {"p": 0.87, "date": "2026-05-02", "leagueKey": "ligue1",      "leagueName": "Ligue 1"},
    "ligue1|Paris Saint-Germain|Lorient|Vitoria Mandante":                            {"p": 0.84, "date": "2026-05-02", "leagueKey": "ligue1",      "leagueName": "Ligue 1"},
    "premier|Leeds United|Burnley|Over 1.5 gols":                                     {"p": 0.86, "date": "2026-05-01", "leagueKey": "premier",     "leagueName": "Premier League"},
    "premier|Newcastle United|Brighton & Hove Albion|Over 1.5 gols":                  {"p": 0.82, "date": "2026-05-02", "leagueKey": "premier",     "leagueName": "Premier League"},
    "premier|Wolverhampton|Sunderland|Under 3.5 gols":                                {"p": 0.82, "date": "2026-05-02", "leagueKey": "premier",     "leagueName": "Premier League"},
    "premier|Wolverhampton|Sunderland|Under 8.5 escanteios":                          {"p": 0.80, "date": "2026-05-02", "leagueKey": "premier",     "leagueName": "Premier League"},
    "saudi|Al-Hazem|Al-Hilal|Over 1.5 gols":                                         {"p": 0.94, "date": "2026-05-02", "leagueKey": "saudi",       "leagueName": "Saudi Pro League"},
    "saudi|Al-Hazem|Al-Hilal|Over 2.5 gols":                                         {"p": 0.83, "date": "2026-05-02", "leagueKey": "saudi",       "leagueName": "Saudi Pro League"},
    "saudi|Al-Hazem|Al-Hilal|Vitoria Visitante":                                      {"p": 0.86, "date": "2026-05-02", "leagueKey": "saudi",       "leagueName": "Saudi Pro League"},
    "seriea|Pisa|Lecce|BTTS - Nao":                                                   {"p": 0.82, "date": "2026-05-01", "leagueKey": "seriea",      "leagueName": "Serie A"},
    "seriea|Pisa|Lecce|Under 2.5 gols":                                               {"p": 0.89, "date": "2026-05-01", "leagueKey": "seriea",      "leagueName": "Serie A"},
    "seriea|Pisa|Lecce|Under 3.5 gols":                                               {"p": 0.97, "date": "2026-05-01", "leagueKey": "seriea",      "leagueName": "Serie A"},
    "seriea|Udinese|Torino|Under 3.5 gols":                                           {"p": 0.81, "date": "2026-05-02", "leagueKey": "seriea",      "leagueName": "Serie A"},
}


def encode_id(bet_id):
    return bet_id.replace('|', '__pipe__').replace('/', '__slash__')


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

    # ------------------------------------------------------------------
    # 1) Corrige assertHistory no Firestore com dados do gabarito
    # ------------------------------------------------------------------
    print('\n== Corrigindo assertHistory ==', flush=True)
    n_fixed = n_ok = 0

    for entry in sorted(HISTORY_GABARITO, key=lambda x: x['date']):
        date  = entry['date']
        bands = entry['bands']
        total = entry['total']
        tv, tr = total['verde'], total['vermelho']
        gt_bands = {k: v['verde']+v['vermelho'] for k,v in bands.items()}

        ref = db.collection('assertHistory').document(date)
        snap = ref.get()
        existing = snap.to_dict() if snap.exists else {}
        ex_bands = {k: v['verde']+v['vermelho'] for k,v in existing.get('bands', {}).items()}
        ex_tv = existing.get('total', {}).get('verde', 0)
        ex_tr = existing.get('total', {}).get('vermelho', 0)

        bands_match = (ex_bands == gt_bands and ex_tv == tv and ex_tr == tr)
        pct = round(tv/(tv+tr)*100) if (tv+tr) else 0

        if bands_match:
            print(f'  OK {date}: {tv}V/{tr}R={pct}% bands={gt_bands}', flush=True)
            n_ok += 1
        else:
            print(f'  CORRIGINDO {date}: {tv}V/{tr}R={pct}%', flush=True)
            print(f'    Firestore: {ex_bands}', flush=True)
            print(f'    Gabarito:  {gt_bands}', flush=True)
            if not DRY_RUN:
                ref.set(entry)
            n_fixed += 1

    print(f'\n  {n_fixed} corrigido(s), {n_ok} ja estavam corretos', flush=True)

    # ------------------------------------------------------------------
    # 2) Grava p_original em betMeta (nunca sobrescreve se ja existir)
    # ------------------------------------------------------------------
    print('\n== Gravando p_original em betMeta ==', flush=True)
    n_updated = n_skipped = 0
    batch = db.batch()
    n_batch = 0

    for bet_id, m in sorted(META_P_ORIGINAL.items()):
        p_orig = m['p']
        doc_id = encode_id(bet_id)
        ref = db.collection('betMeta').document(doc_id)
        snap = ref.get()

        if snap.exists:
            existing_meta = snap.to_dict()
            if 'p_original' in existing_meta:
                n_skipped += 1
                continue
            print(f'  SET p_original={p_orig:.4f} | {bet_id[:70]}', flush=True)
            if not DRY_RUN:
                batch.update(ref, {'p_original': p_orig})
            n_updated += 1
        else:
            print(f'  CRIADO | {bet_id[:70]}', flush=True)
            if not DRY_RUN:
                batch.set(ref, {'p': p_orig, 'p_original': p_orig,
                                'date': m['date'], 'leagueKey': m['leagueKey'],
                                'leagueName': m['leagueName']})
            n_updated += 1
        n_batch += 1
        if n_batch >= 400:
            if not DRY_RUN:
                batch.commit()
            batch = db.batch()
            n_batch = 0

    if n_batch > 0 and not DRY_RUN:
        batch.commit()

    print(f'\n  {n_updated} p_original gravado(s), {n_skipped} ja tinham p_original', flush=True)

    if DRY_RUN:
        print('\n[DRY-RUN] Nenhuma escrita realizada.', flush=True)
    else:
        print('\nFeito!', flush=True)


if __name__ == '__main__':
    main()
