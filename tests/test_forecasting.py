from datetime import date
import math
import pandas as pd
import pytest
from src.forecasting import forecast_month


def sample():
    dates = pd.bdate_range('2025-01-01','2025-03-31')
    df = pd.DataFrame({'date':dates,'visits':1.,'capacity':2.})
    for month,total in [(1,100),(2,200),(3,300)]:
        mask = df.date.dt.month == month
        df.loc[mask,'visits'] = total/mask.sum()
        df.loc[mask,'capacity'] = 2*total/mask.sum()
    return df


def test_mean_and_intervals():
    r=forecast_month(sample(),months=3,today=date(2025,4,15))
    assert r['forecast']==pytest.approx(200)
    assert r['month']==pd.Timestamp('2025-04-01')
    assert r['confidence_interval'][1]==pytest.approx(200+4.303*100/math.sqrt(3))
    assert r['prediction_interval'][1]>r['confidence_interval'][1]
    assert r['prediction_interval'][0]==0


def test_weighted_utilization_and_unavailable():
    r=forecast_month(sample(),'utilization',3,today=date(2025,4,15))
    assert r['forecast']==pytest.approx(.5)
    assert forecast_month(sample(),'collections')['status']=='unavailable'
    assert forecast_month(sample().iloc[1:],months=3)['status']=='unavailable'
    assert forecast_month(sample(),months=3,today=date(2025,3,15))['status']=='unavailable'
    assert forecast_month(sample().iloc[:0],months=3)['status']=='unavailable'


def test_ui_forecast():
    from pathlib import Path
    from streamlit.testing.v1 import AppTest
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=40).run()
    next(b for b in app.button if b.label=='Calculate forecast').click().run()
    assert not app.exception
    assert any('Forecast for January 2026' in h.value for h in app.subheader)
