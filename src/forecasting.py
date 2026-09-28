"""Simple monthly mean forecasts; no changes to observed metric definitions."""
from datetime import date
import math
import pandas as pd

# Two-sided 95% Student-t critical values for df=2..11 (3..12 observations).
T95 = {2:4.303, 3:3.182, 4:2.776, 5:2.571, 6:2.447, 7:2.365,
       8:2.306, 9:2.262, 10:2.228, 11:2.201}


def forecast_month(df, metric='visits', months=6, today=None):
    """Mean of last n contiguous complete observed months (3 <= n <= 12).

    Visits = monthly sum(visits). Utilization = sum(visits)/sum(capacity).
    Forecast = mean(monthly observations). Sample SD uses ddof=1.
    Mean confidence interval = mean +/- t(.975,n-1)*SD/sqrt(n).
    Next-observation prediction interval = mean +/- t*SD*sqrt(1+1/n).
    Bounds clipped to >=0 and utilization <=1. Assumes independent, stationary,
    approximately normal monthly observations; intervals are not calibrated.
    Coverage uses observed weekdays, not a verified staffing roster.
    """
    if metric not in ('visits', 'utilization'):
        return {'status':'unavailable', 'message':'Collections are not measured. Revenue is not a substitute for collections.'}
    if months not in range(3,13):
        raise ValueError('Use 3–12 months.')
    if df.empty:
        return {'status':'unavailable','message':'No observed data in the selected filters.'}
    today = pd.Timestamp(today or date.today())
    data = df[df.date < today.to_period('M').start_time].copy()
    rows = []
    for period, group in data.groupby(data.date.dt.to_period('M')):
        expected = pd.bdate_range(period.start_time, period.end_time)
        if not set(expected).issubset(set(group.date.dt.normalize())):
            continue
        capacity = group.capacity.sum()
        if metric == 'utilization' and capacity <= 0:
            continue
        rows.append({'month':period.start_time, 'observed':float(group.visits.sum() if metric == 'visits' else group.visits.sum()/capacity)})
    history = pd.DataFrame(rows, columns=['month','observed']).tail(months)
    if len(history) < months or len(pd.period_range(history.month.min(), history.month.max(), freq='M')) != months:
        return {'status':'unavailable','message':f'Select at least {months} consecutive complete observed months. Partial months and months with missing weekdays are excluded.'}
    values = history.observed
    estimate = float(values.mean())
    sd = float(values.std(ddof=1))
    t = T95[months-1]
    def bounds(width):
        return (max(0., estimate-width), min(1., estimate+width) if metric == 'utilization' else estimate+width)
    return {'status':'ok','metric':metric,'history':history,'forecast':estimate,
            'month':history.month.max()+pd.offsets.MonthBegin(1),
            'confidence_interval':bounds(t*sd/math.sqrt(months)),
            'prediction_interval':bounds(t*sd*math.sqrt(1+1/months)),
            'message':'Forecast is for the month after the latest complete training month, not necessarily next month from today.'}
