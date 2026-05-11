// Copy design-system/ from the repo root into web/public/design-system/
// so Astro can serve colors_and_type.css and ui_kits/web/web.css at
// stable URLs (referenced from src/layouts/Layout.astro).
//
// Runs as `predev` and `prebuild` from web/package.json. Cross-platform
// (Node fs API instead of `cp -r`).
//
// The destination is gitignored (web/.gitignore: public/design-system/)
// so we don't double-track files. The source design-system/ stays the
// single source of truth.

import { cp, rm } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, "..", "..", "design-system");
const dst = resolve(here, "..", "public", "design-system");

await rm(dst, { recursive: true, force: true });
await cp(src, dst, { recursive: true });
console.log(`synced ${src} → ${dst}`);
