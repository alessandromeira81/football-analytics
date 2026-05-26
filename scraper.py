"""
Football Analytics -- Sofascore Multi-League Scraper (Playwright)
Coleta: escanteios, finalizacoes, finalizacoes no alvo, cartoes, faltas.
Granularidade: total + 1T/2T (stats) + minuto exato (incidents para cartoes).

Uso:
  python scraper.py                      # brasileirao (padrao)
  python scraper.py --liga premier       # Premier League
  python scraper.py --liga laliga
  python scraper.py --liga bundesliga
  python scraper.py --liga ligue1
  python scraper.py --liga argentina
  python scraper.py --liga seriea
  python scraper.py --liga mls
  python scraper.py --liga all           # todas as ligas em sequencia
  python scraper.py --full               # coleta completa (sem incremental)
  python scraper.py 15                   # ate rodada 15
"""

import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

# ─── Configuracao das ligas ───────────────────────────────────────────────────

LEAGUES = {
    'brasileirao': {
        'name':          'Brasileirao Serie A',
        'short':         'BRA',
        'country':       'Brasil',
        'tournament_id': 325,
        'season_id':     87678,   # 2026 — fixo
        'out_file':      'brasileirao_2026_data.json',
        'home_url':      'https://www.sofascore.com/pt/football/tournament/brazil/brasileirao-serie-a/325',
    },
    'premier': {
        'name':          'Premier League',
        'short':         'ENG',
        'country':       'Inglaterra',
        'tournament_id': 17,
        'season_id':     None,    # auto-discover
        'out_file':      'premier_league_data.json',
        'home_url':      'https://www.sofascore.com/football/tournament/england/premier-league/17',
    },
    'laliga': {
        'name':          'La Liga',
        'short':         'ESP',
        'country':       'Espanha',
        'tournament_id': 8,
        'season_id':     None,
        'out_file':      'laliga_data.json',
        'home_url':      'https://www.sofascore.com/football/tournament/spain/laliga/8',
    },
    'bundesliga': {
        'name':          'Bundesliga',
        'short':         'GER',
        'country':       'Alemanha',
        'tournament_id': 35,
        'season_id':     None,
        'out_file':      'bundesliga_data.json',
        'home_url':      'https://www.sofascore.com/football/tournament/germany/bundesliga/35',
    },
    'ligue1': {
        'name':          'Ligue 1',
        'short':         'FRA',
        'country':       'Franca',
        'tournament_id': 34,
        'season_id':     None,
        'out_file':      'ligue1_data.json',
        'home_url':      'https://www.sofascore.com/football/tournament/france/ligue-1/34',
    },
    'saudi': {
        'name':          'Saudi Pro League',
        'short':         'KSA',
        'country':       'Arabia Saudita',
        'tournament_id': 955,
        'season_id':     None,
        'out_file':      'saudi_data.json',
        'home_url':      'https://www.sofascore.com/football/saudi-arabia/saudi-professional-league/955',
    },
    'argentina': {
        'name':          'Liga Profesional',
        'short':         'ARG',
        'country':       'Argentina',
        'tournament_id': 155,
        'season_id':     None,
        'out_file':      'argentina_data.json',
        'home_url':      'https://www.sofascore.com/football/argentina/liga-profesional/155',
    },
    'seriea': {
        'name':          'Serie A',
        'short':         'ITA',
        'country':       'Italia',
        'tournament_id': 23,
        'season_id':     None,
        'out_file':      'seriea_data.json',
        'home_url':      'https://www.sofascore.com/football/italy/serie-a/23',
    },
    'mls': {
        'name':          'MLS',
        'short':         'USA',
        'country':       'Estados Unidos',
        'tournament_id': 242,
        'season_id':     None,
        'out_file':      'mls_data.json',
        'home_url':      'https://www.sofascore.com/football/tournament/usa/mls/242',
    },
}

DELAY = 1.2
BASE  = "https://api.sofascore.com/api/v1"

STAT_KEYS = {
    "cornerKicks":      "corners",
    "totalShotsOnGoal": "shots",
    "shotsOnGoal":      "shotsOnTarget",
    "yellowCards":      "yellowCards",
    "fouls":            "fouls",
}
PERIOD_MAP = {"ALL": "all", "1ST": "1t", "2ND": "2t"}


# ─── Fetch via browser context ────────────────────────────────────────────────

