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
from src.workspace_ui import render_workspace
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
content, controls = st.columns([3.6, 1.45], gap="large")
with controls, st.container(border=True, key="dashboard_filters"):
    st.subheader("Demo access")
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
    st.divider()
    st.subheader("Filters")
    st.caption("Choose a period, select your team, then adjust the target.")
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
    with st.expander("Specialties", expanded=False):
        specialties = st.multiselect("Select specialties", sorted(df.specialty.unique()), default=sorted(df.specialty.unique()), key=f"specialties_{revision}")
    with st.expander("Clinics", expanded=False):
        clinics = st.multiselect("Select clinics", sorted(df.clinic.unique()), default=sorted(df.clinic.unique()), key=f"clinics_{revision}")
    eligible = df[df.specialty.isin(specialties) & df.clinic.isin(clinics)]
    available_names = sorted(eligible.provider.unique())
    with st.expander("Providers", expanded=False):
        names = st.multiselect("Select providers", available_names, default=available_names,
                               key=f"providers_{revision}", help="Provider choices reflect the selected specialties and clinics.")
    st.caption(f"Selected: {len(names)} providers · {len(specialties)} specialties · {len(clinics)} clinics")
    target = st.slider("Target utilization (%)", 50, 100, 85, help="A scenario assumption, not a clinical or industry standard.") / 100
    st.caption(f"Available period: {df.date.min():%b %d, %Y} – {df.date.max():%b %d, %Y}. Coverage reflects observed rows, not a staffing roster.")

with controls:
    render_data_controls()

