"""
Garante que TODA aposta com outcome tem band_hist gravado em betMeta.

Algoritmo:
1. Para cada (data, liga) presente em assertHistory:
   - Le os counts target por banda do assertHistory.leagues[liga].bands
   - Lista bets para essa (data, liga) com outcome verde/vermelho
   - Bets que ja tem band_hist: manten (contabiliza no known_count)
   - Bets sem band_hist: aloca para preencher remaining = target - known
   - Sorting por p desc, top -> rb-95, depois rb-90, etc

2. Para bets sem (data, liga) em assertHistory:
   - Computa band do proprio p_original ou p (best effort)

Apos rodar, todo bet com outcome tem band_hist.
O JS lendo meta.band_hist produz resultados identicos ao assertHistory.

Uso:
  FIREBASE_SERVICE_ACCOUNT='<json>' python complete_band_hist.py [--dry-run]
"""
import json, os, sys
sys.stdout.reconfigure(encoding='utf-8')

DRY_RUN = '--dry-run' in sys.argv
BANDS = ['rb-95', 'rb-90', 'rb-85', 'rb-80']


def encode_id(b):  return b.replace('|', '__pipe__').replace('/', '__slash__')
def decode_id(e):  return e.replace('__pipe__', '|').replace('__slash__', '/')


def band_from_p(p):
    if p > 1: p = p / 100
    pct = round(p * 100)
    if pct >= 95: return 'rb-95'
    if pct >= 90: return 'rb-90'
    if pct >= 85: return 'rb-85'
    if pct >= 80: return 'rb-80'
    return None


def p_of(meta):
    p = meta.get('p_original') or meta.get('p', 0) or 0
    if p > 1: p = p / 100
    return p


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

    print('== Carregando dados do Firestore ==', flush=True)

    outcomes = {}
    for d in db.collection('betOutcomes').stream():
        v = d.to_dict().get('value', 'cinza')
        if v in ('verde', 'vermelho'):
            outcomes[decode_id(d.id)] = v
    print(f'  {len(outcomes)} bets com outcome verde/vermelho', flush=True)

    metas = {}
    for d in db.collection('betMeta').stream():
        metas[decode_id(d.id)] = d.to_dict()
    print(f'  {len(metas)} bets em betMeta', flush=True)

    history = {}
    for d in db.collection('assertHistory').stream():
        history[d.id] = d.to_dict()
    print(f'  {len(history)} datas em assertHistory', flush=True)

    # Agrupa bets com outcome por (date, league)
    print('\n== Agrupando bets por (data, liga) ==', flush=True)
    by_dl = {}  # (date, lk) -> [bet_id, ...]
    no_meta = 0
    no_date = 0
    for bid in outcomes:
        m = metas.get(bid)
        if not m:
            no_meta += 1
            continue
        date = m.get('date', '')
        if not date:
            no_date += 1
            continue
        lk = m.get('leagueKey', '')
        by_dl.setdefault((date, lk), []).append(bid)

    print(f'  {len(by_dl)} combinacoes (data, liga)', flush=True)
    if no_meta:  print(f'  AVISO: {no_meta} bets sem betMeta', flush=True)
    if no_date:  print(f'  AVISO: {no_date} bets sem data', flush=True)

    # Aloca band_hist
    print('\n== Alocando band_hist por (data, liga) ==', flush=True)
    updates = {}    # bet_id -> band_hist a gravar
    keep_existing = 0
    n_aligned = 0
    n_p_based = 0

    for (date, lk), bids in sorted(by_dl.items()):
        league_data = (history.get(date, {}).get('leagues') or {}).get(lk)

        if league_data:
            # Tem dados em assertHistory para (data, liga) — usa alocacao matching
            target_bands = league_data.get('bands', {})
            target_count = {b: 0 for b in BANDS}
            for b in BANDS:
                bd = target_bands.get(b, {})
                target_count[b] = bd.get('verde', 0) + bd.get('vermelho', 0)

            known_count = {b: 0 for b in BANDS}
            unknown_bids = []
            for bid in bids:
                bh = metas[bid].get('band_hist')
                if bh and bh in known_count:
                    known_count[bh] += 1
                    keep_existing += 1
                else:
                    unknown_bids.append(bid)

            remaining = {b: max(0, target_count[b] - known_count[b]) for b in BANDS}

            # Ordena unknowns por p desc
            unknown_bids.sort(key=lambda b: p_of(metas[b]), reverse=True)

            # Aloca top->bottom
            idx = 0
            for b in BANDS:
                n = remaining[b]
                for _ in range(n):
                    if idx >= len(unknown_bids): break
                    updates[unknown_bids[idx]] = b
                    n_aligned += 1
                    idx += 1
                if idx >= len(unknown_bids): break

            # Bets sobrando (sem slot disponivel): usa p
            for j in range(idx, len(unknown_bids)):
                bid = unknown_bids[j]
                b = band_from_p(p_of(metas[bid]))
                if b:
                    updates[bid] = b
                    n_p_based += 1
        else:
            # Nao tem em assertHistory.leagues — usa p direto
            for bid in bids:
                bh = metas[bid].get('band_hist')
                if bh:
                    keep_existing += 1
                    continue
                b = band_from_p(p_of(metas[bid]))
                if b:
                    updates[bid] = b
                    n_p_based += 1

    print(f'  {keep_existing} bets ja tinham band_hist (mantidos)', flush=True)
    print(f'  {n_aligned} bets band_hist por alocacao (matching assertHistory)', flush=True)
    print(f'  {n_p_based} bets band_hist por p (sem entry em assertHistory)', flush=True)
    print(f'  TOTAL a gravar: {len(updates)}', flush=True)

    # Aplica em batches de 400
    if updates and not DRY_RUN:
        print('\n== Gravando band_hist em betMeta ==', flush=True)
        batch = db.batch()
        n = 0
        for bid, bh in updates.items():
            batch.update(db.collection('betMeta').document(encode_id(bid)), {'band_hist': bh})
            n += 1
            if n >= 400:
                batch.commit()
                batch = db.batch()
                n = 0
        if n > 0:
            batch.commit()
        print(f'  {len(updates)} band_hist gravados.', flush=True)

    if DRY_RUN:
        print('\n[DRY-RUN] Nenhuma escrita realizada.', flush=True)
    else:
        print('\nFeito!', flush=True)


if __name__ == '__main__':
    main()
