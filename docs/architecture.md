# Architecture

## Runtime Flow

1. Browser UI calls FastAPI endpoints.
2. FastAPI routes delegate to service classes.
3. FX requests use Frankfurter and fall back to local demo rates.
4. Transfer creation persists records to SQLite or Supabase/Postgres.
5. Customer AI questions are routed to FX tools, document RAG, or restricted admin-data responses.
6. Document RAG retrieves policy/FAQ chunks from Supabase pgvector when available.
7. Admin SQL questions retrieve table schema from Supabase pgvector, ask the LLM for SQL, validate it, then run read-only SQL.
8. LLM and embedding calls are logged to `llm_usage_logs`.
9. User/admin questions are logged to `assistant_question_logs`.
10. Admin Reports displays transfer metrics and AI observability metrics.

## Main Services

- `FxService`: live and historical FX rates.
- `TransferService`: customer transfer creation and persistence.
- `DatabaseService`: SQLite/Postgres access, SQL tables, pgvector tables.
- `KnowledgeService`: document chunking, retrieval, and document RAG.
- `SqlAgent`: schema RAG, SQL generation, SQL validation, report queries.
- `AssistantService`: customer-facing routing and answer composition.
- `OllamaClient`: local/cloud chat abstraction and local embeddings.
- `LlmUsageTracker`: in-memory and persisted model-call logging.

## Data Stores

| Store | Purpose |
| --- | --- |
| `transfers` | persisted customer transfer records |
| `knowledge_chunks` | document RAG embeddings |
| `schema_chunks` | Admin SQL schema RAG embeddings |
| `llm_usage_logs` | LLM/embedding call observability |
| `assistant_question_logs` | question-level observability |

## Safety Boundaries

- Customer assistant does not expose transfer record analytics.
- Admin SQL only allows validated `SELECT` queries.
- SQL write operations and schema changes are blocked.
- `.env`, local databases, virtual environments, and test caches are ignored by Git.
- Admin login is demo-only and should be replaced before production use.

## Target Production Architecture

- Server-side authentication and authorization.
- Read-only reporting database role for SQL agent queries.
- PII masking before LLM calls.
- Prompt-injection checks for uploaded documents.
- Docker Compose or container deployment.
- CI with tests, linting, and formatting.
- Centralized logging and tracing.
