# Deterministic enterprise tool layer

Phase 1G defines the safe deterministic analytics layer future agents can call.
It does not add an agent, orchestrator, monitor, memory system, root-cause
engine or frontend redesign.

## Architecture

Future callers provide typed request objects such as `EnterpriseMetricRequest`.
The tool layer validates metric keys, dimension keys, date ranges, filters and
limits against fixed catalogs. It then compiles parameterized PostgreSQL SQL
from fixed fragments. User text never becomes SQL, table names or column names.

```text
User or future agent
  -> structured tool arguments
  -> allowlisted enterprise tool compiler
  -> deterministic SQL and bound parameters
  -> PostgreSQL enterprise operational facts
  -> structured evidence results
```

LLMs must not calculate operational metrics. Metrics, comparisons, rankings,
trends and financial calculations come from deterministic code and validated
queries.

## Supported dimensions

Supported dimensions are:

`organization`, `region`, `practice`, `specialty`, `provider`, `month`.

Not every metric supports every dimension. Staffing metrics are scoped to
organization, region, practice and month. Referral metrics support specialty but
not provider. Unsupported combinations fail closed.

## Metric catalog

Appointment and access:

`appointments`, `completed_visits`, `no_shows`, `no_show_rate`,
`cancellations`, `rescheduled`, `appointment_completion_rate`,
`average_booking_lead_days`, `median_booking_lead_days`.

Capacity and productivity:

`available_slots`, `blocked_slots`, `blocked_slot_rate`, `clinical_hours`,
`scheduled_hours`, `pto_hours`, `admin_hours`, `visits_per_clinical_hour`,
`visits_per_provider`, `capacity_utilization`.

Staffing:

`budgeted_fte`, `scheduled_fte`, `actual_fte`, `staffing_gap_fte`,
`absence_hours`, `overtime_hours`, `agency_hours`.

Referrals:

`referrals_received`, `referrals_scheduled`, `referrals_completed`,
`referrals_lost`, `referrals_expired`, `referral_conversion_rate`.

Financial:

`modeled_revenue`, `modeled_charges`, `allowed_amount`, `paid_amount`,
`patient_amount`, `adjustment_amount`, `revenue_per_completed_visit`,
`allowed_amount_per_encounter`, `paid_amount_per_encounter`.

Financial labels remain distinct. `modeled_revenue` is not collections, and
`paid_amount` is not profit.

## Semantic rules

Ratios aggregate raw numerators and denominators before division. Monthly trends
must not average daily percentages.

Key formulas:

- `no_show_rate = no_show / (completed + no_show)`
- `staffing_gap_fte = budgeted_fte - actual_fte`
- `blocked_slot_rate = blocked_slots / (available_slots + blocked_slots)`
- `referral_conversion_rate = completed referrals / received referrals`
- `capacity_utilization = completed_visits / available_slots`
- `revenue_per_completed_visit = modeled_revenue / completed_visits`
- `allowed_amount_per_encounter = allowed_amount / encounters`
- `paid_amount_per_encounter = paid_amount / encounters`

Zero denominators use `NULLIF` and return unavailable database values rather
than fabricating zero.

## Tool contracts

Tool results include metric key, value, unit, formula, period, scope, numerator,
denominator and entity counts where available. Comparison helpers identify rate
changes as percentage-point changes and count/financial changes as percentage
changes when the comparison denominator is valid.

Ranking helpers require an explicit metric, dimensions, date period and sort
direction. Ties are deterministic through secondary dimension ordering.

Summary helpers return evidence only. They can say that a metric increased or
decreased; they must not claim cause.

## Ground-truth firewall

Agent-facing tools must not access `ground_truth_anomaly`. They do not import
the anomaly framework, join ground truth, query it, expose it or use it to
influence results. Ground truth is reserved for offline evaluation so future
investigation agents cannot cheat by reading labels.

Tests assert that compiled agent-facing SQL does not reference
`ground_truth_anomaly` and that attempts to request it as a metric fail closed.
