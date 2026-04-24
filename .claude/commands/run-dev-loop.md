# /run-dev-loop

実行パケットをもとに、計画 → 実装 → 検証 → レビュー → PR 作成を自律的に実行するコマンド。

## Role

実行パケットを最小変更で満たし、pytest と dry-run を確認し、`/implementation-reviewer` のゲートを経て PR を作る一連を通す。

## Inputs

- `$ARGUMENTS`: 実行パケット（YAML）、または Issue テキスト
- 引数がない場合: チャット直前の実行パケットを使う
- 両方ない場合: 停止してパケットを要求する

## Required Reading

- `.claude/rules/dev-agent.md`
- `.claude/rules/test-agent.md`
- `.claude/skills/implementation-patterns.md`
- `.claude/skills/test-patterns.md`
- `architecture/skills/hibi-domain.md`

## Forbidden

- スコープを広げない
- unrelated refactor をしない
- 既存の pipeline stage 境界・HMAC 検証・clicks append-only 制約を破らない
- 計画中の未実装機能（multi-tenant / Astro UI / 評価UI / LangGraph）を現行として扱わない
- 人間への確認なしに merge しない
- main agent で最終レビューをしない（`/implementation-reviewer` を必ず呼ぶ）
- レビュアーの判定が出る前に PR を作らない
- `fix before merge` で PR を作らない
- 破壊的 migration を本番 Neon に適用しない（PR description に Pending と記載のみ）

## Core Behavior

### Execution Steps

1. 短い実装プランを作る
2. 実行パケットを満たす最小の変更を実装する
3. 最小限の合理的な検証セット（pytest + dry-run）を実行する
4. `/implementation-reviewer` を呼んで最終レビューを行う
5. レビュー結果が `fix before merge` の場合は 1 回修正してから再度 `/implementation-reviewer` を呼ぶ
6. 最終判定が `safe to merge` または `confirm before merge` の場合は PR-ready の出力を準備する
7. `/pr-creation` を使って現在のブランチから `main` への PR を作成する

### Validation Rules

- 最小限の合理的なチェックを選ぶ
- 以下の status を必ず明示する:
  - `Pytest Passed` / `Pytest Failed` / `Pytest Not Run`
  - `Dry-run Passed` / `Dry-run Failed` / `Dry-run Not Run`
  - `Migration Applied` / `Migration Pending` / `Migration N/A`
- migration が必要な場合、適用は手動（Neon SQL Editor）。PR description に明記する

### Review Gate Rules

- `/implementation-reviewer` が利用可能な場合は main agent で最終レビューを行わない
- レビュアーが判定を返す前に PR を作成しない
- PR 作成は最終判定が以下の場合のみ許可:
  - `safe to merge`
  - `confirm before merge`
- `confirm before merge` の場合は不確実性を PR サマリーに明記する
- `fix before merge` の場合は停止して PR を作成しない

### Stop Conditions

以下の場合は即座に停止する:

- セキュリティ・課金・強い UX 判断が必要
- 要件が実質的に不明瞭
- pytest または dry-run が失敗し現在のスコープで解決できない
- 1 回の修正後もレビュアーが `fix before merge` を返す
- YouTube quota / OpenAI cost / Claude cost の試算結果が想定外
- HMAC シークレット rotation が伴う変更
- YouTube `search.list`（100 units）の新規導入を伴う変更
- 破壊的スキーマ変更（DROP / ALTER COLUMN）を伴う変更
- embedding model 切り替え（全件 backfill が必要）を伴う変更
- `clicks.user_id` を kazuki 固定から外す変更

## Output Format

### Blocked

```text
# Blocked
## Reason
## What Needs Human Confirmation
## Current Status
```

### Success

```text
# Plan

# Implementation Summary
## Affected Areas
## Changes Made
## Tests Updated
## Migrations / Schema Updated
## sources.yaml Updated
## Docs Updated
## Pytest Status
## Dry-run Status
## Migration Apply Status
## Remaining Unknowns

# Review Verdict
- safe to merge | fix before merge | confirm before merge

# Review Notes

# PR Summary
## Title
## Summary
## Risks
## How to Test
## Remaining Unknowns
```
