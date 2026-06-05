# hibi-domain

Hibi の現行ドメイン事実を固定するスキル。
実装・レビュー・計画・バッチ・FastAPI すべての作業で利用する。

実装手順ではない。提案書でもない。将来アーキテクチャ文書でもない。

---

## Core Domain Facts

- Hibi は汎用ニュースリーダーではない。RSS aggregator + curator（KAZ-214: YouTube ソース撤去済み）
- 学習信号は **クリックのみ**。評価UI（👍/👎、星評価）は意図的に不在
- pipeline は 3-stage + ranking 構成。各 Stage は前段の出力にのみ依存
- ranking 反映は **次回バッチ実行時**。クリックは即座に centroid を更新しない
- embedding 対象は `title + summary`。本文ではない
- cold start: `clicks_in_30d < 5` では Obsidian active project の **goal centroid** でランキング（KAZ-202）。goal も無いときのみ純ランダム
- digest v2 (KAZ-204): allowlist は `monogatari` / `roamlore` のみ（`hibi` 自身は対象外）。conditioning は各 `10_projects/<slug>/` の `decisions.md` + `strategy.md` + `status.md` を `goals.loader.read_active_note` で読む（`status: active` / `hibi-active: true` 必須、見出し完全一致セクションのみ、ファイル mtime 降順 + 8000字 cap）。**プロジェクト別 centroid**（クリック blend なし）。類似度 `< 0.28` は novelty レーン。有用記事は `30_raw/hibi/capture/`、digest 満杯時の novelty は `30_raw/hibi/inbox/`（1 件/日）。centroid は vault `.hibi/goal_centroid_cache.json` または `HIBI_GOAL_CACHE_DIR`
- `goals.loader`（KAZ-202 fallback）も同一 allowlist + frontmatter + 見出し規約。6000字 cap 前にノート mtime 降順
- 本番 Actions は `Obsidan-workspace` を sparse-checkout し `OBSIDIAN_VAULT_ROOT` を渡す（`OBSIDIAN_VAULT_PAT` secret）。`HIBI_GOALS_OPTIONAL=1` は本番 daily-news では使わない（[docs/obsidian-vault-ci.md](../../docs/obsidian-vault-ci.md)）
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
- Stage C: RSS は本文 + 要約 + Neon 保存（robots disallow / 本文未取得時は link-only）。要約は `---要約---`（DB）と `---関連---`（メール `learning` 行）を分離。challenge 枠 1–2 件常設。v2 時は `---関連---` を `→ {Monogatari|RoamLore}:` で始める適用注記。メール並びは digest plan 順（v2）または `sources.yaml` 順（v1 fallback）
- 英語産出 v0 (KAZ-203): digest に 1 区画だけ英語プロンプト + Claude 貼り付け依頼文（返信ループ・自動採点は非スコープ）
- 各 Stage は前段の出力に対してのみ動作する。Stage C が Stage A の生メタデータを直接読まない
- workflow timeout は 10 分以内。Stage B の N を増やすときは Stage C のランタイムを試算する

---

## Source Configuration Constraints

- ソースは `sources.yaml` + git で管理。`sources` テーブルは作らない
- ソース健全性は `source_metrics_30d` VIEW で確認。テーブル化は UI 実装時まで保留
- `enabled: false` のソースは fetcher が除外する。コードコメントアウトで無効化しない
- ソース追加は yaml 編集 + `scripts/verify_feeds.py` での feed 検証が必須
- digest パイプラインは `type: rss` のみ。`YOUTUBE_API_KEY` は不要

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

## Web Frontend Constraints

- Web archive ( edition page / archive / landing ) は **Astro** で実装。配置は `web/` ディレクトリ
- Build target は `web/dist/`。**Cloudflare Pages** で `hibi-news.com` から配信
- `design-system/colors_and_type.css` は SSoT。Astro 側で `<link>` で直接参照し、トークンを再宣言しない
- データ取得は **build-time**。Python パイプライン (`daily_news.py` etc.) が `web/src/content/editions/*.json` に dump、Astro Content Collection で読む。Astro から DB へ実行時アクセスしない
- 言語は TypeScript。`tsconfig.json` の strict は有効化する

---

## Known Not-Implemented Areas

以下は計画中。現行挙動として扱わない:

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