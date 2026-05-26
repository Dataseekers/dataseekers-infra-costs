#!/usr/bin/env python3
"""Provider drill-down: KPIs, daily trend, BU/category breakdowns, top services with MoM."""

import pandas as pd
import plotly.express as px
import streamlit as st

from dashboard_components import format_eur, period_selector_ui
from dashboard_queries import (
    get_available_months,
    get_available_providers,
    query_by_dim,
    query_daily,
    query_top_lines_mom,
    query_total,
)

st.set_page_config(page_title="Provider detail", page_icon="🔍", layout="wide")
st.title("Provider detail")

months = get_available_months()
providers = get_available_providers()
if not months or not providers:
    st.warning("No data available yet.")
    st.stop()

# ── Filters ──
c_left, c_right = st.columns([1, 3])
with c_left:
    selected_provider = st.selectbox("Provider", providers, key="selected_provider")
with c_right:
    period = period_selector_ui(months)

# ── Aggregations ──
total = query_total(selected_provider, None, period.start, period.end)
prev_total = query_total(selected_provider, None, period.prev_start, period.prev_end)
org_total = query_total(None, None, period.start, period.end)

mom_pct = ((total - prev_total) / prev_total * 100) if prev_total > 0 else None
share_pct = (total / org_total * 100) if org_total > 0 else 0
delta_eur = total - prev_total

by_bu = query_by_dim(selected_provider, None, "business_unit", period.start, period.end)
by_category = query_by_dim(selected_provider, None, "category", period.start, period.end)
top_lines = query_top_lines_mom(
    selected_provider, None,
    period.start, period.end, period.prev_start, period.prev_end,
    limit=20,
)

top_bu = by_bu["business_unit"].iloc[0] if len(by_bu) > 0 else "—"
top_service = top_lines["description"].iloc[0] if len(top_lines) > 0 else "—"
if isinstance(top_service, str) and len(top_service) > 35:
    top_service = top_service[:32] + "…"

# ── KPI cards ──
st.divider()
k1, k2, k3, k4, k5 = st.columns(5)
k1.metric(
    "Total",
    format_eur(total),
    f"{mom_pct:+.1f}% MoM" if mom_pct is not None else "—",
)
k2.metric(
    "Δ vs previous",
    format_eur(delta_eur) if prev_total > 0 else "—",
    help=f"Previous period: {format_eur(prev_total)}",
)
k3.metric("Share of org total", f"{share_pct:.1f}%", help=format_eur(org_total))
k4.metric("Top BU", top_bu)
k5.metric("Top service", top_service)

st.divider()

# ── Chart 1: Daily cost ──
st.subheader(f"Daily cost — {period.label}")
daily = query_daily(selected_provider, None, period.start, period.end)
if len(daily) > 0:
    fig = px.bar(daily, x="date", y="total")
    fig.update_layout(xaxis_title="", yaxis_title="€", margin=dict(t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("No data in this period.")

# ── Chart 2 + 3: Breakdowns ──
col_left, col_right = st.columns(2)
with col_left:
    st.subheader(f"By Business Unit — {selected_provider}")
    if len(by_bu) > 0:
        fig = px.bar(
            by_bu, x="total", y="business_unit", orientation="h",
            text=by_bu["total"].apply(lambda x: format_eur(x)),
        )
        fig.update_layout(
            yaxis=dict(categoryorder="total ascending"),
            xaxis_title="", yaxis_title="", margin=dict(t=20, b=20),
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data.")

with col_right:
    st.subheader(f"By Category — {selected_provider}")
    if len(by_category) > 0:
        fig = px.pie(by_category, values="total", names="category", hole=0.4)
        fig.update_traces(textinfo="label+percent")
        fig.update_layout(showlegend=False, margin=dict(t=20, b=20))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No data.")

# ── Chart 4: Top services with MoM ──
st.subheader(f"Top 20 cost lines — {selected_provider}")
if len(top_lines) > 0:
    display = top_lines.copy().drop(columns=["provider"])
    display["current_amt"] = display["current_amt"].apply(lambda x: format_eur(x, decimals=2))
    display["prev_amt"] = display["prev_amt"].apply(lambda x: format_eur(x, decimals=2))
    display["delta_eur"] = display["delta_eur"].apply(lambda x: f"€{x:+,.2f}")
    display["delta_pct"] = display["delta_pct"].apply(
        lambda x: f"{x:+.1f}%" if pd.notna(x) else "—"
    )
    st.dataframe(
        display, use_container_width=True, hide_index=True,
        column_config={
            "description": "Description",
            "business_unit": "BU",
            "category": "Category",
            "current_amt": "Current",
            "prev_amt": "Previous",
            "delta_eur": "Δ €",
            "delta_pct": "Δ %",
        },
    )
else:
    st.info("No top lines for this period.")
