from io import BytesIO
from pathlib import Path
import pandas as pd
import pytest
from pypdf import PdfReader
from src.data import generate_data, validate_data
from src.data_reporting import (read_upload, suggest_mapping, mapping_suggestions, project_columns,
                                quality_checks, activate_upload, schema_profile, schema_change, COLUMNS)
from src.reporting import performance_report
from src.analytics import calculate_kpis
from streamlit.testing.v1 import AppTest


def fixture():
    return validate_data(generate_data(start='2025-07-01',days=62)).query("provider_id == 'SYN-001'").copy()


def test_mapping_and_transaction():
    df=fixture()
    raw=df.rename(columns={'provider':'physician','visits':'appts_completed'})
    raw['private_notes']='discard me'
    mapping=suggest_mapping(raw.columns)
    state={}
    activated=activate_upload(state,raw,mapping,True)
    assert set(activated.columns)==set(COLUMNS)
    assert calculate_kpis(activated)==calculate_kpis(df)
    previous=state['uploaded_data']
    raw.loc[raw.index[0],'revenue']=-1
    with pytest.raises(ValueError): activate_upload(state,raw,mapping,True)
    assert state['uploaded_data'] is previous
    with pytest.raises(ValueError): activate_upload(state,df,suggest_mapping(df.columns),False)
    assert state['uploaded_data'] is previous


def test_ambiguous_and_semantic_mapping():
    assert suggest_mapping(['provider','physician'])['provider'] is None
    assert suggest_mapping(['collections','cancellations'])['revenue'] is None
    assert suggest_mapping(['collections','cancellations'])['no_shows'] is None
    mapping=suggest_mapping(COLUMNS); mapping['visits']='booked'
    with pytest.raises(ValueError): project_columns(fixture(),mapping)
    with pytest.raises(ValueError): read_upload(b'date,provider\n')


def test_healthcare_operations_column_recognition_requires_confirmation():
    details = mapping_suggestions(['physician_name', 'visits_complete', 'net_revenue'])
    assert details['provider']['source_column'] == 'physician_name'
    assert details['provider']['target_label'] == 'Provider'
    assert details['visits']['source_column'] == 'visits_complete'
    assert details['visits']['target_label'] == 'Completed visits'
    assert details['revenue']['source_column'] == 'net_revenue'
    assert details['revenue']['target_label'] == 'Realized revenue / collections'
    # Similar-looking cancellations are intentionally never converted to no-shows.
    assert mapping_suggestions(['cancellations'])['no_shows']['source_column'] is None


def test_quality_errors_and_gaps():
    df=fixture().iloc[:3].copy()
    df.loc[df.index[0],'revenue']=None
    df.loc[df.index[1],'visits']=999
    df.loc[df.index[1],'revenue']=-1
    df.loc[df.index[2],'staffed_hours']=-1
    df=pd.concat([df,df.iloc[:1]])
    checks=quality_checks(df).set_index('Check')
    for name in ['Required values','Duplicate provider/date rows','Negative / infinite values',
                 'Negative realized revenue / collections', 'Completed visits above capacity',
                 'Utilization over 100%','Appointment counts']:
        assert checks.loc[name,'Status']=='Error'
    df=fixture(); df=df[df.date != df.date.iloc[4]]
    checks=quality_checks(df).set_index('Check')
    assert checks.loc['Potential missing provider-day records','Status']=='Review'
    assert 'not proven missing' in checks.loc['Potential missing provider-day records','Detail']


def test_schema_change_is_detected_without_retaining_raw_values():
    previous = schema_profile(pd.DataFrame(columns=['physician_name', 'visits_complete']))
    current = schema_profile(pd.DataFrame(columns=['physician_name', 'net_revenue']))
    notice = schema_change(previous, current)
    assert 'schema changed' in notice.lower()
    assert 'added: net_revenue' in notice
    assert 'removed: visits_complete' in notice


def test_report_grounded_and_complete(tmp_path):
    df=fixture()
    pdf=performance_report(df,.85,('2025-07-01','2025-08-31'),'Test aggregate')
    reader=PdfReader(BytesIO(pdf))
    text='\n'.join(page.extract_text() for page in reader.pages)
    for expected in ['Provider Performance Report','Test aggregate','2025-07-01','2025-08-31','Monthly trends','Metric formulas','Dr. Maya Patel','Data quality',f'{df.visits.sum():,}']:
        assert expected in text
    assert 'Dr. Ethan Chen' not in text
    assert len(reader.pages)>=4


def test_uploaded_app_and_restore():
    app=AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py',default_timeout=40)
    df=fixture()
    df['provider']='Dr. Demo Example'
    app.session_state['uploaded_data']=df
    app.session_state['dataset_revision']=1
    app.run()
    assert not app.exception
    assert any('Cloud executive briefs are disabled' in i.value for i in app.info)
    assert next(w for w in app.selectbox if w.label=='Reporting period').value=='Latest calendar year'
    assert next(w for w in app.multiselect if w.label=='Select providers').value==['Dr. Demo Example']
    next(b for b in app.button if b.label=='Generate Performance Report').click().run()
    assert not app.exception
    assert app.session_state['performance_report'][1].startswith(b'%PDF')
    next(w for w in app.slider if w.label=='Target utilization (%)').set_value(80).run()
    assert any('Generate a fresh report' in i.value for i in app.info)
    next(b for b in app.button if b.label=='Restore synthetic demo').click().run()
    assert not app.exception
    assert next(w for w in app.selectbox if w.label=='Reporting period').value=='Latest calendar year'


def test_invalid_uploaded_data_disables_dashboard_and_copilot():
    app = AppTest.from_file(Path(__file__).resolve().parents[1] / 'app.py', default_timeout=40)
    invalid = fixture().copy()
    invalid.loc[invalid.index[0], 'visits'] = invalid.loc[invalid.index[0], 'capacity'] + 1
    app.session_state['uploaded_data'] = invalid
    app.run()
    assert any('Data validation failed' in error.value for error in app.error)
    assert not app.tabs
    assert not app.exception


def test_report_unknown_rates_and_escaped_labels():
    df=fixture().iloc[:1].copy()
    df['provider']='Dr. Demo <Example>'
    df['visits']=0
    df['no_shows']=0
    df['booked']=0
    df['revenue']=0
    pdf=performance_report(df,.85,('2025-07-01','2025-07-01'),'Upload')
    text=' '.join(p.extract_text() for p in PdfReader(BytesIO(pdf)).pages)
    assert 'Dr. Demo <Example>' in text
    assert 'Unavailable' in text
    assert 'unknown revenue opportunity' in text
