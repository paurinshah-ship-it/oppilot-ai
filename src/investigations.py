"""Descriptive rule-based anomalies and associated-change investigations.

Thresholds are demo heuristics, not statistical significance or clinical standards.
All comparisons filter dated rows first. No model infers causes or missing data.
"""
import re
import pandas as pd
from src.analytics import benchmark
from src.semantic_metrics import metric_value, format_metric
from src.workspace import period_changes
from src.date_ranges import latest_month_windows, previous_window, parse_date_range, parse_comparison_ranges, format_range
from src.comparative import reply, resolve_providers, grounding_record

UTIL_DROP = .15  # relative decline, not 15 percentage points
NO_SHOW_SPIKE_PP = 5.0
PEER_GAP_PP = 15.0
MIN_CAPACITY = 100
MIN_BOOKINGS = 30
MIN_OTHER_PEERS = 3


def anomalies(df, windows, bounds):
    snapshot=period_changes(df,windows,bounds)
    findings=[]
    if snapshot['status']!='ok': return snapshot, pd.DataFrame()
    changes=snapshot['changes']
    def add(r,rule,before,after,change,evidence):
        findings.append(dict(Provider=r.provider, Signal=rule, Before=before, After=after, Change=change, Evidence=evidence))
    for _,r in changes.iterrows():
        if min(r.capacity_before,r.capacity_after)>=MIN_CAPACITY:
            relative=(r.utilization_after/r.utilization_before-1) if r.utilization_before else None
            if relative is not None and relative<=-UTIL_DROP+1e-12:
                add(r,'Utilization decline',f'{r.utilization_before:.1%}',f'{r.utilization_after:.1%}',f'{relative:.1%} relative; {r.utilization_change_pp:+.1f} pp','At least 100 staffed slots in both periods; relative decline >=15%')
            if r.visits_after>r.visits_before and r.revenue_after<r.revenue_before:
                add(r,'Revenue down while visits rise',f'${r.revenue_before:,.0f} / {r.visits_before:,.0f} visits',f'${r.revenue_after:,.0f} / {r.visits_after:,.0f} visits',f'${r.revenue_after-r.revenue_before:+,.0f}', 'Review observed revenue per visit; payer mix and collections are not measured')
            peers=changes[(changes.specialty_after==r.specialty_after)&(changes.specialty_before==r.specialty_before)&(changes.index!=r.name)&(changes.capacity_before>=MIN_CAPACITY)&(changes.capacity_after>=MIN_CAPACITY)]
            if r.specialty_before==r.specialty_after and len(peers)>=MIN_OTHER_PEERS:
                median=peers.utilization_change_pp.median()
                gap=r.utilization_change_pp-median
                if abs(gap)>=PEER_GAP_PP:
                    add(r,'Different utilization trend from peers',f'Other-peer median change {median:+.1f} pp',f'Provider change {r.utilization_change_pp:+.1f} pp',f'{gap:+.1f} pp gap',f'{len(peers)} other matched providers in the same specialty; not a quality score')
        if min(r.booked_before,r.booked_after)>=MIN_BOOKINGS and r.no_show_change_pp>=NO_SHOW_SPIKE_PP-1e-12:
            add(r,'No-show spike',f'{r.no_show_rate_before:.1%}',f'{r.no_show_rate_after:.1%}',f'{r.no_show_change_pp:+.1f} pp','At least 30 bookings in both periods; increase >=5 percentage points')
    return snapshot,pd.DataFrame(findings)


