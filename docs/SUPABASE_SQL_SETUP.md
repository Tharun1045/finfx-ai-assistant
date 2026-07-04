# Supabase SQL Setup

The SQL scripts in `scripts/` are the source of truth. This document explains when to run them and what each one is for.

## Do You Need To Run SQL Manually?

For local SQLite development, no.

For Supabase/Postgres, yes, run the scripts once in Supabase SQL Editor.

Why:

- The app can auto-create normal SQL tables when the database connection is available.
- Supabase pgvector setup is clearer when the extension, vector tables, and vector indexes are created manually.
- RLS is explicitly enabled in the scripts.
- Embedding rows should be created by the app, not pasted manually.

## Scripts To Run

Run these in Supabase SQL Editor:

```text
scripts/supabase_pgvector.sql
scripts/supabase_schema_pgvector.sql
scripts/supabase_llm_usage.sql
```

### `scripts/supabase_pgvector.sql`

Creates the document RAG vector table:

```text
knowledge_chunks
```

Used for customer-facing knowledge retrieval over files in:

```text
data/knowledge/
```

### `scripts/supabase_schema_pgvector.sql`

Creates the Admin SQL schema RAG vector table:

```text
schema_chunks
```

Used to retrieve relevant table schema before asking the LLM to generate SQL.

### `scripts/supabase_llm_usage.sql`

Creates AI observability tables:

```text
llm_usage_logs
assistant_question_logs
```

Used to track LLM calls, embedding calls, token estimates, question latency, route mode, and `question_id` links.

## What The App Can Create Automatically

The app can create these normal SQL tables automatically:

```text
transfers
llm_usage_logs
assistant_question_logs
```

Still, for a clean Supabase setup, running the scripts manually is recommended.

## What The App Seeds Automatically

Do not manually insert vector embeddings.

After running the scripts, start FastAPI and call:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/knowledge/vector/index" -Method Post
Invoke-RestMethod "http://127.0.0.1:8000/api/sql/schema-vector/index" -Method Post
```

These endpoints generate embeddings with local Ollama and upsert rows into:

```text
knowledge_chunks
schema_chunks
```

## Status Checks

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/database/status"
Invoke-RestMethod "http://127.0.0.1:8000/api/knowledge/vector/status"
Invoke-RestMethod "http://127.0.0.1:8000/api/sql/schema-vector/status"
```

## Updating Existing Supabase Tables

The scripts use `create table if not exists`, `create index if not exists`, and `add column if not exists` where needed, so they are safe to rerun during development.

If you edit knowledge documents or schema chunk text, rerun the relevant index endpoint.
