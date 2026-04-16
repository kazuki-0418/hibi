import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from string import Template

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "templates", "email.html")

CATEGORY_PILL = {
    "AI/LLM":    ("AI/LLM",    "pill-ai"),
    "Frontend":  ("Frontend",  "pill-fe"),
    "Startup":   ("Startup",   "pill-st"),
    "Career":    ("Career",    "pill-ca"),
    "Tech News": ("Tech News", "pill-tn"),
}

STARS = {3: "★★★", 2: "★★☆", 1: "★☆☆"}

GROUP_LABELS = {
    3: "★★★ 最重要 — Kazuki's priorities",
    2: "★★☆ 注目",
    1: "★☆☆ その他",
}


def _pill(category: str) -> str:
    label, css = CATEGORY_PILL.get(category, ("Tech News", "pill-tn"))
    return f'<span class="pill {css}">{label}</span>'


def _article_html(article: dict) -> str:
    title = article.get("title", "")
    url = article.get("url", "#")
    summary = article.get("summary", "")
    learning = article.get("learning", "")
    practical = article.get("practical_application", "")
    category = article.get("category", "Tech News")
    importance = article.get("importance", 1)

    fields = ""
    if summary:
        fields += f"""
        <div class="field">
          <div class="field-label">概要</div>
          <div class="field-body">{summary}</div>
        </div>"""
    if learning:
        fields += f"""
        <div class="field">
          <div class="field-label">学べること</div>
          <div class="field-body">{learning}</div>
        </div>"""
    if practical:
        fields += f"""
        <div class="field">
          <div class="field-label">実践的な応用</div>
          <div class="field-body">{practical}</div>
        </div>"""

    return f"""
    <div class="article">
      <div class="article-header">
        {_pill(category)}
        <span class="stars">{STARS.get(importance, "★☆☆")}</span>
      </div>
      <div class="article-title">{title}</div>
      {fields}
      <a class="source-link" href="{url}" target="_blank">→ ソースを読む</a>
    </div>"""


def build_html(articles: list[dict], date: str) -> str:
    """Build HTML email from enriched articles list."""
    with open(TEMPLATE_PATH, encoding="utf-8") as f:
        template = Template(f.read())

    # Sort by importance descending
    sorted_articles = sorted(articles, key=lambda a: -a.get("importance", 1))

    articles_html = ""
    current_group = None
    for article in sorted_articles:
        importance = article.get("importance", 1)
        if importance != current_group:
            current_group = importance
            articles_html += f'<div class="group-heading">{GROUP_LABELS[importance]}</div>'
        articles_html += _article_html(article)

    sources = sorted({a.get("source", "") for a in articles if a.get("source")})

    return template.safe_substitute(
        date=date,
        article_count=len(articles),
        articles_html=articles_html,
        source_count=len(sources),
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
