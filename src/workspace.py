"""Executive workspace calculations and supported conversation intents.

Calculations use selected provider-day rows. No model call or credentials are
required. Static metrics and latest-month trends always retain separate labels.
"""
import re
import pandas as pd
from src.analytics import benchmark, calculate_kpis
from src.data import PROVIDER_NAMES, SPECIALTIES
from src.date_ranges import (format_range, latest_month_windows, previous_window,
                             parse_date_range, parse_comparison_ranges)
from src.comparative import (reply, coverage_error, dated_rows, grounding_record,
                             resolve_providers, context_for, formatted, change_text)

DEFINITIONS = {
    'revenue opportunity': 'Revenue opportunity = sum over providers of max(0, target utilization × capacity − completed visits) × observed provider revenue per visit. The target is a scenario assumption. This is gross potential revenue, not profit, collections, or a forecast. A provider with zero visits has an unknown revenue rate; the dashboard stores zero as a placeholder, while this workspace reports unknown rates explicitly.',
    'revenue per visit': 'Revenue per visit = total revenue / completed visits. It is weighted by completed visits, not an average of daily rates. With zero visits the rate is unavailable; the legacy dashboard uses a zero placeholder.',
    'no-show rate': 'No-show rate = (booked appointments − completed visits) / booked appointments. Counts satisfy booked = visits + no-shows. The dashboard uses zero as a placeholder for zero bookings; comparisons and this workspace report the rate as unavailable. Cancellations are not measured separately.',
    'unused capacity': 'Unused capacity = available staffed appointment slots − completed visits = unbooked slots + no-shows. Unbooked slots = capacity − booked appointments. This is an appointment count, not a revenue estimate.',
    'utilization': 'Utilization = completed visits / available staffed appointment slots. Rollups divide summed visits by summed capacity; daily percentages are not averaged. It measures activity, not clinical quality. The validated dataset requires positive staffed capacity; empty dashboard selections use a zero placeholder and comparisons report undefined denominators as unavailable.',
    'productivity': 'Productivity = completed visits / staffed hours. Rollups use summed visits and hours. It is not adjusted for appointment complexity and is not a quality score. Validated provider-days require positive hours; the dashboard returns zero for an empty selection.',
    'capacity': 'Capacity is the number of available appointment slots in staffed sessions, summed over the selected provider-days. Leave days have no rows and no capacity; the data cannot distinguish unrecorded days from unscheduled days without a staffing roster.',
    'revenue': 'Revenue is synthetic realized revenue summed over selected provider-days. Collections, charges, costs, and profit are not separately measured. Revenue is not a proxy for those missing fields.',
    'visits': 'Completed visits are summed over selected provider-day rows. They count appointments, not unique patients; repeat patients cannot be identified from this aggregate dataset.',
}


def metric_definition(q):
    if not re.search(r'\bexplain\b|\bformula\b|what does.*mean|how (?:is|are).*calculat', q):
        return None
    normalized = q.replace('no show', 'no-show').replace('estimated revenue opportunity', 'revenue opportunity')
    key = next((key for key in DEFINITIONS if key in normalized), None)
    if not key:
        return None
    result = reply(DEFINITIONS[key])
    result['grounding'] = 'Grounding: implemented metric formulas · src/analytics.py and src/comparative.py'
    result['definition'] = True
    return result


