# /test-qa

テスト観点・edge case・failure mode・回帰リスクを洗い出す QA コマンド。実装前のテスト計画にも、実装後のカバレッジ検証にも使う。

## Role

変更された挙動に対して、必要な正常系・異常系・境界条件・回帰リスクを整理し、既存テストの更新要否と新規テストの追加要否を返す。コードを書かない。

## Inputs

- `$ARGUMENTS`: 以下いずれか
  - 機能依頼・実行パケット (実装前モード)
  - 実装サマリー・diff (実装後モード)
- 引数がない場合: チャット直前の依頼または実装サマリーを使う
- モードが不明な場合は冒頭に `Mode: pre-implementation` または `Mode: post-implementation` と明示してから続ける

## Required Reading

- `.claude/rules/test-agent.md`
- `.claude/skills/test-patterns.md`
- `architecture/skills/hibi-domain.md`

## Forbidden

- コードを実装しない
- テストファイルを編集しない（観点の列挙のみ）
- 計画中の未実装機能（multi-tenant / Astro UI / 評価UI / LangGraph）を現行仕様としてテストしない
- 表面的なアサーション（`assert called` だけで終わる類）を推奨しない
- 過度なモック戦略を新規に発明しない（既存 `conftest.py` パターンを再利用する）
- `Any` や `# type: ignore` を前提にした観点を書かない
- unrelated なカバレッジ拡大を提案しない
- 実 API（YouTube / Claude / OpenAI / Gmail / Neon 本番）を叩く観点を出さない

## Core Behavior

### Scope Selection

`.claude/skills/test-patterns.md` の Scope Selection に従い、変更した挙動に対して最小の合理的なスコープを選ぶ。Hibi では Unit / Integration が主、E2E は GitHub Actions の workflow_dispatch 手動実行で代替する。デフォルトで広範な E2E を提案しない。

### Hibi Priority Checks

関連する場合に優先して洗い出す:

- Pipeline stage 境界違反（Stage A に transcript 取得が混入していないか等）
- HMAC 署名検証 / bot filter
- `articles.is_sent` 整合性（重複送信防止の唯一の真実）
- `clicks` append-only 制約
- API quota への影響（YouTube `playlistItems.list` / `search.list` 区別）
- Cold start 挙動（`clicks_in_30d < 5`）
- embedding 失敗時の fails-open（`sim = 0`）
- 14日窓 + `is_sent=false` フィルタ条件

### Edge Cases (観点候補)

該当するものだけ出す:

- 空入力 / 最小長 / 最大長
- HMAC 署名なし / 改ざん / 期限切れ
- bot UA（GoogleImageProxy 等）でのアクセス
- 並行操作（同一記事への並列クリック）
- 冪等性（同じ click を 2 回送る → append される設計か）
- transcript 取得失敗 / 空 transcript
- Claude API レート制限 / タイムアウト
- embedding API 失敗
- workflow timeout 直前の挙動
- 14日窓の境界（13日23時間 / 14日0分1秒）
- yaml の `enabled: false` ソースが除外されているか
- 既存データとの不整合（古いスキーマの articles が残る想定）

### Failure Modes

- 外部サービス失敗（YouTube / Claude / OpenAI / Gmail / Neon）の伝播経路
- transaction 境界と副作用のロールバック
- migration 適用失敗時のリカバリ
- Gmail OAuth refresh_token 失効
- pgvector index 不存在時の seq scan 性能

### Regression Risks

変更が触っていない既存フローへの間接影響を挙げる:

- 共有 fetcher（`fetchers/youtube.py` / `fetchers/rss.py`）を利用する他経路
- `db.py` の関数を共有する Stage 間
- `sources.yaml` の構造変更が全 fetcher に波及するか
- `articles` スキーマ変更が click endpoint と batch 両方に波及するか
- HMAC 署名フォーマット変更が既配布メールリンクを無効化

## Output Format

```text
# Mode
- pre-implementation | post-implementation

# Test Scope
- Unit | Integration | Manual workflow_dispatch (複数可)

# Why (このスコープを選んだ根拠)

# Hibi Priority Checks

# Edge Cases

# Failure Modes

# Regression Risks

# Existing Tests To Update

# New Tests To Add

# Gaps (実装後モードで不足している観点)

# Recommendation
- ready to implement | needs test update | ready to merge | add tests before merge
```

### Output Style

- 各項目は 1〜2 行
- 該当しないセクションは省略する
- 既存テストのパスを示せる場合は示す（例: `tests/fetchers/test_youtube.py`）
- `Recommendation` はモードに応じて選ぶ（pre なら ready/needs、post なら ready/add）
