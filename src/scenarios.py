"""Deterministic, period-specific scenarios and a fixed chart-request grammar."""
import math
import re
import pandas as pd
import plotly.express as px
from src.analytics import benchmark
from src.charts import polish
from src.data import PROVIDER_NAMES
from src.comparative import reply, resolve_providers, dated_rows, grounding_record, context_for, coverage_error
from src.date_ranges import parse_date_range, format_range


SCENARIO_QUESTIONS = [
    'What if Dr. Patel reduces no-shows to 2% in August 2025?',
    'What if Dr. Patel reduces no-shows to 2% in August 2025 assuming $250 per visit?',
    'Chart monthly utilization by provider in 2025',
    'Show no-show rates from highest to lowest in August 2025',
]


def scenario_totals(p):
    """Sum each independent scenario across providers; unknown rates stay explicit."""
    rows=[]
    for kind,label in [('no_show','No-show recovery'),('utilization','Utilization recovery')]:
        revenue=p[kind+'_additional_revenue'].sum(min_count=1)
        rows.append({'Scenario':label,'Estimated additional visits':float(p[kind+'_additional_visits'].sum()),
                     'Modeled gross revenue (known rates only)':None if pd.isna(revenue) else float(revenue),
                     'Providers with unknown revenue rates':int(p.scenario_rate.isna().sum())})
    return pd.DataFrame(rows)


def scenario_metrics(df, utilization_target=.85, no_show_target=.08, revenue_per_visit=None):
    """Independent scenarios; never sum their opportunities.

    No-show recovery = min(unused slots, max(0, missed − target × booked)).
    Utilization recovery = min(unused slots, max(0, target × capacity − visits)).
    Revenue = recovered visits × observed provider revenue/visit, or an explicit
    common assumed rate. With zero visits the observed rate is unknown (NaN).
    Bookings and staffed capacity remain fixed. Fractional visits are estimates
    over exactly the supplied rows, not an implied monthly/run-rate forecast.
    """
    if not all(math.isfinite(v) and 0 <= v <= 1 for v in (utilization_target,no_show_target)):
        raise ValueError('Targets must be finite rates between 0 and 1.')
    if revenue_per_visit is not None and (not math.isfinite(revenue_per_visit) or revenue_per_visit < 0):
        raise ValueError('Assumed revenue per visit must be finite and nonnegative.')
    p=benchmark(df,utilization_target)
    p['observed_no_show_rate']=p.no_shows/p.booked.where(p.booked != 0)
    p['scenario_rate']=p.revenue_per_visit.where(p.revenue_rate_known) if revenue_per_visit is None else float(revenue_per_visit)
    p['no_show_additional_visits']=(p.no_shows-no_show_target*p.booked).clip(lower=0).clip(upper=p.unused_capacity)
    p['utilization_additional_visits']=(utilization_target*p.capacity-p.visits).clip(lower=0).clip(upper=p.unused_capacity)
    for kind in ('no_show','utilization'):
        p[kind+'_additional_revenue']=p[kind+'_additional_visits']*p.scenario_rate
    return p


def scenario_text(p, utilization_target, no_show_target, assumed_rate=None):
    lines=[f'**Estimates for this analysis period** · utilization target {utilization_target:.1%}; no-show target {no_show_target:.1%}.',
           'Revenue per visit: '+(f'explicit assumption ${assumed_rate:,.2f}.' if assumed_rate is not None else 'observed separately for each provider; zero-visit rates are unknown.'),
           '| Provider | Current no-show rate | No-show recovery: visits | No-show recovery: revenue | Utilization recovery: visits | Utilization recovery: revenue |',
           '| :--- | ---: | ---: | ---: | ---: | ---: |']
    money=lambda v: 'Unknown rate' if pd.isna(v) else f'${v:,.2f}'
    for r in p.sort_values('provider').itertuples():
        current='Unavailable (no bookings)' if pd.isna(r.observed_no_show_rate) else f'{r.observed_no_show_rate:.1%}'
        lines.append(f'| {r.provider} | {current} | {r.no_show_additional_visits:,.1f} | {money(r.no_show_additional_revenue)} | {r.utilization_additional_visits:,.1f} | {money(r.utilization_additional_revenue)} |')
    lines.append('\nThese scenarios overlap: do not add their visits or revenue. Bookings and capacity are held fixed. Additional visits require demand and operational feasibility. Revenue is gross potential, not collections, profit, or a forecast. Fractional visits are expected values; no monthly extrapolation is made.')
    return '\n\n'.join(lines[:2])+'\n\n'+'\n'.join(lines[2:])


