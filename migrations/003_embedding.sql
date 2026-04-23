-- ================================================================
-- Phase 3 embedding support
--   * pgvector extension (再確認; 001_init で既に作成済み)
--   * articles.embedding vector(1536)
--   * articles.embedding_model text — 後で model を差し替えた時の判別用
--   * HNSW index (cosine) — 近傍検索用。0.5.0+ の pgvector で利用可
--
-- 2 回流しても壊れないよう全部 idempotent。
-- Model: text-embedding-3-small (OpenAI)。次に差し替えるなら再 backfill する。
-- ================================================================

CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS embedding vector(1536);

ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS embedding_model text;

-- HNSW: Hierarchical Navigable Small World。件数が少ないうちは seq scan の
-- 方が速いが、index があっても害はなく、閾値越えた時点で planner が自動で
-- 切り替える。index 構築コストも ~100 行なら無視できる。
CREATE INDEX IF NOT EXISTS articles_embedding_hnsw
    ON articles USING hnsw (embedding vector_cosine_ops);
