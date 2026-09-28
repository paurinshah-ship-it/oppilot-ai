"""Local conversational analytics. No chat text is transmitted to any service.

Supported intents select fixed analytical functions; all numeric answers are
rendered from Pandas calculations. Unsupported questions fail closed. This is
not a general-purpose language model and cannot infer causal explanations.
"""
import re
from datetime import date
from src.date_ranges import parse_date_range, format_range
from src.data import PROVIDER_NAMES
from src.workspace import workspace_response
from src.scenarios import scenarios_response
from src.semantic_query import semantic_response, EXAMPLES as SEMANTIC_QUESTIONS
from src.query_planner import planner_response
from src.investigations import investigation_response
from src.analytical_memory import attach_state, scope_key
from src.deep_analysis import DEEP_QUESTIONS, deep_answer, period_comparison
from src.analytics import benchmark, calculate_kpis, detect_opportunities
from src.comparative import (handle_comparison, grounding_record, grounding_text,
                             metric_from_question, context_for, dated_rows)

SUGGESTIONS = [
    'Which providers have the most unused capacity?',
    'Where is our largest revenue opportunity?',
    'Which provider should operations investigate?',
    'Summarize performance',
] + DEEP_QUESTIONS


COMPARISON_QUESTIONS = [
    'Compare July vs August 2025',
    'Compare Dr. Patel and Dr. Chen in August 2025',
    'Which providers are improving?',
    'Whose utilization dropped the most?',
    'Which no-show rates increased in August 2025?',
    'What is our utilization year to date?',
]


