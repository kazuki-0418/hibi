# /manager

Manager Agent (Python ステートマシンオーケストレータ) の起動ラッパ。
このコマンドは引数を `python -m manager` に通すだけで、フロー判断・retry 制御・state 更新は一切行わない (それらは `manager/` パッケージ側に閉じている)。

## Role

Bash tool 経由で `python -m manager $ARGUMENTS` を実行し、exit code を解釈して次アクションを案内する。Manager の振る舞いそのものには関与しない。

## Inputs

- `$ARGUMENTS`: Manager CLI に渡す引数。LLM は文字列をそのまま通す
  - 例: `status 39`
  - 例: `run 39 --slug design-system --live`
  - 例: `resume 39 --live --retry 40`
  - 例: `run 8 --children 20 21` (Dummy で動作確認)
- 引数なし → `python -m manager --help` を実行して使い方を返す

## Required Reading

- `.claude/rules/manager-agent.md`

詳細仕様 (state machine / artifact レイアウト等) は `manager/runner.py` と `manager/states.py` を必要時のみ参照。

## Forbidden

- `$ARGUMENTS` を解釈・改変しない (typo でも直さない、そのまま渡す)
- フローを再判断しない (LLM が state 遷移を決めると Manager の存在意義が消える)
- 既存サブコマンド (`/triage-issue` `/spec-architect` `/run-dev-loop` 等) をここから直接呼ばない (それらは Manager から呼ばれる)
- Manager の stdout を別の slash に転送しない
- ユーザーが指定していない `--live` を勝手に付けない (実 API/git/PR 副作用が出る)
- ユーザーが指定していない `--retry` を勝手に付けない (失敗子を意図せず再実行してしまう)
- `gh pr create` `gh issue comment` をこの slash 内から直接実行しない (それは Manager の仕事)
- Manager の state JSON や log.jsonl を直接編集しない

## Core Behavior

### Step 1: 引数の有無を確認

- `$ARGUMENTS` が空 or `--help` のみ → `python -m manager --help` を実行
- それ以外 → Step 2 へ

### Step 2: timeout を決めて実行

Bash tool で実行。**サブコマンドで timeout を変える**:

| サブコマンド | timeout 目安 | 実行方式 |
|---|---|---|
| `status <#>` | 5 秒 | 前景 (default timeout) |
| `run <#>` (`--live` なし) | 30 秒 | 前景 |
| `run <#> --live` | 10〜30 分 | `run_in_background: true` (子が複数あるなら必須) |
| `resume <#>` (同上) | 同上 | 同上 |

`run_in_background: true` の場合は完了通知が来るまで待つ。完了後 `/tmp/manager-<#>.out` のように出力先を明示するなら、stdout を保存して読み戻す。

実行コマンド:

```
python -m manager $ARGUMENTS
```

### Step 3: exit code 解釈

| exit | 意味 | ユーザーへの案内 |
|---|---|---|
| 0 | `EXIT_OK` (epic 完走 or status 成功) | サマリー 1-3 行。done/skipped/failed の内訳を示す |
| 2 | `EXIT_NEEDS_HUMAN` (子で人間判断要) | 「`gh issue view <epic#> --comments` で詳細確認」「修正後 `/manager resume <epic#> --live --retry <child#>`」 |
| 3 | `EXIT_HALTED` (kill-switch / cost / signal) | 「`/manager status <epic#>` で state 確認」「`.claude/STOP` がある場合は `rm .claude/STOP` してから resume」 |
| 4 | `EXIT_LOCK_TAKEN` (別 Manager 実行中) | 「`ps aux \| grep 'python -m manager'` で生きてる pid を確認、誤って残った lock なら `rm .claude/state/epic-<#>/lock`」 |
| 1 / other | Python 例外 / 引数エラー | stderr 末尾 20 行を表示 + 「`/manager --help` で引数を確認」 |

### Step 4: 出力整形

- stdout が長い場合は 冒頭 5 行 + 末尾 10 行のみ表示
- `--live` 付きで実行した場合、結果に関わらず「課金確認: `claude.ai/usage` で Max plan quota の消費を確認してください」を末尾に添える
- live run で副作用が残った可能性がある場合 (`EXIT_NEEDS_HUMAN` / `EXIT_HALTED`) は、残存ブランチ・state dir・Issue コメントの存在を伝える

## Output Format

```text
# Manager Result
- Command: <そのまま実行した python -m manager ... のコマンド行>
- Exit Code: <数字> (<意味>)
- Duration: <秒>

# Output
<整形した stdout。長すぎる場合は ... で省略>

# Next Action
<次の具体的なコマンド or 確認手順。1〜3 行>

# Notes
<該当時のみ: 課金確認 / 副作用 / lock 状態 / 等>
```

### Output Style

- 各セクション 1〜3 行
- stdout 全文を貼らない (詳細は `/manager status <#>` で確認できる前提)
- exit code が `NEEDS_HUMAN` / `HALTED` の場合は **対処コマンドを具体的に書く** (推測ではなく上記マッピングに沿う)
- 課金 (`--live`) が走った可能性があれば必ず注意喚起
- ユーザーに「次は何をすればいいか」が 1 行で分かる Next Action を残す
