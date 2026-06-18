# dataseekers-infra-costs

Cost collection and reporting for Dataseekers infrastructure. Pulls monthly/daily spend from every provider into a single BigQuery table and serves a Streamlit dashboard for analysis by provider and business unit.

## What it does

- **Collectors** (`collectors/`) — one per provider, normalising spend into a common `CostRecord` and loading it into BigQuery: GCP (billing export), OVH, OCI, Bright Data, Bitbucket, ClickHouse Cloud, and Claude.ai (manual YAML — no API).
- **BigQuery** (`bigquery/schema.sql`) — `dataseekers-core.costs.raw_costs` (partitioned by date, clustered by provider + business_unit) plus per-BU / per-provider views.
- **Dashboard** (`dashboard.py` + `views/`) — multipage Streamlit app (Overview / Provider detail / BU detail).

Resource → business-unit attribution is driven by `config/bu-mapping.yaml`.

## Install

```bash
pip install -r requirements.txt   # Python 3.12+
```

## Usage

```bash
# Collect all providers for a month
python main.py collect --month 2026-02

# Specific providers / dry-run
python main.py collect --month 2026-02 --providers gcp,ovh
python main.py collect --month 2026-02 --dry-run --verbose

# Month shortcuts
python main.py collect --month previous
python main.py collect --month current

# Monthly report + month-over-month sanity checks
python main.py report   --month 2026-02
python main.py validate --month 2026-02

# Dashboard
streamlit run dashboard.py
```

## Credentials

Each collector needs its own provider credentials, supplied as environment variables (GCP also uses gcloud ADC). See the **Environment Variables** table in [`CLAUDE.md`](CLAUDE.md) for the full per-provider list.

> **Claude.ai has no API** — its cost is entered by hand in `config/bu-mapping.yaml` (`claude_ai.monthly`). `validate` fails hard if the current month's entry is missing; that's expected, not a bug. The monthly workflow opens a reminder GitHub issue if it's absent.

## Automation & deployment

- **Collection** runs on GitHub Actions: `.github/workflows/collect-daily.yml` and `collect-monthly.yml` (the daily run re-collects `--month previous` to catch late GCP billing-export records). The root `bitbucket-pipelines.yml` is the legacy equivalent.
- **Dashboard** deploys to **Streamlit Cloud** from the `main` branch — pushing to `main` redeploys. Streamlit Cloud does not hot-reload imported modules, so a dashboard code change needs a redeploy to take effect.

## Related docs

Strategic / reference docs live in [`dataseekers-infra-docs`](https://github.com/Dataseekers/dataseekers-infra-docs):

- [Cost collectors inventory](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/reference/cost-collectors-inventory.md)
- [Monthly cost report runbook](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/runbooks/cost-report-monthly.md)
- [Claude.ai billing quirks](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/reference/claude-ai-billing.md)
- [ClickHouse Cloud billing quirks](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/reference/clickhouse-cloud-billing.md)
