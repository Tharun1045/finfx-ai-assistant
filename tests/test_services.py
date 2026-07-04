from app.services.fx_service import FxService
from app.services.knowledge_service import KnowledgeService
from app.services.assistant_service import AssistantService
from app.services.provider_service import ProviderService
from app.services.reporting_service import ReportingService
from app.services.sql_agent import SqlAgent
from app.services.tool_planner import ToolPlan
from app.services.database_service import DatabaseService
from app.services.transaction_service import TransactionService
from app.services.transfer_service import TransferService
from app.services.ollama_client import (
    LlmUsageTracker,
    OllamaClient,
    current_question_id,
)
from app.models.schemas import TransferRequest


class OfflineOllamaClient:
    def embed(self, text: str):
        return None

    def generate(self, prompt: str, model: str | None = None):
        return None

    def generate_json(self, prompt: str, model: str | None = None):
        return None


class VectorOllamaClient(OfflineOllamaClient):
    def embed(self, text: str):
        return [1.0, 0.0]

    def generate(self, prompt: str, model: str | None = None):
        return "Vector-grounded answer from Supabase pgvector."


class FakeVectorDatabase:
    def vector_status(self):
        return {
            "available": True,
            "provider": "Supabase/Postgres",
            "indexed_chunks": 1,
        }

    def search_knowledge_chunks(self, embedding, limit: int):
        return {
            "database_status": self.vector_status(),
            "chunks": [
                {
                    "id": "fake-0",
                    "source": "fake-policy.md",
                    "heading": "Fake policy",
                    "text": "High value transfers require identity verification and source of funds checks.",
                    "score": 0.98,
                }
            ],
        }


class FakeSchemaVectorDatabase:
    def schema_vector_status(self):
        return {
            "available": True,
            "provider": "Supabase/Postgres",
            "indexed_chunks": 1,
        }

    def search_schema_chunks(self, embedding, limit: int):
        return {
            "database_status": self.schema_vector_status(),
            "chunks": [
                {
                    "id": "assistant-question-logs",
                    "table": "assistant_question_logs",
                    "schema": (
                        "Table assistant_question_logs stores one row for each user question. "
                        "Columns: question_id, created_at, surface, question_text, route_mode, "
                        "intent, used_rag, used_sql, used_fx, citations_count, status, latency_ms."
                    ),
                    "score": 0.97,
                }
            ],
        }

    def status(self):
        return {"available": True, "provider": "Supabase/Postgres"}

    def run_select_query(self, sql: str):
        return {
            "database_status": self.status(),
            "rows": [{"route_mode": "llm-generated-sql", "latency_ms": 120}],
        }


class WeakVectorDatabase(FakeVectorDatabase):
    def search_knowledge_chunks(self, embedding, limit: int):
        return {
            "database_status": self.vector_status(),
            "chunks": [
                {
                    "id": "weak-0",
                    "source": "verification-policy.md",
                    "heading": "Required documents",
                    "text": "Customers may be asked for proof of identity and source of funds.",
                    "score": 0.42,
                }
            ],
        }


class PlannedFxClient(OfflineOllamaClient):
    def generate_json(self, prompt: str, model: str | None = None):
        return {
            "intent": "fx_best_rate",
            "base_currency": "GBP",
            "quote_currency": "INR",
            "period": "last_month",
            "amount": None,
            "confidence": 0.94,
        }


class StaticToolPlanner:
    def plan(self, question: str):
        return ToolPlan(
            intent="fx_best_rate",
            base_currency="GBP",
            quote_currency="INR",
            period="last_month",
            confidence=0.94,
        )


class StaticTrendPlanner:
    def plan(self, question: str):
        return ToolPlan(
            intent="fx_trend",
            base_currency="GBP",
            quote_currency="INR",
            confidence=0.91,
        )


class StaticTransactionPlanner:
    def plan(self, question: str):
        return ToolPlan(
            intent="transaction_analytics",
            base_currency="GBP",
            confidence=0.9,
        )


