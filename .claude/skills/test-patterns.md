# test-patterns

Hibi でテストを追加・更新する際のガイドスキル。
変更した挙動にフォーカスし、広範な書き直しを強制しない。

## Core Rules

- まず既存テストを確認し、必要なら更新する。毎回新規作成を前提にしない
- 変更した挙動に対して最小限のスコープでテストする
- 関連性のある正常系・失敗系・意味のある境界条件をカバーする
- 表面的なアサーションより挙動・契約・quota 影響・状態一貫性を優先する
- 計画中の未実装機能（multi-tenant / Astro UI / 評価UI / LangGraph）を現行動作としてテストしない
- 型ヒント必須。`Any` / `# type: ignore` で逃げない

## Scope Selection

### Unit

以下に使う:

- 純粋なロジック（HMAC 署名検証 / centroid 計算 / cold start weight）
- バリデーションルール（sources.yaml の構造）
- mapper / helper（VideoMetadata → Article 変換等）
- 独立した summarize プロンプト構築

### Integration

以下に使う:

- fetcher と DB の連携（`fetchers/` ↔ `db.py`）
- Stage A → B → C の境界
- pgvector を含むクエリ
- click endpoint と HMAC 検証 + DB 書き込みの統合
- migration 適用後の DB 状態

### Manual workflow_dispatch

以下に使う（Playwright E2E の代替）:

- 3-stage pipeline 全体のドライラン
- Gmail 配信を含むエンドツーエンド確認
- 本番 Neon に近い環境での動作確認

デフォルトで広範な E2E を実行しない。GitHub Actions workflow_dispatch + ログ確認で代替する。

## Hibi Priority Checks

関連する場合に優先して確認する:

- Pipeline stage 境界（Stage A に transcript が混入していない / Stage B のフィルタ条件）
- HMAC 署名検証 / bot filter 通過判定
- `articles.is_sent` 整合性（重複送信防止の唯一の真実）
- `clicks` append-only 制約
- API quota（YouTube `playlistItems.list` 2 units / `search.list` 100 units の区別）
- Cold start 挙動（`clicks_in_30d < 5` で純ランダム、30 件で full weight）
- Embedding 失敗時の fails-open（`sim = 0`）
- 14日窓 + `is_sent=false` フィルタの境界

## Mocking Guidance

- 既存の `conftest.py` の fixtures と mocks を再利用する
- 外部サービス（YouTube / Claude / OpenAI / Gmail / Neon）は必要最小限のスコープにのみモックする
- 実際の挙動で確認すべきドメイン挙動を過度にモックしない
- pgvector を含むクエリは pytest-postgres or in-memory で本物の SQL を実行する
- 本番 Neon を test target にしない
- HMAC 署名検証は実際の hmac モジュールで動かす（モックしない）

## Test Update Guidance

挙動が変わった場合は以下も更新要否を確認する:

- 既存の unit tests
- integration tests
- migration による DB 状態変更を反映する fixtures
- sources.yaml の構造変更を反映する fixtures
- HMAC 署名フォーマット変更時の固定 sig 値
- 古い期待値を残さない

## Output Format

```text
# Test Scope
# Why
# Existing Tests To Update
# New Tests To Add
# Risks Not Covered
```
