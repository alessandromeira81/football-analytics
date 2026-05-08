"""
Sincroniza o histórico de assertividade para o Firestore.
Lê betOutcomes + betMeta do Firestore, recomputa o histórico por dia,
e grava de volta na coleção assertHistory.

Uso:
  FIREBASE_SERVICE_ACCOUNT='<json>' python assertividade_sync.py
"""

import json
import os
import sys
import firebase_admin
from firebase_admin import credentials, firestore

BANDS = [
    {'min': 0.90, 'max': 1.01, 'cls': 'band-90'},
    {'min': 0.85, 'max': 0.90, 'cls': 'band-85'},
    {'min': 0.80, 'max': 0.85, 'cls': 'band-80'},
    {'min': 0.75, 'max': 0.80, 'cls': 'band-75'},
    {'min': 0.70, 'max': 0.75, 'cls': 'band-70'},
]

def decode_id(encoded):
    return encoded.replace('__pipe__', '|').replace('__slash__', '/')

def main():
    sa_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT', '')
    if not sa_json:
        print('FIREBASE_SERVICE_ACCOUNT não definida.', flush=True)
        sys.exit(1)

    cred = credentials.Certificate(json.loads(sa_json))
    firebase_admin.initialize_app(cred)
    db = firestore.client()

    # 1) Lê resultados individuais
    outcomes = {}
    for doc in db.collection('betOutcomes').stream():
        bet_id = decode_id(doc.id)
        val = doc.to_dict().get('value', 'cinza')
        if val in ('verde', 'vermelho'):
            outcomes[bet_id] = val
    print(f'{len(outcomes)} resultados lidos do Firestore', flush=True)

    # 2) Lê metadados
    meta = {}
    for doc in db.collection('betMeta').stream():
        bet_id = decode_id(doc.id)
        meta[bet_id] = doc.to_dict()
    print(f'{len(meta)} metadados lidos do Firestore', flush=True)

    if not outcomes:
        print('Nenhum resultado registrado. Nada a sincronizar.', flush=True)
        return

    # 3) Agrega por data
    date_map = {}
    for bet_id, state in outcomes.items():
        b = meta.get(bet_id, {})
        date       = b.get('date', '—')
        p          = b.get('p', 0) or 0
        league_key = b.get('leagueKey', '')
        league_name = b.get('leagueName', league_key)

        if date not in date_map:
            date_map[date] = {'bands': {}, 'leagues': {}}

        band_key = None
        for band in BANDS:
            if band['min'] <= p < band['max']:
                band_key = band['cls']
                break
        if not band_key:
            continue

        bands = date_map[date]['bands']
        if band_key not in bands:
            bands[band_key] = {'verde': 0, 'vermelho': 0}
        bands[band_key][state] += 1

        leagues = date_map[date]['leagues']
        if league_key not in leagues:
            leagues[league_key] = {
                'name': league_name,
                'bands': {},
                'total': {'verde': 0, 'vermelho': 0}
            }
        lg = leagues[league_key]
        if band_key not in lg['bands']:
            lg['bands'][band_key] = {'verde': 0, 'vermelho': 0}
        lg['bands'][band_key][state] += 1
        lg['total'][state] += 1

    # 4) Grava no Firestore
    batch = db.batch()
    for date, data in date_map.items():
        bands = data['bands']
        tv = sum(b.get('verde', 0) for b in bands.values())
        tr = sum(b.get('vermelho', 0) for b in bands.values())
        entry = {
            'date':    date,
            'bands':   bands,
            'total':   {'verde': tv, 'vermelho': tr},
            'leagues': data['leagues'],
        }
        ref = db.collection('assertHistory').document(date)
        batch.set(ref, entry)
        print(f'  {date}: {tv}V / {tr}R', flush=True)

    batch.commit()
    print(f'\n✅ {len(date_map)} dia(s) sincronizado(s) no Firestore.', flush=True)

if __name__ == '__main__':
    main()
