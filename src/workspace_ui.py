"""Streamlit executive workspace; calculation functions remain independently testable."""
import hashlib
import pandas as pd
import streamlit as st
from src.workspace import (executive_summary, top_opportunities, scorecard,
                           specialty_metrics, trend_snapshot, investigation, DEFINITIONS)
from src.comparative import formatted, change_text
from src.date_ranges import format_range
from src.investigations_ui import render_investigations
from src.recommendations_ui import render_recommendations


def render_workspace(df, target):
    st.subheader('Executive operations workspace')
    st.caption('Selected-team metrics, provider details, and management review. All findings are calculated locally; no API credentials are needed.')
    window = format_range(df.date.min().date(), df.date.max().date())
    st.caption(f'Selected period: {window} · {df.provider_id.nunique()} providers · {len(df):,} provider-day records')
    trend = trend_snapshot(df)
    scope_key = hashlib.sha256((df.to_csv(index=False) + str(target)).encode()).hexdigest()
    if st.button('Generate Executive Summary', type='primary'):
        st.session_state.workspace_summary = {'key':scope_key, 'text':executive_summary(df,target,trend)}
    saved = st.session_state.get('workspace_summary')
    if saved and saved['key'] == scope_key:
        with st.container(border=True):
            st.markdown(saved['text'])
    elif saved:
        st.info('Selection or target changed. Generate a new executive summary for the current scope.')

    render_recommendations(df, target, uploads_active="uploaded_data" in st.session_state)

    st.subheader('Top Opportunities')
    st.caption('Each category retains tied leaders. Slot counts, rates, and modeled dollars have different units; overlapping opportunities must not be added together.')
    opportunities = top_opportunities(df,target,trend)
    if opportunities.empty:
        st.info('No measured opportunity rules trigger for this selection.')
    else:
        st.dataframe(opportunities, hide_index=True, width='stretch')
    st.caption('Month-over-month trend availability: ' + trend['message'])

    render_investigations(df)

    st.subheader('Provider detail')
    provider = st.selectbox('Choose a provider for the scorecard', sorted(df.provider.unique()), key='workspace_provider')
    left,right = st.columns(2)
    with left:
        st.markdown(f'**{provider} · selected-period dimensions**')
        st.dataframe(scorecard(df,provider,target), hide_index=True, width='stretch')
        st.caption('Dimensions are shown separately; there is no composite provider score. Collections are not measured.')
    with right:
        st.markdown('**Latest two complete calendar months within the selection**')
        st.caption(trend['message'])
        rows = trend['changes']
        match = rows[rows.provider == provider] if not rows.empty else rows
        if trend['status']=='ok' and not match.empty:
            row = match.iloc[0]
            changes = []
            for metric,label in [('utilization','Utilization'),('no_show_rate','No-show rate'),('visits','Completed visits')]:
                a,b = row[f'{metric}_before'],row[f'{metric}_after']
                changes.append([label,formatted(a,metric),formatted(b,metric),change_text(a,b,metric)])
            st.dataframe(pd.DataFrame(changes,columns=['Metric','First period','Second period','Change']),hide_index=True,width='stretch')
            with st.expander('Investigate utilization change'):
                st.markdown(investigation(provider,trend))
        else:
            st.info('A matched two-month trend is unavailable for this provider. No directional claim is shown.')

    st.subheader('Specialty comparisons')
    choices = sorted(df.specialty.unique())
    selected = st.multiselect('Compare selected specialties',choices,default=choices,key='workspace_specialties')
    specialties = specialty_metrics(df[df.specialty.isin(selected)],target) if selected else pd.DataFrame()
    if specialties.empty:
        st.info('Select at least one specialty.')
    else:
        st.dataframe(specialties[['specialty','visits','capacity','utilization','no_show_rate','revenue','revenue_per_visit','unused_capacity','opportunity','unknown_rates']],hide_index=True,width='stretch',column_config={
            'utilization':st.column_config.NumberColumn('Utilization',format='percent'),
            'no_show_rate':st.column_config.NumberColumn('No-show rate',format='percent'),
            'revenue':st.column_config.NumberColumn('Revenue',format='dollar'),
            'revenue_per_visit':st.column_config.NumberColumn('Revenue / visit',format='dollar'),
            'opportunity':st.column_config.NumberColumn('Modeled opportunity',format='dollar'),
            'unknown_rates':st.column_config.NumberColumn('Providers with unknown revenue rates'),
        })
    st.caption('Ratios use summed numerators and denominators. Opportunity sums provider-level estimates and excludes unknown rates. Specialty mix and visit complexity differ.')
    with st.expander('Explain a metric'):
        term = st.selectbox('Metric formula',list(DEFINITIONS),key='workspace_formula')
        st.write(DEFINITIONS[term])


