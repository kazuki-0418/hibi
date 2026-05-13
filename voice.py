"""Voice & tone guard for Hibi summary text.

Hibi の design-system は `design-system/README.md` の "Content fundamentals"
で voice & tone を定義している (三人称・観察的・宣言的、賞賛は抑制、感嘆符
/絵文字/二人称呼びかけ/マーケ語禁止)。`summarize()` が Claude から受け取った
要約文に対し、この関数で violation を検出する。

検出はあくまで **観測目的** で、配信パイプラインは止めない。違反があれば
呼び出し側で warning ログを出す想定。意図:

- LLM の出力が design-system から逸脱しているかを継続的に観測したい
- ただし「驚愕」「!」が含まれた途端に配信が落ちると運用負荷が跳ねるので、
  検出だけして配信は通す
- 将来的に違反率が下がらない場合は、ここで検出した patterns を hard-fail
  条件に格上げできる余地を残す

このため本モジュールは副作用なしの pure function に限定する (psycopg・
ネットワーク・logging 依存を持ち込まない)。
"""
from __future__ import annotations

import re

# design-system/README.md "Content fundamentals → What we don't do" と
# "Voice" セクションを根拠とする禁止表現。
#
# - クリックベイト動詞: 驚愕 / 衝撃 / やばい / 革命的 / 画期的
# - 過剰賞賛: すごい / 最高
# - マーケ CTA: 今すぐ / お見逃しなく / 必見
# - 二人称呼びかけ: あなた / 読者の皆様
# - 一人称: 私 / 僕 (newspaper has no first-person voice)
#
# 完全一致ではなく substring 検出。「驚愕の発表」「読者の皆様、必見」のような
# 自然な文脈で機能するため。
_FORBIDDEN_WORDS: tuple[str, ...] = (
    "驚愕",
    "衝撃",
    "やばい",
    "すごい",
    "最高",
    "画期的",
    "革命的",
    "お見逃しなく",
    "今すぐ",
    "必見",
    "あなた",
    "読者の皆様",
    "私",
    "僕",
)

# 絵文字検出: Unicode の主要な絵文字ブロックをカバー。
# - Misc Symbols and Pictographs (1F300-1F5FF): ☂️ 📅 📰 など
# - Emoticons (1F600-1F64F): 😀 など
# - Transport and Map (1F680-1F6FF): 🚀 など
# - Supplemental Symbols and Pictographs (1F900-1F9FF): 🤖 など
# - Symbols and Pictographs Extended-A (1FA70-1FAFF)
# - Misc Symbols (2600-26FF) + Dingbats (2700-27BF): ☀ ✨ など
#
# design-system は「・」(middot, U+30FB) を例外として明示的に許可しているが、
# 上記レンジには含まれないので除外不要。
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001F5FF"
    "\U0001F600-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA70-\U0001FAFF"
    "☀-⛿"
    "✀-➿"
    "]"
)


def check_voice_violations(text: str) -> list[str]:
    """要約テキストの voice & tone 違反を列挙する。

    Returns:
        違反パターンの list。重複は除去するが、複数種類の違反は別要素として
        返す。空 list は「違反なし」。

    検出対象:
        - `_FORBIDDEN_WORDS` のいずれかが substring として含まれる
        - 感嘆符 ``!`` または全角 ``！`` が含まれる
        - 絵文字 (`_EMOJI_RE`) が含まれる
    """
    violations: list[str] = []

    for word in _FORBIDDEN_WORDS:
        if word in text:
            violations.append(word)

    if "!" in text or "！" in text:
        violations.append("感嘆符")

    if _EMOJI_RE.search(text) is not None:
        violations.append("絵文字")

    return violations
