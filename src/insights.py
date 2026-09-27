"""Deterministic executive insights grounded in the selected data."""


def executive_insights(df, providers, target):
    if providers.empty:
        return ["No data matches this selection."]
    below = providers[providers.utilization < target]
    messages = [f"**{len(below)} of {len(providers)} providers** fall below the selected {target:.0%} utilization target."]
    if not below.empty:
        top = providers.sort_values("opportunity", ascending=False).iloc[0]
        messages.append(f"**{top['provider']} ({top.specialty})** has the largest modeled revenue opportunity: **${top.opportunity:,.0f}**. Providers with no completed visits have no observed revenue rate; their revenue opportunity cannot be estimated.")
    else:
        messages.append("All selected providers meet the scenario target.")
    unbooked = int((df.capacity - df.booked).sum())
    messages.append(f"Unused capacity comprises **{unbooked:,} unbooked slots** and **{df.no_shows.sum():,} no-shows**. Review demand, scheduling access, and appointment reminders as possible next steps.")
    return messages
