# Hibi 日々

> 日々の小さな知らせ。 A daily AI newspaper, delivered by email.

Hibi is a personal AI newspaper. Every morning it scans a curated list of tech YouTube channels and RSS feeds, has Claude summarize the best five stories in Japanese, and emails the digest to a single recipient.

The product is bilingual JP/EN, technical, and intimate — built for one reader, sent at 6 AM. The visual system is **Japanese minimalist**: monochrome, generous whitespace, hairline rules, no decoration that doesn't earn its keep. Think *MUJI catalog*, *Kinfolk*, *Brutus Casa* — printed-page calm, not SaaS dashboard.

---

## Sources

- Codebase: `github.com/kazuki-0418/hibi` — Python pipeline (fetch → summarize → email), GitHub Actions cron at UTC 13:00.
- The repo ships one template (`templates/email.html`) using a purple-gradient look. **This design system replaces that direction** with the monochrome, type-driven aesthetic defined in the design tokens you provided.
- No existing logo, brand guide, or marketing surface — this system establishes those.

## Surfaces

| # | Surface       | Folder                  | Status                            |
|---|---------------|-------------------------|-----------------------------------|
| 1 | Email digest  | `ui_kits/email/`        | Primary product output            |
| 2 | Web archive   | `ui_kits/web/`          | Read-on-the-web, edition archive  |

## Index

- `colors_and_type.css` — All tokens as CSS custom properties. Drop into any page.
- `preview/` — Specimen cards rendered in the Design System tab.
- `assets/` — Wordmark, seal, and visual marks.
- `ui_kits/email/` — Newsletter email template (the daily artifact).
- `ui_kits/web/` — Web edition + archive index.
- `SKILL.md` — Agent skill manifest.

---

## Content fundamentals

Hibi is **bilingual but JP-led**. Body copy is Japanese; English appears as eyebrow labels, numeric metadata, and source titles (which often arrive in English from the feed).

**Voice**

- Quiet, observational, declarative. Hibi reports — it does not sell.
- Third-person omniscient. The newspaper has no first-person voice. Avoid「私」「僕」.
- Address the reader implicitly. Never「あなた」. Never「読者の皆様」.
- No exclamation marks. No emoji. No emoticons.
- Praise is restrained:「興味深い」over「すごい」; 「注目」over「最高」.

**Casing & punctuation**

- English headings, labels, and section eyebrows: **UPPERCASE with wide tracking** (`letter-spacing: 0.08em`).
- Japanese body: 句点「。」読点「、」 — never the English period inside Japanese sentences.
- Mixed JP/EN inline: thin space around the English token, e.g. 「Claude を使って要約する」.
- Numbers, dates, percentages: half-width, tabular figures. e.g. `2026.05.10`, `5 articles`.
- Em-dash「—」used sparingly for clauses; never「ー」(katakana prolong) for the same purpose.

**Lengths**

- Email subject: ≤ 28 全角 chars. Always begins with the date: `2026.05.10 — 今朝の5本`.
- Story title (from source): keep verbatim. Translate parenthetically only if the English is impenetrable.
- Story summary: **3 lines, ~120 全角 chars total.** Each line is one idea, ends in 「。」, no bullet points.
- Section labels: 1 word or 2-character pairs preferred. 「要点」「背景」「示唆」.

**Example summary block**

> **Anthropic、Claude 4.6 をリリース**
> Anthropic が Claude Sonnet 4.6 を公開した。長文要約とコード生成の精度が向上している。
> 既存 API キーで即時利用可能。料金体系は前世代と同じ。
> 開発者向けにバッチ処理 API も同時にベータ提供開始。

**What we don't do**

- No clickbait verbs:「驚愕の」「衝撃」「やばい」.
- No reaction copy: don't tell the reader what to feel.
- No marketing CTAs:「今すぐ」「お見逃しなく」.
- No emoji. The closest we get is a 「・」 middot separator.

---

## Visual foundations

### Palette

Grayscale only. Six values, no hue.

| Token              | Hex        | Role                                                  |
|--------------------|------------|-------------------------------------------------------|
| `--bg-primary`     | `#FFFFFF`  | Paper white. Default background.                      |
| `--bg-subtle`      | `#FAFAF7`  | Warm off-white. Section bands, email body.            |
| `--bg-sunken`      | `#F2F1EC`  | Card-on-card, pull quotes, code.                      |
| `--text-primary`   | `#1A1A1A`  | Near-black. Headings, body, the only accent.          |
| `--text-secondary` | `#5C5A57`  | Warm gray. Lead paragraphs, secondary copy.           |
| `--text-muted`     | `#9B9894`  | Eyebrows, dates, captions, meta.                      |
| `--border`         | `#E8E6E1`  | Hairline rules — the primary structural element.      |

