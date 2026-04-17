-- Phase 3 の pgvector に備えて拡張を有効化
create extension if not exists vector;

create table if not exists articles (
  id           uuid primary key default gen_random_uuid(),
  source_type  text not null,
  source_name  text not null,
  content_id   text not null unique,
  title        text not null,
  url          text not null,
  summary      text,
  published_at timestamptz,
  sent_at      timestamptz,
  created_at   timestamptz default now()
  -- embedding vector(1536) は Phase 3 (#9) で追加
);

create index if not exists idx_articles_content_id on articles (content_id);
create index if not exists idx_articles_created_at on articles (created_at desc);
