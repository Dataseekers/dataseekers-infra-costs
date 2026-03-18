import os
from datetime import date, datetime

import requests

from .base import CostCollector, CostRecord
from .currency import convert_to_eur


class BitbucketCollector(CostCollector):
    provider = "bitbucket"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.username = os.environ["BITBUCKET_USERNAME"]
        self.token = os.environ["BITBUCKET_API_TOKEN"]
        self.workspace = os.environ.get("BITBUCKET_WORKSPACE", "paraty")
        self.subscription_usd = float(os.environ.get("BITBUCKET_SUBSCRIPTION_USD", "354.05"))

    def _request(self, url: str) -> dict:
        resp = requests.get(url, auth=(self.username, self.token), timeout=30)
        resp.raise_for_status()
        return resp.json()

    def collect(self, start_date: date, end_date: date) -> list[CostRecord]:
        now = datetime.utcnow()
        records = []
        bu = self.get_bu("default")

        # Fixed subscription cost
        eur_amount, rate = convert_to_eur(self.subscription_usd, "USD", start_date)
        records.append(CostRecord(
            date=start_date,
            provider=self.provider,
            business_unit=bu,
            category="ci_cd",
            description=f"Bitbucket Standard plan subscription ({self.subscription_usd} USD)",
            amount=eur_amount,
            original_currency="USD",
            original_amount=self.subscription_usd,
            exchange_rate=rate,
            source="manual",
            collected_at=now,
        ))

        # TODO: build minutes tracking (requires iterating 1794 repos, slow)
        # Uncomment when needed or run separately
        # total_seconds = self._get_build_seconds(start_date, end_date)

        return records

    def _get_build_seconds(self, start_date: date, end_date: date) -> int:
        """Sum build_seconds_used across all repos in the workspace."""
        total = 0
        url = (
            f"https://api.bitbucket.org/2.0/repositories/{self.workspace}"
            f"?pagelen=100&fields=values.slug,next"
        )

        repos = []
        while url:
            data = self._request(url)
            repos.extend([r["slug"] for r in data.get("values", [])])
            url = data.get("next")

        for repo_slug in repos:
            total += self._get_repo_build_seconds(repo_slug, start_date, end_date)

        return total

    def _get_repo_build_seconds(self, repo_slug: str, start_date: date, end_date: date) -> int:
        """Get build seconds for a single repo in the date range."""
        total = 0
        url = (
            f"https://api.bitbucket.org/2.0/repositories/{self.workspace}/{repo_slug}"
            f"/pipelines/?pagelen=100&sort=-created_on"
            f"&fields=values.build_seconds_used,values.created_on,values.state,next"
        )

        while url:
            try:
                data = self._request(url)
            except Exception:
                break

            for pipeline in data.get("values", []):
                created = pipeline.get("created_on", "")
                if not created:
                    continue

                pipeline_date = datetime.fromisoformat(created.replace("Z", "+00:00")).date()

                if pipeline_date < start_date:
                    return total  # Sorted by -created_on, no more in range
                if pipeline_date >= end_date:
                    continue

                total += pipeline.get("build_seconds_used", 0) or 0

            url = data.get("next")

        return total
