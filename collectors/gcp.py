import os
from datetime import date, datetime

from google.cloud import bigquery

from .base import CostCollector, CostRecord


class GCPCollector(CostCollector):
    provider = "gcp"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.billing_table = os.environ.get(
            "GCP_BILLING_TABLE",
            "dataseekers-core.billing.gcp_billing_export_v1_0148C2_FF5DAE_3649EE",
        )

    def collect(self, start_date: date, end_date: date) -> list[CostRecord]:
        now = datetime.utcnow()
        records = []

        client = bigquery.Client()

        query = f"""
        SELECT
            DATE(usage_start_time) as usage_date,
            project.id as project_id,
            service.description as service_desc,
            SUM(cost) + SUM(IFNULL(
                (SELECT SUM(c.amount) FROM UNNEST(credits) c), 0
            )) as net_cost,
            currency
        FROM `{self.billing_table}`
        WHERE DATE(usage_start_time) >= @start_date
          AND DATE(usage_start_time) < @end_date
        GROUP BY 1, 2, 3, 5
        HAVING net_cost > 0.01
        ORDER BY net_cost DESC
        """

        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date),
            ]
        )

        results = client.query(query, job_config=job_config).result()

        for row in results:
            project_id = row.project_id or "unknown"
            bu = self.get_bu(project_id)
            category = self._classify(row.service_desc)
            currency = row.currency or "EUR"

            # GCP billing in EUR for EU accounts, no conversion needed typically
            amount = row.net_cost
            rate = 1.0

            records.append(CostRecord(
                date=row.usage_date,
                provider=self.provider,
                business_unit=bu,
                category=category,
                description=f"{row.service_desc} - {project_id}",
                amount=amount,
                original_currency=currency,
                original_amount=row.net_cost,
                exchange_rate=rate,
                source="api",
                collected_at=now,
            ))

        return records

    def _classify(self, service_desc: str) -> str:
        desc = service_desc.lower()
        if "compute" in desc:
            return "compute"
        if "kubernetes" in desc or "container" in desc:
            return "compute"
        if "storage" in desc:
            return "storage"
        if "bigquery" in desc:
            return "database"
        if "sql" in desc:
            return "database"
        if "network" in desc or "load balancing" in desc:
            return "network"
        if "cloud run" in desc or "functions" in desc:
            return "compute"
        if "artifact" in desc or "container registry" in desc:
            return "ci_cd"
        return "other"