def _respond(question, df, target=.85, history=None, as_of=None, raw_df=None, data_bounds=None):
    """Return text, status, and explicit provider reference for safe follow-ups.

    Explicit dates filter raw_df before aggregation; undated queries use df. Ties are retained. History
    is used only for a previous explicit provider reference, never as evidence.
    """
    parsed = None
    grounding = 'Grounding: no metrics calculated'
    def result(text, status='answered', provider=None):
        # Successful answers stay unchanged. Unanswerable/partial requests
        # explain the limitation and offer supported, data-scoped alternatives.
        suggestions = []
        if status in ('refused', 'limited', 'unavailable', 'partially_available', 'invalid'):
            suggestions = ['Summarize performance',
                           'Which providers have the most unused capacity?',
                           'Which provider is most productive?']
            if re.search(r'revenue|profit|forecast|predict', q):
                suggestions = ['What is our revenue?',
                               'Where is our largest revenue opportunity?',
                               'How concentrated is our revenue opportunity?']
            elif re.search(r'why|cause|reason|provider|doctor|\bdr\b', q) and not df.empty:
                known = provider if provider in set(df.provider) else sorted(df.provider.unique())[0]
                suggestions = [f'What is {known} utilization?',
                               'Which providers have the highest no-show rates?',
                               'Is unused capacity mainly unbooked slots or no-shows?']
            introduction = ('After selecting a date range and team with available data, try:'
                            if df.empty else 'You can ask instead:')
            text += '\n\n' + introduction + '\n' + '\n'.join(f'- {item}' for item in suggestions)
        return {'text': text, 'status': status, 'provider': provider,
                'suggested_questions': suggestions, 'date_range': parsed, 'grounding': grounding}
    q = question.strip().lower().rstrip(".?! ")
    q = re.sub(r"\bdoctor\s+", "dr. ", q)
    if not q or len(q) > 1000:
        return result('Please ask a short question about the selected dashboard metrics.', 'refused')
    # Patient counts are aggregate operations data, not patient-level requests.
    # Keep other safety categories separate from patient-specific information.
    blocked_patterns = [
        r'ignore|invent|pretend|system prompt|api.key|diagnos|treat|medication|ssn|date of birth',
        r'\b(?:fire|fired|firing|terminate|terminated|terminating|termination)\b',
        r'\b(?:prescri\w*|dosage|dose|clinical advice)\b',
        r'\b(?:patient|patients)(?:[’\']s|[’\'])?\b.*\b(?:names?|identit\w*|identif\w*|records?|charts?|addresses|address|phone|email|dob|mrn|medical history|lab results|symptoms|condition|details|information)\b',
        r'\b(?:names?|identit\w*|identif\w*|records?|charts?|addresses|address|phone|email|dob|mrn|medical history|lab results|symptoms|condition|details|information)\b.*\bpatients?\b',
        r'\b(?:this|that|individual|specific|named)\s+patient\b',
        r'\bwho\b.*\bpatients?\b',
    ]
    if any(re.search(pattern, q) for pattern in blocked_patterns):
        if re.search(r'\b(?:fire|fired|firing|terminate|terminated|terminating|termination)\b', q):
            reason = 'Operational metrics cannot justify employment decisions. I cannot recommend firing or terminating someone.'
        elif re.search(r'diagnos|treat|medication|prescri|dosage|\bdose\b|clinical advice', q):
            reason = 'This dashboard contains operational metrics, not clinical evidence. I cannot provide clinical advice or patient-level clinical information.'
        elif re.search(r'ignore|invent|pretend|system prompt|api.key', q):
            reason = 'I cannot disclose secrets or provide fabricated figures; answers must come from the calculated dashboard data.'
        else:
            reason = 'I cannot provide patient information: this synthetic dataset contains aggregate provider-day records, not patient identities, records, or clinical details.'
        return result(reason, 'refused')
    # Coverage is measured against the loaded dataset, never the UI date window.
    source = df if raw_df is None else raw_df
    bounds = data_bounds or ((source.date.min().date(), source.date.max().date())
                             if not source.empty else (None, None))
    investigated = investigation_response(q, df, source, as_of or date.today(), bounds)
    if investigated is not None:
        return investigated
    planned = planner_response(q, df, source, target, history, as_of or date.today(), bounds)
    if planned is not None:
        return planned
    scenario_answer = scenarios_response(q, df, source, target, history, as_of or date.today(), bounds)
    if scenario_answer is not None:
        return scenario_answer
    semantic = semantic_response(q, df, source, target, as_of or date.today(), bounds)
    if semantic is not None:
        return semantic
    workspace_answer = workspace_response(q, df, source, target, history, as_of or date.today(), bounds)
    if workspace_answer is not None:
        return workspace_answer
    comparative = handle_comparison(q, df, source, target, history, as_of or date.today(), bounds)
    if comparative is not None:
        return comparative
    parsed = parse_date_range(q, as_of or date.today(), *bounds)
    status = parsed['status']
    if status == 'invalid':
        return result('I could not resolve one valid date range. Use Q2 2025, July 2026, or from 2026-07-01 to 2026-08-15.', 'invalid')
    if status in ('unavailable', 'partially_available'):
        requested = (format_range(parsed['requested_start'], parsed['requested_end'])
                     if parsed['requested_start'] else 'the available period')
        coverage = format_range(*bounds) if bounds[0] else 'no dated records'
        text = f"I can't answer that from the available data. You asked for {requested}, but the dataset covers {coverage}."
        if status == 'partially_available':
            text += ' This is partial coverage. I can analyze the available portion if you request its explicit start and end dates.'
        return result(text, status)
    if status == 'ok':
        # Filter provider-day rows BEFORE calculating any KPI or benchmark.
        df = source[source.date.dt.date.between(parsed['effective_start'], parsed['effective_end'])]
        q = parsed['remaining_question']
    if df.empty:
        return result('No data matches the current selection. Broaden the dashboard filters.',
                      'unavailable' if status == 'ok' else 'refused')
    if re.search(r'next|forecast|predict|previous|yesterday|20[0-9]{2}|quarter|month|week|today', q):
        return result('That date expression is not supported; forecasts are not supported. Use a calendar month, Q1–Q4, last/this year, last/this month, or an explicit date range.', 'refused')
    effective = ((parsed['effective_start'], parsed['effective_end']) if status == 'ok'
                 else (df.date.min().date(), df.date.max().date()))
    grounding = 'Grounding: provider-day metrics · ' + format_range(*effective)
    p = benchmark(df, target)
    mentions = re.findall(r'provider\s*(\d+)\b', q)
    matches = [name for name in sorted(set(PROVIDER_NAMES) | set(source.provider)) if
               re.search(r'\b' + re.escape(name.lower()) + r'\b', q) or
               re.search(r'\b(?:dr\.?|doctor)\s+' + re.escape(name.split()[-1].lower()) + r'\b', q)]
    matches += [PROVIDER_NAMES[int(number)-1] if 1 <= int(number) <= len(PROVIDER_NAMES)
                else f'Provider {int(number):02d}' for number in mentions]
    if len(set(matches)) > 1:
        return result('Ask about one provider at a time, or use the Provider comparisons tab.', 'refused')
    provider = matches[0] if matches else None
    if not provider and re.search(r'\bdr\.?\s|\bdoctor\s', q):
        return result('I cannot find that named doctor in the fictional provider roster. Choose an exact name from the dashboard; I will not infer an identity.', 'refused')
    if not provider and re.search(r'\b(their|them|that provider|they)\b', q):
        provider = next((m.get('provider') for m in reversed(history or []) if m.get('role') == 'assistant'), None)
        if not provider:
            return result('Which provider do you mean? Use a fictional name such as Dr. Maya Patel.', 'refused')
    if provider and provider not in set(p.provider):
        return result(f'{provider} is not in the current selection. Adjust the filters or choose a listed provider.', 'refused')
    scope = 'Selected period: ' + format_range(*effective) + '. '
    if parsed['label'] == 'last year':
        scope = f"Last year means calendar year {effective[0].year}. " + scope
    if status == 'ok' and (not q or re.fullmatch(
            r'(?:show |give me )?(?:(?:an? |the )?(?:entire |full )?year(?:ly)? )?(?:summary|comparison|comparisons|overview|performance)?', q)
            or re.fullmatch(r'compare (?:all )?providers,? clinics,? and specialties', q)):
        return result(scope + '\n\n' + period_comparison(df, target))
    causal = bool(re.search(r'\bwhy\b|cause|reason', q))
    if causal and not provider:
        return result('This dataset cannot establish causes. Specify a provider to inspect utilization, unbooked slots, and no-shows; demand and visit complexity are not measured.', 'refused')
    if provider:
        row = p[p.provider == provider].iloc[0]
        if not any(term in q for term in ['utilization', 'capacity', 'revenue', 'opportunity', 'productiv', 'visits', 'why', 'compare', 'benchmark', 'no-show', 'about', 'investigate']):
            return result('I cannot answer that from the available metrics. Ask about this provider’s utilization, visits, capacity, productivity, or revenue.', 'refused')
        text = (f'{provider}: {row.visits:,.0f} visits / {row.capacity:,.0f} staffed slots = {row.utilization:.1%} utilization; '
                f'{row.visits_per_hour:.2f} visits/staffed hour; ${row.revenue:,.0f} revenue. '
                f'Unused capacity: {row.unused_capacity:,.0f} = {row.unbooked_slots:,.0f} unbooked + {row.no_shows:,.0f} no-shows. '
                f'Selected specialty utilization: {row.peer_utilization:.1%} (includes self, {row.peer_count} providers); '
                f'gap: {row.utilization_gap_pp:+.1f} percentage points. '
                f'Modeled opportunity: ${row.opportunity:,.0f} at {target:.0%} utilization. ')
        if not row.revenue_rate_known:
            text += 'Revenue opportunity is unknown without observed revenue per visit; zero is only a placeholder. '
        if row.peer_count == 1:
            text += 'There are no other selected specialty peers, so this is a self-comparison. '
        if causal:
            text += 'These figures describe the arithmetic gap, not its cause. The data cannot establish why; review demand, scheduling, staffing, and visit complexity with operations.'
        return result(scope + text, 'limited' if causal else 'answered', provider)
    if causal:
        return result('The available data cannot establish causes.', 'refused')
    deeper = deep_answer(q, df, target)
    if deeper is not None:
        limited = 'needed' in deeper or 'undefined' in deeper
        return result(scope + deeper, 'limited' if limited else 'answered')
    if re.search(r'\b(most|highest|largest)\b', q) and re.search(r'\b(patients|visits)\b', q) and not re.search(r'\bper\b|\bhour\b|productiv', q):
        leaders = p[p.visits == p.visits.max()].sort_values('provider')
        text = '; '.join(f'{r.provider}: {r.visits:,.0f} completed visits' for r in leaders.itertuples())
        return result(scope + 'Highest completed-visit volume: ' + text +
                      '. Counts represent visits, not unique patients; the dataset cannot identify repeat patients.',
                      provider=leaders.iloc[0].provider if len(leaders) == 1 else None)
    if 'compare' in q and re.search(r'\b(visits|utilization)\b', q):
        metric = 'utilization' if 'utilization' in q else 'visits'
        ranked = p.sort_values([metric, 'provider'], ascending=[False, True])
        values = [f'{r.provider}: {r.utilization:.1%} utilization' if metric == 'utilization'
                  else f'{r.provider}: {r.visits:,.0f} completed visits' for r in ranked.itertuples()]
        return result(scope + 'Provider comparison: ' + '; '.join(values) + '.')
    if 'unused' in q or 'unbooked' in q:
        ranked = p.sort_values(['unused_capacity', 'provider'], ascending=[False, True])
        leaders = ranked[ranked.unused_capacity >= ranked.iloc[min(2, len(ranked)-1)].unused_capacity]
        text = '; '.join(f'{r.provider}: {r.unused_capacity:,.0f} unused slots ({r.unbooked_slots:,.0f} unbooked + {r.no_shows:,.0f} no-shows)' for r in leaders.itertuples())
        return result(scope + 'Highest unused capacity (top three positions, including ties): ' + text + '.', provider=leaders.iloc[0].provider if len(leaders) == 1 else None)
    if 'opportunity' in q or 'investigate' in q:
        flagged = detect_opportunities(p, target)
        if flagged.empty:
            return result(scope + 'No operational opportunity rules trigger for this selection.')
        maximum = flagged.opportunity.max()
        leaders = flagged[flagged.opportunity == maximum]
        text = '; '.join(f'{r.provider}: ${r.opportunity:,.0f}; {r.signals}' for r in leaders.itertuples())
        text = (f'Prioritize operational review by modeled revenue opportunity: {text}. '
                f'Total modeled opportunity: ${p.opportunity.sum():,.0f} at {target:.0%} utilization. '
                'Formula: sum(max(0, target × capacity − visits) × provider revenue/visit). '
                'Review scheduling demand, reminders, staffing, and visit complexity; flags do not establish causes or clinical quality. '
                'This is gross potential revenue, not guaranteed profit; zero-visit providers have unknown revenue rates.')
        return result(scope + text, provider=leaders.iloc[0].provider if len(leaders) == 1 else None)
    if 'productive' in q or 'productivity' in q:
        leaders = p[p.visits_per_hour == p.visits_per_hour.max()]
        return result(scope + 'Highest visits per staffed hour: ' + '; '.join(f'{r.provider}: {r.visits_per_hour:.2f}' for r in leaders.itertuples()) + '. Compare within specialty; visit complexity is not measured.', provider=leaders.iloc[0].provider if len(leaders) == 1 else None)
    if q in ['summarize performance', 'summary', 'summarize', 'how are we doing?'] or re.fullmatch(r'(what (is|are) (our|the) )?(visits|revenue|utilization|capacity)\??', q):
        k = calculate_kpis(df)
        return result(scope + f"{k['visits']:,} visits; {k['capacity']:,} slots; {k['utilization']:.1%} utilization; ${k['revenue']:,.0f} revenue; {k['productivity']:.2f} visits/staffed hour.")
    return result('I cannot answer that from these dashboard metrics. I can rank unused capacity, modeled revenue opportunity, and productivity, or describe a selected provider. I cannot infer clinical quality, causality, or missing facts.', 'refused')


