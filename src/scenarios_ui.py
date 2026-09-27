"""Scenario controls are independent of dashboard targets and team filters."""
import streamlit as st
from src.scenarios import scenario_metrics, scenario_text, scenario_totals
from src.date_ranges import format_range


def render_scenarios(df,target):
    st.subheader('Scenario simulator')
    st.caption('These assumptions apply only to this simulator. Dashboard filters and the dashboard target remain unchanged.')
    names=st.multiselect('Scenario providers',sorted(df.provider.unique()),default=sorted(df.provider.unique()),key='scenario_providers')
    utilization=st.slider('Scenario target utilization (%)',0,100,round(target*100),key='scenario_utilization')/100
    no_show=st.slider('Scenario target no-show rate (%)',0,100,8,key='scenario_no_show')/100
    override=st.checkbox('Use an assumed revenue per visit',key='scenario_override')
    rate=st.slider('Assumed revenue per visit ($)',0,2000,250,step=10,disabled=not override,key='scenario_rate')
    rows=df[df.provider.isin(names)]
    if rows.empty:
        st.info('Select at least one scenario provider.')
        return
    st.caption(f'Analysis period: {format_range(rows.date.min().date(),rows.date.max().date())} · {rows.provider_id.nunique()} providers · {len(rows):,} provider-day records. No monthly extrapolation.')
    p=scenario_metrics(rows,utilization,no_show,rate if override else None)
    st.dataframe(scenario_totals(p),hide_index=True,width="stretch")
    st.caption("These are alternative scenarios, not additive components. Revenue totals exclude unknown rates; blank totals mean every rate is unknown.")
    st.markdown(scenario_text(p,utilization,no_show,rate if override else None))
    unknown=int(p.scenario_rate.isna().sum())
    if unknown:
        st.info(f'{unknown} providers have unknown observed revenue rates. Their additional revenue is unavailable; use an explicit assumed rate to model them.')
    with st.expander('Scenario formulas'):
        st.write('No-show recovery = min(unused slots, max(0, observed no-shows − target no-show rate × bookings)). Utilization recovery = min(unused slots, max(0, target utilization × capacity − visits)). Each revenue estimate = recovered visits × observed provider revenue/visit or the explicit assumed rate. Never add the two recovery scenarios together.')
    st.caption('Ask-to-chart examples in Ask copilot: “Chart monthly utilization by provider in 2025” or “Show no-show rates from highest to lowest in August 2025”.')
