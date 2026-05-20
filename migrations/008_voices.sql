-- ================================================================
-- voices table (Issue #136, child of epic #134 — idea mining)
--
-- 製品レビューやユーザーの声 (UGC) を idea-mining 用に蓄積する
-- private テーブル。newspaper pipeline (`articles` / `is_sent` /
-- ranking / embedding) からは独立しており、daily newsletter / web
-- archive にも露出しない。
--
-- 初期 fetcher は Apple iTunes RSS (`idea_mining/fetchers/apple_rss.py`)
-- で、★1-4 のレビューのみを source='apple_rss' として insert する。
-- ★5 は INSERT 前にコード側で除外する (rating は meta JSONB に保持)。
--
-- ## カラム
--
--   * id          — UUID PK
--   * source      — fetcher 名 (e.g. 'apple_rss')。将来 Reddit / HN を
--                   追加するときは別 source 値で並列に積む。
--   * source_id   — fetcher 内で一意な ID (Apple RSS の review id)。
--   * posted_at   — レビュー投稿日時 (Apple feed の `updated`)。
--   * title       — レビュータイトル (Apple feed の `title`)。
--   * body        — レビュー本文 (Apple feed の `content`)。
--   * meta        — JSONB: { version, author, country, lang, rating, ... }。
--                   スキーマは fetcher ごとに緩く、追加フィールドは将来
--                   ALTER 無しで足せる。
--   * created_at  — 取り込み時刻。
--
-- ## 制約
--
--   * UNIQUE (source, source_id) — 再実行で同一レビューが重複しない
--     ように。INSERT 側は ON CONFLICT (source, source_id) DO NOTHING で
--     冪等にする。
--   * idx_voices_source_posted — 「最近のレビュー」クエリ用。
--
-- ## 非対応
--
--   * daily newsletter / archive への露出 (private のまま)
--   * embedding / pgvector 適用 (Issue #136 では out-of-scope)
--   * 評価 UI / 削除 UI
--   * `clicks.user_id` 連携 (1 人運用前提)
--
-- 2 回流しても壊れないよう全部 idempotent (IF NOT EXISTS)。
-- 手動 apply: Neon SQL Editor で実行する。
-- ================================================================

CREATE TABLE IF NOT EXISTS voices (
    id          uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    source      text        NOT NULL,
    source_id   text        NOT NULL,
    posted_at   timestamptz NOT NULL,
    title       text,
    body        text,
    meta        jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS voices_source_source_id_uidx
    ON voices (source, source_id);

CREATE INDEX IF NOT EXISTS idx_voices_source_posted
    ON voices (source, posted_at DESC);
