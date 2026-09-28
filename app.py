import pandas as pd
import streamlit as st
from src.data import DATA_PATH, load_data
from src.analytics import benchmark, answer, calculate_kpis, monthly_performance, detect_opportunities
from src.charts import (visits_chart, revenue_chart, utilization_chart,
                        productivity_chart, provider_revenue_chart, utilization_trend_chart)
from src.presentation import apply_style, header
from src.forecasting_ui import render_forecasting
from src.insights import executive_insights
from src.conversation import respond, SUGGESTIONS, COMPARISON_QUESTIONS
from src.voice import render_voice
from src.workspace_ui import render_workspace
from src.scenarios_ui import render_scenarios
from src.scenarios import SCENARIO_QUESTIONS
from src.data_reporting_ui import render_data_controls, render_reporting
from src.semantic_metrics import catalog_records
from src.query_explanation import explain_plan
from src.semantic_query import EXAMPLES as SEMANTIC_QUESTIONS
import hashlib
from ai_copilot import build_context, context_key, configuration_ready, generate_brief, CopilotError

st.set_page_config(page_title="Provider Performance Copilot", page_icon="📊", layout="wide")

apply_style()

@st.cache_data
def read_data(modified_ns):
    return load_data()

try:
    df = read_data(DATA_PATH.stat().st_mtime_ns)
except (OSError, ValueError, pd.errors.ParserError) as exc:
    st.error(f"Unable to load provider data: {exc}")
    st.stop()
if 'uploaded_data' in st.session_state:
    df = st.session_state.uploaded_data
header()
revision = st.session_state.get('dataset_revision', 0)
content, controls = st.columns([3.6, 1.45], gap="large")
with controls, st.container(border=True, key="dashboard_filters"):
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
    p = benchmark(filtered, target)
    kpis = calculate_kpis(filtered)
    visits, capacity, revenue = kpis["visits"], kpis["capacity"], kpis["revenue"]
    columns = st.columns(4)
    for col, label, value in zip(columns, ["Completed visits", "Capacity", "Utilization", "Revenue"],
                                 [f"{visits:,}", f"{capacity:,}", f"{kpis['utilization']:.1%}", (f"${revenue / 1_000_000:,.2f}M" if revenue >= 1_000_000 else f"${revenue:,.0f}")]):
        col.metric(label, value, help=f"Exact reported revenue: ${revenue:,.2f}" if label == "Revenue" else None)
    with st.container(key="overview_operational_kpis"):
        columns = st.columns(3)
        columns[0].metric("Unused capacity", f"{kpis['unused_capacity']:,} slots")
        columns[1].metric("Visits / staffed hour", f"{kpis['productivity']:.2f}")
        columns[2].metric("Revenue opportunity", f"${p.opportunity.sum():,.0f}")
    st.caption(f"{p.provider_id.nunique()} providers · {dates[0]:%b %d, %Y} – {dates[1]:%b %d, %Y} · Opportunity modeled at {target:.0%} utilization")

    overview, copilot, benchmarks, opportunities, workspace, scenarios, executive, reporting = st.tabs(["Overview", "Ask copilot", "Compare", "Opportunities", "Executive workspace", "Scenarios", "Executive brief", "Data & Reporting"])
    with overview:
        monthly = monthly_performance(filtered)
        left, right = st.columns(2)
        with left:
            st.subheader("Visits and available capacity")
            st.plotly_chart(visits_chart(monthly), width="stretch")
        with right:
            st.subheader("Revenue by month")
            st.plotly_chart(revenue_chart(monthly), width="stretch")
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
        st.caption("Peer utilization is weighted by capacity within each specialty and current filters, including the provider. Productivity is visits per staffed hour, not clinical quality.")
        st.dataframe(p[["provider", "specialty", "clinic", "visits", "capacity", "utilization", "peer_utilization", "visits_per_hour", "peer_productivity", "productivity_index", "utilization_gap_pp", "peer_count", "revenue"]],
                     hide_index=True, width="stretch", column_config={
                         "utilization": st.column_config.NumberColumn("Utilization", format="percent"),
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
                            st.session_state.brief_discussion.extend([{"role": "user", "text": brief_question}, {"role": "assistant", **reply}])
                            st.session_state.brief_discussion = st.session_state.brief_discussion[-40:]
                        history = st.session_state.brief_discussion
                        for start in reversed(range(0, len(history), 2)):
                            for message in history[start:start + 2]:
                                with st.chat_message(message["role"]):
                                    st.markdown(message["text"])
                                    if message["role"] == "assistant":
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
            render_voice(filtered, target, chat_scope, raw_df=query_data, data_bounds=data_bounds)
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
    with st.expander("Metric definitions and assumptions"):
        st.markdown("""
        - **Utilization:** completed visits ÷ available appointment slots; all rollups use weighted totals.
        - **Booking rate:** booked ÷ capacity. **No-show rate:** (booked − visits) ÷ booked; zero when no bookings.
        - **Specialty benchmark:** specialty total visits ÷ specialty total capacity; productivity uses specialty staffed hours instead. Peers include self within the selection; one-provider groups are self-comparisons.
        - **Utilization gap (pp):** 100 × (provider utilization − specialty utilization). **Productivity index:** provider visits/hour ÷ specialty visits/hour.
        - **Productivity:** completed visits ÷ staffed hours. FTE is reflected in scheduled hours and slots.
        - **Revenue:** synthetic realized revenue; not charges, profit, or a reimbursement forecast.
        - **Unused capacity:** capacity − completed visits.
        - **Estimated opportunity:** for each provider, max(0, target × capacity − visits) × observed revenue per visit, then summed. Providers with no visits have no inferred revenue rate.
        - The scenario assumes demand, staffing, payer mix, and visit revenue support additional visits. It excludes incremental costs and is not guaranteed revenue. Fractional visits represent an expected scenario.
        - This dashboard measures operational activity, not clinical quality or individual care recommendations.
        """)
