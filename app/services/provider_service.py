from app.services.alpha_vantage_service import AlphaVantageService
from app.services.fred_service import FredService


class ProviderService:
    def __init__(
        self,
        alpha_vantage_service: AlphaVantageService | None = None,
        fred_service: FredService | None = None,
    ) -> None:
        self.alpha_vantage_service = alpha_vantage_service or AlphaVantageService()
        self.fred_service = fred_service or FredService()

    def status(self) -> dict:
        return {
            "active_without_keys": [{
                "provider": "frankfurter",
                "configured": True,
                "capabilities": ["live_fx_rates", "historical_fx_rates", "rate_variance"],
                "requires_api_key": False,
            }],
            "optional_api_key_providers": [
                self.alpha_vantage_service.status(),
                self.fred_service.status(),
                {
                    "provider": "paid-providers",
                    "configured": False,
                    "capabilities": ["realtime_bid_ask", "bank_grade_rates", "professional_forecasts"],
                    "requires_api_key": True,
                    "examples": ["OpenExchangeRates paid tiers", "XE", "OANDA", "Refinitiv", "Bloomberg"],
                },
            ],
        }
