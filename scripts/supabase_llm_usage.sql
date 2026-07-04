-- Optional: run this in Supabase SQL Editor if you want to create the LLM usage table manually.
-- The FastAPI app also creates this table automatically when the database connection is available.

create table if not exists public.llm_usage_logs (
  usage_id text primary key,
  created_at text not null,
  question_id text,
  call_type text not null,
  provider text not null,
  model text not null,
  success integer not null,
  input_tokens integer not null,
  output_tokens integer not null,
  total_tokens integer not null
);

alter table public.llm_usage_logs
add column if not exists question_id text;

alter table public.llm_usage_logs enable row level security;

create index if not exists llm_usage_logs_created_at_idx
on public.llm_usage_logs (created_at);

create index if not exists llm_usage_logs_question_id_idx
on public.llm_usage_logs (question_id);

create table if not exists public.assistant_question_logs (
  question_id text primary key,
  created_at text not null,
  surface text not null,
  question_text text not null,
  route_mode text,
  intent text,
  used_rag integer not null,
  used_sql integer not null,
  used_fx integer not null,
  citations_count integer not null,
  status text not null,
  latency_ms integer not null
);

alter table public.assistant_question_logs enable row level security;

create index if not exists assistant_question_logs_created_at_idx
on public.assistant_question_logs (created_at);
