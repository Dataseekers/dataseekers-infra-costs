#!/usr/bin/env python3
"""Cost dashboard — Streamlit app for dataseekers infrastructure costs."""

import streamlit as st
import plotly.express as px

from dashboard_queries import (
    get_available_months,
    get_month_data,
    get_monthly_trend,
    get_trend_by_bu,
)

st.set_page_config(
    page_title="Dataseekers Costs",
    page_icon="💰",
    layout="wide",
)

# ── Header ──
st.title("Dataseekers Infrastructure Costs")

months = get_available_months()
if not months:
    st.warning("No data available yet.")
    st.stop()

selected_month = st.selectbox("Month", months, key="selected_month")
data = get_month_data(selected_month)

# ── KPI cards ──
col0, col1, col2, col3, col4 = st.columns(5)

total = data["total"]
prev = data["prev_total"]
change = ((total - prev) / prev * 100) if prev > 0 else 0

daily_df = data["daily"]
days = len(daily_df) if len(daily_df) > 0 else 1
cost_per_day = total / days

col0.metric("Cost / Day", f"€{cost_per_day:,.0f}", help=f"Average over {days} days with data")
col1.metric("Total", f"€{total:,.0f}", f"{change:+.1f}%" if prev > 0 else "—")
col2.metric("Providers", f"{len(data['by_provider'])}")
col3.metric("Business Units", f"{len(data['by_bu'])}")
col4.metric("Previous Month", f"€{prev:,.0f}" if prev > 0 else "—")

st.divider()

# ── Row 1: By BU + By Provider ──
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Cost by Business Unit")
    if len(data["by_bu"]) > 0:
        fig = px.pie(
            data["by_bu"],
            values="total",
            names="business_unit",
            hole=0.4,
        )
        fig.update_traces(textinfo="label+percent", textposition="outside")
        fig.update_layout(showlegend=False, margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig, use_container_width=True)

        bu_options = data["by_bu"]["business_unit"].tolist()
        gc1, gc2 = st.columns([3, 1])
        with gc1:
            target_bu = st.selectbox("Drill into BU", bu_options, key="overview_goto_bu")
        with gc2:
            st.write("")  # spacer to align with selectbox label
            if st.button("View detail →", key="overview_goto_bu_btn"):
                st.session_state["selected_bu"] = target_bu
                st.switch_page("pages/2_BU_detail.py")

with col_right:
    st.subheader("Cost by Provider")
    if len(data["by_provider"]) > 0:
        fig = px.bar(
            data["by_provider"],
            x="total",
            y="provider",
            orientation="h",
            text=data["by_provider"]["total"].apply(lambda x: f"€{x:,.0f}"),
        )
        fig.update_layout(
            yaxis=dict(categoryorder="total ascending"),
            xaxis_title="",
            yaxis_title="",
            margin=dict(t=20, b=20),
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

        provider_options = data["by_provider"]["provider"].tolist()
        gc1, gc2 = st.columns([3, 1])
        with gc1:
            target_provider = st.selectbox("Drill into provider", provider_options, key="overview_goto_provider")
        with gc2:
            st.write("")
            if st.button("View detail →", key="overview_goto_provider_btn"):
                st.session_state["selected_provider"] = target_provider
                st.switch_page("pages/1_Provider_detail.py")

# ── Row 2: Daily trend + Monthly evolution ──
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("Daily Cost (current month)")
    if len(data["daily"]) > 0:
        fig = px.bar(data["daily"], x="date", y="total")
        fig.update_layout(
            xaxis_title="",
            yaxis_title="€",
            margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig, use_container_width=True)

with col_right:
    st.subheader("Monthly Trend")
    trend = get_monthly_trend()
    if len(trend) > 0:
        fig = px.bar(
            trend,
            x="month",
            y="total",
            text=trend["total"].apply(lambda x: f"€{x:,.0f}"),
        )
        fig.update_layout(
            xaxis_title="",
            yaxis_title="€",
            xaxis_type="category",
            margin=dict(t=20, b=20),
        )
        fig.update_traces(textposition="outside")
        st.plotly_chart(fig, use_container_width=True)

# ── Row 3: BU x Provider heatmap ──
st.subheader("Business Unit × Provider")
if len(data["by_bu_provider"]) > 0:
    pivot = data["by_bu_provider"].pivot_table(
        index="business_unit",
        columns="provider",
        values="total",
        fill_value=0,
    )
    fig = px.imshow(
        pivot,
        text_auto=".0f",
        aspect="auto",
        color_continuous_scale="Blues",
    )
    fig.update_layout(margin=dict(t=20, b=20))
    st.plotly_chart(fig, use_container_width=True)

# ── Row 4: Trend by BU ──
st.subheader("Monthly Trend by Business Unit")
trend_bu = get_trend_by_bu()
if len(trend_bu) > 0:
    fig = px.line(trend_bu, x="month", y="total", color="business_unit", markers=True)
    fig.update_layout(
        xaxis_title="",
        yaxis_title="€",
        legend_title="",
        margin=dict(t=20, b=20),
    )
    st.plotly_chart(fig, use_container_width=True)

# ── Row 5: Top cost lines ──
st.subheader("Top 15 Cost Lines")
if len(data["top_lines"]) > 0:
    display = data["top_lines"].copy()
    display["total"] = display["total"].apply(lambda x: f"€{x:,.2f}")
    st.dataframe(
        display,
        use_container_width=True,
        hide_index=True,
        column_config={
            "business_unit": "Business Unit",
            "provider": "Provider",
            "category": "Category",
            "description": "Description",
            "total": "Amount",
        },
    )
