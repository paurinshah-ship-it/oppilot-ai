import pandas as pd
import streamlit as st
from src.data import DATA_PATH, validate_data
from src.postgres_analytics import load_dashboard_data, postgres_configured
from src.analytics import benchmark, answer, calculate_kpis, monthly_performance, detect_opportunities
from src.charts import (visits_chart, revenue_chart, utilization_chart,
                        productivity_chart, provider_revenue_chart, utilization_trend_chart,
                        opportunity_concentration_chart)
from src.presentation import apply_style, header
from src.forecasting_ui import render_forecasting
from src.insights import executive_insights
from src.conversation import respond, SUGGESTIONS, COMPARISON_QUESTIONS
from src.voice import render_voice
from src.workspace_ui import render_executive_opportunities, render_provider_and_specialty_detail
from src.scenarios_ui import render_scenarios
from src.scenarios import SCENARIO_QUESTIONS
from src.data_reporting_ui import render_data_controls, render_reporting
from src.access_control import demo_profiles, scope_data, scope_description
from src.copilot_audit import record_query, render_calculation_path, render_audit_trail
from src.semantic_metrics import catalog_records
from src.query_explanation import explain_plan
from src.semantic_query import EXAMPLES as SEMANTIC_QUESTIONS
import hashlib
import html
from ai_copilot import build_context, context_key, configuration_ready, generate_brief, CopilotError

st.set_page_config(page_title="Provider Performance Copilot", page_icon="📊", layout="wide")

apply_style()

@st.cache_data
def read_data(source_revision):
    return load_dashboard_data()


def render_executive_brief(filtered, target, query_data, data_bounds, dates, audit_filters):
    """Keep executive-brief generation in one focused, auditable executive view."""
    if 'uploaded_data' in st.session_state:
        st.info('Cloud executive briefs are disabled for uploaded data. Use the calculated Executive Summary in Operational priorities.')
        return
    try:
        brief_context = build_context(filtered, target)
        current_key = context_key(brief_context)
        live = st.button('Generate AI Executive Brief', type='primary')
        if not configuration_ready():
            st.info('Local mode: Generate AI Executive Brief will produce a calculated brief without a model call. To enable AI-prioritized actions, configure OPENAI_API_KEY and OPENAI_MODEL in the server environment and restart Streamlit. Never enter credentials in chat.')
        st.caption('Calculated findings plus AI-prioritized management actions. Rankings use utilization, retain ties, and do not measure clinical quality.')
        st.info('Only verified synthetic aggregates are sent to OpenAI. No raw records, free-text prompts, or patient data are sent. Recommendations require management review.')
        with st.expander('Review calculated metrics sent to the model'):
            st.json(brief_context)
        if live:
            st.session_state.pop('executive_brief', None)
            with st.spinner('Preparing executive brief…'):
                st.session_state.executive_brief = generate_brief(filtered, target, use_ai=configuration_ready())
            generated = st.session_state.executive_brief
            audit_response = {
                'text': '\n\n'.join(generated['sections'].values()), 'status': 'answered',
                'grounding_details': [{'label': 'Executive brief inputs', 'start': dates[0], 'end': dates[1],
                                       'providers': int(filtered.provider_id.nunique()), 'records': len(filtered)}],
            }
            record_query(st.session_state, 'Generate AI Executive Brief', audit_response, query_data,
                         audit_filters, 'Executive brief generation')
        brief = st.session_state.get('executive_brief')
        if brief and brief['context_key'] == current_key:
            st.caption(brief['mode'])
            for title, body in brief['sections'].items():
                with st.container(border=True):
                    st.subheader(title)
                    st.text(body)
            st.warning(brief['guardrails'])
            st.caption(f'Brief period: {dates[0]:%b %d, %Y} – {dates[1]:%b %d, %Y} · {len(filtered):,} provider-day records')
            discussion_scope = hashlib.sha256((query_data.to_csv(index=False) + filtered.to_csv(index=False) + str(target)).encode()).hexdigest()
            if st.session_state.get('brief_discussion_scope') != discussion_scope:
                st.session_state.brief_discussion = []
                st.session_state.brief_discussion_scope = discussion_scope
            st.markdown('#### Discuss this brief')
            if st.button('Clear brief conversation'):
                st.session_state.brief_discussion = []
            with st.form('brief_follow_up', clear_on_submit=True):
                brief_question = st.text_input('Question about this brief', placeholder='Where is our largest revenue opportunity?', max_chars=1000)
                ask_brief = st.form_submit_button('Ask about brief', type='primary')
            if ask_brief and brief_question.strip():
                reply = respond(brief_question, filtered, target, st.session_state.brief_discussion, raw_df=query_data, data_bounds=data_bounds)
                record_query(st.session_state, brief_question, reply, query_data, audit_filters, 'Executive brief discussion')
                st.session_state.brief_discussion.extend([{'role': 'user', 'text': brief_question}, {'role': 'assistant', **reply}])
                st.session_state.brief_discussion = st.session_state.brief_discussion[-40:]
            for start in reversed(range(0, len(st.session_state.brief_discussion), 2)):
                for message in st.session_state.brief_discussion[start:start + 2]:
                    with st.chat_message(message['role']):
                        st.markdown(message['text'])
                        if message['role'] == 'assistant':
                            audit = next((item for item in st.session_state.get('copilot_audit', []) if item['audit_id'] == message.get('audit_id')), None)
                            if audit:
                                render_calculation_path(audit)
                            st.caption(message.get('grounding', 'No metrics calculated') + ' · ' + message['status'])
                            if message.get('chart') is not None:
                                st.plotly_chart(message['chart'], width='stretch', key=f'brief_chart_{start}')
        elif brief:
            st.info('Filters or target changed. Generate a new brief for this selection.')
    except CopilotError as exc:
        st.error(str(exc))


