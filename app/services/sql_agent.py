import math
import re
from dataclasses import dataclass

from app.services.ollama_client import OllamaClient


@dataclass(frozen=True)
class SchemaChunk:
    id: str
    table: str
    text: str


class SqlAgent:
    # These schema chunks are the fallback source of truth if Supabase pgvector is not indexed yet.
    schema_chunks = (
        SchemaChunk(
            id="transfers-core",
            table="transfers",
            text=(
                "Table transfers stores customer payment and FX transfer records. "
                "Columns: transfer_id, created_at, customer_name, from_currency, to_currency, "
                "amount, converted_amount, rate, beneficiary_country, purpose, status, provider. "
                "Use this table for last payment, latest transfer, customer transfer, currency corridor, "
                "GBP to INR, amount, beneficiary country, purpose, provider, and transfer status questions."
            ),
        ),
        SchemaChunk(
            id="llm-usage-logs",
            table="llm_usage_logs",
            text=(
                "Table llm_usage_logs stores AI observability and token usage records. "
                "Columns: usage_id, created_at, question_id, call_type, provider, model, success, "
                "input_tokens, output_tokens, total_tokens. Use this table for LLM usage, "
                "token consumption, provider usage, model calls, failed AI calls, and observability questions."
            ),
        ),
        SchemaChunk(
            id="assistant-question-logs",
            table="assistant_question_logs",
            text=(
                "Table assistant_question_logs stores one row for each user question sent to Ask AI or Admin Reports. "
                "Columns: question_id, created_at, surface, question_text, route_mode, intent, used_rag, "
                "used_sql, used_fx, citations_count, status, latency_ms. Use this table for question history, "
                "routing decisions, RAG usage, SQL usage, FX usage, blocked questions, and latency questions. "
                "Join is not allowed here, but question_id can be compared with llm_usage_logs question_id manually."
            ),
        ),
    )
    allowed_tables = {
        "transfers": {
            "transfer_id",
            "created_at",
            "customer_name",
            "from_currency",
            "to_currency",
            "amount",
            "converted_amount",
            "rate",
            "beneficiary_country",
            "purpose",
            "status",
            "provider",
        },
        "llm_usage_logs": {
            "usage_id",
            "created_at",
            "question_id",
            "call_type",
            "provider",
            "model",
            "success",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        },
        "assistant_question_logs": {
            "question_id",
            "created_at",
            "surface",
            "question_text",
            "route_mode",
            "intent",
            "used_rag",
            "used_sql",
            "used_fx",
            "citations_count",
            "status",
            "latency_ms",
        },
    }
    allowed_columns = set().union(*allowed_tables.values())
    allowed_functions = {"count", "sum", "avg", "min", "max", "round"}
    blocked_terms = {
        "alter",
        "attach",
        "copy",
        "create",
        "delete",
        "drop",
        "execute",
        "grant",
        "insert",
        "merge",
        "pragma",
        "reindex",
        "replace",
        "revoke",
        "truncate",
        "update",
        "vacuum",
    }

    def __init__(
        self, transaction_service, database_service=None, ollama_client=None
    ) -> None:
        self.transaction_service = transaction_service
        self.database_service = database_service
        self.ollama_client = ollama_client or OllamaClient()

    def answer(self, question: str) -> dict:
        """Answer Admin Reports questions by generating or selecting safe read-only SQL."""
        normalized = question.lower()

        if not self.database_service:
            return {
                "generated_sql": None,
                "result": [],
                "explanation": "SQL analytics is configured for persisted Supabase/Postgres transfer records only.",
            }

        blocked_llm_result = None
        llm_result = self._answer_with_llm_sql(question)
        if llm_result and llm_result.get("mode") != "llm-sql-blocked":
            return llm_result
        if llm_result:
            blocked_llm_result = llm_result
            if any(
                re.search(rf"\b{term}\b", normalized) for term in self.blocked_terms
            ):
                return blocked_llm_result

        highest_answer = self._answer_highest_transfer_question(normalized)
        if highest_answer:
            return highest_answer

        currency_answer = self._answer_currency_transfer_question(normalized)
        if currency_answer:
            return currency_answer

        if self._asks_for_latest_transfer(normalized):
            sql = """
            SELECT transfer_id, created_at, customer_name, from_currency, to_currency,
                   amount, converted_amount, rate, beneficiary_country, purpose, status, provider
            FROM transfers
            ORDER BY created_at DESC
            LIMIT 1;
            """.strip()
            records = self.database_service.list_transfers(limit=1)
            return {
                "generated_sql": sql,
                "result": records["transfers"],
                "database_status": records["database_status"],
                "explanation": "Returned the latest persisted transfer from the SQL database.",
            }

        if self._asks_for_recent_transfers(normalized):
            sql = """
            SELECT transfer_id, created_at, customer_name, from_currency, to_currency,
                   amount, converted_amount, rate, beneficiary_country, purpose, status, provider
            FROM transfers
            ORDER BY created_at DESC
            LIMIT 10;
            """.strip()
            records = self.database_service.list_transfers(limit=10)
            return {
                "generated_sql": sql,
                "result": records["transfers"],
                "database_status": records["database_status"],
                "explanation": "Returned recent persisted transfers from the SQL database.",
            }

        if any(term in normalized for term in ("summary", "total", "count", "volume")):
            sql = """
            SELECT COUNT(*) AS total_persisted_transfers,
                   SUM(amount) AS total_source_amount
            FROM transfers;
            """.strip()
            summary = self.database_service.transfer_summary()
            return {
                "generated_sql": sql,
                "result": {
                    "total_persisted_transfers": summary["total_persisted_transfers"],
                    "total_source_amount": summary["total_source_amount"],
                },
                "database_status": summary["database_status"],
                "explanation": "Returned a Supabase/Postgres transfer summary.",
            }

        if blocked_llm_result:
            return blocked_llm_result

        return {
            "generated_sql": None,
            "result": [],
            "database_status": self.database_service.status(),
            "explanation": "Ask about persisted Supabase transfers, for example: last transaction, recent transfers, or transfer summary.",
        }

    def _answer_with_llm_sql(self, question: str) -> dict | None:
        """Use schema RAG to give the LLM only table metadata, then validate SQL before execution."""
        schema_context = self._schema_context(question)
        plan = self.ollama_client.generate_json(
            self._sql_prompt(question, schema_context)
        )
        if not plan or not isinstance(plan.get("sql"), str):
            return None

        candidate_sql = plan["sql"]
        validation = self.validate_sql(candidate_sql)
        if not validation["valid"]:
            return {
                "mode": "llm-sql-blocked",
                "generated_sql": candidate_sql,
                "safe_sql": None,
                "result": [],
                "database_status": self.database_service.status(),
                "explanation": f"LLM-generated SQL was blocked: {validation['reason']}",
            }

        safe_sql = validation["sql"]
        query_result = self.database_service.run_select_query(safe_sql)
        return {
            "mode": "llm-generated-sql",
            "generated_sql": candidate_sql,
            "safe_sql": safe_sql,
            "result": query_result["rows"],
            "database_status": query_result["database_status"],
            "schema_context": schema_context,
            "explanation": plan.get("explanation")
            or "Ollama generated a read-only SQL query, which was validated before execution.",
        }

    def schema_vector_status(self) -> dict:
        if not self.database_service:
            return {
                "available": False,
                "provider": "No database",
                "message": "Schema vector search needs Supabase/Postgres.",
            }
        return self.database_service.schema_vector_status()

    def index_schema_vector_store(self) -> dict:
        """Persist table-schema chunks into Supabase pgvector for SQL intent retrieval."""
        status = self.schema_vector_status()
        if not status["available"]:
            return {"indexed": False, "chunks_indexed": 0, "database_status": status}

        indexed = 0
        skipped = 0
        for chunk in self.schema_chunks:
            embedding = self.ollama_client.embed(chunk.text)
            if not embedding:
                skipped += 1
                continue
            self.database_service.upsert_schema_chunk(
                {
                    "id": chunk.id,
                    "table": chunk.table,
                    "text": chunk.text,
                },
                embedding,
            )
            indexed += 1

        return {
            "indexed": indexed > 0,
            "chunks_indexed": indexed,
            "chunks_skipped": skipped,
            "database_status": self.schema_vector_status(),
        }

    def _answer_currency_transfer_question(self, normalized: str) -> dict | None:
        currencies = ("GBP", "EUR", "USD", "INR", "AUD", "CAD", "AED")
        requested = next(
            (currency for currency in currencies if currency.lower() in normalized),
            None,
        )
        transfer_terms = (
            "transaction",
            "transactions",
            "transfer",
            "transfers",
            "payment",
            "payments",
        )
        if not requested or not any(term in normalized for term in transfer_terms):
            return None

        sql = f"""
        SELECT transfer_id, created_at, customer_name, from_currency, to_currency,
               amount, converted_amount, rate, beneficiary_country, purpose, status, provider
        FROM transfers
        WHERE from_currency = '{requested}' OR to_currency = '{requested}'
        ORDER BY created_at DESC
        LIMIT 50;
        """.strip()
        query_result = self.database_service.run_select_query(sql)
        return {
            "mode": "safe-sql-template",
            "generated_sql": sql,
            "safe_sql": sql,
            "result": query_result["rows"],
            "database_status": query_result["database_status"],
            "explanation": f"Returned persisted transfers where either side of the currency pair is {requested}.",
        }

    def _answer_highest_transfer_question(self, normalized: str) -> dict | None:
        highest_terms = ("highest", "largest", "biggest", "maximum", "max")
        transfer_terms = (
            "transaction",
            "transactions",
            "transfer",
            "transfers",
            "payment",
            "payments",
            "amount",
        )
        if not any(term in normalized for term in highest_terms):
            return None
        if not any(term in normalized for term in transfer_terms):
            return None

        currency = self._currency_in_question(normalized)
        filters = []
        explanation_parts = []

        if currency:
            if re.search(rf"\bfrom\s+{currency.lower()}\b", normalized):
                filters.append(f"from_currency = '{currency}'")
                explanation_parts.append(f"from {currency}")
            elif re.search(rf"\bto\s+{currency.lower()}\b", normalized):
                filters.append(f"to_currency = '{currency}'")
                explanation_parts.append(f"to {currency}")
            else:
                filters.append(
                    f"(from_currency = '{currency}' OR to_currency = '{currency}')"
                )
                explanation_parts.append(f"involving {currency}")

        if "today" in normalized:
            filters.append("substr(created_at, 1, 10) = CAST(CURRENT_DATE AS TEXT)")
            explanation_parts.append("today")

        where_clause = f"WHERE {' AND '.join(filters)}" if filters else ""
        sql = f"""
        SELECT transfer_id, created_at, customer_name, from_currency, to_currency,
               amount, converted_amount, rate, beneficiary_country, purpose, status, provider
        FROM transfers
        {where_clause}
        ORDER BY amount DESC
        LIMIT 1;
        """.strip()
        query_result = self.database_service.run_select_query(sql)
        scope = (
            " ".join(explanation_parts)
            if explanation_parts
            else "across persisted transfers"
        )
        return {
            "mode": "safe-sql-template",
            "generated_sql": sql,
            "safe_sql": sql,
            "result": query_result["rows"],
            "database_status": query_result["database_status"],
            "explanation": f"Returned the highest source amount transfer {scope}.",
        }

    def _currency_in_question(self, normalized: str) -> str | None:
        currencies = ("GBP", "EUR", "USD", "INR", "AUD", "CAD", "AED")
        return next(
            (currency for currency in currencies if currency.lower() in normalized),
            None,
        )

    def validate_sql(self, sql: str) -> dict:
        """Allow only a small, read-only SELECT subset before any generated SQL reaches the database."""
        cleaned = " ".join(sql.strip().split())
        cleaned = cleaned[:-1].strip() if cleaned.endswith(";") else cleaned
        lowered = cleaned.lower()

        if not cleaned:
            return {"valid": False, "reason": "empty SQL"}
        if not lowered.startswith("select "):
            return {"valid": False, "reason": "only SELECT queries are allowed"}
        if ";" in cleaned:
            return {"valid": False, "reason": "multiple SQL statements are not allowed"}
        if "--" in cleaned or "/*" in cleaned or "*/" in cleaned:
            return {"valid": False, "reason": "SQL comments are not allowed"}
        if any(re.search(rf"\b{term}\b", lowered) for term in self.blocked_terms):
            return {
                "valid": False,
                "reason": "write or schema-changing SQL is not allowed",
            }
        selected_table = self._selected_table(lowered)
        if not selected_table:
            return {
                "valid": False,
                "reason": "queries must read from an allowed reporting table",
            }
        if re.search(r"\b(join|union|intersect|except)\b", lowered):
            return {
                "valid": False,
                "reason": "joins and set operations are not allowed in this report query",
            }

        unknown_identifiers = self._unknown_identifiers(lowered, selected_table)
        if unknown_identifiers:
            return {
                "valid": False,
                "reason": f"unknown identifier: {unknown_identifiers[0]}",
            }

        if not re.search(r"\blimit\s+\d+\b", lowered):
            cleaned = f"{cleaned} LIMIT 50"

        return {"valid": True, "sql": f"{cleaned};"}

    def _selected_table(self, lowered_sql: str) -> str | None:
        match = re.search(r"\bfrom\s+([a-z_][a-z0-9_]*)\b", lowered_sql)
        if not match:
            return None
        table = match.group(1)
        return table if table in self.allowed_tables else None

    def _unknown_identifiers(self, lowered_sql: str, selected_table: str) -> list[str]:
        keywords = {
            "as",
            "asc",
            "and",
            "between",
            "by",
            "case",
            "desc",
            "distinct",
            "else",
            "end",
            "from",
            "group",
            "having",
            "in",
            "is",
            "like",
            "limit",
            "not",
            "null",
            "or",
            "order",
            "select",
            "then",
            "when",
            "where",
        }
        text = re.sub(r"'[^']*'", " ", lowered_sql)
        text = re.sub(r"\bas\s+[a-z_][a-z0-9_]*", " as ", text)
        identifiers = re.findall(r"\b[a-z_][a-z0-9_]*\b", text)
        allowed = (
            self.allowed_tables[selected_table]
            | self.allowed_functions
            | keywords
            | set(self.allowed_tables)
        )
        return sorted(
            {identifier for identifier in identifiers if identifier not in allowed}
        )

    def _schema_context(self, question: str) -> list[dict]:
        """Retrieve the most relevant table descriptions for the user's SQL question."""
        query_embedding = self.ollama_client.embed(question)
        if query_embedding and self.database_service:
            vector_result = self.database_service.search_schema_chunks(
                query_embedding, limit=2
            )
            chunks = vector_result.get("chunks", [])
            if chunks:
                return [
                    {
                        "id": chunk["id"],
                        "table": chunk["table"],
                        "score": round(float(chunk["score"]), 4),
                        "schema": chunk["schema"],
                        "source": "supabase-pgvector",
                    }
                    for chunk in chunks
                    if float(chunk["score"]) > 0
                ]

        scored = []
        for chunk in self.schema_chunks:
            score = self._keyword_schema_score(question, chunk.text)
            if query_embedding:
                chunk_embedding = self.ollama_client.embed(chunk.text)
                if chunk_embedding:
                    score = max(
                        score,
                        self._cosine_similarity(
                            tuple(query_embedding), tuple(chunk_embedding)
                        ),
                    )
            scored.append((score, chunk))

        scored.sort(key=lambda item: item[0], reverse=True)
        selected = scored[:2]
        return [
            {
                "id": chunk.id,
                "table": chunk.table,
                "score": round(float(score), 4),
                "schema": chunk.text,
                "source": "code-fallback",
            }
            for score, chunk in selected
            if score > 0
        ] or [
            {
                "id": self.schema_chunks[0].id,
                "table": self.schema_chunks[0].table,
                "score": 0.0,
                "schema": self.schema_chunks[0].text,
                "source": "code-fallback",
            }
        ]

    def _sql_prompt(self, question: str, schema_context: list[dict]) -> str:
        schema_text = "\n\n".join(f"- {chunk['schema']}" for chunk in schema_context)
        return f"""
You are a careful SQL analyst for a fintech reporting page.
Generate one read-only SQL query for the user's question.

Rules:
- Return JSON only.
- JSON shape: {{"sql": "...", "explanation": "..."}}
- Use only the table schema provided below.
- Use only SELECT statements.
- Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, COPY, PRAGMA, or multiple statements.
- Add a LIMIT of 50 or less unless the query returns only aggregates.
- Use ISO text ordering for created_at.
- Do not use JSON functions such as JSON_AGG or json_build_object.
- Do not use table aliases or qualified names such as t.transfer_id.
- Select normal columns directly so the UI can render a table.

Retrieved schema context:
{schema_text}

User question: {question}
""".strip()

    @staticmethod
    def _keyword_schema_score(question: str, schema_text: str) -> float:
        query_terms = set(re.findall(r"[a-zA-Z0-9_]+", question.lower()))
        schema_terms = set(re.findall(r"[a-zA-Z0-9_]+", schema_text.lower()))
        if not query_terms:
            return 0.0
        return len(query_terms.intersection(schema_terms)) / len(query_terms)

    @staticmethod
    def _cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
        if len(left) != len(right) or not left or not right:
            return 0.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(a * a for a in left))
        right_norm = math.sqrt(sum(b * b for b in right))
        if not left_norm or not right_norm:
            return 0.0
        return dot / (left_norm * right_norm)

    def _asks_for_latest_transfer(self, normalized: str) -> bool:
        latest_terms = ("last", "latest", "newest", "most recent")
        transfer_terms = (
            "transaction",
            "transactions",
            "transfer",
            "transfers",
            "payment",
            "payments",
        )
        return any(term in normalized for term in latest_terms) and any(
            term in normalized for term in transfer_terms
        )

    def _asks_for_recent_transfers(self, normalized: str) -> bool:
        recent_terms = ("recent", "list", "show", "all")
        transfer_terms = (
            "transaction",
            "transactions",
            "transfer",
            "transfers",
            "payment",
            "payments",
        )
        return any(term in normalized for term in recent_terms) and any(
            term in normalized for term in transfer_terms
        )
