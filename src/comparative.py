"""Deterministic comparison routing, calculations, and structured grounding.

No text is sent to a model. Relative dates use the supplied Python clock.
All period filtering happens on provider-day rows before aggregation.
"""
from datetime import date
import re
import pandas as pd
from src.analytics import benchmark
from src.semantic_metrics import metric_value
from src.data import PROVIDER_NAMES
from src.date_ranges import (parse_date_range, parse_comparison_ranges, format_range,
                             previous_window, latest_month_windows)

METRICS = {
    'visits': 'Completed visits', 'utilization': 'Utilization',
    'no_show_rate': 'No-show rate', 'revenue': 'Revenue',
    'revenue_per_visit': 'Revenue per visit', 'unused_capacity': 'Unused capacity',
}


def metric_from_question(q):
    if re.search(r'no[- ]show', q):
        return 'no_show_rate'
    if 'revenue per visit' in q:
        return 'revenue_per_visit'
    if 'unused' in q:
        return 'unused_capacity'
    if 'revenue' in q or 'opportunity' in q:
        return 'revenue'
    if 'visits' in q or 'patients' in q:
        return 'visits'
    return 'utilization'


def resolve_providers(q, roster):
    """Resolve every Dr/Doctor reference; reject unknown or ambiguous surnames."""
    names = []
    for match in re.finditer(r'\b(?:dr\.?|doctor)\s+([a-z]+)(?:\s+([a-z]+))?', q):
        first, second = match[1], match[2]
        full = [n for n in roster if n.lower().removeprefix('dr. ') == f'{first} {second}']
        candidates = full or [n for n in roster if n.split()[-1].lower() == first]
        if len(candidates) != 1:
            return [], ('I cannot find that named doctor in the fictional provider roster.' if not candidates
                        else 'That surname is ambiguous. Use the full provider name.')
        names.extend(candidates)
    for number in re.findall(r'\bprovider\s*(\d+)\b', q):
        i = int(number) - 1
        if not 0 <= i < len(PROVIDER_NAMES):
            return [], 'That provider is not in the current selection.'
        names.append(PROVIDER_NAMES[i])
    return list(dict.fromkeys(names)), None


def dated_rows(df, start, end):
    return df[df.date.dt.date.between(start, end)]


def grounding_record(df, start, end, label='Analysis'):
    return dict(label=label, start=start, end=end, providers=int(df.provider_id.nunique()),
                records=len(df), coverage='Within dataset bounds; daily completeness not verified')


def grounding_text(records):
    lines = ['Grounding: provider-day metrics']
    for item in records:
        lines.append(f"{item['label']}: {format_range(item['start'], item['end'])} · "
                     f"{item['providers']} providers · {item['records']:,} provider-day records")
    lines.append('Data coverage: requested bounds available; daily completeness not verified. '
                 'Absent provider-days may represent leave or unscheduled days.')
    return '\n\n'.join(lines)


def values(df):
    """Weighted metrics, with undefined rate denominators represented by NaN."""
    keys = {'visits': 'completed_visits', 'utilization': 'utilization',
            'no_show_rate': 'no_show_rate', 'revenue': 'revenue',
            'revenue_per_visit': 'revenue_per_visit', 'unused_capacity': 'unused_capacity'}
    return {old: metric_value(df, semantic) for old, semantic in keys.items()}


def formatted(value, metric):
    if pd.isna(value):
        return 'Unavailable (zero denominator)'
    if metric in ('utilization', 'no_show_rate'):
        return f'{value:.1%}'
    if metric in ('revenue', 'revenue_per_visit'):
        return f'${value:,.2f}'
    return f'{value:,.0f}'


def change_text(before, after, metric):
    """Rate changes are percentage points; counts/dollars also show relative %.

    Relative change = 100 * (after-before)/before, undefined at a zero baseline.
    """
    if pd.isna(before) or pd.isna(after):
        return 'Unavailable (zero denominator)'
    if metric in ('utilization', 'no_show_rate'):
        return f'{100*(after-before):+.1f} percentage points'
    relative = f'{100*(after-before)/before:+.1f}%' if before else 'relative change undefined (zero baseline)'
    delta = f'${after-before:+,.2f}' if metric.startswith('revenue') else f'{after-before:+,.0f}'
    return f'{delta} ({relative})'


