-- ================================================================
-- Editions schema (DDL only — PR1 of #51's 3-PR split)
--
--   * `editions` table — 1 メール / 1 web ページ = 1 edition の集約単位
--     `issue_no` は配信日順に決定的に振る（auto-increment ではない）。
--     `standfirst` / `daily_title` は #T4-3 で埋める。
--     `sources_scanned` は #T4-2 で埋める。
--
--   * `articles.edition_id` — 既存 articles を edition に紐付ける
--     nullable FK。backfill は別 migration / scripts/ で行い、
--     全件が埋まったことを確認した後、別 PR で NOT NULL 化する想定。
--     ここを直接 NOT NULL にすると既存行が無 edition で残ったまま
--     migration が走るので、backfill との順序が乱れる。
--
-- 2 回流しても壊れないよう全部 idempotent。
--
-- 同日複数配信を禁ずる `editions.date UNIQUE` を入れている。将来
-- 「号外」要件が出た場合はこの UNIQUE を外し、(date, issue_no) の
-- 複合 UNIQUE などに切り替える別 migration を切ること。
--
-- 関連: epic #39 / issue #51
-- ================================================================

CREATE TABLE IF NOT EXISTS editions (
    issue_no        INTEGER     PRIMARY KEY,
    date            DATE        NOT NULL UNIQUE,
    standfirst      TEXT,
    daily_title     TEXT,
    sources_scanned JSONB,
    generated_at    TIMESTAMPTZ DEFAULT now()
);

-- articles に nullable FK を追加。backfill 後の NOT NULL 化は別 PR。
ALTER TABLE articles
    ADD COLUMN IF NOT EXISTS edition_id INTEGER REFERENCES editions(issue_no);

CREATE INDEX IF NOT EXISTS articles_edition_id_idx ON articles (edition_id);
