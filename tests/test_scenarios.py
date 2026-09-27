from pathlib import Path
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest
from src.scenarios import scenario_metrics, monthly_utilization_data, build_requested_chart
from src.conversation import respond
from src.voice import process_turn


@pytest.fixture
def data():
    return pd.DataFrame([
        dict(date=pd.Timestamp(day),provider_id='A',provider='Dr. Maya Patel',specialty='Primary Care',clinic='Demo',
             capacity=100,booked=80,visits=60,no_shows=20,revenue=15000,staffed_hours=8,fte=1)
        for day in ['2025-07-01','2025-07-31','2025-08-01','2025-08-31']])


def test_hand_calculated_scenarios(data):
    p=scenario_metrics(data,.85,.08).iloc[0]
    # 320 bookings; 80 missed visits. Recover 80 - .08*320 = 54.4 visits.
    assert p.no_show_additional_visits==pytest.approx(54.4)
    assert p.no_show_additional_revenue==pytest.approx(13600)
    assert p.utilization_additional_visits==100
    assert p.utilization_additional_revenue==25000
    assert p.no_show_additional_visits<=p.unused_capacity
    assert scenario_metrics(data,.4,.5).iloc[0].no_show_additional_visits==0
    assert scenario_metrics(data,.4,.5).iloc[0].utilization_additional_visits==0
    assert scenario_metrics(data,.85,.08,100).iloc[0].no_show_additional_revenue==pytest.approx(5440)


def test_unknown_rates_and_validation(data):
    zero=data.assign(visits=0,no_shows=80,revenue=0)
    assert scenario_metrics(zero).scenario_rate.isna().all()
    assert scenario_metrics(zero).no_show_additional_revenue.isna().all()
    assert scenario_metrics(zero,revenue_per_visit=0).no_show_additional_revenue.eq(0).all()
    for bad in [-.1,1.1,float('nan')]:
        with pytest.raises(ValueError):scenario_metrics(data,no_show_target=bad)
    with pytest.raises(ValueError):scenario_metrics(data,revenue_per_visit=float('inf'))


def test_chat_scenario_claimed_baseline_and_date_scope(data):
    question='What happens if Dr. Patel reduces no-shows from 14% to 8% in August 2025?'
    reply=respond(question,data[data.date.dt.month==7],raw_df=data)
    assert reply['status']=='answered'
    assert reply['scenario'][0]['no_show_additional_visits']==pytest.approx(27.2)
    assert 'observed no-show counts instead' in reply['text']
    assert '25.0%' in reply['text']
    assert reply['grounding_details'][0]['records']==2
    assert 'do not add' in reply['text']
    assumed=respond('What if Dr. Patel reduces no-shows to 8% in August 2025 assuming $100 per visit?',data)
    assert assumed['status']=='answered'
    assert assumed['scenario'][0]['no_show_additional_revenue']==pytest.approx(2720)


def test_scenario_rejections(data):
    assert respond('What if Dr. Garcia reduces no-shows to 8%?',data)['status']=='refused'
    assert respond('What if Dr. Patel reduces no-shows to 108%?',data)['status']=='invalid'
    assert respond('What if Dr. Patel reduces no-shows to 8% in August 2026?',data)['status']=='unavailable'
    assert respond('What if Dr. Patel reduces no-shows to 8% in Q3 2025?',data)['status']=='partially_available'
    assert respond('What if Dr. Patel reduces no-shows by 8%?',data)['status']=='invalid'
    assert respond('Chart patient names',data)['status']=='refused'
    assert respond('Chart profit by provider',data)['status']=='limited'


def test_weighted_monthly_chart_and_gaps(data):
    uneven=data.copy()
    uneven.loc[1,['visits','capacity']]=[9,10]
    monthly=monthly_utilization_data(uneven,pd.Timestamp('2025-07-01'),pd.Timestamp('2025-09-30'))
    assert monthly.iloc[0].utilization==pytest.approx(69/110)
    assert pd.isna(monthly.iloc[2].utilization)
    fig=build_requested_chart(uneven,'monthly_utilization',pd.Timestamp('2025-07-01'),pd.Timestamp('2025-09-30'))
    assert fig.data[0].connectgaps is False
    assert fig.data[0].y[0]==pytest.approx(69/110)


def test_chart_query_scoping_and_no_show_exclusions(data):
    answer=respond('Chart monthly utilization by provider in August 2025',data)
    assert answer['status']=='answered'
    assert len(answer['chart'].data[0].x)==1
    assert answer['grounding_details'][0]['records']==2
    unbooked=data.assign(provider_id='B',provider='Dr. Ethan Chen',booked=0,visits=0,no_shows=0,revenue=0)
    mixed=pd.concat([data,unbooked])
    ranked=respond('Show no-show rates from highest to lowest',mixed)
    assert ranked['status']=='answered'
    assert list(ranked['chart'].data[0].y)==['Dr. Maya Patel']
    assert '1 providers without bookings' in ranked['text']
    assert respond('Show no-show rates from highest to lowest',unbooked)['status']=='unavailable'
    assert respond('Chart monthly utilization by provider in 2026',data)['status']=='unavailable'
    _,voice=process_turn({'audio':'mock'},data,.85,[],transcriber=lambda _: 'Chart monthly utilization by provider')
    assert voice.get('chart') is not None


def test_ui_sliders_and_chart_chat():
    app=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=30).run()
    assert not app.exception
    assert any(t.label=='Scenarios' for t in app.tabs)
    baseline=[m.value for m in app.metric]
    dates=app.date_input[0].value
    next(s for s in app.slider if s.label=='Scenario target no-show rate (%)').set_value(0).run()
    next(c for c in app.checkbox if c.label=='Use an assumed revenue per visit').check().run()
    next(s for s in app.slider if s.label=='Assumed revenue per visit ($)').set_value(300).run()
    assert [m.value for m in app.metric]==baseline
    assert app.date_input[0].value==dates
    assert any('explicit assumption $300.00' in m.value for m in app.markdown)
    app.chat_input[0].set_value('Chart monthly utilization by provider in August 2025').run()
    assert not app.exception
    assert len(app.get('plotly_chart'))==7
    assert app.session_state.chat_history[-1]['status']=='answered'


def test_totals_keep_unknown_rates_explicit(data):
    from src.scenarios import scenario_totals
    zero=data.assign(provider_id='B',provider='Dr. Ethan Chen',visits=0,no_shows=80,revenue=0)
    totals=scenario_totals(scenario_metrics(pd.concat([data,zero])))
    assert totals.iloc[0]['Providers with unknown revenue rates']==1
    assert totals.iloc[0]['Modeled gross revenue (known rates only)']==pytest.approx(13600)
    all_unknown=scenario_totals(scenario_metrics(zero))
    assert all_unknown['Modeled gross revenue (known rates only)'].isna().all()