def respond(question, df, target=.85, history=None, as_of=None, raw_df=None, data_bounds=None):
    """Shared text/voice entry point; attach factual provenance and follow-ups.

    Context is structured metadata (provider, metric, inclusive dates), never
    inferred from generated prose. Only the latest assistant turn supplies it.
    """
    response = _respond(question, df, target, history, as_of, raw_df, data_bounds)
    response.setdefault('grounding_details', [])
    response.setdefault('context', None)
    if not response.get('definition') and not response['grounding_details'] and response['grounding'] != 'Grounding: no metrics calculated':
        parsed = response.get('date_range') or {}
        if parsed.get('status') == 'ok':
            start, end = parsed['effective_start'], parsed['effective_end']
            source = df if raw_df is None else raw_df
            rows = dated_rows(source, start, end)
        else:
            rows = df
            start, end = rows.date.min().date(), rows.date.max().date()
        response['grounding_details'] = [grounding_record(rows, start, end)]
        response['grounding'] = grounding_text(response['grounding_details'])
        if response['status'] in ('answered', 'limited'):
            metric = metric_from_question(question.lower())
            provider = response.get('provider')
            if not provider and metric == 'no_show_rate' and 'highest' in question.lower():
                ranked = benchmark(rows, target)
                ranked = ranked[ranked.booked > 0]
                leaders = ranked[ranked.no_show_rate == ranked.no_show_rate.max()]
                if len(leaders) == 1:
                    provider = leaders.iloc[0].provider
                    response['provider'] = provider
            response['context'] = context_for([provider] if provider else [], metric, start, end)
    response['follow_ups'] = []
    context = response.get('context')
    if context and context['providers'] and response['status'] in ('answered', 'limited'):
        response['follow_ups'] = [
            {'label': 'Compare with previous period', 'question': 'Compare with previous period'},
            {'label': 'Estimate revenue impact', 'question': 'Estimate revenue impact'},
            {'label': 'Show provider trend', 'question': 'Show provider trend'},
        ]
    attach_state(response, scope_key(df, df if raw_df is None else raw_df, target))
    return response