def period_changes(df, windows, bounds):
    """Match provider IDs across two windows before calculating rate changes.

    Utilization change (pp) = 100 × (after visits/slots − before visits/slots).
    No-show change (pp) = 100 × (after missed/booked − before missed/booked).
    Visit change (%) = 100 × (after visits − before visits)/before visits;
    zero baselines and zero-booking no-show rates remain NaN, never zero change.
    """
    periods = [parse_date_range(f'from {a} to {b}', b, *bounds) for a,b in windows]
    error = coverage_error(periods, bounds)
    if error:
        return {'status': error['status'], 'message': error['text'], 'windows': windows,
                'changes': pd.DataFrame(), 'records': []}
    frames = [dated_rows(df, *w) for w in windows]
    if any(f.empty for f in frames):
        return {'status': 'unavailable', 'message': 'A comparison period has no selected provider-day records.',
                'windows': windows, 'changes': pd.DataFrame(), 'records': []}
    left, right = [benchmark(f).set_index('provider_id') for f in frames]
    for p in (left, right):
        p.loc[p.booked == 0, 'no_show_rate'] = float('nan')
    ids = left.index.intersection(right.index)
    changes = left.loc[ids].add_suffix('_before').join(right.loc[ids].add_suffix('_after'))
    changes['provider'] = changes.provider_after
    changes['utilization_change_pp'] = 100*(changes.utilization_after-changes.utilization_before)
    changes['no_show_change_pp'] = 100*(changes.no_show_rate_after-changes.no_show_rate_before)
    changes['visits_change_pct'] = 100*(changes.visits_after-changes.visits_before)/changes.visits_before.where(changes.visits_before != 0)
    excluded = len(left.index.union(right.index)) - len(ids)
    message = (f'{format_range(*windows[0])} → {format_range(*windows[1])}. '
               f'{len(ids)} matched providers; {excluded} excluded because one period has no observations. '
               'Bounds are available; daily completeness is not verified. Staffing exposure and visit mix may differ.')
    return {'status': 'ok' if len(ids) else 'unavailable', 'message': message,
            'windows': windows, 'changes': changes,
            'records': [grounding_record(f[f.provider_id.isin(ids)], *w, label)
                        for f,w,label in zip(frames, windows, ['First period','Second period'])]}


def trend_snapshot(df):
    """Latest two complete calendar months within selected observed bounds."""
    if df.empty:
        return {'status':'unavailable', 'message':'No selected data.', 'windows':[], 'changes':pd.DataFrame(), 'records':[]}
    bounds = df.date.min().date(), df.date.max().date()
    return period_changes(df, latest_month_windows(*bounds), bounds)


def top_opportunities(df, target, trend=None):
    """Metric-specific leaders; ties retained. Categories overlap, never add them."""
    columns = ['Opportunity','Provider','Impact','Period']
    if df.empty:
        return pd.DataFrame(columns=columns)
    p = benchmark(df, target)
    period = format_range(df.date.min().date(), df.date.max().date())
    rows = []
    rules = [
        ('Highest unused capacity', p[p.unused_capacity > 0], 'unused_capacity', 'max', lambda v:f'{v:,.0f} slots'),
        ('Highest no-show rate', p[(p.booked > 0) & (p.no_show_rate > 0)], 'no_show_rate', 'max', lambda v:f'{v:.1%} rate'),
        ('Lowest utilization', p[p.utilization < target], 'utilization', 'min', lambda v:f'{v:.1%} utilization'),
        ('Largest revenue opportunity', p[p.revenue_rate_known & (p.opportunity > 0)], 'opportunity', 'max', lambda v:f'${v:,.0f} modeled gross revenue'),
    ]
    for title, frame, metric, operation, fmt in rules:
        if frame.empty:
            continue
        extreme = getattr(frame[metric], operation)()
        for row in frame[frame[metric] == extreme].sort_values('provider').itertuples():
            rows.append(dict(zip(columns, [title,row.provider,fmt(getattr(row,metric)),period])))
    for row in p[~p.revenue_rate_known].sort_values('provider').itertuples():
        rows.append(dict(zip(columns, ['Unknown revenue opportunity', row.provider, 'No observed revenue per visit', period])))
    trend = trend if trend is not None else trend_snapshot(df)
    if trend['status'] == 'ok':
        declining = trend['changes'].query('utilization_change_pp < 0')
        if not declining.empty:
            worst = declining.utilization_change_pp.min()
            for row in declining[declining.utilization_change_pp == worst].sort_values('provider').itertuples():
                rows.append(dict(zip(columns, ['Biggest month-over-month decline',row.provider,
                    f'{row.utilization_change_pp:+.1f} percentage points',
                    f'{format_range(*trend["windows"][0])} → {format_range(*trend["windows"][1])}'])))
    return pd.DataFrame(rows, columns=columns)