def monthly_utilization_data(df,start,end):
    """Sum visits/capacity per provider-month; retain missing months as NaN gaps."""
    monthly=df.assign(month=df.date.dt.to_period('M').dt.to_timestamp()).groupby(['provider','month'])[['visits','capacity']].sum()
    months=pd.date_range(pd.Timestamp(start).replace(day=1),pd.Timestamp(end).replace(day=1),freq='MS')
    grid=pd.MultiIndex.from_product([sorted(df.provider.unique()),months],names=['provider','month'])
    monthly=monthly.reindex(grid).reset_index()
    monthly['utilization']=monthly.visits/monthly.capacity.where(monthly.capacity != 0)
    return monthly


def build_requested_chart(df,kind,start,end):
    if kind=='monthly_utilization':
        monthly=monthly_utilization_data(df,start,end)
        fig=px.line(monthly,x='month',y='utilization',color='provider',markers=True,
                    labels={'month':'Month','utilization':'Completed visits / staffed slots','provider':'Provider'})
        fig.update_traces(connectgaps=False)
        fig.update_yaxes(tickformat='.0%')
        fig=polish(fig,460)
        fig.update_layout(legend=dict(orientation='v',y=1,x=1.02))
    elif kind=='no_show_ranking':
        p=benchmark(df)
        p=p[p.booked>0].sort_values(['no_show_rate','provider'],ascending=[False,True])
        fig=px.bar(p,x='no_show_rate',y='provider',orientation='h',
                   labels={'no_show_rate':'No-shows / booked appointments','provider':'Provider'})
        fig.update_yaxes(categoryorder='array',categoryarray=p.provider.tolist(),autorange='reversed')
        fig.update_xaxes(tickformat='.0%')
        fig=polish(fig,max(350,25*len(p)+100))
    else:
        raise ValueError('Unsupported chart kind')
    fig.update_layout(title=f'{"Monthly utilization" if kind=="monthly_utilization" else "No-show rates, highest to lowest"} · {format_range(start,end)}')
    return fig


