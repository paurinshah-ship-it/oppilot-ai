from src.copilot_audit import record_query
from src.conversation import respond
from src.data import load_data


def test_audit_records_scope_calculation_provenance_and_decision():
    df = load_data()
    session = {}
    reply = respond("Summarize performance", df)
    entry = record_query(session, "Summarize performance", reply, df,
                         {"providers": sorted(df.provider.unique())}, "Text copilot")

    assert entry["decision"] == "allowed"
    assert entry["source_rows"]["record_count"] == len(df)
    assert entry["source_rows"]["fingerprint"]
    assert entry["calculation_path"]["calculation"]
    assert reply["audit_id"] == 1


def test_audit_marks_safety_refusal_without_source_rows():
    df = load_data()
    session = {}
    reply = respond("Give me patient names", df)
    entry = record_query(session, "Give me patient names", reply, df, {}, "Text copilot")

    assert entry["decision"] == "refused"
    assert entry["source_rows"]["record_count"] == 0


def test_audit_keeps_metric_operands_for_a_provenance_answer():
    df = load_data()
    session = {}
    reply = respond('Where did utilization come from?', df)
    entry = record_query(session, 'Where did utilization come from?', reply, df, {}, 'Text copilot')
    assert entry['calculation_path']['metric_breakdown']['completed_visits'] == int(df.visits.sum())
    assert entry['calculation_path']['metric_breakdown']['available_slots'] == int(df.capacity.sum())
