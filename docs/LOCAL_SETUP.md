# Local Setup

Use this checklist before starting FinFX AI Assistant locally.

## 1. Required Software

Install these first:

- Python: https://www.python.org/downloads/
- Git: https://git-scm.com/downloads
- Ollama: https://ollama.com/download
- VS Code, optional but recommended: https://code.visualstudio.com/

Recommended Python versions:

```text
Python 3.12, 3.13, or 3.14
```

## 2. Optional Accounts And API Keys

The project can run without paid API keys using:

- Ollama for local AI
- Frankfurter for free FX rates
- SQLite for local database fallback

Optional accounts:

- Supabase: https://supabase.com/
- OpenAI Platform: https://platform.openai.com/docs/
- Claude / Anthropic: https://docs.anthropic.com/
- Alpha Vantage: https://www.alphavantage.co/documentation/
- FRED API: https://fred.stlouisfed.org/docs/api/fred/

## 3. Clone And Open Project

```powershell
git clone <your-repo-url>
cd finfx-ai-assistant
code .
```

## 4. Create Python Virtual Environment

```powershell
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, run:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then reopen the terminal and activate again.

## 5. Install Ollama Models

Ollama lets this project run LLMs locally on your laptop. It starts a local API server, usually at:

```text
http://localhost:11434
```

In this project, Ollama is used for:

- local chat responses,
- JSON tool planning,
- Admin SQL generation,
- document embeddings,
- schema embeddings.

This is different from online LLM APIs such as OpenAI or Claude. Ollama runs models on your own machine and does not need an API key. OpenAI and Claude run in the cloud, usually give stronger models, and require API keys and internet access.

Official Ollama links:

- Download: https://ollama.com/download
- Model library: https://ollama.com/library
- API docs: https://github.com/ollama/ollama/blob/main/docs/api.md

Install notes:

- On Windows and macOS, download and run the installer from the Ollama download page.
- On Linux, the official download page shows an install command:

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

After installation, Ollama usually runs in the background and exposes its local API at `http://localhost:11434`.

Start Ollama, then run:

```powershell
ollama pull llama3.2:3b
ollama pull nomic-embed-text
```

Check Ollama:

```powershell
ollama --version
ollama list
```

Check the local embedding API:

```powershell
Invoke-RestMethod http://localhost:11434/api/embeddings `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"model":"nomic-embed-text","prompt":"What documents are required for a high value transfer?"}'
```

## 6. Create Local `.env`

Create your own local environment file:

```powershell
copy .env.example .env
```

For local SQLite only:

```text
DATABASE_URL=sqlite:///./finfx.db
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_CHAT_MODEL=llama3.2:3b
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
```

Optional keys can be added later:

```text
OPENAI_API_KEY=your_openai_key_here
ANTHROPIC_API_KEY=your_anthropic_key_here
ALPHA_VANTAGE_API_KEY=your_alpha_vantage_key_here
FRED_API_KEY=your_fred_key_here
```

Never commit `.env`.

## 7. Supabase Setup, Optional But Recommended

Use Supabase if you want persistent SQL records and pgvector RAG.

1. Create a Supabase project: https://supabase.com/
2. Copy the pooled Postgres connection string.
3. Put it in `.env`:

```text
DATABASE_URL=postgresql://postgres.PROJECT_REF:YOUR_PASSWORD@REGION.pooler.supabase.com:6543/postgres?sslmode=require
```

4. Run these scripts in Supabase SQL Editor:

```text
scripts/supabase_pgvector.sql
scripts/supabase_schema_pgvector.sql
scripts/supabase_llm_usage.sql
```

More details:

```text
docs/SUPABASE_SQL_SETUP.md
```

## 8. Start The App

```powershell
python -m uvicorn app.main:app --reload
```

Open:

```text
http://127.0.0.1:8000
```

API docs:

```text
http://127.0.0.1:8000/docs
```

## 9. Index Vector Stores

Only needed when using Supabase pgvector.

Start FastAPI first, then run:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/knowledge/vector/index" -Method Post
Invoke-RestMethod "http://127.0.0.1:8000/api/sql/schema-vector/index" -Method Post
```

Check status:

```powershell
Invoke-RestMethod "http://127.0.0.1:8000/api/database/status"
Invoke-RestMethod "http://127.0.0.1:8000/api/knowledge/vector/status"
Invoke-RestMethod "http://127.0.0.1:8000/api/sql/schema-vector/status"
```

## 10. Run Tests

```powershell
python -m pytest tests\test_services.py --basetemp .pytest-tmp
python -m compileall app
node --check app\static\app.js
node --check app\static\reports.js
```

## 11. Useful Demo Questions

Customer assistant:

```text
my payment failed, what to do, how to contact support
what documents are required for a high value transfer?
gbp/inr trend in last 30 days
will GBP/INR increase next month?
```

Admin Reports:

```text
last transaction
GBP TO INR HIGHEST TRANSFER
which llm provider used most tokens?
which assistant route had the slowest latency?
```

## 12. Common Issues

If `uvicorn` is not recognized:

```powershell
python -m uvicorn app.main:app --reload
```

If Supabase is unavailable:

- check `DATABASE_URL`,
- use pooled connection string,
- include `sslmode=require`,
- restart FastAPI after editing `.env`.

If Ollama does not answer:

```powershell
ollama list
ollama ps
```

Make sure `llama3.2:3b` and `nomic-embed-text` are installed.
