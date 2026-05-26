# dataseekers-infra-costs

## Tech Stack

- Python 3.12+
- Google Cloud BigQuery (storage + views)
- APIs: OVH, OCI, Bright Data, Bitbucket, GCP billing export, ClickHouse Cloud
- Manual YAML input (no API): Claude.ai

## Commands

```bash
# Collect costs (all providers)
python main.py collect --month 2026-02

# Collect specific providers
python main.py collect --month 2026-02 --providers gcp,ovh

# Dry run (no BigQuery write)
python main.py collect --month 2026-02 --dry-run --verbose

# Report
python main.py report --month 2026-02

# Validate (month-over-month sanity checks)
python main.py validate --month 2026-02

# Month shortcuts
python main.py collect --month previous
python main.py collect --month current

# Dashboard (Streamlit, multipage)
streamlit run dashboard.py
```

## Install

```bash
pip install -r requirements.txt
```

## Architecture

```
collectors/
  base.py               # CostCollector ABC + CostRecord dataclass + BQ load
                        # get_bu(key, record_date=None) — supports date-ranged BU mapping
  currency.py           # EUR conversion via ECB API (prefetch 90d + retries)
  gcp.py                # BigQuery billing export query
  ovh.py                # OVH billing API (signed requests)
  oci.py                # Oracle Cloud Usage API
  brightdata.py         # Zone cost API
  bitbucket.py          # Fixed subscription cost
  clickhouse.py         # ClickHouse Cloud usageCost API (CHC unit, per-cycle rate)
  claude_ai.py          # Claude.ai Team plan — manual yaml input, no API
config/
  bu-mapping.yaml       # Provider resource → business unit mapping
                        # Also: clickhouse.chc_usd_rates and claude_ai.monthly
bigquery/
  schema.sql            # Table + views DDL
main.py                 # CLI entrypoint: collect, report, validate
dashboard.py            # Streamlit Overview page (entry point: `streamlit run dashboard.py`)
dashboard_queries.py    # Cached BQ queries shared across pages
dashboard_components.py # UI helpers: period_selector_ui (Month/3M/Custom), format_eur
pages/
  1_Provider_detail.py  # Drill-down per provider (KPIs, daily trend, BU/category, top services MoM)
  2_BU_detail.py        # Drill-down per business unit (KPIs, monthly trend, providers/category, top services MoM, day×provider heatmap)
```

State sharing between pages uses `st.session_state` keys: `selected_month`, `selected_provider`, `selected_bu`. Each detail page exposes a "Drill into …" widget pair (selectbox + button) so users can jump from Overview → detail and between detail pages with the chosen item pre-selected.

## BigQuery

- **Dataset:** `dataseekers-core.costs` (us-central1)
- **Table:** `raw_costs` — partitioned by date, clustered by provider + business_unit
- **Views:** `by_bu_month`, `by_provider_month`, `by_bu_provider`, `monthly_summary`, `daily_detail`

## Environment Variables

### Required per provider

| Provider | Variables |
|----------|-----------|
| GCP | `GCP_BILLING_TABLE` (optional, has default) + gcloud ADC |
| OVH | `OVH_APPLICATION_KEY`, `OVH_APPLICATION_SECRET`, `OVH_CONSUMER_KEY` |
| OCI | `OCI_TENANCY`, `OCI_USER`, `OCI_FINGERPRINT`, `OCI_KEY_FILE` (or `OCI_KEY_CONTENT`), `OCI_REGION` |
| Bright Data | `BRIGHTDATA_API_TOKEN` |
| Bitbucket | `BITBUCKET_USERNAME`, `BITBUCKET_API_TOKEN`, `BITBUCKET_WORKSPACE`, `BITBUCKET_SUBSCRIPTION_USD` |
| ClickHouse Cloud | `CLICKHOUSE_CLOUD_API_KEY_ID`, `CLICKHOUSE_CLOUD_API_KEY_SECRET`, `CLICKHOUSE_CLOUD_ORG_ID`, `CLICKHOUSE_CLOUD_CHC_USD_RATE` (optional, default 0.9689 USD/CHC for SCALE tier, derived from a Mar 18–Apr 18 invoice cross-check) |
| Claude.ai | None — reads `config/bu-mapping.yaml > claude_ai.monthly` entry per month (`subscription_usd` + `extra_usage_eur`). Workflow opens reminder GitHub issue if entry is missing on day 3. |

## Related docs (`dataseekers-infra-docs`)

- [Cost collectors inventory](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/reference/cost-collectors-inventory.md) — snapshot of the 7 active collectors (auth, cadence, currency) and what's intentionally not collected.
- [Monthly cost report runbook](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/runbooks/cost-report-monthly.md) — how to prepare the monthly email to management.
- [Claude.ai billing quirks](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/reference/claude-ai-billing.md) — no public API, two-component model (USD subscription + EUR overage), update flow.
- [ClickHouse Cloud billing quirks](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/reference/clickhouse-cloud-billing.md) — CHC unit, 18-to-18 cycle, per-cycle rate table.
- [GCP billing export late records](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/reference/gcp-billing-export-late-records.md) — why the daily workflow re-collects `--month previous`.
- [Cost collector ↔ invoice validation](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/reference/cost-collector-invoice-validation.md) — pattern for cross-checking against the provider's invoice.

## Testing

Skip tests — no test suite yet.

## Type Checking

Skip type checking — no mypy/pyright configured.

## Versioning

Skip versioning — no version tracking yet.

## Skip Skills

- frontend-patterns
- flask-patterns
- fastapi-patterns
- node-patterns
- project-structure
