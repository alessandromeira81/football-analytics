"""
Salva insights de bets >= 80% no Firestore betMeta SERVER-SIDE.

Antes deste script existir, o save era 100% client-side via
_autoSaveAllMeta() — so funcionava se Alessandro abrisse o dashboard
logado. Quando o usuario nao abria, os bets nao eram salvos e
assertividade_sync.py nao tinha como marcar outcomes.

Agora roda no daily-scraper com FIREBASE_SERVICE_ACCOUNT (admin):
- Abre index.html em Playwright (computa insights via JS)
- Filtra bets com prob >= 80%
- Salva betMeta no Firestore (NAO sobrescreve se ja existir,
  para preservar p_original congelado)

Uso:
  FIREBASE_SERVICE_ACCOUNT='<json>' python save_upcoming_bets.py
"""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

REPO_ROOT = Path(__file__).parent.absolute()
HTML_PATH = REPO_ROOT / 'index.html'


def encode_id(b):
    return b.replace('|', '__pipe__').replace('/', '__slash__')


def extract_bets():
    """Extrai todos os bets via Playwright headless."""
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

        all_bets = page.evaluate('computeAllInsights()')
        browser.close()

    return all_bets


def main():
    sa_json = os.environ.get('FIREBASE_SERVICE_ACCOUNT', '')
    if not sa_json:
        print('FIREBASE_SERVICE_ACCOUNT nao definida. Saindo.', flush=True)
        sys.exit(1)

    import firebase_admin
    from firebase_admin import credentials, firestore as fs
    cred = credentials.Certificate(json.loads(sa_json))
    firebase_admin.initialize_app(cred)
    db = fs.client()

    print('== Extraindo bets via Playwright ==', flush=True)
    all_bets = extract_bets()
    print(f'  {len(all_bets)} bets totais extraidos', flush=True)

    # Filtra bets >= 80%
    bets_80 = []
    for b in all_bets:
        p = b.get('p', 0)
        if p > 1:
            p = p / 100
        if p < 0.80:
            continue
        bets_80.append({**b, 'p_norm': p})

    print(f'  {len(bets_80)} bets >= 80% (insights)', flush=True)

    # Le betMeta existente pra nao sobrescrever
    print('\n== Lendo betMeta existente ==', flush=True)
    existing = set()
    existing_with_p_orig = set()
    for doc in db.collection('betMeta').stream():
        bet_id = doc.id.replace('__pipe__', '|').replace('__slash__', '/')
        existing.add(bet_id)
        if 'p_original' in (doc.to_dict() or {}):
            existing_with_p_orig.add(bet_id)
    print(f'  {len(existing)} bets existentes em betMeta', flush=True)

    # Salva novos / atualiza p (mas NUNCA sobrescreve p_original)
    print('\n== Gravando betMeta no Firestore ==', flush=True)
    batch = db.batch()
    n_new = n_updated = n_kept = 0
    batch_count = 0

    for b in bets_80:
        bet_id = b.get('betId', '')
        if not bet_id:
            continue
        doc_id = encode_id(bet_id)
        ref = db.collection('betMeta').document(doc_id)

        p = b['p_norm']
        date = b.get('date', '')
        lk = b.get('leagueKey', '')
        ln = b.get('leagueName', lk)

        if bet_id not in existing:
            # Novo bet — cria com p_original
            batch.set(ref, {
                'p':          p,
                'p_original': p,
                'date':       date,
                'leagueKey':  lk,
                'leagueName': ln,
            })
            n_new += 1
        elif bet_id not in existing_with_p_orig:
            # Existe mas sem p_original — atualiza apenas p_original (congela agora)
            batch.update(ref, {'p_original': p})
            n_updated += 1
        else:
            # Ja tem p_original — preserva
            n_kept += 1
            continue

        batch_count += 1
        if batch_count >= 400:
            batch.commit()
            batch = db.batch()
            batch_count = 0

    if batch_count > 0:
        batch.commit()

    print(f'  {n_new} novos | {n_updated} p_original atualizados | {n_kept} preservados', flush=True)
    print('\nFeito!', flush=True)


if __name__ == '__main__':
    main()
