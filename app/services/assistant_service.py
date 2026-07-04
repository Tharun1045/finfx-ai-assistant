import re

from app.services.fx_service import FxService
from app.services.knowledge_service import KnowledgeService
from app.services.ollama_client import OllamaClient
from app.services.tool_planner import ToolPlan, ToolPlanner


class AssistantService:
    def __init__(
        self,
        fx_service: FxService,
        knowledge_service: KnowledgeService,
        tool_planner: ToolPlanner | None = None,
        ollama_client: OllamaClient | None = None,
        sql_agent=None,
    ) -> None:
        self.fx_service = fx_service
        self.knowledge_service = knowledge_service
        self.ollama_client = ollama_client or OllamaClient()
        self.tool_planner = tool_planner or ToolPlanner(self.ollama_client)
        self.sql_agent = sql_agent

    def answer(self, question: str, use_llm: bool = True) -> dict:
        """Route a customer question to the safest available tool before falling back to document RAG."""
        pair = self._extract_currency_pair(question)
        # Deterministic checks stay first for obvious/sensitive routing; the LLM router handles flexible wording after that.
        if pair and self._looks_like_fx_outlook_question(question):
            return self._answer_fx_outlook(question, pair)

        if pair and self._looks_like_fx_trend_question(question):
            return self._answer_fx_question(question, pair)

        if self._looks_like_customer_support_question(question):
            return self.knowledge_service.answer(question, use_llm=use_llm)

        if use_llm:
            plan = self.tool_planner.plan(question)
            if plan:
                planned_answer = self._answer_from_plan(question, plan)
                if planned_answer:
                    return planned_answer

        if pair and self._looks_like_fx_question(question):
            return self._answer_fx_question(question, pair)

        return self.knowledge_service.answer(question, use_llm=use_llm)

    def _answer_fx_outlook(self, question: str, pair: tuple[str, str]) -> dict:
        from_currency, to_currency = pair
        trend = self.fx_service.trend_summary(from_currency, to_currency, days=30, average_days=20)
        if "error" in trend:
            return self._unsupported_currency_response(trend)
        return self._format_outlook_answer(question, trend)

    def _answer_from_plan(self, question: str, plan: ToolPlan) -> dict | None:
        """Execute an LLM-generated tool plan when the router confidence is high enough."""
        if plan.confidence < 0.7:
            return None

        if plan.intent == "knowledge_rag":
            return self.knowledge_service.answer(question, use_llm=True)

        if plan.intent == "transaction_analytics":
            return self._customer_sql_restricted_response(plan)

        if plan.intent not in {"fx_latest_rate", "fx_best_rate", "fx_trend", "fx_outlook"}:
            return None

        if not plan.base_currency or not plan.quote_currency:
            return None

        if plan.intent == "fx_outlook":
            return self._answer_fx_outlook(question, (plan.base_currency, plan.quote_currency))

        if plan.intent == "fx_trend":
            trend = self.fx_service.trend_summary(plan.base_currency, plan.quote_currency, days=30, average_days=20)
            if "error" in trend:
                return self._unsupported_currency_response(trend)
            return self._format_trend_answer(question, trend, mode="llm-tool-agent")

        if plan.intent == "fx_best_rate":
            if plan.period == "last_month":
                rate = self.fx_service.best_rate_last_month(plan.base_currency, plan.quote_currency)
                period_label = "last month"
            else:
                rate = self.fx_service.best_rate_this_month(plan.base_currency, plan.quote_currency)
                period_label = "this month"
            if "error" in rate:
                return self._unsupported_currency_response(rate)
            return self._format_best_rate_answer(question, rate, period_label, mode="llm-tool-agent", plan=plan)

        converted = self.fx_service.convert(plan.amount or 1, plan.base_currency, plan.quote_currency, use_live=True)
        if "error" in converted:
            return self._unsupported_currency_response(converted)
        return self._format_latest_rate_answer(question, converted, mode="llm-tool-agent", plan=plan)

    def _answer_fx_question(self, question: str, pair: tuple[str, str]) -> dict:
        """Answer live-rate, best-rate, and trend questions using the FX service."""
        from_currency, to_currency = pair
        normalized = question.lower()

        if any(term in normalized for term in ("trend", "average", "moving average", "last 30 days", "20-day", "20 day")):
            trend = self.fx_service.trend_summary(
                from_currency,
                to_currency,
                days=self._extract_day_window(normalized, default=30),
                average_days=self._extract_average_window(normalized, default=20),
            )
            if "error" in trend:
                return self._unsupported_currency_response(trend)
            return self._format_trend_answer(question, trend, mode="fx-tool")

        wants_best_rate = any(term in normalized for term in ("best", "highest", "highesgt", "peak"))
        asks_month = "month" in normalized

        if wants_best_rate and asks_month:
            period_label = "this month"
            if "last month" in normalized or "previous month" in normalized:
                rate = self.fx_service.best_rate_last_month(from_currency, to_currency)
                period_label = "last month"
            else:
                rate = self.fx_service.best_rate_this_month(from_currency, to_currency)

            if "error" in rate:
                return self._unsupported_currency_response(rate)

            return self._format_best_rate_answer(question, rate, period_label, mode="fx-tool")

        converted = self.fx_service.convert(1, from_currency, to_currency, use_live=True)
        if "error" in converted:
            return self._unsupported_currency_response(converted)

        return self._format_latest_rate_answer(question, converted, mode="fx-tool")

    def _format_trend_answer(self, question: str, trend: dict, mode: str) -> dict:
        if trend["average_rate"] is None:
            deterministic_answer = (
                f"The latest {trend['from_currency']}/{trend['to_currency']} rate is {trend['latest_rate']} "
                f"as of {trend['latest_date']}. I could not calculate the {trend['average_days']}-day average "
                f"because the historical series was not available from the provider."
            )
        else:
            relation = "above" if trend["latest_rate"] > trend["average_rate"] else "below" if trend["latest_rate"] < trend["average_rate"] else "equal to"
            direction = "increased" if trend["direction"] == "up" else "decreased" if trend["direction"] == "down" else "was flat"
            deterministic_answer = (
                f"Over the last {trend['period_days']} observations, {trend['from_currency']}/{trend['to_currency']} "
                f"{direction} from {trend['start_rate']} on {trend['start_date']} to {trend['latest_rate']} on "
                f"{trend['latest_date']} ({trend['change_percent']}%). The {trend['average_days']}-day average is "
                f"{trend['average_rate']}, so today's/latest rate is {relation} that average. This uses "
                f"{trend['observations']} Frankfurter observations."
            )

        answer = self._summarize_tool_result(question, trend, deterministic_answer) if mode == "llm-tool-agent" else deterministic_answer
        preview_points = trend.get("series", [])[-5:]
        return {
            "answer": answer,
            "citations": [trend["provider"]],
            "mode": mode,
            "llm_available": mode == "llm-tool-agent",
            "tool_plan": None,
            "retrieved_chunks": [{
                "source": trend["provider"],
                "heading": f"{trend['from_currency']}/{trend['to_currency']} {trend['period_days']}-day trend",
                "score": 1.0,
                "preview": f"{trend['source']}; latest points: {preview_points}",
            }],
        }

    def _format_outlook_answer(self, question: str, trend: dict) -> dict:
        if trend["average_rate"] is None:
            answer = (
                f"I cannot make a reliable next-30-day outlook for {trend['from_currency']}/{trend['to_currency']} "
                f"because historical observations were not available. The latest available rate is "
                f"{trend['latest_rate']} as of {trend['latest_date']}."
            )
        else:
            relation = "above" if trend["latest_rate"] > trend["average_rate"] else "below" if trend["latest_rate"] < trend["average_rate"] else "equal to"
            if trend["direction"] == "up" and trend["latest_rate"] >= trend["average_rate"]:
                bias = "recent momentum is positive"
            elif trend["direction"] == "down" and trend["latest_rate"] <= trend["average_rate"]:
                bias = "recent momentum is negative"
            else:
                bias = "recent momentum is mixed"

            answer = (
                f"I cannot guarantee whether {trend['from_currency']}/{trend['to_currency']} will increase in the next 30 days, "
                f"but the recent data gives a directional outlook. Over the last {trend['period_days']} observations, the rate moved "
                f"from {trend['start_rate']} on {trend['start_date']} to {trend['latest_rate']} on {trend['latest_date']} "
                f"({trend['change_percent']}%). The latest rate is {relation} the {trend['average_days']}-day average of "
                f"{trend['average_rate']}, so {bias}. Treat this as trend context, not a prediction."
            )

        return {
            "answer": answer,
            "citations": [trend["provider"]],
            "mode": "fx-outlook",
            "llm_available": False,
            "tool_plan": None,
            "metrics": {
                "pair": f"{trend['from_currency']}/{trend['to_currency']}",
                "latest_rate": trend["latest_rate"],
                "latest_date": trend["latest_date"],
                "start_rate": trend.get("start_rate"),
                "start_date": trend.get("start_date"),
                "average_rate": trend.get("average_rate"),
                "average_days": trend.get("average_days"),
                "change_percent": trend.get("change_percent"),
                "bias": bias if trend["average_rate"] is not None else "insufficient historical data",
                "direction": trend.get("direction"),
            },
            "retrieved_chunks": [{
                "source": trend["provider"],
                "heading": f"{trend['from_currency']}/{trend['to_currency']} trend-based outlook",
                "score": 1.0,
                "preview": f"{trend['source']}; {trend['observations']} historical observations used.",
            }],
        }

    def _format_best_rate_answer(
        self,
        question: str,
        rate: dict,
        period_label: str,
        mode: str,
        plan: ToolPlan | None = None,
    ) -> dict:
        deterministic_answer = (
            f"The highest {rate['from_currency']} to {rate['to_currency']} rate {period_label} was "
            f"{rate['best_rate']} on {rate['best_date']}. The latest available rate is "
            f"{rate['latest_rate']} from {rate['latest_date']} for that period. This is based on "
            f"{rate['observations']} live Frankfurter observations."
        )
        answer = self._summarize_tool_result(question, rate, deterministic_answer) if mode == "llm-tool-agent" else deterministic_answer
        return {
            "answer": answer,
            "citations": [rate["provider"]],
            "mode": mode,
            "llm_available": mode == "llm-tool-agent",
            "tool_plan": self._plan_payload(plan),
            "retrieved_chunks": [{
                "source": rate["provider"],
                "heading": f"{rate['from_currency']}/{rate['to_currency']} live rate series",
                "score": 1.0,
                "preview": f"{rate['period_start']} to {rate['period_end']}; source: {rate['source']}",
            }],
        }

    def _format_latest_rate_answer(
        self,
        question: str,
        converted: dict,
        mode: str,
        plan: ToolPlan | None = None,
    ) -> dict:
        deterministic_answer = (
            f"The latest {converted['from_currency']} to {converted['to_currency']} rate is "
            f"{converted['rate']} as of {converted['as_of']}. For {converted['amount']} {converted['from_currency']}, "
            f"that is {converted['converted_amount']} {converted['to_currency']}."
        )
        answer = self._summarize_tool_result(question, converted, deterministic_answer) if mode == "llm-tool-agent" else deterministic_answer
        return {
            "answer": answer,
            "citations": [converted["provider"]],
            "mode": mode,
            "llm_available": mode == "llm-tool-agent",
            "tool_plan": self._plan_payload(plan),
            "retrieved_chunks": [{
                "source": converted["provider"],
                "heading": f"{converted['from_currency']}/{converted['to_currency']} live rate",
                "score": 1.0,
                "preview": converted["source"],
            }],
        }

    def _summarize_tool_result(self, question: str, tool_result: dict, fallback: str) -> str:
        """Let the selected LLM make a tool result easier to read without changing the facts."""
        prompt = f"""You are FinFX AI Assistant.
Use only the tool result below. Do not add financial advice.
Answer the user's question in 2-4 concise sentences.
Mention the data provider when available.

Question: {question}
Tool result: {tool_result}

Answer:"""
        return self.ollama_client.generate(prompt) or fallback

    def _customer_sql_restricted_response(self, plan: ToolPlan) -> dict:
        return {
            "answer": (
                "I cannot show customer transaction records in the public assistant. "
                "Please use Admin Reports for Supabase transfer analytics."
            ),
            "citations": [],
            "mode": "restricted-admin-data",
            "llm_available": False,
            "tool_plan": self._plan_payload(plan),
            "retrieved_chunks": [],
        }

    @staticmethod
    def _plan_payload(plan: ToolPlan | None) -> dict | None:
        if not plan:
            return None
        return {
            "intent": plan.intent,
            "base_currency": plan.base_currency,
            "quote_currency": plan.quote_currency,
            "period": plan.period,
            "amount": plan.amount,
            "confidence": plan.confidence,
        }

    @staticmethod
    def _extract_currency_pair(question: str) -> tuple[str, str] | None:
        match = re.search(r"\b([A-Z]{3})\s*(?:TO|/)\s*([A-Z]{3})\b", question.upper())
        if not match:
            return None
        return match.group(1), match.group(2)

    @staticmethod
    def _extract_day_window(normalized: str, default: int) -> int:
        match = re.search(r"last\s+(\d{1,3})\s+days?", normalized)
        if not match:
            match = re.search(r"(\d{1,3})[-\s]?day\s+trend", normalized)
        return max(2, min(int(match.group(1)), 120)) if match else default

    @staticmethod
    def _extract_average_window(normalized: str, default: int) -> int:
        match = re.search(r"(\d{1,3})[-\s]?day\s+average", normalized)
        return max(2, min(int(match.group(1)), 120)) if match else default

    @staticmethod
    def _looks_like_fx_question(question: str) -> bool:
        normalized = question.lower()
        terms = ("rate", "exchange", "convert", "currency", "fx", "gbp", "eur", "usd", "inr")
        return any(term in normalized for term in terms)

    @staticmethod
    def _looks_like_fx_trend_question(question: str) -> bool:
        normalized = question.lower()
        terms = ("trend", "average", "moving average", "last 30 days", "20-day", "20 day")
        return any(term in normalized for term in terms)

    @staticmethod
    def _looks_like_fx_outlook_question(question: str) -> bool:
        normalized = question.lower()
        future_terms = ("will", "next", "forecast", "predict", "prediction", "outlook", "increase", "decrease")
        horizon_terms = ("next 30", "30 days", "next month", "coming month")
        return any(term in normalized for term in future_terms) and any(term in normalized for term in horizon_terms)

    @staticmethod
    def _looks_like_customer_support_question(question: str) -> bool:
        normalized = question.lower()
        payment_issue_terms = (
            "my payment failed",
            "payment failed",
            "transfer failed",
            "payment delayed",
            "transfer delayed",
            "payment issue",
            "transfer issue",
        )
        help_terms = (
            "what to do",
            "what should i do",
            "how to contact",
            "contact support",
            "support",
            "help",
        )
        return any(term in normalized for term in payment_issue_terms) and any(term in normalized for term in help_terms)

    @staticmethod
    def _unsupported_currency_response(error: dict) -> dict:
        return {
            "answer": f"I could not answer that FX question. {error.get('error', 'Unsupported currency')}.",
            "citations": [],
            "mode": "fx-tool",
            "llm_available": False,
            "retrieved_chunks": [],
        }
