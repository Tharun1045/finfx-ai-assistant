# Roadmap

## Completed MVP

- FastAPI backend.
- Static browser UI.
- Live FX rates with Frankfurter.
- Currency conversion.
- Transfer creation and SQL persistence.
- Supabase/Postgres support.
- Customer-facing AI assistant.
- Local Ollama chat and embeddings.
- Document RAG over markdown knowledge files.
- Supabase pgvector document store.
- Admin Reports dashboard.
- Natural-language Admin SQL with validation.
- Persistent schema RAG in Supabase pgvector.
- LLM usage logging.
- Assistant question logging.
- AI observability dashboard.

## Near-Term Improvements

- Replace demo admin login with server-side authentication.
- Add a read-only database role for report queries.
- Add stronger SQL validation tests for more natural-language cases.
- Add frontend test coverage.
- Add automatic formatting and linting.
- Add Docker Compose for local setup.
- Add screenshots or a short demo video for the portfolio README.

## Data Engineering Extensions

- Add scheduled daily summary tables.
- Add richer corridor-level aggregations.
- Add FX-rate cache tables.
- Add batch jobs for historical transfer metrics.
- Add event-driven transfer ingestion with Kafka or Redpanda.

## AI Engineering Extensions

- Add prompt-injection detection for uploaded documents.
- Add PII masking before LLM calls.
- Add response quality evaluation test cases.
- Add model/provider comparison reports.
- Add cost estimates for OpenAI/Anthropic runs.
- Add retrieval-quality metrics for document RAG and schema RAG.

## Production Hardening

- CI pipeline with tests and linting.
- Deployment configuration.
- Server-side sessions.
- Audit logging.
- Secrets management.
- Monitoring and tracing.
- Rate limiting.
- Error tracking.
