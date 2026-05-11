"""
Send daily news email from enriched articles.

Usage:
  python send_mail.py --subject "Daily Tech News - 2026-04-15" \
                      --from-enriched enriched_articles.json
"""
import argparse
import json
import os
from datetime import date

from dotenv import load_dotenv
from mailer import send

load_dotenv()


def format_subject(date_str: str, count: int) -> str:
    """Build the daily subject line.

    Format: ``YYYY.MM.DD — 今朝のN本`` (half-width period + em-dash, no emoji).
    """
    return f"{date_str} — 今朝の{count}本"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", default=None, help="Email subject (default: auto-generated)")
    parser.add_argument("--from-enriched", dest="from_enriched", default="enriched_articles.json")
    parser.add_argument("--date", default=None, help="Date string shown in email header (default: today)")
    args = parser.parse_args()

    date_str = args.date or date.today().strftime("%Y.%m.%d")

    with open(args.from_enriched, encoding="utf-8") as f:
        articles = json.load(f)

    subject = args.subject or format_subject(date_str, count=len(articles))

    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]

    send(
        subject=subject,
        articles=articles,
        date=date_str,
        to=gmail_address,
        from_addr=gmail_address,
        password=gmail_password,
    )
    print(f"Email sent: {subject}")


if __name__ == "__main__":
    main()
