# Football Analytics Dashboard

Dashboard de análise estatística de futebol com modelo probabilístico Poisson.

## Stack
- **Frontend**: HTML/CSS/JS (single-file, sem framework)
- **Dados**: Sofascore via scraper Python + Playwright
- **Storage**: Firebase/Firestore (histórico de apostas)
- **Hospedagem**: Vercel
- **Automação**: GitHub Actions (scraper diário às 3h BRT)

## Ligas suportadas
Brasileirão, Premier League, La Liga, Bundesliga, Ligue 1, Serie A, Liga Profesional Argentina, Saudi Pro League

## Setup local
```bash
pip install playwright
playwright install chromium
python scraper.py --liga brasileirao
```

## Deploy
Conectar o repositório ao Vercel — deploy automático a cada push.
