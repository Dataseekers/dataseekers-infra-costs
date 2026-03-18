-- Dataset: dataseekers-core.costs
-- Run this once to create the table and views

CREATE TABLE IF NOT EXISTS `dataseekers-core.costs.raw_costs` (
  date           DATE NOT NULL,
  provider       STRING NOT NULL,
  business_unit  STRING NOT NULL,
  category       STRING NOT NULL,
  description    STRING,
  amount         FLOAT64 NOT NULL,
  original_currency STRING,
  original_amount   FLOAT64,
  exchange_rate     FLOAT64,
  source         STRING NOT NULL,
  collected_at   TIMESTAMP NOT NULL
)
PARTITION BY date
CLUSTER BY provider, business_unit;

-- By business unit + month
CREATE OR REPLACE VIEW `dataseekers-core.costs.by_bu_month` AS
SELECT
  DATE_TRUNC(date, MONTH) as month,
  business_unit,
  SUM(amount) as total,
  SUM(amount) / SUM(SUM(amount)) OVER (PARTITION BY DATE_TRUNC(date, MONTH)) * 100 as pct
FROM `dataseekers-core.costs.raw_costs`
GROUP BY 1, 2;

-- By provider + month
CREATE OR REPLACE VIEW `dataseekers-core.costs.by_provider_month` AS
SELECT
  DATE_TRUNC(date, MONTH) as month,
  provider,
  SUM(amount) as total,
  SUM(amount) / SUM(SUM(amount)) OVER (PARTITION BY DATE_TRUNC(date, MONTH)) * 100 as pct
FROM `dataseekers-core.costs.raw_costs`
GROUP BY 1, 2;

-- Cross: business unit x provider x month
CREATE OR REPLACE VIEW `dataseekers-core.costs.by_bu_provider` AS
SELECT
  DATE_TRUNC(date, MONTH) as month,
  business_unit,
  provider,
  SUM(amount) as total
FROM `dataseekers-core.costs.raw_costs`
GROUP BY 1, 2, 3;

-- Monthly summary with month-over-month change
CREATE OR REPLACE VIEW `dataseekers-core.costs.monthly_summary` AS
SELECT
  DATE_TRUNC(date, MONTH) as month,
  SUM(amount) as total,
  LAG(SUM(amount)) OVER (ORDER BY DATE_TRUNC(date, MONTH)) as prev_month,
  SAFE_DIVIDE(
    SUM(amount) - LAG(SUM(amount)) OVER (ORDER BY DATE_TRUNC(date, MONTH)),
    LAG(SUM(amount)) OVER (ORDER BY DATE_TRUNC(date, MONTH))
  ) * 100 as mom_change_pct
FROM `dataseekers-core.costs.raw_costs`
GROUP BY 1;

-- Daily detail (for spike detection)
CREATE OR REPLACE VIEW `dataseekers-core.costs.daily_detail` AS
SELECT
  date,
  business_unit,
  provider,
  SUM(amount) as total
FROM `dataseekers-core.costs.raw_costs`
GROUP BY 1, 2, 3;