def browser_fetch(page, url):
    """Faz requisicao HTTP via Playwright APIRequestContext.

    Usa o mesmo cookie jar do navegador (mesma sessao que o Sofascore viu),
    sem as restricoes de CORS do JavaScript in-page.
    """
    try:
        resp = page.context.request.get(
            url,
            headers={
                "Accept":           "application/json, text/plain, */*",
                "Accept-Language":  "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
                "Cache-Control":    "no-cache",
                "Pragma":           "no-cache",
                "Referer":          "https://www.sofascore.com/",
                "Origin":           "https://www.sofascore.com",
                "Sec-Fetch-Dest":   "empty",
                "Sec-Fetch-Mode":   "cors",
                "Sec-Fetch-Site":   "same-site",
            },
            timeout=20000,
        )
        if not resp.ok:
            print(f"  [ERR] HTTP {resp.status} → ...{url[-60:]}", flush=True)
            return None
        return resp.json()
    except Exception as e:
        print(f"  [ERR] {e}", flush=True)
        return None


# ─── Season discovery ─────────────────────────────────────────────────────────

def navigate_and_discover_season(page, tournament_id, home_url, known_sid=None):
    """Navega para a pagina da liga e descobre o season_id.

    Se known_sid fornecido, navega normalmente e devolve-o.
    Senao, intercepta as requisicoes de rede que o Sofascore faz ao carregar
    a pagina — todas incluem /season/{id}/ na URL, o que revela o season atual.
    Fallback: endpoint /seasons.
    """
    if known_sid:
        try:
            page.goto(home_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
        except Exception as e:
            print(f"  [WARN] Navegacao para home da liga falhou: {e}", flush=True)
        return known_sid

    # Intercepta requisicoes para capturar o season_id dinamicamente
    captured = {"sid": None}
    pattern  = re.compile(rf"/unique-tournament/{tournament_id}/season/(\d+)/")

    def on_request(request):
        if captured["sid"]:
            return
        m = pattern.search(request.url)
        if m:
            captured["sid"] = int(m.group(1))

    page.on("request", on_request)
    try:
        # networkidle espera todas as requests terminarem (mais confiavel para SPA)
        page.goto(home_url, wait_until="networkidle", timeout=45000)
    except Exception:
        try:
            page.goto(home_url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)
        except Exception as e:
            print(f"  [WARN] Erro ao navegar: {e}", flush=True)
    finally:
        page.remove_listener("request", on_request)

    if captured["sid"]:
        print(f"  Season capturada via rede: id={captured['sid']}", flush=True)
        return captured["sid"]

    # Fallback: endpoint /seasons
    url  = f"{BASE}/unique-tournament/{tournament_id}/seasons"
    data = browser_fetch(page, url)
    if data and "seasons" in data and data["seasons"]:
        sid   = data["seasons"][0].get("id")
        sname = data["seasons"][0].get("name", "?")
        print(f"  Season via API: {sname} (id={sid})", flush=True)
        return sid

    # Fallback 2: reinicia sessao e tenta novamente
    print(f"  [RETRY] Aguardando 15s e retentando discovery para tournament {tournament_id}...", flush=True)
    time.sleep(15)
    try:
        page.goto("https://www.sofascore.com", wait_until="domcontentloaded", timeout=20000)
        time.sleep(5)
        data2 = browser_fetch(page, f"{BASE}/unique-tournament/{tournament_id}/seasons")
        if data2 and "seasons" in data2 and data2["seasons"]:
            sid2   = data2["seasons"][0].get("id")
            sname2 = data2["seasons"][0].get("name", "?")
            print(f"  Season via API (retry): {sname2} (id={sid2})", flush=True)
            return sid2
        print(f"  [DEBUG] /seasons (retry) retornou: {str(data2)[:300]}", flush=True)
    except Exception as e2:
        print(f"  [WARN] Retry falhou: {e2}", flush=True)

    print(f"  [WARN] season_id nao encontrado para tournament {tournament_id}", flush=True)
    print(f"  [DEBUG] /seasons (tentativa inicial) retornou: {str(data)[:300]}", flush=True)
    return None


# ─── Parsers ──────────────────────────────────────────────────────────────────

def parse_statistics(data):
    result = {p: {} for p in PERIOD_MAP.values()}
    if not data or "statistics" not in data:
        return result
    for group_block in data["statistics"]:
        period_key = PERIOD_MAP.get(group_block.get("period"))
        if not period_key:
            continue
        for group in group_block.get("groups", []):
            for stat in group.get("statisticsItems", []):
                key    = stat.get("key")
                mapped = STAT_KEYS.get(key)
                if mapped:
                    result[period_key][mapped] = {
                        "home": _safe_int(stat.get("home")),
                        "away": _safe_int(stat.get("away")),
                    }
    return result


def parse_event_odds(data):
    """Extrai odds do endpoint /event/{id}/odds/{src}/all ou /featured.
    Chave: '{marketName}_{choiceGroup}_{choiceName}' quando ha choiceGroup
           '{marketName}_{choiceName}' quando nao ha (ex: 'Full time_1')
    Ex: 'Match goals_2.5_Over', 'Cards in match_3.5_Over', 'Full time_1'
    """
    odds = {}
    if not data or not isinstance(data, dict):
        return odds

    # /all endpoint: {"markets": [...], "eventId": N}
    # /featured endpoint: {"featured": {id: market, ...}, "hasMoreOdds": bool}
    if "markets" in data:
        items = data["markets"] if isinstance(data["markets"], list) else []
    else:
        raw = data.get("featured") or {}
        items = list(raw.values()) if isinstance(raw, dict) else (raw if isinstance(raw, list) else [])

    for market in items:
        if not isinstance(market, dict):
            continue
        mname  = (market.get("marketName") or "").strip()
        cgroup = (market.get("choiceGroup") or "").strip()
        choices = market.get("choices") or []
        for ch in choices:
            if not isinstance(ch, dict):
                continue
            cname = (ch.get("name") or "").strip()
            key   = f"{mname}_{cgroup}_{cname}" if cgroup else f"{mname}_{cname}"
            dec   = ch.get("decimalValue")
            if dec is not None:
                try:
                    odds[key] = round(float(dec), 2)
                    continue
                except (TypeError, ValueError):
                    pass
            frac = ch.get("fractionalValue") or ""
            if isinstance(frac, str) and "/" in frac:
                try:
                    num, den = frac.split("/")
                    odds[key] = round(1 + int(num) / int(den), 2)
                except (ValueError, ZeroDivisionError):
                    pass
    return odds


def parse_referee(data):
    if not data or "event" not in data:
        return {}
    ref = (data.get("event") or {}).get("referee") or {}
    if not ref.get("id"):
        return {}
    return {"id": ref["id"], "name": ref.get("name", "")}


def parse_incidents(data):
    cards = []
    if not data or "incidents" not in data:
        return cards
    for inc in data["incidents"]:
        if inc.get("incidentType") != "card":
            continue
        cls = inc.get("incidentClass", "")
        if cls not in ("yellow", "yellowRed", "red"):
            continue
        minute = inc.get("time", 0)
        if minute < 0:
            continue
        added     = inc.get("addedTime") or 0
        total_min = minute + added
        is_home   = inc.get("isHome", True)
        card_type = "yellow" if cls == "yellow" else "red"
        cards.append({
            "type":   card_type,
            "minute": total_min,
            "isHome": is_home,
            "period": "1t" if minute <= 45 else "2t",
        })
    return cards


def _safe_int(val):
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


# ─── Coleta de um jogo ────────────────────────────────────────────────────────

def collect_game(page, event, round_num):
    eid       = event["id"]
    home_team = event["homeTeam"]["name"]
    away_team = event["awayTeam"]["name"]
    home_id   = event["homeTeam"]["id"]
    away_id   = event["awayTeam"]["id"]

    score_home = (event.get("homeScore") or {}).get("current") or 0
    score_away = (event.get("awayScore") or {}).get("current") or 0

    ts       = event.get("startTimestamp", 0)
    date_str = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else ""

    stats_data = browser_fetch(page, f"{BASE}/event/{eid}/statistics")
    time.sleep(DELAY)
    inc_data   = browser_fetch(page, f"{BASE}/event/{eid}/incidents")
    time.sleep(DELAY)
    ev_detail  = browser_fetch(page, f"{BASE}/event/{eid}")
    time.sleep(DELAY)

    stats   = parse_statistics(stats_data)
    cards   = parse_incidents(inc_data)
    referee = parse_referee(ev_detail)

    red_home = sum(1 for c in cards if c["type"] == "red" and c["isHome"])
    red_away = sum(1 for c in cards if c["type"] == "red" and not c["isHome"])
    for period in ("all", "1t", "2t"):
        stats[period]["redCards"] = {"home": red_home, "away": red_away}

    return {
        "id":       eid,
        "round":    round_num,
        "date":     date_str,
        "homeTeam": home_team,
        "awayTeam": away_team,
        "homeId":   home_id,
        "awayId":   away_id,
        "score":    {"home": int(score_home), "away": int(score_away)},
        "stats":    stats,
        "cards":    cards,
        "referee":  referee,
    }


# ─── Backfill ─────────────────────────────────────────────────────────────────

def backfill_referee(page, games_by_id):
    missing = [g for g in games_by_id.values() if "referee" not in g]
    if not missing:
        return 0
    print(f"\nBackfill arbitros: {len(missing)} jogos sem dado...", flush=True)
    count = 0
    for g in missing:
        eid  = g["id"]
        data = browser_fetch(page, f"{BASE}/event/{eid}")
        time.sleep(DELAY)
        g["referee"] = parse_referee(data)
        count += 1
        if count % 20 == 0:
            print(f"  {count}/{len(missing)} concluidos", flush=True)
    print(f"  OK: {count} arbitros preenchidos", flush=True)
    return count


def backfill_stats(page, games_by_id):
    missing = [g for g in games_by_id.values()
               if "fouls" not in (g.get("stats", {}).get("all") or {})]
    if not missing:
        return 0
    print(f"\nBackfill stats: {len(missing)} jogos sem fouls...", flush=True)
    count = 0
    for g in missing:
        eid  = g["id"]
        data = browser_fetch(page, f"{BASE}/event/{eid}/statistics")
        time.sleep(DELAY)
        new_stats = parse_statistics(data)
        for period in ("all", "1t", "2t"):
            g["stats"][period].update(new_stats[period])
        count += 1
        if count % 20 == 0:
            print(f"  {count}/{len(missing)} concluidos", flush=True)
    print(f"  OK: {count} jogos com stats atualizados", flush=True)
    return count


# ─── Persistencia ─────────────────────────────────────────────────────────────

def load_existing(out_file):
    if not os.path.exists(out_file):
        return {}, 0, None
    try:
        with open(out_file, encoding="utf-8") as f:
            data = json.load(f)
        meta        = data.get("meta", {})
        games_by_id = {g["id"]: g for g in data.get("games", [])}
        last_round  = meta.get("lastRound", 0)
        season_id   = meta.get("seasonId")          # reutiliza season_id ja descoberto
        print(f"JSON existente: {len(games_by_id)} jogos, ultima coleta rodada {last_round}", flush=True)
        if season_id:
            print(f"  Season_id cached no JSON: {season_id}", flush=True)
        return games_by_id, last_round, season_id
    except Exception as e:
        print(f"Aviso: nao foi possivel ler JSON existente ({e})", flush=True)
        return {}, 0, None


# ─── Injecao no HTML ──────────────────────────────────────────────────────────

def inject_into_html(league_key, data):
    """Injeta dados da liga no bloco especifico do HTML do dashboard."""
    # Tenta app.html (novo nome) primeiro; fallback para index.html (legado)
    for cand in ("app.html", "index.html"):
        if os.path.exists(cand):
            html_file = cand
            break
    else:
        print(f"Aviso: app.html/index.html nao encontrado, injecao ignorada.", flush=True)
        return

    with open(html_file, encoding="utf-8") as f:
        html = f.read()

    json_str  = json.dumps(data, ensure_ascii=False)
    start_tag = f"<!-- SCRAPED_DATA_{league_key}_START -->"
    end_tag   = f"<!-- SCRAPED_DATA_{league_key}_END -->"

    new_block = (
        f"{start_tag}\n"
        f"<script>window.SCRAPED_DATA=window.SCRAPED_DATA||{{}};window.SCRAPED_DATA['{league_key}']={json_str};</script>\n"
        f"{end_tag}"
    )

    if start_tag not in html:
        print(f"Aviso: marcador {start_tag} nao encontrado no HTML.", flush=True)
        return

    updated = re.sub(
        rf'{re.escape(start_tag)}.*?{re.escape(end_tag)}',
        new_block,
        html,
        flags=re.DOTALL,
    )

    with open(html_file, "w", encoding="utf-8") as f:
        f.write(updated)
    print(f"OK: dados de '{league_key}' injetados em {html_file}", flush=True)


# ─── Coleta de uma liga ───────────────────────────────────────────────────────

def run_league(page, league_key, force_full=False, max_round_arg=None):
    league = LEAGUES[league_key]
    tid    = league['tournament_id']

    print(f"\n{'='*56}", flush=True)
    print(f"  Liga: {league['name']} ({league['country']})", flush=True)
    print(f"{'='*56}", flush=True)

    # Carrega JSON existente primeiro — recupera season_id ja descoberto anteriormente
    games_by_id, last_collected, cached_sid = load_existing(league['out_file'])

    # Prefere: 1) season_id fixo no config  2) season_id salvo no JSON  3) auto-discovery
    effective_sid = league['season_id'] or cached_sid

    # Navega para a pagina da liga e descobre/confirma o season_id
    sid = navigate_and_discover_season(page, tid, league['home_url'], known_sid=effective_sid)
    if sid is None:
        print("ERRO: season_id nao encontrado. Pulando liga.", flush=True)
        return

    backfilled  = backfill_referee(page, games_by_id)
    backfilled += backfill_stats(page, games_by_id)

    rounds_data = browser_fetch(page, f"{BASE}/unique-tournament/{tid}/season/{sid}/rounds")
    if not rounds_data:
        print("ERRO: nao foi possivel acessar a API do Sofascore", flush=True)
        return

    # currentRound pode nao estar presente (ex: final da temporada)
    # Fallback: maior rodada listada em "rounds"
    current_round = (rounds_data.get("currentRound") or {}).get("round")
    if not current_round:
        all_rounds = [r.get("round", 0) for r in rounds_data.get("rounds", [])]
        current_round = max(all_rounds) if all_rounds else 38
    # Garante que max_round nunca regride abaixo do que ja temos coletado
    max_round = max_round_arg or max(current_round, last_collected)
    print(f"  Rodada detectada: {current_round} | coletando ate: {max_round}", flush=True)

    if force_full or last_collected == 0:
        start_round = 1
        print(f"Modo: coleta completa (rodadas 1 a {max_round})", flush=True)
    else:
        # Re-coleta a ultima rodada (pode ter jogos novos) + novas rodadas
        start_round = last_collected
        print(f"Modo: incremental — rodadas {start_round} a {max_round}", flush=True)

    new_count = 0
    for rnd in range(start_round, max_round + 1):
        print(f"\n[Rodada {rnd:2d}]", end=" ", flush=True)
        ev_data = browser_fetch(page, f"{BASE}/unique-tournament/{tid}/season/{sid}/events/round/{rnd}")
        time.sleep(DELAY)

        if not ev_data or "events" not in ev_data:
            print("sem dados", flush=True)
            continue

        finished = [e for e in ev_data["events"] if (e.get("status") or {}).get("type") == "finished"]
        already  = sum(1 for e in finished if e["id"] in games_by_id)
        fetch_ev = [e for e in finished if e["id"] not in games_by_id]
        print(f"{len(finished)} jogos ({already} ja coletados, {len(fetch_ev)} novos)", flush=True)

        for i, ev in enumerate(fetch_ev):
            home = ev["homeTeam"]["name"]
            away = ev["awayTeam"]["name"]
            print(f"  {i+1:2d}. {home[:15]:<15} x {away[:15]:<15}", end=" ", flush=True)
            game = collect_game(page, ev, rnd)
            games_by_id[game["id"]] = game
            new_count += 1
            corners_h = (game["stats"].get("all") or {}).get("corners", {}).get("home", "?")
            corners_a = (game["stats"].get("all") or {}).get("corners", {}).get("away", "?")
            print(f"escanteios: {corners_h}-{corners_a}", flush=True)

    # Proxima rodada (jogos agendados para Insights)
    # Sofascore pode retornar currentRound como o round em andamento/proximo,
    # entao testamos max_round e max_round+1 e usamos o primeiro que tiver
    # jogos ainda nao iniciados.
    scheduled = []
    for candidate_rnd in [max_round, max_round + 1]:
        sched_data = browser_fetch(page, f"{BASE}/unique-tournament/{tid}/season/{sid}/events/round/{candidate_rnd}")
        time.sleep(DELAY)
        if not sched_data or "events" not in sched_data:
            continue
        unplayed = [e for e in sched_data["events"]
                    if (e.get("status") or {}).get("type") == "notstarted"]
        if unplayed:
            for ev in sched_data["events"]:
                eid = ev["id"]
                ts  = ev.get("startTimestamp", 0)
                # Busca odds completas via /all (tem Over/Under, escanteios, cartoes)
                ev_odds = {}
                for src in [1, 2, 3, 4]:
                    odds_data = browser_fetch(page, f"{BASE}/event/{eid}/odds/{src}/all")
                    time.sleep(DELAY)
                    ev_odds = parse_event_odds(odds_data)
                    if ev_odds:
                        print(f"  [ODDS] evento {eid} source={src} ({len(ev_odds)} mercados)", flush=True)
                        break
                if not ev_odds:
                    print(f"  [ODDS] evento {eid}: sem odds (sources 1-4)", flush=True)
                scheduled.append({
                    "id":       eid,
                    "round":    candidate_rnd,
                    "homeTeam": ev["homeTeam"]["name"],
                    "awayTeam": ev["awayTeam"]["name"],
                    "date":     datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "",
                    "odds":     ev_odds,
                })
            # Desduplicar por (homeTeam, awayTeam) — mantém entrada com odds se existir
            seen = {}
            for g in scheduled:
                key_pair = (g["homeTeam"], g["awayTeam"])
                if key_pair not in seen or (g["odds"] and not seen[key_pair]["odds"]):
                    seen[key_pair] = g
            scheduled = list(seen.values())

            # Preservar árbitros inseridos manualmente no JSON anterior
            if os.path.exists(league['out_file']):
                try:
                    with open(league['out_file'], encoding="utf-8") as f:
                        prev = json.load(f)
                    prev_refs = {
                        (g["homeTeam"], g["awayTeam"]): g.get("referee")
                        for g in prev.get("scheduledGames", [])
                        if g.get("referee")
                    }
                    for g in scheduled:
                        key_pair = (g["homeTeam"], g["awayTeam"])
                        if key_pair in prev_refs and not g.get("referee"):
                            g["referee"] = prev_refs[key_pair]
                    if prev_refs:
                        print(f"  [REFS] {len(prev_refs)} arbitro(s) manual(is) preservado(s)", flush=True)
                except Exception:
                    pass

            print(f"Proxima rodada ({candidate_rnd}): {len(scheduled)} jogos agendados", flush=True)
            break

    # Rodadas especiais com slug (playoffs, finais de rebaixamento, etc.)
    # Ex: Ligue 1 usa round=29/slug=final para o barrage Nice x Saint-Etienne.
    # O endpoint /events/round/{n} NAO retorna esses jogos — exige /round/{n}/slug/{s}.
    special_rounds = [r for r in rounds_data.get("rounds", []) if r.get("slug")]
    for sr in special_rounds:
        sr_round = sr["round"]
        sr_slug  = sr["slug"]
        sr_name  = sr.get("name", sr_slug)
        sr_data  = browser_fetch(page, f"{BASE}/unique-tournament/{tid}/season/{sid}/events/round/{sr_round}/slug/{sr_slug}")
        time.sleep(DELAY)
        if not sr_data or "events" not in sr_data:
            continue
        events = sr_data["events"]
        # Jogos nao iniciados → adiciona a scheduled (evita duplicatas por id)
        scheduled_ids = {s["id"] for s in scheduled}
        sr_unplayed = [e for e in events if (e.get("status") or {}).get("type") == "notstarted"
                       and e["id"] not in scheduled_ids]
        if sr_unplayed:
            print(f"  Rodada especial '{sr_name}': {len(sr_unplayed)} jogo(s) agendado(s)", flush=True)
            for ev in sr_unplayed:
                eid = ev["id"]
                ts  = ev.get("startTimestamp", 0)
                ev_odds = {}
                for src in [1, 2, 3, 4]:
                    odds_data = browser_fetch(page, f"{BASE}/event/{eid}/odds/{src}/all")
                    time.sleep(DELAY)
                    ev_odds = parse_event_odds(odds_data)
                    if ev_odds:
                        print(f"  [ODDS] evento {eid} source={src} ({len(ev_odds)} mercados)", flush=True)
                        break
                if not ev_odds:
                    print(f"  [ODDS] evento {eid}: sem odds (sources 1-4)", flush=True)
                scheduled.append({
                    "id":       eid,
                    "round":    sr_round,
                    "homeTeam": ev["homeTeam"]["name"],
                    "awayTeam": ev["awayTeam"]["name"],
                    "date":     datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d") if ts else "",
                    "odds":     ev_odds,
                })
        # Jogos ja encerrados na rodada especial → coleta historico
        sr_finished = [e for e in events if (e.get("status") or {}).get("type") == "finished"
                       and e["id"] not in games_by_id]
        for ev in sr_finished:
            home = ev["homeTeam"]["name"]
            away = ev["awayTeam"]["name"]
            print(f"  Rodada especial '{sr_name}' — coletando: {home} x {away}", flush=True)
            game = collect_game(page, ev, sr_round)
            games_by_id[game["id"]] = game
            new_count += 1

    if new_count == 0 and backfilled == 0 and not scheduled and not force_full:
        print("\nNenhum dado novo. JSON nao atualizado.", flush=True)
        return

    all_games   = list(games_by_id.values())
    total_games = len(all_games)

    output = {
        "meta": {
            "leagueKey":    league_key,
            "leagueName":   league["name"],
            "tournamentId": tid,
            "seasonId":     sid,
            "lastRound":    max_round,
            "totalGames":   total_games,
            "updatedAt":    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "note": "Corners: granularidade 1T/2T apenas. Cartoes: minuto exato via incidents.",
        },
        "games":          all_games,
        "scheduledGames": scheduled,
    }

    with open(league['out_file'], "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nOK: {total_games} jogos salvos em {league['out_file']}", flush=True)

    inject_into_html(league_key, output)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    force_full    = "--full" in sys.argv
    inject_only   = "--inject" in sys.argv
    league_keys   = []
    max_round_arg = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg in ("--full", "--inject"):
            pass
        elif arg == "--liga":
            if i + 1 < len(args):
                league_keys = [args[i + 1]]
                i += 1
        elif arg.startswith("--liga="):
            league_keys = [arg.split("=", 1)[1]]
        elif arg.isdigit():
            max_round_arg = int(arg)
        i += 1

    if not league_keys:
        league_keys = ["brasileirao"]  # default

    # Modo --inject: apenas re-injeta o JSON existente no HTML, sem raspar
    if inject_only:
        if "all" in league_keys:
            league_keys = list(LEAGUES.keys())
        for key in league_keys:
            if key not in LEAGUES:
                print(f"Liga desconhecida: {key}")
                continue
            out_file = LEAGUES[key]["out_file"]
            if not os.path.exists(out_file):
                print(f"JSON nao encontrado: {out_file}")
                continue
            with open(out_file, encoding="utf-8") as f:
                data = json.load(f)
            inject_into_html(key, data)
        return

    if "all" in league_keys:
        league_keys = list(LEAGUES.keys())

    # Valida ligas
    valid = [k for k in league_keys if k in LEAGUES]
    invalid = [k for k in league_keys if k not in LEAGUES]
    if invalid:
        print(f"Liga(s) desconhecida(s): {invalid}")
        print(f"Opcoes validas: {list(LEAGUES.keys())}")
    if not valid:
        return

    print("=" * 56, flush=True)
    print("  Football Analytics -- Scraper Sofascore", flush=True)
    print(f"  Ligas: {', '.join(valid)}", flush=True)
    print("=" * 56, flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx     = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            viewport={"width": 1280, "height": 800},
        )
        page = ctx.new_page()

        # Aquece o contexto com a pagina inicial do Sofascore
        print("Abrindo Sofascore...", flush=True)
        try:
            page.goto("https://www.sofascore.com", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  [WARN] Home do Sofascore nao carregou: {e}", flush=True)
        time.sleep(3)
        print(f"  URL atual: {page.url}", flush=True)

        # Teste rapido de acesso a API — confirma que a sessao esta funcional
        _test = browser_fetch(page, f"{BASE}/sport/0/scheduled-events/2026-05-08")
        if _test is None:
            print("  [WARN] API inacessivel apos home. Aguardando 15s e retentando...", flush=True)
            time.sleep(15)
            _test = browser_fetch(page, f"{BASE}/sport/0/scheduled-events/2026-05-08")
            if _test is None:
                print("  [ERRO] API Sofascore bloqueada neste ambiente. Verifique IP/bot-detection.", flush=True)
            else:
                print("  API acessivel apos espera.", flush=True)
        else:
            print(f"  API OK — {len(_test.get('events', []))} eventos hoje.", flush=True)

        for key in valid:
            # A navegacao para cada liga e feita dentro de run_league
            run_league(page, key, force_full=force_full, max_round_arg=max_round_arg)

        browser.close()

    print("\nConcluido.", flush=True)


if __name__ == "__main__":
    main()