def investigate(df,windows,bounds):
    snapshot=period_changes(df,windows,bounds)
    # Complete provider turnover still permits aggregate accounting analysis.
    # period_changes emits two records only after coverage and nonempty-frame checks.
    if snapshot['status']=='unavailable' and len(snapshot['records'])==2:
        snapshot['status']='ok'
        snapshot['message']+=' No matched-provider trend can be inferred; aggregate changes include complete provider turnover.'
    if snapshot['status']!='ok': return snapshot['message'],snapshot
    frames=[df[df.date.dt.date.between(*w)] for w in windows]
    lines=['**Revenue investigation — associated changes, not causes**',snapshot['message'],
           'The totals below include all selected providers observed in each period; matched-provider anomaly checks are separate.',
           '| Metric | Earlier period | Later period | Change |','|---|---:|---:|---:|']
    keys=['revenue','completed_visits','no_show_rate','revenue_per_visit','utilization','capacity','unused_capacity','productivity']
    values={k:[metric_value(f,k) for f in frames] for k in keys}
    for k,(a,b) in values.items():
        change='Unavailable' if pd.isna(a) or pd.isna(b) else (f'{100*(b-a):+.1f} pp' if k in ('no_show_rate','utilization') else f'{b-a:+,.2f} ({(b/a-1)*100:+.1f}%)' if a else f'{b-a:+,.2f}; relative change undefined')
        lines.append(f'| {k.replace("_"," ").title()} | {format_metric(a,k)} | {format_metric(b,k)} | {change} |')
    lines+=['| Collections | Not measured | Not measured | Unavailable |','| Cancellations | Not measured | Not measured | Unavailable |']
    revenue_change=values['revenue'][1]-values['revenue'][0]
    if revenue_change>=0: lines.append('Revenue did not decline in this comparison; the decline premise is not supported.')
    v0,v1=values['completed_visits'];p0,p1=values['revenue_per_visit']
    if pd.notna(p0) and pd.notna(p1):
        # Exact symmetric arithmetic decomposition of R=V*P, not causal attribution.
        volume=(v1-v0)*(p0+p1)/2
        rate=(p1-p0)*(v0+v1)/2
        lines.append(f'Arithmetic decomposition: visit-volume component ${volume:+,.2f}; observed revenue-per-visit component ${rate:+,.2f}. These sum to revenue change ${revenue_change:+,.2f}.')
        negatives={'Lower completed visit volume':volume,'Lower observed revenue per visit':rate}
        negatives={k:v for k,v in negatives.items() if v<0}
        if revenue_change<0 and negatives:
            minimum=min(negatives.values())
            lines.append('Largest negative arithmetic component (ties retained): '+', '.join(k for k,v in negatives.items() if abs(v-minimum)<1e-8)+'. This is an accounting association, not an identified cause.')
    else: lines.append('Revenue decomposition unavailable: at least one period has no visits and no defined revenue-per-visit rate.')
    before,after=[f.groupby('provider_id').agg(visits=('visits','sum'),revenue=('revenue','sum')) for f in frames]
    entered=after.index.difference(before.index);exited=before.index.difference(after.index);common=before.index.intersection(after.index)
    lines.append(f'Provider mix: {len(common)} matched, {len(entered)} newly observed, {len(exited)} no longer observed. These are observation changes, not confirmed hires or departures. Newly observed revenue ${after.loc[entered,"revenue"].sum():,.2f}; previously observed-only revenue ${before.loc[exited,"revenue"].sum():,.2f}.')
    if v0 and v1:
        ids=before.index.union(after.index)
        shares0=before.visits.reindex(ids,fill_value=0)/v0
        shares1=after.visits.reindex(ids,fill_value=0)/v1
        movement=100*(shares1-shares0).abs().sum()/2
        lines.append(f'Provider visit-share redistribution: {movement:.1f} percentage points (half the sum of absolute provider share changes). Revenue per visit also reflects provider mix; these are not independent additive causes.')
    lines.append('Suggested investigation: review staffed schedules, booking and no-show patterns, and revenue posting or pricing changes. Cancellations, payer mix and appointment complexity require additional data. Causation cannot be established from this dataset.')
    snapshot['records']=[grounding_record(f,*w,label) for f,w,label in zip(frames,windows,['Earlier period','Later period'])]
    table_end = 5 + len(keys) + 2
    text = '\n\n'.join(lines[:3])+'\n\n'+'\n'.join(lines[3:table_end])+'\n\n'+'\n\n'.join(lines[table_end:])
    return text.replace('$', r'\$'),snapshot


def investigation_response(q,df,source,today,bounds):
    detect=bool(re.search(r'\banomal(?:y|ies)\b|unusual changes',q))
    why=bool(re.search(r'\bwhy\b|\binvestigate\b',q) and re.search(r'revenue|collections',q))
    if not (detect or why): return None
    if 'collections' in q:
        return reply('Collections are not measured. Revenue cannot be substituted for collections, and cancellations are also unavailable. I cannot establish why collections declined. Ask: "Investigate revenue decline" or "Show revenue per visit by provider".','unavailable')
    names,error=resolve_providers(q,sorted(source.provider.unique()))
    if error: return reply(error,'limited')
    pair=parse_comparison_ranges(q,today,*bounds)
    parsed=parse_date_range(q,today,*bounds) if not pair else None
    residual=' '.join(p['remaining_question'] for p in pair) if pair else parsed['remaining_question']
    for name in names:
        residual=residual.replace(name.lower(),' ')
        residual=re.sub(r'\b(?:dr\.?|doctor)\s+'+re.escape(name.split()[-1].lower())+r'\b',' ',residual)
    residual=re.sub(r"[’']s\b",' ',residual)
    allowed=set('show detect find anomalies anomaly unusual changes why did has have our the revenue decline declined decreased decrease fall fallen dropped drop investigate for in during compare versus vs and provider providers a an'.split())
    if set(re.findall('[a-z]+',residual))-allowed:
        return reply('I could not resolve every investigation qualifier. Specify a named provider and a month, or use "Investigate revenue decline" for the latest two complete months.','limited')
    scoped=source if pair or parsed['status']!='no_date_requested' else df
    actual_bounds=bounds if scoped is source else (df.date.min().date(),df.date.max().date()) if not df.empty else (None,None)
    if scoped.empty: return reply('No selected data is available.','unavailable')
    if names: scoped=scoped[scoped.provider.isin(names)]
    if pair:
        if any(p['status']!='ok' for p in pair):
            from src.comparative import coverage_error
            return coverage_error(pair,bounds)
        windows=sorted([(p['effective_start'],p['effective_end']) for p in pair])
        if windows[0][1]>=windows[1][0]: return reply('Choose two nonoverlapping periods.','limited')
    elif parsed['status']=='no_date_requested': windows=latest_month_windows(*actual_bounds)
    elif parsed['status']=='ok':
        current=(parsed['effective_start'],parsed['effective_end']);windows=[previous_window(*current),current]
    else:
        from src.comparative import coverage_error
        return coverage_error([parsed],bounds)
    if detect:
        snap,flags=anomalies(scoped,windows,actual_bounds)
        text=snap['message']+'\n\n'
        if snap['status']=='ok':
            text+=('No configured anomaly thresholds triggered. This does not prove performance is normal.' if flags.empty else '\n\n'.join(f'**{r.Provider}: {r.Signal}** — {r.Before} → {r.After}; {r.Change}. {r.Evidence}.' for r in flags.itertuples()))
        text+='\n\nRules are descriptive demo thresholds, not statistical significance. Differences do not establish causation.'
        text=text.replace('$', r'\$')
    else: text,snap=investigate(scoped,windows,actual_bounds)
    return reply(text,'answered' if snap['status']=='ok' else snap['status'],snap['records'])
