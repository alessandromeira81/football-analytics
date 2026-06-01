"""
Backfill historico de temporadas passadas para uma liga.

Uso:
  python backfill_historical.py --liga brasileirao --year 2024
  python backfill_historical.py --liga premier --year 2023

Append jogos da temporada especificada no JSON da liga (dedupe por ID).
Nao mexe em scheduledGames (so adiciona ao array 'games').
"""
import sys
import json
import os
import time
import argparse
from datetime import datetime, timezone
from playwright.sync_api import sync_playwright

# Importa do scraper principal para reusar parsing
from scraper import (
    LEAGUES, BASE, DELAY,
    browser_fetch, collect_game, navigate_and_discover_season,
)


def find_season_id_for_year(page, tid, target_year):
    """Busca o season_id para um ano especifico via /seasons endpoint.

    Aceita match exato no campo 'year' OU match parcial no 'name'
    (cobre formatos tipo '23/24' ou 'Premier League 2024/2025').
    """
    data = browser_fetch(page, f"{BASE}/unique-tournament/{tid}/seasons")
    if not data:
        return None, None

    target_str = str(target_year)
    candidates = []
    for s in data.get("seasons", []):
        year_field = s.get("year", "")
        name_field = s.get("name", "")

        # Match exato
        if year_field == target_str:
            return s["id"], name_field

        # Match em formato XX/YY (ex: "23/24" para 2023)
        if "/" in year_field:
            parts = year_field.split("/")
            # Normaliza para 4 digitos
            try:
                start = int(parts[0])
                if start < 100:
                    start = 2000 + start
                if start == target_year:
                    return s["id"], name_field
            except ValueError:
                pass

        # Fallback: ano aparece no nome
        if target_str in name_field:
            candidates.append((s["id"], name_field))

    # Se nao achou exato mas tem candidato pelo nome, pega o primeiro
    if candidates:
        return candidates[0]
    return None, None


def load_or_init(out_file, league_key, league, tid):
    """Carrega JSON existente ou inicia estrutura base."""
    if os.path.exists(out_file):
        with open(out_file, encoding="utf-8") as f:
            return json.load(f)
    return {
        "meta": {
            "leagueKey":    league_key,
            "leagueName":   league["name"],
            "tournamentId": tid,
            "totalGames":   0,
            "updatedAt":    "",
            "note":         "Inicializado via backfill_historical.py",
        },
        "games": [],
        "scheduledGames": [],
    }


def collect_round(page, tid, sid, rnd, games_by_id, sr_slug=None):
    """Coleta uma rodada (regular ou especial)."""
    if sr_slug:
        url = f"{BASE}/unique-tournament/{tid}/season/{sid}/events/round/{rnd}/slug/{sr_slug}"
    else:
        url = f"{BASE}/unique-tournament/{tid}/season/{sid}/events/round/{rnd}"
    ev_data = browser_fetch(page, url)
    time.sleep(DELAY)
    if not ev_data or "events" not in ev_data:
        return 0

    new_count = 0
    finished = [e for e in ev_data["events"]
                if (e.get("status") or {}).get("type") == "finished"]
    new_evs = [e for e in finished if e["id"] not in games_by_id]
    if not finished:
        return 0
    print(f"  R{rnd}{'/'+sr_slug if sr_slug else ''}: {len(finished)} jogos "
          f"({len(new_evs)} novos)", flush=True)
    for ev in new_evs:
        home = ev["homeTeam"]["name"]
        away = ev["awayTeam"]["name"]
        try:
            game = collect_game(page, ev, rnd)
            games_by_id[game["id"]] = game
            new_count += 1
            corners_h = (game["stats"].get("all") or {}).get("corners", {}).get("home", "?")
            corners_a = (game["stats"].get("all") or {}).get("corners", {}).get("away", "?")
            print(f"    + {home[:18]} x {away[:18]} | {corners_h}-{corners_a}c", flush=True)
        except Exception as e:
            print(f"    [ERR] {home} x {away}: {e}", flush=True)
    return new_count


def collect_paged(page, tid, sid, games_by_id):
    """Coleta liga sem rounds (MLS) via /events/last/{p}."""
    new_count = 0
    p = 0
    max_pages = 60
    while p < max_pages:
        ev_data = browser_fetch(page, f"{BASE}/unique-tournament/{tid}/season/{sid}/events/last/{p}")
        time.sleep(DELAY)
        if not ev_data or "events" not in ev_data:
            break
        finished = [e for e in ev_data["events"]
                    if (e.get("status") or {}).get("type") == "finished"]
        new_evs = [e for e in finished if e["id"] not in games_by_id]
        print(f"[Pag {p}] {len(finished)} jogos ({len(new_evs)} novos)", flush=True)
        for ev in new_evs:
            home = ev["homeTeam"]["name"]
            away = ev["awayTeam"]["name"]
            rnd = (ev.get("roundInfo") or {}).get("round", 0)
            try:
                game = collect_game(page, ev, rnd)
                games_by_id[game["id"]] = game
                new_count += 1
                print(f"  + {home[:18]} x {away[:18]}", flush=True)
            except Exception as e:
                print(f"  [ERR] {home} x {away}: {e}", flush=True)
        if not ev_data.get("hasNextPage"):
            break
        p += 1
    return new_count


