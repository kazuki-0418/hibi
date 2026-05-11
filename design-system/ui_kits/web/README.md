# Web UI Kit — Hibi Archive

A read-on-the-web companion to the daily email. Three surfaces:

1. **Home / Archive** — chronological list of editions, designed like a quiet broadsheet contents page.
2. **Edition** — a single morning's email, reformatted for a wider browser column.
3. **Subscribe** — a single-page sign-up.

## Layout

- 1280px container, 720px reading column for body content.
- Section padding 128px on desktop, 64px on mobile.
- The masthead is full-bleed and rule-framed; everything else respects the container.

## Files

- `index.html` — the archive home, showing recent editions.
- `edition.html` — an individual edition page (mirrors the email).
- `subscribe.html` — the sign-up.
- `*.jsx` — component sources (server-rendered or static).

## Notes

- No JS framework required; the kit ships static HTML so the archive can be hosted on GitHub Pages.
- The same tokens (`colors_and_type.css`) drive both web and email.
