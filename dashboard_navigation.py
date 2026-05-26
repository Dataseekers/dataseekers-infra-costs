"""Page handles for the multipage dashboard.

Defined here (not in dashboard.py) so each page file can import the handles
and pass them to `st.page_link` for cross-page navigation. Using stable
Page objects sidesteps the path-string resolution issues `st.switch_page`
and `st.page_link` hit in some Streamlit versions.
"""

import streamlit as st

OVERVIEW = st.Page(
    "dashboard_overview.py",
    title="Overview",
    icon="💰",
    default=True,
    url_path="overview",
)

PROVIDER_DETAIL = st.Page(
    "views/Provider_detail.py",
    title="By provider",
    icon="⚙️",
    url_path="by_provider",
)

BU_DETAIL = st.Page(
    "views/BU_detail.py",
    title="By business unit",
    icon="🎯",
    url_path="by_business_unit",
)

ALL_PAGES = [OVERVIEW, PROVIDER_DETAIL, BU_DETAIL]
