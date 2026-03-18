import os
import tempfile
from datetime import date, datetime

import oci

from .base import CostCollector, CostRecord
from .currency import convert_to_eur


class OCICollector(CostCollector):
    provider = "oci"

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Support key content from env var (for CI) or file path
        key_content = os.environ.get("OCI_KEY_CONTENT")
        key_file = os.environ.get("OCI_KEY_FILE")

        if key_content:
            # Write key to temp file for OCI SDK
            self._key_tmpfile = tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False)
            self._key_tmpfile.write(key_content)
            self._key_tmpfile.close()
            key_file = self._key_tmpfile.name

        self.config = {
            "user": os.environ["OCI_USER"],
            "key_file": key_file,
            "fingerprint": os.environ["OCI_FINGERPRINT"],
            "tenancy": os.environ["OCI_TENANCY"],
            "region": os.environ.get("OCI_REGION", "eu-madrid-1"),
        }

    def collect(self, start_date: date, end_date: date) -> list[CostRecord]:
        now = datetime.utcnow()
        records = []

        usage_client = oci.usage_api.UsageapiClient(self.config)

        resp = usage_client.request_summarized_usages(
            oci.usage_api.models.RequestSummarizedUsagesDetails(
                tenant_id=self.config["tenancy"],
                time_usage_started=datetime(start_date.year, start_date.month, start_date.day),
                time_usage_ended=datetime(end_date.year, end_date.month, end_date.day),
                granularity="DAILY",
                compartment_depth=2,
                group_by=["compartmentName", "service"],
            )
        ).data

        for item in resp.items:
            if not item.computed_amount or item.computed_amount <= 0:
                continue

            compartment = item.compartment_name or "root"
            bu = self.get_bu(compartment)
            category = self._classify(item.service)
            currency = item.currency or "EUR"

            if currency != "EUR":
                eur_amount, rate = convert_to_eur(item.computed_amount, currency, start_date)
            else:
                eur_amount = item.computed_amount
                rate = 1.0

            usage_date = item.time_usage_started.date() if item.time_usage_started else start_date

            records.append(CostRecord(
                date=usage_date,
                provider=self.provider,
                business_unit=bu,
                category=category,
                description=f"{item.service} - {compartment}",
                amount=eur_amount,
                original_currency=currency,
                original_amount=item.computed_amount,
                exchange_rate=rate,
                source="api",
                collected_at=now,
            ))

        return records

    def _classify(self, service: str) -> str:
        service_lower = service.lower()
        if "mysql" in service_lower or "database" in service_lower:
            return "database"
        if "compute" in service_lower:
            return "compute"
        if "kubernetes" in service_lower or "container" in service_lower:
            return "compute"
        if "storage" in service_lower:
            return "storage"
        if "load balancer" in service_lower:
            return "network"
        if "network" in service_lower or "vcn" in service_lower:
            return "network"
        return "other"
