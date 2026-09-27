from datetime import date
import math
import pandas as pd
import pytest
from src.semantic_metrics import metric_value, execute_metrics
from src.semantic_query import interpret_query
from src.conversation import respond


def rows():
    return pd.DataFrame([
        dict(date=pd.Timestamp('2025-07-01'),provider_id='A',provider='Dr. Demo Alpha',clinic='North',specialty='Care',visits=8,capacity=10,booked=10,no_shows=2,revenue=800,staffed_hours=4),
        dict(date=pd.Timestamp('2025-07-31'),provider_id='B',provider='Dr. Demo Beta',clinic='North',specialty='Care',visits=18,capacity=30,booked=20,no_shows=2,revenue=3600,staffed_hours=8),
        dict(date=pd.Timestamp('2025-08-31'),provider_id='A',provider='Dr. Demo Alpha',clinic='South',specialty='Care',visits=9,capacity=10,booked=10,no_shows=1,revenue=900,staffed_hours=4),
    ])


def test_weighted_catalog_and_provider_opportunity():
    df=rows().iloc[:2]
    assert metric_value(df,'completed_visits')==26
    assert metric_value(df,'utilization')==pytest.approx(.65)
    assert metric_value(df,'no_show_rate')==pytest.approx(4/30)
    assert metric_value(df,'revenue_opportunity',.85)==pytest.approx(50+1500)
    assert math.isnan(metric_value(df,'collections'))
    d=execute_metrics(df,['completed_visits','utilization','revenue_opportunity'],['clinic'])
    assert d.iloc[0].revenue_opportunity==1550
    assert d.iloc[0].utilization==.65


def test_undefined_and_allowlist():
    df=rows().iloc[:1].copy();df['visits']=0;df['booked']=0;df['no_shows']=0
    assert math.isnan(metric_value(df,'no_show_rate'))
    assert math.isnan(metric_value(df,'revenue_opportunity'))
    with pytest.raises(ValueError): execute_metrics(df,['invented'],[])
    with pytest.raises(ValueError): execute_metrics(df,['revenue'],['patient'])


def test_compositional_plan_and_date_before_aggregation():
    df=rows()
    q='Show completed visits and utilization by clinic in July 2025'
    plan=interpret_query(q,date(2026,9,27),(date(2025,7,1),date(2025,8,31)),list(df.provider.unique()))
    assert plan['error'] is None
    assert set(plan['metrics'])=={'completed_visits','utilization'}
    assert plan['dimensions']==['clinic']
    answer=respond(q,df.iloc[2:],raw_df=df)
    assert answer['status']=='answered'
    assert answer['semantic_data'][0]['completed_visits']==26
    assert answer['grounding_details'][0]['records']==2
    current=respond('Show completed visits by clinic',df.iloc[2:],raw_df=df)
    assert current['semantic_data'][0]['completed_visits']==9
    assert list(df.clinic)==['North','North','South']


@pytest.mark.parametrize('question,status',[
    ('Show collections by clinic','unavailable'),
    ('Show revenue by age','limited'),
    ('Show revenue by clinic excluding North','limited'),
    ('Show revenue by clinic in 2020','unavailable'),
    ('Show revenue by clinic in Q3 2025','partially_available'),
    ('Show patient names by clinic','refused'),
    ('Show medication dosage by clinic','refused'),
    ('Which provider should we fire by clinic?','refused'),
])
def test_fail_closed(question,status):
    assert respond(question,rows())['status']==status


def test_dimensions_ranking_and_alias_priority():
    answer=respond('Show revenue per visit by specialty and month',rows())
    assert answer['status']=='answered'
    assert answer['query_plan']['metrics']==['revenue_per_visit']
    assert len(answer['semantic_data'])==2
    answer=respond('Show highest utilization by provider',rows())
    assert answer['status']=='answered'
    assert answer['semantic_data'][0]['provider']=='Dr. Demo Alpha'
    answer=respond('Show completed_visits for Dr. Alpha',rows())
    assert answer['status']=='answered'
    assert answer['semantic_data'][0]['completed_visits']==17
