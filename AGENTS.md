# AGENTS.md

Cloud-agent operating notes for the Hibi (日々) monorepo. See `CLAUDE.md` for product context and coding rules.

## Cursor Cloud specific instructions

### Runtime versions

- **Python 3.12** for the daily pipeline (`requirements.txt`) and manager tests.
- **`uv`** for the FastAPI service under `service/` (`service/pyproject.toml`, `service/uv.lock`).
- **Node ≥ 20.18.0** for the Astro site (`web/.nvmrc` pins `20.18.0`).

### One-time VM prerequisites

Ubuntu images may ship without `python3.12-venv`. If `python3 -m venv .venv` fails, install it once:

```bash
sudo apt-get install -y python3.12-venv
```

Install `uv` if it is not on `PATH` (the Astral installer may fail in some networks; `pip install uv` works):

```bash
pip install uv
```

### Dependency refresh (automatic)

The VM update script recreates/refreshes:

- Root venv: `pip install -r requirements.txt pytest`
- Service env: `cd service && uv sync`
- Web deps: `cd web && npm install`

### Verify / lint / test

| Area | Command | Notes |
|------|---------|-------|
| Pipeline unit tests | `source .venv/bin/activate && pytest tests/ -q` | **Scope `tests/` only** — bare `pytest` also collects `scripts/test_neon_connection.py`, which exits if `DATABASE_URL` is unset. |
| Service unit tests | `cd service && uv run pytest -q` | Mocks DB via `service/tests/conftest.py`; no Neon needed. |
| Web typecheck | `cd web && npm run check` | `@astrojs/check` |
| Web build | `cd web && npm run build` | Static output in `web/dist/` |

There is no repo-wide Python linter (ruff/mypy). Web linting is `npm run check`.

`manager/tests/` has some failing runner tests on current `main` (6 failures observed during env setup); pipeline and service suites are the primary CI gates for product code.

### Run locally (no secrets)

**Web archive (recommended hello-world):**

```bash
cd web && npm run dev -- --host 0.0.0.0 --port 4321
```

Uses committed JSON in `web/src/content/editions/` — no database or API keys.

**FastAPI click API:**

```bash
cd service
export CLICK_SIGNING_SECRET=dev-secret-0123456789abcdef
export DATABASE_URL=postgresql://test/test
export PUBLIC_BASE_URL=http://localhost:8000
export IP_SALT=dev-ip-salt-0123456789
export APP_ENV=development
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

`/health` returns `{"status":"ok"}` even with a dummy `DATABASE_URL` (pool warnings are expected). `/docs` is available when `APP_ENV=development`.

Use **tmux** for long-running dev servers in Cloud Agent VMs.

### Full pipeline / E2E (secrets required)

`daily_news.py` needs Neon (`DATABASE_URL`), Anthropic, YouTube, and Gmail OAuth vars from `.env.example`. Do not run against production Neon without explicit approval.

### Gotchas

- Root `.venv` and `service/.venv` are separate; activate the right one per task.
- `pytest` is not listed in `requirements.txt` but is required for local/CI-style verification (installed by the update script).
- `docker-compose.yml` is homelab/prod-oriented (GHCR image + Cloudflare tunnel), not a local dev stack.
