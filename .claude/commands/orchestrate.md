# /orchestrate

Main Orchestrator コマンド。任意のタスクを分類し、適切な subagent に振り分けて結果を統合する。

## Role

依頼を受け、`.claude/skills/orchestrator.md` の Classification と Standard Flows に従って subagent (`/triage-issue` / `/spec-architect` / `/make-execution-packet` / `/run-dev-loop` / `/implementation-reviewer` / `/test-qa` / `/pr-creation`) に振り分け、結果を要約して次アクションを提示する。

## Inputs

- `$ARGUMENTS`: 任意のタスク説明、Issue 番号、実装サマリー、設計相談、テスト観点依頼など
- 引数がない場合: チャット直前のユーザー依頼を使う
- 両方ない場合: 停止して依頼内容を要求する

## Required Reading

- `.claude/skills/orchestrator.md`
- `architecture/skills/hibi-domain.md`
- `CLAUDE.md`（存在する場合）

各 subagent の詳細は呼び出し時に subagent 側で Read させる。

## Forbidden

- subagent が本来担う作業を Orchestrator 自身で行わない
- subagent の生出力をそのままユーザーに貼り付けない
- 分類が曖昧なまま subagent を呼ばない（3 候補以上で曖昧なら先にユーザー確認）
- `blocked` / `do-not-run` / `fix before merge` / `confirm-first` を無視して次段に進まない
- 同じ subagent を 3 回以上連続で呼ばない
- Required Reading を読まない subagent がいても黙認しない（1 回だけ再実行）
- 人間への確認なしに merge / deploy / GitHub Actions の本番実行をしない

## Core Behavior

`.claude/skills/orchestrator.md` の以下セクションに従う:

- Classification
- Standard Flows
- Subagent Invocation
- Result Integration Rules
- Stop Conditions

### Invocation Template

```text
あなたは /<command-name> として動作する。
以下の command ファイルを最初に Read tool で読み、その Required Reading セクションに列挙された全ファイルを読んでから開始すること。
- .claude/commands/<command-name>.md

入力 ($ARGUMENTS):
<内容>

出力は .claude/commands/<command-name>.md の Output Format に厳密に従うこと。
```

### Parallel vs Sequential

- 依存のない subagent（例: `/spec-architect` と `/test-qa` pre）は同一 message に並列で Agent 呼び出しを置く
- 依存のある subagent（例: `/triage-issue` → `/make-execution-packet`）は逐次実行し、前段の出力を次段の入力に渡す

### Re-routing

最初の分類が誤りだと判明した場合、Orchestrator は 1 回だけ再分類して別 subagent を呼ぶ。2 回以上は停止してユーザーに確認。

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

- 各セクション 1〜3 行
- subagent の Verdict / Classification / Recommendation はそのまま引用してよい
- 長い diff や全文ログは貼らない
- ユーザー確認が必要な分岐があれば `Next Action` に明示的な Yes/No 質問を置く
