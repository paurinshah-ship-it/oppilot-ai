"""In-memory PDF export of the exact selected provider-day rows. No model calls."""
from io import BytesIO
from xml.sax.saxutils import escape
import pandas as pd
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
from src.analytics import benchmark, calculate_kpis, monthly_performance
from src.workspace import executive_summary, top_opportunities, DEFINITIONS
from src.data_reporting import quality_checks


def performance_report(df, target, requested_dates, source):
    """Ratios are weighted; opportunity uses provider rates, never a group rate.

    Undefined rate/opportunity cells stay unavailable. Date coverage is observed
    bounds, not a claim that every scheduled provider-day was submitted.
    """
    if df.empty:
        raise ValueError('Cannot export an empty selection.')
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=landscape(A4), rightMargin=36, leftMargin=36,
                            topMargin=36, bottomMargin=36, title='Provider Performance Report')
    styles = getSampleStyleSheet()
    styles['BodyText'].fontSize = 9
    styles['BodyText'].leading = 12
    story = []
    def para(text, style='BodyText'):
        # Escape uploaded labels; interpret no external markup or links.
        text = str(text).replace('**', '').replace('−','-').replace('–','-').replace('×','x').replace('≥','>=')
        return Paragraph(escape(text).replace('\n','<br/>'), styles[style])
    def heading(text):
        story.append(para(text, 'Heading2'))
    def table(frame):
        rows = [[para(c) for c in frame.columns]]
        for row in frame.itertuples(index=False, name=None):
            rows.append([para('Unavailable' if pd.isna(v) else v) for v in row])
        t = Table(rows, colWidths=[doc.width/len(frame.columns)]*len(frame.columns), repeatRows=1)
        t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#EDE9F5')),
                               ('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white, colors.HexColor('#F8F7FB')]),
                               ('VALIGN',(0,0),(-1,-1),'TOP'), ('BOTTOMPADDING',(0,0),(-1,-1),7),
                               ('TOPPADDING',(0,0),(-1,-1),7), ('LINEBELOW',(0,0),(-1,0),1,colors.HexColor('#7563B5'))]))
        story.append(t)
    story.append(para('Provider Performance Report', 'Title'))
    story.append(para(f'Source: {source}\nRequested: {requested_dates[0]} through {requested_dates[1]}\nObserved: {df.date.min():%Y-%m-%d} through {df.date.max():%Y-%m-%d} | {df.provider_id.nunique()} providers | {len(df):,} provider-day records'))
    story.append(para('Coverage: observed bounds only; schedule completeness is unverified. Only selected providers, clinics, specialties and dated rows are included. No patient records.'))
    k = calculate_kpis(df)
    p = benchmark(df, target)
    heading('Selected-period KPIs')
    table(pd.DataFrame({'Metric':['Visits','Capacity','Utilization','Revenue','Visits / staffed hour','Unused capacity'],
                        'Value':[f'{k["visits"]:,}',f'{k["capacity"]:,}',f'{k["utilization"]:.1%}',f'${k["revenue"]:,.2f}',f'{k["productivity"]:.2f}',f'{k["unused_capacity"]:,}']}))
    story.append(PageBreak())
    heading('Calculated executive summary')
    for line in executive_summary(df,target).split('\n\n'):
        story.extend([para(line), Spacer(1,6)])
    story.append(PageBreak())
    heading('Provider comparisons - selected period')
    comparison = p[['provider','specialty','clinic','visits','utilization','no_show_rate','revenue','unused_capacity']].copy()
    comparison['utilization'] = comparison.utilization.map(lambda v:f'{v:.1%}')
    comparison['no_show_rate'] = p.no_show_rate.where(p.booked.gt(0)).map(lambda v: 'Unavailable' if pd.isna(v) else f'{v:.1%}')
    comparison['revenue'] = comparison.revenue.map(lambda v:f'${v:,.0f}')
    table(comparison)
    story.append(PageBreak())
    heading('Top opportunities - not additive')
    story.append(para(f'Target utilization: {target:.0%}. Gross potential revenue is an estimate, not collections, profit or a forecast. Providers with no visits have an unknown revenue rate.'))
    table(top_opportunities(df,target))
    story.append(PageBreak())
    heading('Monthly trends - selected rows only')
    story.append(para('Edge months may be partial. Missing provider-days are not filled with zeros. Monthly totals are not necessarily comparable volumes.'))
    monthly = monthly_performance(df)
    monthly['utilization'] = (monthly.visits/monthly.capacity).map(lambda v:f'{v:.1%}')
    monthly['month'] = monthly.month.dt.strftime('%Y-%m')
    monthly['revenue'] = monthly.revenue.map(lambda v:f'${v:,.0f}')
    table(monthly)
    story.append(PageBreak())
    heading('Data quality - selected rows')
    table(quality_checks(df))
    story.append(PageBreak())
    heading('Metric formulas and limitations')
    for name, definition in DEFINITIONS.items():
        # Imported data has the same revenue contract but is not claimed synthetic.
        story.extend([para(name.title(),'Heading3'), para(definition.replace('synthetic realized revenue','reported revenue'))])
    def footer(canvas, document):
        canvas.setFont('Helvetica',8)
        canvas.drawString(36,20,'Provider Performance Copilot | Operational analysis; not clinical or employment advice')
        canvas.drawRightString(landscape(A4)[0]-36,20,f'Page {document.page}')
    doc.build(story,onFirstPage=footer,onLaterPages=footer)
    return output.getvalue()
