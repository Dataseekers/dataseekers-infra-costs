#!/usr/bin/env python3
"""Streamlit entry point: registers pages via `st.navigation` and dispatches to them.

Page content lives in `dashboard_overview.py` and `pages/*.py`. Cross-page
links are built against the Page objects defined in `dashboard_navigation.py`,
which avoids the path-string resolution bugs of `st.switch_page`.
"""

import streamlit as st

from dashboard_navigation import ALL_PAGES

st.set_page_config(
    page_title="Dataseekers Costs",
    page_icon="💰",
    layout="wide",
)

pg = st.navigation(ALL_PAGES)
pg.run()
