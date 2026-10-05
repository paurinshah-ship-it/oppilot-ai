# Synthetic anomaly framework

Phase 1F adds deterministic anomaly injection for evaluation datasets. The
framework creates known operational problems in the synthetic enterprise data so
future investigation agents can be scored against ground truth. It does not add
agents, monitoring, orchestration, memory, or frontend behavior.

## Baseline and anomalous modes

Baseline generation remains available through the Phase 1B-1E generators. The
anomaly framework is opt-in: callers build or provide a clean dataset, then call
`apply_anomalies(..., anomaly_profile="portfolio_demo")`. The baseline is copied
before mutation so clean data remains reproducible and comparable.

The anomalous dataset is derived deterministically from the baseline. Fixed
definitions specify practice, date range, type, affected metric, direction,
severity and intensity. No wall-clock values, database state or unseeded random
streams influence the profile.

## Supported anomaly types

The stable machine-readable anomaly types are:

| Type | Main table | Expected pattern |
| --- | --- | --- |
| `MA_STAFFING_SHORTAGE` | `staffing_daily` | Medical Assistant actual FTE decreases; absence, overtime and agency coverage may rise. |
| `PROVIDER_PTO_CAPACITY_REDUCTION` | `provider_capacity` | PTO hours increase while clinical hours and available slots decrease. |
| `NO_SHOW_SPIKE` | `appointment_event` | Completed events convert to `no_show`; modeled revenue becomes zero and linked encounters/payments are removed. |
| `REFERRAL_DEMAND_SURGE` | `referral` | Additional synthetic referrals appear for one practice/specialty/window. |
| `SCHEDULING_TEMPLATE_CAPACITY_REDUCTION` | `provider_capacity` | Blocked slots increase and available slots decrease while clinical hours stay unchanged. |
| `REVENUE_PER_VISIT_DECLINE` | `encounter`, `payment` | Allowed and paid amounts decline while encounter volume stays stable. |

## Portfolio demo profile

`portfolio_demo` contains 10 deterministic anomalies:

- 2 MA staffing shortages
- 2 provider PTO capacity reductions
- 2 no-show spikes
- 2 referral demand surges
- 1 scheduling-template capacity reduction
- 1 revenue-per-visit decline

The profile spreads anomalies across multiple practices, dates and metrics. Some
dates may overlap, but not every practice is anomalous.

## Severity and direction

Severity uses the existing stable catalog: `low`, `medium`, `high`. Direction
uses `increase` or `decrease`. The numeric `intensity` in code controls the
deterministic transformation, such as percentage reduction, conversion share or
number of additional referrals.

## Ground truth

Every applied anomaly produces one `ground_truth_anomaly` row:

`anomaly_id`, `practice_id`, `start_date`, `end_date`, `anomaly_type`,
`affected_metric`, `expected_direction`, `severity`, and `description`.

Descriptions include root cause, affected entity, date window, expected impact
and intensity. Ground truth is for offline evaluation. Future user-facing
investigation flows must not expose or query these rows during inference because
that would turn evaluation into lookup.

## Consistency rules

Anomaly injection must not create contradictions. Converted no-shows cannot keep
completed encounters or payments. Capacity and staffing values cannot go
negative. Revenue decline cannot create negative allowed, paid or patient
amounts. Referral rows remain synthetic and contain no patient, diagnosis or
referring-physician identity fields.
