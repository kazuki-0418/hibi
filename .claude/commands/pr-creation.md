# /pr-creation

現在のブランチから **適切な base ブランチ** (epic ブランチがあればそれ、無ければ `main`) への PR を作成するコマンド。

## Role

変更ファイルを確認し、PR テンプレートを埋めて、MCP github (`mcp__github__create_pull_request`) で適切な base への PR を作る。MCP server が無い環境では Bash の `gh pr create` でフォールバックする。

## Base ブランチ判定 (絶対ルール — flat PR design)

**子 PR は常に親 epic ブランチを base にする。epic が無ければ main。sibling child branch を base にしない。**

設計分離:
- **ブランチ作成**: stacked (child-N は child-N-1 の tip から派生 → 前の子の成果物が見える)
- **PR の merge 先**: flat (常に epic、stacked PR は作らない)

判定ロジック:

1. 現在のブランチ名を取得 (`git rev-parse --abbrev-ref HEAD`)
2. パターン `^(epic/\d+-.*)-child-(\d+)$` にマッチするか確認 (例: `epic/134-epic-child-138` → epic prefix `epic/134-epic`)
3. マッチした場合: epic prefix (`epic/134-epic`) が local or origin に存在すれば `base` = それ、無ければ `base` = `main`
4. マッチしない (= 単独ブランチ) → `base` = `main`

理由: stacked PR は graphite 等のツール前提で GitHub native レビューが煩雑になる。kazuki は GitHub UI で素直に merge したい (上から順、PR 単独で完結)。PR diff が膨らむのは epic から先に merge する運用で自然に縮む (GitHub の base 引き算)。

検出例 (`epic/134-epic-child-139` で発火):

```bash
CURRENT=$(git rev-parse --abbrev-ref HEAD)
if [[ "$CURRENT" =~ ^(epic/.+)-child-[0-9]+$ ]]; then
  EPIC="${BASH_REMATCH[1]}"
  if git rev-parse --verify "$EPIC" >/dev/null 2>&1 || \
     git rev-parse --verify "origin/$EPIC" >/dev/null 2>&1; then
    BASE="$EPIC"
  else
    BASE="main"
  fi
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
- **child ブランチで PR を作る時、base に sibling child を選ばない** (絶対ルール、上記「Base ブランチ判定」参照)。epic prefix が存在すれば必ず epic、無ければ main。stacked PR チェーンを作らない
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
- Source config 変更なし → `### Sources` を `N/A`、変更あり → `verify_feeds.py` 実行ログを記載
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
- Sources: <summary + verify_feeds.py log | N/A>
- Architecture: <diagram type | omitted>
- Workflow: <summary | N/A>

# Remaining Unknowns
```
