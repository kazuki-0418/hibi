# Hibi (日々)

A personal AI newspaper. A cron at 13:17 UTC fetches curated YouTube channels
and RSS feeds, has Claude summarize the best five stories in Japanese, and
emails the digest to a single recipient (kazuki). No public web archive, no
click tracking, no multi-tenant signup — see `docs/legal-posture.md` for why.

## Layout overview

- `daily_news.py` — pipeline entry point (fetch → rank → summarize → save → mail).
- `manager/` — code-driven state machine that orchestrates the project's
  slash-command sub-agents. Has its own rules in `.claude/rules/manager-agent.md`.
- `design-system/` — brand guide + tokens used by the email template
  (`mailer.py`). See "Design system" below.

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

## Legal posture (read before proposing scope expansion)

Hibi runs as a **single-user private newspaper** (kazuki only) because of the
Perplexity copyright suit pending in Tokyo District Court (filed 2025-08).
Commercial use, third-party signup, multi-tenant delivery, OSS distribution,
and aggressive fetcher changes (robots.txt handling, paywall, scope) are
**all on hold** until that case resolves or a license path opens. Resume
signals and the policy live in `docs/legal-posture.md` — read that file
before suggesting auth, multi-tenant, distribution, or scraping-policy work.

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
- For the email template, inline the relevant tokens into `mailer.py`.
- **Do not redefine** tokens (color hex, font family, spacing scale) in
  other files. If a token needs to change, edit `colors_and_type.css` and
  let every surface inherit.
- Do not introduce new tokens without first putting them in this file.

Non-negotiable visual rules (Japanese minimalist) live in
`design-system/README.md` — read it before touching the email template:

- Grayscale (7 values) only — no saturated color, no gradients, no emoji.
- Hairline rules (`1px solid #E8E6E1`) instead of cards / shadows.
- Noto Sans JP for body/headings, Noto Serif JP for display, Inter for
  Latin labels.
- Voice & tone: third-person, observational; no exclamation marks,
  no marketing CTAs, no second-person address.

Detailed guidance, UI kits, and assets are inside `design-system/`; that
directory is the SSoT, and `/hibi-design` exposes it to Claude Code.
