# orchestrator

Main Orchestrator が任意のタスクを分類し、適切な subagent に振り分けるためのルーティング skill。

`/orchestrate` コマンドから参照される。汎用アーキテクチャ文書ではない。

## Core Rules

- ユーザーの依頼を自分で実装・判定せず、適切な subagent に振る
- 複数の subagent を跨ぐ場合は順序と依存を明示する
- subagent 呼び出しは Agent tool 経由で行う
- subagent に渡す prompt には「Required Reading を Read tool で必ず読むこと」を毎回明示する
- subagent の出力をそのまま貼り付けない。要約と次アクションを main session が統合する
- 分類が曖昧な場合は勝手に決めず、ユーザーに確認する

## Classification

| 種別 | シグナル | 振り先 |
| ------ | --------- | -------- |
| `issue-triage` | Issue 番号 / Issue 本文 / "この Issue やっていい?" | `/triage-issue` |
| `packetize` | triage 済み Issue の実装準備 / "実行パケット作って" | `/make-execution-packet` |
| `spec` | "要件整理" / "受け入れ基準" / "どう設計する?" / 設計判断の確認 | `/spec-architect` |
| `test-plan` | "テスト観点出して" / "edge case は?" / 実装前のテスト計画 | `/test-qa` (Mode: pre-implementation) |
| `implement` | 実行パケットあり / "これを実装して" / PR まで通す | `/run-dev-loop` |
| `review` | 実装サマリー / diff あり / "レビューして" | `/implementation-reviewer` |
| `test-gap` | 実装済みで "テスト不足ない?" / 実装後 QA | `/test-qa` (Mode: post-implementation) |
| `pr-only` | 実装完了 + ブランチあり / "PR だけ作って" | `/pr-creation` |
| `quota-impact` | "YouTube quota への影響は?" / "コスト試算" / API 呼び出し増減を伴う変更 | `/spec-architect`（quota 観点優先） |
| `migration` | "Neon スキーマ変更" / "migration 追加" / "embedding backfill" | `/spec-architect` → `/run-dev-loop` |

分類できない / 複数が同時に該当する場合は、ユーザーに 1 問だけ確認する。

## Standard Flows

### Flow A: Issue 受領 → PR 作成（フル自動）

1. `/triage-issue` → `ready` なら次へ。`needs-confirmation` ならユーザーに確認。`do-not-run` なら停止
2. `/make-execution-packet`
3. `/run-dev-loop`（内部で `/implementation-reviewer` と `/pr-creation` を呼ぶ）

### Flow B: 設計相談 → 実装

1. `/spec-architect` で計画
2. `/test-qa` (pre) でテスト観点を得る
3. ユーザー承認後に `/make-execution-packet`
4. `/run-dev-loop`

### Flow C: 実装済みコードの検証のみ

1. `/implementation-reviewer`
2. 必要に応じて `/test-qa` (post) でテスト漏れ確認

### Flow D: 単発 subagent

- 要件整理だけ → `/spec-architect`
- レビューだけ → `/implementation-reviewer`
- PR 作成だけ → `/pr-creation`

### Flow E: バッチ修正（Hibi 特有）

GitHub Actions workflow_dispatch を E2E の代替として使う。

1. `/triage-issue`
2. `/make-execution-packet`
3. `/run-dev-loop`（pytest + dry-run まで）
4. ユーザーに workflow_dispatch 手動実行を依頼
5. ログ確認後に `/implementation-reviewer`
6. `/pr-creation`

### Flow F: スキーマ変更（Hibi 特有）

破壊的でない migration 追加を含む変更。

1. `/spec-architect`（migration apply タイミングを明示）
2. `/run-dev-loop`（pytest までで停止、migration 適用は手動）
3. ユーザーに Neon SQL Editor での適用を依頼
4. `/implementation-reviewer`
5. `/pr-creation`

破壊的変更（DROP / ALTER COLUMN）は Flow F に乗せず、必ず Stop Conditions に落とす。

## Subagent Invocation

Agent tool を使う。`general-purpose` subagent_type を指定し、prompt の冒頭に以下を含める:

```text
あなたは /<command-name> として動作する。
以下の command ファイルを最初に Read tool で読み、その Required Reading セクションに書かれた全ファイルを読んでから開始すること。
- .claude/commands/<command-name>.md

入力:
<$ARGUMENTS 相当>

出力は .claude/commands/<command-name>.md の Output Format に厳密に従うこと。
```

並行可能な subagent（例: `/spec-architect` と `/test-qa` pre）は同じ message に複数 Agent 呼び出しを並列で置く。

依存がある subagent（例: `/triage-issue` → `/make-execution-packet`）は逐次実行。前段の出力を次段の `$ARGUMENTS` に渡す。

## Result Integration Rules

subagent の結果を受けたら、main session が以下を判断:

- 結果に `blocked` / `do-not-run` / `fix before merge` が含まれる → 停止しユーザーに確認
- 結果が空 / Required Reading 未実施の兆候 → その subagent を 1 回だけ再実行（prompt で Required Reading を強く再指示）
- 次 subagent が必要 → Classification に従って次を呼ぶ
- 依頼完了条件を満たした → 最終サマリーを main session で作成

subagent の出力全文をユーザーに貼り付けない。Orchestrator は要点 + 次アクションだけ提示する。

## Stop Conditions

以下の場合は subagent を呼ばず停止してユーザーに確認する:

- セキュリティ・課金・権限境界の判断が必要
- 依頼が曖昧で Classification が 3 候補以上
- 前段 subagent が `blocked` / `do-not-run` / `confirm-first` を返した
- 同じ subagent を 2 回呼んでも Required Reading を読んでいない兆候がある
- YouTube `search.list`（100 units）の新規導入を伴う変更
- HMAC シークレット rotation を伴う変更
- 破壊的スキーマ変更（DROP COLUMN / ALTER TYPE）
- embedding model 切り替え（全件 backfill が必要）
- `clicks.user_id` を kazuki 固定から外す変更
- Claude / OpenAI API のモデル変更を伴う変更
- 本番 GitHub Actions workflow を止める / 改変する変更

## Output Format

```text
# Classification
- <task type>

# Chosen Flow
- <Flow A/B/C/D/E/F or single subagent>

# Subagents Invoked
- <name>: <purpose>

# Summary of Results
- <1-3 lines per subagent>

# Next Action
- <what main session or user should do next>

# Blocked / Confirmation Needed (該当時のみ)
- <reason>
```

### Output Style

- 各項目は 1〜3 行
- subagent の生出力を貼らない
- 推測で subagent を追加呼び出ししない