**Forbidden:** blue/purple gradients, neon, saturated primaries, colorful category pills. If you need to differentiate categories, use a numeric prefix or a wide-tracked English label — not color.

### Typography

Three families. Two are Noto siblings (one sans, one serif) for full JP coverage; Inter handles Latin metadata.

- **Noto Sans JP** — body, headings. 400 / 500 / 700.
- **Noto Serif JP** — reserved for *display* moments (issue numbers, pull quotes, the wordmark).
- **Inter** — Latin labels, datestamps, source URLs. 400 / 500 / 700.

Heading-to-body ratio targets **3:1 to 4:1**. A 72px h1 sits above 18px body. Body line-height is generous (1.7) to support 漢字 density. Headings tighten to 1.15.

### Spacing

Powers-of-ratio scale: 4 / 8 / 16 / 24 / 32 / 48 / 64 / 96 / 128 / 160 px. Sections breathe at 128px desktop, 64px mobile. Reading column caps at 720px; full grid at 1280px.

### Backgrounds

Flat. No gradients, no images-as-background, no patterns, no grain. If the design feels empty, **add space, not texture**. The only allowed "background" treatment is a band of `--bg-subtle` to demarcate sections.

### Borders, rules, frames

The hairline rule **is** the visual system. Use `1px solid var(--border)` to:

- Separate stories in the digest.
- Frame the email body (top and bottom only — sides stay open).
- Underline links.
- Cap section headers (rule above, eyebrow below).

Corners are square. The only allowed radii are `2px` (occasional softening on input fields) and `999px` (date capsule on the masthead — and only there).

### Shadows & depth

**None.** Depth is achieved through value contrast (`#1A1A1A` text on `#FFFFFF`) and whitespace. If a card needs to feel elevated, add space around it, not shadow under it.

### Hover & press

- Links: opacity 1 → 0.55, 120ms ease-out. Underline stays.
- Buttons (rare — Hibi mostly has links): background `--text-primary` → opacity 0.85.
- Press: no scale, no shrink. Just a 60ms hold at opacity 0.7.
- Focus: 2px outline in `--text-primary`, 2px offset. Never blue.

### Motion

Sparing. Page enters fade up 12px over 480ms ease-out. Hover transitions 120ms. No bounces, no springs, no parallax, no scroll-jacking. A printed page that happens to live on the web.

### Imagery

Hibi is type-first. When images appear (rare — only on the web archive's individual editions), they are:

- Monochrome or very desaturated (filter: grayscale(100%) acceptable).
- Full-bleed within their column, never inset with a border.
- Captioned in muted small-caps English.

### Transparency & blur

Not used. No frosted glass, no overlays.

### Layout rules

- 12-column grid, 24px gutter, 1280px max width.
- The masthead is full-bleed; everything else respects the container.
- Reading text never exceeds 720px wide — even on desktop, run wide whitespace beside the column.
- Vertical rhythm: section headings always have a 1px rule above and 32px space below.

### Card pattern

A "card" in Hibi is just a region of text with a hairline above and below. No background fill. No border on left/right. No radius. The whitespace does the framing.

---

## Iconography

Hibi avoids decorative iconography by design. The visual language is type, rules, and whitespace.

When a glyph is genuinely needed:

- **Unicode marks preferred:** `・`(middot) `—`(em-dash) `→`(arrow) `↗`(external link) `§`(section).
- **No emoji.** Ever. Including the existing template's 📅 📰.
- **Numeric prefixes** stand in for category icons. `01 AI` `02 FE` reads better than colored pills.
- **The seal** (see `assets/seal.svg`) is the only ornamental mark — a 24×24 stamp containing the issue number, used once per email in the footer.

No icon font is included. If a future surface requires UI icons (a web app form, for instance), use [Lucide](https://lucide.dev) at `1.5px` stroke, `--text-secondary` color, `20px` default size — its quiet geometric line aligns with the system. This is a deferred decision; document the substitution if you use it.

---

## Caveats & substitutions

- **Fonts** are loaded from Google Fonts CDN (Noto Sans JP, Noto Serif JP, Inter). If you have brand-licensed alternates (e.g. *AXIS Font*, *Tsukushi A Round Gothic*) drop them into `fonts/` and swap `--font-jp`.
- **No logo existed**, so this system establishes a typographic wordmark (見ろ `assets/wordmark.svg`) using Noto Serif JP at 96px. Treat it as the first proposal, not a final mark.
- **The existing email template** (`hibi/templates/email.html`) uses a purple gradient and colored category pills. This system is a **deliberate redesign**, not a continuation. Migrate at your discretion.
