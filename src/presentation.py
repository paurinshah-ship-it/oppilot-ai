"""Presentation helpers for the executive demo."""
import streamlit as st


def apply_style():
    st.markdown("""
    <style>
    .stApp {background: #F6F5FA;}
    .block-container {padding: 2rem 1.75rem; max-width: 1700px;}
    h1 {letter-spacing: -1px; font-weight: 750;}
    h3 {letter-spacing: -.35px; font-size: 1.25rem;}
    [data-testid="stMetric"] {background: #FFFFFF; border: 1px solid #E4DFF0;
      border-top: 3px solid #7563B5; border-radius: 12px; padding: 16px;
      box-shadow: 0 3px 12px #30204C06;}
    [data-testid="stMetricLabel"] {color: #655F76; font-size: .83rem; white-space: normal;}
    [data-testid="stMetricValue"] {color: #352D4B; font-weight: 700; font-size: clamp(1.2rem, 1.8vw, 1.85rem);}
    /* Scope the operational KPI treatment to this row; retain native metrics. */
    .st-key-overview_operational_kpis [data-testid="stMetric"] {
      background: linear-gradient(135deg, #FFFFFF 35%, #F0ECF8);
      border: 1px solid #DDD5EC; border-left: 4px solid #7563B5;
      border-radius: 16px; padding: 10px 16px; min-height: 88px;
      box-shadow: 0 4px 16px #33254F08;
    }
    .st-key-overview_operational_kpis [data-testid="stMetricLabel"] {
      color: #65577D; font-weight: 600; letter-spacing: .02em; margin-bottom: 4px;
    }
    .st-key-overview_operational_kpis [data-testid="stMetricValue"] {
      color: #443260; font-size: clamp(1.25rem, 2vw, 2rem);
      font-weight: 750; letter-spacing: -.04em; font-variant-numeric: tabular-nums;
    }
    [data-testid="stTabs"] {margin-top: 18px;}
    [role="tablist"] {gap: 6px; background: #EDE9F5; padding: 6px; border-radius: 12px;}
    [role="tab"] {border-radius: 8px; padding: 10px 14px;}
    [role="tab"][aria-selected="true"] {background: white; color: #594299; font-weight: 650;}
    .executive-header {background: linear-gradient(110deg, #33254F, #7561A3);
      padding: 24px 28px; border-radius: 16px; color: white; margin-bottom: 16px;}
    .executive-header .eyebrow {font-size: 11px; letter-spacing: 2px; color: #DDD3F1;}
    .executive-header h1 {font-size: 30px; color: white; padding: 8px 0;}
    .executive-header p {color: #F0EAF8; margin: 0; font-size: 14px;}
    </style>
    """, unsafe_allow_html=True)


def header():
    st.markdown("""
    <div class="executive-header">
      <div class="eyebrow">AMBULATORY OPERATIONS · EXECUTIVE OVERVIEW</div>
      <h1>Provider Performance Copilot</h1>
      <p>Understand performance. Compare providers. Prioritize opportunities.</p>
    </div>
    """, unsafe_allow_html=True)
    st.caption("UPLOADED AGGREGATES · User confirmed non-PHI · Local analytics" if "uploaded_data" in st.session_state else "SYNTHETIC DEMO · Fictional providers · No patient data or PHI")
