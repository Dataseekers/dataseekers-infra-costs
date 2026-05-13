from datetime import date, datetime

from .base import CostCollector, CostRecord
from .currency import convert_to_eur


class ClaudeAICollector(CostCollector):
    provider = "claude_ai"

    def collect(self, start_date: date, end_date: date) -> list[CostRecord]:
        now = datetime.utcnow()
        bu = self.get_bu("default")
        key = start_date.strftime("%Y-%m")

        entry = (self._bu_mapping.get(self.provider) or {}).get("monthly", {}).get(key)
        if not entry:
            return []

        records: list[CostRecord] = []

        subscription_usd = entry.get("subscription_usd")
        if subscription_usd:
            eur_amount, rate = convert_to_eur(subscription_usd, "USD", start_date)
            records.append(CostRecord(
                date=start_date,
                provider=self.provider,
                business_unit=bu,
                category="ai_subscription",
                description=f"Claude.ai Team plan subscription ({subscription_usd} USD, {key})",
                amount=eur_amount,
                original_currency="USD",
                original_amount=float(subscription_usd),
                exchange_rate=rate,
                source="manual",
                collected_at=now,
            ))

        extra_usage_eur = entry.get("extra_usage_eur")
        if extra_usage_eur:
            records.append(CostRecord(
                date=start_date,
                provider=self.provider,
                business_unit=bu,
                category="ai_usage",
                description=f"Claude.ai extra-usage auto-reloads ({extra_usage_eur} EUR, {key})",
                amount=float(extra_usage_eur),
                original_currency="EUR",
                original_amount=float(extra_usage_eur),
                exchange_rate=1.0,
                source="manual",
                collected_at=now,
            ))

        return records
