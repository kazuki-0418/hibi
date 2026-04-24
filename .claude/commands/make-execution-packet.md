# /make-execution-packet

承認済み Issue を自律実装用の実行パケット (YAML) に変換するコマンド。

## Role

Issue を最小限・実装指向の実行パケットに整形する。受け入れ基準・制約・stop 条件を明文化する。

## Inputs

- `$ARGUMENTS`: Issue テキスト、または Issue 番号
- 引数がない場合: チャット直前の Issue 本文を使う
- 両方ない場合: 停止してユーザーに Issue を要求する

## Required Reading

- `.claude/rules/spec-agent.md`
- `architecture/skills/hibi-domain.md`
- `.claude/skills/spec-architect.md`

## Forbidden

- コードを実装しない
- 長い説明文を書かない
- スコープを広げない
- 未承認の新規機能を追加しない
- 計画中の未実装機能（multi-tenant / Astro UI / 評価UI / LangGraph）を現行仕様として扱わない

## Core Behavior

- 受け入れ基準は具体的かつテスト可能に書く
- 制約はスコープ拡大を防ぐものにする
- `target_tests` は最小限の合理的なセットにする
- `stop_conditions` は以下が関連する場合に必ず含める:
  - YouTube `search.list` の新規導入
  - HMAC シークレット rotation
  - 破壊的スキーマ変更
  - embedding model 切り替え
  - `clicks.user_id` 固定化前提の変更
- `out_of_scope` はリデザインと無関係なクリーンアップを除外する
- Issue が自律実装に安全でない場合は `classification: blocked` と明示し `goal` に理由を書く

## Output Format

```yaml
issue_id:
title:
classification:
scope:
goal:
acceptance_criteria:
  -
constraints:
  -
impacted_areas:
  -
target_tests:
  -
stop_conditions:
  -
out_of_scope:
  -
```

### Output Style

- 各リスト項目は 1 行で書く
- 説明文を追加しない
- 実装指向の短い語で書く
