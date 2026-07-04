import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import settings


class AlphaVantageService:
    provider = "alpha-vantage"

    def is_configured(self) -> bool:
        return bool(settings.alpha_vantage_api_key)

    def status(self) -> dict:
        return {
            "provider": self.provider,
            "configured": self.is_configured(),
            "capabilities": ["fx_daily_time_series", "technical_indicators"],
            "requires_api_key": True,
        }

    def fx_daily(self, from_currency: str, to_currency: str, outputsize: str = "compact") -> dict:
        if not self.is_configured():
            return {
                "provider": self.provider,
                "configured": False,
                "error": "ALPHA_VANTAGE_API_KEY is not configured.",
                "next_step": "Add ALPHA_VANTAGE_API_KEY to your environment or .env file.",
            }

        query = urlencode({
            "function": "FX_DAILY",
            "from_symbol": from_currency.upper(),
            "to_symbol": to_currency.upper(),
            "outputsize": outputsize,
            "apikey": settings.alpha_vantage_api_key,
        })
        request = Request(
            f"{settings.alpha_vantage_base_url}?{query}",
            headers={"User-Agent": "FinFX-AI-Assistant/0.1"},
        )

        try:
            with urlopen(request, timeout=settings.provider_timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {"provider": self.provider, "configured": True, "error": str(exc)}

        if "Error Message" in payload or "Note" in payload or "Information" in payload:
            return {
                "provider": self.provider,
                "configured": True,
                "error": payload.get("Error Message") or payload.get("Note") or payload.get("Information"),
            }

        return {
            "provider": self.provider,
            "configured": True,
            "from_currency": from_currency.upper(),
            "to_currency": to_currency.upper(),
            "data": payload,
        }
