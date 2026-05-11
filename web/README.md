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

## What's NOT here yet

This is the scaffold. The following land in later PRs:

- Data flow: Python pipeline → `web/src/content/editions/*.json` → Astro Content Collection.
- Edition page (`/edition/[issue_no]`) — issue #41.
- Archive index — issue #42.
- Landing page — issue #58.
- Cloudflare Pages deploy hook — issue #59.

The current `src/pages/index.astro` is a placeholder that proves the scaffold runs.
