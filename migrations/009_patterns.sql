-- ================================================================
-- patterns table (Issue #134 child — idea mining extractor)
--
-- 直近 7 日の `voices` (Apple iTunes ★1-4 customer reviews 等) を
-- Haiku でクラスタリングし、頻度 3+ の構造的ペインを週次で蓄積する
-- private テーブル。`extractor` (`idea_mining/extractor.py`) が
-- 火 / 木 / 土 03:00 UTC の cron で書き込む。
--
-- newspaper pipeline (`articles` / ranking / embedding / mailer /
-- archive) からは独立しており、daily newsletter / web archive にも
-- 露出しない (private のまま)。
--
-- ## カラム
--
--   * id                    — UUID PK
--   * week_iso              — `YYYY-Www` 形式の ISO week (e.g. '2026-W21')。
--                             extractor 実行時 UTC の
--                             `datetime.now(timezone.utc).isocalendar()` から生成。
--   * pain                  — pain の短文ラベル (Haiku が抽出)。
--   * categories            — pain の topical タグ群 (TEXT[])。
--   * frequency             — 同種 voice の出現回数 (Haiku がクラスタ集計)。
--                             frequency < 3 の pain は INSERT 前に extractor 側で
--                             捨てるため、ここに 1-2 の行は来ない。
--   * source_diversity      — distinct `voices.source` 数。
--                             < 2 のとき confidence が <= 0.5 に clamp される。
--   * representative_voices — UUID[]、pain を代表する `voices.id` の参照。
--                             FK 制約は張らない (voices は append-only で
--                             削除しない前提)。
--   * confidence            — REAL 0..1。source_diversity < 2 で <= 0.5 clamp。
--   * meta                  — JSONB: { model, raw_response_snippet, ... }。
--                             extractor が将来追加メタを足せるよう緩く。
--   * created_at            — 最初に INSERT された時刻。
--   * updated_at            — ON CONFLICT DO UPDATE で refresh される時刻。
--
-- ## 制約
--
--   * UNIQUE (week_iso, pain) — 同 (週, pain) で複数 row が出ないように。
--     extractor 側は `ON CONFLICT (week_iso, pain) DO UPDATE` で
--     frequency / source_diversity / representative_voices / confidence /
--     categories / meta / updated_at を refresh する。
--   * idx_patterns_week — 「特定週の全 pain」クエリ用。
--
-- ## 非対応 (out-of-scope)
--
--   * 古い week_iso の archive / truncate (歴史記録として残す)
--   * daily newsletter / archive への露出
--   * pgvector / embedding
--   * 評価 UI / multi-tenant 化
--
-- 2 回流しても壊れないよう全部 idempotent (IF NOT EXISTS)。
-- 手動 apply: Neon SQL Editor で実行する。
-- ================================================================

CREATE TABLE IF NOT EXISTS patterns (
    id                    uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    week_iso              text        NOT NULL,
    pain                  text        NOT NULL,
    categories            text[]      NOT NULL DEFAULT ARRAY[]::text[],
    frequency             integer     NOT NULL,
    source_diversity      integer     NOT NULL,
    representative_voices uuid[]      NOT NULL DEFAULT ARRAY[]::uuid[],
    confidence            real        NOT NULL,
    meta                  jsonb       NOT NULL DEFAULT '{}'::jsonb,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS patterns_week_iso_pain_uidx
    ON patterns (week_iso, pain);

CREATE INDEX IF NOT EXISTS idx_patterns_week
    ON patterns (week_iso);
