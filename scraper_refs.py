"""
Scraper de árbitros do Brasileirão Série A.
Estratégia em duas camadas:
  1. Sofascore — já temos os IDs dos jogos, tenta pegar o árbitro via /event/{id}
  2. CBF — scraping da página de escala para os jogos que o Sofascore não tem ainda

Uso:
  python scraper_refs.py                  # atualiza brasileirao_2026_data.json
  python scraper_refs.py --dry-run        # mostra o que encontrou sem salvar
"""

import json
import os
import re
import sys
import time
from difflib import SequenceMatcher
from playwright.sync_api import sync_playwright

DATA_FILE  = "brasileirao_2026_data.json"
BASE_SF    = "https://www.sofascore.com/api/v1"
BASE_CBF   = "https://www.cbf.com.br"
DELAY      = 1.5
DRY_RUN    = "--dry-run" in sys.argv

# ── Fuzzy matching ────────────────────────────────────────────────────────────

def _sim(a, b):
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()

def _norm(name):
    """Normaliza nome de time para comparação entre CBF e Sofascore."""
    name = name.lower()
    for pat in [r'\bs/?a\b', r'\bfc\b', r'\bec\b', r'\bsc\b', r'\bac\b', r'\bbc\b']:
        name = re.sub(pat, '', name)
    subs = {
        'athletico': 'atlético', 'atletico': 'atlético',
        'bragantino': 'bragantino', 'red bull': 'bragantino',
        'vasco da gama': 'vasco', 'botafogo de futebol e regatas': 'botafogo',
        'sport club recife': 'sport', 'sport recife': 'sport',
        'ceará': 'ceara', 'goiás': 'goias', 'cuiabá': 'cuiaba',
        'fortaleza': 'fortaleza',
    }
    for k, v in subs.items():
        name = name.replace(k, v)
    return re.sub(r'\s+', ' ', name).strip()

def _best_match(home_cbf, away_cbf, scheduled):
    """Retorna (índice, score) do melhor match em scheduled."""
    best_idx, best_score = -1, 0
    for i, g in enumerate(scheduled):
        score = (_sim(_norm(home_cbf), _norm(g['homeTeam'])) +
                 _sim(_norm(away_cbf), _norm(g['awayTeam']))) / 2
        if score > best_score:
            best_score, best_idx = score, i
    return best_idx, best_score

# ── Camada 1: Sofascore ───────────────────────────────────────────────────────

def _sf_fetch(page, url):
    try:
        resp = page.evaluate(f"""
            async () => {{
                const r = await fetch('{url}', {{
                    headers: {{'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'}}
                }});
                if (!r.ok) return null;
                return await r.json();
            }}
        """)
        time.sleep(DELAY)
        return resp
    except Exception as e:
        print(f"    [SF fetch] erro em {url}: {e}", flush=True)
        return None

def fill_from_sofascore(page, scheduled):
    """Tenta pegar árbitro de cada jogo via Sofascore /event/{id}."""
    filled = 0
    for g in scheduled:
        if g.get('referee'):
            continue
        eid = g.get('id')
        if not eid:
            continue
        data = _sf_fetch(page, f"{BASE_SF}/event/{eid}")
        if not data:
            continue
        ref = (data.get('event') or {}).get('referee') or {}
        if ref.get('name'):
            g['referee'] = {'id': ref.get('id', 0), 'name': ref['name']}
            print(f"  [SF] {g['homeTeam']} x {g['awayTeam']}: {ref['name']}", flush=True)
            filled += 1
    return filled

# ── Camada 2: CBF ─────────────────────────────────────────────────────────────

