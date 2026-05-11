# Manager Agent Rules

Manager Agent (`manager/` パッケージ) の改修・テスト時に適用するルール。
対象: `manager/**/*.py`

## Rules

- Manager は **コード駆動の state machine**。LLM にステート遷移を判断させない
- 状態遷移は `manager/states.py` の `LEGAL_TRANSITIONS` に必ず登録する。`is_legal()` を通らない遷移を runner で発生させない
- リトライ上限・コスト上限・タイムアウトは `manager/limits.py` に定数で持つ。env / 引数で動的変更しない
- Manager は既存の 7 スラッシュコマンド (`/triage-issue` `/make-execution-packet` `/spec-architect` `/run-dev-loop` `/implementation-reviewer` `/test-qa` `/pr-creation`) を **無改修** で呼ぶ。コマンド側の Output Format に依存する
- subagent 出力のパーサ追加・変更時は `manager/tests/fixtures/*.md` にゴールデン入力を追加し、parser テストでカバーする
- `Subagent` / `GitOps` / `Escalator` の Protocol を破らない。Real 実装と Dummy 実装は同 Protocol を満たす
- `subprocess.run` 系は必ず `timeout=SUBAGENT_TIMEOUT_SECONDS` を渡し、`TimeoutExpired` をハンドルする
- `claude -p` 起動時は `--bare`, `--no-session-persistence`, `--max-budget-usd`, `--session-id`, `--add-dir <repo_root>`, `--output-format json`, `--dangerously-skip-permissions` を必ず付ける
  - `--bare` の理由: CLAUDE.md auto-discovery / hooks / MCP / `.env` の意図せぬ読み込みを完全停止する。`.env` に `ANTHROPIC_API_KEY` が残っていた場合、`--bare` 無しだと `claude -p` が auto-discovery で API key を拾い、**Claude Max plan ではなく API ($) 課金にサイレントに切り替わる**。Phase 3 live 1 回目で実際に発生した
  - skip-permissions の理由: 非対話 `-p` モードで Edit/Write/Bash の許可ダイアログが起きると subagent が deadlock する。Manager 自身が kill-switch / cost limit / diff limit / NEEDS_HUMAN escalation で安全網を担っているため、内側の subagent は trusted モードで動かす
- subprocess.run は env を `sanitized_env()` で明示渡し、`ANTHROPIC_*` を **除去** する。env 経由で API key が再混入することを物理的に防ぐ
- 既知の Phase 4 まで残る制約: `/pr-creation` が `--base main` ハードコードのため子 PR は一旦 main に向く。`_handle_verify_pr` が `gh pr edit <url> --base <epic-branch>` で retarget する (soft-fail: retarget 失敗してもログのみ、PR 自体は残る)
- `resume` / 失敗子 retry: `python -m manager run <epic#>` で既存 state を resume、`--retry <child#> ...` で失敗子をリセットしてキュー先頭に戻す
- SIGINT / SIGTERM: 子境界で flag をチェックし、現在の subagent 完了を待ってから state を save し HALTED 終了。Ctrl-C で state corruption しない
- `python -m manager status <epic#>` で epic + 子 state のスナップショットを表示 (実行なし)
- state JSON 書き込みは `_atomic_write` を経由し、`.bak` を残す
- `epic_lock` は `flock(2)` 経由。lock 取得失敗時は `EXIT_LOCK_TAKEN=4` で即終了
- kill-switch (`.claude/STOP` / `.claude/STOP_NOW`) は **全 transition 直前** で評価する
- 型ヒント必須。`Any` / `# type: ignore` で逃げない
- async / 並行処理を導入しない (1 Manager = 1 epic = 1 プロセス)
- 既存 `/orchestrate` (LLM 駆動ルータ) を Manager 内で呼ばない。両者は併存
- Phase 4 まで multi-epic 並列・Web UI・既存エージェント改修は **Non-goals**