class StaticTrendFxService(FxService):
    def trend_summary(
        self,
        from_currency: str,
        to_currency: str,
        days: int = 30,
        average_days: int = 20,
        today=None,
    ):
        return {
            "from_currency": from_currency,
            "to_currency": to_currency,
            "period_days": days,
            "average_days": average_days,
            "latest_rate": 1.334,
            "latest_date": "2026-07-03",
            "average_rate": 1.321,
            "start_rate": 1.3,
            "start_date": "2026-06-04",
            "change": 0.034,
            "change_percent": 2.6154,
            "direction": "up",
            "observations": 30,
            "series": [{"date": "2026-07-03", "rate": 1.334}],
            "source": "Live rates from Frankfurter public exchange-rate API",
            "provider": "frankfurter",
            "is_live": True,
        }


class StaticConversionFxService(FxService):
    def convert(
        self, amount: float, from_currency: str, to_currency: str, use_live: bool = True
    ) -> dict:
        return {
            "amount": amount,
            "from_currency": from_currency.upper(),
            "to_currency": to_currency.upper(),
            "rate": 126.39,
            "converted_amount": round(amount * 126.39, 2),
            "as_of": "2026-07-04",
            "provider": "test-fx",
            "is_live": use_live,
            "source": "Deterministic test FX service",
        }


class StaticReportFxService(FxService):
    def get_rates(self, use_live: bool = True) -> dict:
        return {
            "base": "GBP",
            "as_of": "2026-07-04",
            "provider": "test-fx",
            "rates": {"EUR": 1.18, "USD": 1.33, "INR": 126.39},
            "is_live": use_live,
        }


class GeneratedSqlClient(OfflineOllamaClient):
    def embed(self, text: str):
        text = text.lower()
        if "usage" in text or "token" in text or "llm" in text:
            return [0.0, 1.0]
        return [1.0, 0.0]

    def generate_json(self, prompt: str, model: str | None = None):
        return {
            "sql": """
            SELECT transfer_id, customer_name, amount, from_currency, to_currency
            FROM transfers
            WHERE amount > 1000
            ORDER BY created_at DESC
            LIMIT 10;
            """,
            "explanation": "Filtered persisted transfers by amount.",
        }


