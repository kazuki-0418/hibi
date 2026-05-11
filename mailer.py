import html
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from string import Template

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "email.html")

FONT_JP = (
    "'Noto Sans JP',system-ui,-apple-system,"
    "'Yu Gothic','Hiragino Kaku Gothic ProN',sans-serif"
)
FONT_EN = "'Inter',system-ui,-apple-system,sans-serif"

STORY_WRAPPER = (
    "padding:28px 48px;border-bottom:1px solid #E8E6E1;"
)
STORY_WRAPPER_LAST = (
    "padding:28px 48px;"
)
NUM_STYLE = (
    f"font-family:{FONT_EN};font-variant-numeric:tabular-nums;"
    "font-weight:500;font-size:32px;color:#1A1A1A;line-height:1;"
    "letter-spacing:-0.02em;width:48px;vertical-align:top;padding-right:24px;"
)
META_STYLE = (
    f"font-family:{FONT_EN};font-size:10px;letter-spacing:0.25em;"
    "text-transform:uppercase;color:#9B9894;margin-bottom:10px;"
)
META_SEP_STYLE = "color:#E8E6E1;padding:0 8px;"
META_CAT_STYLE = "color:#1A1A1A;font-weight:500;"
H2_STYLE = (
    f"font-family:{FONT_JP};font-size:22px;font-weight:700;line-height:1.35;"
    "color:#1A1A1A;margin:0 0 12px;letter-spacing:-0.01em;"
)
P_STYLE = (
    f"font-family:{FONT_JP};font-size:15px;line-height:1.75;"
    "color:#5C5A57;margin:0 0 6px;"
)
SRC_STYLE = (
    f"margin-top:14px;font-family:{FONT_EN};font-size:11px;"
    "letter-spacing:0.15em;text-transform:uppercase;color:#9B9894;"
)
SRC_LINK_STYLE = (
    "color:#1A1A1A;border-bottom:1px solid #1A1A1A;"
    "padding-bottom:1px;text-decoration:none;"
)

SOURCE_ROW_STYLE = (
    f"font-family:{FONT_EN};font-size:12px;letter-spacing:0.05em;color:#1A1A1A;"
    "padding:6px 0;border-bottom:1px solid #E8E6E1;"
)
SOURCE_KIND_STYLE = (
    "color:#9B9894;font-size:10px;letter-spacing:0.2em;text-transform:uppercase;"
    "text-align:right;"
)


def _story_html(index: int, article: dict, is_last: bool) -> str:
    """Render a single Story row matching design-system/ui_kits/email.

    User-controlled strings (title, summary, learning, practical, category,
    source name, source type, url) are escaped before interpolation so a feed
    containing `&`, `<`, `>`, or a stray `"` can't corrupt the rendered Gmail
    body or break the anchor `href`. URLs go through `quote=True` so quotes
    inside an href are neutralized.
    """
    title = html.escape(article.get("title", ""))
    url = html.escape(article.get("url", "#"), quote=True)
    summary = html.escape(article.get("summary", ""))
    learning = html.escape(article.get("learning", ""))
    practical = html.escape(article.get("practical_application", ""))
    category = html.escape(article.get("category") or "News")
    source_name = html.escape(article.get("source") or article.get("source_name") or "")
    source_type = html.escape(article.get("source_type") or "")

    # Meta line: CATEGORY · SOURCE_TYPE (caps), no emoji, no pill backgrounds.
    meta_parts: list[str] = [f'<span style="{META_CAT_STYLE}">{category}</span>']
    if source_type:
        meta_parts.append(f'<span style="{META_SEP_STYLE}">·</span>')
        meta_parts.append(f"<span>{source_type}</span>")
    meta_html = "".join(meta_parts)

    body_parts: list[str] = []
    if summary:
        body_parts.append(f'<p style="{P_STYLE}">{summary}</p>')
    if learning:
        body_parts.append(f'<p style="{P_STYLE}">{learning}</p>')
    if practical:
        body_parts.append(f'<p style="{P_STYLE}">{practical}</p>')
    body_html = "".join(body_parts)

    src_label = source_name or "Source"
    src_html = (
        f'<div style="{SRC_STYLE}">'
        f'Source <a href="{url}" style="{SRC_LINK_STYLE}">{src_label}</a>'
        f"</div>"
    )

    wrapper = STORY_WRAPPER_LAST if is_last else STORY_WRAPPER
    return (
        f'<article style="{wrapper}">'
        '<table role="presentation" width="100%" cellpadding="0" '
        'cellspacing="0" border="0" style="border-collapse:collapse;">'
        "<tr>"
        f'<td style="{NUM_STYLE}">{index:02d}</td>'
        "<td>"
        f'<div style="{META_STYLE}">{meta_html}</div>'
        f'<h2 style="{H2_STYLE}">{title}</h2>'
        f"{body_html}"
        f"{src_html}"
        "</td>"
        "</tr>"
        "</table>"
        "</article>"
    )


def _sources_html(articles: list[dict]) -> str:
    """Render the Sources block as a 2-column table.

    Inline styles only; styles come from design-system tokens (no class refs).
    """
    seen: dict[str, str] = {}
    for a in articles:
        name = a.get("source") or a.get("source_name")
        if not name:
            continue
        if name not in seen:
            seen[name] = a.get("source_type") or ""
    if not seen:
        return ""

    items = [(html.escape(name), html.escape(kind)) for name, kind in seen.items()]
    rows: list[str] = []
    for i in range(0, len(items), 2):
        left_name, left_kind = items[i]
        right = items[i + 1] if i + 1 < len(items) else None
        left_cell = (
            f'<td style="{SOURCE_ROW_STYLE}">{left_name}'
            f'<span style="{SOURCE_KIND_STYLE};margin-left:12px;">{left_kind}</span>'
            "</td>"
        )
        if right is None:
            right_cell = (
                f'<td style="{SOURCE_ROW_STYLE};border-bottom:none;"></td>'
            )
        else:
            right_name, right_kind = right
            right_cell = (
                f'<td style="{SOURCE_ROW_STYLE};padding-left:24px;">{right_name}'
                f'<span style="{SOURCE_KIND_STYLE};margin-left:12px;">{right_kind}</span>'
                "</td>"
            )
        rows.append(f"<tr>{left_cell}{right_cell}</tr>")
    return "".join(rows)


def build_html(articles: list[dict], date: str) -> str:
    """Build the daily email HTML from enriched article dicts.

    Articles are rendered top-to-bottom with numeric prefix 01..N matching
    design-system/ui_kits/email. Importance scores no longer drive layout —
    Hibi's design-system removes group headings, pills, and stars.
    """
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        template = Template(f.read())

    article_blocks: list[str] = []
    total = len(articles)
    for idx, article in enumerate(articles, start=1):
        article_blocks.append(
            _story_html(idx, article, is_last=(idx == total))
        )
    articles_html = "".join(article_blocks)

    sources_html = _sources_html(articles)
    source_count = len({a.get("source") or a.get("source_name") for a in articles if a.get("source") or a.get("source_name")})

    return template.safe_substitute(
        date=date,
        article_count=len(articles),
        articles_html=articles_html,
        sources_html=sources_html,
        source_count=source_count,
    )


def send(
    subject: str,
    articles: list[dict],
    date: str,
    to: str,
    from_addr: str,
    password: str,
) -> None:
    html_body = build_html(articles, date)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(from_addr, password)
        server.sendmail(from_addr, to, msg.as_string())
