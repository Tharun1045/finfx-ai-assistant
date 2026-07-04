class ReportingService:
    def __init__(self, fx_service, transaction_service, database_service=None) -> None:
        self.fx_service = fx_service
        self.transaction_service = transaction_service
        self.database_service = database_service

    def daily_report(self) -> dict:
        summary = self.transaction_service.summary()
        suspicious = self.transaction_service.suspicious_transactions()
        rates = self.fx_service.get_rates()
        persisted = (
            self.database_service.transfer_summary() if self.database_service else None
        )

        return {
            "title": "Daily FX and Payments Operations Report",
            "date": rates["as_of"],
            "executive_summary": (
                f"Processed {summary['total_transactions']} demo transactions with total volume "
                f"of GBP {summary['total_volume_gbp']}. Top currency pair was "
                f"{summary['top_currency_pair']['pair']}. {len(suspicious)} transactions were flagged for review."
            ),
            "fx_snapshot": rates,
            "transaction_summary": summary,
            "persisted_transfer_summary": persisted,
            "flagged_transactions": suspicious,
            "next_actions": [
                "Review high-risk and failed transactions.",
                "Investigate corridors with repeated payment failures.",
                "Monitor target FX rates for customer alert opportunities.",
            ],
        }
