from app.services.database_service import DatabaseService
from app.services.fx_service import FxService


class TransferService:
    def __init__(self, fx_service: FxService, database_service: DatabaseService) -> None:
        self.fx_service = fx_service
        self.database_service = database_service

    def create_transfer(self, payload) -> dict:
        conversion = self.fx_service.convert(
            payload.amount,
            payload.from_currency,
            payload.to_currency,
            use_live=True,
        )
        if "error" in conversion:
            return {"stored": False, "error": conversion["error"], "conversion": conversion}

        record = {
            "customer_name": payload.customer_name,
            "from_currency": conversion["from_currency"],
            "to_currency": conversion["to_currency"],
            "amount": payload.amount,
            "converted_amount": conversion["converted_amount"],
            "rate": conversion["rate"],
            "beneficiary_country": payload.beneficiary_country,
            "purpose": payload.purpose,
            "provider": conversion["provider"],
        }
        return self.database_service.create_transfer(record)
