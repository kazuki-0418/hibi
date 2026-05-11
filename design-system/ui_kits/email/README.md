# Email UI Kit — Hibi Daily

The newsletter is the **product**. Most days the reader only sees this one artifact.

## Layout

- 680px max-width — sweet spot for Gmail/Apple Mail desktop and acceptable on mobile.
- White paper background. No card chrome around the email itself; rules above/below the masthead frame it.
- Five stories. Numbered 01–05. The most important story is index 01, not "featured" — order is the editorial signal.

## Structure

```
Masthead     —  日々 wordmark · datestamp · issue no.
Standfirst   —  one-line editorial framing ("今朝の5本")
Stories      —  five article cards, each numbered, rule-divided
Sources      —  small-caps list of where the stories came from
Colophon     —  Hibi seal, generation timestamp, unsubscribe link
```

## Files

- `index.html` — the rendered email, exactly as it goes out.
- `MailFrame.jsx` — the outer wrapper.
- `Masthead.jsx` — wordmark + date + issue.
- `Standfirst.jsx` — single-line editorial intro.
- `Story.jsx` — one article block.
- `Sources.jsx` — source list.
- `Colophon.jsx` — footer with seal and meta.

## Notes for production

- This kit ships with web fonts via Google Fonts `@import`. Many email clients strip `<link>` and `@import`. **For production**, render the email server-side and inline:
  - Web fonts → fall back to `system-ui` + `-apple-system` (Helvetica → Yu Gothic → Hiragino Kaku Gothic ProN). The system is intentionally robust to this.
  - All styles → inline via `<style>` block + (ideally) per-element inlining (premailer / juice).
- Image assets (seal.svg) won't render in some clients without a hosted URL. The kit references local paths; swap to CDN before send.
- All hairlines, type weights, and spacing translate directly to email-safe CSS.
