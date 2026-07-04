import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter

from app.models.schemas import AskRequest, ConvertRequest, SqlRequest, TransferRequest
from app.services.assistant_service import AssistantService
from app.services.fx_service import FxService
from app.services.knowledge_service import KnowledgeService
from app.services.alpha_vantage_service import AlphaVantageService
from app.services.fred_service import FredService
from app.services.database_service import DatabaseService
from app.services.provider_service import ProviderService
from app.services.reporting_service import ReportingService
from app.services.sql_agent import SqlAgent
from app.services.transfer_service import TransferService
from app.services.transaction_service import TransactionService
from app.services.ollama_client import current_question_id, usage_tracker

router = APIRouter()
fx_service = FxService()
transaction_service = TransactionService()
database_service = DatabaseService()
usage_tracker.set_database_service(database_service)
knowledge_service = KnowledgeService(database_service=database_service)
sql_agent = SqlAgent(transaction_service, database_service)
assistant_service = AssistantService(fx_service, knowledge_service, sql_agent=sql_agent)
transfer_service = TransferService(fx_service, database_service)
reporting_service = ReportingService(fx_service, transaction_service, database_service)
alpha_vantage_service = AlphaVantageService()
fred_service = FredService()
provider_service = ProviderService(alpha_vantage_service, fred_service)


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/database/status")
def database_status() -> dict:
    return database_service.status()


@router.get("/fx/rates")
def get_rates(live: bool = True) -> dict:
    return fx_service.get_rates(use_live=live)


@router.get("/fx/live-rates")
def live_rate_table() -> dict:
    return fx_service.live_rate_table()


@router.get("/providers/status")
def provider_status() -> dict:
    return provider_service.status()


@router.get("/llm/usage")
def llm_usage() -> dict:
    return usage_tracker.summary()


@router.get("/llm/usage/persisted")
def persisted_llm_usage() -> dict:
    return database_service.llm_usage_summary()


@router.get("/assistant/questions/persisted")
def persisted_assistant_questions() -> dict:
    return database_service.assistant_question_summary()


@router.get("/providers/alpha-vantage/fx-daily")
def alpha_vantage_fx_daily(from_currency: str = "GBP", to_currency: str = "USD") -> dict:
    return alpha_vantage_service.fx_daily(from_currency, to_currency)


@router.get("/economics/fred/latest")
def fred_latest_indicators() -> dict:
    return fred_service.latest_observations()


@router.post("/fx/convert")
def convert_currency(payload: ConvertRequest, live: bool = True) -> dict:
    return fx_service.convert(payload.amount, payload.from_currency, payload.to_currency, use_live=live)


@router.get("/transactions/summary")
def transaction_summary() -> dict:
    return transaction_service.summary()


@router.get("/transactions/failed")
def failed_transactions() -> dict:
    return {"transactions": transaction_service.failed_transactions()}


@router.get("/transactions/suspicious")
def suspicious_transactions() -> dict:
    return {"transactions": transaction_service.suspicious_transactions()}


@router.post("/transfers")
def create_transfer(payload: TransferRequest) -> dict:
    return transfer_service.create_transfer(payload)


@router.get("/transfers")
def list_transfers(limit: int = 50) -> dict:
    return database_service.list_transfers(limit=limit)


@router.post("/knowledge/ask")
def ask_knowledge(payload: AskRequest) -> dict:
    return _run_logged_question(
        surface="ask_ai",
        question=payload.question,
        runner=lambda: assistant_service.answer(payload.question, use_llm=payload.use_llm),
    )


@router.get("/knowledge/vector/status")
def knowledge_vector_status() -> dict:
    return knowledge_service.vector_status()


@router.post("/knowledge/vector/index")
def index_knowledge_vectors() -> dict:
    return knowledge_service.index_vector_store()


@router.post("/sql/ask")
def ask_sql(payload: SqlRequest) -> dict:
    return _run_logged_question(
        surface="admin_reports_sql",
        question=payload.question,
        runner=lambda: sql_agent.answer(payload.question),
    )


@router.get("/sql/schema-vector/status")
def sql_schema_vector_status() -> dict:
    return sql_agent.schema_vector_status()


@router.post("/sql/schema-vector/index")
def index_sql_schema_vectors() -> dict:
    return sql_agent.index_schema_vector_store()


@router.get("/reports/daily")
def daily_report() -> dict:
    return reporting_service.daily_report()


def _run_logged_question(surface: str, question: str, runner) -> dict:
    """Wrap Ask AI/Admin SQL calls with a shared question_id for observability logs."""
    question_id = f"Q-{uuid.uuid4().hex[:12].upper()}"
    token = current_question_id.set(question_id)
    started = time.perf_counter()
    created_at = datetime.now(timezone.utc).isoformat()
    result: dict = {}
    status = "success"

    try:
        result = runner()
        return {**result, "question_id": question_id}
    except Exception:
        status = "failed"
        raise
    finally:
        latency_ms = round((time.perf_counter() - started) * 1000)
        current_question_id.reset(token)
        if result:
            mode = result.get("mode", "unknown")
            status = "blocked" if mode in {"llm-sql-blocked", "restricted-admin-data"} else status
            database_service.create_assistant_question_log({
                "question_id": question_id,
                "created_at": created_at,
                "surface": surface,
                "question_text": question,
                "route_mode": mode,
                "intent": _question_intent(result),
                "used_rag": "rag" in mode,
                "used_sql": surface == "admin_reports_sql" or "sql" in mode,
                "used_fx": _question_used_fx(result),
                "citations_count": len(result.get("citations", [])),
                "status": status,
                "latency_ms": latency_ms,
            })


def _question_intent(result: dict) -> str | None:
    tool_plan = result.get("tool_plan")
    if isinstance(tool_plan, dict):
        return tool_plan.get("intent")
    return result.get("intent")


def _question_used_fx(result: dict) -> bool:
    mode = result.get("mode", "")
    if mode in {"fx-tool", "fx-outlook", "llm-tool-agent"}:
        return True
    citations = result.get("citations", [])
    return any(str(citation).lower() in {"frankfurter", "alpha-vantage", "fred"} for citation in citations)
