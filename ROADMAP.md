# Provider Performance Copilot roadmap

Build in releases. Keep Python/Pandas responsible for calculations and date resolution; the conversational layer selects supported analyses and explains calculated results. Preserve the current dashboard, selected-team filters, local voice processing, and safety restrictions.

## Current baseline

The app already has calendar dates and year-only requests, weighted KPIs, provider/specialty benchmarks, complete-year trend comparisons, opportunity rules, a utilization target slider, a provider table, a calculated executive brief and optional AI management actions, basic provider follow-up context, dated grounding, and strict CSV validation. Newest chat exchanges appear first.

The demo dataset covers 2021–2025. Requests for 2026 must report unavailable coverage instead of substituting a different year. Revenue is measured; collections and cancellations are not separate measured fields. Do not relabel revenue as collections or infer cancellations from no-shows.

## Release 1 — Comparative conversation (implemented)

| Roadmap items | Work | Acceptance criteria |
| --- | --- | --- |
| 1. Date intelligence | Add year to date, trailing 30 days, and two-period comparisons | Resolve relative dates from Python's current date; last 30 days includes today and preceding 29 days; validate both comparison windows before filtering raw rows. |
| 2. Provider comparison | Resolve two selected fictional providers and compare dimensions | Show visits, utilization, no-show rate, revenue per visit, revenue, and unused capacity. Report collections as unavailable; unknown or ambiguous names require clarification. |
| 3. Trend detection | Compare provider metrics across explicit periods and documented defaults | Changes in rates use percentage points; percentage changes handle zero baselines explicitly; match providers across windows and disclose missing observations. |
| 11–12. Context and suggestions | Track provider, metric, and period; provide actionable follow-up buttons | Follow-ups resolve from explicit structured context, never generated prose. Filters reset context; button requests follow the same safety and availability path as typed requests. |
| 15–16. Grounding and availability | Add provider and raw-row counts plus factual coverage messages | Every analytical answer identifies its period, providers, and records. Comparison answers show both windows. Dataset bounds are not presented as proof of complete daily observations. |

## Release 2 — Executive operations workspace (implemented)

| Roadmap items | Work | Acceptance criteria |
| --- | --- | --- |
| 4. Executive summary | Add Generate Executive Summary using verified comparisons | Summarize KPIs, volume leader, opportunity leader, and changes only when both periods are available. Local generation works without API credentials. |
| 5. Why investigation | Describe associated changes and propose investigations | Check direction of change instead of accepting the question's premise. Describe visits, capacity, bookings, and no-shows; never invent cancellations, appointment mix, or causation. |
| 6. Top opportunities | Consolidate static flags and period declines | Show metric-specific impacts, tie handling, period labels, and non-additive opportunity warnings. |
| 9–10. Scorecards and specialties | Add provider selection/detail views and specialty comparisons | Keep dimensions separate; use weighted ratios and provider-level opportunity sums; show trends and availability. |
| 14. Explain my metric | Map metric questions to the implemented formulas | Explain denominators, zero-denominator behavior, target assumptions, and units consistently with code. |

## Release 3 — Scenarios and charts (implemented)

| Roadmap items | Work | Acceptance criteria |
| --- | --- | --- |
| 7–8. Simulator and sliders | Add no-show targets and optional revenue-per-visit assumptions | Additional visits = max(0, observed no-shows − target rate × booked visits), bounded by unused slots. Additional revenue = additional visits × observed or explicitly assumed revenue/visit. Label estimates for the actual analysis period; do not sum overlapping utilization and no-show opportunities. |
| 20. Ask to chart | Map supported chart requests to fixed Plotly builders | Chart the same validated raw-row scope as text answers; monthly utilization is total visits / total capacity, not an average of daily percentages. |

## Release 4 — Data onboarding and reporting (implemented)

| Roadmap items | Work | Acceptance criteria |
| --- | --- | --- |
| 13. Data-quality checker | Expose validation results and potential date gaps | Detect required-field nulls, duplicates, negative values, utilization over 100%, and impossible counts. Distinguish unscheduled days/leave from proven missing records. |
| 17–18. CSV upload and mapping | Stage uploads, suggest mappings, confirm ambiguous mappings, validate before activation | Accept synthetic or verified non-PHI aggregate provider-day data only; never send PHI to a model. Never silently map cancellations to no-shows or collections to revenue. Unknown columns are not sent to a model. Preserve the current dataset when validation fails. |
| 19. Export report | Add Excel or PDF with KPIs, comparisons, trends, opportunities, and summary | Export the same scoped calculations shown in the app, including date coverage, formulas, scenario assumptions, and missing-data notes. |

## Verification for every release

- Test calculations against hand-computed fixtures, including ties and zero denominators.
- Test complete, partial, and unavailable dates without silently changing periods.
- Test safety restrictions and unsupported-data explanations independently.
- Test Streamlit interactions and local voice routing when affected.
- Run Python syntax checks and the regression suite; restart the local app and verify health.
