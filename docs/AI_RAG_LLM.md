# LLM, RAG, Vectors, and Knowledge Architecture

This document explains the AI architecture used in FinFX AI Assistant.

## Key Definitions

### LLM

A large language model generates or transforms text. In this project, the LLM is used for:

- answering retrieved policy/FAQ questions,
- planning which tool should answer a user question,
- summarizing live FX tool results,
- generating read-only SQL for Admin Reports,
- formatting grounded answers.

Default local model:

```text
llama3.2:3b
```

### Embedding Model

An embedding model converts text into a list of numbers. Similar text should produce vectors that are close together.

Default local embedding model:

```text
nomic-embed-text
```

This project keeps embeddings local even if the chat LLM provider is changed to OpenAI or Anthropic. That keeps pgvector dimensions stable at 768.

### Vector

A vector is a numeric representation of text. Example:

```text
"high value transfer documents" -> [0.12, -0.04, 0.88, ...]
```

The app compares vectors to find semantically similar content.

### Vector Database

A vector database stores embeddings and can search by similarity.

This project uses Supabase Postgres with the `pgvector` extension.

### RAG

RAG means retrieval-augmented generation.

Instead of asking the LLM to answer from memory, the app:

1. embeds the user question,
2. retrieves relevant context from a vector store or local fallback,
3. sends only that context to the LLM,
4. asks the LLM to answer using the retrieved context,
5. shows citations/evidence in the UI.

RAG makes answers more grounded, auditable, and domain-specific.

## AI Layers In This Project

### 1. Customer Assistant Router

The customer-facing assistant decides whether a question should go to:

- live FX tools,
- FX trend/outlook logic,
- document RAG,
- restricted admin-data response.

It uses a mix of deterministic checks and an LLM tool planner.

Customer questions about transaction records are blocked from the public assistant and routed to an Admin Reports message instead.

### 2. Document RAG

Document RAG answers policy, FAQ, support, compliance, and verification questions.

Source documents:

```text
data/knowledge/transfer-faq.md
data/knowledge/verification-policy.md
```

Supabase table:

```text
knowledge_chunks
```

Flow:

1. Markdown documents are split into chunks.
2. Each chunk is embedded with `nomic-embed-text`.
3. Chunks are stored in Supabase pgvector.
4. User question is embedded.
5. Supabase returns the closest chunks.
6. `llama3.2:3b` answers using retrieved chunks.
7. UI shows citations and retrieved evidence.

If Supabase pgvector is unavailable, the app falls back to local semantic retrieval or keyword retrieval.

### 3. Admin SQL Schema RAG

Admin SQL uses schema RAG to help the LLM write SQL safely.

This is different from document RAG. It does not retrieve policy documents. It retrieves table schema descriptions.

Supabase table:

```text
schema_chunks
```

Stored schema chunks:

```text
transfers
llm_usage_logs
assistant_question_logs
```

Flow:

1. Admin asks a natural-language report question.
2. App embeds the question using local Ollama.
3. Supabase pgvector searches `schema_chunks`.
4. App sends only the relevant schema text to the LLM.
5. LLM generates one SQL `SELECT` query.
6. App validates the SQL.
7. App blocks unsafe SQL.
8. App runs only validated read-only SQL.

The app still keeps code-based schema chunks as fallback if Supabase schema vectors are unavailable.

### 4. SQL Safety Layer

The SQL agent does not blindly trust the LLM.

It blocks:

- `INSERT`
- `UPDATE`
- `DELETE`
- `DROP`
- `ALTER`
- `CREATE`
- `TRUNCATE`
- `COPY`
- comments
- multiple statements
- joins and set operations for this demo
- unknown tables
- unknown columns
- JSON aggregation functions that the UI cannot safely render

Allowed tables:

```text
transfers
llm_usage_logs
assistant_question_logs
```

Allowed functions:

```text
count, sum, avg, min, max, round
```

### 5. LLM Usage and Question Logging

The app records observability data for future optimization.

Supabase tables:

```text
assistant_question_logs
llm_usage_logs
```

`assistant_question_logs` stores one row per user/admin question.

`llm_usage_logs` stores one row per LLM or embedding call.

Both are connected by:

```text
question_id
```

This allows reports like:

- which question used most tokens,
- which route is slowest,
- how many calls a question triggered,
- which provider/model was used,
- how often RAG is used,
- how many calls failed.