def comparison_table(before, after):
    lines = ['| Metric | Earlier/requested first | Later/requested second | Change (second − first) |',
             '| :--- | ---: | ---: | :--- |']
    for key, title in METRICS.items():
        lines.append(f'| {title} | {formatted(before[key], key)} | {formatted(after[key], key)} | {change_text(before[key], after[key], key)} |')
    lines.append('| Collections | Not measured | Not measured | Unavailable |')
    return '\n'.join(lines)


def provider_table(df, names):
    lines = ['| Metric | ' + ' | '.join(names) + ' |', '| :--- | ' + ' | '.join(['---:']*len(names)) + ' |']
    rows = [values(df[df.provider == name]) for name in names]
    for key, title in METRICS.items():
        lines.append('| ' + title + ' | ' + ' | '.join(formatted(row[key], key) for row in rows) + ' |')
    lines.append('| Collections | ' + ' | '.join(['Not measured']*len(names)) + ' |')
    return '\n'.join(lines)


def reply(text, status='answered', records=None, context=None):
    records = records or []
    return dict(text=text, status=status, provider=(context['providers'][0] if context and len(context['providers']) == 1 else None),
                suggested_questions=[] if status == 'answered' else ['Summarize performance', 'Which providers have the highest no-show rates?', 'Which provider is most productive?'],
                grounding=grounding_text(records) if records else 'Grounding: no metrics calculated',
                grounding_details=records, context=context, date_range=None)


def context_for(names, metric, start, end):
    return dict(providers=list(names), metric=metric, start=start, end=end)


def coverage_error(periods, bounds):
    invalid = [p for p in periods if p['status'] != 'ok']
    if not invalid:
        return None
    if any(p['status'] in ('invalid', 'no_date_requested') for p in invalid):
        return reply('Specify two supported date periods, for example July 2025 vs August 2025.', 'invalid')
    status = 'unavailable' if any(p['status'] == 'unavailable' for p in invalid) else 'partially_available'
    requested = '; '.join(format_range(p['requested_start'], p['requested_end']) if p.get('requested_start') else p.get('label', 'available period') for p in periods)
    available = format_range(*bounds) if bounds[0] else 'no dated records'
    return reply(f'Data coverage: {"Partial" if status == "partially_available" else "Unavailable"}. '
                 f'Requested: {requested}. Dataset covers {available}. Both periods must be available; '
                 'no comparison was calculated. Request explicit available dates to analyze a partial period.', status)


