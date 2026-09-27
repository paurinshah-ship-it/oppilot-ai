"""Structured, session-scoped analytical state. Never extract facts from prose."""
import hashlib
import pandas as pd


def scope_key(df, source, target):
    """Bind memory to dataset contents, team, dashboard rows and target."""
    digest = hashlib.sha256(str(target).encode())
    for frame in (df, source):
        digest.update(str(list(frame.columns)).encode())
        digest.update(pd.util.hash_pandas_object(frame, index=False).values.tobytes())
    return digest.hexdigest()


def read_state(history, scope):
    last = next((m for m in reversed(history or []) if m.get('role') == 'assistant'), {})
    state = last.get('analytical_state')
    return state if isinstance(state, dict) and state.get('scope') == scope else None


def attach_state(response, scope):
    """Advance only after a calculated answer. Ambiguous entity lists stay lists."""
    if response['status'] not in ('answered', 'limited') or response.get('definition'):
        return
    context = response.get('context')
    if not context:
        return
    metric = context.get('metric')
    if metric == 'visits': metric = 'completed_visits'
    response['analytical_state'] = dict(version=1, scope=scope, metric=metric,
        providers=list(context.get('providers', [])), start=context.get('start'), end=context.get('end'),
        dimension=response.get('query_plan', {}).get('dimension','provider'),
        comparison=response.get('query_plan', {}).get('comparison_kind'),
        specialties=response.get('query_plan', {}).get('specialties', []))
