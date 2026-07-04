import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence
from urllib.parse import urlparse

from app.core.config import settings


class DatabaseService:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or settings.database_url

    def status(self) -> dict:
        try:
            with self._connection() as connection:
                self._ensure_schema(connection)
                return {
                    "available": True,
                    "provider": self.provider_name(),
                    "message": f"{self.provider_name()} database is available.",
                }
        except Exception as exc:
            return {
                "available": False,
                "provider": self.provider_name(),
                "message": f"{self.provider_name()} is not available.",
                "error": str(exc),
                "next_steps": [
                    "Check that DATABASE_URL is correct.",
                    "For Supabase, use the pooled connection string with sslmode=require.",
                    "Install dependencies with pip install -r requirements.txt.",
                    "Restart the FastAPI server after changing environment variables.",
                ],
            }

    def provider_name(self) -> str:
        if self.database_url.startswith("sqlite"):
            return "SQLite"
        if self.database_url.startswith(("postgresql", "postgres")):
            return "Supabase/Postgres"
        return "Unknown SQL provider"

    def create_transfer(self, transfer: dict) -> dict:
        """Persist a customer transfer record using SQLite locally or Supabase/Postgres in demo mode."""
        status = self.status()
        if not status["available"]:
            return {"stored": False, "database_status": status}

        record = {
            "transfer_id": f"TRF-{uuid.uuid4().hex[:10].upper()}",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "customer_name": transfer["customer_name"],
            "from_currency": transfer["from_currency"].upper(),
            "to_currency": transfer["to_currency"].upper(),
            "amount": float(transfer["amount"]),
            "converted_amount": float(transfer["converted_amount"]),
            "rate": float(transfer["rate"]),
            "beneficiary_country": transfer["beneficiary_country"],
            "purpose": transfer["purpose"],
            "status": "submitted",
            "provider": transfer["provider"],
        }

        with self._connection() as connection:
            self._ensure_schema(connection)
            self._execute(
                connection,
                """
                INSERT INTO transfers (
                    transfer_id, created_at, customer_name, from_currency, to_currency,
                    amount, converted_amount, rate, beneficiary_country, purpose, status, provider
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(record.values()),
            )
            connection.commit()

        return {"stored": True, "transfer": record, "database_status": status}

    def list_transfers(self, limit: int = 50) -> dict:
        status = self.status()
        if not status["available"]:
            return {"database_status": status, "transfers": []}

        with self._connection() as connection:
            self._ensure_schema(connection)
            cursor = self._execute(
                connection,
                """
                SELECT transfer_id, created_at, customer_name, from_currency, to_currency,
                       amount, converted_amount, rate, beneficiary_country, purpose, status, provider
                FROM transfers
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        keys = [
            "transfer_id", "created_at", "customer_name", "from_currency", "to_currency",
            "amount", "converted_amount", "rate", "beneficiary_country", "purpose", "status", "provider",
        ]
        return {"database_status": status, "transfers": [dict(zip(keys, row)) for row in rows]}

    def transfer_summary(self) -> dict:
        records = self.list_transfers(limit=500)
        transfers = records["transfers"]
        total_volume = sum(row["amount"] for row in transfers)
        return {
            "database_status": records["database_status"],
            "total_persisted_transfers": len(transfers),
            "total_source_amount": round(total_volume, 2),
            "recent_transfers": transfers[:10],
        }

    def run_select_query(self, sql: str) -> dict:
        """Run a pre-validated reporting SELECT query and return rows as dictionaries."""
        status = self.status()
        if not status["available"]:
            return {"database_status": status, "rows": []}

        with self._connection() as connection:
            self._ensure_schema(connection)
            cursor = self._execute(connection, sql)
            rows = cursor.fetchall()
            columns = [column[0] for column in cursor.description or []]

        return {
            "database_status": status,
            "rows": [dict(zip(columns, row)) for row in rows],
        }

    def create_llm_usage_log(self, record: dict) -> dict:
        """Store one LLM/embedding call so token usage can be analysed later."""
        status = self.status()
        if not status["available"]:
            return {"stored": False, "database_status": status}

        log = {
            "usage_id": f"LLM-{uuid.uuid4().hex[:12].upper()}",
            "created_at": record["timestamp"],
            "question_id": record.get("question_id"),
            "call_type": record["call_type"],
            "provider": record["provider"],
            "model": record["model"],
            "success": 1 if record["success"] else 0,
            "input_tokens": int(record["input_tokens"]),
            "output_tokens": int(record["output_tokens"]),
            "total_tokens": int(record["total_tokens"]),
        }

        with self._connection() as connection:
            self._ensure_schema(connection)
            self._execute(
                connection,
                """
                INSERT INTO llm_usage_logs (
                    usage_id, created_at, question_id, call_type, provider, model, success,
                    input_tokens, output_tokens, total_tokens
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                tuple(log.values()),
            )
            connection.commit()

        return {"stored": True, "log": log, "database_status": status}

    def create_assistant_question_log(self, record: dict) -> dict:
        """Store one user question and its route so it can be joined to LLM usage by question_id."""
        status = self.status()
        if not status["available"]:
            return {"stored": False, "database_status": status}

        log = {
            "question_id": record["question_id"],
            "created_at": record["created_at"],
            "surface": record["surface"],
            "question_text": record["question_text"],
            "route_mode": record.get("route_mode"),
            "intent": record.get("intent"),
            "used_rag": 1 if record.get("used_rag") else 0,
            "used_sql": 1 if record.get("used_sql") else 0,
            "used_fx": 1 if record.get("used_fx") else 0,
            "citations_count": int(record.get("citations_count", 0)),
            "status": record.get("status", "success"),
            "latency_ms": int(record.get("latency_ms", 0)),
        }

        with self._connection() as connection:
            self._ensure_schema(connection)
            self._execute(
                connection,
                """
                INSERT INTO assistant_question_logs (
                    question_id, created_at, surface, question_text, route_mode, intent,
                    used_rag, used_sql, used_fx, citations_count, status, latency_ms
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (question_id) DO UPDATE SET
                    route_mode = EXCLUDED.route_mode,
                    intent = EXCLUDED.intent,
                    status = EXCLUDED.status,
                    latency_ms = EXCLUDED.latency_ms
                """,
                tuple(log.values()),
            )
            connection.commit()

        return {"stored": True, "log": log, "database_status": status}

    def list_llm_usage_logs(self, limit: int = 200) -> dict:
        status = self.status()
        if not status["available"]:
            return {"database_status": status, "logs": []}

        with self._connection() as connection:
            self._ensure_schema(connection)
            cursor = self._execute(
                connection,
                """
                SELECT usage_id, created_at, question_id, call_type, provider, model, success,
                       input_tokens, output_tokens, total_tokens
                FROM llm_usage_logs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        keys = [
            "usage_id", "created_at", "question_id", "call_type", "provider", "model", "success",
            "input_tokens", "output_tokens", "total_tokens",
        ]
        logs = [dict(zip(keys, row)) for row in rows]
        for log in logs:
            log["success"] = bool(log["success"])
        return {"database_status": status, "logs": logs}

    def llm_usage_summary(self, limit: int = 500) -> dict:
        records = self.list_llm_usage_logs(limit=limit)
        logs = records["logs"]
        totals = {
            "calls": len(logs),
            "successful_calls": sum(1 for log in logs if log["success"]),
            "failed_calls": sum(1 for log in logs if not log["success"]),
            "input_tokens": sum(log["input_tokens"] for log in logs),
            "output_tokens": sum(log["output_tokens"] for log in logs),
            "total_tokens": sum(log["total_tokens"] for log in logs),
        }
        by_provider = self._usage_rollup(logs, "provider")
        by_call_type = self._usage_rollup(logs, "call_type")
        return {
            "database_status": records["database_status"],
            "totals": totals,
            "by_provider": by_provider,
            "by_call_type": by_call_type,
            "recent": logs[:25],
            "note": "Persisted LLM usage logs from Supabase/Postgres.",
        }

    def assistant_question_summary(self, limit: int = 500) -> dict:
        """Summarise question logs and attach token usage by shared question_id."""
        status = self.status()
        if not status["available"]:
            return {"database_status": status, "totals": {}, "recent": []}

        with self._connection() as connection:
            self._ensure_schema(connection)
            cursor = self._execute(
                connection,
                """
                SELECT question_id, created_at, surface, question_text, route_mode, intent,
                       used_rag, used_sql, used_fx, citations_count, status, latency_ms
                FROM assistant_question_logs
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()

        keys = [
            "question_id", "created_at", "surface", "question_text", "route_mode", "intent",
            "used_rag", "used_sql", "used_fx", "citations_count", "status", "latency_ms",
        ]
        questions = [dict(zip(keys, row)) for row in rows]
        usage_logs = self.list_llm_usage_logs(limit=2000)["logs"]
        usage_by_question: dict[str, dict] = {}
        for log in usage_logs:
            question_id = log.get("question_id")
            if not question_id:
                continue
            usage_by_question.setdefault(question_id, {"llm_calls": 0, "total_tokens": 0})
            usage_by_question[question_id]["llm_calls"] += 1
            usage_by_question[question_id]["total_tokens"] += log["total_tokens"]

        for question in questions:
            linked_usage = usage_by_question.get(question["question_id"], {"llm_calls": 0, "total_tokens": 0})
            question.update(linked_usage)
            question["used_rag"] = bool(question["used_rag"])
            question["used_sql"] = bool(question["used_sql"])
            question["used_fx"] = bool(question["used_fx"])

        totals = {
            "questions": len(questions),
            "llm_calls": sum(question["llm_calls"] for question in questions),
            "total_tokens": sum(question["total_tokens"] for question in questions),
            "average_latency_ms": round(
                sum(question["latency_ms"] for question in questions) / len(questions)
            ) if questions else 0,
        }

        return {
            "database_status": status,
            "totals": totals,
            "by_route": self._question_rollup(questions, "route_mode"),
            "by_surface": self._question_rollup(questions, "surface"),
            "recent": questions[:50],
            "note": "Persisted assistant question logs joined to LLM usage logs by question_id.",
        }

    def vector_status(self) -> dict:
        if not self.database_url.startswith(("postgresql", "postgres")):
            return {
                "available": False,
                "provider": self.provider_name(),
                "message": "Vector search is only enabled for Supabase/Postgres.",
            }

        try:
            with self._connection() as connection:
                self._ensure_vector_schema(connection)
                cursor = self._execute(connection, "SELECT COUNT(*) FROM knowledge_chunks")
                count = cursor.fetchone()[0]
                return {
                    "available": True,
                    "provider": self.provider_name(),
                    "message": "Supabase pgvector knowledge store is available.",
                    "indexed_chunks": count,
                }
        except Exception as exc:
            return {
                "available": False,
                "provider": self.provider_name(),
                "message": "Supabase pgvector knowledge store is not available.",
                "error": str(exc),
                "next_steps": [
                    "Run scripts/supabase_pgvector.sql in Supabase SQL Editor.",
                    "Make sure the vector extension is enabled.",
                    "Restart FastAPI, then run the knowledge index endpoint.",
                ],
            }

    def upsert_knowledge_chunk(self, chunk: dict, embedding: Sequence[float]) -> None:
        with self._connection() as connection:
            self._ensure_vector_schema(connection)
            self._execute(
                connection,
                """
                INSERT INTO knowledge_chunks (chunk_id, source, heading, content, embedding, updated_at)
                VALUES (?, ?, ?, ?, ?::vector, ?)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    source = EXCLUDED.source,
                    heading = EXCLUDED.heading,
                    content = EXCLUDED.content,
                    embedding = EXCLUDED.embedding,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    chunk["id"],
                    chunk["source"],
                    chunk["heading"],
                    chunk["text"],
                    self._vector_literal(embedding),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()

    def search_knowledge_chunks(self, embedding: Sequence[float], limit: int) -> dict:
        """Run cosine-distance search over persisted document embeddings."""
        status = self.vector_status()
        if not status["available"]:
            return {"database_status": status, "chunks": []}

        with self._connection() as connection:
            cursor = self._execute(
                connection,
                """
                SELECT chunk_id, source, heading, content,
                       1 - (embedding <=> ?::vector) AS score
                FROM knowledge_chunks
                ORDER BY embedding <=> ?::vector
                LIMIT ?
                """,
                (
                    self._vector_literal(embedding),
                    self._vector_literal(embedding),
                    limit,
                ),
            )
            rows = cursor.fetchall()

        keys = ["id", "source", "heading", "text", "score"]
        return {"database_status": status, "chunks": [dict(zip(keys, row)) for row in rows]}

    def schema_vector_status(self) -> dict:
        if not self.database_url.startswith(("postgresql", "postgres")):
            return {
                "available": False,
                "provider": self.provider_name(),
                "message": "Schema vector search is only enabled for Supabase/Postgres.",
            }

        try:
            with self._connection() as connection:
                self._ensure_schema_vector_schema(connection)
                cursor = self._execute(connection, "SELECT COUNT(*) FROM schema_chunks")
                count = cursor.fetchone()[0]
                return {
                    "available": True,
                    "provider": self.provider_name(),
                    "message": "Supabase pgvector schema store is available.",
                    "indexed_chunks": count,
                }
        except Exception as exc:
            return {
                "available": False,
                "provider": self.provider_name(),
                "message": "Supabase pgvector schema store is not available.",
                "error": str(exc),
                "next_steps": [
                    "Run scripts/supabase_schema_pgvector.sql in Supabase SQL Editor.",
                    "Make sure the vector extension is enabled.",
                    "Restart FastAPI, then run the schema vector index endpoint.",
                ],
            }

    def upsert_schema_chunk(self, chunk: dict, embedding: Sequence[float]) -> None:
        with self._connection() as connection:
            self._ensure_schema_vector_schema(connection)
            self._execute(
                connection,
                """
                INSERT INTO schema_chunks (chunk_id, table_name, schema_text, embedding, updated_at)
                VALUES (?, ?, ?, ?::vector, ?)
                ON CONFLICT (chunk_id) DO UPDATE SET
                    table_name = EXCLUDED.table_name,
                    schema_text = EXCLUDED.schema_text,
                    embedding = EXCLUDED.embedding,
                    updated_at = EXCLUDED.updated_at
                """,
                (
                    chunk["id"],
                    chunk["table"],
                    chunk["text"],
                    self._vector_literal(embedding),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            connection.commit()

    def search_schema_chunks(self, embedding: Sequence[float], limit: int) -> dict:
        """Run cosine-distance search over persisted table-schema embeddings."""
        status = self.schema_vector_status()
        if not status["available"]:
            return {"database_status": status, "chunks": []}

        with self._connection() as connection:
            cursor = self._execute(
                connection,
                """
                SELECT chunk_id, table_name, schema_text,
                       1 - (embedding <=> ?::vector) AS score
                FROM schema_chunks
                ORDER BY embedding <=> ?::vector
                LIMIT ?
                """,
                (
                    self._vector_literal(embedding),
                    self._vector_literal(embedding),
                    limit,
                ),
            )
            rows = cursor.fetchall()

        keys = ["id", "table", "schema", "score"]
        return {"database_status": status, "chunks": [dict(zip(keys, row)) for row in rows]}

    @contextmanager
    def _connection(self):
        if self.database_url.startswith("sqlite"):
            path = self.database_url.replace("sqlite:///", "", 1)
            Path(path).parent.mkdir(parents=True, exist_ok=True) if Path(path).parent != Path(".") else None
            connection = sqlite3.connect(path)
            try:
                yield connection
            finally:
                connection.close()
            return

        if self.database_url.startswith(("postgresql", "postgres")):
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError("psycopg is not installed. Run pip install -r requirements.txt.") from exc

            connection = psycopg.connect(self.database_url)
            try:
                yield connection
            finally:
                connection.close()
            return

        parsed = urlparse(self.database_url)
        raise RuntimeError(f"Unsupported DATABASE_URL scheme: {parsed.scheme}")

    def _ensure_schema(self, connection) -> None:
        self._execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS transfers (
                transfer_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                customer_name TEXT NOT NULL,
                from_currency TEXT NOT NULL,
                to_currency TEXT NOT NULL,
                amount REAL NOT NULL,
                converted_amount REAL NOT NULL,
                rate REAL NOT NULL,
                beneficiary_country TEXT NOT NULL,
                purpose TEXT NOT NULL,
                status TEXT NOT NULL,
                provider TEXT NOT NULL
            )
            """,
        )
        self._execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS llm_usage_logs (
                usage_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                question_id TEXT,
                call_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                success INTEGER NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL
            )
            """,
        )
        self._ensure_column(connection, "llm_usage_logs", "question_id", "question_id TEXT")
        self._execute(
            connection,
            """
            CREATE INDEX IF NOT EXISTS llm_usage_logs_created_at_idx
            ON llm_usage_logs (created_at)
            """,
        )
        self._execute(
            connection,
            """
            CREATE INDEX IF NOT EXISTS llm_usage_logs_question_id_idx
            ON llm_usage_logs (question_id)
            """,
        )
        self._execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS assistant_question_logs (
                question_id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                surface TEXT NOT NULL,
                question_text TEXT NOT NULL,
                route_mode TEXT,
                intent TEXT,
                used_rag INTEGER NOT NULL,
                used_sql INTEGER NOT NULL,
                used_fx INTEGER NOT NULL,
                citations_count INTEGER NOT NULL,
                status TEXT NOT NULL,
                latency_ms INTEGER NOT NULL
            )
            """,
        )
        self._execute(
            connection,
            """
            CREATE INDEX IF NOT EXISTS assistant_question_logs_created_at_idx
            ON assistant_question_logs (created_at)
            """,
        )
        connection.commit()

    def _ensure_vector_schema(self, connection) -> None:
        if not self.database_url.startswith(("postgresql", "postgres")):
            raise RuntimeError("Vector schema requires Supabase/Postgres.")

        self._execute(connection, "CREATE EXTENSION IF NOT EXISTS vector")
        self._execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS knowledge_chunks (
                chunk_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                heading TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding vector(768) NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        )
        self._execute(
            connection,
            """
            CREATE INDEX IF NOT EXISTS knowledge_chunks_embedding_idx
            ON knowledge_chunks USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
            """,
        )
        connection.commit()

    def _ensure_schema_vector_schema(self, connection) -> None:
        if not self.database_url.startswith(("postgresql", "postgres")):
            raise RuntimeError("Schema vector schema requires Supabase/Postgres.")

        self._execute(connection, "CREATE EXTENSION IF NOT EXISTS vector")
        self._execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS schema_chunks (
                chunk_id TEXT PRIMARY KEY,
                table_name TEXT NOT NULL,
                schema_text TEXT NOT NULL,
                embedding vector(768) NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
        )
        self._execute(
            connection,
            """
            CREATE INDEX IF NOT EXISTS schema_chunks_embedding_idx
            ON schema_chunks USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 100)
            """,
        )
        self._execute(
            connection,
            """
            CREATE INDEX IF NOT EXISTS schema_chunks_table_name_idx
            ON schema_chunks (table_name)
            """,
        )
        connection.commit()

    def _execute(self, connection, sql: str, params: tuple = ()):
        if self.database_url.startswith(("postgresql", "postgres")):
            sql = sql.replace("?", "%s")
        return connection.execute(sql, params)

    def _ensure_column(self, connection, table: str, column: str, definition: str) -> None:
        if self.database_url.startswith(("postgresql", "postgres")):
            cursor = self._execute(
                connection,
                """
                SELECT 1
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ? AND column_name = ?
                """,
                (table, column),
            )
            exists = cursor.fetchone() is not None
        else:
            cursor = connection.execute(f"PRAGMA table_info({table})")
            exists = any(row[1] == column for row in cursor.fetchall())

        if not exists:
            self._execute(connection, f"ALTER TABLE {table} ADD COLUMN {definition}")

    @staticmethod
    def _vector_literal(embedding: Sequence[float]) -> str:
        return "[" + ",".join(str(float(value)) for value in embedding) + "]"

    @staticmethod
    def _usage_rollup(logs: list[dict], key: str) -> dict:
        groups: dict[str, dict] = {}
        for log in logs:
            group = log[key]
            groups.setdefault(group, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
            groups[group]["calls"] += 1
            groups[group]["input_tokens"] += log["input_tokens"]
            groups[group]["output_tokens"] += log["output_tokens"]
            groups[group]["total_tokens"] += log["total_tokens"]
        return groups

    @staticmethod
    def _question_rollup(questions: list[dict], key: str) -> dict:
        groups: dict[str, dict] = {}
        for question in questions:
            group = question.get(key) or "unknown"
            groups.setdefault(group, {"questions": 0, "llm_calls": 0, "total_tokens": 0})
            groups[group]["questions"] += 1
            groups[group]["llm_calls"] += question["llm_calls"]
            groups[group]["total_tokens"] += question["total_tokens"]
        return groups
