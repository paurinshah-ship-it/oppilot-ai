from datetime import date
from pathlib import Path
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from src.conversation import respond
from src.workspace import (trend_snapshot, executive_summary, top_opportunities,
                           specialty_metrics, scorecard, investigation)


@pytest.fixture
def data():
    rows=[]
    for day in pd.date_range('2025-07-01','2025-08-31'):
        for ident,name,specialty,capacity,booked,visits in [
            ('A','Dr. Maya Patel','Primary Care',100,95 if day.month==7 else 90,76 if day.month==7 else 83),
            ('B','Dr. Ethan Chen','Cardiology',200,180,160 if day.month==7 else 150),
        ]:
            rows.append(dict(date=day,provider_id=ident,provider=name,specialty=specialty,clinic='Demo',fte=1,
                             capacity=capacity,booked=booked,visits=visits,no_shows=booked-visits,revenue=visits*250,staffed_hours=8))
    return pd.DataFrame(rows)


def test_executive_summary_matches_calculations(data):
    summary=executive_summary(data,.85)
    assert f'{data.visits.sum():,} completed visits / {data.capacity.sum():,} staffed slots' in summary
    assert 'No-show rates increased for 1 of 2 providers' in summary
    assert 'Largest modeled revenue opportunity: Dr. Ethan Chen: $232,500' in summary
    assert 'Jul 1, 2025–Jul 31, 2025' in summary
    assert 'Aug 1, 2025–Aug 31, 2025' in summary
    partial=executive_summary(data[data.date.dt.month==8],.85)
    assert 'Monthly changes are unavailable' in partial
    assert 'No-show rates increased' not in partial


def test_opportunities_units_ties_and_declines(data):
    opps=top_opportunities(data,.85)
    decline=opps[opps.Opportunity=='Biggest month-over-month decline'].iloc[0]
    assert decline.Provider=='Dr. Ethan Chen'
    assert decline.Impact=='-5.0 percentage points'
    tied=pd.concat([data, data[data.provider_id=='B'].assign(provider_id='C',provider='Dr. Test Tie')])
    opps=top_opportunities(tied,.85)
    assert set(opps[opps.Opportunity=='Biggest month-over-month decline'].Provider)=={'Dr. Ethan Chen','Dr. Test Tie'}
    unused=opps[opps.Opportunity=='Highest unused capacity']
    assert unused.Impact.str.endswith(' slots').all()


def test_investigation_checks_direction(data):
    snapshot=trend_snapshot(data)
    assert snapshot['status']=='ok'
    down=investigation('Dr. Ethan Chen',snapshot)
    assert 'utilization decreased, 80.0% → 75.0%' in down
    assert '| Completed visits | 4,960 | 4,650 | -310 |' in down
    assert 'Cancellations and appointment mix are not measured' in down
    up=investigation('Dr. Maya Patel',snapshot)
    assert 'A decrease is not supported' in up
    assert '+7.0 percentage points' in up


def test_why_query_filters_raw_rows_and_grounding(data):
    dashboard=data[data.date.dt.month==7]
    answer=respond("Why did Dr. Patel's utilization decrease in August 2025?",dashboard,raw_df=data)
    assert answer['status']=='limited'
    assert 'A decrease is not supported' in answer['text']
    assert len(answer['grounding_details'])==2
    assert all(r['records']==31 and r['providers']==1 for r in answer['grounding_details'])
    assert answer['provider']=='Dr. Maya Patel'
    unavailable=respond('Why did Dr. Patel utilization decrease this month?',data,as_of=date(2026,9,26))
    assert unavailable['status']=='unavailable'


def test_specialties_weighted_opportunity_and_queries(data):
    expected=specialty_metrics(data,.85).set_index('specialty')
    assert expected.loc['Cardiology','utilization']==.775
    assert expected.loc['Cardiology','opportunity']==232500
    compare=respond('Compare cardiology and primary care',data)
    assert compare['status']=='answered'
    assert 'Cardiology' in compare['text'] and 'Primary Care' in compare['text']
    leader=respond('Which specialty has the highest utilization?',data)
    assert 'Primary Care' in leader['text'] and '79.5%' in leader['text']
    opportunity=respond('Which specialty has the greatest revenue opportunity?',data)
    assert '$232,500' in opportunity['text']
    assert respond('Compare cardiology and oncology',data)['status']=='limited'
    assert respond('Compare cardiology and primary care',data[data.specialty=='Cardiology'])['status']=='unavailable'


def test_zero_rates_not_presented_as_measured_zeros(data):
    zero=data.assign(visits=0,revenue=0,booked=0,no_shows=0)
    specialties=specialty_metrics(zero,.85)
    assert specialties.no_show_rate.isna().all()
    assert specialties.opportunity.isna().all()
    card=scorecard(zero,'Dr. Maya Patel',.85).set_index('Metric').Value
    assert card['No-show rate']=='Unavailable (no bookings)'
    assert card['Collections']=='Not measured'
    assert card['Modeled revenue opportunity']=='Unknown revenue rate'
    summary=executive_summary(zero,.85)
    assert '2 providers have unknown revenue opportunity' in summary
    assert '0 of 0 providers with defined rates' in summary


@pytest.mark.parametrize('question,expected',[
    ('What does utilization mean?','completed visits / available staffed appointment slots'),
    ('How is revenue opportunity calculated?','max(0, target utilization × capacity'),
    ('Explain no-show rate','zero as a placeholder'),
    ('What does productivity mean?','completed visits / staffed hours'),
])
def test_formula_explanations_do_not_claim_data_grounding(data,question,expected):
    answer=respond(question,data.iloc[:0])
    assert answer['status']=='answered'
    assert expected in answer['text']
    assert answer['grounding_details']==[]
    assert 'implemented metric formulas' in answer['grounding']


def test_workspace_ui_selection_and_summary_invalidation():
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=30).run()
    assert not app.exception
    assert any(t.label=='Executive workspace' for t in app.tabs)
    next(b for b in app.button if b.label=='Generate Executive Summary').click().run()
    assert 'Overall utilization' in app.session_state.workspace_summary['text']
    prior_key=app.session_state.workspace_summary['key']
    next(s for s in app.selectbox if s.label=='Choose a provider for the scorecard').set_value('Dr. Maya Patel').run()
    assert not app.exception
    assert app.session_state.workspace_summary['key']==prior_key
    next(w for w in app.multiselect if w.label == "Select specialties").set_value(['Cardiology']).run()
    assert not app.exception
    assert any('Generate a new executive summary' in i.value for i in app.info)
    assert 'Dr. Maya Patel' not in next(s for s in app.selectbox if s.label=='Choose a provider for the scorecard').options