def _cbf_escala_page(page):
    """
    Navega para a página de escala da CBF e extrai os dados de árbitro.
    Retorna lista de {homeTeam, awayTeam, referee_name}.
    """
    results = []
    urls = [
        f"{BASE_CBF}/a-cbf/arbitragem/escala-campeonato-brasileiro-serie-a",
        f"{BASE_CBF}/futebol-brasileiro/competicoes/campeonato-brasileiro-serie-a/2026",
    ]

    for url in urls:
        try:
            print(f"  [CBF] navegando: {url}", flush=True)
            page.goto(url, timeout=30000, wait_until='domcontentloaded')
            page.wait_for_timeout(3000)

            # Extrai via JS procurando padrões de árbitro + times na página
            found = page.evaluate("""
                () => {
                    const results = [];
                    const text = document.body.innerText || '';

                    // Padrão: bloco com dois times e árbitro
                    const blocks = document.querySelectorAll(
                        '.jogo, .partida, .match, .game, [class*="jogo"], [class*="partida"], [class*="match"]'
                    );

                    blocks.forEach(block => {
                        const t = block.innerText || '';
                        // Árbitro principal
                        const refMatch = t.match(/[Áá]rbitro(?:\\s+Principal)?[:\\s]+([A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][a-zàáâãéêíóôõúç]+(\\s[A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][a-zàáâãéêíóôõúç]+){1,4})/);
                        if (!refMatch) return;

                        // Times: pega os dois primeiros elementos com nome de time
                        const teamEls = block.querySelectorAll(
                            '[class*="time"], [class*="team"], [class*="clube"], [class*="mandante"], [class*="visitante"]'
                        );
                        const teams = [];
                        teamEls.forEach(el => {
                            const n = el.innerText.trim();
                            if (n && n.length > 2 && n.length < 40) teams.push(n);
                        });

                        if (teams.length >= 2) {
                            results.push({
                                home: teams[0],
                                away: teams[1],
                                referee: refMatch[1].trim()
                            });
                        }
                    });
                    return results;
                }
            """)

            if found:
                print(f"  [CBF] {len(found)} escalações encontradas", flush=True)
                for f in found:
                    results.append({
                        'homeTeam': f['home'],
                        'awayTeam': f['away'],
                        'referee_name': f['referee']
                    })
                return results

        except Exception as e:
            print(f"  [CBF] erro em {url}: {e}", flush=True)

    return results

def _cbf_match_links(page):
    """Tenta extrair links de partidas da CBF para buscar árbitros individualmente."""
    links = []
    try:
        page.goto(
            f"{BASE_CBF}/a-cbf/arbitragem/escala-campeonato-brasileiro-serie-a",
            timeout=30000, wait_until='domcontentloaded'
        )
        page.wait_for_timeout(3000)

        links = page.evaluate("""
            () => {
                const anchors = document.querySelectorAll('a[href*="/jogos/campeonato-brasileiro"]');
                return Array.from(anchors).map(a => a.href).filter(h => h.includes('/2026/'));
            }
        """)
        links = list(dict.fromkeys(links))  # deduplica
        print(f"  [CBF] {len(links)} links de partidas encontrados", flush=True)
    except Exception as e:
        print(f"  [CBF] erro ao buscar links: {e}", flush=True)
    return links

def _cbf_parse_match_page(page, url):
    """Extrai árbitro de uma página individual de partida da CBF."""
    try:
        target = url + ("&" if "?" in url else "?") + "view=escala-de-arbitros"
        page.goto(target, timeout=20000, wait_until='domcontentloaded')
        page.wait_for_timeout(2000)

        data = page.evaluate("""
            () => {
                const t = document.body.innerText || '';
                const refMatch = t.match(/[Áá]rbitro(?:\\s+Principal)?[:\\s]+([A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][a-zàáâãéêíóôõúç]+(\\s[A-ZÀÁÂÃÉÊÍÓÔÕÚÇ][a-zàáâãéêíóôõúç]+){1,4})/);
                const homeEl = document.querySelector('[class*="mandante"] [class*="nome"], [class*="home"] [class*="name"]');
                const awayEl = document.querySelector('[class*="visitante"] [class*="nome"], [class*="away"] [class*="name"]');
                return {
                    referee: refMatch ? refMatch[1].trim() : null,
                    home: homeEl ? homeEl.innerText.trim() : null,
                    away: awayEl ? awayEl.innerText.trim() : null,
                };
            }
        """)

        if data and data.get('referee') and data.get('home') and data.get('away'):
            return data
    except Exception as e:
        print(f"    [CBF match] erro em {url}: {e}", flush=True)
    return None

