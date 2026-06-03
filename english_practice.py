"""English output practice block for the daily digest (KAZ-203).

One prompt per edition: tied to a goal-ranked or challenge article, with a
copy-paste Claude request that stresses naturalness over grammar nitpicks.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from anthropic import Anthropic

log = logging.getLogger(__name__)

GOAL_SNIPPET_LIMIT = 800
PASTE_SUMMARY_LIMIT = 400
CLAUDE_MODEL = "claude-haiku-4-5-20251001"


@dataclass(frozen=True)
class EnglishPractice:
    """Single daily English output exercise."""

    prompt_line: str
    paste_request: str
    article_title: str


def pick_english_anchor(delivered: list[dict]) -> dict | None:
    """Pick one digest article for the English prompt (goal first, then challenge)."""
    if not delivered:
        return None
    for slot in ("goal", "challenge"):
        for item in delivered:
            if item.get("digest_slot") == slot:
                return item
    return delivered[0]


def build_paste_request(
    prompt_line: str,
    *,
    article_title: str,
    article_summary: str | None,
    goal_snippet: str,
) -> str:
    """Deterministic Claude paste block (naturalness > grammar, speak-first)."""
    summary_text = (article_summary or "").strip()
    if not summary_text:
        summary_text = "(No summary — react to the title and your own take.)"
    else:
        summary_text = summary_text[:PASTE_SUMMARY_LIMIT]

    goal_text = goal_snippet.strip() or "(No project focus loaded today.)"
    goal_text = goal_text[:GOAL_SNIPPET_LIMIT]

    return (
        "Please help me write a short response in natural English.\n"
        "- At least one sentence (2–3 is fine).\n"
        "- Prioritize natural, fluent expression — not grammar nitpicking.\n"
        "- I already spoke my thoughts aloud first; this is the written step.\n\n"
        "---\n"
        "Today's exercise prompt:\n"
        f"{prompt_line}\n\n"
        "---\n"
        f"Article title: {article_title}\n\n"
        "Digest context (may be Japanese):\n"
        f"{summary_text}\n\n"
        "---\n"
        "My current project focus (for relevance only):\n"
        f"{goal_text}\n"
    )


def _fallback_prompt_line(article_title: str, project_slugs: tuple[str, ...]) -> str:
    projects = ", ".join(project_slugs) if project_slugs else "your active projects"
    short_title = article_title[:80]
    return (
        f"In English (2–3 sentences): how does «{short_title}» apply to {projects}? "
        "Speak out loud first, then write at least one sentence. "
        "（まず声に出してから書く。）"
    )


def generate_english_practice(
    client: Anthropic,
    anchor: dict,
    goal_focus_text: str,
    project_slugs: tuple[str, ...],
) -> EnglishPractice:
    """Generate today's English output prompt via Claude, with template fallback."""
    title = anchor.get("title", "")
    summary = anchor.get("summary")
    goal_snippet = goal_focus_text[:GOAL_SNIPPET_LIMIT]

    prompt = f"""You create ONE short English-output exercise for a Japanese reader who wants to practice switching into English (not translation drills).

Article title: {title}
Digest summary (may be empty): {(summary or "")[:PASTE_SUMMARY_LIMIT]}
Project focus (trimmed): {goal_snippet or "(none)"}
Active projects: {", ".join(project_slugs) if project_slugs else "(unspecified)"}

Rules for prompt_line:
- One line the reader sees in their morning email.
- Include an English task (2–3 sentences worth of output expected).
- Tie the task to the article AND the reader's project focus (no blank page).
- End with exactly this Japanese phrase: （まず声に出してから書く。）
- No emoji, no exclamation marks, no marketing tone.

Return ONLY JSON:
{{"prompt_line": "..."}}"""

    prompt_line = ""
    try:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        if raw.startswith("{"):
            parsed = json.loads(raw)
            if isinstance(parsed.get("prompt_line"), str):
                prompt_line = parsed["prompt_line"].strip()
    except (json.JSONDecodeError, KeyError, TypeError, IndexError) as exc:
        log.warning("english practice JSON parse failed: %s", exc)
    except Exception as exc:
        log.warning("english practice generation failed: %s", exc)

    if not prompt_line or "声に出して" not in prompt_line:
        prompt_line = _fallback_prompt_line(title, project_slugs)

    paste_request = build_paste_request(
        prompt_line,
        article_title=title,
        article_summary=summary,
        goal_snippet=goal_snippet,
    )
    return EnglishPractice(
        prompt_line=prompt_line,
        paste_request=paste_request,
        article_title=title,
    )