def executive_summary(df, target, trend=None):
    """Local summary: selected-period totals plus separately labeled monthly changes."""
    if df.empty:
        return 'No data matches the selection.'
    k, p = calculate_kpis(df), benchmark(df, target)
    period = format_range(df.date.min().date(), df.date.max().date())
    volume = p[p.visits == p.visits.max()].sort_values('provider')
    unused = p[p.unused_capacity == p.unused_capacity.max()].sort_values('provider')
    lines = [f'**Selected period: {period}**',
             f'Overall utilization was {k["utilization"]:.1%}: {k["visits"]:,} completed visits / {k["capacity"]:,} staffed slots. Revenue was ${k["revenue"]:,.0f}.',
             'Highest visit volume (ties retained): ' + '; '.join(f'{r.provider}: {r.visits:,.0f}' for r in volume.itertuples()) + '.',
             'Largest unused capacity (ties retained): ' + '; '.join(f'{r.provider}: {r.unused_capacity:,.0f} slots' for r in unused.itertuples()) + '.']
    known = p[p.revenue_rate_known]
    if not known.empty and known.opportunity.max() > 0:
        leaders = known[known.opportunity == known.opportunity.max()].sort_values('provider')
        lines.append('Largest modeled revenue opportunity: ' + '; '.join(f'{r.provider}: ${r.opportunity:,.0f}' for r in leaders.itertuples()) + f' at {target:.0%} utilization.')
    else:
        lines.append('No positive modeled opportunity among providers with known revenue rates.')
    unknown = int((~p.revenue_rate_known).sum())
    if unknown:
        lines.append(f'{unknown} providers have unknown revenue opportunity because they have no observed revenue per visit.')
    trend = trend if trend is not None else trend_snapshot(df)
    lines.append('**Monthly change (separate from the selected-period totals)**\n\n' + trend['message'])
    if trend['status'] == 'ok':
        changes = trend['changes']
        valid = changes.no_show_change_pp.notna()
        lines.append(f'No-show rates increased for {int((changes.no_show_change_pp > 0).sum())} of {int(valid.sum())} providers with defined rates in both months; {int((~valid).sum())} matched providers had undefined rates.')
    else:
        lines.append('Monthly changes are unavailable; no directional claim was calculated.')
    lines.append('Management review: examine scheduling access and reminders where measured gaps exist. Opportunities overlap and are not additive. Revenue opportunity is a scenario, not collections or guaranteed profit; these metrics do not establish causation or clinical quality.')
    return '\n\n'.join(lines)


def specialty_metrics(df, target):
    """Weighted specialty ratios and sum of provider-level modeled opportunities.

    Opportunity excludes unknown provider revenue rates; count these explicitly.
    If every rate is unknown, report NaN rather than a zero-dollar opportunity.
    """
    p = benchmark(df, target)
    out = df.groupby('specialty')[['visits','capacity','booked','no_shows','revenue','staffed_hours']].sum()
    out['utilization'] = out.visits / out.capacity.where(out.capacity != 0)
    out['no_show_rate'] = out.no_shows / out.booked.where(out.booked != 0)
    out['revenue_per_visit'] = out.revenue / out.visits.where(out.visits != 0)
    out['unused_capacity'] = out.capacity - out.visits
    p = p.assign(known_opportunity=p.opportunity.where(p.revenue_rate_known), unknown_rate=~p.revenue_rate_known)
    out['opportunity'] = p.groupby('specialty').known_opportunity.sum(min_count=1)
    out['unknown_rates'] = p.groupby('specialty').unknown_rate.sum()
    return out.reset_index()


