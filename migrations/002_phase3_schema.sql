-- ================================================================
-- Phase 3 schema additions
--   * articles.user_id  (multi-tenant 化への布石)
--   * articles.category (source_metrics_30d で GROUP BY するため)
--   * clicks            (メールリンクのクリック記録)
--   * source_metrics_30d VIEW (sources.yaml のメンテ判断用)
--
-- 2 回流しても壊れないよう、全部 idempotent に書く。
-- ================================================================

-- 1. articles への列追加 ------------------------------------------------

-- multi-tenant 化の布石。当面は kazuki 固定の UUID を default に。
ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS user_id uuid NOT NULL
    DEFAULT '00000000-0000-0000-0000-000000000001';

-- fetcher は既に unified item に `category` を入れているが、DB には落ちていなかった。
-- VIEW で GROUP BY するために永続化する。nullable（既存行は NULL）。
ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS category text;

CREATE INDEX IF NOT EXISTS articles_user_id_idx ON articles (user_id);


-- 2. clicks テーブル ----------------------------------------------------

CREATE TABLE IF NOT EXISTS clicks (
    id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    article_id  uuid NOT NULL REFERENCES articles (id) ON DELETE CASCADE,
    user_id     uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000001',
    clicked_at  timestamptz NOT NULL DEFAULT NOW(),
    user_agent  text,
    ip_hash     text   -- SHA-256(ip || daily_salt) を想定。salt は D で扱う。
);

CREATE INDEX IF NOT EXISTS clicks_article_id_idx     ON clicks (article_id);
CREATE INDEX IF NOT EXISTS clicks_user_clicked_idx   ON clicks (user_id, clicked_at DESC);


-- 3. source_metrics_30d VIEW -------------------------------------------

-- sources.yaml メンテ用。直近30日での配信件数・平均要約長・最終配信日時を
-- ソース別 / カテゴリ別で見られる。`psql -c "select * from source_metrics_30d"`
-- で mute 判断や品質劣化の検知に使う。
CREATE OR REPLACE VIEW source_metrics_30d AS
SELECT
    source_type,
    source_name,
    category,
    COUNT(*)                  AS delivered,
    AVG(LENGTH(summary))::int AS avg_summary_len,
    MIN(created_at)           AS first_delivered,
    MAX(created_at)           AS last_delivered
FROM articles
WHERE created_at > NOW() - INTERVAL '30 days'
GROUP BY source_type, source_name, category
ORDER BY delivered DESC;
