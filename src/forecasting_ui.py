"""Observed, forecast, and interval presentation for the selected dashboard scope."""
import streamlit as st
import plotly.graph_objects as go
from src.forecasting import forecast_month


def render_forecasting(df):
    with st.expander('Forecast next month — experimental'):
        st.caption('Uses the selected dates and team. Collections are unavailable; no revenue substitution is made.')
        metric = st.selectbox('Forecast measure', ['visits', 'utilization', 'collections'], format_func=lambda x:x.title())
        months = st.slider('Historical months for forecast', 3, 12, 6)
        if st.button('Calculate forecast'):
            result = forecast_month(df, metric, months)
            if result['status'] != 'ok':
                st.info(result['message'])
                return
            fmt = (lambda x:f'{x:.1%}') if metric == 'utilization' else (lambda x:f'{x:,.0f}')
            st.subheader(f"Forecast for {result['month']:%B %Y}")
            st.write(f"**Forecast:** {fmt(result['forecast'])}")
            lo, hi = result['confidence_interval']
            st.write(f'**95% confidence interval for the mean:** {fmt(lo)}–{fmt(hi)}')
            pl, ph = result['prediction_interval']
            st.write(f'**95% prediction interval for next month:** {fmt(pl)}–{fmt(ph)}')
            history = result['history']
            fig = go.Figure(go.Scatter(x=history.month,y=history.observed,name='Observed',mode='lines+markers',line_color='#7563B5'))
            fig.add_trace(go.Scatter(x=[result['month']],y=[result['forecast']],name='Forecast · 95% prediction interval',mode='markers',marker=dict(symbol='diamond',size=12,color='#246C70'),error_y=dict(type='data',array=[ph-result['forecast']],arrayminus=[result['forecast']-pl],symmetric=False)))
            fig.update_layout(yaxis_title=metric.title(),xaxis_title='Month',legend=dict(orientation='h'))
            if metric == 'utilization': fig.update_yaxes(tickformat='.0%')
            st.plotly_chart(fig,width='stretch')
            st.dataframe(history.rename(columns={'observed':'Observed value'}),hide_index=True,width='stretch')
            st.caption(result['message'])
            st.warning('Experimental rolling-mean baseline. Intervals assume independent, stable monthly observations and are not validated coverage guarantees. Seasonality, staffing changes, demand, holidays and provider mix can invalidate these assumptions. Observed weekday coverage does not establish complete provider reporting. Bounds are clipped to feasible values. Use for planning review, not commitments.')
