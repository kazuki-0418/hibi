-- ================================================================
-- Better Auth schema (Issue #103, child of epic #109)
--
-- Better Auth (https://better-auth.com) を Astro web app (#104) で
-- 動かすために必要な 4 テーブルを additive で追加する。
--
--   * user          — 認証ユーザー本体
--   * session       — ログイン session (cookie の token で引く)
--   * account       — OAuth provider / password credential 等の認証手段
--   * verification  — メール認証トークン等の一時データ
--
-- ## 設計判断
--
--   * テーブル名 user / session は PostgreSQL の予約語に該当するため、
--     一貫性を保ち事故を防ぐ目的で 4 テーブルすべて DDL 内で "..."
--     で囲む (reserved-word safety)。
--   * 列名は snake_case。Better Auth のデフォルト camelCase は app 側
--     (#104) の field mapping で snake_case に対応付ける。
--     SQL 側で camelCase を許容しない。
--   * id 型は UUID。既存 articles.user_id / clicks.user_id (kazuki 固定
--     UUID) と型を揃え、multi-tenant 化 (epic #111) で参照を繋ぎ替える
--     ときに型差分が出ないようにする。
--   * session.user_id / account.user_id は "user"(id) を FK で参照し、
--     ON DELETE CASCADE。ユーザー削除で依存 row を同時に消す。
--   * session.token は UNIQUE (Better Auth は token で session を引くため)。
--   * account(provider_id, account_id) は複合 UNIQUE
--     (同一 provider 上の同一 account を 2 user に紐付けない)。
--   * verification.identifier は非 UNIQUE index (同一 identifier に対し
--     再発行で複数 token が並ぶケースがあるため UNIQUE にしない)。
--
-- ## 非対応 (このマイグレーション外)
--
--   * articles.user_id / clicks.user_id の動的化は multi-tenant epic #111
--   * user.subscribed_at の追加は #112
--   * RLS / Row Level Security は今は導入しない
--   * Better Auth Astro app / CLI config / field mapping の宣言は #104
--   * legacy fixed UUID への seed user 投入 (旧 #108 は close 済)
--
-- 2 回流しても壊れないよう全部 idempotent (IF NOT EXISTS)。
-- 手動 apply: Neon SQL Editor で実行する (#36 / #54 と同じ運用)。
--
-- 関連: epic #109 / issue #103 / Astro app #104
-- ================================================================


-- 1. user テーブル ------------------------------------------------------
--
-- 認証ユーザーの本体。`user` は PostgreSQL の予約語なので、すべての
-- DDL 参照で必ず "user" と二重引用符で囲む。

CREATE TABLE IF NOT EXISTS "user" (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT        NOT NULL,
    email           TEXT        NOT NULL UNIQUE,
    email_verified  BOOLEAN     NOT NULL DEFAULT false,
    image           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);


-- 2. session テーブル ---------------------------------------------------
--
-- ログイン session。Better Auth は cookie の `token` 値で session を
-- 引くため UNIQUE index 必須。親 user 削除で CASCADE 削除。

CREATE TABLE IF NOT EXISTS "session" (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID        NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    token       TEXT        NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    ip_address  TEXT,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS session_token_uidx ON "session" (token);
CREATE INDEX        IF NOT EXISTS session_user_id_idx ON "session" (user_id);


-- 3. account テーブル ---------------------------------------------------
--
-- 認証手段 (OAuth provider / password credential 等)。
-- (provider_id, account_id) を複合 UNIQUE にすることで、同一 provider 上の
-- 同一 account を 2 ユーザーに紐付けることを防ぐ。

CREATE TABLE IF NOT EXISTS "account" (
    id                        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id                   UUID        NOT NULL REFERENCES "user"(id) ON DELETE CASCADE,
    account_id                TEXT        NOT NULL,
    provider_id               TEXT        NOT NULL,
    access_token              TEXT,
    refresh_token             TEXT,
    access_token_expires_at   TIMESTAMPTZ,
    refresh_token_expires_at  TIMESTAMPTZ,
    id_token                  TEXT,
    scope                     TEXT,
    password                  TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS account_provider_account_uidx
    ON "account" (provider_id, account_id);
CREATE INDEX        IF NOT EXISTS account_user_id_idx
    ON "account" (user_id);


-- 4. verification テーブル ----------------------------------------------
--
-- メール認証トークン等の一時データ。identifier (email 等) で検索するため
-- 非 UNIQUE index を付ける。同一 identifier に対し再発行で複数 token が
-- 並ぶケースがあるため UNIQUE にはしない。

CREATE TABLE IF NOT EXISTS "verification" (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    identifier  TEXT        NOT NULL,
    value       TEXT        NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS verification_identifier_idx
    ON "verification" (identifier);
