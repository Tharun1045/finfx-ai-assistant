# FinFX AI Assistant

FinFX AI Assistant is a fintech-style AI and data engineering portfolio project. It combines live FX rates, transfer capture, Supabase/Postgres reporting, local Ollama LLM workflows, document RAG, schema RAG, and AI observability in one FastAPI application.

The project is designed for learning and demonstration. All sample data and knowledge documents are synthetic.

## What It Does

- Shows live and historical FX rates using the Frankfurter public API.
- Converts currencies and shows both full converted amount and 1-unit exchange rate.
- Lets a user create transfer records and persist them to SQL.
- Uses Supabase/Postgres for transfer records, LLM usage logs, question logs, document vectors, and schema vectors.
- Provides a customer-facing AI assistant for FX, transfer FAQ, policy, compliance, and support questions.
- Provides Admin Reports with a transfer dashboard and AI observability dashboard.
- Uses local Ollama for chat/planning and embeddings.
- Supports optional OpenAI or Anthropic chat providers while keeping embeddings local.
- Uses pgvector for persistent document RAG and persistent Admin SQL schema RAG.

For LLM/RAG concepts, including how Ollama differs from hosted LLM APIs such as OpenAI and Claude, see:

```text
docs/AI_RAG_LLM.md
```

For step-by-step flow charts showing Ask AI, RAG, vector search, LLM calls, and Admin SQL, see:

```text
docs/AI_FLOW_CHARTS.md
```

## Tech Stack

- Backend: Python, FastAPI, Pydantic
- Frontend: HTML, CSS, JavaScript
- Database: SQLite for local fallback, Supabase/Postgres for persistent records
- Vector store: Supabase pgvector
- Local AI: Ollama
- Default chat model: `llama3.2:3b`
- Default embedding model: `nomic-embed-text`
- Testing: Pytest
- FX provider: Frankfurter, with optional Alpha Vantage and FRED extensions

## Third-Party Tools And Services

Official links:

- [FastAPI](https://fastapi.tiangolo.com/) - Python API framework.
- [Supabase](https://supabase.com/) - hosted Postgres database used for persistent SQL data.
- [Supabase pgvector](https://supabase.com/docs/guides/database/extensions/pgvector) - vector search extension used for document RAG and schema RAG.
- [Ollama](https://ollama.com/) - local LLM runtime used for chat, planning, SQL generation, and embeddings.
- [Frankfurter](https://frankfurter.dev/) - free public FX rates API used for live and historical exchange rates.
- [OpenAI Platform](https://platform.openai.com/docs/) - optional cloud LLM provider.
- [Claude / Anthropic Docs](https://docs.anthropic.com/) - optional cloud LLM provider.
- [Alpha Vantage](https://www.alphavantage.co/documentation/) - optional FX/time-series provider.
- [FRED API](https://fred.stlouisfed.org/docs/api/fred/) - optional macroeconomic data provider.
- [Pytest](https://docs.pytest.org/) - Python test framework.

## Project Structure

```text
finfx-ai-assistant/
  app/
    api/                 FastAPI routes
    core/                settings and environment config
    models/              request schemas
    services/            FX, RAG, SQL, transfer, database, and LLM services
    static/              browser UI
  data/
    knowledge/           synthetic markdown policy and FAQ docs
    fx_rates.json        local fallback rates
    transactions.csv     synthetic demo transaction data
  docs/
    AI_RAG_LLM.md        LLM, RAG, vector, and knowledge architecture
    AI_FLOW_CHARTS.md    Ask AI and Admin SQL flow charts
    architecture.md      system architecture notes
    roadmap.md           future roadmap
  scripts/
    supabase_pgvector.sql
    supabase_schema_pgvector.sql
    supabase_llm_usage.sql
  tests/
    test_services.py
```

## Setup Checklist

Start here if you are setting up the project for the first time:

```text
docs/LOCAL_SETUP.md
```

It lists required software, official URLs, Ollama setup commands, `.env` setup, Supabase setup, vector indexing commands, and common issues.

## Local Setup

Use Python 3.12, 3.13, or 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Start Ollama and pull the recommended local models:

```powershell
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

Create a local `.env` from `.env.example`:

```powershell
copy .env.example .env
```

Start the API:

```powershell
python -m uvicorn app.main:app --reload
```

Open:

- App: http://127.0.0.1:8000
- API docs: http://127.0.0.1:8000/docs

## Environment Variables

The app can run locally with SQLite, or connect to Supabase/Postgres.

```text
APP_NAME=FinFX AI Assistant
ENVIRONMENT=local
DATABASE_URL=sqlite:///./finfx.db
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=llama3.2:3b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

Optional provider keys:

```text
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
ALPHA_VANTAGE_API_KEY=
FRED_API_KEY=
```

Create a local `.env` file to save these values when running the project on your own machine:

```powershell
copy .env.example .env
```

Then edit `.env` and add only the keys you want to use:

```text
OPENAI_API_KEY=your_openai_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_key_here
FRED_API_KEY=your_fred_key_here
```

These keys are optional. The project can still run locally with Ollama and Frankfurter without paid API keys.

Do not commit `.env`. It is ignored by Git so each developer can keep their own local database URL and API keys private.

## Supabase Setup

Run these scripts in the Supabase SQL Editor when using Supabase/Postgres:

```text
scripts/supabase_pgvector.sql          document knowledge vectors
scripts/supabase_schema_pgvector.sql   Admin SQL schema vectors
scripts/supabase_llm_usage.sql         persisted LLM and question logs
```

The SQL scripts are the source of truth. Setup notes are in:

```text
docs/SUPABASE_SQL_SETUP.md
```

Do you need to run SQL manually?

- For a quick local SQLite demo: no.
- For Supabase with pgvector: yes, run the SQL scripts once in Supabase SQL Editor.
- The app can auto-create normal SQL tables such as `transfers`, `llm_usage_logs`, and `assistant_question_logs`.
- The vector extension, vector tables, and vector indexes are better created manually in Supabase SQL Editor.
- After the tables exist, the app indexes data through API endpoints; do not manually insert embeddings.

Then start FastAPI and index the vector stores:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/knowledge/vector/index" -Method Post
Invoke-RestMethod "http://127.0.0.1:8000/api/sql/schema-vector/index" -Method Post
```

Check status:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/knowledge/vector/status"
Invoke-RestMethod "http://127.0.0.1:8000/api/sql/schema-vector/status"
Invoke-RestMethod "http://127.0.0.1:8000/api/database/status"
```

## Main UI Areas

The main dashboard includes:

- AI assistant
- Live FX tool
- Live exchange-rate table
- Customer transfer form
- Provider status
- In-memory LLM usage summary

Admin Reports includes:

- Transfer dashboard
- Natural-language SQL analytics
- AI observability dashboard
- Persisted LLM usage logs
- Persisted assistant question logs

The Admin Reports login is demo-only and uses fixed frontend credentials. It is not production authentication.

## Sample Questions

Customer AI assistant:

```text
my payment failed, what to do, how to contact support
what documents are required for a high value transfer?
why is my payment delayed?
what is suspicious activity?
what is the GBP to INR rate?
gbp/inr trend in last 30 days
will GBP/INR increase next month?
```

Admin Reports SQL:

```text
last transaction
recent transfers
transfer summary
gbp to inr last payment
GBP TO INR HIGHEST TRANSFER
highest GBP amount transferred
which llm provider used most tokens?
which assistant route had the slowest latency?
show recent assistant questions
```

## Testing

```powershell
python -m pytest tests\test_services.py --basetemp .pytest-tmp
python -m compileall app
node --check app\static\app.js
node --check app\static\reports.js
```

## GitHub Safety Checklist

Before pushing:

- Confirm `.env` is not staged.
- Confirm `finfx.db` is not staged.
- Confirm `.venv/`, `.pytest_cache/`, and `.pytest-tmp/` are not staged.
- Stage only source, docs, scripts, tests, and `.env.example`.
- Use `.env.example` for placeholders only.

Useful commands:

```powershell
git status --short
git add .gitignore .env.example README.md app data docs scripts tests requirements.txt
git status --short
```

## Disclaimer

This is a learning and portfolio project. It is not financial advice, not a production compliance system, and not suitable for real customer payments without proper security, audit, data protection, and regulatory review.
