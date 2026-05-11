-- ================================================================
-- articles.edition_id を NOT NULL に昇格 (PR3 of #51 split)
--
-- 前提 (PR3 を merge する前に production Neon で確認済み):
--   * migration 004 適用済み (editions テーブル + articles.edition_id カラム存在)
--   * scripts/backfill_editions.py --apply 実行済み
--   * SELECT count(*) FROM articles WHERE edition_id IS NULL  → 0
--   * SELECT count(*) FROM editions                            → 16
--
-- ALTER TABLE ... SET NOT NULL は ACCESS EXCLUSIVE lock を取って
-- 全行を scan する。articles 規模 (現状 148 行) では一瞬で完了。
-- NULL が 1 件でも残っていた場合 ALTER は失敗するので、その場合は
-- backfill 再実行してからこの migration を再 apply すること。
--
-- 関連: epic #39 / issue #51 / PR1=#61 (DDL) / PR2=#62 (backfill script)
-- ================================================================

ALTER TABLE articles
    ALTER COLUMN edition_id SET NOT NULL;
