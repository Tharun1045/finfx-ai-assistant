from dataclasses import dataclass

from app.services.ollama_client import OllamaClient


@dataclass(frozen=True)
class ToolPlan:
    intent: str
    base_currency: str | None = None
    quote_currency: str | None = None
    period: str | None = None
    amount: float | None = None
    confidence: float = 0.0


class ToolPlanner:
    allowed_intents = {
        "fx_latest_rate",
        "fx_best_rate",
        "fx_trend",
        "fx_outlook",
        "knowledge_rag",
        "transaction_analytics",
        "unknown",
    }
    allowed_periods = {"today", "this_month", "last_month", "unknown"}

    def __init__(self, ollama_client: OllamaClient | None = None) -> None:
        self.ollama_client = ollama_client or OllamaClient()

    def plan(self, question: str) -> ToolPlan | None:
        prompt = f"""You are an intent planner for a fintech AI assistant.
Return ONLY valid JSON. Do not explain.

Available intents:
- fx_latest_rate: latest exchange rate for a currency pair
- fx_best_rate: highest/best/peak/strongest exchange rate for a currency pair over a period
- fx_trend: historical trend, average, or comparison over days for a currency pair
- fx_outlook: future-looking FX outlook or increase/decrease question for a currency pair
- knowledge_rag: policy, transfer, compliance, document, verification, FAQ, customer support, or "what should I do" questions
- transaction_analytics: admin/reporting questions asking to list, count, aggregate, or inspect stored payment rows, failed transactions, suspicious transactions, volumes, statuses
- unknown: anything else

Fields:
- intent: one of the available intents
- base_currency: 3-letter ISO currency code or null
- quote_currency: 3-letter ISO currency code or null
- period: today, this_month, last_month, or unknown
- amount: numeric amount if the user asks to convert money, otherwise null
- confidence: number from 0 to 1

Understand misspellings and natural wording. Examples:
"last month highesgt rate of GBP to INR" -> {{"intent":"fx_best_rate","base_currency":"GBP","quote_currency":"INR","period":"last_month","amount":null,"confidence":0.95}}
"when was pound strongest against rupee last month" -> {{"intent":"fx_best_rate","base_currency":"GBP","quote_currency":"INR","period":"last_month","amount":null,"confidence":0.9}}
"gbp/inr trend last 30 days" -> {{"intent":"fx_trend","base_currency":"GBP","quote_currency":"INR","period":"unknown","amount":null,"confidence":0.92}}
"will gbp/inr increase next month" -> {{"intent":"fx_outlook","base_currency":"GBP","quote_currency":"INR","period":"unknown","amount":null,"confidence":0.9}}
"what docs are needed for high value transfer" -> {{"intent":"knowledge_rag","base_currency":null,"quote_currency":null,"period":"unknown","amount":null,"confidence":0.9}}
"my payment failed, what should I do and how do I contact support" -> {{"intent":"knowledge_rag","base_currency":null,"quote_currency":null,"period":"unknown","amount":null,"confidence":0.92}}
"highest GBP amount transferred" -> {{"intent":"transaction_analytics","base_currency":"GBP","quote_currency":null,"period":"unknown","amount":null,"confidence":0.88}}

Question: {question}
JSON:"""
        data = self.ollama_client.generate_json(prompt)
        if not data:
            return None

        intent = data.get("intent")
        period = data.get("period") or "unknown"
        if intent not in self.allowed_intents:
            return None
        if period not in self.allowed_periods:
            period = "unknown"

        return ToolPlan(
            intent=intent,
            base_currency=self._currency(data.get("base_currency")),
            quote_currency=self._currency(data.get("quote_currency")),
            period=period,
            amount=self._amount(data.get("amount")),
            confidence=self._confidence(data.get("confidence")),
        )

    @staticmethod
    def _currency(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        cleaned = value.upper().strip()
        return cleaned if len(cleaned) == 3 and cleaned.isalpha() else None

    @staticmethod
    def _amount(value: object) -> float | None:
        if isinstance(value, int | float):
            return float(value)
        return None

    @staticmethod
    def _confidence(value: object) -> float:
        if isinstance(value, int | float):
            return max(0.0, min(float(value), 1.0))
        return 0.0
