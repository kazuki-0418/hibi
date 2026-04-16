"""
Send daily news email.
Called by the Claude Code scheduled task after summarization.

Usage:
  python send_mail.py --subject "Daily Tech News - 2026-04-15" \
                      --hn "summary text..." \
                      --reddit "summary text..." \
                      --itmedia "summary text..." \
                      --producthunt "summary text..."

Or pipe a JSON file:
  python send_mail.py --from-json summaries.json
"""
import argparse
import json
import os

from dotenv import load_dotenv
from mailer import send

load_dotenv()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject", required=True)
    parser.add_argument("--from-json", dest="from_json", help="Path to JSON file with summaries")
    parser.add_argument("--hn", default="", help="HackerNews summary")
    parser.add_argument("--reddit", default="", help="Reddit summary")
    parser.add_argument("--itmedia", default="", help="ITmedia summary")
    parser.add_argument("--producthunt", default="", help="Product Hunt summary")
    args = parser.parse_args()

    if args.from_json:
        with open(args.from_json, encoding="utf-8") as f:
            data = json.load(f)
        sections = [{"source": k, "summary": v} for k, v in data.items()]
    else:
        sections = []
        if args.hn:
            sections.append({"source": "HackerNews", "summary": args.hn})
        if args.reddit:
            sections.append({"source": "Reddit", "summary": args.reddit})
        if args.itmedia:
            sections.append({"source": "ITmedia", "summary": args.itmedia})
        if args.producthunt:
            sections.append({"source": "Product Hunt", "summary": args.producthunt})

    gmail_address = os.environ["GMAIL_ADDRESS"]
    gmail_password = os.environ["GMAIL_APP_PASSWORD"]

    send(
        subject=args.subject,
        sections=sections,
        to=gmail_address,
        from_addr=gmail_address,
        password=gmail_password,
    )
    print(f"Email sent: {args.subject}")


if __name__ == "__main__":
    main()
