from datetime import date, datetime

from .base import CostCollector, CostRecord


class ClaudeAICollector(CostCollector):
    provider = "claude_ai"

    def collect(self, start_date: date, end_date: date) -> list[CostRecord]:
        now = datetime.utcnow()
        bu = self.get_bu("default")
        key = start_date.strftime("%Y-%m")

        monthly = (self._bu_mapping.get(self.provider) or {}).get("monthly_eur") or {}
        amount = monthly.get(key)
        if not amount:
            return []

        return [CostRecord(
            date=start_date,
            provider=self.provider,
            business_unit=bu,
            category="ai_subscription",
            description=f"Claude.ai Team plan + overage ({amount} EUR, {key})",
            amount=float(amount),
            original_currency="EUR",
            original_amount=float(amount),
            exchange_rate=1.0,
            source="manual",
            collected_at=now,
        )]
