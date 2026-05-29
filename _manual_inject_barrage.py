"""
Injecao manual: jogos Saint-Etienne v Nice (barrage Ligue 1, round 29 final).
Coletado direto da API Sofascore (via browser do usuario).

Move os 2 jogos de scheduledGames -> games com resultados reais,
para que as picks ja geradas em betMeta sejam validadas automaticamente
pelo assertividade_sync.py.
"""
import json
from datetime import datetime, timezone

GAMES_TO_ADD = [
    {
        "id": 16198895,
        "round": 29,
        "date": "2026-05-26",
        "homeTeam": "Saint-Étienne",
        "awayTeam": "Nice",
        "homeId": 0,
        "awayId": 0,
        "score": {"home": 0, "away": 0},
        "stats": {
            "all": {
                "shots":         {"home": 7,  "away": 4},
                "shotsOnTarget": {"home": 0,  "away": 0},
                "corners":       {"home": 6,  "away": 6},
                "fouls":         {"home": 10, "away": 7},
                "yellowCards":   {"home": 1,  "away": 0},
                "redCards":      {"home": 0,  "away": 0},
            }
        },
        "cards": [{"type": "yellow", "minute": 50, "isHome": True, "period": "2t"}],
        "referee": None,
    },
    {
        "id": 16198901,
        "round": 29,
        "date": "2026-05-29",
        "homeTeam": "Nice",
        "awayTeam": "Saint-Étienne",
        "homeId": 0,
        "awayId": 0,
        "score": {"home": 4, "away": 1},
        "stats": {
            "all": {
                "shots":         {"home": 20, "away": 13},
                "shotsOnTarget": {"home": 10, "away": 2},
                "corners":       {"home": 6,  "away": 4},
                "fouls":         {"home": 10, "away": 5},
                "yellowCards":   {"home": 2,  "away": 0},
                "redCards":      {"home": 0,  "away": 0},
            }
        },
        "cards": [
            {"type": "yellow", "minute": 30, "isHome": True, "period": "1t"},
            {"type": "yellow", "minute": 70, "isHome": True, "period": "2t"},
        ],
        "referee": None,
    },
]


def main():
    with open("ligue1_data.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    games_by_id = {g["id"]: g for g in data.get("games", [])}
    added = 0
    for g in GAMES_TO_ADD:
        if g["id"] not in games_by_id:
            games_by_id[g["id"]] = g
            added += 1
            print(f"+ Adicionado: {g['homeTeam']} {g['score']['home']}x{g['score']['away']} {g['awayTeam']} ({g['date']})")
        else:
            print(f"= Ja existe: {g['homeTeam']} x {g['awayTeam']} ({g['date']})")

    # Remove esses jogos do scheduledGames
    new_ids = {g["id"] for g in GAMES_TO_ADD}
    scheduled = [s for s in data.get("scheduledGames", []) if s["id"] not in new_ids]
    removed_sched = len(data.get("scheduledGames", [])) - len(scheduled)
    print(f"\nRemovidos do scheduledGames: {removed_sched}")

    data["games"] = list(games_by_id.values())
    data["scheduledGames"] = scheduled
    data["meta"]["totalGames"] = len(data["games"])
    data["meta"]["updatedAt"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data["meta"]["note"] = data["meta"].get("note", "") + " | Injecao manual 29/05: barrage round 29."

    with open("ligue1_data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\nOK: ligue1_data.json atualizado. Total games: {len(data['games'])}, scheduled: {len(scheduled)}")
    print(f"Adicionados: {added}")


if __name__ == "__main__":
    main()