def fill_from_cbf(page, scheduled):
    """Preenche árbitros via scraping do site da CBF."""
    filled = 0

    # Tenta a página de escala diretamente primeiro
    cbf_refs = _cbf_escala_page(page)

    if not cbf_refs:
        # Fallback: pega links individuais de partidas e scrapa cada um
        links = _cbf_match_links(page)
        for url in links[:20]:  # limita a 20 para não demorar demais
            match_data = _cbf_parse_match_page(page, url)
            if match_data:
                cbf_refs.append({
                    'homeTeam': match_data['home'],
                    'awayTeam': match_data['away'],
                    'referee_name': match_data['referee']
                })

    if not cbf_refs:
        print("  [CBF] nenhuma escalação encontrada.", flush=True)
        return 0

    # Aplica aos jogos agendados via fuzzy matching
    for entry in cbf_refs:
        idx, score = _best_match(entry['homeTeam'], entry['awayTeam'], scheduled)
        if idx < 0 or score < 0.65:
            print(f"  [CBF] sem match para {entry['homeTeam']} x {entry['awayTeam']} (score={score:.2f})", flush=True)
            continue
        g = scheduled[idx]
        if g.get('referee'):
            continue  # já preenchido pelo Sofascore
        g['referee'] = {'id': 0, 'name': entry['referee_name']}
        print(f"  [CBF] {g['homeTeam']} x {g['awayTeam']}: {entry['referee_name']} (match={score:.2f})", flush=True)
        filled += 1

    return filled

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not os.path.exists(DATA_FILE):
        print(f"Arquivo {DATA_FILE} não encontrado.", flush=True)
        sys.exit(1)

    with open(DATA_FILE, encoding='utf-8') as f:
        data = json.load(f)

    scheduled = data.get('scheduledGames', [])
    if not scheduled:
        print("Nenhum jogo agendado no JSON.", flush=True)
        return

    missing = [g for g in scheduled if not g.get('referee')]
    print(f"\n{len(scheduled)} jogos agendados — {len(missing)} sem árbitro\n", flush=True)

    if not missing:
        print("Todos os jogos já têm árbitro. Nada a fazer.", flush=True)
        return

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
        ctx = browser.new_context(
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                       '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            locale='pt-BR'
        )
        page = ctx.new_page()

        # Camada 1: Sofascore
        print("── Camada 1: Sofascore ──────────────────────────────────", flush=True)
        n1 = fill_from_sofascore(page, scheduled)
        print(f"   {n1} árbitro(s) encontrado(s) via Sofascore\n", flush=True)

        # Camada 2: CBF (para os que ainda não têm)
        still_missing = [g for g in scheduled if not g.get('referee')]
        if still_missing:
            print("── Camada 2: CBF ────────────────────────────────────────", flush=True)
            n2 = fill_from_cbf(page, scheduled)
            print(f"   {n2} árbitro(s) encontrado(s) via CBF\n", flush=True)
        else:
            n2 = 0

        browser.close()

    total = n1 + n2
    print(f"\nTotal: {total} árbitro(s) atualizado(s)", flush=True)

    # Resumo final
    print("\nStatus final:", flush=True)
    for g in scheduled:
        ref = (g.get('referee') or {}).get('name', '— sem árbitro')
        print(f"  {g['homeTeam']} x {g['awayTeam']}: {ref}", flush=True)

    if total > 0 and not DRY_RUN:
        data['scheduledGames'] = scheduled
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"\n✅ {DATA_FILE} atualizado.", flush=True)
    elif DRY_RUN:
        print("\n[dry-run] Nenhum arquivo modificado.", flush=True)
    else:
        print("\nNenhum árbitro novo encontrado. JSON não modificado.", flush=True)

if __name__ == '__main__':
    main()
