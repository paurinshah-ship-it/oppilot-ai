"""Validated analytical plans. Python owns dates, filters, facts and deltas.

Plans contain only allowlisted metric/dimension IDs and ISO calendar bounds.
This module has no model access. Raw dated rows are filtered before execution.
"""
from datetime import date
import re
import pandas as pd
from src.semantic_metrics import METRICS, metric_value, format_metric
from src.date_ranges import parse_date_range, parse_comparison_ranges, format_range
from src.comparative import reply, grounding_record, resolve_providers
from src.analytical_memory import scope_key, read_state


def identify_metric(q):
    residual=q.replace('_',' ')
    found=[]
    for alias,key in sorted([(a.replace('_',' '),k) for k,m in METRICS.items() for a in (k,)+m.aliases],key=lambda x:len(x[0]),reverse=True):
        pattern=r'\b'+re.escape(alias)+r'\b'
        if re.search(pattern,residual):
            if key not in found: found.append(key)
            residual=re.sub(pattern,' ',residual)
    return found,residual


def period_plan(parsed):
    return {'label': parsed['label'].replace(' ','_').replace('last_quarter','previous_quarter'),
            'start': str(parsed['requested_start']) if parsed['requested_start'] else None,
            'end': str(parsed['requested_end']) if parsed['requested_end'] else None}


def build_plan(q, df, source, today, bounds, state=None):
    """Own specialty temporal comparisons, relative-quarter queries and short follow-ups.

    Unknown residual words never become silently ignored filters.
    """
    follow=bool(re.match(r'^(?:how about|what about)\b',q))
    peer=bool(re.search(r'\bspecialty average\b',q))
    quarter=bool(re.search(r'\b(?:this|last|previous) quarter\b',q))
    specialties=[s for s in sorted(source.specialty.unique(),key=len,reverse=True) if re.search(r'\b'+re.escape(s.lower())+r'\b',q)]
    pair=parse_comparison_ranges(q,today,*bounds)
    if not (follow or peer or quarter or (specialties and pair)):
        return None
    if (follow or peer) and not state:
        return {'error':'There is no unambiguous analytical memory for this selection. Ask an explicit provider and metric question first.'}
    names,name_error=resolve_providers(q,sorted(source.provider.unique()))
    if name_error: return {'error':name_error}
    metrics,residual=identify_metric(q)
    if not metrics and state: metrics=[state['metric']]
    if len(metrics)!=1 or metrics[0] not in METRICS:
        return {'error':'Specify one supported metric for this comparison.'}
    if not names and (follow or peer): names=list(state.get('providers',[]))
    if (follow or peer) and len(names)!=1:
        return {'error':'The previous result did not identify one provider (possibly a tie). Name the provider explicitly before using a follow-up.'}
    if not specialties and follow: specialties=list(state.get('specialties',[]))
    if len(specialties)>1:
        return {'error':'Choose one specialty for a period comparison; multiple specialties would mix separate benchmarks.'}
    for name in names:
        residual=residual.replace(name.lower(),' ')
        residual=re.sub(r'\b(?:dr\.?|doctor)\s+'+re.escape(name.split()[-1].lower())+r'\b',' ',residual)
    for specialty in specialties: residual=re.sub(r'\b'+re.escape(specialty.lower())+r'\b',' ',residual)
    # Remove dates from BOTH parts, then check leftover qualifiers.
    parts=re.split(r'\b(?:versus|vs\.?)\s+',residual,maxsplit=1)
    cleaned=' '.join(parse_date_range(p,today,*bounds)['remaining_question'] for p in parts)
    cleaned=re.sub(r"[’']s\b",' ',cleaned)
    words=set(re.findall('[a-z]+',cleaned))
    allowed=set('compare comparison in during for with to the a an and versus vs this last previous quarter period how what about him her them that his their its specialty average provider providers utilization show our is was'.split())
    if words-allowed: return {'error':'I could not resolve all comparison filters or qualifiers. Specify a metric, a named provider or specialty, and calendar periods.'}
    parsed=parse_date_range(q,today,*bounds) if pair is None else pair[0]
    if pair is None and parsed['status']=='no_date_requested':
        if follow or peer:
            first={'label':'remembered_period','start':str(state['start']),'end':str(state['end'])}
        elif not df.empty:
            first={'label':'dashboard_selection','start':str(df.date.min().date()),'end':str(df.date.max().date())}
        else: return {'error':'No dashboard data is selected.'}
    else: first=period_plan(parsed)
    second=period_plan(pair[1]) if pair else None
    return {'version':1,'metric':metrics[0], 'dimension':'specialty' if specialties and not names else 'provider',
            'providers':names,'specialties':specialties,'period':first['label'],
            'comparison_period':second['label'] if second else ('specialty_average' if peer else None),
            'range':first,'comparison_range':second,
            'comparison_kind':'specialty_average' if peer else ('temporal' if second else 'value'),
            'use_dashboard_rows': parsed['status']=='no_date_requested' and not (follow or peer),
            'error':None}


