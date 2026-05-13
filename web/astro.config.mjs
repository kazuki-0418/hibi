import { defineConfig } from "astro/config";

// Hibi web archive.
// - Build target: web/dist/ (deployed via Cloudflare Pages to hibi-news.com).
// - Static output only; no SSR. Data is read at build time from
//   web/src/content/editions/*.json which the Python pipeline dumps.
// - Design-system tokens come from design-system/colors_and_type.css
//   (SSoT). Astro must not redeclare colors / typography locally.
export default defineConfig({
  site: "https://hibi-news.com",
  output: "static",
});