def scenarios_response(q,df,source,target,history,today,bounds):
    """Only whitelisted scenarios/charts; called after the shared safety check."""
    scenario=bool(re.search(r'no[- ]shows?',q) and re.search(r'what (?:if|happens)|reduc|target|scenario|simulat',q))
    chart=bool(re.search(r'\b(chart|plot|graph)\b',q) or re.search(r'^show no[- ]show rates? from highest to lowest',q))
    if not (scenario or chart):
        return None
    names,error=resolve_providers(q,sorted(set(PROVIDER_NAMES)|set(source.provider)))
    if error:
        return reply(error,'refused')
    if names and not set(names).issubset(set(source.provider)):
        return reply('A requested provider is not in the current team selection.','unavailable')
    percentages=list(re.finditer(r'(-?\d+(?:\.\d+)?)\s*%',q))
    assumption=re.search(r'(?:at|assuming|using)\s+\$(\d+(?:\.\d+)?)\s*(?:per visit|/visit|revenue per visit)',q)
    # Remove scenario numerals before date parsing; they are not date expressions.
    date_query=re.sub(r'-?\d+(?:\.\d+)?\s*%','',q) if scenario else q
    if assumption:
        date_query=date_query.replace(assumption[0],'')
    parsed=parse_date_range(date_query,today,*bounds)
    if parsed['status'] not in ('ok','no_date_requested'):
        return coverage_error([parsed],bounds)
    rows=dated_rows(source,parsed['effective_start'],parsed['effective_end']) if parsed['status']=='ok' else df
    if names:
        rows=rows[rows.provider.isin(names)]
    if rows.empty or names and not set(names).issubset(set(rows.provider)):
        return reply('No selected records exist for a requested provider or period.','unavailable')
    window=(parsed['effective_start'],parsed['effective_end']) if parsed['status']=='ok' else (rows.date.min().date(),rows.date.max().date())
    residual=parsed['remaining_question']
    for name in names:
        residual=residual.replace(name.lower(),'')
        residual=re.sub(r'\b(?:dr\.?|doctor)\s+'+re.escape(name.split()[-1].lower())+r'\b','',residual)
    residual=re.sub(r"[’']s\b|\bprovider\s*\d+\b",'',residual)
    if chart:
        allowed=set('chart plot graph show monthly utilization by provider providers no show shows rate rates from highest to lowest in for the our'.split())
        if set(re.findall(r'[a-z]+',residual))-allowed:
            return reply('Supported charts: monthly utilization by provider, or no-show rates from highest to lowest.','limited')
        kind='monthly_utilization' if 'monthly' in q and 'utilization' in q else 'no_show_ranking' if re.search(r'no[- ]show',q) else None
        if not kind:
            return reply('Choose monthly utilization by provider or no-show rates from highest to lowest.','limited')
        if kind=='no_show_ranking' and rows.booked.sum()==0:
            return reply('No bookings are available; no-show rates are undefined and no chart was calculated.','unavailable')
        text=('Monthly utilization uses summed visits / summed staffed slots within each provider-month. Missing months remain gaps. Boundary months include only dates in the requested period.' if kind=='monthly_utilization'
              else f'Providers are ordered by no-shows / bookings, highest first. {int((benchmark(rows).booked==0).sum())} providers without bookings are excluded; their rates are undefined.')
        answer=reply(text,records=[grounding_record(rows,*window)],context=context_for(names,'utilization' if kind=='monthly_utilization' else 'no_show_rate',*window))
        answer['chart']=build_requested_chart(rows,kind,*window)
        return answer
    allowed=set('what happens if reduce reduces reducing no show shows rate rates from to target scenario simulate in for the our by provider'.split())
    if set(re.findall(r'[a-z]+',residual))-allowed or not 1<=len(percentages)<=2:
        return reply('Specify a no-show target, for example: What if Dr. Patel reduces no-shows to 8% in August 2025? Optionally add assuming $250 per visit.','limited')
    rates=[float(m[1])/100 for m in percentages]
    if any(not 0<=r<=1 for r in rates) or not re.search(r'(?:to|target)\s*-?\d+(?:\.\d+)?\s*%',q):
        return reply('Use a target no-show rate between 0% and 100%, such as “to 8%”.','invalid')
    if len(rates)==2 and not re.search(r'from\s*-?\d+(?:\.\d+)?\s*%\s+to\s*-?\d+(?:\.\d+)?\s*%',q):
        return reply('Use “from X% to Y%” for a claimed starting rate and a target.','invalid')
    assumed=float(assumption[1]) if assumption else None
    if assumed is not None and not math.isfinite(assumed):
        return reply('Assumed revenue per visit must be finite and nonnegative.','invalid')
    p=scenario_metrics(rows,target,rates[-1],assumed)
    text=scenario_text(p,target,rates[-1],assumed)
    if len(rates)==2:
        text=f'You supplied a starting rate of {rates[0]:.1%}. Calculations use observed no-show counts instead; each observed rate is shown below.\n\n'+text
    answer=reply(text,records=[grounding_record(rows,*window)],context=context_for(names,'no_show_rate',*window))
    answer['scenario']=p.to_dict('records')
    return answer