def render_executive_opportunities(df, target):
    """Render executive recommendations and investigations without provider-detail controls."""
    window = format_range(df.date.min().date(), df.date.max().date())
    trend = trend_snapshot(df)
    scope_key = hashlib.sha256((df.to_csv(index=False) + str(target)).encode()).hexdigest()
    st.caption(f'Selected period: {window} · {df.provider_id.nunique()} providers · {len(df):,} provider-day records')
    if st.button('Generate Executive Summary', type='primary', key='executive_center_summary'):
        st.session_state.workspace_summary = {'key': scope_key, 'text': executive_summary(df, target, trend)}
    saved = st.session_state.get('workspace_summary')
    if saved and saved['key'] == scope_key:
        st.markdown(saved['text'])
    elif saved:
        st.info('Selection or target changed. Generate a new executive summary for the current scope.')
    render_recommendations(df, target, uploads_active='uploaded_data' in st.session_state)
    st.subheader('Top opportunities')
    st.caption('Each category retains tied leaders. Slot counts, rates, and modeled dollars have different units; overlapping opportunities must not be added together.')
    opportunities = top_opportunities(df, target, trend)
    if opportunities.empty:
        st.info('No measured opportunity rules trigger for this selection.')
    else:
        st.dataframe(opportunities, hide_index=True, width='stretch')
    st.caption('Month-over-month trend availability: ' + trend['message'])
    render_investigations(df)


def render_provider_and_specialty_detail(df, target):
    """Render the comparison-oriented executive detail in one focused view."""
    trend = trend_snapshot(df)
    st.caption(f'Selected period: {format_range(df.date.min().date(), df.date.max().date())} · {df.provider_id.nunique()} providers · {len(df):,} provider-day records')
    st.subheader('Provider detail')
    provider = st.selectbox('Choose a provider for the scorecard', sorted(df.provider.unique()), key='executive_provider')
    left, right = st.columns(2)
    with left:
        st.markdown(f'**{provider} · selected-period dimensions**')
        st.dataframe(scorecard(df, provider, target), hide_index=True, width='stretch')
        st.caption('Dimensions are shown separately; there is no composite provider score. Collections are not measured.')
    with right:
        st.markdown('**Latest two complete calendar months within the selection**')
        st.caption(trend['message'])
        rows = trend['changes']
        match = rows[rows.provider == provider] if not rows.empty else rows
        if trend['status'] == 'ok' and not match.empty:
            row = match.iloc[0]
            changes = []
            for metric, label in [('utilization', 'Utilization'), ('no_show_rate', 'No-show rate'), ('visits', 'Completed visits')]:
                before, after = row[f'{metric}_before'], row[f'{metric}_after']
                changes.append([label, formatted(before, metric), formatted(after, metric), change_text(before, after, metric)])
            st.dataframe(pd.DataFrame(changes, columns=['Metric', 'First period', 'Second period', 'Change']), hide_index=True, width='stretch')
            with st.expander('Investigate utilization change'):
                st.markdown(investigation(provider, trend))
        else:
            st.info('A matched two-month trend is unavailable for this provider. No directional claim is shown.')
    st.divider()
    st.subheader('Specialty comparisons')
    choices = sorted(df.specialty.unique())
    selected = st.multiselect('Compare selected specialties', choices, default=choices, key='executive_specialties')
    specialties = specialty_metrics(df[df.specialty.isin(selected)], target) if selected else pd.DataFrame()
    if specialties.empty:
        st.info('Select at least one specialty.')
    else:
        st.dataframe(specialties[['specialty', 'visits', 'capacity', 'utilization', 'no_show_rate', 'revenue', 'revenue_per_visit', 'unused_capacity', 'opportunity', 'unknown_rates']], hide_index=True, width='stretch', column_config={
            'utilization': st.column_config.NumberColumn('Utilization', format='percent'),
            'no_show_rate': st.column_config.NumberColumn('No-show rate', format='percent'),
            'revenue': st.column_config.NumberColumn('Revenue', format='dollar'),
            'revenue_per_visit': st.column_config.NumberColumn('Revenue / visit', format='dollar'),
            'opportunity': st.column_config.NumberColumn('Modeled opportunity', format='dollar'),
            'unknown_rates': st.column_config.NumberColumn('Providers with unknown revenue rates'),
        })
    st.caption('Ratios use summed numerators and denominators. Opportunity sums provider-level estimates and excludes unknown rates. Specialty mix and visit complexity differ.')
    with st.expander('Explain a metric'):
        term = st.selectbox('Metric formula', list(DEFINITIONS), key='executive_formula')
        st.write(DEFINITIONS[term])
