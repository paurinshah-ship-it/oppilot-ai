"""Presentation helpers for the executive demo."""
import streamlit as st


def apply_style():
    st.markdown("""
    <style>
    .stApp {background: #F6F7FB;}
    /* Clear Streamlit's fixed toolbar so the compact header is fully visible. */
    /* Leave room below Streamlit's top toolbar so the right-side header copy is never clipped. */
    .block-container {padding: 3.5rem 2.25rem 2.5rem; max-width: 1720px;}
    h1 {letter-spacing: -1px; font-weight: 750;}
    h3 {letter-spacing: -.35px; font-size: 1.25rem;}
    [data-testid="stMetric"] {background: #FFFFFF; border: 1px solid #E7EAF1;
      border-top: 3px solid #5B6ED6; border-radius: 12px; padding: 16px;
      box-shadow: 0 3px 12px #18234A08;}
    [data-testid="stMetricLabel"] {color: #655F76; font-size: .95rem; white-space: normal;}
    [data-testid="stMetricValue"] {color: #352D4B; font-weight: 700; font-size: clamp(1.2rem, 1.8vw, 1.85rem);}
    /* Retain native metrics while grouping headline and operational measures. */
    .st-key-headline_kpis [data-testid="stMetric"] {
      background: #FFFFFF; border-top-color: #2F6BFF; min-height: 112px;
      padding: 18px 18px 16px;
    }
    .st-key-headline_kpis [data-testid="stMetricLabel"] {font-weight: 650; color: #62708A;}
    .st-key-headline_kpis [data-testid="stMetricValue"] {font-size: clamp(1.35rem, 2.25vw, 2.1rem); color: #18233F;}
    .st-key-overview_operational_kpis [data-testid="stMetric"] {
      background: transparent; border: 0; border-left: 1px solid #D9DFEA;
      border-radius: 0; padding: 4px 18px; min-height: 62px; box-shadow: none;
    }
    .st-key-overview_operational_kpis [data-testid="column"]:first-child [data-testid="stMetric"] {border-left: 0;}
    .st-key-overview_operational_kpis [data-testid="stMetricLabel"] {
      color: #65577D; font-weight: 600; letter-spacing: .02em; margin-bottom: 4px;
    }
    .st-key-overview_operational_kpis [data-testid="stMetricValue"] {
      color: #253554; font-size: clamp(1.05rem, 1.55vw, 1.45rem);
      font-weight: 750; letter-spacing: -.04em; font-variant-numeric: tabular-nums;
    }
    [data-testid="stTabs"] {margin-top: 28px;}
    [role="tablist"] {display: flex; gap: 8px; background: #EEF2F8; padding: 6px;
      border: 1px solid #DCE4F0; border-radius: 14px; border-bottom: 1px solid #DCE4F0;}
    [role="tab"] {border: 1px solid transparent; border-radius: 9px; padding: 11px 15px;
      min-height: 48px; color: #3A4964; font-size: 1.02rem; font-weight: 700;}
    [role="tab"][aria-selected="true"] {background: #1E4FAF; color: #FFFFFF; font-weight: 750;
      border: 1px solid #1E4FAF; box-shadow: 0 4px 10px #1E4FAF2A;}
    .executive-header {background: transparent; border: 0;
      padding: 6px 0 12px; border-radius: 0; color: #17233D; margin-bottom: 0;
      display: flex; align-items: center; justify-content: space-between; gap: 18px;}
    .executive-header .eyebrow {font-size: 10px; letter-spacing: 1.6px; color: #5E6E8A;}
    .executive-header h1 {font-size: 22px; color: #17233D; padding: 3px 0; margin: 0;}
    .executive-header p {color: #5E6E8A; margin: 0; font-size: 13px; text-align: right;}
    /* Readable text, generous targets, and visible keyboard focus across the UI. */
    [data-testid="stCaptionContainer"] {color: #595267; font-size: .95rem; line-height: 1.6;}
    [data-testid="stWidgetLabel"] p {font-size: 1rem; font-weight: 600;}
    .stButton button, .stDownloadButton button {min-height: 44px; border-radius: 10px;
      border-color: #C9BEDD; font-weight: 600;}
    button:focus-visible, input:focus-visible, textarea:focus-visible,
    summary:focus-visible, [role="tab"]:focus-visible {
      outline: 3px solid #594299 !important; outline-offset: 3px;
    }
    [role="tablist"] {flex-wrap: wrap; overflow: visible; height: auto;}
    [role="tab"] {height: auto; letter-spacing: .005em;}
    [data-testid="stTabs"] [data-testid="stTabPanel"] {padding-top: 26px;}
    .tab-page-heading {display: flex; align-items: baseline; justify-content: space-between; gap: 20px;
      margin: 0 0 22px; padding: 0 0 16px; border-bottom: 1px solid #DCE4F0;}
    .tab-page-heading h2 {color: #162B50; font-size: clamp(1.45rem, 2vw, 1.8rem); letter-spacing: -.03em; margin: 0;}
    .tab-page-heading p {color: #5A6982; font-size: 1rem; line-height: 1.5; margin: 0; max-width: 700px;}
    [data-testid="stExpander"] {background: #FFFFFF; border: 1px solid #E4E8F0; border-radius: 12px;}
    [data-testid="stExpander"] summary {min-height: 48px;}
    [data-testid="stChatMessage"] {background: #FFFFFF; border: 1px solid #E4DFF0;
      border-radius: 16px; padding: 20px; line-height: 1.65;}
    [data-testid="stChatInput"] {border: 1px solid #A99AC4; border-radius: 14px;}
    .context-strip {display: grid; grid-template-columns: 1fr 1.4fr 1.4fr; align-items: center;
      gap: 20px; min-height: 62px; padding: 10px 0 12px; margin-bottom: 12px;
      border-top: 1px solid #E0E6EF; border-bottom: 1px solid #E0E6EF; color: #263653;}
    .context-strip > div {min-width: 0;}
    .context-label {display: block; color: #6C7890; font-size: .72rem; font-weight: 750;
      letter-spacing: .07em; margin-bottom: 2px; text-transform: uppercase;}
    .context-strip strong {display: block; font-size: .91rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;}
    .dashboard-section-kicker {color: #69758B; font-size: .78rem; font-weight: 800;
      letter-spacing: .09em; margin: 22px 0 7px; text-transform: uppercase;}
    .st-key-operations_copilot {background: linear-gradient(100deg, #EFF5FF 0%, #F7F9FF 100%);
      border: 1px solid #D9E4FA; border-radius: 14px; padding: 20px 22px 18px; margin: 20px 0 8px;}
    .operations-copilot-heading {display: flex; align-items: end; justify-content: space-between;
      gap: 16px; padding-bottom: 13px; margin-bottom: 14px; border-bottom: 1px solid #D8E3F7;}
    .operations-copilot-heading h2 {color: #1C315A; font-size: 1.2rem; letter-spacing: -.02em; margin: 2px 0 0;}
    .operations-copilot-heading p {color: #60708B; font-size: .88rem; margin: 0; text-align: right;}
    .copilot-mark {color: #2F6BFF; font-size: 1rem; margin-right: 7px;}
    .copilot-eyebrow {color: #3156AA; font-size: .76rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase;}
    .st-key-operations_copilot h5 {color: #31466D; font-size: .82rem; font-weight: 800; letter-spacing: .035em; margin: 0 0 7px; text-transform: uppercase;}
    .st-key-operations_copilot [data-testid="stMarkdownContainer"] p {color: #273752; line-height: 1.5; min-height: 48px;}
    .st-key-operations_copilot .stButton button {background: transparent; border: 1px solid #B9C9E9; color: #244EA8; min-height: 38px; padding: 4px 12px;}
    .st-key-text_chat_help {margin: 26px 0 5.5rem;}
    .st-key-provider_comparison_shell {padding: 4px 0 8px;}
    .st-key-provider_comparison_shell [role="tablist"] {margin: 14px 0 8px; gap: 22px;}
    .st-key-provider_comparison_shell [role="tab"] {font-size: .95rem;}
    .st-key-comparison_drilldown {background: #FFFFFF; border-top: 1px solid #DEE5EF;
      margin-top: 26px; padding: 22px 0 0;}
    .st-key-comparison_drilldown h4 {color: #24385F; margin-bottom: 2px;}
    .drilldown-stat {border-left: 2px solid #98B6F8; padding: 6px 0 6px 12px; margin: 8px 0 14px;}
    .drilldown-stat span {color: #64738E; display: block; font-size: .79rem; font-weight: 700; letter-spacing: .03em; text-transform: uppercase;}
    .drilldown-stat strong {color: #1D3158; display: block; font-size: 1.3rem; margin-top: 2px;}
    .st-key-executive_center_shell [role="tablist"] {margin: 14px 0 12px; gap: 22px;}
    .st-key-executive_center_shell [role="tab"] {font-size: .95rem;}
    .st-key-executive_center_shell h4 {color: #24385F; margin-bottom: 3px;}
    .st-key-refinement_view [role="radiogroup"] {display: flex; flex-wrap: wrap; gap: 8px;}
    .st-key-refinement_view label {background: #FFFFFF; border: 1px solid #D8E0EC; border-radius: 8px;
      margin: 0; min-height: 38px; padding: 7px 14px;}
    /* The calculation widgets retain the established filter state for the app
       and automated coverage. Selection happens in the persistent dialogs. */
    div.stVerticalBlock.st-key-team_filter_state {
      position: absolute !important; width: 1px !important; height: 1px !important;
      margin: 0 !important; overflow: hidden !important; opacity: 0 !important;
      pointer-events: none !important;
    }
    .overview-section-title {font-size: 1.1rem; font-weight: 750; color: #1D2C49; margin: 24px 0 4px;}
    .overview-section-note {font-size: .91rem; color: #61708B; margin-bottom: 8px;}
    [data-testid="stDataFrame"] {border: 1px solid #E0E6F0; border-radius: 12px; overflow: hidden;}
    @media (max-width: 760px) {
      .block-container {padding: 1rem;}
      .executive-header {padding: 16px; display: block;}
      .executive-header h1 {font-size: 26px;}
      .executive-header p {text-align: left; margin-top: 6px;}
      [role="tab"] {padding: 10px;}
      .tab-page-heading {display: block;}
      .tab-page-heading p {margin-top: 6px;}
      [data-testid="stMetricValue"] {overflow-wrap: anywhere; white-space: normal;}
      .context-strip {grid-template-columns: 1fr; gap: 9px; padding: 12px 0;}
      .operations-copilot-heading {display: block;}
      .operations-copilot-heading p {text-align: left; margin-top: 6px;}
    }
    </style>
    """, unsafe_allow_html=True)


def header():
    st.markdown("""
    <div class="executive-header">
      <div><div class="eyebrow">HEALTHCARE OPERATIONS INTELLIGENCE</div><h1>Provider Performance Copilot</h1></div>
      <p>Executive operations workspace<br>Performance, capacity, and opportunity</p>
    </div>
    """, unsafe_allow_html=True)
    st.caption("UPLOADED AGGREGATES · User confirmed non-PHI · Local analytics" if "uploaded_data" in st.session_state else "SYNTHETIC DEMO · Portfolio Project · Fictional providers · No patient data or PHI")