def handle_comparison(q, df, source, target, history, today, bounds):
    """Return a new comparison answer, or None to preserve existing intent paths."""
    roster = sorted(set(PROVIDER_NAMES) | set(source.provider))
    names, name_error = resolve_providers(q, roster)
    pair = parse_comparison_ranges(q, today, *bounds)
    # Preserve existing complete-year analyses; these new phrases use monthly windows.
    trend = bool(re.search(r'\bimproving\b|dropped|increased|decreased|\btrend\b', q)) and not re.search(r'why|cause|reason', q)
    follow = bool(re.search(r'how does that compare|compare (?:that|with)|show provider trend|estimate revenue impact', q))
    last = next((m for m in reversed(history or []) if m.get('role') == 'assistant'), {})
    context = last.get('context') if follow else None
    is_pair_request = bool(re.search(r'\bcompare\b|\bversus\b|\bvs\b', q)) and (len(names) > 1 or name_error)
    if not (pair or trend or follow or is_pair_request):
        return None
    if re.search(r'forecast|predict|\bnext\b', q):
        return reply('Forecasts are not supported; choose two observed periods.', 'refused')
    if re.search(r'clinical|quality|profit|salary|cancellation', q):
        return reply('These metrics are not measured by the dataset. I cannot infer clinical quality, profit, or cancellations.', 'refused')
    if name_error:
        return reply(name_error + ' Choose exact names from the dashboard.', 'refused')
    if follow and not names:
        if not context or not context.get('providers'):
            return reply('Which provider and metric do you mean? Ask an explicit provider question first; ties need an explicit provider choice.', 'limited')
        names = context['providers']
    if any(name not in set(source.provider) for name in names):
        return reply('One or more named providers are not in the current selection. Adjust team filters or choose listed providers.', 'refused')
    metric = metric_from_question(q)
    if context and not re.search(r'utilization|no[- ]show|visits|patients|revenue|unused', q):
        metric = {'completed_visits': 'visits'}.get(context['metric'], context['metric'])
        if metric not in METRICS:
            return reply('That remembered metric is not supported by this comparison. Specify utilization, no-show rate, visits or revenue.', 'limited')
    if 'collections' in q and not is_pair_request:
        return reply('Collections are not measured. The dataset contains revenue, which cannot be substituted for collections.', 'limited')
    scoped = source[source.provider.isin(names)] if names else source
    parsed = parse_date_range(q, today, *bounds) if not pair else None
    if pair and any(p['status'] in ('invalid', 'no_date_requested') for p in pair):
        return coverage_error(pair, bounds)
    if pair is None and parsed['status'] == 'invalid':
        return coverage_error([parsed], bounds)
    # New comparison routes are deliberately limited to measured operational
    # vocabulary. A date match must not turn an unsupported question into an answer.
    residual = ' '.join(p['remaining_question'] for p in pair) if pair else parsed['remaining_question']
    for name in names:
        residual = residual.replace(name.lower(), '')
        residual = re.sub(r'\b(?:dr\.?|doctor)\s+' + re.escape(name.split()[-1].lower()) + r'\b', '', residual)
    residual = re.sub(r"[’']s\b", '', residual)
    residual = re.sub(r'\bprovider\s*\d+\b', '', residual)
    allowed = set('compare comparison between and vs versus providers provider who which whose had has have the most highest lowest increased decreased dropped improving are is was were did in for from over during at by with utilization no show shows rate rates completed visits patients revenue per visit unused capacity performance this last previous period periods trend estimate impact does that how all our their them total summary on collections a an'.split())
    if set(re.findall(r"[a-z]+", residual)) - allowed:
        return reply('I cannot answer that comparison from the measured operational metrics. Ask about visits, utilization, no-show rates, revenue, revenue per visit, or unused capacity.', 'refused')
    # Prior-answer follow-ups use structured dates, never dates guessed from prose.
    if follow and context and pair is None:
        current = (context['start'], context['end'])
        if 'estimate revenue impact' in q:
            current_range = parse_date_range(f'from {current[0]} to {current[1]}', today, *bounds)
            error = coverage_error([current_range], bounds)
            if error:
                return error
            rows = dated_rows(scoped, *current)
            if rows.empty:
                return reply('No records remain for that provider and period.', 'unavailable')
            p = benchmark(rows, target)
            known = p.revenue_rate_known.all()
            text = (f'Modeled gross revenue opportunity: ${p.opportunity.sum():,.0f} at {target:.0%} utilization. '
                    'Formula: sum(max(0, target × capacity − visits) × provider revenue/visit). '
                    'This is not collections, profit, a forecast, or an estimate of causation.') if known else 'Revenue opportunity is unavailable without observed revenue per visit.'
            return reply(text, 'answered' if known else 'limited', [grounding_record(rows, *current)], context_for(names, 'revenue', *current))
        if parsed['status'] == 'no_date_requested':
            prior = previous_window(*current)
            pair = [parse_date_range(f'from {a} to {b}', today, *bounds) for a, b in (prior, current)]
        else:
            pair = [parse_date_range(f'from {current[0]} to {current[1]}', today, *bounds), parsed]
    if pair is None and trend:
        if parsed['status'] == 'no_date_requested':
            if df.empty:
                return reply('No data matches the current dashboard selection.', 'unavailable')
            windows = latest_month_windows(df.date.min().date(), df.date.max().date())
            # An undated query must not expand the dashboard's date selection.
            scoped = df[df.provider.isin(names)] if names else df
            trend_bounds = (df.date.min().date(), df.date.max().date())
            pair = [parse_date_range(f'from {a} to {b}', today, *trend_bounds) for a, b in windows]
            error = coverage_error(pair, trend_bounds)
            if error:
                error['text'] += ' Default trends require two complete calendar months within the selected window.'
                return error
        else:
            if parsed['status'] != 'ok':
                return coverage_error([parsed], bounds)
            current = parsed['requested_start'], parsed['requested_end']
            pair = [parse_date_range(f'from {a} to {b}', today, *bounds) for a, b in (previous_window(*current), current)]
    if pair:
        error = coverage_error(pair, bounds)
        if error:
            return error
        windows = [(p['effective_start'], p['effective_end']) for p in pair]
        if windows[0] == windows[1]:
            return reply('Those dates identify the same period. Choose a different comparison period.', 'limited')
        frames = [dated_rows(scoped, *window) for window in windows]
        if any(frame.empty for frame in frames):
            return reply('There are no selected provider-day records in one comparison period. No comparison was calculated.', 'unavailable')
        ids = set(frames[0].provider_id) & set(frames[1].provider_id)
        if names and any(not set(names).issubset(set(frame.provider)) for frame in frames):
            return reply('A requested provider has no records in one period. No comparison was calculated.', 'unavailable')
        if not ids:
            return reply('No providers have observations in both periods.', 'unavailable')
        excluded = (set(frames[0].provider_id) | set(frames[1].provider_id)) - ids
        frames = [frame[frame.provider_id.isin(ids)] for frame in frames]
        records = [grounding_record(frame, *window, label=label) for frame, window, label in zip(frames, windows, ('First period', 'Second period'))]
        intro = f'{format_range(*windows[0])} → {format_range(*windows[1])}. Same-provider comparison; {len(excluded)} providers excluded because one period has no observations. '
        if names:
            intro += 'Providers: ' + ', '.join(names) + '. '
        if trend and parsed and parsed['status'] == 'no_date_requested' and not context:
            intro += 'Default: latest two complete calendar months within selected date bounds. '
        if trend:
            before = {key: values(group)[metric] for key, group in frames[0].groupby('provider_id')}
            after = {key: values(group)[metric] for key, group in frames[1].groupby('provider_id')}
            labels = frames[1].drop_duplicates('provider_id').set_index('provider_id').provider
            rows = [(labels[key], before[key], after[key]) for key in sorted(ids)
                    if pd.notna(before[key]) and pd.notna(after[key])]
            unknown = len(ids) - len(rows)
            if re.search(r'dropped|decreased', q):
                rows = [r for r in rows if r[2] < r[1]]
                rows.sort(key=lambda r: (r[2]-r[1], r[0]))
            elif 'increased' in q or 'improving' in q:
                improving_down = 'improving' in q and metric in ('no_show_rate', 'unused_capacity')
                rows = [r for r in rows if (r[2] < r[1] if improving_down else r[2] > r[1])]
                rows.sort(key=lambda r: ((r[2]-r[1]) if improving_down else -(r[2]-r[1]), r[0]))
            else:
                rows.sort(key=lambda r: r[0])
            table = ['| Provider | First period | Second period | Change |', '| :--- | ---: | ---: | :--- |']
            table += [f'| {name} | {formatted(a, metric)} | {formatted(b, metric)} | {change_text(a,b,metric)} |' for name,a,b in rows]
            text = f'{METRICS[metric]} changes. ' + intro + '\n\n' + ('\n'.join(table) if rows else 'No providers match the requested direction of change.')
            text += f'\n\n{unknown} providers have undefined rates and are excluded from change rankings.'
        elif len(names) > 1:
            text = intro + '\n\n' + '\n\n'.join(
                '**' + name + '**\n\n' + comparison_table(
                    values(frames[0][frames[0].provider == name]),
                    values(frames[1][frames[1].provider == name])) for name in names)
        else:
            text = intro + '\n\n' + comparison_table(values(frames[0]), values(frames[1]))
        text += '\n\nChanges are descriptive, not causal. Period lengths, staffed days, and visit mix may differ; visits are not unique patients.'
        return reply(text, records=records, context=context_for(names, metric, *windows[1]))
    # Two named providers, one shared period.
    if len(names) != 2:
        return reply('Choose exactly two named providers for a side-by-side comparison.', 'limited')
    if parsed['status'] not in ('no_date_requested', 'ok'):
        return coverage_error([parsed], bounds)
    if parsed['status'] == 'ok':
        window = parsed['effective_start'], parsed['effective_end']
        rows = dated_rows(scoped, *window)
    else:
        rows = df[df.provider.isin(names)]
        window = (df.date.min().date(), df.date.max().date()) if not df.empty else (None, None)
    if rows.empty or not set(names).issubset(set(rows.provider)):
        return reply('A requested provider has no observations in this period.', 'unavailable')
    return reply(provider_table(rows, names) + '\n\nCollections are not measured; revenue is shown separately. '
                 'These operational metrics do not adjust for specialty or visit complexity and do not measure clinical quality.',
                 records=[grounding_record(rows, *window)], context=context_for(names, metric, *window))