def backfill(league_key, year):
    if league_key not in LEAGUES:
        print(f"Liga desconhecida: {league_key}")
        print(f"Opcoes: {list(LEAGUES.keys())}")
        sys.exit(1)

    league = LEAGUES[league_key]
    tid = league["tournament_id"]

    print(f"{'='*60}")
    print(f"  Backfill: {league['name']} | Ano: {year}")
    print(f"{'='*60}")

    try:
        from playwright_stealth import Stealth
        USE_STEALTH = True
    except ImportError:
        USE_STEALTH = False
        print("[WARN] playwright-stealth nao instalado", flush=True)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        ctx = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            viewport={"width": 1920, "height": 1080},
        )
        page = ctx.new_page()

        if USE_STEALTH:
            Stealth().apply_stealth_sync(page)
            print("Stealth aplicado.", flush=True)

        # Aquece sessao com navegacao humanizada (essencial pra passar bloqueio)
        print("Abrindo Sofascore (home)...", flush=True)
        try:
            page.goto("https://www.sofascore.com", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  [WARN] Home: {e}", flush=True)
        time.sleep(5)
        print("Navegando /football...", flush=True)
        try:
            page.goto("https://www.sofascore.com/football", wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"  [WARN] /football: {e}", flush=True)
        time.sleep(5)

        # Teste API com endpoint de seasons (sempre disponivel pra qualquer liga)
        _test = browser_fetch(page, f"{BASE}/unique-tournament/{tid}/seasons")
        if _test is None:
            print("[ERRO] API Sofascore bloqueada. Backfill cancelado.", flush=True)
            browser.close()
            sys.exit(2)
        print(f"API OK ({len(_test.get('seasons', []))} temporadas listadas)", flush=True)

        # Descobre season_id
        sid, season_name = find_season_id_for_year(page, tid, year)
        if sid is None:
            print(f"ERRO: nao encontrou season_id para {league_key} {year}", flush=True)
            print("Verifique se a temporada existe na Sofascore.", flush=True)
            browser.close()
            sys.exit(3)
        print(f"Season: '{season_name}' (id={sid})", flush=True)

        # Carrega arquivo existente
        out_file = league["out_file"]
        data = load_or_init(out_file, league_key, league, tid)
        games_by_id = {g["id"]: g for g in data.get("games", [])}
        before = len(games_by_id)
        print(f"Jogos ja no arquivo: {before}", flush=True)

        # Detecta modo (rounds vs paged)
        rounds_data = browser_fetch(page, f"{BASE}/unique-tournament/{tid}/season/{sid}/rounds")
        new_count = 0

        if rounds_data and rounds_data.get("rounds"):
            regular = [r["round"] for r in rounds_data["rounds"] if not r.get("slug")]
            special = [r for r in rounds_data["rounds"] if r.get("slug")]
            print(f"Modo rounds: {len(regular)} regulares + {len(special)} especiais", flush=True)

            for rnd in sorted(set(regular)):
                new_count += collect_round(page, tid, sid, rnd, games_by_id)

            for sr in special:
                new_count += collect_round(page, tid, sid, sr["round"], games_by_id, sr_slug=sr["slug"])
        else:
            print("Modo paginado (sem rounds — ex: MLS)", flush=True)
            new_count = collect_paged(page, tid, sid, games_by_id)

        browser.close()

    # Atualiza arquivo
    data["games"] = list(games_by_id.values())
    max_round = max((g.get("round", 0) for g in data["games"]), default=0)
    data["meta"]["totalGames"] = len(data["games"])
    data["meta"]["lastRound"] = max_round
    data["meta"]["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prev_note = data["meta"].get("note", "")
    backfill_tag = f"backfill_{year}={new_count}"
    if backfill_tag not in prev_note:
        data["meta"]["note"] = (prev_note + " | " + backfill_tag).lstrip(" |")

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n{'='*60}")
    print(f"OK: +{new_count} jogos coletados ({before} → {len(data['games'])} total)")
    print(f"Arquivo: {out_file}")
    print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--liga", required=True, help="Chave da liga (brasileirao, premier, ...)")
    parser.add_argument("--year", type=int, required=True, help="Ano da temporada (ex: 2024)")
    args = parser.parse_args()

    backfill(args.liga, args.year)


if __name__ == "__main__":
    main()
