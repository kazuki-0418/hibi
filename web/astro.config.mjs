import { defineConfig } from "astro/config";
import cloudflare from "@astrojs/cloudflare";

// Hibi web archive.
// - Deploy target: Cloudflare Pages Functions (Workers runtime) at hibi-news.com.
// - `output: "static"` is Astro 5's default and now covers what `hybrid` did:
//   pages are prerendered unless they opt out with `export const prerender = false`.
//   Public pages (/, /edition/*, /privacy, /unsubscribe ...) stay static and read
//   their data at build time from web/src/content/editions/*.json which the
//   Python pipeline dumps. Auth-adjacent routes (/api/auth/**, /account, /login)
//   set `prerender = false` so Better Auth can read/write the Neon
//   `user` / `session` / ... tables that migration 007 added.
// - DB driver in SSR routes must be `@neondatabase/serverless` (WebSocket).
//   `pg` (node:net) is not available on the Workers runtime.
// - Design-system tokens come from design-system/colors_and_type.css (SSoT).
//   Astro must not redeclare colors / typography locally.
export default defineConfig({
  site: "https://hibi-news.com",
  output: "static",
  adapter: cloudflare(),
});
