"""Goal-conditioned summarization output parsing (KAZ-202)."""

from __future__ import annotations

from dataclasses import dataclass

_GOAL_NOTE_MARKER = "---関連---"


@dataclass(frozen=True)
class SummaryResult:
    """Faithful summary (stored in DB) plus optional goal-relevance note (email only)."""

    summary: str
    goal_note: str


def build_summarize_prompt(
    title: str,
    content: str,
    *,
    voice_rule: str,
    content_char_limit: int,
    goal_context: str,
    target_project_label: str = "",
) -> str:
    goal_block = ""
    if goal_context.strip():
        goal_block = f"""
対象プロジェクトの conditioning（要約の歪め禁止・適用注記の根拠のみ）:
{goal_context[:4000]}
"""
    project_hint = ""
    if target_project_label:
        project_hint = (
            f"- 「---関連---」ブロックは必ず「→ {target_project_label}:」で始める。"
            "そのプロジェクトへの適用を1〜2行で述べる（事実要約は変更しない）。\n"
        )

    return f"""{voice_rule}
{goal_block}
以下の記事/動画を日本語で要約してください。
技術的な要点、実装のヒント、開発者にとっての示唆を優先してください。

重要:
- 「---要約---」ブロックは出典に忠実な3行要約のみ。推測・補完・謝罪は禁止。困難なら要約ブロックを空にする。
{project_hint}- 「---関連---」ブロックが不要な場合は空にする。
- 各行は1文で「・」で始める。

タイトル: {title}

本文:
{content[:content_char_limit]}

出力形式（この2ブロックのみ）:
---要約---
・(1行目)
・(2行目)
・(3行目)
---関連---
・(関連があれば1行目)
・(関連があれば2行目)"""


def parse_summarize_response(raw: str) -> SummaryResult:
    """Split Claude output into faithful summary and goal-relevance note."""
    text = raw.strip()
    if _GOAL_NOTE_MARKER not in text:
        return SummaryResult(summary=text, goal_note="")

    summary_part, note_part = text.split(_GOAL_NOTE_MARKER, 1)
    summary = summary_part.replace("---要約---", "").strip()
    goal_note = note_part.strip()
    return SummaryResult(summary=summary, goal_note=goal_note)
