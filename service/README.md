# service

Resident FastAPI for Personal AI Newspaper (click tracking + future Astro UI API).
Runs independently of the `daily_news.py` batch; deployed as a container image
pulled from GHCR.

## Local development

```bash
cd service
uv sync
uv run uvicorn app.main:app --reload
curl http://localhost:8000/health
```

## Docker

```bash
docker build -t personal-daily-news:local -f service/Dockerfile .
docker run --rm -p 8000:8000 personal-daily-news:local
```