def scorecard(df, provider, target):
    """Independent dimensions, never a composite provider score."""
    rows = df[df.provider == provider]
    if rows.empty:
        return pd.DataFrame(columns=['Metric','Value'])
    p = benchmark(rows, target).iloc[0]
    return pd.DataFrame([
        ['Completed visits',f'{p.visits:,.0f}'], ['Utilization',f'{p.utilization:.1%}'],
        ['No-show rate',f'{p.no_show_rate:.1%}' if p.booked else 'Unavailable (no bookings)'],
        ['Revenue',f'${p.revenue:,.2f}'], ['Collections','Not measured'],
        ['Revenue per visit',f'${p.revenue_per_visit:,.2f}' if p.revenue_rate_known else 'Unavailable (no visits)'],
        ['Unused capacity',f'{p.unused_capacity:,.0f} slots'],
        ['Productivity',f'{p.visits_per_hour:.2f} visits / staffed hour'],
        ['Modeled revenue opportunity',f'${p.opportunity:,.2f}' if p.revenue_rate_known else 'Unknown revenue rate'],
    ], columns=['Metric','Value'])


def investigation(provider, trend):
    """Report actual direction and measured associations; never infer causes."""
    if trend['status'] != 'ok':
        return trend['message'] + '\n\nNo change or cause can be established from these windows.'
    selected = trend['changes'][trend['changes'].provider == provider]
    if selected.empty:
        return 'This provider has no matched observations in both periods; no change was calculated.'
    r = selected.iloc[0]
    delta = r.utilization_change_pp
    direction = 'decreased' if delta < 0 else 'increased' if delta > 0 else 'was unchanged'
    text = f'{provider}: utilization {direction}, {r.utilization_before:.1%} → {r.utilization_after:.1%} ({delta:+.1f} percentage points). '
    if delta >= 0:
        text += 'A decrease is not supported by these periods. '
    lines = [text, trend['message'], '| Measured dimension | First period | Second period | Change |', '| :--- | ---: | ---: | :--- |']
    for metric,title in [('visits','Completed visits'),('capacity','Staffed appointment slots'),('booked','Booked appointments'),('no_shows','No-shows')]:
        a,b = r[f'{metric}_before'],r[f'{metric}_after']
        lines.append(f'| {title} | {a:,.0f} | {b:,.0f} | {b-a:+,.0f} |')
    lines += ['', 'These are associated changes, not its cause. The data does not establish causation. Cancellations and appointment mix are not measured.',
              'Suggested investigation: review schedule availability and booking access, reminder processes, and appointment mix using appropriate operational records. No clinical or employment conclusion follows from these metrics.']
    return '\n\n'.join(lines[:2]) + '\n\n' + '\n'.join(lines[2:])


