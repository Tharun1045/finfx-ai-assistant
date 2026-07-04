import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import settings


class FredService:
    provider = "fred"

    default_series = {
        "FEDFUNDS": "Federal Funds Effective Rate",
        "CPIAUCSL": "Consumer Price Index for All Urban Consumers",
        "UNRATE": "US Unemployment Rate",
        "DEXUSUK": "US Dollars to One British Pound",
    }

    def is_configured(self) -> bool:
        return bool(settings.fred_api_key)

    def status(self) -> dict:
        return {
            "provider": self.provider,
            "configured": self.is_configured(),
            "capabilities": ["economic_indicators", "macro_context"],
            "requires_api_key": True,
            "default_series": self.default_series,
        }

    def latest_observations(self) -> dict:
        if not self.is_configured():
            return {
                "provider": self.provider,
                "configured": False,
                "error": "FRED_API_KEY is not configured.",
                "next_step": "Add FRED_API_KEY to your environment or .env file.",
            }

        observations = {}
        for series_id, label in self.default_series.items():
            observations[series_id] = {
                "label": label,
                **self.series_observations(series_id, limit=1),
            }

        return {
            "provider": self.provider,
            "configured": True,
            "observations": observations,
        }

    def series_observations(self, series_id: str, limit: int = 12) -> dict:
        if not self.is_configured():
            return {"configured": False, "error": "FRED_API_KEY is not configured."}

        query = urlencode(
            {
                "series_id": series_id,
                "api_key": settings.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": limit,
            }
        )
        request = Request(
            f"{settings.fred_base_url}/series/observations?{query}",
            headers={"User-Agent": "FinFX-AI-Assistant/0.1"},
        )

        try:
            with urlopen(
                request, timeout=settings.provider_timeout_seconds
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            return {"configured": True, "error": str(exc)}

        return {
            "configured": True,
            "series_id": series_id,
            "observations": payload.get("observations", []),
        }
