-- ================================================================
-- stats_summary VIEW (Issue #54)
--
-- design-system の web archive masthead が表示する 3 集計を 1 行に
-- まとめる。プレーン VIEW にしてあるので毎回再評価される (= 配信が
-- 走ればその場で最新値が見える)。pg トラフィックが増えたら materialized
-- view + cron refresh に昇格する想定。
--
--   * editions_count: editions テーブルの行数 = 配信回数。
--   * stories_count : articles テーブルの行数 = 累計記事数。
--   * sources_count : 直近 30 日に 1 件以上の記事を提供したソース数。
--                     issue #54 案 B「運用中の証明として強い」を採用。
--                     `articles.source_name` の DISTINCT を直近 30 日で
--                     取る。`editions.sources_scanned` JSONB ではなく
--                     articles 側を使うのは、JSONB は「fetch を試みた」
--                     の記録で、「実際に記事を提供した」とはズレるため。
--
-- 2 回流しても壊れないよう REPLACE で書く。
--
-- 関連: epic #39 / issue #54
-- ================================================================

CREATE OR REPLACE VIEW stats_summary AS
SELECT
    (SELECT count(*) FROM editions)::int AS editions_count,
    (SELECT count(*) FROM articles)::int AS stories_count,
    (
        SELECT count(DISTINCT source_name)
        FROM articles
        WHERE created_at >= now() - INTERVAL '30 days'
    )::int AS sources_count;
