-- Run this once in Supabase SQL Editor.
-- It enables pgvector and creates the persistent RAG knowledge store.

create extension if not exists vector;

create table if not exists public.knowledge_chunks (
  chunk_id text primary key,
  source text not null,
  heading text not null,
  content text not null,
  embedding vector(768) not null,
  updated_at text not null
);

alter table public.knowledge_chunks enable row level security;

create index if not exists knowledge_chunks_embedding_idx
on public.knowledge_chunks
using ivfflat (embedding vector_cosine_ops)
with (lists = 100);

analyze public.knowledge_chunks;
