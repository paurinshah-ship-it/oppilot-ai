from pathlib import Path
import pandas as pd
from streamlit.testing.v1 import AppTest
from src.data import generate_data
from src.analytics import benchmark, answer

def test_synthetic_invariants():
    df = generate_data()
    pd.testing.assert_frame_equal(df, generate_data())
    assert len(df.provider.unique()) == 48
    assert (df.visits + df.no_shows == df.booked).all()
    assert (df.booked <= df.capacity).all()
    assert (df.revenue >= 0).all()

def test_weighted_metrics_and_opportunity():
    df = pd.DataFrame([
        dict(provider_id="A", provider="A", specialty="X", clinic="Y", visits=5, capacity=10, booked=8, revenue=500, staffed_hours=4),
        dict(provider_id="A", provider="A", specialty="X", clinic="Y", visits=15, capacity=30, booked=20, revenue=1500, staffed_hours=8)])
    p = benchmark(df, .8)
    assert p.iloc[0].utilization == .5
    assert p.iloc[0].opportunity == 1200
    assert p.iloc[0].unused_capacity == 20
    assert benchmark(df, .5).opportunity.sum() == 0
    assert "$1,200" in answer("opportunity", p, .8)

def test_app_and_empty_filters():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run(timeout=30)
    assert not app.exception
    assert len(app.metric) == 7
    assert next(w for w in app.selectbox if w.label == "Reporting period").value == "Latest calendar year"
    assert [tab.label for tab in app.tabs][:2] == ["Overview", "Ask copilot"]
    next(w for w in app.multiselect if w.label == "Select specialties").set_value([]).run()
    assert not app.exception
    assert any("No data" in message.value for message in app.info)

def test_filters_target_and_chat():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run(timeout=30)
    next(w for w in app.multiselect if w.label == "Select specialties").set_value(["Cardiology"])
    next(w for w in app.slider if w.label == "Target utilization (%)").set_value(90).run()
    app.chat_input[0].set_value("Where is the largest opportunity?").run()
    assert not app.exception
    assert "90%" in app.chat_message[1].markdown[0].value

def test_kpis_are_weighted_and_empty_safe():
    from src.analytics import calculate_kpis
    df = pd.DataFrame({"visits": [10, 9], "capacity": [100, 10],
                       "revenue": [1000, 900], "staffed_hours": [20, 3]})
    k = calculate_kpis(df)
    assert k["visits"] == 19
    assert k["capacity"] == 110
    assert k["utilization"] == 19 / 110
    assert k["productivity"] == 19 / 23
    assert k["revenue"] == 1900
    assert k["unused_capacity"] == 91
    assert calculate_kpis(df.iloc[:0])["utilization"] == 0


