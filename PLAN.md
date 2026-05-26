# PLAN — Multipage drill-down for the cost dashboard

Última actualización: 2026-05-26
Branch sugerida: `dashboard-multipage-drilldown`

## Goal

Convertir `dashboard.py` en una app multipage Streamlit con dos drill-downs (provider, BU) que aceleren la redacción del email mensual de costes y faciliten responder "qué ha subido / por qué" sin pelearse con BQ a mano.

## Non-goals

- No tocamos collectors, schema, workflows, deploy ni el dataset BQ.
- No añadimos auth/control de acceso al dashboard (out of scope).
- No introducimos un schema "service-level" más fino que el actual `description` field.
- No tocamos el orden ni formato del email mensual — solo facilitamos el trabajo previo.

## Use cases que la app debe resolver

Anclados al [runbook del email mensual](https://github.com/Dataseekers/dataseekers-infra-docs/blob/main/runbooks/cost-report-monthly.md):

1. *"¿Cuánto se ha movido GCP MoM y qué BUs lo explican?"* → Provider detail filtrando GCP.
2. *"Puig sube 5% — ¿qué provider lo impulsa y en qué servicio?"* → BU detail filtrando puig.
3. *"¿Hay algún día con spike anómalo en ClickHouse?"* → Provider detail con curva diaria.
4. *"¿La migración rentacar→OVH se está notando?"* → BU detail rentacar, 6-12m de trend con desglose por provider.
5. *"Validar contra factura ClickHouse del último ciclo (18→18)"* → Provider detail con selector de rango de fechas custom + descomposición.

## UX overview

```
┌─ Sidebar (auto-generado por Streamlit) ─┐
│ ◯ dashboard       (Overview, actual)    │
│ ◯ Provider detail                       │
│ ◯ BU detail                             │
└─────────────────────────────────────────┘
```

- Cada página tiene su propio set de filtros en el cuerpo (no en sidebar) para no chocar con la nav.
- `st.session_state["selected_month"]` se preserva entre páginas → al cambiar de página el contexto temporal se mantiene.
- Cross-link: al clicar un BU en Provider detail (vía botón o `st.page_link` adyacente), saltamos a BU detail con ese BU pre-seleccionado.

## Diseño de KPIs por página

### Página 1 — Overview (refactor del `dashboard.py` actual)

Mantener tal cual está hoy + small cleanup:

- Extraer queries a módulo común.
- Añadir `st.page_link` debajo de la pie chart por BU y del bar chart por provider, para entrar al drill-down del item clicado (Streamlit no soporta click-through nativo sin `streamlit-plotly-events`; usar selector + botón "Ver detalle").

No se añaden KPIs nuevos aquí — la Overview ya es densa.

---

### Página 2 — Provider detail

**Filtros (cuerpo, no sidebar):**
- `Provider` (selectbox, default = top provider del mes seleccionado).
- `Período`: radio con tres opciones:
  - "Mes" (default, usa `selected_month` del session_state).
  - "Últimos 3 meses".
  - "Custom" (date_input con rango libre, útil para validar ciclo CHC 18→18).

**KPI row (5 cards):**

| KPI | Cálculo | Rationale |
|---|---|---|
| **Total** | `SUM(amount)` en período | Cifra principal. |
| **MoM Δ%** | vs mismo nº de días del período anterior | El driver del email. |
| **Share del total** | `provider_total / org_total * 100` | Pone el provider en contexto. |
| **Top BU** | BU con mayor `SUM(amount)` dentro del provider | Sirve para escribir "Provider X sube por BU Y". |
| **Top service** | Top `description` (LIKE-aware, dedup primer token) | Identifica el SKU concreto que mueve la aguja. |

**Charts:**

1. **Daily trend** (`px.line` o `px.bar`) — eje X días del período, eje Y €. Marca picos. Si período = "Últimos 3 meses", agrupa por día con bandas de mes.
2. **Breakdown por BU** (`px.bar` horizontal) — barras stackeadas por BU, etiqueta € + % share. Permite ver qué BU es el grueso del provider.
3. **Breakdown por category** (`px.pie` donut) — compute/storage/network/database/ci_cd/other. Útil para GCP (gran variedad) y OCI; trivial pero diagnóstico para los demás.
4. **Top 20 services table con MoM** — columnas: `description`, `business_unit`, `category`, `current`, `previous`, `Δ €`, `Δ %`. Ordenable. Ordenada por `|Δ €|` desc para destacar movers.

**Query patterns** (todas con `@st.cache_data(ttl=3600)`):

```sql
-- Daily trend
SELECT date, SUM(amount) AS total
FROM raw_costs
WHERE provider = @provider AND date BETWEEN @start AND @end
GROUP BY 1 ORDER BY 1;

-- By BU (within provider)
SELECT business_unit, SUM(amount) AS total
FROM raw_costs
WHERE provider = @provider AND date BETWEEN @start AND @end
GROUP BY 1 ORDER BY 2 DESC;

-- By category
SELECT category, SUM(amount) AS total
FROM raw_costs
WHERE provider = @provider AND date BETWEEN @start AND @end
GROUP BY 1 ORDER BY 2 DESC;

-- Top services with MoM (CTE pattern)
WITH curr AS (
  SELECT description, business_unit, category, SUM(amount) AS amt
  FROM raw_costs WHERE provider = @provider AND date BETWEEN @start AND @end GROUP BY 1, 2, 3
),
prev AS (
  SELECT description, SUM(amount) AS amt
  FROM raw_costs WHERE provider = @provider AND date BETWEEN @prev_start AND @prev_end GROUP BY 1
)
SELECT
  COALESCE(c.description, p.description) AS description,
  c.business_unit, c.category,
  IFNULL(c.amt, 0) AS current_amt,
  IFNULL(p.amt, 0) AS prev_amt,
  IFNULL(c.amt, 0) - IFNULL(p.amt, 0) AS delta_eur,
  SAFE_DIVIDE(IFNULL(c.amt, 0) - IFNULL(p.amt, 0), p.amt) * 100 AS delta_pct
FROM curr c FULL OUTER JOIN prev p USING (description)
ORDER BY ABS(IFNULL(c.amt, 0) - IFNULL(p.amt, 0)) DESC
LIMIT 20;
```

---

### Página 3 — BU detail

**Filtros (cuerpo):**
- `Business Unit` (selectbox, default = top BU del mes seleccionado).
- `Período`: igual que provider detail (mes / 3M / custom).

**KPI row (5 cards):**

| KPI | Cálculo | Rationale |
|---|---|---|
| **Total** | `SUM(amount)` en período | Cifra base del bullet del email. |
| **MoM Δ%** | vs período anterior equivalente | "Rentacar baja un 4%" del email viene de aquí. |
| **Share del total** | `bu_total / org_total * 100` | Tamaño relativo de la BU. |
| **Top provider** | Provider con mayor `SUM` dentro de la BU | "drivers": "…por aumento en Bright Data". |
| **Top service** | Top `description` dentro de la BU | Permite citar el servicio concreto. |

**Charts:**

1. **Monthly trend de la BU** (`px.line` con `markers=True`) — últimos 12-18 meses (todo lo disponible, capped a 18). Muestra trayectoria sin ruido. Si la BU tiene <3 meses de datos, fallback a daily.
2. **Breakdown por provider** (`px.bar` horizontal con MoM Δ inline) — para cada provider de la BU, mostrar current + delta vs prev.
3. **Breakdown por category** (`px.pie` donut) — ver mix compute/storage/network/database. Útil para detectar shifts arquitecturales (e.g. de DB a network).
4. **Top 20 cost lines de la BU con MoM** — misma shape que en provider detail, pero filtrado por `business_unit`.
5. **Heatmap día × provider** (`px.imshow`) — días en eje X, providers en eje Y, intensidad = €. Sirve para spot-check de patrones (e.g. spikes de Bright Data en fines de semana).

**Query patterns** análogos a Provider detail pero con `business_unit = @bu` como filtro maestro.

---

## Módulo compartido — `dashboard_queries.py`

Extraer del `dashboard.py` actual + añadir:

```python
@st.cache_data(ttl=3600)
def query_bq(sql: str, **params) -> pd.DataFrame: ...

@st.cache_data(ttl=3600)
def get_available_months() -> list[str]: ...

def get_period_dates(period_kind: str, anchor_month: str, custom: tuple[date, date] | None = None) -> tuple[date, date, date, date]:
    """Returns (start, end, prev_start, prev_end) for the chosen period."""

# Reusable building blocks:
@st.cache_data(ttl=3600)
def query_by_dim(provider: str | None, bu: str | None, start: date, end: date, dim: str) -> pd.DataFrame: ...

@st.cache_data(ttl=3600)
def query_top_lines_mom(filter_col: str, filter_val: str, start, end, prev_start, prev_end, limit: int = 20) -> pd.DataFrame: ...
```

Y un `dashboard_components.py` con helpers de UI (selector de período, MoM badge, formato €).

## File structure tras el cambio

```
dataseekers-infra-costs/
  dashboard.py                 # Overview (refactor: imports de _queries y _components)
  dashboard_queries.py         # NEW — funciones cacheadas y building blocks BQ
  dashboard_components.py      # NEW — helpers UI (period selector, badges, formatters)
  pages/
    1_Provider_detail.py       # NEW
    2_BU_detail.py             # NEW
  …                             # resto sin cambios
```

`streamlit run dashboard.py` sigue siendo el entry point. Streamlit detecta `pages/` automáticamente.

## Cross-page interactions

- `st.session_state["selected_month"]` se setea en Overview y se lee como default en las otras páginas.
- En Provider detail, debajo del bar chart de BUs, añadir botón "Ver detalle de <BU>" que escribe `st.session_state["selected_bu"]` y hace `st.switch_page("pages/2_BU_detail.py")`.
- Análogo en BU detail con providers.

Estado mínimo a propagar:
- `selected_month` (string YYYY-MM).
- `selected_provider` (string, opcional).
- `selected_bu` (string, opcional).
- `selected_period_kind` (string: "month" | "3m" | "custom").

## Implementation phases

### Phase 0 — Refactor sin nuevas features (1 PR)
1. Crear `dashboard_queries.py` y mover ahí `query_bq`, `get_available_months`, `get_month_data`, `get_monthly_trend`, `get_trend_by_bu`.
2. Crear `dashboard_components.py` con `format_eur`, `mom_badge`, `period_selector_widget`.
3. `dashboard.py` se reduce a imports + layout. Sin cambios funcionales.
4. Smoke test con `AppTest.from_file("dashboard.py")` → verificar 0 excepciones y mismos KPIs.

### Phase 1 — Provider detail (1 PR)
1. `pages/1_Provider_detail.py` completo.
2. Test con `AppTest.from_file("pages/1_Provider_detail.py")` para los 3 modos de período + 2 providers (GCP y ClickHouse) → verificar 0 excepciones, KPI cards no nulas, top-services no vacío.
3. Verificación manual contra invoice de ClickHouse (período custom 2026-04-18 → 2026-05-18, comparar con la factura). Aprovecha [feedback_validate_collector_against_invoice].

### Phase 2 — BU detail (1 PR)
1. `pages/2_BU_detail.py` completo.
2. Tests análogos para 2 BUs (hotels y rentacar — donde más se mueve).
3. Verificación: total de `hotels` en mayo debe matchear `SELECT SUM(amount) FROM raw_costs WHERE business_unit='hotels' AND date BETWEEN '2026-05-01' AND '2026-05-31'`.

### Phase 3 — Cross-page links + polish (1 PR)
1. Botones "Ver detalle de…" en ambas direcciones.
2. Propagación de `selected_month` entre páginas.
3. README del repo (sección Dashboard) con captura.

## Tests

Usar [`streamlit.testing.v1.AppTest`](https://docs.streamlit.io/develop/api-reference/app-testing) ([[reference_streamlit_apptest]]). Por página:

```python
from streamlit.testing.v1 import AppTest

def test_provider_detail_gcp_month():
    at = AppTest.from_file("pages/1_Provider_detail.py", default_timeout=60)
    at.session_state["selected_month"] = "2026-04"
    at.session_state["selected_provider"] = "gcp"
    at.run()
    assert not at.exception
    assert any("Total" in m.label for m in at.main.metric)

def test_bu_detail_hotels():
    at = AppTest.from_file("pages/2_BU_detail.py", default_timeout=60)
    at.session_state["selected_month"] = "2026-05"
    at.session_state["selected_bu"] = "hotels"
    at.run()
    assert not at.exception
```

Mínimo: 1 test por página + 1 test del Overview (regression Phase 0). No tests de datos exactos — solo smoke + presencia de widgets clave.

## Validation antes de merge final

- Total org del mes seleccionado en Overview = suma de totals en todas las páginas Provider detail (sumando los 7 providers) = suma de totals en BU detail (todas las BUs).
- Top services de GCP en Provider detail coincide con `Top 15 cost lines` filtrando GCP en Overview.
- Verificación visual: cargar el dashboard, navegar las 3 páginas, comprobar que el `selected_month` se preserva.
- Smoke headless de las 3 páginas (no `streamlit run`).

## Decisiones pendientes que afectan al plan

1. **Estado URL vs session_state**: ¿queremos URLs compartibles (`?provider=gcp&month=2026-05`) o nos basta con session_state? URL implica usar `st.query_params` (más LOC, pero linkeable a Slack/email). **Default sugerido:** session_state en Phase 1-2, query_params si se pide después.
2. **Periodo "Custom"**: ¿lo metemos desde Phase 1 o lo dejamos para Phase 3? **Sugerido Phase 1** porque es exactamente lo que necesitas para validar facturas ClickHouse.
3. **Heatmap día × provider en BU detail**: ¿util o ruidoso? **Sugerido sí**, pero detrás de un `st.expander` para no abrumar.
4. **Tabla top services**: ¿15 o 20 filas? Hoy son 15 en Overview. **Sugerido 20** para drill-down (más profundidad).
5. **MoM definition para período "Últimos 3 meses"**: ¿comparamos contra los 3 meses anteriores o no aplicamos MoM en ese caso? **Sugerido:** mostrar el delta de los 3 meses como un total comparado contra los 3 previos. Si confunde, lo quitamos.

## Out of scope (para futuras iteraciones)

- Filtros multi-select (e.g. comparar 2 providers).
- Anomaly detection automática (sólo gráficos que la hacen visible).
- Export a CSV/PNG desde la UI.
- Caché persistente (Redis, etc.) — Streamlit in-memory es suficiente.
- Auth / SSO (depende del deploy actual).
- Service-level schema más fino que `description`.

## Estimación

- Phase 0: ~1h (refactor mecánico + test).
- Phase 1: ~3h (página + queries + test + invoice cross-check).
- Phase 2: ~2h (mismo shape que Phase 1).
- Phase 3: ~1h (cross-links + polish).

Total ~7h efectivas, repartidas en 4 PRs.
