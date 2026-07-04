import json
from contextvars import ContextVar
from datetime import datetime, timezone
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.core.config import settings

current_question_id: ContextVar[str | None] = ContextVar(
    "current_question_id", default=None
)


class LlmUsageTracker:
    def __init__(self) -> None:
        self._lock = Lock()
        self._records: list[dict] = []
        self._database_service = None

    def set_database_service(self, database_service) -> None:
        """Attach persistence so in-memory usage records are also written to Supabase/Postgres."""
        self._database_service = database_service

    def record(
        self,
        call_type: str,
        provider: str,
        model: str,
        input_text: str,
        output_text: str | None = None,
        success: bool = True,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
    ) -> None:
        """Record each LLM or embedding call for the AI observability dashboard."""
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "question_id": current_question_id.get(),
            "call_type": call_type,
            "provider": provider,
            "model": model,
            "success": success,
            "input_tokens": (
                input_tokens
                if input_tokens is not None
                else self.estimate_tokens(input_text)
            ),
            "output_tokens": (
                output_tokens
                if output_tokens is not None
                else self.estimate_tokens(output_text or "")
            ),
        }
        record["total_tokens"] = record["input_tokens"] + record["output_tokens"]
        with self._lock:
            self._records.append(record)
            self._records = self._records[-100:]
        if self._database_service:
            try:
                self._database_service.create_llm_usage_log(record)
            except Exception:
                pass

    def summary(self) -> dict:
        with self._lock:
            records = list(self._records)
        totals = {
            "calls": len(records),
            "successful_calls": sum(1 for record in records if record["success"]),
            "failed_calls": sum(1 for record in records if not record["success"]),
            "input_tokens": sum(record["input_tokens"] for record in records),
            "output_tokens": sum(record["output_tokens"] for record in records),
            "total_tokens": sum(record["total_tokens"] for record in records),
        }
        by_provider: dict[str, dict] = {}
        by_call_type: dict[str, dict] = {}
        for record in records:
            self._rollup(by_provider, record["provider"], record)
            self._rollup(by_call_type, record["call_type"], record)
        return {
            "totals": totals,
            "by_provider": by_provider,
            "by_call_type": by_call_type,
            "recent": records[-10:][::-1],
            "note": "Token counts are estimated for local Ollama and exact when a cloud provider returns usage metadata.",
        }

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return max(1, round(len(text or "") / 4)) if text else 0

    @staticmethod
    def _rollup(target: dict[str, dict], key: str, record: dict) -> None:
        target.setdefault(
            key, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
        )
        target[key]["calls"] += 1
        target[key]["input_tokens"] += record["input_tokens"]
        target[key]["output_tokens"] += record["output_tokens"]
        target[key]["total_tokens"] += record["total_tokens"]


usage_tracker = LlmUsageTracker()


