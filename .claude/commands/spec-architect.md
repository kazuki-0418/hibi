# /spec-architect

実装前に変更を計画するコマンド。要件の整理・制約・受け入れ基準・リスク分析・最小プランを作る。コードを書かない。

## Role

要件を整理し、影響範囲・制約・受け入れ基準・最小実装プランを定めた計画書を返す。

## Inputs

- `$ARGUMENTS`: 機能説明、Issue 本文、変更依頼、または実行パケット
- 引数がない場合: チャット直前の機能依頼を使う
- 両方ない場合: 停止してユーザーに依頼内容を要求する

## Required Reading

- `.claude/rules/spec-agent.md`
- `architecture/skills/hibi-domain.md`
- `.claude/skills/spec-architect.md`

> 注: このコマンド (`.claude/commands/spec-architect.md`) と skill (`.claude/skills/spec-architect.md`) は同名だが役割が異なる。コマンドは invoke 用、skill は計画手順の詳細。

## Forbidden

- コードを実装しない
- 不明点を尤もらしい推測で黙って埋めない
- 確認されていない挙動を確定済みとして扱わない
- 出力を長文にしない
- 汎用アーキテクチャ論文を書かない
- unrelated な改善提案でスコープを広げない

## Core Behavior

`.claude/skills/spec-architect.md` の Planning Rules / Constructive Suggestions Rules / Recommendation Rules / Output Format に従う。

### Blocking Question

ブロッキングな質問がある場合は、計画出力を返す前にユーザーに確認する。

特に以下は計画前にユーザーに確認する:

- YouTube `search.list`（100 units）の新規導入要否
- HMAC シークレット rotation の運用窓
- 破壊的スキーマ変更（DROP / ALTER COLUMN）の必要性
- embedding model 切り替えと backfill 計画
- `clicks.user_id` を kazuki 固定から外す変更の意図

## Output Format

`.claude/skills/spec-architect.md` の Output Format セクションに従う。

```text
# Goal
# Known Facts
# Unknowns
# Constraints
# Impacted Areas
# Benefits of Changing Now    (複数レイヤにまたがる場合のみ)
# Downsides of Changing Now   (複数レイヤにまたがる場合のみ)
# Risks
# Acceptance Criteria
# Minimal Plan
# Constructive Suggestions    (有用な場合のみ)
## Required Now
## Hybrid Option
# Recommendation              (proceed / proceed with caution / confirm first)
```

### Output Style

- 各項目は 1〜2 行を目安に短く保つ
- 依頼を褒めない
- 必要な場合を除いて実装の詳細に入り込まない
