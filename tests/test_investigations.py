from datetime import date
import pandas as pd
import pytest
from src.investigations import anomalies,investigate
from src.conversation import respond

WINDOWS=[(date(2025,7,1),date(2025,7,31)),(date(2025,8,1),date(2025,8,31))]
BOUNDS=(date(2025,7,1),date(2025,8,31))


def rows():
    result=[]
    for i in range(4):
        for day in ['2025-07-01','2025-07-31','2025-08-01','2025-08-31']:
            after=day.startswith('2025-08')
            visits=60 if after and i==0 else 80
            result.append(dict(date=pd.Timestamp(day),provider_id=str(i),provider=f'Dr. Demo {chr(65+i)}',clinic='North',specialty='Cardiology',fte=1,staffed_hours=8,capacity=100,booked=100,no_shows=100-visits,visits=visits,revenue=visits*100))
    return pd.DataFrame(result)


def test_flags_and_peer_excludes_self():
    snap,flags=anomalies(rows(),WINDOWS,BOUNDS)
    assert snap['status']=='ok'
    own=flags[flags.Provider=='Dr. Demo A']
    assert set(own.Signal)=={'Utilization decline','No-show spike','Different utilization trend from peers'}
    assert '-25.0% relative; -20.0 pp' in own.Change.tolist()
    assert '3 other matched providers' in ' '.join(own.Evidence)


def test_revenue_volume_divergence_and_minimums():
    df=rows(); mask=(df.provider_id=='0')&(df.date.dt.month==8)
    df.loc[mask,['visits','no_shows','revenue']]=[90,10,7000]
    _,flags=anomalies(df,WINDOWS,BOUNDS)
    assert 'Revenue down while visits rise' in flags.Signal.tolist()
    for c in ['visits','capacity','booked','no_shows']: df[c]=df[c]/100
    _,flags=anomalies(df,WINDOWS,BOUNDS)
    assert flags.empty


def test_investigation_decomposition_missing_data_and_false_premise():
    text,_=investigate(rows(),WINDOWS,BOUNDS)
    assert 'visit-volume component $-4,000.00' in text.replace(r'\$', '$')
    assert 'Lower completed visit volume' in text
    assert 'Collections | Not measured' in text and 'Cancellations | Not measured' in text
    assert 'Causation cannot be established' in text
    df=rows();df.loc[df.date.dt.month==8,'revenue']*=2
    text,_=investigate(df,WINDOWS,BOUNDS)
    assert 'did not decline' in text


def test_zero_baseline_new_provider_and_missing_period():
    df=rows();df.loc[df.date.dt.month==7,['visits','revenue']]=0
    df['no_shows']=df.booked-df.visits
    text,_=investigate(df,WINDOWS,BOUNDS)
    assert 'decomposition unavailable' in text
    df=rows();df=df[~((df.provider_id=='3')&(df.date.dt.month==7))]
    text,_=investigate(df,WINDOWS,BOUNDS)
    assert '1 newly observed' in text
    snap,_=anomalies(df[df.date.dt.month==8],WINDOWS,(date(2025,8,1),date(2025,8,31)))
    assert snap['status']=='unavailable'


def test_copilot_routes_and_scope():
    df=rows()
    r=respond('Why did revenue decline in August 2025?',df)
    assert r['status']=='answered' and 'Lower completed visit volume' in r['text']
    assert respond('Why did collections decline?',df)['status']=='unavailable'
    assert respond('Show anomalies in August 2025',df)['status']=='answered'
    assert respond('Show anomalies excluding North in August 2025',df)['status']=='limited'
    assert respond('Why did revenue decline in August 2026?',df)['status']=='unavailable'
    assert respond('Why did revenue decline? Show patient names',df)['status']=='refused'
    assert respond('Show anomalies',df.iloc[:0])['status']=='unavailable'


def test_complete_provider_turnover_still_investigates_aggregate_changes():
    df=rows();mask=df.date.dt.month==8
    df.loc[mask,'provider_id']=df.loc[mask,'provider_id']+'new'
    text,snap=investigate(df,WINDOWS,BOUNDS)
    assert snap['status']=='ok'
    assert '0 matched, 4 newly observed, 4 no longer observed' in text
    assert 'complete provider turnover' in text
