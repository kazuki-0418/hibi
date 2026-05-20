# /pr-creation

現在のブランチから **適切な base ブランチ** (epic ブランチがあればそれ、無ければ `main`) への PR を作成するコマンド。

## Role

変更ファイルを確認し、PR テンプレートを埋めて、MCP github (`mcp__github__create_pull_request`) で適切な base への PR を作る。MCP server が無い環境では Bash の `gh pr create` でフォールバックする。

## Base ブランチ判定 (絶対ルール — stacked design)

**子 PR は「直前の sibling child branch があればそれ、無ければ epic ブランチ、それも無ければ main」を base にする。** 親 epic を飛び越えて main を直接 base にしない。

判定ロジック:

1. 現在のブランチ名を取得 (`git rev-parse --abbrev-ref HEAD`)
2. パターン `^(epic/\d+-.*)-child-(\d+)$` にマッチするか確認 (例: `epic/134-epic-child-138` → epic prefix `epic/134-epic`, child number `138`)
3. マッチした場合の **stacked base 検索**:
   - 同 epic prefix の sibling 子ブランチ `<epic-prefix>-child-<N>` を `git for-each-ref` で列挙し、現在の child number より小さい `N` の中で **最大の `N`** を選ぶ
   - その branch が local (or origin) に存在すれば `base` = そのブランチ (例: 現在 `child-138`、`child-137` が存在 → `base = epic/134-epic-child-137`)
   - 存在しない (= merge 後に削除済) なら fallback して epic prefix そのものを base にする (例: `epic/134-epic`)
4. epic prefix にもブランチが無い (= マッチしない / 単独ブランチ) → `base` = `main`

理由: 子 #N の PR base を一つ前の子 #N-1 にすることで、PR を stacked PR の連鎖にし、人手 merge を待たずに次の子を進められる。merge は最終的に下から (#N-1 → #N → ... の順で kazuki が承認)。

検出例 (`epic/134-epic-child-138` で発火):

```bash
CURRENT=$(git rev-parse --abbrev-ref HEAD)
[[ "$CURRENT" =~ ^(epic/.+)-child-([0-9]+)$ ]] || { BASE="main"; exit 0; }
EPIC="${BASH_REMATCH[1]}"
CHILD_N="${BASH_REMATCH[2]}"
# Find highest sibling with lower number
PREV=$(git for-each-ref "refs/heads/${EPIC}-child-*" --format='%(refname:short)' \
       | awk -F'-child-' -v cur="$CHILD_N" '$2 < cur {print $0}' \
       | sort -t- -k4 -n | tail -1)
if [[ -n "$PREV" ]] && git rev-parse --verify "$PREV" >/dev/null 2>&1; then
  BASE="$PREV"
elif git rev-parse --verify "$EPIC" >/dev/null 2>&1; then
  BASE="$EPIC"
else
  BASE="main"
fi
```

## Inputs

- `$ARGUMENTS`: ブランチ名、サマリー、関連 Issue 番号（任意）
- 引数がない場合: チャット直前の実装サマリーと現在のブランチ名を使う

## Required Reading

- `.github/PULL_REQUEST_TEMPLATE.md`（存在すればテンプレートとして使う）
- `architecture/skills/hibi-domain.md`

## Forbidden

- 人間への確認なしに merge しない
- force push をしない
- `main` ブランチに直接コミット・push しない
- **stacked design に違反して `main` / 過去 sibling より上 (低い number の child) を base にしない** (絶対ルール、上記「Base ブランチ判定」参照)。直前の sibling → epic → main の優先順を守る
- `.env` / 鍵 / トークン / `*.json` の credentials を stage しない
- レビュアーの判定が `fix before merge` のまま PR を作らない
- HMAC シークレット rotation を伴う変更は main への直接 push をしない（必ずブランチ + PR + 運用窓説明）

## Core Behavior

### Step 1: ブランチ名から Issue 番号を抽出

例:

- `feat/42-add-rss-source` → Issue: `42`
- `agent/issue-7` → Issue: `7`

正規表現 `/(\d+)/` でブランチ名から最初の数字を抽出する。

- 見つかった場合 → サマリーセクションに `Closes #<number>` を含める
- 見つからない場合 → `Closes #?` にして手動で補完を促す

### Step 2: 変更ファイルを確認

```bash
git diff --name-only <base>...HEAD   # <base> は「Base ブランチ判定」で決めた値 (epic ブランチ or main)
```

| パス | フラグ |
| ------ | ------ |
| `fetchers/`, `db.py`, `daily_news.py`, `service/` | **Pipeline / Backend changed** |
| `migrations/` | **Schema changed** |
| `sources.yaml` | **Source config changed** |
| `architecture/` | **Architecture changed** |
| `.github/workflows/` | **Workflow changed** |
| `templates/` | **Email template changed** |

### Step 3: テンプレートを埋める

条件付きセクション:

- Pipeline 変更なし → `### Pipeline` を `N/A`
- Schema 変更なし → `### Schema` を `N/A`、変更あり → migration apply status を必ず記載
- Source config 変更なし → `### Sources` を `N/A`、変更あり → `verify_channels.py` 実行ログを記載
- Architecture 変更なし → `## Architecture / Flow Diagram` セクションを省略
- Architecture が変わった場合 → 変更タイプに応じた Mermaid ダイアグラムを挿入

### Mermaid Diagram Selection

| 変更タイプ | ダイアグラム種別 |
| ----------- | ---------------- |
| Pipeline stage 構成変更 | `flowchart TB` |
| データモデル（articles / clicks）追加・変更 | `erDiagram` |
| Click tracking フロー変更 | `sequenceDiagram` |
| 状態遷移変更（is_sent 等） | `stateDiagram-v2` |

ダイアグラムガイドライン:

- after の状態だけを示す。before/after 比較はしない
- 変更に直接関与するノードだけを含める
- 既存の Hibi 命名（articles / clicks / sources / fetcher / Stage A/B/C）を使う

### Step 4: PR 作成

**推奨**: MCP github の `mcp__github__create_pull_request` を呼ぶ。
引数:

- `owner` / `repo` は現在のリポジトリ
- `base`: 「Base ブランチ判定」で決めた値 (epic ブランチ or `main`)
- `head`: 現在のブランチ
- `title`: concise summary（PR Title Format に従う）
- `body`: 埋めたテンプレート

**フォールバック** (MCP github が利用できない環境のみ):

```bash
BASE=$(... 「Base ブランチ判定」で決めた値、epic ブランチがあればそれ、無ければ main ...)
gh pr create \
  --base "$BASE" \
  --head <current-branch> \
  --title "<concise summary>" \
  --body "<filled-in template>"
```

どちらの経路で作成しても、実行後レポートの URL は実際に作られた PR の URL を必ず記載すること（hallucination 禁止）。

## Output Format

### PR Title Format

`[type]: <description>`（type: `feat` / `fix` / `refactor` / `chore` / `docs`）

### 実行後レポート

```text
# PR Created
- URL:
- Title:
- Branch:
- Closes Issue:

# Sections Filled
- Pipeline: <summary | N/A>
- Schema: <summary + migration apply status | N/A>
- Sources: <summary + verify_channels.py log | N/A>
- Architecture: <diagram type | omitted>
- Workflow: <summary | N/A>

# Remaining Unknowns
```
