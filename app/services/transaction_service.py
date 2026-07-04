import csv
from collections import Counter, defaultdict
from functools import lru_cache

from app.core.config import settings


class TransactionService:
    def __init__(self) -> None:
        self.transactions_path = settings.data_dir / "transactions.csv"

    @lru_cache(maxsize=1)
    def load_transactions(self) -> list[dict]:
        with self.transactions_path.open("r", encoding="utf-8", newline="") as file:
            rows = list(csv.DictReader(file))

        for row in rows:
            row["amount_gbp"] = float(row["amount_gbp"])
            row["risk_score"] = int(row["risk_score"])
        return rows

    def summary(self) -> dict:
        rows = self.load_transactions()
        total_volume = sum(row["amount_gbp"] for row in rows)
        status_counts = Counter(row["status"] for row in rows)
        pair_volume: dict[str, float] = defaultdict(float)
        country_volume: dict[str, float] = defaultdict(float)

        for row in rows:
            pair_volume[row["currency_pair"]] += row["amount_gbp"]
            country_volume[row["destination_country"]] += row["amount_gbp"]

        top_pair = max(pair_volume.items(), key=lambda item: item[1])
        return {
            "total_transactions": len(rows),
            "total_volume_gbp": round(total_volume, 2),
            "status_counts": dict(status_counts),
            "top_currency_pair": {"pair": top_pair[0], "volume_gbp": round(top_pair[1], 2)},
            "volume_by_country": {country: round(volume, 2) for country, volume in country_volume.items()},
        }

    def failed_transactions(self) -> list[dict]:
        return [row for row in self.load_transactions() if row["status"] == "failed"]

    def suspicious_transactions(self) -> list[dict]:
        flagged = []
        for row in self.load_transactions():
            reasons = []
            if row["amount_gbp"] >= 10000:
                reasons.append("large transfer")
            if row["risk_score"] >= 75:
                reasons.append("high risk score")
            if row["status"] in {"failed", "compliance_review"}:
                reasons.append(f"status is {row['status']}")
            if reasons:
                flagged.append({**row, "reasons": reasons})
        return flagged
