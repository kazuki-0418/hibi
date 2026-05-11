---
name: hibi-design
description: Use this skill to generate well-branded interfaces and assets for Hibi (日々), a daily Japanese-language AI newspaper. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping. The brand is Japanese minimalist — monochrome, generous whitespace, type-driven, hairline rules instead of cards. No emoji. No gradients. No saturated color.
user-invocable: true
---

Read the README.md file within this skill, and explore the other available files.

If creating visual artifacts (slides, mocks, throwaway prototypes, etc), copy assets out and create static HTML files for the user to view. If working on production code, you can copy assets and read the rules here to become an expert in designing with this brand.

If the user invokes this skill without any other guidance, ask them what they want to build or design, ask some questions, and act as an expert designer who outputs HTML artifacts or production code depending on the need.

## Quick orientation

- **`README.md`** — voice, palette, type, spacing, motion, iconography rules. Read this first.
- **`colors_and_type.css`** — drop-in tokens (`--bg-primary`, `--text-primary`, `--font-jp`, `--space-N`, etc).
- **`assets/`** — wordmark, horizontal lockup, seal. Use these; do not redraw.
- **`preview/`** — small specimen cards. Useful as visual reference for what "good Hibi" looks like.
- **`ui_kits/email/`** — the newsletter, the actual product. Most work happens here.
- **`ui_kits/web/`** — archive home, edition page, subscribe page.

## Non-negotiables

- Grayscale only. Seven values, no hue. **No** gradients, neon, or saturated primaries.
- Type carries the whole identity. Noto Sans JP (body + headings), Noto Serif JP (display), Inter (Latin labels).
- Hairline rules (`1px solid #E8E6E1`) frame content. **Cards have no background and no border-radius.**
- No drop shadows. Depth = value contrast + whitespace.
- No emoji. Categories use numeric prefixes (`01 AI`), never colored pills.
- Japanese body text uses 句点。読点、. Mixed JP/EN uses a thin space around the English token.
- Voice is observational and quiet. No exclamation marks, no clickbait, no marketing CTAs.
