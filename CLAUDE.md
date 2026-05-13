# Hibi (日々)

A personal AI newspaper. A cron at 13:17 UTC fetches curated YouTube channels
and RSS feeds, has Claude summarize the best five stories in Japanese, and
emails the digest to a single recipient. The same articles are surfaced as
an archive on `hibi-news.com`.

## Layout overview

- `daily_news.py` — pipeline entry point (fetch → rank → summarize → save → mail).
- `service/` — FastAPI click-tracking service, deployed to homelab via
  GHCR + self-hosted runner + nginx + Cloudflare Tunnel.
- `manager/` — code-driven state machine that orchestrates the project's
  slash-command sub-agents. Has its own rules in `.claude/rules/manager-agent.md`.
- `design-system/` — brand guide + tokens + UI kits (see "Design system" below).
- `web/` — Astro site for the public archive on hibi-news.com.

## Agent rules

Role-specific guardrails live next door — read the one that matches the work:

- `.claude/rules/dev-agent.md` — implementation tasks (Python, migrations, workflows).
- `.claude/rules/test-agent.md` — tests under `tests/**` and `conftest.py`.
- `.claude/rules/spec-agent.md` — requirements / planning before non-trivial code.
- `.claude/rules/manager-agent.md` — anything inside `manager/`.

Project-wide non-negotiables (also re-stated in each file):

- Type hints required; no `Any` / `# type: ignore` escape hatches.
- psycopg 3.x only — no psycopg2 / SQLAlchemy / Alembic.
- No async or concurrency in the daily pipeline (single epic = single process).
- Migrations are additive; never edit an existing migration file.
- Secrets stay in `.env` (or homelab `/opt/ops/env/hibi/api.env`); never in code or commit messages.

## Design system — single source of truth

`design-system/` is the only place that owns brand decisions. The skill
`/hibi-design` (symlinked from `.claude/skills/hibi-design/`) loads the same
files Claude sees here.

**Tokens** (colors, spacing, fonts, radii, line-heights) come from exactly
one file:

```text
design-system/colors_and_type.css
```

When implementing UI:

- Reference these tokens via the CSS custom properties they define
  (`--bg-primary`, `--text-primary`, `--font-jp`, `--space-N`, ...).
- For email, inline the relevant tokens into the template; for web, link
  the file directly.
- **Do not redefine** tokens (color hex, font family, spacing scale) in
  other files. If a token needs to change, edit `colors_and_type.css` and
  let every surface inherit.
- Do not introduce new tokens without first putting them in this file.

Non-negotiable visual rules (Japanese minimalist) live in
`design-system/README.md` — read it before any work touching email
templates, web pages, or marketing surfaces:

- Grayscale (7 values) only — no saturated color, no gradients, no emoji.
- Hairline rules (`1px solid #E8E6E1`) instead of cards / shadows.
- Noto Sans JP for body/headings, Noto Serif JP for display, Inter for
  Latin labels.
- Voice & tone: third-person, observational; no exclamation marks,
  no marketing CTAs, no second-person address.

Detailed guidance, UI kits, and assets are inside `design-system/`; that
directory is the SSoT, and `/hibi-design` exposes it to Claude Code.

## Auto-deploy (FYI)

A push to `main` that touches `service/**` builds a SHA-pinned image
(`ghcr.io/kazuki-0418/hibi-api:sha-<sha>`), and the homelab self-hosted
runner rolls forward via `make deploy-hibi`. See `docs/deploy.md` for the
full flow and the rollback escape hatch.
