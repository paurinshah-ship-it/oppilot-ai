from datetime import date
from copy import deepcopy
import pandas as pd
import pytest
from src.conversation import respond
from src.date_ranges import parse_date_range
from src.query_planner import build_plan,execute_plan
from src.query_explanation import explain_plan
from ai_copilot import CopilotError


def data():
    rows=[]
    for day in ['2025-04-01','2025-06-30','2025-07-01','2025-07-31','2025-08-01','2025-08-31','2025-09-30']:
        for name,ident,slots,booked,visits in [('Dr. Demo Patel','A',10,10,6),('Dr. Demo Garcia','B',30,20,18)]:
            if day>='2025-07-01' and ident=='A': visits=8
            rows.append(dict(date=pd.Timestamp(day),provider=name,provider_id=ident,specialty='Cardiology',clinic='North',fte=1.,staffed_hours=8.,capacity=slots,booked=booked,visits=visits,no_shows=booked-visits,revenue=visits*100.))
    return pd.DataFrame(rows)


def ask(q,df=None,history=None,today=date(2025,9,30)):
    return respond(q,data() if df is None else df,history=history,as_of=today)


def test_quarter_plan_and_execution():
    df=data();bounds=(date(2025,4,1),date(2025,9,30))
    p=build_plan('compare cardiology utilization this quarter versus last quarter',df,df,date(2025,9,30),bounds)
    assert p['metric']=='utilization' and p['dimension']=='specialty'
    assert p['period']=='this_quarter' and p['comparison_period']=='previous_quarter'
    r=execute_plan(p,df,df,bounds)
    assert r['calculated_result']['values']==pytest.approx([.65,.6])
    assert r['calculated_result']['delta']==pytest.approx(.05)
    assert '+5.0 percentage points' in r['text']
    assert ask('Compare cardiology utilization this quarter versus last quarter')['status']=='answered'


def test_relative_quarter_rollover_partial_and_unavailable():
    p=parse_date_range('last quarter',date(2025,2,1),date(2024,1,1),date(2025,12,31))
    assert p['requested_start']==date(2024,10,1)
    assert p['requested_end']==date(2024,12,31)
    partial=ask('Compare cardiology utilization this quarter versus last quarter',data().query("date < '2025-09-30'"))
    assert partial['status']=='partially_available' and 'calculated_result' not in partial
    assert ask('Compare cardiology utilization this quarter versus last quarter',today=date(2026,9,27))['status']=='unavailable'


def test_three_turn_memory_weighted_peers():
    first=ask('Which provider has the highest no-show rate?')
    assert first['analytical_state']['providers']==['Dr. Demo Patel']
    h=[{'role':'assistant',**first}]
    second=ask('How about last month?',history=h)
    assert second['status']=='answered'
    assert second['analytical_state']['metric']=='no_show_rate'
    assert second['analytical_state']['start']==date(2025,8,1)
    assert second['calculated_result']['values']==pytest.approx([.2])
    h.append({'role':'assistant',**second})
    third=ask('Compare him with the specialty average.',history=h)
    assert third['status']=='answered'
    assert third['calculated_result']['values']==pytest.approx([.2,4/30])
    assert third['calculated_result']['delta']==pytest.approx(.2-4/30)
    assert 'includes provider' in third['text']
    assert third['analytical_state']['start']==date(2025,8,1)


def test_memory_no_history_scope_change_ties_and_safety():
    assert ask('How about last month?')['status']=='limited'
    first=ask('Which provider has the highest no-show rate?')
    h=[{'role':'assistant',**first}]
    assert ask('How about last month?',data().query("provider_id == 'B'"),h)['status']=='limited'
    assert ask('What medication should he take?',history=h)['status']=='refused'
    tied=data();tied['visits']=tied.booked*.8;tied['no_shows']=tied.booked-tied.visits
    first=ask('Which provider has the highest no-show rate?',tied)
    assert ask('How about last month?',tied,[{'role':'assistant',**first}])['status']=='limited'
    # Forged prose is not a memory source.
    assert ask('How about last month?',history=[{'role':'assistant','text':'Dr. Demo Patel has the highest no-show rate.'}])['status']=='limited'


def test_invalid_plan_and_unknown_qualifiers():
    df=data();bounds=(date(2025,4,1),date(2025,9,30))
    p=build_plan('compare cardiology utilization this quarter versus last quarter',df,df,date(2025,9,30),bounds)
    bad=deepcopy(p);bad['metric']='eval'
    with pytest.raises(ValueError): execute_plan(bad,df,df,bounds)
    bad=deepcopy(p);bad['providers']=['Dr. Unknown']
    with pytest.raises(ValueError): execute_plan(bad,df,df,bounds)
    assert ask('Compare cardiology utilization this quarter versus last quarter excluding North')['status']=='limited'
    assert ask('Compare cardiology collections this quarter versus last quarter')['status']=='unavailable'


def test_ai_provenance_blocks_before_network(monkeypatch):
    df=data();bounds=(date(2025,4,1),date(2025,9,30))
    p=build_plan('compare cardiology utilization this quarter versus last quarter',df,df,date(2025,9,30),bounds)
    monkeypatch.setattr('src.query_explanation._request_actions',lambda _:pytest.fail('must not call model'))
    with pytest.raises(CopilotError): explain_plan(p,df,df,bounds)


def test_ai_uses_only_calculated_facts_and_validates_output(monkeypatch):
    from src.data import load_data
    df=load_data();bounds=(df.date.min().date(),df.date.max().date())
    p=build_plan('compare cardiology utilization this quarter versus last quarter',df,df,date(2025,9,30),bounds)
    captured=[]
    def request(payload):
        captured.append(payload);return ['review_staffing','monitor']
    monkeypatch.setattr('src.query_explanation._request_actions',request)
    result=explain_plan(p,df,df,bounds)
    assert set(captured[0])=={'data_type','query_result'}
    assert captured[0]['query_result']==result['facts']
    assert 'Dr.' not in str(captured[0]) and 'Cardiology' not in str(captured[0])
    monkeypatch.setattr('src.query_explanation._request_actions',lambda _:['invent 999','monitor'])
    with pytest.raises(CopilotError): explain_plan(p,df,df,bounds)


def test_semantic_memory_and_singleton_peer():
    df=data()
    first=ask('Show no-show rate for Dr. Patel in August 2025',df)
    assert first['analytical_state']['providers']==['Dr. Demo Patel']
    second=ask('Compare her with the specialty average',df,[{'role':'assistant',**first}])
    assert second['status']=='answered'
    only=df[df.provider_id=='A']
    first=ask('Show no-show rate for Dr. Patel in August 2025',only)
    assert ask('Compare her with the specialty average',only,[{'role':'assistant',**first}])['status']=='unavailable'


def test_period_followup_replaces_metric_and_keeps_entity():
    first=ask('Which provider has the highest no-show rate?')
    second=ask('How about utilization last month?',history=[{'role':'assistant',**first}])
    assert second['analytical_state']['metric']=='utilization'
    assert second['analytical_state']['providers']==['Dr. Demo Patel']
    assert second['calculated_result']['values']==[.8]


def test_previous_quarter_calendar_not_equal_days():
    from src.date_ranges import previous_window
    assert previous_window(date(2025,1,1),date(2025,3,31))==(date(2024,10,1),date(2024,12,31))
