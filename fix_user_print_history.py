"""
Grava no assertHistory os dados EXATOS do print original que o usuario
viu na epoca. O sistema mudou a forma de calculo depois — mas o passado
NAO MUDA. Esta funcao apenas escreve os dados originais por cima.

Dados extraidos diretamente do print enviado pelo usuario.

Uso:
  FIREBASE_SERVICE_ACCOUNT='<json>' python fix_user_print_history.py [--dry-run]
"""
import json, os, sys
sys.stdout.reconfigure(encoding='utf-8')

DRY_RUN = '--dry-run' in sys.argv

# ── Dados originais do print do usuario ──────────────────────────────────────
# Apenas datas que diferem do que esta no Firestore atualmente
USER_PRINT_DATA = {
    "2026-05-01": {
        "bands": {
            "rb-95": {"verde": 1, "vermelho": 0},
            "rb-85": {"verde": 1, "vermelho": 1},
            "rb-80": {"verde": 0, "vermelho": 1}
        },
        "total": {"verde": 2, "vermelho": 2}
    },
    "2026-05-02": {
        "bands": {
            "rb-95": {"verde": 3, "vermelho": 0},
            "rb-90": {"verde": 5, "vermelho": 3},
            "rb-85": {"verde": 6, "vermelho": 0},
            "rb-80": {"verde": 12, "vermelho": 4}
        },
        "total": {"verde": 26, "vermelho": 7}
    },
    "2026-05-03": {
        "bands": {
            "rb-90": {"verde": 6, "vermelho": 0},
            "rb-85": {"verde": 6, "vermelho": 2},
            "rb-80": {"verde": 15, "vermelho": 18}
        },
        "total": {"verde": 27, "vermelho": 20}
    },
    "2026-05-04": {
        "bands": {
            "rb-90": {"verde": 2, "vermelho": 0},
            "rb-80": {"verde": 2, "vermelho": 7}
        },
        "total": {"verde": 4, "vermelho": 7}
    },
    "2026-05-05": {
        "bands": {
            "rb-90": {"verde": 1, "vermelho": 0},
            "rb-80": {"verde": 2, "vermelho": 0}
        },
        "total": {"verde": 3, "vermelho": 0}
    }
}

# leagues — derivado do gabarito HTML quando match com totals do print
# (para 01/05 e 02/05 o print confere com gabarito; para 03-05 nao temos
# breakdown de liga e o filtro de pais degrada graciosamente para essas datas)
LEAGUES_DATA = {
    "2026-05-01": {
        "seriea":  {"name": "Serie A",        "bands": {"rb-95": {"verde": 1, "vermelho": 0}, "rb-85": {"verde": 0, "vermelho": 1}, "rb-80": {"verde": 0, "vermelho": 1}}, "total": {"verde": 1, "vermelho": 2}},
        "premier": {"name": "Premier League", "bands": {"rb-85": {"verde": 1, "vermelho": 0}},                                                                              "total": {"verde": 1, "vermelho": 0}}
    },
    "2026-05-02": {
        "argentina":   {"name": "Liga Profesional",    "bands": {"rb-95": {"verde": 2, "vermelho": 0}, "rb-90": {"verde": 2, "vermelho": 1}, "rb-85": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 4, "vermelho": 1}}, "total": {"verde": 9, "vermelho": 2}},
        "bundesliga":  {"name": "Bundesliga",          "bands": {"rb-95": {"verde": 1, "vermelho": 0}, "rb-90": {"verde": 1, "vermelho": 1}, "rb-85": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 3, "vermelho": 0}}, "total": {"verde": 6, "vermelho": 1}},
        "saudi":       {"name": "Saudi Pro League",    "bands": {"rb-90": {"verde": 1, "vermelho": 0}, "rb-85": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 1, "vermelho": 0}},                                       "total": {"verde": 3, "vermelho": 0}},
        "brasileirao": {"name": "Brasileirao Serie A", "bands": {"rb-90": {"verde": 1, "vermelho": 1}, "rb-85": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 1, "vermelho": 1}},                                       "total": {"verde": 3, "vermelho": 2}},
        "ligue1":      {"name": "Ligue 1",             "bands": {"rb-85": {"verde": 1, "vermelho": 0}, "rb-80": {"verde": 0, "vermelho": 1}},                                                                              "total": {"verde": 1, "vermelho": 1}},
        "laliga":      {"name": "La Liga",             "bands": {"rb-85": {"verde": 1, "vermelho": 0}},                                                                                                                    "total": {"verde": 1, "vermelho": 0}},
        "premier":     {"name": "Premier League",      "bands": {"rb-80": {"verde": 2, "vermelho": 1}},                                                                                                                    "total": {"verde": 2, "vermelho": 1}},
        "seriea":      {"name": "Serie A",             "bands": {"rb-80": {"verde": 1, "vermelho": 0}},                                                                                                                    "total": {"verde": 1, "vermelho": 0}}
    }
    # 03-05/05: sem breakdown por liga (print do usuario nao detalha)
}


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

    print('== Sobrescrevendo assertHistory com dados do print do usuario ==', flush=True)

    for date, entry in sorted(USER_PRINT_DATA.items()):
        tv, tr = entry['total']['verde'], entry['total']['vermelho']
        total = tv + tr
        pct = round(tv/total*100) if total else 0
        bands_summary = {k: v['verde']+v['vermelho'] for k,v in entry['bands'].items()}

        full_entry = {
            'date':    date,
            'bands':   entry['bands'],
            'total':   entry['total'],
            'leagues': LEAGUES_DATA.get(date, {})
        }

        print(f'  {date}: {tv}V/{tr}R={total} ({pct}%) bands={bands_summary} leagues={"sim" if full_entry["leagues"] else "nao"}', flush=True)

        if not DRY_RUN:
            db.collection('assertHistory').document(date).set(full_entry)

    if DRY_RUN:
        print('\n[DRY-RUN] Nenhuma escrita realizada.', flush=True)
    else:
        print('\nFeito! assertHistory restaurado para os dados originais.', flush=True)


if __name__ == '__main__':
    main()
