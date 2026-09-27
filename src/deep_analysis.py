"""Longitudinal and operational analyses from filtered records only."""
import pandas as pd
from src.analytics import benchmark

DEEP_QUESTIONS = [
    'How has performance changed year over year?',
    'Which providers improved utilization the most?',
    'Which providers had the largest utilization decline?',
    'Which specialties have the largest revenue opportunity?',
    'Which clinics have the lowest utilization?',
    'Which providers have the highest no-show rates?',
    'Is unused capacity mainly unbooked slots or no-shows?',
    'How concentrated is our revenue opportunity?',
    'Which providers are furthest below specialty peers?',
    'What if utilization reached 90%?',
]


def annual_summary(df):
    """Weighted annual totals, marking partial years from observed coverage.

    utilization = sum(visits)/sum(capacity); productivity = visits/staffed_hours.
    A complete observed year spans its first through last weekday. Date filters
    that omit boundary staffed days conservatively produce a partial-year label.
    """
    out = df.assign(year=df.date.dt.year).groupby('year').agg(
        visits=('visits', 'sum'), capacity=('capacity', 'sum'), revenue=('revenue', 'sum'),
        staffed_hours=('staffed_hours', 'sum'), start=('date', 'min'), end=('date', 'max'))
    out['utilization'] = out.visits / out.capacity
    out['productivity'] = out.visits / out.staffed_hours
    out['complete'] = [row.start <= pd.bdate_range(f'{year}-01-01', f'{year}-12-31')[0]
                       and row.end >= pd.bdate_range(f'{year}-01-01', f'{year}-12-31')[-1]
                       for year, row in out.iterrows()]
    return out


def deep_answer(q, df, target):
    """Return a grounded reply or None if the deeper intent is unsupported.

    Changes in utilization are percentage points; revenue growth is relative to
    the prior year's revenue. Provider change uses the same provider IDs in both
    complete consecutive years. Opportunity concentration = top-5 sum / total.
    """
    p = benchmark(df, target)
    if 'year over year' in q or 'improved utilization' in q or 'utilization decline' in q:
        annual = annual_summary(df)
        complete = annual[annual.complete]
        pairs = [(year - 1, year) for year in complete.index if year - 1 in complete.index]
        if not pairs:
            return 'At least two complete consecutive calendar years in the selection are needed. Broaden the date filter; partial years are not compared.'
        first, last = pairs[-1]
        if 'year over year' in q:
            lines = []
            for before, after in pairs:
                a, b = annual.loc[before], annual.loc[after]
                growth = f'{100*(b.revenue/a.revenue-1):+.1f}%' if a.revenue else 'undefined (zero baseline)'
                lines.append(f'{before}→{after}: visits {a.visits:,.0f}→{b.visits:,.0f}; utilization {a.utilization:.1%}→{b.utilization:.1%} ({100*(b.utilization-a.utilization):+.1f} pp); revenue ${a.revenue:,.0f}→${b.revenue:,.0f} ({growth})')
            return '\n'.join(lines) + '\nOnly complete consecutive years shown. Nominal revenue changes include volume and revenue-per-visit effects; causation is not established.'
        before = benchmark(df[df.date.dt.year == first]).set_index('provider_id')
        after = benchmark(df[df.date.dt.year == last]).set_index('provider_id')
        joined = after[['provider', 'utilization']].join(before.utilization.rename('prior'), how='inner')
        joined['change_pp'] = 100 * (joined.utilization - joined.prior)
        declining = 'decline' in q
        ranked = joined[joined.change_pp < 0] if declining else joined[joined.change_pp > 0]
        ranked = ranked.sort_values('change_pp', ascending=declining)
        if ranked.empty:
            return f'No providers {"declined" if declining else "improved"} in utilization from {first} to {last}.'
        cutoff = ranked.iloc[min(4, len(ranked)-1)].change_pp
        leaders = ranked[ranked.change_pp <= cutoff] if declining else ranked[ranked.change_pp >= cutoff]
        return f'{first}→{last}, same providers, top five positions including ties: ' + '; '.join(f'{r.provider}: {r.prior:.1%}→{r.utilization:.1%} ({r.change_pp:+.1f} pp)' for r in leaders.itertuples()) + '. Differences are descriptive, not causal; staffed days and case mix may differ.'
    if 'specialt' in q and 'opportunity' in q:
        grouped = p.groupby('specialty').opportunity.sum().sort_values(ascending=False)
        return 'Specialty opportunity (sum of provider-level estimates): ' + '; '.join(f'{name}: ${value:,.0f}' for name, value in grouped.items()) + f'. Target {target:.0%}; gross scenario over the selected period, not guaranteed revenue.'
    if 'clinic' in q and 'utilization' in q:
        clinics = df.groupby('clinic')[['visits', 'capacity']].sum()
        rates = (clinics.visits / clinics.capacity).sort_values()
        return 'Clinic utilization, lowest first (total visits / staffed slots): ' + '; '.join(f'{name}: {value:.1%}' for name, value in rates.items()) + '. Specialty mix and staffing differ; this is not clinical quality.'
    if 'highest' in q and ('no-show' in q or 'no show' in q):
        ranked = p[p.booked > 0].sort_values('no_show_rate', ascending=False)
        if ranked.empty:
            return 'No bookings are available to calculate no-show rates.'
        cutoff = ranked.iloc[min(4, len(ranked)-1)].no_show_rate
        ranked = ranked[ranked.no_show_rate >= cutoff]
        return 'Highest no-show rates, top five positions including ties: ' + '; '.join(f'{r.provider}: {r.no_show_rate:.1%} ({r.no_shows:,.0f}/{r.booked:,.0f} booked)' for r in ranked.itertuples()) + '. Descriptive rates only; review reminders and access barriers without assuming causes.'
    if 'mainly' in q or 'breakdown' in q or 'decompos' in q:
        unused = p.unused_capacity.sum()
        if unused == 0:
            return 'There is no unused capacity in this selection.'
        unbooked, missed = p.unbooked_slots.sum(), p.no_shows.sum()
        return f'Unused slots: {unused:,.0f} = {unbooked:,.0f} unbooked ({unbooked/unused:.1%}) + {missed:,.0f} no-shows ({missed/unused:.1%}). These are accounting components, not explanations of underlying causes.'
    if 'concentrat' in q and 'opportunity' in q:
        total = p.opportunity.sum()
        if total == 0:
            return 'No modeled revenue opportunity; concentration is undefined.'
        top = p.sort_values(['opportunity', 'provider_id'], ascending=[False, True]).head(5)
        return f'Top {len(top)} providers account for {top.opportunity.sum()/total:.1%} of modeled opportunity (${top.opportunity.sum():,.0f} / ${total:,.0f}). Ties are ordered by provider ID. Gross scenario, not guaranteed profit.'
    if 'below' in q and ('peers' in q or 'benchmark' in q):
        ranked = p[(p.peer_count > 1) & (p.utilization_gap_pp < 0)].sort_values('utilization_gap_pp')
        if ranked.empty:
            return 'No providers are below a selected specialty benchmark with at least two members.'
        cutoff = ranked.iloc[min(4, len(ranked)-1)].utilization_gap_pp
        return 'Largest gaps to weighted selected specialty peers (includes self): ' + '; '.join(f'{r.provider}: {r.utilization_gap_pp:+.1f} pp' for r in ranked[ranked.utilization_gap_pp <= cutoff].itertuples()) + '. Top five positions including ties; not a quality ranking.'
    if q.strip(' ?') == 'what if utilization reached 90%':
        scenario = benchmark(df, .90)
        return f'At a 90% target: {scenario.recoverable_visits.sum():,.1f} expected additional visits and ${scenario.opportunity.sum():,.0f} modeled gross opportunity. Current {target:.0%} scenario: ${p.opportunity.sum():,.0f}. Each provider contributes max(0, target × slots − visits) × observed revenue/visit. Demand, staffing, costs, and zero-visit rate uncertainty remain; the dashboard target has not changed.'
    return None