class PairLatestSqlClient(GeneratedSqlClient):
    def generate_json(self, prompt: str, model: str | None = None):
        return {
            "sql": """
            SELECT transfer_id, created_at, customer_name, from_currency, to_currency,
                   amount, converted_amount, rate, beneficiary_country, purpose, status, provider
            FROM transfers
            WHERE from_currency = 'GBP' AND to_currency = 'INR'
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            "explanation": "Used schema RAG to find the latest GBP to INR transfer.",
        }


class HighestTransferSqlClient(GeneratedSqlClient):
    def generate_json(self, prompt: str, model: str | None = None):
        return {
            "sql": """
            SELECT transfer_id, created_at, customer_name, from_currency, to_currency,
                   amount, converted_amount, rate, beneficiary_country, purpose, status, provider
            FROM transfers
            WHERE from_currency = 'GBP' OR to_currency = 'GBP'
            ORDER BY amount DESC
            LIMIT 1;
            """,
            "explanation": "Used schema RAG to find the highest transfer involving GBP.",
        }


class LlmUsageSqlClient(GeneratedSqlClient):
    def generate_json(self, prompt: str, model: str | None = None):
        return {
            "sql": """
            SELECT provider, model, call_type, total_tokens, created_at
            FROM llm_usage_logs
            ORDER BY total_tokens DESC
            LIMIT 10;
            """,
            "explanation": "Used schema RAG to inspect persisted LLM usage logs.",
        }


class QuestionLogSqlClient(GeneratedSqlClient):
    def generate_json(self, prompt: str, model: str | None = None):
        return {
            "sql": """
            SELECT route_mode, latency_ms
            FROM assistant_question_logs
            ORDER BY latency_ms DESC
            LIMIT 10;
            """,
            "explanation": "Used persistent schema RAG to inspect assistant question logs.",
        }


class DangerousSqlClient(OfflineOllamaClient):
    def generate_json(self, prompt: str, model: str | None = None):
        return {
            "sql": "DELETE FROM transfers;",
            "explanation": "This should never run.",
        }


def test_currency_conversion_returns_demo_amount() -> None:
    result = FxService().convert(100, "GBP", "EUR", use_live=False)
    assert result["converted_amount"] == 118
    assert result["to_currency"] == "EUR"
    assert result["is_live"] is False


def test_fx_conversion_returns_unit_rate_and_converted_amount() -> None:
    result = FxService().convert(5000, "GBP", "INR", use_live=False)

    assert result["from_currency"] == "GBP"
    assert result["to_currency"] == "INR"
    assert result["amount"] == 5000
    assert result["rate"] > 0
    assert result["converted_amount"] == round(5000 * result["rate"], 2)


def test_live_rates_fall_back_to_demo_when_disabled() -> None:
    result = FxService().get_rates(use_live=False)
    assert result["provider"] == "local-demo"
    assert "EUR" in result["rates"]


def test_provider_status_lists_optional_sources() -> None:
    status = ProviderService().status()
    optional_names = {
        provider["provider"] for provider in status["optional_api_key_providers"]
    }
    assert "alpha-vantage" in optional_names
    assert "fred" in optional_names
    assert status["active_without_keys"][0]["provider"] == "frankfurter"


def test_llm_provider_switch_keeps_embeddings_on_local_ollama() -> None:
    client = OllamaClient()
    client.provider = "openai"
    calls = []

    def fake_post_json(path, payload, timeout):
        calls.append((path, payload))
        return {"embedding": [0.1, 0.2]}

    client._post_json = fake_post_json

    assert client.embed("policy text") == [0.1, 0.2]
    assert calls[0][0] == "/api/embeddings"
    assert calls[0][1]["model"] == "nomic-embed-text"


def test_cloud_llm_provider_without_key_fails_gracefully() -> None:
    client = OllamaClient()
    client.provider = "openai"
    client.openai_api_key = None

    assert client.generate("hello") is None
    assert client.generate_json('{"answer": "hello"}') is None
    assert client.is_available() is False


def test_llm_usage_tracker_rolls_up_calls_and_tokens() -> None:
    tracker = LlmUsageTracker()
    tracker.record(
        "json", "ollama", "llama3.2:3b", "hello world", '{"ok": true}', success=True
    )
    tracker.record(
        "chat",
        "openai",
        "gpt-4o-mini",
        "prompt",
        "answer",
        success=True,
        input_tokens=10,
        output_tokens=4,
    )

    summary = tracker.summary()

    assert summary["totals"]["calls"] == 2
    assert summary["totals"]["successful_calls"] == 2
    assert summary["by_provider"]["ollama"]["calls"] == 1
    assert summary["by_provider"]["openai"]["total_tokens"] == 14
    assert summary["by_call_type"]["json"]["calls"] == 1


def test_llm_usage_tracker_attaches_current_question_id() -> None:
    tracker = LlmUsageTracker()
    token = current_question_id.set("Q-TEST")
    try:
        tracker.record(
            "chat", "ollama", "llama3.2:3b", "prompt", "answer", success=True
        )
    finally:
        current_question_id.reset(token)

    assert tracker.summary()["recent"][0]["question_id"] == "Q-TEST"


def test_database_service_persists_sqlite_transfer(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    result = database.create_transfer(
        {
            "customer_name": "Test Customer",
            "from_currency": "GBP",
            "to_currency": "INR",
            "amount": 100,
            "converted_amount": 12639,
            "rate": 126.39,
            "beneficiary_country": "India",
            "purpose": "Test",
            "provider": "frankfurter",
        }
    )
    assert result["stored"] is True
    assert database.list_transfers()["transfers"][0]["customer_name"] == "Test Customer"


def test_transfer_service_creates_and_persists_transfer_record(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    service = TransferService(StaticConversionFxService(), database)

    result = service.create_transfer(
        TransferRequest(
            customer_name="Transfer Service Customer",
            from_currency="GBP",
            to_currency="INR",
            amount=5000,
            beneficiary_country="India",
            purpose="Family support",
        )
    )

    assert result["stored"] is True
    assert result["transfer"]["customer_name"] == "Transfer Service Customer"
    assert result["transfer"]["converted_amount"] == 631950
    assert result["transfer"]["provider"] == "test-fx"


def test_database_service_persists_llm_usage_logs(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    stored = database.create_llm_usage_log(
        {
            "timestamp": "2026-07-04T10:00:00+00:00",
            "call_type": "chat",
            "provider": "ollama",
            "model": "llama3.2:3b",
            "success": True,
            "input_tokens": 100,
            "output_tokens": 25,
            "total_tokens": 125,
        }
    )

    summary = database.llm_usage_summary()

    assert stored["stored"] is True
    assert summary["totals"]["calls"] == 1
    assert summary["totals"]["total_tokens"] == 125
    assert summary["by_provider"]["ollama"]["calls"] == 1
    assert summary["recent"][0]["call_type"] == "chat"


def test_database_service_links_question_logs_to_llm_usage(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_assistant_question_log(
        {
            "question_id": "Q-LINKED",
            "created_at": "2026-07-04T10:00:00+00:00",
            "surface": "admin_reports_sql",
            "question_text": "which question used most tokens",
            "route_mode": "llm-generated-sql",
            "intent": "sql_analytics",
            "used_rag": True,
            "used_sql": True,
            "used_fx": False,
            "citations_count": 0,
            "status": "success",
            "latency_ms": 120,
        }
    )
    database.create_llm_usage_log(
        {
            "timestamp": "2026-07-04T10:00:01+00:00",
            "question_id": "Q-LINKED",
            "call_type": "json",
            "provider": "ollama",
            "model": "llama3.2:3b",
            "success": True,
            "input_tokens": 80,
            "output_tokens": 20,
            "total_tokens": 100,
        }
    )

    summary = database.assistant_question_summary()

    assert summary["totals"]["questions"] == 1
    assert summary["totals"]["llm_calls"] == 1
    assert summary["totals"]["total_tokens"] == 100
    assert summary["recent"][0]["question_id"] == "Q-LINKED"
    assert summary["recent"][0]["llm_calls"] == 1


def test_rate_variance_contains_change_fields_for_demo_fallback() -> None:
    result = FxService().rate_variance("GBP", "EUR")
    assert result["pair"] == "GBP/EUR"
    assert "latest_rate" in result
    assert "change_percent" in result


def test_transaction_summary_counts_rows() -> None:
    summary = TransactionService().summary()
    assert summary["total_transactions"] == 10
    assert summary["status_counts"]["failed"] == 2


def test_suspicious_transactions_include_reasons() -> None:
    suspicious = TransactionService().suspicious_transactions()
    assert suspicious
    assert "reasons" in suspicious[0]


def test_knowledge_answer_returns_citation_with_offline_fallback() -> None:
    answer = KnowledgeService(ollama_client=OfflineOllamaClient()).answer(
        "What documents are required?"
    )
    assert answer["citations"]
    assert answer["mode"] == "keyword-retrieval"
    assert "proof of identity" in answer["answer"].lower()


def test_rag_fallback_response_uses_local_keyword_retrieval() -> None:
    answer = KnowledgeService(ollama_client=OfflineOllamaClient()).answer(
        "How long can a payment delay take?"
    )

    assert answer["mode"] == "keyword-retrieval"
    assert answer["llm_available"] is False
    assert answer["citations"]
    assert "delay" in answer["answer"].lower()


def test_knowledge_answer_uses_pgvector_when_available() -> None:
    answer = KnowledgeService(
        ollama_client=VectorOllamaClient(),
        database_service=FakeVectorDatabase(),
    ).answer("What checks are needed for high value transfer?")

    assert answer["mode"] == "ollama-pgvector-rag"
    assert answer["citations"] == ["fake-policy.md"]
    assert answer["retrieved_chunks"][0]["score"] == 0.98


def test_knowledge_answer_blocks_weak_vector_matches() -> None:
    answer = KnowledgeService(
        ollama_client=VectorOllamaClient(),
        database_service=WeakVectorDatabase(),
    ).answer("who i am?")

    assert answer["mode"] == "no-context"
    assert answer["citations"] == []
    assert answer["retrieved_chunks"] == []


def test_sql_agent_without_database_explains_supabase_only() -> None:
    agent = SqlAgent(TransactionService())
    answer = agent.answer("Show failed payments")
    assert answer["generated_sql"] is None
    assert answer["result"] == []
    assert "Supabase/Postgres" in answer["explanation"]


def test_sql_agent_reads_last_persisted_transfer(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_transfer(
        {
            "customer_name": "Latest Customer",
            "from_currency": "GBP",
            "to_currency": "INR",
            "amount": 2500,
            "converted_amount": 315975,
            "rate": 126.39,
            "beneficiary_country": "India",
            "purpose": "Family support",
            "provider": "frankfurter",
        }
    )
    agent = SqlAgent(
        TransactionService(), database, ollama_client=OfflineOllamaClient()
    )

    answer = agent.answer("last transaction")

    assert "FROM transfers" in answer["generated_sql"]
    assert answer["result"][0]["customer_name"] == "Latest Customer"


def test_sql_agent_summarizes_persisted_transfers(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_transfer(
        {
            "customer_name": "Summary Customer",
            "from_currency": "GBP",
            "to_currency": "EUR",
            "amount": 1000,
            "converted_amount": 1180,
            "rate": 1.18,
            "beneficiary_country": "Germany",
            "purpose": "Supplier invoice",
            "provider": "frankfurter",
        }
    )
    agent = SqlAgent(
        TransactionService(), database, ollama_client=OfflineOllamaClient()
    )

    answer = agent.answer("transfer summary")

    assert "COUNT(*)" in answer["generated_sql"]
    assert answer["result"]["total_persisted_transfers"] == 1


def test_sql_agent_answers_currency_transaction_question_with_safe_template(
    tmp_path,
) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_transfer(
        {
            "customer_name": "INR Customer",
            "from_currency": "GBP",
            "to_currency": "INR",
            "amount": 5000,
            "converted_amount": 631950,
            "rate": 126.39,
            "beneficiary_country": "India",
            "purpose": "Family support",
            "provider": "frankfurter",
        }
    )
    agent = SqlAgent(TransactionService(), database, ollama_client=DangerousSqlClient())

    answer = agent.answer("any INR transaction?")

    assert answer["mode"] == "safe-sql-template"
    assert "to_currency = 'INR'" in answer["safe_sql"]
    assert answer["result"][0]["customer_name"] == "INR Customer"


def test_sql_agent_answers_highest_amount_today_from_currency(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    lower = database.create_transfer(
        {
            "customer_name": "Lower CAD Customer",
            "from_currency": "CAD",
            "to_currency": "INR",
            "amount": 1000,
            "converted_amount": 61000,
            "rate": 61,
            "beneficiary_country": "India",
            "purpose": "Family support",
            "provider": "frankfurter",
        }
    )["transfer"]["transfer_id"]
    higher = database.create_transfer(
        {
            "customer_name": "Higher CAD Customer",
            "from_currency": "CAD",
            "to_currency": "USD",
            "amount": 4000,
            "converted_amount": 2900,
            "rate": 0.725,
            "beneficiary_country": "United States",
            "purpose": "Supplier invoice",
            "provider": "frankfurter",
        }
    )["transfer"]["transfer_id"]
    assert lower != higher
    agent = SqlAgent(TransactionService(), database, ollama_client=DangerousSqlClient())

    answer = agent.answer("highest transferred amount today from CAD")

    assert answer["mode"] == "safe-sql-template"
    assert "from_currency = 'CAD'" in answer["safe_sql"]
    assert "ORDER BY amount DESC" in answer["safe_sql"]
    assert "CURRENT_DATE" in answer["safe_sql"]
    assert answer["result"][0]["customer_name"] == "Higher CAD Customer"


def test_sql_agent_executes_valid_llm_generated_sql(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_transfer(
        {
            "customer_name": "LLM Customer",
            "from_currency": "GBP",
            "to_currency": "INR",
            "amount": 2500,
            "converted_amount": 315975,
            "rate": 126.39,
            "beneficiary_country": "India",
            "purpose": "Family support",
            "provider": "frankfurter",
        }
    )
    agent = SqlAgent(TransactionService(), database, ollama_client=GeneratedSqlClient())

    answer = agent.answer("show high value transfers")

    assert answer["mode"] == "llm-generated-sql"
    assert "FROM transfers" in answer["safe_sql"]
    assert answer["result"][0]["customer_name"] == "LLM Customer"


def test_sql_agent_uses_schema_rag_for_currency_pair_latest_payment(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_transfer(
        {
            "customer_name": "Older Pair Customer",
            "from_currency": "GBP",
            "to_currency": "INR",
            "amount": 1000,
            "converted_amount": 126390,
            "rate": 126.39,
            "beneficiary_country": "India",
            "purpose": "Family support",
            "provider": "frankfurter",
        }
    )
    database.create_transfer(
        {
            "customer_name": "Latest Pair Customer",
            "from_currency": "GBP",
            "to_currency": "INR",
            "amount": 2500,
            "converted_amount": 315975,
            "rate": 126.39,
            "beneficiary_country": "India",
            "purpose": "Education fees",
            "provider": "frankfurter",
        }
    )
    agent = SqlAgent(
        TransactionService(), database, ollama_client=PairLatestSqlClient()
    )

    answer = agent.answer("gbp to inr last payment")

    assert answer["mode"] == "llm-generated-sql"
    assert "from_currency = 'GBP' AND to_currency = 'INR'" in answer["safe_sql"]
    assert answer["schema_context"][0]["table"] == "transfers"
    assert answer["result"][0]["customer_name"] == "Latest Pair Customer"


def test_sql_agent_uses_schema_rag_for_highest_transfer_when_llm_sql_is_valid(
    tmp_path,
) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_transfer(
        {
            "customer_name": "Lower GBP Customer",
            "from_currency": "GBP",
            "to_currency": "INR",
            "amount": 1000,
            "converted_amount": 126390,
            "rate": 126.39,
            "beneficiary_country": "India",
            "purpose": "Family support",
            "provider": "frankfurter",
        }
    )
    database.create_transfer(
        {
            "customer_name": "Higher GBP Customer",
            "from_currency": "GBP",
            "to_currency": "USD",
            "amount": 5000,
            "converted_amount": 6660,
            "rate": 1.332,
            "beneficiary_country": "United States",
            "purpose": "Supplier invoice",
            "provider": "frankfurter",
        }
    )
    agent = SqlAgent(
        TransactionService(), database, ollama_client=HighestTransferSqlClient()
    )

    answer = agent.answer("GBP TO INR HIGHEST TRANSFER")

    assert answer["mode"] == "llm-generated-sql"
    assert "FROM transfers" in answer["safe_sql"]
    assert answer["schema_context"][0]["table"] == "transfers"
    assert answer["result"][0]["customer_name"] == "Higher GBP Customer"


def test_sql_agent_schema_rag_can_select_llm_usage_logs(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_llm_usage_log(
        {
            "timestamp": "2026-07-04T10:00:00+00:00",
            "call_type": "chat",
            "provider": "ollama",
            "model": "llama3.2:3b",
            "success": True,
            "input_tokens": 100,
            "output_tokens": 25,
            "total_tokens": 125,
        }
    )
    agent = SqlAgent(TransactionService(), database, ollama_client=LlmUsageSqlClient())

    answer = agent.answer("which llm provider used most tokens")

    assert answer["mode"] == "llm-generated-sql"
    assert "FROM llm_usage_logs" in answer["safe_sql"]
    assert answer["schema_context"][0]["table"] == "llm_usage_logs"
    assert answer["result"][0]["provider"] == "ollama"


def test_sql_agent_prefers_persistent_schema_vector_context() -> None:
    agent = SqlAgent(
        TransactionService(),
        FakeSchemaVectorDatabase(),
        ollama_client=QuestionLogSqlClient(),
    )

    answer = agent.answer("which assistant route had the slowest latency")

    assert answer["mode"] == "llm-generated-sql"
    assert "FROM assistant_question_logs" in answer["safe_sql"]
    assert answer["schema_context"][0]["source"] == "supabase-pgvector"
    assert answer["result"][0]["route_mode"] == "llm-generated-sql"


def test_sql_agent_blocks_dangerous_llm_generated_sql(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    agent = SqlAgent(TransactionService(), database, ollama_client=DangerousSqlClient())

    answer = agent.answer("delete all transfers")

    assert answer["mode"] == "llm-sql-blocked"
    assert answer["safe_sql"] is None
    assert answer["result"] == []


def test_sql_validation_blocks_delete_update_and_drop(tmp_path) -> None:
    agent = SqlAgent(
        TransactionService(),
        DatabaseService(f"sqlite:///{tmp_path / 'test.db'}"),
        ollama_client=OfflineOllamaClient(),
    )

    for sql in (
        "DELETE FROM transfers;",
        "UPDATE transfers SET status = 'submitted';",
        "DROP TABLE transfers;",
    ):
        validation = agent.validate_sql(sql)
        assert validation["valid"] is False


def test_admin_report_summary_includes_persisted_transfer_data(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_transfer(
        {
            "customer_name": "Report Customer",
            "from_currency": "GBP",
            "to_currency": "INR",
            "amount": 750,
            "converted_amount": 94792.5,
            "rate": 126.39,
            "beneficiary_country": "India",
            "purpose": "Family support",
            "provider": "test-fx",
        }
    )
    report = ReportingService(
        StaticReportFxService(), TransactionService(), database
    ).daily_report()

    assert report["title"] == "Daily FX and Payments Operations Report"
    assert report["persisted_transfer_summary"]["total_persisted_transfers"] == 1
    assert report["persisted_transfer_summary"]["total_source_amount"] == 750
    assert report["fx_snapshot"]["provider"] == "test-fx"


def test_assistant_routes_fx_questions_to_fx_tool() -> None:
    assistant = AssistantService(
        FxService(), KnowledgeService(ollama_client=OfflineOllamaClient())
    )
    answer = assistant.answer("What is the GBP to INR rate?", use_llm=False)
    assert answer["mode"] == "fx-tool"
    assert "GBP" in answer["answer"]


def test_assistant_routes_trend_questions_to_fx_trend_tool() -> None:
    assistant = AssistantService(
        StaticTrendFxService(), KnowledgeService(ollama_client=OfflineOllamaClient())
    )
    answer = assistant.answer(
        "Show GBP/USD daily trend for the last 30 days and compare with 20-day average"
    )
    assert answer["mode"] == "fx-tool"
    assert "20-day average" in answer["answer"]
    assert "1.321" in answer["answer"]


def test_assistant_routes_forecast_questions_to_trend_outlook() -> None:
    assistant = AssistantService(
        StaticTrendFxService(), KnowledgeService(ollama_client=OfflineOllamaClient())
    )
    answer = assistant.answer(
        "will GBP/INR increase in next 30 days when compared to today rate?"
    )
    assert answer["mode"] == "fx-outlook"
    assert "cannot guarantee" in answer["answer"]
    assert "recent momentum is positive" in answer["answer"]


def test_assistant_routes_last_month_highest_rate_to_fx_tool() -> None:
    assistant = AssistantService(
        FxService(), KnowledgeService(ollama_client=OfflineOllamaClient())
    )
    answer = assistant.answer("last month highesgt rate of GBP to INR", use_llm=False)
    assert answer["mode"] == "fx-tool"
    assert "highest GBP to INR rate last month" in answer["answer"]


def test_assistant_can_use_llm_tool_plan() -> None:
    client = OfflineOllamaClient()
    assistant = AssistantService(
        FxService(),
        KnowledgeService(ollama_client=client),
        tool_planner=StaticToolPlanner(),
        ollama_client=client,
    )
    answer = assistant.answer("when was pound strongest against rupee last month")
    assert answer["mode"] == "llm-tool-agent"
    assert answer["tool_plan"]["intent"] == "fx_best_rate"
    assert "highest GBP to INR rate last month" in answer["answer"]


def test_assistant_can_use_ai_router_for_fx_trend() -> None:
    client = OfflineOllamaClient()
    assistant = AssistantService(
        StaticTrendFxService(),
        KnowledgeService(ollama_client=client),
        tool_planner=StaticTrendPlanner(),
        ollama_client=client,
    )

    answer = assistant.answer("how has pound moved against rupee recently")

    assert answer["mode"] == "llm-tool-agent"
    assert "20-day average" in answer["answer"]
    assert answer["citations"] == ["frankfurter"]


def test_assistant_routes_failed_payment_support_to_knowledge_rag() -> None:
    assistant = AssistantService(
        FxService(), KnowledgeService(ollama_client=OfflineOllamaClient())
    )

    answer = assistant.answer("my payment failed, what to do, how to contact support")

    assert answer["mode"] == "keyword-retrieval"
    assert answer["citations"]
    assert "failed transfers" in answer["answer"].lower()


def test_assistant_blocks_ai_routed_sql_in_customer_view(tmp_path) -> None:
    database = DatabaseService(f"sqlite:///{tmp_path / 'test.db'}")
    database.create_transfer(
        {
            "customer_name": "Router SQL Customer",
            "from_currency": "GBP",
            "to_currency": "INR",
            "amount": 5000,
            "converted_amount": 631950,
            "rate": 126.39,
            "beneficiary_country": "India",
            "purpose": "Family support",
            "provider": "frankfurter",
        }
    )
    client = OfflineOllamaClient()
    assistant = AssistantService(
        FxService(),
        KnowledgeService(ollama_client=client),
        tool_planner=StaticTransactionPlanner(),
        ollama_client=client,
        sql_agent=SqlAgent(
            TransactionService(), database, ollama_client=DangerousSqlClient()
        ),
    )

    answer = assistant.answer("highest GBP amount transferred")

    assert answer["mode"] == "restricted-admin-data"
    assert "Admin Reports" in answer["answer"]
    assert answer["retrieved_chunks"] == []