@st.dialog('Team selector', dismissible=True)
def render_team_selector(title, field_label, options, state_key, empty_label):
    """Persistent selector dialog: it remains open while multiple choices are made."""
    st.subheader(title)
    st.caption('Select any number of options. This window stays open while you choose; use the × in the upper-right corner when finished.')
    selected = st.multiselect(field_label, options, key=state_key, placeholder=empty_label)
    st.caption(f'{len(selected)} selected')


def sync_filter_widget(widget_key, selection_key):
    """Copy a test-compatible hidden control into the dialog's canonical state."""
    st.session_state[selection_key] = list(st.session_state[widget_key])

try:
    source_revision = "postgres" if postgres_configured() else DATA_PATH.stat().st_mtime_ns
    df = read_data(source_revision)
except (OSError, ValueError, pd.errors.ParserError) as exc:
    st.error(f"Unable to load provider data: {exc}")
    st.stop()
if 'uploaded_data' in st.session_state:
    df = st.session_state.uploaded_data
try:
    # A defensive gate also protects against an invalid dataframe being placed
    # directly into session state. No metrics, report, or copilot path runs
    # until the aggregate provider-day contract is valid.
    df = validate_data(df)
except ValueError as exc:
    header()
    st.error(f"Data validation failed. Dashboard and copilot analysis are disabled: {exc}")
    st.caption("Correct the source file and upload it again. The app does not infer or repair operational measures.")
    render_data_controls()
    st.stop()
header()
if postgres_configured():
    st.caption("Data source: PostgreSQL aggregate provider-day tables. No patient-level records are stored.")
