"""
Corrige assertHistory no Firestore usando o gabarito extraido do HTML salvo.
Tambem grava p_original em betMeta para congelar o p historico de cada aposta.

Uso:
  FIREBASE_SERVICE_ACCOUNT='<json>' python fix_history_bands.py [--dry-run]
"""
import json, os, re, sys

sys.stdout.reconfigure(encoding='utf-8')

DRY_RUN = '--dry-run' in sys.argv

HTML_FILE = "football_analytics_01 a 05.html"

# --------------------------------------------------------------------------
def parse_embedded(html_path):
    with open(html_path, encoding='utf-8') as f:
        content = f.read()
    marker_start = 'var ASSERT_EMBEDDED = '
    marker_end   = '}; /* ASSERT_DATA_MARKER */'
    s = content.find(marker_start)
    e = content.find(marker_end, s)
    if s == -1 or e == -1:
        raise ValueError("ASSERT_EMBEDDED nao encontrado no HTML")
    return json.loads(content[s + len(marker_start): e + 1])


def band_of(p_pct):
    if p_pct >= 95: return 'rb-95'
    if p_pct >= 90: return 'rb-90'
    if p_pct >= 85: return 'rb-85'
    if p_pct >= 80: return 'rb-80'
    return None


def encode_id(bet_id):
    return bet_id.replace('|', '__pipe__').replace('/', '__slash__')


def decode_id(encoded):
    return encoded.replace('__pipe__', '|').replace('__slash__', '/')


# --------------------------------------------------------------------------
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

    print(f'\n== Lendo {HTML_FILE} ==', flush=True)
    data = parse_embedded(HTML_FILE)

    history_gt = data.get('__history__') or []
    meta_gt    = data.get('__meta__') or {}
    print(f'  {len(history_gt)} entradas de historico', flush=True)
    print(f'  {len(meta_gt)} entradas de meta', flush=True)

    # ------------------------------------------------------------------
    # 1) Corrige assertHistory no Firestore com os dados do gabarito
    # ------------------------------------------------------------------
    print('\n== Corrigindo assertHistory ==', flush=True)
    today = __import__('datetime').date.today().isoformat()

    for entry in sorted(history_gt, key=lambda x: x['date']):
        date  = entry['date']
        bands = entry['bands']
        total = entry['total']
        leagues = entry.get('leagues', {})

        tv = total.get('verde', 0)
        tr = total.get('vermelho', 0)
        pct = round(tv / (tv + tr) * 100) if (tv + tr) else 0

        band_summary = {k: v['verde']+v['vermelho'] for k,v in bands.items()}

        # Le o que esta no Firestore agora
        ref = db.collection('assertHistory').document(date)
        existing = ref.get().to_dict() if ref.get().exists else {}
        ex_tv = existing.get('total', {}).get('verde', 0)
        ex_tr = existing.get('total', {}).get('vermelho', 0)
        ex_bands = {k: v['verde']+v['vermelho'] for k,v in existing.get('bands', {}).items()}

        changed = (ex_bands != band_summary) or (ex_tv != tv) or (ex_tr != tr)

        if changed:
            print(f'  CORRIGINDO {date}: {tv}V/{tr}R={pct}%', flush=True)
            print(f'    Firestore bands: {ex_bands}', flush=True)
            print(f'    Gabarito bands:  {band_summary}', flush=True)
            if not DRY_RUN:
                ref.set({'date': date, 'bands': bands, 'total': total, 'leagues': leagues})
        else:
            print(f'  OK {date}: {tv}V/{tr}R={pct}% bands={band_summary}', flush=True)

    # ------------------------------------------------------------------
    # 2) Grava p_original em betMeta (nunca sobrescreve se ja existir)
    # ------------------------------------------------------------------
    print('\n== Gravando p_original em betMeta ==', flush=True)
    n_updated = n_skipped = n_missing = 0

    for bet_id, m_raw in sorted(meta_gt.items()):
        if bet_id in ('__history__',):
            continue
        m = json.loads(m_raw) if isinstance(m_raw, str) else m_raw
        p_orig = m.get('p', 0)
        if p_orig > 1:
            p_orig = p_orig / 100.0   # normaliza: 97 -> 0.97
        date   = m.get('date', '')
        lk     = m.get('leagueKey', '')
        ln     = m.get('leagueName', '')

        # Pula Tottenham com data futura (dado inconsistente no HTML)
        if date > today:
            print(f'  SKIP (data futura {date}): {bet_id[:60]}', flush=True)
            continue

        if band_of(p_orig * 100) is None:
            print(f'  SKIP (p={p_orig:.3f} fora das bandas): {bet_id[:60]}', flush=True)
            continue

        doc_id = encode_id(bet_id)
        ref = db.collection('betMeta').document(doc_id)
        snap = ref.get()

        if snap.exists:
            existing_meta = snap.to_dict()
            if 'p_original' in existing_meta:
                # Ja tem p_original: nao sobrescreve
                n_skipped += 1
                continue
            # Adiciona p_original sem alterar o resto
            if not DRY_RUN:
                ref.update({'p_original': p_orig})
            print(f'  SET p_original={p_orig:.4f} | {bet_id[:70]}', flush=True)
            n_updated += 1
        else:
            # betMeta nao existe ainda: cria com p_original = p
            if not DRY_RUN:
                ref.set({'p': p_orig, 'p_original': p_orig, 'date': date,
                         'leagueKey': lk, 'leagueName': ln})
            print(f'  CRIADO p={p_orig:.4f} | {bet_id[:70]}', flush=True)
            n_updated += 1

    print(f'\n  {n_updated} atualizados, {n_skipped} ja tinham p_original, {n_missing} nao encontrados', flush=True)
    if DRY_RUN:
        print('\n[DRY-RUN] Nenhuma escrita realizada.', flush=True)
    else:
        print('\nFeito!', flush=True)


if __name__ == '__main__':
    main()
