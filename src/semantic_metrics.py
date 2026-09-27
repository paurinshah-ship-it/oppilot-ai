"""Allowlisted semantic catalog and Pandas execution; no SQL/eval or model calls.

A metric defines its source measures, formula, unit, aliases and availability.
Ratios divide summed measures. Undefined denominators remain unavailable.
"""
from dataclasses import dataclass
import pandas as pd

@dataclass(frozen=True)
class Metric:
    label: str
    aliases: tuple[str, ...]
    columns: tuple[str, ...]
    operation: str
    formula: str
    unit: str = 'count'
    available: bool = True

METRICS = {
    'completed_visits': Metric('Completed visits', ('completed visits','visits','patient count','patients'), ('visits',), 'sum', 'sum(visits); appointments, not unique patients'),
    'capacity': Metric('Capacity', ('appointment capacity','capacity','available slots'), ('capacity',), 'sum', 'sum(capacity)'),
    'utilization': Metric('Utilization', ('utilization',), ('visits','capacity'), 'ratio', 'sum(visits) / sum(capacity)', 'percent'),
    'no_show_rate': Metric('No-show rate', ('no-show rate','no show rate','no-show rates','no show rates'), ('no_shows','booked'), 'ratio', 'sum(no_shows) / sum(booked)', 'percent'),
    'revenue': Metric('Revenue', ('revenue',), ('revenue',), 'sum', 'sum(revenue)', 'currency'),
    'collections': Metric('Collections', ('collections',), ('collections',), 'sum', 'Not measured by the provider-day contract; never substitute revenue', 'currency', False),
    'revenue_per_visit': Metric('Revenue per visit', ('revenue per visit',), ('revenue','visits'), 'ratio', 'sum(revenue) / sum(visits)', 'currency'),
    'productivity': Metric('Productivity', ('productivity','visits per staffed hour','visits per hour'), ('visits','staffed_hours'), 'ratio', 'sum(visits) / sum(staffed_hours)', 'decimal'),
    'unused_capacity': Metric('Unused capacity', ('unused capacity','unused slots'), ('capacity','visits'), 'difference', 'sum(capacity) - sum(visits)'),
    'revenue_opportunity': Metric('Revenue opportunity', ('revenue opportunity','estimated revenue opportunity'), ('provider_id','visits','capacity','revenue'), 'provider_opportunity', 'sum per provider: max(0, target * sum(capacity) - sum(visits)) * sum(revenue) / sum(visits); unknown if any provider has zero visits', 'currency'),
}
DIMENSIONS = {'provider': ('provider_id','provider'), 'clinic': ('clinic',),
              'specialty': ('specialty',), 'month': ('month',)}


def metric_value(df, key, target=.85):
    """Execute a catalog operation. Unknown opportunity rates are not zero."""
    if key not in METRICS or not 0 <= target <= 1:
        raise ValueError('Unknown metric or invalid utilization target.')
    m = METRICS[key]
    if not m.available or any(c not in df.columns for c in m.columns) or df.empty:
        return float('nan')
    if df[list(m.columns)].isna().any().any():
        return float('nan')
    if m.operation == 'provider_opportunity':
        p = df.groupby('provider_id')[['visits','capacity','revenue']].sum()
        if p.visits.eq(0).any():
            return float('nan')
        return float(((target*p.capacity-p.visits).clip(lower=0)*p.revenue/p.visits).sum())
    totals = [df[c].sum() for c in m.columns]
    if m.operation == 'sum':
        return float(totals[0])
    if m.operation == 'ratio':
        return float(totals[0]/totals[1]) if totals[1] else float('nan')
    if m.operation == 'difference':
        return float(totals[0]-totals[1])
    raise ValueError('Unsupported metric operation.')


def execute_metrics(df, metrics, dimensions=(), target=.85):
    """Aggregate raw rows at requested grain; no averaging precomputed ratios."""
    if not metrics or any(m not in METRICS for m in metrics):
        raise ValueError('Choose metrics from the semantic catalog.')
    if any(d not in DIMENSIONS for d in dimensions) or len(set(dimensions)) != len(dimensions):
        raise ValueError('Choose unique dimensions from the semantic catalog.')
    rows = df.copy()
    if 'month' in dimensions:
        rows['month'] = rows.date.dt.strftime('%Y-%m')
    columns = list(dict.fromkeys(c for d in dimensions for c in DIMENSIONS[d]))
    groups = rows.groupby(columns, dropna=False, sort=True) if columns else [((), rows)]
    result = []
    for values, group in groups:
        values = values if isinstance(values, tuple) else (values,)
        row = dict(zip(columns, values))
        row.update({key: metric_value(group, key, target) for key in metrics})
        result.append(row)
    return pd.DataFrame(result, columns=columns+list(metrics))


def format_metric(value, key):
    if pd.isna(value):
        return 'Unavailable'
    unit = METRICS[key].unit
    if unit == 'percent': return f'{value:.1%}'
    if unit == 'currency': return f'${value:,.2f}'
    if unit == 'decimal': return f'{value:.2f}'
    return f'{value:,.0f}'


def catalog_records():
    return [{'Metric': k, 'Label': m.label, 'Formula': m.formula, 'Unit': m.unit,
             'Availability': 'Measured / calculated' if m.available else 'Not measured'} for k,m in METRICS.items()]
