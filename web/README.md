# Hibi web

Static archive site for the Hibi daily newspaper. Built with Astro, deployed to Cloudflare Pages at `hibi-news.com`.

See `architecture/skills/hibi-domain.md` → "Web Frontend Constraints" for the canonical shape rules (build-time data, SSoT for tokens, no runtime DB access from Astro).

## Local development

Requires Node `>=20.18.0` (see `.nvmrc`).

```sh
cd web
nvm use      # or: nvm install
npm install
npm run dev  # opens http://localhost:4321
```

## Build

```sh
npm run build   # produces web/dist/
npm run preview # serves dist/ locally to sanity-check the build output
```

The build output (`dist/`) is what Cloudflare Pages serves. Don't commit `dist/`.

## Type check

```sh
npm run check   # @astrojs/check — strict TypeScript
```

## Deploy (Cloudflare Pages)

Build target: `hibi-news.com`. Cloudflare Pages is the deploy host (decided in epic #39 body). Builds are triggered automatically on push to `main` via the GitHub integration.

### One-time setup (Cloudflare dashboard)

1. **Create project**: dash.cloudflare.com → Workers & Pages → Create application → Pages → Connect to Git → select this repo.
2. **Build configuration**:
   - Framework preset: **Astro**
   - **Root directory**: `web`
   - **Build command**: `npm install && npm run build`
   - **Build output directory**: `dist`
   - **Production branch**: `main`
3. **Environment variables** (Production):
   - `NODE_VERSION`: `20.18.0` (mirrors `web/.nvmrc`)
   - **No `DATABASE_URL`** — the build does NOT touch the DB. Edition JSON files live in `web/src/content/editions/` and are committed via `scripts/dump_editions_to_json.py --apply`.
4. **Custom domain**: Pages project → Custom domains → Add `hibi-news.com`. Cloudflare auto-issues a TLS cert; DNS is configured via Cloudflare DNS if the domain is on Cloudflare (or via CNAME record otherwise).

After step 4, every merge to `main` deploys automatically.

### Build hooks vs. data refreshes

The build only sees what's committed to the repo. To publish a new edition:

1. `daily_news.py` (cron) writes a new `editions` row + articles to Neon.
2. Run `python scripts/dump_editions_to_json.py --apply` locally (or via a future automated commit step).
3. Commit the new `web/src/content/editions/NNNN.json` file.
4. Push → Cloudflare Pages rebuilds → site updates.

Automating step 3 (cron commits the JSON itself) is a future extension; it's currently a manual step.

### Cache strategy

`web/public/_headers` ships cache hints to Cloudflare:

- Hashed assets (`*.css`, `*.js`, fonts, SVG): `Cache-Control: max-age=31536000, immutable`.
- HTML (`/`, `/edition/*/`): `Cache-Control: max-age=300` — updates propagate within 5 minutes.

Baseline security headers (`Referrer-Policy`, `X-Content-Type-Options`, `Permissions-Policy`) are also set there.