def period_comparison(df, target):
    """Compare all selected entities using raw-row sums and weighted ratios.

    Utilization = visits / capacity; productivity = visits / staffed hours.
    Group opportunity is the sum of provider-level opportunities, never an
    opportunity calculated from a pooled group revenue rate.
    """
    providers = benchmark(df, target)
    totals = df[['visits', 'capacity', 'revenue', 'staffed_hours']].sum()
    sections = [f"{totals.visits:,.0f} completed visits; {totals.capacity:,.0f} slots; "
                f"{totals.visits / totals.capacity:.1%} utilization; ${totals.revenue:,.0f} revenue. "
                'Comparisons include the selected providers, clinics, and specialties.']
    for key, title in [('provider', 'Providers'), ('clinic', 'Clinics'), ('specialty', 'Specialties')]:
        rows = df.groupby(key)[['visits', 'capacity', 'revenue', 'staffed_hours']].sum()
        if key == 'provider':
            opportunities = providers.set_index('provider').opportunity
        else:
            opportunities = providers.groupby(key).opportunity.sum()
        rows['opportunity'] = opportunities
        rows['utilization'] = rows.visits / rows.capacity
        rows['productivity'] = rows.visits / rows.staffed_hours
        rows = rows.sort_values(['visits'], ascending=False, kind='stable')
        lines = [f'**{title}**',
                 '| Name | Visits | Capacity | Utilization | Visits/hour | Revenue | Opportunity |',
                 '| :--- | ---: | ---: | ---: | ---: | ---: | ---: |']
        for name, row in rows.iterrows():
            lines.append(f'| {name} | {row.visits:,.0f} | {row.capacity:,.0f} | {row.utilization:.1%} | '
                         f'{row.productivity:.2f} | ${row.revenue:,.0f} | ${row.opportunity:,.0f} |')
        sections.append('\n'.join(lines))
    sections.append(f'Opportunity is modeled gross revenue at {target:.0%} utilization, not guaranteed profit. '
                    'Zero-visit providers have unknown revenue rates. Visits are not unique patients. '
                    'Operational comparisons do not measure clinical quality or adjust for visit complexity.')
    return '\n\n'.join(sections)
