"""Data onboarding staged separately from active dashboard state."""
import hashlib
import pandas as pd
import streamlit as st
from src.data_reporting import COLUMNS, read_upload, suggest_mapping, project_columns, quality_checks, activate_upload
from src.reporting import performance_report


def render_data_controls():
    with st.expander('Data source and CSV upload'):
        uploaded = 'uploaded_data' in st.session_state
        st.caption('Active: ' + ('uploaded aggregate CSV (local only)' if uploaded else 'built-in synthetic demo'))
        st.info('Upload only synthetic or verified non-PHI provider-day aggregates. No patient rows, identifiers, clinical notes or free text. Uploads stay in this local app session; cloud AI briefs are disabled for uploaded data.')
        st.caption('Required date format: YYYY-MM-DD. Revenue must mean realized revenue, not collections or charges. Cancellations cannot replace no-shows. Missing measures are not inferred. Only mapped columns are retained.')
        st.download_button('Download CSV template', ','.join(COLUMNS)+'\n', 'provider_day_template.csv', 'text/csv')
        file = st.file_uploader('Upload provider-day CSV', type=['csv'])
        if file is not None:
            payload = file.getvalue()
            digest = hashlib.sha256(payload).hexdigest()[:16]
            try:
                raw = read_upload(payload)
                suggestions = suggest_mapping(raw.columns)
                mapping = {}
                with st.form('csv_mapping_'+digest):
                    st.caption('Confirm each mapping. Ambiguous aliases are left unselected. Unknown columns will be discarded.')
                    cols = st.columns(3)
                    for i, field in enumerate(COLUMNS):
                        options = ['Not mapped'] + list(raw.columns)
                        selected = suggestions[field] or 'Not mapped'
                        mapping[field] = cols[i%3].selectbox(field,options,index=options.index(selected),key='mapping_'+digest+field)
                        if mapping[field] == 'Not mapped':
                            mapping[field] = None
                    confirmed = st.checkbox('I confirm this is synthetic or verified non-PHI aggregate data and these field meanings match the mapping.',key='confirm_'+digest)
                    submitted = st.form_submit_button('Validate and activate CSV')
                if submitted:
                    candidate = project_columns(raw,mapping)
                    checks = quality_checks(candidate)
                    st.dataframe(checks, hide_index=True, width='stretch')
                    activate_upload(st.session_state,raw,mapping,confirmed)
                    st.rerun()
            except (ValueError, KeyError, UnicodeError, pd.errors.ParserError) as exc:
                st.error(f'Upload not activated: {exc}. The active dataset is unchanged.')
        if uploaded and st.button('Restore synthetic demo'):
            del st.session_state['uploaded_data']
            st.session_state['dataset_revision'] = st.session_state.get('dataset_revision',0)+1
            st.rerun()


def render_reporting(df,target,dates):
    st.subheader('Data quality and performance report')
    st.caption('Checks below cover the selected rows. Weekday gaps are advisory, not proof of missing data; a staffing roster is required to verify completeness.')
    st.dataframe(quality_checks(df),hide_index=True,width='stretch')
    source = 'Uploaded non-PHI aggregates (user confirmed)' if 'uploaded_data' in st.session_state else 'Built-in synthetic demo'
    fingerprint = hashlib.sha256((df.to_csv(index=False)+str(target)+str(dates)+source).encode()).hexdigest()
    st.caption('The PDF includes selected-period KPIs, provider comparisons, monthly trends, opportunities, a calculated executive summary, quality checks and formulas. It is generated locally without AI calls.')
    if st.button('Generate Performance Report'):
        st.session_state['performance_report'] = (fingerprint,performance_report(df,target,dates,source))
    saved = st.session_state.get('performance_report')
    if saved and saved[0] == fingerprint:
        st.download_button('Export Performance Report', saved[1], 'provider_performance_report.pdf','application/pdf')
    elif saved:
        st.info('Selection or source changed. Generate a fresh report for this scope.')