with content:
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

    overview, copilot, benchmarks, opportunities, workspace, scenarios, executive, reporting = st.tabs(["Overview", "Ask copilot", "Compare", "Opportunities", "Executive workspace", "Scenarios", "Executive brief", "Data & Reporting"])
    with overview:
        monthly = monthly_performance(filtered)
        priority_provider = p.sort_values("opportunity", ascending=False).iloc[0]
        unbooked = int((filtered.capacity - filtered.booked).sum())
        st.markdown(
            f'''<div class="priority-panel">
              <div class="priority-title">✦ Copilot identified 3 operational priorities</div>
              <ul>
                <li>{int((p.utilization < target).sum())} of {len(p)} providers are below the selected {target:.0%} utilization target.</li>
                <li>{html.escape(priority_provider.provider)} has the largest modeled opportunity: ${priority_provider.opportunity:,.0f}.</li>
                <li>Unused capacity includes {unbooked:,} unbooked slots and {int(filtered.no_shows.sum()):,} no-shows.</li>
              </ul>
              <div class="priority-note">Calculated from the selected team and period. Use Ask Copilot for a grounded follow-up.</div>
            </div>''', unsafe_allow_html=True)
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
        st.subheader("Compare provider performance")
        st.caption("Specialty colors stay consistent across all charts. Use the filters on the right to compare similar providers.")
        productivity, utilization = st.columns(2)
        with productivity:
            with st.container(border=True):
                st.subheader("Productivity")
                st.caption("Completed visits per staffed hour")
                st.plotly_chart(productivity_chart(p), width="stretch")
        with utilization:
            with st.container(border=True):
                st.subheader("Capacity utilization")
                st.caption("Completed visits as a share of staffed slots")
                st.plotly_chart(utilization_chart(p, target), width="stretch")
        with st.container(border=True):
            st.subheader("Revenue by provider")
            st.caption("Reported revenue across the selected period")
            st.plotly_chart(provider_revenue_chart(p), width="stretch")
        st.subheader("Provider scorecard")
        st.caption("Specialty peer utilization is weighted by capacity. Contextual medians describe the typical selected provider in a specialty, practice, or organization; they are not rankings. All groups include the provider.")
        st.dataframe(p[["provider", "specialty", "clinic", "visits", "capacity", "utilization", "specialty_median_utilization", "practice_median_utilization", "organization_median_utilization", "specialty_median_gap_pp", "practice_median_gap_pp", "organization_median_gap_pp", "peer_utilization", "visits_per_hour", "peer_productivity", "productivity_index", "utilization_gap_pp", "peer_count", "revenue"]],
                     hide_index=True, width="stretch", column_config={
                         "utilization": st.column_config.NumberColumn("Utilization", format="percent"),
                         "specialty_median_utilization": st.column_config.NumberColumn("Specialty median", format="percent"),
                         "practice_median_utilization": st.column_config.NumberColumn("Practice median", format="percent"),
                         "organization_median_utilization": st.column_config.NumberColumn("Organization median", format="percent"),
                         "specialty_median_gap_pp": st.column_config.NumberColumn("vs specialty median (pp)", format="%.1f"),
                         "practice_median_gap_pp": st.column_config.NumberColumn("vs practice median (pp)", format="%.1f"),
                         "organization_median_gap_pp": st.column_config.NumberColumn("vs organization median (pp)", format="%.1f"),
                         "peer_utilization": st.column_config.NumberColumn("Specialty peer utilization", format="percent"),
                         "visits_per_hour": st.column_config.NumberColumn("Visits / staffed hour", format="%.2f"),
                         "revenue": st.column_config.NumberColumn("Revenue", format="dollar")})
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
    with workspace:
        render_forecasting(filtered)
        render_workspace(filtered, target)
    with scenarios:
        render_scenarios(filtered, target)
    with reporting:
        render_reporting(filtered, target, dates)
    with executive:
        if 'uploaded_data' in st.session_state:
            st.info('Cloud executive briefs are disabled for uploaded data. Use Generate Executive Summary in the Executive workspace for a local calculated brief.')
        else:
            st.subheader("AI Executive Brief")
            st.caption("Calculated findings plus AI-prioritized management actions. Rankings use utilization, retain ties, and do not measure clinical quality.")
            st.info("Only verified synthetic aggregates are sent to OpenAI. No raw records, free-text prompts, or patient data are sent. Recommendations require management review.")
            try:
                brief_context = build_context(filtered, target)
                current_key = context_key(brief_context)
                with st.expander("Review calculated metrics sent to the model"):
                    st.json(brief_context)
                if not configuration_ready():
                    st.info("Local mode: Generate AI Executive Brief will produce a calculated brief without a model call. To enable AI-prioritized actions, configure OPENAI_API_KEY and OPENAI_MODEL in the server environment and restart Streamlit. Never enter credentials in chat.")
                preview_col, ai_col = st.columns(2)
                preview = preview_col.button("Preview calculated brief")
                live = ai_col.button("Generate AI Executive Brief", type="primary")
                if preview or live:
                    st.session_state.pop("executive_brief", None)
                    with st.spinner("Preparing executive brief…"):
                        st.session_state.executive_brief = generate_brief(filtered, target, use_ai=live and configuration_ready())
                    generated = st.session_state.executive_brief
                    audit_response = {
                        "text": "\n\n".join(generated["sections"].values()),
                        "status": "answered",
                        "grounding_details": [{
                            "label": "Executive brief inputs", "start": dates[0], "end": dates[1],
                            "providers": int(filtered.provider_id.nunique()), "records": len(filtered),
                        }],
                    }
                    record_query(st.session_state, "Generate AI Executive Brief", audit_response, query_data,
                                 audit_filters, "Executive brief generation")
                brief = st.session_state.get("executive_brief")
                if brief and brief["context_key"] == current_key:
                    st.caption(brief["mode"])
                    for title, body in brief["sections"].items():
                        with st.container(border=True):
                            st.subheader(title)
                            st.text(body)
                    st.warning(brief["guardrails"])
                    st.caption(f"Brief period: {dates[0]:%b %d, %Y} – {dates[1]:%b %d, %Y} · {len(filtered):,} provider-day records")
                    discussion_scope = hashlib.sha256((query_data.to_csv(index=False) + filtered.to_csv(index=False) + str(target)).encode()).hexdigest()
                    if st.session_state.get("brief_discussion_scope") != discussion_scope:
                        st.session_state.brief_discussion = []
                        st.session_state.brief_discussion_scope = discussion_scope
                    with st.container(border=True):
                        st.subheader("Discuss this brief")
                        st.caption("Grounded local follow-ups with separate conversation memory. Questions are not sent to an AI service. Ask about a provider, compare periods, or investigate an opportunity. Please do not enter PHI.")
                        if st.button("Clear brief conversation"):
                            st.session_state.brief_discussion = []
                        with st.form("brief_follow_up", clear_on_submit=True):
                            brief_question = st.text_input("Question about this brief", placeholder="Where is our largest revenue opportunity?", max_chars=1000)
                            ask_brief = st.form_submit_button("Ask about brief", type="primary")
                        if ask_brief and brief_question.strip():
                            reply = respond(brief_question, filtered, target, st.session_state.brief_discussion, raw_df=query_data, data_bounds=data_bounds)
                            record_query(st.session_state, brief_question, reply, query_data, audit_filters, "Executive brief discussion")
                            st.session_state.brief_discussion.extend([{"role": "user", "text": brief_question}, {"role": "assistant", **reply}])
                            st.session_state.brief_discussion = st.session_state.brief_discussion[-40:]
                        history = st.session_state.brief_discussion
                        for start in reversed(range(0, len(history), 2)):
                            for message in history[start:start + 2]:
                                with st.chat_message(message["role"]):
                                    st.markdown(message["text"])
                                    if message["role"] == "assistant":
                                        audit = next((item for item in st.session_state.get("copilot_audit", []) if item["audit_id"] == message.get("audit_id")), None)
                                        if audit:
                                            render_calculation_path(audit)
                                        st.caption(message.get("grounding", "No metrics calculated") + " · " + message["status"])
                                        if message.get("chart") is not None:
                                            st.plotly_chart(message["chart"], width="stretch", key=f"brief_chart_{start}")

                elif brief:
                    st.info("Filters or target changed. Generate a new brief for this selection.")
            except CopilotError as exc:
                st.error(str(exc))

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
            st.subheader("Ask a question")
            st.caption("Type a question or choose an example. Text and voice histories are kept separate. Optional AI explanations are available on supported answers.")
            if st.button("Clear chat", key="clear_text_chat", help="Clear only the text conversation. Voice chat is kept separately."):
                st.session_state.chat_history = []
                st.session_state.pop("pending_follow_up", None)
            with st.expander("Explore supported metrics and examples"):
                st.dataframe(pd.DataFrame(catalog_records()), hide_index=True, width="stretch")
                st.caption("A deterministic parser creates an allowlisted metric/dimension/date plan. Specialized comparisons, trends and scenarios retain their existing routes.")
                for example in SEMANTIC_QUESTIONS:
                    st.code(example, language=None)
            suggested = None
            with st.expander("Suggested questions — start here", expanded=False):
                topic = st.radio("Analysis topic", ["Quick answers", "Comparisons", "Scenarios and charts", "Trends", "Operational opportunities"], horizontal=True)
                choices = (SCENARIO_QUESTIONS if topic == "Scenarios and charts" else COMPARISON_QUESTIONS if topic == "Comparisons" else SUGGESTIONS[:4] if topic == "Quick answers"
                           else SUGGESTIONS[4:7] if topic == "Trends" else SUGGESTIONS[7:])
                question_columns = st.columns(2)
                for index, prompt in enumerate(choices):
                    if question_columns[index % 2].button(prompt, key="suggest_" + prompt, width="stretch"):
                        suggested = prompt
            question = st.chat_input("Ask about capacity or a provider, or enter a year (e.g. 2023)")
            pending_follow_up = st.session_state.pop("pending_follow_up", None)
            if question or suggested or pending_follow_up:
                prompt = question or suggested or pending_follow_up
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
            render_audit_trail(st.session_state)
    with st.expander("Metric definitions and assumptions"):
        st.markdown("""
        - **Utilization:** completed visits ÷ available appointment slots; all rollups use weighted totals.
        - **Booking rate:** booked ÷ capacity. **No-show rate:** (booked − visits) ÷ booked; zero when no bookings.
        - **Specialty benchmark:** specialty total visits ÷ specialty total capacity; productivity uses specialty staffed hours instead. Peers include self within the selection; one-provider groups are self-comparisons.
        - **Utilization context medians:** median of aggregated provider utilization rates within the selected specialty, practice/clinic, or organization. Each reference group includes the provider and is descriptive context, not a performance rank.
        - **Utilization gap (pp):** 100 × (provider utilization − specialty utilization). **Productivity index:** provider visits/hour ÷ specialty visits/hour.
        - **Productivity:** completed visits ÷ staffed hours. FTE is reflected in scheduled hours and slots.
        - **Revenue:** synthetic realized revenue; not charges, profit, or a reimbursement forecast.
        - **Unused capacity:** capacity − completed visits.
        - **Estimated opportunity:** for each provider, max(0, target × capacity − visits) × observed revenue per visit, then summed. Providers with no visits have no inferred revenue rate.
        - The scenario assumes demand, staffing, payer mix, and visit revenue support additional visits. It excludes incremental costs and is not guaranteed revenue. Fractional visits represent an expected scenario.
        - This dashboard measures operational activity, not clinical quality or individual care recommendations.
        """)
