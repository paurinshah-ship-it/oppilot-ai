"""Deterministic question -> metric/dimension/date plan -> allowlisted executor.

Compositional descriptive queries supplement specialized trend/scenario routes.
Unrecognized qualifiers fail closed: no guessed filters or generated code.
"""
import re
import pandas as pd
from src.semantic_metrics import METRICS, execute_metrics, format_metric
from src.date_ranges import parse_date_range, format_range
from src.comparative import reply, grounding_record, resolve_providers, dated_rows

EXAMPLES = ['Show completed visits and utilization by clinic in 2025',
            'Show no-show rate by specialty and month in July 2025',
            'Show revenue opportunity by provider during the available period']


def interpret_query(question, today, bounds, roster):
    q = question.lower().strip().rstrip('.?! ')
    # Established trend, causal, scenario, chart and follow-up handlers retain ownership.
    if re.search(r'\b(why|trend|improving|decreased|increased|dropped|chart|plot|forecast|predict)\b|what.if|compare with', q):
        return None
    # These forms select the compositional route; existing conversational intents remain compatible.
    if not (re.search(r'\bby\b',q) or q.startswith(('show ', 'total ', 'calculate ')) or any(k in q for k in METRICS if '_' in k)):
        return None
    parsed = parse_date_range(q,today,*bounds)
    residual = parsed['remaining_question']
    metrics = []
    candidates = sorted([(alias.replace('_',' '), key) for key,m in METRICS.items() for alias in (key,)+m.aliases],key=lambda x:len(x[0]),reverse=True)
    residual = residual.replace('_',' ')
    for alias,key in candidates:
        pattern = r'\b'+re.escape(alias)+r'\b'
        if re.search(pattern,residual):
            if key not in metrics: metrics.append(key)
            residual = re.sub(pattern,' ',residual)
    if not metrics:
        return None
    names,error = resolve_providers(residual, roster)
    for name in names:
        residual = re.sub(r'\b'+re.escape(name.lower())+r'\b',' ',residual)
        residual = re.sub(r'\b(?:dr\.?|doctor)\s+'+re.escape(name.split()[-1].lower())+r'\b',' ',residual)
    dimensions = []
    for key,pattern in [('provider',r'\bproviders?\b'),('clinic',r'\bclinics?\b'),('specialty',r'\bspecialt(?:y|ies)\b'),('month',r'\bmonths?\b')]:
        if re.search(pattern,residual):
            dimensions.append(key)
            residual = re.sub(pattern,' ',residual)
    order = 'desc' if re.search(r'\b(highest|most|largest|descending)\b',residual) else 'asc' if re.search(r'\b(lowest|least|ascending)\b',residual) else None
    residual = re.sub(r'\b(show|me|the|our|total|calculate|what|is|are|and|by|for|in|during|period|available|across|per|compare|which|has|have|with|highest|most|largest|lowest|least|ascending|descending|order|rank)\b|[, &]', ' ',residual)
    if error or residual.strip():
        error = error or 'I could not resolve all requested filters or qualifiers. Use catalog metrics with provider, clinic, specialty or month dimensions.'
    if order and len(metrics)>1:
        error = 'Ranking multiple metrics is ambiguous. Ask to rank one metric or omit the ranking.'
    return dict(metrics=metrics, dimensions=dimensions, providers=names, date_range=parsed,
                order=order, error=error)


def semantic_response(q, df, source, target, today, bounds):
    plan = interpret_query(q,today,bounds,sorted(source.provider.unique()))
    if plan is None: return None
    def finish(text,status='answered',records=None):
        response=reply(text,status,records)
        response['query_plan']=plan
        response['date_range']=plan['date_range']
        if status!='answered':
            response['suggested_questions']=EXAMPLES
            response['text']+='\n\nYou can ask instead:\n'+'\n'.join('- '+s for s in EXAMPLES)
        return response
    if plan['error']: return finish(plan['error'],'limited')
    period=plan['date_range']
    if period['status'] not in ('ok','no_date_requested'):
        requested=format_range(period['requested_start'],period['requested_end']) if period.get('requested_start') else period.get('label','requested dates')
        available=format_range(*bounds) if bounds[0] else 'no dated records'
        return finish(f'Date coverage: {period["status"]}. Requested: {requested}. Dataset covers {available}. No partial result was calculated; request explicit available dates.',period['status'])
    rows=dated_rows(source,period['effective_start'],period['effective_end']) if period['status']=='ok' else df
    if plan['providers']: rows=rows[rows.provider.isin(plan['providers'])]
    if rows.empty: return finish('No provider-day rows match this request and the selected team.','unavailable')
    unavailable=[k for k in plan['metrics'] if not METRICS[k].available or any(c not in rows for c in METRICS[k].columns)]
    if unavailable:
        return finish('Not measured: '+', '.join(METRICS[k].label for k in unavailable)+'. Revenue cannot be substituted for collections. No figures were invented.','unavailable')
    result=execute_metrics(rows,plan['metrics'],plan['dimensions'],target)
    if plan['order']:
        result=result.sort_values(plan['metrics'][0],ascending=plan['order']=='asc',na_position='last',kind='stable')
    display=result.drop(columns=['provider_id'],errors='ignore').copy()
    for metric in plan['metrics']: display[metric]=display[metric].map(lambda v:format_metric(v,metric))
    display=display.rename(columns={k:m.label for k,m in METRICS.items()})
    # Escape table delimiters from user-confirmed uploaded labels.
    safe=lambda v: str(v).replace('|','\\|').replace('\n',' ')
    lines=['| '+' | '.join(display.columns)+' |','| '+' | '.join(['---']*len(display.columns))+' |']
    lines+=['| '+' | '.join(safe(v) for v in row)+' |' for row in display.head(100).itertuples(index=False,name=None)]
    if len(display)>100: lines.append(f'Showing 100 of {len(display)} groups; narrow the dates or team for more detail.')
    lines+=['','Formulas:']+[f'- {METRICS[k].label}: {METRICS[k].formula}.' for k in plan['metrics']]
    if 'revenue_opportunity' in plan['metrics']: lines.append(f'Target utilization: {target:.0%}. Gross potential revenue estimate, not collections, profit or a forecast.')
    if result[plan['metrics']].isna().any().any(): lines.append('Unavailable cells have missing measures or undefined denominators; they are not zero.')
    start,end=(period['effective_start'],period['effective_end']) if period['status']=='ok' else (rows.date.min().date(),rows.date.max().date())
    response=finish('\n'.join(lines),records=[grounding_record(rows,start,end,'Semantic query')])
    if len(plan['metrics']) == 1:
        names = list(plan['providers'])
        if not names and plan['order'] and 'provider' in result:
            first = result.iloc[0][plan['metrics'][0]]
            names = result.loc[result[plan['metrics'][0]].eq(first), 'provider'].tolist()
        response['context'] = dict(providers=names, metric=plan['metrics'][0], start=start, end=end)
        response['provider'] = names[0] if len(names) == 1 else None
    response['semantic_data']=result.to_dict('records')
    return response
