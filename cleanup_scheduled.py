"""
Remove jogos passados de scheduledGames em todos os JSONs das ligas.
Roda toda terça às 20h BRT (23h UTC) via GitHub Actions.
Mantém apenas jogos com data >= hoje.
"""

import json
import os
from datetime import date

TODAY = date.today().isoformat()

LEAGUE_FILES = [
    'brasileirao_2026_data.json',
    'premier_2026_data.json',
    'laliga_2026_data.json',
    'bundesliga_2026_data.json',
    'ligue1_2026_data.json',
    'saudi_2026_data.json',
    'argentina_2026_data.json',
    'seriea_2026_data.json',
]

total_removed = 0

for fname in LEAGUE_FILES:
    if not os.path.exists(fname):
        continue
    try:
        with open(fname, encoding='utf-8') as f:
            data = json.load(f)

        scheduled = data.get('scheduledGames', [])
        before = len(scheduled)
        data['scheduledGames'] = [g for g in scheduled if g.get('date', '9999') >= TODAY]
        removed = before - len(data['scheduledGames'])

        if removed > 0:
            with open(fname, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f'  [{fname}] {removed} jogo(s) passado(s) removido(s)', flush=True)
            total_removed += removed
        else:
            print(f'  [{fname}] nada a remover', flush=True)

    except Exception as e:
        print(f'  [{fname}] erro: {e}', flush=True)

print(f'\nTotal: {total_removed} jogo(s) removido(s) de scheduledGames.', flush=True)