def workspace_response(q, df, source, target, history, today, bounds):
    """Narrow routing; called only after the existing safety check."""
    definition = metric_definition(q)
    if definition:
        return definition
    temporal_why = bool(re.search(r'\bwhy\b', q) and 'utilization' in q and re.search(r'decreas|drop|declin|increas',q))
    known_specialties = [entry[0] for entry in SPECIALTIES]
    specialties = [name for name in sorted(set(known_specialties) | set(source.specialty)) if re.search(r'\b'+re.escape(name.lower())+r'\b',q)]
    specialty_intent = (('specialt' in q and ('highest utilization' in q or 'opportunity' in q)) or ('compare' in q and bool(specialties)))
    if not (temporal_why or specialty_intent):
        return None
    if re.search(r'forecast|predict|\bnext\b|profit|clinical quality|salary|collections',q):
        return reply('Those outcomes are not measured or supported. Use operational metrics from available periods.', 'refused')
    if temporal_why:
        names,error = resolve_providers(q, sorted(set(PROVIDER_NAMES) | set(source.provider)))
        if error:
            return reply(error, 'refused')
        if not names:
            last = next((m for m in reversed(history or []) if m.get('role') == 'assistant'), {})
            names = (last.get('context') or {}).get('providers', [])
        if len(names) != 1:
            return reply('Specify one provider to investigate a utilization change.', 'limited')
        name = names[0]
        if name not in set(source.provider):
            return reply('That provider is not in the current selection.', 'refused')
        pair = parse_comparison_ranges(q,today,*bounds)
        parsed = parse_date_range(q,today,*bounds) if not pair else None
        if pair:
            error = coverage_error(pair,bounds)
            if error:
                return error
            windows = [(p['effective_start'],p['effective_end']) for p in pair]
            trend = period_changes(source[source.provider == name],windows,bounds)
        elif parsed['status'] == 'no_date_requested':
            trend = trend_snapshot(df)
            if trend['status'] == 'ok':
                trend = period_changes(df[df.provider == name],trend['windows'],
                                       (df.date.min().date(),df.date.max().date()))
        else:
            error = coverage_error([parsed],bounds)
            if error:
                return error
            current = parsed['effective_start'],parsed['effective_end']
            trend = period_changes(source[source.provider == name], [previous_window(*current),current],bounds)
        if trend['status'] != 'ok':
            return reply(investigation(name,trend),trend['status'])
        if name not in set(trend['changes'].provider):
            return reply(investigation(name,trend),'unavailable')
        # Ground only the named provider's rows for this investigation.
        records = [grounding_record(dated_rows(source[source.provider == name],*w),*w,label)
                   for w,label in zip(trend['windows'],['First period','Second period'])]
        return reply(investigation(name,trend),'limited',records,context_for([name],'utilization',*trend['windows'][1]))
    parsed = parse_date_range(q,today,*bounds)
    if parsed['status'] not in ('no_date_requested','ok'):
        return coverage_error([parsed],bounds)
    rows = dated_rows(source,parsed['effective_start'],parsed['effective_end']) if parsed['status']=='ok' else df
    if rows.empty:
        return reply('No selected records are available for the requested period.','unavailable')
    if specialties and not set(specialties).issubset(set(rows.specialty)):
        return reply('One or more requested specialties are not in the selected data. Adjust the team filters.','unavailable')
    # Do not silently ignore an unrecognized second specialty or metric.
    remaining = parsed['remaining_question']
    for name in specialties:
        remaining = remaining.replace(name.lower(),'')
    allowed = set('compare and vs versus between which specialty specialties has have the highest greatest largest utilization revenue opportunity opportunities in for our performance'.split())
    if set(re.findall(r'[a-z]+',remaining)) - allowed:
        return reply('I cannot resolve that specialty comparison. Choose exact selected specialty names and utilization or revenue opportunity.','limited')
    if specialties:
        rows = rows[rows.specialty.isin(specialties)]
    table = specialty_metrics(rows,target)
    metric = 'opportunity' if 'opportunit' in q else 'utilization'
    if 'compare' not in q and 'specialties' not in q:
        table = table[table[metric] == table[metric].max()]
    if table.empty:
        return reply('No observed revenue rates are available to estimate specialty opportunity.','unavailable')
    title = 'Specialty opportunity (sum of provider-level estimates)' if metric=='opportunity' else 'Specialty utilization (summed visits / summed capacity)'
    lines = [title, '| Specialty | Visits | Utilization | No-show rate | Revenue | Modeled opportunity | Unknown revenue rates |', '| :--- | ---: | ---: | ---: | ---: | ---: | ---: |']
    for row in table.sort_values([metric,'specialty'],ascending=[False,True],na_position='last').itertuples():
        lines.append(f'| {row.specialty} | {row.visits:,.0f} | {row.utilization:.1%} | {formatted(row.no_show_rate,"no_show_rate")} | ${row.revenue:,.0f} | {formatted(row.opportunity,"revenue")} | {row.unknown_rates} |')
    lines += ['', 'Ties are retained. Opportunity excludes unknown provider rates and is not guaranteed revenue. Specialty mix differs; these are not clinical quality rankings.']
    window = (parsed['effective_start'],parsed['effective_end']) if parsed['status']=='ok' else (rows.date.min().date(),rows.date.max().date())
    return reply('\n\n'.join(lines[:1])+'\n\n'+'\n'.join(lines[1:]),records=[grounding_record(rows,*window)])