def validate_plan(plan, source):
    """Independent execution boundary; reject malformed or injected plans."""
    if plan.get('version')!=1 or plan.get('metric') not in METRICS or plan.get('dimension') not in ('provider','specialty'):
        raise ValueError('Invalid metric or dimension in query plan.')
    if plan.get('comparison_kind') not in ('value','temporal','specialty_average'):
        raise ValueError('Invalid comparison operation.')
    for key,column in [('providers','provider'),('specialties','specialty')]:
        values=plan.get(key)
        if not isinstance(values,list) or any(not isinstance(v,str) or v not in set(source[column]) for v in values):
            raise ValueError('Plan entities are outside the selected team.')
    if plan['comparison_kind']=='specialty_average' and METRICS[plan['metric']].operation!='ratio':
        raise ValueError('Specialty averages support utilization, no-show rate, productivity and revenue per visit. Specify a rate metric.')
    if plan['comparison_kind']=='specialty_average' and len(plan['providers'])!=1:
        raise ValueError('Specialty comparison needs exactly one provider.')
    periods=[plan.get('range')]
    if plan['comparison_kind']=='temporal': periods.append(plan.get('comparison_range'))
    for p in periods:
        if not isinstance(p,dict): raise ValueError('Invalid date plan.')
        try: start,end=date.fromisoformat(p['start']),date.fromisoformat(p['end'])
        except (TypeError,KeyError,ValueError): raise ValueError('Invalid date plan.') from None
        if start>end: raise ValueError('Reversed date plan.')
    return periods


def execute_plan(plan, df, source, bounds, target=.85):
    """No model, generated code or SQL. Recheck coverage before aggregating.

    Temporal comparisons use providers observed in both periods. Specialty peer
    rates divide summed measures within selected team, include self, and require
    at least one other provider. Deltas = first requested value - comparator.
    """
    periods=validate_plan(plan,source)
    metric=plan['metric']
    if not METRICS[metric].available:
        return reply('Collections are not measured; revenue cannot substitute for collections.','unavailable')
    if not 0<=target<=1: raise ValueError('Invalid target.')
    checked=[parse_date_range(f'from {p["start"]} to {p["end"]}',date.today(),*bounds) for p in periods]
    for p in checked:
        if p['status']!='ok':
            available=format_range(*bounds) if bounds[0] else 'no dated records'
            return reply(f'Data coverage: {p["status"]}. Requested {p["label"]}; dataset covers {available}. No partial result was calculated. Request explicit available dates.',p['status'])
    frames=[]; windows=[]
    for p in checked:
        start,end=p['effective_start'],p['effective_end'];windows.append((start,end))
        data=df if plan.get('use_dashboard_rows') else source
        frame=data[data.date.dt.date.between(start,end)]
        if plan['specialties']: frame=frame[frame.specialty.isin(plan['specialties'])]
        frames.append(frame)
    if plan['comparison_kind']=='specialty_average':
        subject=frames[0][frames[0].provider.isin(plan['providers'])]
        if subject.empty: return reply('No records for the remembered provider and period.','unavailable')
        specialty=subject.specialty.unique()
        if len(specialty)!=1: return reply('This provider spans multiple specialties; select one specialty explicitly.','limited')
        peers=frames[0][frames[0].specialty==specialty[0]]
        if peers.provider_id.nunique()<2:
            return reply('No other same-specialty provider is available within the selected team. Broaden the team filters.','unavailable')
        frames=[subject,peers];windows=windows*2
        labels=[plan['providers'][0],f'{specialty[0]} weighted specialty average (includes provider; selected team)']
        note=f'Specialty benchmark includes {peers.provider_id.nunique()} providers. It is a weighted aggregate, not an average of provider percentages.'
    else:
        frames=[f[f.provider.isin(plan['providers'])] if plan['providers'] else f for f in frames]
        note=''
        if len(frames)==2:
            ids=set(frames[0].provider_id)&set(frames[1].provider_id)
            excluded=(set(frames[0].provider_id)|set(frames[1].provider_id))-ids
            frames=[f[f.provider_id.isin(ids)] for f in frames]
            note=f'Same-provider comparison: {len(ids)} matched providers; {len(excluded)} excluded because one period had no observations. Staffing exposure may differ.'
        labels=[format_range(*w) for w in windows]
    if any(f.empty for f in frames): return reply('No matching provider-day rows in one or more requested periods.','unavailable')
    values=[metric_value(f,metric,target) for f in frames]
    title=', '.join(plan['providers'] or plan['specialties']) or 'Selected team'
    lines=[f'**{title} · {METRICS[metric].label}**']
    lines += [f'{label}: {format_metric(value,metric)}' for label,value in zip(labels,values)]
    delta=None
    if len(values)==2 and all(pd.notna(v) for v in values):
        delta=values[0]-values[1]
        change=f'{delta*100:+.1f} percentage points' if METRICS[metric].unit=='percent' else f'{delta:+,.2f}'
        lines.append(f'Change (first requested value minus comparator): {change}.')
    elif len(values)==2: lines.append('Change unavailable: a denominator or revenue rate is undefined.')
    lines.extend([note, 'Formula: '+METRICS[metric].formula+'.', 'These operational differences do not establish causation or clinical quality.'])
    records=[grounding_record(f,*w,label=label) for f,w,label in zip(frames,windows,labels)]
    context={'providers':plan['providers'],'metric':metric,'start':windows[0][0],'end':windows[0][1]}
    result=reply('\n\n'.join(x for x in lines if x),'answered',records,context)
    result['calculated_result']={'metric':metric,'values':[float(v) if pd.notna(v) else None for v in values],
        'delta':float(delta) if delta is not None else None,'unit':METRICS[metric].unit,
        'provider_counts':[int(f.provider_id.nunique()) for f in frames], 'record_counts':[len(f) for f in frames]}
    return result


def planner_response(q,df,source,target,history,today,bounds):
    state=read_state(history,scope_key(df,source,target))
    plan=build_plan(q,df,source,today,bounds,state)
    if plan is None: return None
    if plan.get('error'):
        result=reply(plan['error'],'limited')
    else:
        try: result=execute_plan(plan,df,source,bounds,target)
        except ValueError as exc: result=reply(str(exc),'invalid')
    result['query_plan']=plan
    if result['status']!='answered':
        result['text']+='\n\nYou can ask instead:\n- Which providers have the highest no-show rates?\n- Show utilization by specialty during the available period\n- Summarize performance'
    return result