## LLM Providers

The app supports multiple chat providers through one client layer.

### Ollama

Default local provider.

No API key required.

Ollama runs open-weight LLMs on your own laptop or machine and exposes a local HTTP API, usually at:

```text
http://localhost:11434
```

Used for:

- chat generation,
- JSON tool planning,
- SQL generation,
- embeddings.

In this project, Ollama is the default because it makes the AI workflow easy to run locally without paid keys. It is also useful for learning how LLM routing, RAG, embeddings, and SQL generation work before switching to a hosted model.

### Ollama vs Online LLM APIs

| Area | Ollama local model | OpenAI/Claude hosted model |
| --- | --- | --- |
| Where it runs | On your laptop or local machine | Cloud provider servers |
| API key | Not required for local use | Required |
| Internet | Not needed after models are downloaded | Required |
| Cost | No per-token API bill for local runs | Usually billed by usage |
| Privacy | Prompts stay local unless your app sends data elsewhere | Prompts are sent to provider API |
| Speed | Depends on local CPU/GPU | Usually fast and scalable |
| Quality | Depends on local model size and hardware | Often stronger for reasoning and instruction following |
| Hardware | Uses local CPU/GPU; may be slower on CPU-only machines | Provider handles infrastructure |
| Best for | learning, local demos, private prototypes, offline workflows | production-grade reasoning, scale, managed reliability |

Important limitation: local Ollama models do not automatically know live internet data. In this project, live data comes from tools such as Frankfurter, Supabase, Alpha Vantage, or FRED. The LLM reasons over the data that the app retrieves.

### OpenAI

Optional cloud provider.

Requires:

```text
OPENAI_API_KEY
```

Used only for chat/JSON generation if selected.

Embeddings remain local in Ollama.

### Anthropic/Claude

Optional cloud provider.

Requires:

```text
ANTHROPIC_API_KEY
```

Used only for chat generation if selected.

Embeddings remain local in Ollama.

## Why Keep Embeddings Local?

The pgvector tables are created with:

```text
vector(768)
```

`nomic-embed-text` produces 768-dimensional embeddings. If the project changed embedding providers casually, stored vectors could become incompatible. Keeping embeddings local avoids that problem.

## Tables Used By AI Features

| Feature | Table | Type |
| --- | --- | --- |
| Document RAG | `knowledge_chunks` | pgvector |
| Admin SQL schema RAG | `schema_chunks` | pgvector |
| Transfer reports | `transfers` | SQL |
| LLM call logs | `llm_usage_logs` | SQL |
| Question logs | `assistant_question_logs` | SQL |

## Knowledge Content

Current synthetic knowledge docs:

### transfer-faq.md

Contains:

- transfer timelines,
- payment delays,
- failed transfers.

Used for questions like:

```text
why is my payment delayed?
my payment failed, what should I do?
how long do international transfers take?
```

### verification-policy.md

Contains:

- required documents,
- high value transfers,
- suspicious activity.

Used for questions like:

```text
what documents are required for a high value transfer?
what is suspicious activity?
what checks are needed for large transfers?
```

## Example Flows

### Customer Policy Question

```text
User: what documents are required for a high value transfer?
```

Flow:

```text
question -> embedding -> knowledge_chunks -> retrieved policy context -> LLM answer -> citations
```

### Customer FX Question

```text
User: gbp/inr trend in last 30 days
```

Flow:

```text
question -> route to FX tool -> Frankfurter historical rates -> deterministic trend summary -> UI
```

### Admin SQL Question

```text
Admin: which assistant route had the slowest latency?
```

Flow:

```text
question -> embedding -> schema_chunks -> relevant schema -> LLM SQL -> SQL validator -> assistant_question_logs query -> table result
```

## Current Limitations

- The UI admin login is demo-only and not production authentication.
- The SQL agent is intentionally conservative.
- Forecasting is trend-context only, not a real prediction model.
- Token counts are estimated for local Ollama unless a cloud provider returns exact usage.
- The project does not include production PII masking yet.

## Production Improvements

Good next steps:

- server-side authentication for Admin Reports,
- read-only database role for SQL agent queries,
- prompt injection checks for uploaded documents,
- PII masking before LLM calls,
- Docker Compose,
- CI pipeline,
- richer dashboards,
- cloud deployment,
- stronger monitoring and tracing.
