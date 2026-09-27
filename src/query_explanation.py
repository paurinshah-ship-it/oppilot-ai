"""Optional AI-selected guidance, appended to immutable Python-calculated facts.

No user prompt, conversation history or uploaded data crosses this boundary.
Reuse the existing schema-constrained API adapter and credential handling.
"""
from ai_copilot import build_context, _request_actions, CopilotError
from copilot_prompt import ACTIONS
from src.query_planner import execute_plan


def explain_plan(plan, df, source, bounds, target=.85, use_ai=True):
    # Provenance is checked before any API call, including apparently synthetic uploads.
    build_context(source, target)
    build_context(df, target)
    try:
        result=execute_plan(plan,df,source,bounds,target)
    except ValueError as exc:
        raise CopilotError("The query plan is no longer valid for this selection.") from exc
    if result['status']!='answered' or 'calculated_result' not in result:
        raise CopilotError('An explanation requires an available, successfully calculated plan.')
    facts=result['calculated_result']
    payload={'data_type':'verified synthetic aggregates','query_result':facts}
    ids=_request_actions(payload) if use_ai else ['review_staffing','monitor']
    # Defense in depth: never render unconstrained model text or invented figures.
    if not isinstance(ids,list) or not 2<=len(ids)<=4 or any(not isinstance(i,str) or i not in ACTIONS for i in ids) or len(set(ids))!=len(ids):
        raise CopilotError('Invalid explanation output; no unverified text was displayed.')
    return {'text':result['text']+'\n\nManagement interpretation:\n'+'\n'.join('- '+ACTIONS[i] for i in ids),
            'mode':'AI-selected guidance; all facts and numbers calculated in Python' if use_ai else 'Local explanation; no model call',
            'facts':facts}