revision = st.session_state.get('dataset_revision', 0)
context_summary = st.empty()
with st.expander("Adjust view & filters", expanded=True):
    st.markdown("### 1. Set your reporting context")
    access, period_controls = st.columns([1, 1.6], gap="large")
    with access:
        st.markdown("##### Viewing access")
        profiles = demo_profiles(df)
        profile_by_key = {profile.key: profile for profile in profiles}
        selected_profile_key = st.selectbox(
            "View as",
            options=list(profile_by_key),
            format_func=lambda key: profile_by_key[key].label,
            key="demo_access_profile",
            help="Changes the in-memory aggregate data scope used by this demo.",
        )
        active_profile = profile_by_key[selected_profile_key]
        df = scope_data(df, active_profile)
        st.caption(scope_description(active_profile, len(df)))
        st.caption("Demo selector only — production access requires authenticated, server-enforced roles.")
    with period_controls:
        st.markdown("##### Reporting period")
        st.caption("Choose the dates for this analysis.")
        period = st.selectbox("Reporting period", ["All available data" if "uploaded_data" in st.session_state else "All five years", "Latest calendar year", "Latest two calendar years", "Custom dates"], index=1)
        range_end = df.date.max().date()
        range_start = df.date.min().date()
        if period == "Latest calendar year":
            range_start = pd.Timestamp(range_end.year, 1, 1).date()
        elif period == "Latest two calendar years":
            range_start = pd.Timestamp(range_end.year - 1, 1, 1).date()
        range_start = max(range_start, df.date.min().date())
        # The widget alone owns its value. Each preset has a distinct range widget,
        # avoiding conflicting session-state writes and preserving range-mode typing.
        dates = st.date_input("Date range", value=(range_start, range_end),
                             min_value=df.date.min().date(), max_value=df.date.max().date(),
                             key=f"report_dates_{revision}_{period}")
    st.divider()
    st.markdown("### 2. Refine the team")
    st.caption("Select specialties and clinics first, then choose the providers you want to compare. Each selector stays open while you make multiple choices.")
    refinement_view = st.radio("Refinement view", ["Specialties", "Clinics", "Providers"], horizontal=True,
                                label_visibility="collapsed", key="refinement_view")
    specialty_state = f"specialties_{revision}"
    clinic_state = f"clinics_{revision}"
    provider_state = f"providers_{revision}"
    specialty_widget = f"{specialty_state}_widget"
    clinic_widget = f"{clinic_state}_widget"
    provider_widget = f"{provider_state}_widget"
    specialty_options = sorted(df.specialty.unique())
    clinic_options = sorted(df.clinic.unique())

    # The dialog owns the selection. Hidden state controls preserve the existing
    # calculation and automated-test contract without competing for dialog keys.
    if specialty_state not in st.session_state:
        st.session_state[specialty_state] = specialty_options
    if clinic_state not in st.session_state:
        st.session_state[clinic_state] = clinic_options
    st.session_state[specialty_widget] = list(st.session_state[specialty_state])
    st.session_state[clinic_widget] = list(st.session_state[clinic_state])
    # These state widgets retain the established filter contract for calculations
    # and automated coverage. The visible selectors are the persistent dialogs below.
    with st.container(key="team_filter_state"):
        st.multiselect("Select specialties", specialty_options, key=specialty_widget,
                       on_change=sync_filter_widget, args=(specialty_widget, specialty_state))
        st.multiselect("Select clinics", clinic_options, key=clinic_widget,
                       on_change=sync_filter_widget, args=(clinic_widget, clinic_state))
        specialties = st.session_state[specialty_state]
        clinics = st.session_state[clinic_state]
        eligible = df[df.specialty.isin(specialties) & df.clinic.isin(clinics)]
        available_names = sorted(eligible.provider.unique())
        if provider_state not in st.session_state:
            st.session_state[provider_state] = available_names
        else:
            st.session_state[provider_state] = [name for name in st.session_state[provider_state] if name in available_names]
        st.session_state[provider_widget] = list(st.session_state[provider_state])
        st.multiselect("Select providers", available_names, key=provider_widget,
                       on_change=sync_filter_widget, args=(provider_widget, provider_state))
        names = st.session_state[provider_state]
    with st.container(key="refine_specialties"):
        st.markdown("##### Choose specialties")
        st.caption(f"{len(specialties)} selected")
        if st.button("Open specialty selector", key="open_specialty_selector", width="stretch"):
            render_team_selector("Select specialties", "Specialties", sorted(df.specialty.unique()), specialty_state, "Choose one or more specialties")
    with st.container(key="refine_clinics"):
        st.markdown("##### Choose clinics")
        st.caption(f"{len(clinics)} selected")
        if st.button("Open clinic selector", key="open_clinic_selector", width="stretch"):
            render_team_selector("Select clinics", "Clinics", sorted(df.clinic.unique()), clinic_state, "Choose one or more clinics")
    with st.container(key="refine_providers"):
        st.markdown("##### Choose providers")
        st.caption(f"{len(available_names)} providers are available after the specialty and clinic selections.")
        if st.button("Open provider selector", key="open_provider_selector", width="stretch", help="Provider choices reflect the selected specialties and clinics."):
            render_team_selector("Select providers", "Providers", available_names, provider_state, "Choose one or more providers")
    active_refinement = refinement_view.lower()
    st.markdown(f'''<style>
      .st-key-refine_specialties {{display: {"block" if active_refinement == "specialties" else "none"};}}
      .st-key-refine_clinics {{display: {"block" if active_refinement == "clinics" else "none"};}}
      .st-key-refine_providers {{display: {"block" if active_refinement == "providers" else "none"};}}
    </style>''', unsafe_allow_html=True)
    target = st.slider("Target utilization (%)", 50, 100, 85, help="A scenario assumption, not a clinical or industry standard.") / 100
    st.caption(f"Selected: {len(names)} providers · {len(specialties)} specialties · {len(clinics)} clinics")
    st.caption(f"Available period: {df.date.min():%b %d, %Y} – {df.date.max():%b %d, %Y}. Coverage reflects observed rows, not a staffing roster.")

date_context = (f"{dates[0]:%b %d, %Y} – {dates[1]:%b %d, %Y}"
                if isinstance(dates, (tuple, list)) and len(dates) == 2
                else "Select a start and end date")
context_summary.markdown(
    f'''<div class="context-strip">
      <div><span class="context-label">Viewing as</span><strong>{html.escape(active_profile.label)}</strong></div>
      <div><span class="context-label">Reporting period</span><strong>{date_context}</strong></div>
      <div><span class="context-label">Selected team</span><strong>{len(names)} providers · {len(specialties)} specialties · {len(clinics)} clinics</strong></div>
    </div>''', unsafe_allow_html=True)

