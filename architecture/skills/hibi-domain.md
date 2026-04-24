# hibi-domain

Hibi の現行ドメイン事実を固定するスキル。
実装・レビュー・計画・バッチ・FastAPI すべての作業で利用する。

実装手順ではない。提案書でもない。将来アーキテクチャ文書でもない。

---

## Core Domain Facts

- Hibi は汎用ニュースリーダーではない。YouTube/RSS aggregator + curator
- 学習信号は **クリックのみ**。評価UI（👍/👎、星評価）は意図的に不在
- pipeline は 3-stage + ranking 構成。各 Stage は前段の出力にのみ依存
- ranking 反映は **次回バッチ実行時**。クリックは即座に centroid を更新しない
- embedding 対象は `title + summary`。本文ではない
- cold start: `clicks_in_30d < 5` で純ランダム、30 件で full weight
- score 式: `sim × 0.7 × weight + rand() × (1 − 0.4 × weight)`、weight = `min(1, clicks_in_30d / 30)`
- 現行の事実は以下のダイアグラムから確認する:
  - `architecture/diagrams/pipeline-flow.mmd`
  - `architecture/diagrams/data-model.mmd`
  - `architecture/diagrams/click-tracking-flow.mmd`

---

## Pipeline Boundary Constraints

- Stage A は **メタデータのみ** 取得する。transcript / 本文取得を Stage A に混ぜない
- Stage B のフィルタ条件は `published_at >= now() - 14 days` AND `is_sent = false`
- Stage B は ranking で上位 N 件を抽出。N の現行値は 5（旧 10 から変更済み）
- Stage C は抽出済み記事のみ transcript + 要約 + Neon 保存
- 各 Stage は前段の出力に対してのみ動作する。Stage C が Stage A の生メタデータを直接読まない
- workflow timeout は 10 分以内。Stage B の N を増やすときは Stage C のランタイムを試算する

---

## Source Configuration Constraints

- ソースは `sources.yaml` + git で管理。`sources` テーブルは作らない
- ソース健全性は `source_metrics_30d` VIEW で確認。テーブル化は UI 実装時まで保留
- `enabled: false` のソースは fetcher が除外する。コードコメントアウトで無効化しない
- ソース追加は yaml 編集 + `scripts/verify_channels.py` での実在検証が必須
- LLM に `channel_id` を生成させない。ハルシネーション率が高い。名前と URL のみ LLM、ID は API 検証

---

## Click Tracking Constraints

- クリック URL は HMAC 署名必須。`?a=<article_id>&sig=<HMAC>`
- 署名なし / 改ざんリクエストは `clicks` に記録しない（fails-open でリダイレクトのみ）
- bot filter は `user_agent` で判定。GoogleImageProxy 等のプリフェッチは除外
- `clicks.user_id` は当面 kazuki 固定 UUID
- HMAC シークレット rotation は既配布メールのリンクを無効化する。明示的なメンテナンス窓が必要

---

## Embedding Constraints

- embedding model: OpenAI `text-embedding-3-small`、1536 次元
- model 切り替えは全件 backfill が必要。コストは数セント水準だが運用窓を取る
- embedding 失敗時は `sim = 0` で jitter のみ効く fails-open 設計。ranking を停止しない
- `articles.embedding` は pgvector カラム。別テーブル `embeddings` は作らない
- embedding 計算は Stage B の ranking 直前に batch 投入。事前計算しない

---

## State and Persistence Constraints

- `articles.is_sent` は配信完了の唯一の真実。重複送信防止は `content_id` UK + `is_sent` で判定
- `clicks` は append-only。論理削除カラムを足さない。multi-tenant 化時に `user_id` で論理分離
- migrations は手動実行。`migrations/NNN_*.sql` を番号順に Neon SQL Editor で適用
- 破壊的変更（DROP COLUMN、ALTER TYPE）は別 PR + 運用窓で実行。同 PR に DDL と DML を混ぜない
- backfill が必要な migration は別 PR に分ける

---

## Delivery Constraints

- 配信は Gmail API、OAuth2 refresh_token 方式
- OAuth consent screen は **Production** 必須。Testing は 7 日で refresh_token 失効
- メール本文の URL はすべて HMAC 署名付きトラッキング URL に置換
- bounce 処理 / unsubscribe link / Privacy Policy は multi-tenant 化前に必須。1 人運用では不要

---

## Known Not-Implemented Areas

以下は計画中。現行挙動として扱わない:

- Astro UI（Phase 3 後半）
- multi-tenant（`clicks.user_id` の動的化）
- source mute 機能
- 評価 UI（👍/👎、星評価）— 明示的に作らない方針
- LangGraph による agent 化
- Stripe / 課金
- カテゴリ別タブ、検索、お気に入り
- pgvector の HNSW index（現行は seq scan で十分）

---

## Do Not Assume

- 汎用ニュースアプリの慣例（カテゴリタブ、検索、お気に入り、共有）を持ち込まない
- `articles.rating` のような評価フィールドが存在すると仮定しない
- multi-user が動いていると仮定しない
- Cloudflare Workers で動くと仮定しない（Pyodide 非互換）
- async / 並行処理が入っていると仮定しない（YAGNI 判断済み）
- ORM が入っていると仮定しない。psycopg 3.x + 生 SQL のみ
- Alembic が入っていると仮定しない。手動 migration
- LangGraph / multi-agent が現行で動いていると仮定しない
- Astro UI が存在すると仮定しない（Phase 3 後半）
- search.list で動的にチャンネルを取得していると仮定しない（quota 制約で playlistItems.list のみ）