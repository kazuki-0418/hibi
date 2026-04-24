# /triage-issue

GitHub Issue を読み、自律実行の安全性を判定する分類コマンド。計画・実装はしない。

## Role

Issue を `auto-fixable` / `confirm-first` / `blocked` に分類し、スコープとリスクフラグを付けて返す。

## Inputs

- `$ARGUMENTS`: Issue テキスト、または Issue 番号
- 引数がない場合: チャット直前の Issue 本文を使う
- 両方ない場合: 停止してユーザーに Issue を要求する

## Required Reading

- `.claude/rules/spec-agent.md`
- `architecture/skills/hibi-domain.md`

## Forbidden

- コードを実装しない
- 実行パケットを作らない（それは `/make-execution-packet` の役割）
- 実装プランを書かない（それは `/spec-architect` の役割）
- Issue の修正版を提案しない

## Core Behavior

以下の観点で Issue を評価する:

- 要件の明確さ
- ドメイン境界への影響（Pipeline stage 境界、HMAC 署名、`is_sent` 整合、clicks append-only）
- API quota / cost への影響
- 1 PR に収まるスコープか
- セキュリティ・課金・運用窓・強い UX 判断の有無

### Blocking / Escalation Conditions

以下に該当する場合は `blocked` にする:

- セキュリティ・課金・強い UX 判断が必要
- 要件が実質的に曖昧
- YouTube `search.list` の新規導入を伴う（quota 影響大）
- HMAC シークレット rotation を伴う（既配布リンク無効化）
- 破壊的スキーマ変更（DROP / ALTER COLUMN）を伴う
- embedding model 切り替えを伴う（全件 backfill）
- `clicks.user_id` を kazuki 固定から外す変更（multi-tenant 化判断）
- Pipeline stage 境界の再設計が必要
- 1 PR に収まらないスコープ

### Scope Estimation

- `small`: 1 ファイル・1 fetcher・1 migration で完結する変更
- `medium`: 複数ファイルにまたがるが契約変更は軽微
- `large`: スキーマ変更・pipeline 構成変更・複数モジュールにまたがる

`large` の場合のみ最小分割を提案する。

## Output Format

```text
# Classification
- auto-fixable | confirm-first | blocked

# Scope
- small | medium | large

# Risk Flags
- security
- billing
- quota-impact
- ux-heavy
- ambiguous
- hmac-rotation
- schema-breaking
- embedding-migration
- multi-tenant
- pipeline-redesign

# Why

# Missing Information

# Blocking Question

# Split Proposal

# Execution Readiness
- ready | needs-confirmation | do-not-run
```

### Output Style

- 各項目を短く保つ
- 該当しない Risk Flags は除外する
- `Split Proposal` は `large` の場合のみ含める
- 長文・推測・改善提案を書かない