with st.container():
    if not isinstance(dates, (tuple, list)) or len(dates) != 2:
        st.info("Select both a start and end date.")
        st.stop()
    query_data = df[df.specialty.isin(specialties) & df.clinic.isin(clinics) & df.provider.isin(names)]
    data_bounds = (df.date.min().date(), df.date.max().date())
    filtered = df[df.date.between(pd.Timestamp(dates[0]), pd.Timestamp(dates[1])) &
                  df.specialty.isin(specialties) & df.clinic.isin(clinics) & df.provider.isin(names)]
    if filtered.empty:
        st.info("No data matches these filters. Select at least one provider, clinic, and specialty.")
        st.stop()
    audit_filters = {
        "access_role": active_profile.role,
        "access_scope": active_profile.scope_label,
        "reporting_period": period,
        "dashboard_date_range": [str(dates[0]), str(dates[1])],
        "specialties": specialties,
        "clinics": clinics,
        "providers": names,
        "target_utilization": target,
    }
    p = benchmark(filtered, target)
    kpis = calculate_kpis(filtered)
    visits, capacity, revenue = kpis["visits"], kpis["capacity"], kpis["revenue"]
    opportunity_total = p.opportunity.sum()
    st.markdown('<div class="dashboard-section-kicker">Executive performance</div>', unsafe_allow_html=True)
    with st.container(key="headline_kpis"):
        columns = st.columns(4)
        for col, label, value in zip(columns, ["Completed visits", "Utilization", "Revenue", "Modeled opportunity"],
                                     [f"{visits:,}", f"{kpis['utilization']:.1%}",
                                      (f"${revenue / 1_000_000:,.2f}M" if revenue >= 1_000_000 else f"${revenue:,.0f}"),
                                      f"${opportunity_total / 1_000_000:,.2f}M" if opportunity_total >= 1_000_000 else f"${opportunity_total:,.0f}"]):
            col.metric(label, value, help=f"Exact reported revenue: ${revenue:,.2f}" if label == "Revenue" else None)
    with st.container(key="overview_operational_kpis"):
        columns = st.columns(3)
        columns[0].metric("Capacity", f"{capacity:,} slots")
        columns[1].metric("Unused capacity", f"{kpis['unused_capacity']:,} slots")
        columns[2].metric("Visits / staffed hour", f"{kpis['productivity']:.2f}")
    st.caption(f"{p.provider_id.nunique()} providers · {dates[0]:%b %d, %Y} – {dates[1]:%b %d, %Y} · Opportunity modeled at {target:.0%} utilization")

    overview, copilot, benchmarks, opportunities, executive, scenarios, reporting = st.tabs([
        "Overview", "Ask Copilot", "Provider Comparison", "Opportunities",
        "Executive Center", "Scenarios", "Data & Reporting",
    ])
    with overview:
        monthly = monthly_performance(filtered)
        priority_provider = p.sort_values("opportunity", ascending=False).iloc[0]
        unbooked = int((filtered.capacity - filtered.booked).sum())
        below_target = int((p.utilization < target).sum())
        no_shows = int(filtered.no_shows.sum())
        with st.container(key="operations_copilot"):
            st.markdown(
                '''<div class="operations-copilot-heading">
                  <div><span class="copilot-mark">✦</span><span class="copilot-eyebrow">Operations Copilot</span>
                  <h2>Three data-derived priorities</h2></div>
                  <p>Calculated from the selected team and reporting period.</p>
                </div>''', unsafe_allow_html=True)
            priority_columns = st.columns(3, gap="large")
            with priority_columns[0]:
                st.markdown("##### Utilization opportunity")
                st.markdown(f"**{below_target} of {len(p)} providers** are below the selected {target:.0%} utilization target.")
                if st.button("Investigate utilization", key="investigate_utilization"):
                    st.session_state.pending_follow_up = "Which providers are furthest below their utilization benchmark?"
                    st.toast("A grounded utilization investigation is ready in Ask Copilot.")
                    st.rerun()
            with priority_columns[1]:
                st.markdown("##### Largest modeled opportunity")
                st.markdown(f"**{html.escape(priority_provider.provider)}** has ${priority_provider.opportunity:,.0f} in modeled revenue opportunity.")
                if st.button("Investigate opportunity", key="investigate_opportunity"):
                    st.session_state.pending_follow_up = "Where is our largest revenue opportunity?"
                    st.toast("A grounded opportunity investigation is ready in Ask Copilot.")
                    st.rerun()
            with priority_columns[2]:
                st.markdown("##### Capacity to recover")
                st.markdown(f"**{unbooked:,} unbooked slots** and **{no_shows:,} no-shows** contribute to unused capacity.")
                if st.button("Investigate capacity", key="investigate_capacity"):
                    st.session_state.pending_follow_up = "Which providers have the most unused capacity?"
                    st.toast("A grounded capacity investigation is ready in Ask Copilot.")
                    st.rerun()
        left, right = st.columns(2)
        with left:
            st.markdown('<div class="overview-section-title">Performance trend</div><div class="overview-section-note">Completed visits and staffed appointment capacity by month</div>', unsafe_allow_html=True)
            st.plotly_chart(visits_chart(monthly), width="stretch")
        with right:
            st.markdown('<div class="overview-section-title">Opportunity concentration</div><div class="overview-section-note">Providers with the largest modeled revenue opportunity</div>', unsafe_allow_html=True)
            st.plotly_chart(opportunity_concentration_chart(p), width="stretch")
        st.markdown('<div class="overview-section-title">Top opportunities</div><div class="overview-section-note">Provider-level operational review items; overlapping signals are not additive.</div>', unsafe_allow_html=True)
        overview_opportunities = detect_opportunities(p, target).head(5)
        if overview_opportunities.empty:
            st.info("No configured opportunity rules triggered for this selection.")
        else:
            st.dataframe(overview_opportunities[["provider", "utilization", "utilization_gap_pp", "opportunity", "signals"]],
                         hide_index=True, width="stretch", column_config={
                             "utilization": st.column_config.NumberColumn("Utilization", format="percent"),
                             "utilization_gap_pp": st.column_config.NumberColumn("Peer gap (pp)", format="%.1f"),
                             "opportunity": st.column_config.NumberColumn("Modeled opportunity", format="dollar"),
                             "signals": st.column_config.TextColumn("Action")})
        from src.deep_analysis import annual_summary
        with st.expander("Annual performance scorecard", expanded=True):
            annual = annual_summary(filtered)
            st.caption("Weighted annual metrics. Complete refers to observed first/last weekday coverage; partial years should not be compared as full-year volumes.")
            st.dataframe(annual[["visits", "capacity", "utilization", "productivity", "revenue", "complete"]],
                         column_config={"utilization": st.column_config.NumberColumn(format="percent"),
                                        "revenue": st.column_config.NumberColumn(format="dollar")}, width="stretch")
        with st.container(border=True):
            st.subheader("Utilization over time")
            st.caption("Weighted completed-visit utilization compared with your scenario target.")
            st.plotly_chart(utilization_trend_chart(monthly, target), width="stretch")
        st.caption("Capacity represents slots in staffed sessions. Unused capacity includes unbooked slots and no-shows; leave days have no capacity.")
    with benchmarks:
        with st.container(key="provider_comparison_shell"):
            st.subheader("Provider comparison")
            st.caption("Compare selected providers on operational dimensions. Click a provider row to open its aggregate provider-day drill-down; no patient-level records are available.")
            comparison_rows = p[["provider", "specialty", "clinic", "visits", "capacity", "utilization", "visits_per_hour", "revenue", "unused_capacity", "opportunity"]].copy()
            comparison_rows = comparison_rows.sort_values(["visits_per_hour", "provider"], ascending=[False, True]).reset_index(drop=True)

            def comparison_table(rows, columns, config, key):
                """Select a provider without exposing anything below provider-day aggregates."""
                event = st.dataframe(rows[columns], hide_index=True, width="stretch", column_config=config,
                                    on_select="rerun", selection_mode="single-row", key=key)
                selected_rows = event.selection.rows
                if selected_rows:
                    st.session_state.comparison_provider = rows.iloc[selected_rows[0]].provider

            productivity_tab, utilization_tab, revenue_tab, scorecard_tab = st.tabs([
                "Productivity", "Utilization", "Revenue & opportunity", "Scorecards",
            ])
            with productivity_tab:
                st.markdown("#### Visits per staffed hour")
                st.caption("Completed visits ÷ staffed hours. This is an operational throughput measure, not a quality score.")
                st.plotly_chart(productivity_chart(p), width="stretch")
                comparison_table(comparison_rows, ["provider", "specialty", "clinic", "visits_per_hour", "visits"], {
                    "visits_per_hour": st.column_config.NumberColumn("Visits / staffed hour", format="%.2f"),
                    "visits": st.column_config.NumberColumn("Completed visits", format="%,d"),
                }, "comparison_productivity_rows")
            with utilization_tab:
                st.markdown("#### Capacity utilization")
                st.caption("Completed visits as a share of staffed appointment slots. The dashed line is the selected scenario target.")
                st.plotly_chart(utilization_chart(p, target), width="stretch")
                comparison_table(comparison_rows.sort_values("utilization", ascending=False), ["provider", "specialty", "clinic", "utilization", "capacity", "unused_capacity"], {
                    "utilization": st.column_config.NumberColumn("Utilization", format="percent"),
                    "capacity": st.column_config.NumberColumn("Staffed slots", format="%,d"),
                    "unused_capacity": st.column_config.NumberColumn("Unused capacity", format="%,d"),
                }, "comparison_utilization_rows")
            with revenue_tab:
                st.markdown("#### Revenue and modeled opportunity")
                st.caption("Revenue is reported synthetic realized revenue. Opportunity is a scenario estimate based on the selected utilization target.")
                st.plotly_chart(provider_revenue_chart(p), width="stretch")
                comparison_table(comparison_rows.sort_values("revenue", ascending=False), ["provider", "specialty", "clinic", "revenue", "opportunity"], {
                    "revenue": st.column_config.NumberColumn("Revenue", format="dollar"),
                    "opportunity": st.column_config.NumberColumn("Modeled opportunity", format="dollar"),
                }, "comparison_revenue_rows")
            with scorecard_tab:
                st.markdown("#### Peer context")
                st.caption("Specialty peer utilization is weighted by capacity. Contextual medians are descriptive context, not performance rankings; groups include the provider.")
                scorecards = p[["provider", "specialty", "clinic", "utilization", "specialty_median_utilization", "practice_median_utilization", "organization_median_utilization", "specialty_median_gap_pp", "practice_median_gap_pp", "organization_median_gap_pp", "visits_per_hour", "productivity_index", "peer_count"]].sort_values("provider").reset_index(drop=True)
                comparison_table(scorecards, scorecards.columns.tolist(), {
                    "utilization": st.column_config.NumberColumn("Utilization", format="percent"),
                    "specialty_median_utilization": st.column_config.NumberColumn("Specialty median", format="percent"),
                    "practice_median_utilization": st.column_config.NumberColumn("Practice median", format="percent"),
                    "organization_median_utilization": st.column_config.NumberColumn("Organization median", format="percent"),
                    "specialty_median_gap_pp": st.column_config.NumberColumn("vs specialty median (pp)", format="%.1f"),
                    "practice_median_gap_pp": st.column_config.NumberColumn("vs practice median (pp)", format="%.1f"),
                    "organization_median_gap_pp": st.column_config.NumberColumn("vs organization median (pp)", format="%.1f"),
                    "visits_per_hour": st.column_config.NumberColumn("Visits / staffed hour", format="%.2f"),
                    "productivity_index": st.column_config.NumberColumn("Productivity index", format="%.2f"),
                    "peer_count": st.column_config.NumberColumn("Peer count", format="%,d"),
                }, "comparison_scorecard_rows")

            available_providers = sorted(filtered.provider.unique())
            selected_provider = st.session_state.get("comparison_provider", available_providers[0])
            if selected_provider not in available_providers:
                selected_provider = available_providers[0]
            with st.container(key="comparison_drilldown"):
                st.markdown("#### Provider drill-down")
                st.caption("Click a row above, or choose a provider below. Drill-down ends at the provider-day aggregate because this application does not store appointment or patient-level data.")
                provider = st.selectbox("Provider", available_providers,
                                        index=available_providers.index(selected_provider),
                                        key="comparison_provider_picker")
                provider_rows = filtered[filtered.provider == provider].sort_values("date", ascending=False).copy()
                provider_totals = provider_rows[["visits", "capacity", "staffed_hours", "revenue", "no_shows"]].sum()
                detail_metrics = st.columns(4)
                drilldown_stats = [
                    ("Completed visits", f"{int(provider_totals.visits):,}"),
                    ("Utilization", f"{provider_totals.visits / provider_totals.capacity:.1%}" if provider_totals.capacity else "Not available"),
                    ("Visits / staffed hour", f"{provider_totals.visits / provider_totals.staffed_hours:.2f}" if provider_totals.staffed_hours else "Not available"),
                    ("Revenue", f"${provider_totals.revenue:,.0f}"),
                ]
                for column, (label, value) in zip(detail_metrics, drilldown_stats):
                    column.markdown(f'<div class="drilldown-stat"><span>{label}</span><strong>{value}</strong></div>', unsafe_allow_html=True)
                st.caption("Click a provider-day row to see the exact daily numerator and denominator.")
                daily_event = st.dataframe(provider_rows[["date", "visits", "booked", "capacity", "no_shows", "staffed_hours", "revenue"]],
                                           hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                                           key="comparison_provider_days", column_config={
                                               "date": st.column_config.DateColumn("Date", format="MMM D, YYYY"),
                                               "visits": st.column_config.NumberColumn("Completed visits", format="%,d"),
                                               "booked": st.column_config.NumberColumn("Booked", format="%,d"),
                                               "capacity": st.column_config.NumberColumn("Staffed slots", format="%,d"),
                                               "no_shows": st.column_config.NumberColumn("No-shows", format="%,d"),
                                               "staffed_hours": st.column_config.NumberColumn("Staffed hours", format="%.1f"),
                                               "revenue": st.column_config.NumberColumn("Revenue", format="dollar"),
                                           })
                if daily_event.selection.rows:
                    day = provider_rows.iloc[daily_event.selection.rows[0]]
                    st.markdown(f"**{day.date:%b %d, %Y} · daily denominator**")
                    utilization = day.visits / day.capacity if day.capacity else None
                    productivity = day.visits / day.staffed_hours if day.staffed_hours else None
                    st.caption(
                        f"Utilization: {int(day.visits):,} completed visits ÷ {int(day.capacity):,} staffed slots"
                        + (f" = {utilization:.1%}." if utilization is not None else ".")
                        + f" Productivity: {int(day.visits):,} ÷ {day.staffed_hours:.1f} staffed hours"
                        + (f" = {productivity:.2f} visits per staffed hour." if productivity is not None else ".")
                    )
    with opportunities:
        st.subheader("Executive insights")
        for insight in executive_insights(filtered, p, target):
            with st.container(border=True):
                st.write(insight)
        st.dataframe(p[["provider", "specialty", "unused_capacity", "recoverable_visits", "opportunity"]].round(2), hide_index=True, width="stretch")
        st.subheader("Detected opportunities")
        st.caption("Illustrative rules: utilization below target; unbooked slots ≥15%; no-shows ≥10%; or utilization ≥5 percentage points below selected specialty peers. Flags overlap and are not additive.")
        detected = detect_opportunities(p, target)
        if detected.empty:
            st.success("No opportunity rules triggered for this selection.")
        else:
            st.dataframe(detected[["provider", "specialty", "unbooked_slots", "no_shows", "signals", "opportunity"]].round(2),
                         hide_index=True, width="stretch")
        st.download_button("Download opportunity analysis", detect_opportunities(p, target).to_csv(index=False), "synthetic_opportunities.csv", "text/csv")
    with scenarios:
        render_scenarios(filtered, target)
    with reporting:
        st.subheader("Data source")
        st.caption("Manage the active synthetic demo or upload verified non-PHI provider-day aggregates without interrupting the operational overview.")
        render_data_controls()
        st.divider()
        render_reporting(filtered, target, dates)
    with executive:
        with st.container(key="executive_center_shell"):
            st.subheader("Executive Center")
            st.caption("A focused leadership workspace. Each view uses the selected team and reporting period, with calculations performed locally before any optional AI explanation.")
            brief_tab, outlook_tab, priorities_tab, detail_tab = st.tabs([
                "Executive brief", "Forecast & outlook", "Operational priorities", "Provider & specialty detail",
            ])
            with brief_tab:
                render_executive_brief(filtered, target, query_data, data_bounds, dates, audit_filters)
            with outlook_tab:
                st.markdown("#### Forecast & outlook")
                st.caption("Observed data, forecast, and intervals are separated clearly. Use this experimental rolling-mean baseline for planning review only.")
                render_forecasting(filtered)
            with priorities_tab:
                st.markdown("#### Operational priorities")
                st.caption("Deterministic recommendations, top opportunities, and anomaly investigation for the selected scope.")
                render_executive_opportunities(filtered, target)
            with detail_tab:
                st.markdown("#### Provider & specialty detail")
                st.caption("Review selected-provider dimensions, recent movement, and weighted specialty context without assigning a composite score.")
                render_provider_and_specialty_detail(filtered, target)

    with copilot:
        st.subheader("Conversational operations copilot")
        st.caption("Local, rule-based analytics conversation. Answers use selected dashboard data; no chat text is sent to a model or external service. Please do not enter PHI.")
        chat_scope = hashlib.sha256((filtered.to_csv(index=False) + str(target)).encode()).hexdigest()
        if st.session_state.get("chat_scope") != chat_scope:
            had_chat = bool(st.session_state.get("chat_history"))
            st.session_state.chat_history = []
            st.session_state.voice_history = []
            st.session_state.pop("voice_response", None)
            st.session_state.pop("pending_follow_up", None)
            st.session_state.chat_scope = chat_scope
            if had_chat:
                st.info("Selection changed. Chat history was cleared so replies use the current data.")
        text_area, voice_area = st.tabs(["GenAI / text chat", "Voice conversation"])
        with voice_area:
            st.subheader("Voice conversation")
            st.caption("A separate conversation with its own memory. Start voice, speak, then pause for an answer.")
            render_voice(filtered, target, chat_scope, raw_df=query_data, data_bounds=data_bounds,
                         audit_filters=audit_filters)
            with st.expander("Voice chat history"):
                voice_history = st.session_state.get("voice_history", [])
                if not voice_history:
                    st.caption("No voice messages yet.")
                for start in reversed(range(0, len(voice_history), 2)):
                    for message in voice_history[start:start + 2]:
                        with st.chat_message(message["role"]):
                            st.markdown(message["text"])
        with text_area:
            heading, clear = st.columns([5, 1])
            with heading:
                st.subheader("Ask the operations copilot")
                st.caption("Ask a question about the selected team and period. Answers are calculated from dashboard data; text and voice conversations stay separate.")
            with clear:
                st.write("")
                if st.button("Clear chat", key="clear_text_chat", help="Clear only the text conversation. Voice chat is kept separately.", width="stretch"):
                    st.session_state.chat_history = []
                    st.session_state.pop("pending_follow_up", None)
            question = st.chat_input("Ask a question about capacity, a provider, or a year such as 2023")
            pending_follow_up = st.session_state.pop("pending_follow_up", None)
            if question or pending_follow_up:
                prompt = question or pending_follow_up
                response = respond(prompt, filtered, target, st.session_state.chat_history, raw_df=query_data, data_bounds=data_bounds)
                record_query(st.session_state, prompt, response, query_data, audit_filters, "Text copilot")
                st.session_state.chat_history.extend([
                    {"role": "user", "text": prompt}, {"role": "assistant", **response}])
                st.session_state.chat_history = st.session_state.chat_history[-40:]
            # Reverse exchanges only; retain chronological history for follow-ups.
            history = st.session_state.chat_history
            display_messages = [message for start in reversed(range(0, len(history), 2))
                                for message in history[start:start + 2]]
            if display_messages:
                st.caption("Newest conversation first")
            for display_index, message in enumerate(display_messages):
                with st.chat_message(message["role"]):
                    st.markdown(message["text"])
                    if message["role"] == "assistant":
                        audit = next((item for item in st.session_state.get("copilot_audit", []) if item["audit_id"] == message.get("audit_id")), None)
                        if audit:
                            render_calculation_path(audit)
                        if message.get("query_plan"):
                            with st.expander("How this answer was calculated"):
                                st.json(message["query_plan"])
                        if message.get("calculated_result") and display_index == 1:
                            st.caption("Optional AI explanation sends only verified synthetic calculated results, never chat history. Numbers remain Python-calculated.")
                            if st.button("Explain this result with AI", disabled=("uploaded_data" in st.session_state or not configuration_ready()), key="explain_latest_plan"):
                                try:
                                    with st.spinner("Explaining calculated results…"):
                                        message["ai_explanation"] = explain_plan(message["query_plan"], filtered, query_data, data_bounds, target)
                                except CopilotError as exc:
                                    st.error(str(exc))
                        if message.get("ai_explanation"):
                            st.caption(message["ai_explanation"]["mode"])
                            st.markdown(message["ai_explanation"]["text"])
                        if message.get("analytical_state"):
                            with st.expander("Analytical memory"):
                                st.json({k:v for k,v in message["analytical_state"].items() if k != "scope"})
                        if message.get("chart") is not None:
                            st.plotly_chart(message["chart"], width="stretch", key=f"chat_chart_{display_index}")
                        st.caption(message.get("grounding", "Grounding: no metrics calculated") + " · " + message["status"])
                        if display_index == 1:
                            follow_columns = st.columns(3)
                            for index, item in enumerate(message.get("follow_ups", [])):
                                if follow_columns[index].button(item["label"], key="follow_" + item["label"]):
                                    st.session_state.pending_follow_up = item["question"]
                                    st.rerun()
            with st.container(key="text_chat_help"):
                st.divider()
                st.markdown("#### Help center")
                st.caption("Use these quick references when you need ideas, supported metrics, definitions, or the local audit history.")
                suggestions_tab, metrics_tab, definitions_tab, audit_tab = st.tabs([
                    "Suggested questions", "Explore metrics & examples",
                    "Metric definitions and assumptions", "Audit trail",
                ])
                with suggestions_tab:
                    topic = st.radio("Analysis topic", ["Quick answers", "Comparisons", "Scenarios and charts", "Trends", "Operational opportunities"], horizontal=True)
                    choices = (SCENARIO_QUESTIONS if topic == "Scenarios and charts" else COMPARISON_QUESTIONS if topic == "Comparisons" else SUGGESTIONS[:4] if topic == "Quick answers"
                               else SUGGESTIONS[4:7] if topic == "Trends" else SUGGESTIONS[7:])
                    question_columns = st.columns(2)
                    for index, prompt in enumerate(choices):
                        if question_columns[index % 2].button(prompt, key="suggest_" + prompt, width="stretch"):
                            st.session_state.pending_follow_up = prompt
                            st.rerun()
                with metrics_tab:
                    st.caption("Supported operational metrics and sample phrasing.")
                    st.dataframe(pd.DataFrame(catalog_records()), hide_index=True, width="stretch")
                    for example in SEMANTIC_QUESTIONS:
                        st.code(example, language=None)
                with definitions_tab:
                    st.markdown("""
                    - **Utilization:** completed visits ÷ available appointment slots; rollups use weighted totals.
                    - **Booking rate:** booked ÷ capacity. **No-show rate:** (booked − visits) ÷ booked; zero when no bookings.
                    - **Specialty benchmark:** specialty total visits ÷ specialty total capacity; productivity uses specialty staffed hours instead. Peers include self within the selection.
                    - **Utilization context medians:** median aggregated provider utilization in the selected specialty, practice/clinic, or organization; descriptive context, not a rank.
                    - **Utilization gap (pp):** 100 × (provider utilization − specialty utilization). **Productivity index:** provider visits/hour ÷ specialty visits/hour.
                    - **Productivity:** completed visits ÷ staffed hours. FTE is reflected in scheduled hours and slots.
                    - **Revenue:** synthetic realized revenue; not charges, profit, or a reimbursement forecast.
                    - **Unused capacity:** capacity − completed visits.
                    - **Estimated opportunity:** max(0, target × capacity − visits) × observed revenue per visit, summed by provider. Providers with no visits have no inferred rate.
                    - Scenario opportunity assumes demand, staffing, payer mix, and visit revenue support added visits. It excludes incremental costs and is not guaranteed revenue.
                    - This dashboard measures operational activity, not clinical quality or individual care recommendations.
                    """)
                with audit_tab:
                    render_audit_trail(st.session_state)