class OllamaClient:
    def __init__(self) -> None:
        self.base_url = settings.ollama_base_url.rstrip("/")
        self.provider = settings.llm_provider
        self.openai_base_url = settings.openai_base_url.rstrip("/")
        self.openai_api_key = settings.openai_api_key
        self.anthropic_base_url = settings.anthropic_base_url.rstrip("/")
        self.anthropic_api_key = settings.anthropic_api_key

    def embed(self, text: str) -> list[float] | None:
        # Keep embeddings on local Ollama so the pgvector table stays at 768 dimensions.
        payload = {"model": settings.ollama_embedding_model, "prompt": text}
        data = self._post_json(
            "/api/embeddings", payload, timeout=settings.ollama_timeout_seconds
        )
        usage_tracker.record(
            "embedding",
            "ollama",
            settings.ollama_embedding_model,
            text,
            success=bool(data and isinstance(data.get("embedding"), list)),
        )
        if not data:
            return None
        embedding = data.get("embedding")
        return embedding if isinstance(embedding, list) else None

    def generate(self, prompt: str, model: str | None = None) -> str | None:
        """Generate text with the configured chat provider: Ollama, OpenAI, or Anthropic."""
        if self.provider == "openai":
            return self._generate_openai(prompt, model)
        if self.provider in {"claude", "anthropic"}:
            return self._generate_anthropic(prompt, model)
        return self._generate_ollama(prompt, model)

    def generate_json(self, prompt: str, model: str | None = None) -> dict | None:
        """Generate a JSON object for routing and SQL planning tasks."""
        if self.provider == "ollama":
            return self._generate_ollama_json(prompt, model)

        response = self.generate(
            f"{prompt}\n\nReturn only valid JSON. Do not include markdown or explanation.",
            model,
        )
        if not response:
            return None
        return self._parse_json_object(response)

    def is_available(self) -> bool:
        if self.provider == "openai":
            return bool(self.openai_api_key)
        if self.provider in {"claude", "anthropic"}:
            return bool(self.anthropic_api_key)
        data = self._get_json("/api/tags", timeout=5)
        return bool(data and "models" in data)

    def _generate_ollama(self, prompt: str, model: str | None = None) -> str | None:
        payload = {
            "model": model or settings.ollama_chat_model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 500},
        }
        data = self._post_json(
            "/api/generate", payload, timeout=settings.ollama_timeout_seconds
        )
        if not data:
            usage_tracker.record(
                "chat", "ollama", payload["model"], prompt, success=False
            )
            return None
        response = data.get("response")
        usage_tracker.record(
            "chat",
            "ollama",
            payload["model"],
            prompt,
            response if isinstance(response, str) else "",
            success=isinstance(response, str),
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )
        return response.strip() if isinstance(response, str) else None

    def _generate_ollama_json(
        self, prompt: str, model: str | None = None
    ) -> dict | None:
        payload = {
            "model": model or settings.ollama_chat_model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 300},
        }
        data = self._post_json(
            "/api/generate", payload, timeout=settings.ollama_timeout_seconds
        )
        if not data or not isinstance(data.get("response"), str):
            usage_tracker.record(
                "json", "ollama", payload["model"], prompt, success=False
            )
            return None

        parsed = self._parse_json_object(data["response"])
        usage_tracker.record(
            "json",
            "ollama",
            payload["model"],
            prompt,
            data["response"],
            success=bool(parsed),
            input_tokens=data.get("prompt_eval_count"),
            output_tokens=data.get("eval_count"),
        )
        return parsed

    def _generate_openai(self, prompt: str, model: str | None = None) -> str | None:
        if not self.openai_api_key:
            usage_tracker.record(
                "chat",
                "openai",
                model or settings.openai_chat_model,
                prompt,
                success=False,
            )
            return None
        selected_model = model or settings.openai_chat_model
        payload = {
            "model": selected_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 600,
        }
        data = self._post_absolute_json(
            f"{self.openai_base_url}/chat/completions",
            payload,
            timeout=settings.ollama_timeout_seconds,
            headers={"Authorization": f"Bearer {self.openai_api_key}"},
        )
        try:
            content = data["choices"][0]["message"]["content"] if data else None
        except (KeyError, IndexError, TypeError):
            usage_tracker.record(
                "chat", "openai", selected_model, prompt, success=False
            )
            return None
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        usage_tracker.record(
            "chat",
            "openai",
            selected_model,
            prompt,
            content if isinstance(content, str) else "",
            success=isinstance(content, str),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )
        return content.strip() if isinstance(content, str) else None

    def _generate_anthropic(self, prompt: str, model: str | None = None) -> str | None:
        if not self.anthropic_api_key:
            usage_tracker.record(
                "chat",
                "anthropic",
                model or settings.anthropic_chat_model,
                prompt,
                success=False,
            )
            return None
        selected_model = model or settings.anthropic_chat_model
        payload = {
            "model": selected_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 600,
        }
        data = self._post_absolute_json(
            f"{self.anthropic_base_url}/messages",
            payload,
            timeout=settings.ollama_timeout_seconds,
            headers={
                "x-api-key": self.anthropic_api_key,
                "anthropic-version": "2023-06-01",
            },
        )
        content = data.get("content") if data else None
        if not isinstance(content, list):
            usage_tracker.record(
                "chat", "anthropic", selected_model, prompt, success=False
            )
            return None
        text_parts = [
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        text = "\n".join(part for part in text_parts if part).strip()
        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        usage_tracker.record(
            "chat",
            "anthropic",
            selected_model,
            prompt,
            text,
            success=bool(text),
            input_tokens=usage.get("input_tokens"),
            output_tokens=usage.get("output_tokens"),
        )
        return text or None

    def _get_json(self, path: str, timeout: float) -> dict | None:
        request = Request(
            f"{self.base_url}{path}", headers={"User-Agent": "FinFX-AI-Assistant/0.1"}
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return None

    def _post_json(self, path: str, payload: dict, timeout: float) -> dict | None:
        return self._post_absolute_json(
            f"{self.base_url}{path}", payload, timeout=timeout
        )

    def _post_absolute_json(
        self,
        url: str,
        payload: dict,
        timeout: float,
        headers: dict[str, str] | None = None,
    ) -> dict | None:
        body = json.dumps(payload).encode("utf-8")
        request_headers = {
            "Content-Type": "application/json",
            "User-Agent": "FinFX-AI-Assistant/0.1",
            **(headers or {}),
        }
        request = Request(
            url,
            data=body,
            headers=request_headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            return None

    @staticmethod
    def _parse_json_object(value: str) -> dict | None:
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            start = value.find("{")
            end = value.rfind("}")
            if start == -1 or end == -1 or end <= start:
                return None
            try:
                parsed = json.loads(value[start : end + 1])
            except json.JSONDecodeError:
                return None

        return parsed if isinstance(parsed, dict) else None
