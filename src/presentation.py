"""Presentation helpers for the executive demo."""
import streamlit as st


def apply_style():
    st.markdown("""
    <style>
    .stApp {background: #F6F7FB;}
    /* Clear Streamlit's fixed toolbar so the compact header is fully visible. */
    .block-container {padding: 3.25rem 1.75rem 2.5rem; max-width: 1680px;}
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
    [data-testid="stTabs"] {margin-top: 20px;}
    [role="tablist"] {gap: 20px; background: transparent; padding: 0 4px; border-radius: 0; border-bottom: 1px solid #DEE4EE;}
    [role="tab"] {border-radius: 0; padding: 12px 2px 10px; border-bottom: 3px solid transparent;}
    [role="tab"][aria-selected="true"] {background: transparent; color: #2453D4; font-weight: 700; border: 0; border-bottom: 3px solid #2F6BFF; box-shadow: none;}
    .executive-header {background: #FFFFFF; border: 1px solid #E2E7F0;
      padding: 15px 20px; border-radius: 14px; color: #17233D; margin-bottom: 10px;
      display: flex; align-items: center; justify-content: space-between; gap: 18px;}
    .executive-header .eyebrow {font-size: 10px; letter-spacing: 1.6px; color: #5E6E8A;}
    .executive-header h1 {font-size: 23px; color: #17233D; padding: 3px 0; margin: 0;}
    .executive-header p {color: #5E6E8A; margin: 0; font-size: 14px; text-align: right;}
    /* Readable text, generous targets, and visible keyboard focus across the UI. */
    [data-testid="stCaptionContainer"] {color: #595267; font-size: .95rem; line-height: 1.6;}
    [data-testid="stWidgetLabel"] p {font-size: 1rem; font-weight: 600;}
    .stButton button, .stDownloadButton button {min-height: 44px; border-radius: 10px;
      border-color: #C9BEDD; font-weight: 600;}
    button:focus-visible, input:focus-visible, textarea:focus-visible,
    summary:focus-visible, [role="tab"]:focus-visible {
      outline: 3px solid #594299 !important; outline-offset: 3px;
    }
    [role="tablist"] {flex-wrap: wrap; overflow: visible; height: auto; gap: 8px;}
    [role="tab"] {min-height: 44px; height: auto; color: #4D435F;}
    [data-testid="stExpander"] {background: #FFFFFF; border: 1px solid #E4E8F0; border-radius: 12px;}
    [data-testid="stExpander"] summary {min-height: 48px;}
    [data-testid="stChatMessage"] {background: #FFFFFF; border: 1px solid #E4DFF0;
      border-radius: 16px; padding: 20px; line-height: 1.65;}
    [data-testid="stChatInput"] {border: 1px solid #A99AC4; border-radius: 14px;}
    .st-key-dashboard_filters {background: #FFFFFF; border-radius: 16px;}
    .priority-panel {background: linear-gradient(100deg, #EEF4FF, #F7F9FF); border: 1px solid #D7E3FF;
      border-radius: 14px; padding: 18px 20px; margin: 18px 0 8px; color: #213657;}
    .priority-panel .priority-title {font-size: 1rem; font-weight: 750; color: #2147A9; margin-bottom: 8px;}
    .priority-panel ul {margin: 0; padding-left: 20px; line-height: 1.7;}
    .priority-panel .priority-note {font-size: .87rem; color: #5E6E8A; margin-top: 8px;}
    .overview-section-title {font-size: 1.1rem; font-weight: 750; color: #1D2C49; margin: 24px 0 4px;}
    .overview-section-note {font-size: .91rem; color: #61708B; margin-bottom: 8px;}
    @media (max-width: 760px) {
      .block-container {padding: 1rem;}
      .executive-header {padding: 16px; display: block;}
      .executive-header h1 {font-size: 26px;}
      .executive-header p {text-align: left; margin-top: 6px;}
      [role="tab"] {padding: 10px;}
      [data-testid="stMetricValue"] {overflow-wrap: anywhere; white-space: normal;}
    }
    </style>
    """, unsafe_allow_html=True)


def header():
    st.markdown("""
    <div class="executive-header">
      <div><h1>Provider Performance Copilot</h1></div>
      <p>Selected-team analytics<br>and operational priorities</p>
    </div>
    """, unsafe_allow_html=True)
    st.caption("UPLOADED AGGREGATES · User confirmed non-PHI · Local analytics" if "uploaded_data" in st.session_state else "SYNTHETIC DEMO · Portfolio Project · Fictional providers · No patient data or PHI")