def test_csv_validation(tmp_path):
    import pytest
    from src.data import load_data
    valid = generate_data().head(3)
    path = tmp_path / "sample.csv"
    valid.to_csv(path, index=False)
    assert len(load_data(path)) == 3
    for column, bad_value in [("capacity", -1), ("revenue", float("inf")),
                              ("visits", 1.5), ("date", "invalid"), ("staffed_hours", 0)]:
        bad = valid.astype(object).copy()
        bad.loc[bad.index[0], column] = bad_value
        bad.to_csv(path, index=False)
        with pytest.raises(ValueError):
            load_data(path)
    pd.concat([valid, valid]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Duplicate"):
        load_data(path)


def test_pipeline_reconciles_and_summary_prompt():
    from src.data import load_data
    from src.analytics import calculate_kpis, monthly_performance
    from src.charts import visits_chart, revenue_chart
    df = load_data()
    k = calculate_kpis(df)
    monthly = monthly_performance(df)
    assert monthly.visits.sum() == k["visits"]
    assert monthly.capacity.sum() == k["capacity"]
    assert len(visits_chart(monthly).data) == 2
    assert len(revenue_chart(monthly).data) == 1
    assert "completed visits" in answer("Summarize performance", benchmark(df), .85)


def test_zero_revenue_does_not_imply_target_met():
    from src.data import validate_data
    from src.insights import executive_insights
    df = generate_data().head(1)
    df["visits"] = 0
    df["no_shows"] = df.booked
    df["revenue"] = 0
    df = validate_data(df)
    messages = executive_insights(df, benchmark(df), .85)
    assert not any("All selected providers meet" in message for message in messages)
    assert any("cannot be estimated" in message for message in messages)

def test_comparison_charts_match_provider_metrics():
    from src.data import load_data
    from src.analytics import monthly_performance
    from src.charts import productivity_chart, provider_revenue_chart, utilization_chart, utilization_trend_chart
    df = load_data()
    providers = benchmark(df)
    for figure, metric in [(productivity_chart(providers), "visits_per_hour"),
                           (provider_revenue_chart(providers), "revenue"),
                           (utilization_chart(providers, .9), "utilization")]:
        plotted = {name: value for trace in figure.data for name, value in zip(trace.y, trace.x)}
        assert plotted == dict(zip(providers.provider, providers[metric]))
    monthly = monthly_performance(df)
    trend = utilization_trend_chart(monthly, .9)
    assert list(trend.data[0].y) == list(monthly.visits / monthly.capacity)
    assert trend.layout.shapes[0].y0 == .9


def test_provider_selection_updates_cards_and_comparisons():
    from src.data import load_data
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    next(w for w in app.multiselect if w.label == "Select providers").set_value(["Dr. Maya Patel"]).run()
    df = load_data()
    expected = df[(df.provider == "Dr. Maya Patel") & (df.date.dt.year == df.date.dt.year.max())].visits.sum()
    assert app.metric[0].value == f"{expected:,}"
    assert len(app.get("plotly_chart")) == 6
    assert not app.exception
    next(w for w in app.multiselect if w.label == "Select specialties").set_value(["Cardiology"]).run()
    options = next(w for w in app.multiselect if w.label == "Select providers").options
    assert "Dr. Maya Patel" not in options
    assert "Dr. Ethan Chen" in options
    assert not app.exception

def test_five_year_window():
    df = generate_data()
    dates = pd.to_datetime(df.date)
    assert dates.min() == pd.Timestamp("2021-01-01")
    assert dates.max() == pd.Timestamp("2025-12-31")
    assert (dates.max() - dates.min()).days + 1 == 1826
    assert df.specialty.nunique() == 12
    assert df.provider.nunique() == 48
    assert df.provider.str.startswith("Dr. ").all()
    assert (dates.dt.dayofweek < 5).all()


def test_advanced_metrics_hand_calculation():
    import pytest
    from src.analytics import detect_opportunities
    df = pd.DataFrame([
        dict(provider_id="A", provider="A", specialty="X", clinic="Y", visits=60, capacity=100, booked=80, revenue=6000, staffed_hours=40),
        dict(provider_id="B", provider="B", specialty="X", clinic="Y", visits=90, capacity=100, booked=100, revenue=9000, staffed_hours=30)])
    p = benchmark(df, .85).set_index("provider")
    a = p.loc["A"]
    assert a.unused_capacity == 40
    assert a.unbooked_slots == 20
    assert a.no_shows == 20
    assert a.no_show_rate == .25
    assert a.booking_rate == .8
    assert a.revenue_per_visit == 100
    assert a.recoverable_visits == 25
    assert a.opportunity == 2500
    assert p.loc["B"].opportunity == 0
    assert a.peer_utilization == .75
    assert a.peer_productivity == pytest.approx(150 / 70)
    assert a.productivity_index == pytest.approx(.7)
    assert a.utilization_gap_pp == pytest.approx(-15)
    signals = detect_opportunities(p.reset_index(), .85).set_index("provider").loc["A"].signals
    assert "Below utilization target" in signals
    assert "Unbooked slots" in signals
    assert "No-shows" in signals
    assert "below specialty" in signals


def test_date_filter_is_inclusive():
    from src.data import load_data
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    day = pd.Timestamp("2025-02-03").date()
    app.date_input[0].set_value((day, day)).run()
    df = load_data()
    expected = df[df.date == pd.Timestamp(day)].visits.sum()
    assert app.metric[0].value == f"{expected:,}"
    assert not app.exception
