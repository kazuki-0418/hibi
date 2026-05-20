-- ================================================================
-- candidates table (Issue #138 — B-Mode Ideator output)
--
-- `idea_mining/ideator.py` が patterns 1 件あたり 5-10 件のアイデア
-- 候補を Anthropic Opus (`claude-opus-4-7`) で生成し、本テーブルへ
-- INSERT する。profile/user-constraints + profile/negative-examples
-- を system prompt の先頭に注入する前提で、結果はバリデーション
-- (monetization enum / llm_moat_conditions enum / negative-example
-- キーワードフィルタ) を通過したものだけが本テーブルに入る。
--
-- newspaper pipeline (`articles` / ranking / embedding / mailer /
-- archive) には露出しない private テーブル。
--
-- ## カラム
--
--   * id                  — BIGSERIAL PK
--   * spot_id             — Phase 0 では nullable で null 固定。
--                           将来 `spots` テーブル導入時に FK 化する余地のみ残す。
--   * pattern_id          — patterns.id (uuid) への FK。NOT NULL。
--                           Issue 提示 DDL は BIGINT だったが、現行
--                           patterns.id は uuid のため uuid に揃える。
--   * name                — 候補プロダクト名。NOT NULL。
--   * one_liner           — 価値提案 1 行。
--   * target_user         — 具体ペルソナ。
--   * monetization        — subscription / one-time / affiliate / freemium / b2b
--                           CHECK 制約で値域固定。
--   * llm_moat_conditions — workflow / data / distribution / trust / network
--                           / physical / regulatory の text[] (≥1)。
--                           値域は Python 側でも再検証する (DB レベルでは
--                           array 要素 CHECK が組みづらいため設計上は
--                           Python が真の gate)。
--   * why_different       — negative-examples との差分説明。
--   * estimated_mvp_hours — MVP 工数 (integer, nullable)。
--   * killer_use_case     — 想定キラーユースケース。
--   * generated_at        — Ideator が候補を出した時刻 (DEFAULT now())。
--   * critic_verdict      — Issue #139 (Critic Agent) が後段で書き込む
--                           GO / PENDING / KILL。本 Issue では NULL のまま。
--   * critic_meta         — Critic の 5F / PESTLE / KILL flags の JSONB。
--                           本 Issue では NULL のまま。
--
-- ## 非対応 (out-of-scope; 本 Issue 範囲外)
--
--   * spot_id への FK 制約 (spots テーブル未導入のため bigint NULL のみ)
--   * critic_verdict / critic_meta への書き込み (Issue #139)
--   * candidates の dedupe / UNIQUE 制約
--   * pgvector / embedding
--   * UI / dashboard 露出
--
-- 2 回流しても壊れないよう全部 idempotent (IF NOT EXISTS / DROP
-- CONSTRAINT IF EXISTS)。手動 apply: Neon SQL Editor で実行する。
-- ================================================================

CREATE TABLE IF NOT EXISTS candidates (
    id                    bigserial   PRIMARY KEY,
    spot_id               bigint,
    pattern_id            uuid        NOT NULL REFERENCES patterns(id),
    name                  text        NOT NULL,
    one_liner             text,
    target_user           text,
    monetization          text,
    llm_moat_conditions   text[]      NOT NULL DEFAULT ARRAY[]::text[],
    why_different         text,
    estimated_mvp_hours   integer,
    killer_use_case       text,
    generated_at          timestamptz NOT NULL DEFAULT now(),
    critic_verdict        text,
    critic_meta           jsonb
);

CREATE INDEX IF NOT EXISTS idx_candidates_pattern_id
    ON candidates (pattern_id);

CREATE INDEX IF NOT EXISTS idx_candidates_generated_at
    ON candidates (generated_at DESC);

ALTER TABLE candidates
    DROP CONSTRAINT IF EXISTS candidates_monetization_chk;
ALTER TABLE candidates
    ADD CONSTRAINT candidates_monetization_chk
    CHECK (monetization IS NULL OR monetization IN (
        'subscription', 'one-time', 'affiliate', 'freemium', 'b2b'
    ));

ALTER TABLE candidates
    DROP CONSTRAINT IF EXISTS candidates_critic_verdict_chk;
ALTER TABLE candidates
    ADD CONSTRAINT candidates_critic_verdict_chk
    CHECK (critic_verdict IS NULL OR critic_verdict IN (
        'GO', 'PENDING', 'KILL'
    ));
