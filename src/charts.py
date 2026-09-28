"""Plotly figures consume Pandas aggregates; no UI or file access."""
import plotly.express as px
import pandas as pd

COLORS = {"Primary Care": "#7563B5", "Cardiology": "#5276BC",
          "Dermatology": "#8873B2", "Orthopedics": "#CB8B47", "Neurology": "#8D5776",
          "Gastroenterology": "#418C69", "Endocrinology": "#AF6352", "Pulmonology": "#578B9E",
          "Rheumatology": "#7768A6", "Urology": "#9C843C", "Ophthalmology": "#5973A0",
          "Otolaryngology": "#738C54"}


def polish(fig, height=350):
    fig.update_layout(template="plotly_white", height=height,
                      font=dict(family="Arial, sans-serif", color="#51485F", size=12),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      margin=dict(l=10, r=20, t=45, b=20),
                      legend=dict(orientation="h", y=1.16, x=0, title_text=""),
                      hoverlabel=dict(bgcolor="#FFFFFF", font_size=13))
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(gridcolor="#EAE5F0", zeroline=False)
    return fig


def visits_chart(monthly):
    fig = px.line(monthly, x="month", y=["visits", "capacity"], markers=True,
                  color_discrete_sequence=["#7563B5", "#B8B0C9"],
                  labels={"month": "", "value": "Appointments", "variable": "Measure"})
    fig.update_layout(hovermode="x unified")
    return polish(fig)


def revenue_chart(monthly):
    fig = px.bar(monthly, x="month", y="revenue", color_discrete_sequence=["#7563B5"],
                 labels={"month": "", "revenue": "Revenue ($)"})
    fig.update_traces(hovertemplate="%{x|%b %Y}<br>$%{y:,.0f}<extra></extra>")
    fig.update_yaxes(tickprefix="$", tickformat="~s")
    return polish(fig)


def provider_chart(providers, metric, label, tickformat):
    ordered = providers.sort_values(metric)
    fig = px.bar(ordered, x=metric, y="provider", color="specialty", orientation="h",
                 color_discrete_map=COLORS,
                 custom_data=["clinic", "specialty"],
                 labels={metric: label, "provider": "", "specialty": "Specialty"})
    fig.update_traces(hovertemplate="<b>%{y}</b><br>%{customdata[1]} · %{customdata[0]}<br>"
                     + label + ": %{x:" + tickformat + "}<extra></extra>")
    fig.update_yaxes(categoryorder="array", categoryarray=ordered.provider.tolist())
    fig.update_xaxes(tickformat=tickformat)
    return polish(fig, max(390, 28 * len(providers) + 110))


def utilization_chart(providers, target):
    fig = provider_chart(providers, "utilization", "Completed visits / capacity", ".0%")
    fig.add_vline(x=target, line_dash="dash", line_color="#B87928",
                  annotation_text=f"Target {target:.0%}", annotation_position="top")
    fig.update_xaxes(range=[0, 1.05])
    return fig


def productivity_chart(providers):
    return provider_chart(providers, "visits_per_hour", "Visits / staffed hour", ".2f")


def provider_revenue_chart(providers):
    return provider_chart(providers, "revenue", "Revenue ($)", ",.0f")


def utilization_trend_chart(monthly, target):
    monthly = monthly.assign(utilization=monthly.visits / monthly.capacity)
    fig = px.line(monthly, x="month", y="utilization", markers=True,
                  color_discrete_sequence=["#7563B5"],
                  labels={"month": "", "utilization": "Completed visits / capacity"})
    fig.add_hline(y=target, line_dash="dash", line_color="#B87928",
                  annotation_text=f"Target {target:.0%}")
    fig.update_yaxes(tickformat=".0%", range=[0, 1.05])
    fig.update_traces(hovertemplate="%{x|%b %Y}<br>%{y:.1%}<extra></extra>")
    return polish(fig)


def opportunity_concentration_chart(providers):
    """Provider-level modeled opportunity; values are pre-calculated by benchmark."""
    ordered = providers.sort_values("opportunity", ascending=False).head(12).sort_values("opportunity")
    fig = px.bar(ordered, x="opportunity", y="provider", orientation="h",
                 color_discrete_sequence=["#2F6BFF"],
                 labels={"opportunity": "Modeled opportunity ($)", "provider": ""})
    fig.update_traces(hovertemplate="<b>%{y}</b><br>$%{x:,.0f}<extra></extra>")
    fig.update_xaxes(tickprefix="$", tickformat="~s")
    return polish(fig, height=360)


def monthly_no_show_by_specialty_chart(monthly_specialty):
    """Render an allowlisted monthly specialty no-show chart from Pandas output.

    ``monthly_specialty`` must already contain weighted no-show rates calculated
    from provider-day rows. This function accepts data, never natural language
    or generated visualization instructions.
    """
    required = {"month", "specialty", "no_show_rate"}
    if not required.issubset(monthly_specialty.columns):
        raise ValueError("Monthly specialty no-show chart requires approved aggregate columns.")
    data = monthly_specialty.copy()
    data["month"] = pd.to_datetime(data["month"], format="%Y-%m")
    fig = px.line(data, x="month", y="no_show_rate", color="specialty", markers=True,
                  color_discrete_map=COLORS,
                  labels={"month": "", "no_show_rate": "No-show rate", "specialty": "Specialty"})
    fig.update_yaxes(tickformat=".0%", rangemode="tozero")
    fig.update_traces(hovertemplate="%{x|%b %Y}<br>%{fullData.name}: %{y:.1%}<extra></extra>")
    fig.update_layout(hovermode="x unified")
    return polish(fig, height=390)
