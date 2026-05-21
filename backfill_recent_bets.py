"""
BACKFILL ONE-TIME: recupera bets dos dias 17-19/05/2026 que nunca foram
salvos no Firestore porque o usuario nao abriu o dashboard nesses dias.

Estrategia:
1. Abre index.html em Playwright (carrega SCRAPED_DATA com games + scheduledGames)
2. Para cada jogo em games[] com data nos dias-alvo:
   a. Chama computeMatchInsights() para gerar os mesmos bets que seriam mostrados
   b. Para cada bet >= 80%, salva betMeta com p_original (se nao existir)
3. Depois roda assertividade_sync.py para marcar outcomes a partir dos placares.

Caveat: as stats atuais incluem os proprios jogos sendo analisados,
o que adiciona pequeno bias. Em ~30 jogos de temporada, adicionar 1 jogo
move medias em <5%. Insights serao aproximacao razoavel do que foi
mostrado na epoca.

Uso:
  FIREBASE_SERVICE_ACCOUNT='<json>' python backfill_recent_bets.py
"""
import json, os, sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')

REPO_ROOT = Path(__file__).parent.absolute()
HTML_PATH = REPO_ROOT / 'index.html'

TARGET_DATES = ['2026-05-17', '2026-05-18', '2026-05-19']


def encode_id(b):
    return b.replace('|', '__pipe__').replace('/', '__slash__')


def extract_historical_bets():
    """
    Roda Playwright e computa insights para jogos passados nos TARGET_DATES.
    Retorna dict betId -> {league_key, league_name, home, away, date, label, p, cat}
    """
    from playwright.sync_api import sync_playwright

    file_url = HTML_PATH.as_uri()
    print(f'  Abrindo {file_url}', flush=True)

    js_code = """
    (function() {
      const targetDates = %s;
      const results = [];
      const sd = window.SCRAPED_DATA || {};
      const savedGames = window.SCRAPED_GAMES;
      const savedByTeam = window.SCRAPED_BY_TEAM;

      Object.keys(window.LEAGUES_META).forEach(key => {
        const data = sd[key];
        if (!data || !data.games || !data.games.length) return;

        window.SCRAPED_GAMES = data.games;
        window.SCRAPED_BY_TEAM = window.aggregateGames(data.games);

        const meta = window.LEAGUES_META[key];

        // Itera todos os games (finalizados) com data nos alvos
        data.games.forEach(game => {
          if (!targetDates.includes(game.date)) return;

          const refName = game.referee ? (game.referee.name || game.referee) : '';
          const result = window.computeMatchInsights(game.homeTeam, game.awayTeam, refName);
          if (!result) return;

          result.bets.forEach(bet => {
            const betId = key + '|' + game.homeTeam + '|' + game.awayTeam + '|' + bet.label;
            let p = bet.p;
            if (p > 1) p = p / 100;
            if (p < 0.80) return;

            results.push({
              betId: betId,
              league_key: key,
              league_name: meta.name,
              home: game.homeTeam,
              away: game.awayTeam,
              date: game.date,
              label: bet.label,
              p: p,
              cat: bet.cat,
              score: game.score
            });
          });
        });
      });

      window.SCRAPED_GAMES = savedGames;
      window.SCRAPED_BY_TEAM = savedByTeam;
      return results;
    })()
    """ % json.dumps(TARGET_DATES)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context()
        page = ctx.new_page()
        page.on('pageerror', lambda e: None)

        page.goto(file_url, wait_until='domcontentloaded', timeout=30000)
        page.wait_for_function(
            'window.SCRAPED_DATA && '
            'typeof window.computeMatchInsights === "function" && '
            'Object.keys(window.SCRAPED_DATA).length > 0',
            timeout=30000
        )
        page.wait_for_timeout(5000)

        bets = page.evaluate(js_code)
        browser.close()

    return bets


def evaluate_outcome(label, score):
    """Mesma logica do assertividade_sync.evaluate_bet, simplificada."""
    if not score: return None
    sh, sa = score.get('home'), score.get('away')
    if sh is None or sa is None: return None

    tot = sh + sa
    btts = sh > 0 and sa > 0

    if label == 'Vitoria Mandante':  return 'verde' if sh > sa else 'vermelho'
    if label == 'Empate':            return 'verde' if sh == sa else 'vermelho'
    if label == 'Vitoria Visitante': return 'verde' if sa > sh else 'vermelho'
    if label == 'BTTS - Sim':        return 'verde' if btts else 'vermelho'
    if label == 'BTTS - Nao':        return 'verde' if not btts else 'vermelho'

    import re
    m = re.match(r'^(Over|Under) (\d+\.5) gols$', label)
    if m:
        line = float(m.group(2))
        if m.group(1) == 'Over': return 'verde' if tot > line else 'vermelho'
        else:                    return 'verde' if tot < line else 'vermelho'

    # Outros mercados (escanteios/cartoes/etc) precisariam de stats — pula
    return None


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

    print('== Backfilling bets de 17-19/05/2026 ==', flush=True)
    bets = extract_historical_bets()
    print(f'  {len(bets)} bets >= 80% encontrados para os dias-alvo', flush=True)

    # Le betMeta existente
    existing_meta = set()
    existing_outcomes = set()
    for doc in db.collection('betMeta').stream():
        existing_meta.add(doc.id)
    for doc in db.collection('betOutcomes').stream():
        existing_outcomes.add(doc.id)

    # Salva
    print('\n== Gravando ==', flush=True)
    batch = db.batch()
    n_meta = n_outcomes = n_batch = 0

    for b in bets:
        doc_id = encode_id(b['betId'])

        # betMeta
        if doc_id not in existing_meta:
            batch.set(db.collection('betMeta').document(doc_id), {
                'p':          b['p'],
                'p_original': b['p'],
                'date':       b['date'],
                'leagueKey':  b['league_key'],
                'leagueName': b['league_name'],
            })
            n_meta += 1
            n_batch += 1

        # betOutcomes (so mercados suportados pelo evaluate_outcome)
        if doc_id not in existing_outcomes:
            outcome = evaluate_outcome(b['label'], b['score'])
            if outcome:
                batch.set(db.collection('betOutcomes').document(doc_id), {'value': outcome})
                n_outcomes += 1
                n_batch += 1
                print(f'  {b["date"]} | {b["home"][:15]} x {b["away"][:15]} | {b["label"]} | {round(b["p"]*100)}% → {outcome}', flush=True)

        if n_batch >= 400:
            batch.commit()
            batch = db.batch()
            n_batch = 0

    if n_batch > 0:
        batch.commit()

    print(f'\n  {n_meta} betMeta novos | {n_outcomes} outcomes marcados', flush=True)


if __name__ == '__main__':
    main()
