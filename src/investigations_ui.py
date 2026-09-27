"""Automatic descriptive monitoring inside the executive workspace."""
import streamlit as st
from src.investigations import anomalies, investigate
from src.date_ranges import latest_month_windows


def render_investigations(df):
    st.subheader('Anomalies and investigation')
    st.caption('Latest two complete calendar months within selected dates. Rules: utilization down ≥15% relative; no-show rate up ≥5 percentage points; revenue down with visits up; utilization change ≥15 points from at least three other specialty peers. Minimums: 100 slots per period, or 30 bookings for no-show checks. Heuristics, not significance tests.')
    bounds=(df.date.min().date(),df.date.max().date())
    windows=latest_month_windows(*bounds)
    snapshot,flags=anomalies(df,windows,bounds)
    st.caption(snapshot['message'])
    if snapshot['status']!='ok': st.info('Anomaly detection requires available observations in both comparison periods.')
    elif flags.empty: st.write('No configured thresholds triggered. This does not establish that performance is normal.')
    else: st.dataframe(flags,hide_index=True,width='stretch')
    st.caption('Only matched providers are screened; leave or missing observations may affect comparisons. No causal or clinical-quality conclusions.')
    if st.button('Investigate revenue change'):
        text,_=investigate(df,windows,bounds)
        st.markdown(text)
    st.caption('Collections and cancellations are not measured. The investigation uses reported revenue and explicitly identifies missing measures.')
