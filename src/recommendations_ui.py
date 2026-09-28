"""Recommendation-engine presentation; calculation decisions stay in recommendations.py."""
import hashlib
import streamlit as st

from ai_copilot import configuration_ready, CopilotError
from copilot_prompt import ACTIONS
from src.recommendations import recommendation_engine, explain_recommendations


def render_recommendations(df, target, uploads_active=False):
    st.subheader("Deterministic recommendations")
    st.caption("Python applies fixed rules to the selected provider-day data. AI, when configured, may only summarize the resulting evidence and select rule-approved next steps.")
    recommendations = recommendation_engine(df, target)
    if recommendations.empty:
        st.info("No deterministic recommendation rules triggered for this selection.")
        return
    display = recommendations[["provider", "specialty", "recommendation", "evidence", "modeled_opportunity"]].copy()
    st.dataframe(display, hide_index=True, width="stretch", column_config={
        "modeled_opportunity": st.column_config.NumberColumn("Modeled opportunity", format="dollar"),
    })
    st.caption("Demand is not measured. Below-target utilization therefore triggers demand validation, not an assumption that demand exists. Recommendations can overlap and are not additive.")
    scope = hashlib.sha256((df.to_csv(index=False) + str(target)).encode()).hexdigest()
    if st.session_state.get("recommendation_scope") != scope:
        st.session_state.pop("recommendation_explanations", None)
        st.session_state.recommendation_scope = scope
    label = "Explain calculated recommendations with AI" if configuration_ready() and not uploads_active else "Show rule explanations"
    if st.button(label, key="explain_recommendations"):
        try:
            st.session_state.recommendation_explanations = explain_recommendations(
                recommendations, use_ai=configuration_ready() and not uploads_active,
                source_df=df, target=target)
        except CopilotError as exc:
            st.error(str(exc))
    explanations = st.session_state.get("recommendation_explanations")
    if explanations:
        st.markdown("#### Evidence and next steps")
        for row in recommendations.head(10).itertuples():
            explanation = explanations.get(row.recommendation_id)
            if not explanation:
                continue
            with st.container(border=True):
                st.markdown(f"**{row.provider} · {row.recommendation}**")
                st.caption("Evidence calculated by Python")
                st.write(row.evidence)
                st.caption(explanation["mode"])
                st.write(explanation["summary"])
                st.markdown("**Rule-approved next steps**")
                for action_id in explanation["action_ids"]:
                    st.write(f"• {ACTIONS[action_id]}")
