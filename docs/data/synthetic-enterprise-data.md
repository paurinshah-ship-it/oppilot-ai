# Synthetic enterprise data — Phases 1B–1D

OpPilot AI's reference fixture is entirely fictional. NorthStar Medical Group,
practice names and provider identities are invented for operational analytics
demonstration; no real affiliation, provider directory or credential verification
is implied. Real U.S. cities/states supply geographic context, not addresses.
No patient data, NPI, SSN, birth date, home address, phone, email, diagnoses or
clinical attributes are generated. Accidental resemblance to real names does not
establish an affiliation.

## Contents and geographic structure

The generator creates exactly one organization, five regions, 25 practices,
12 retained specialties and 150 fictional providers. Every region has five
practices. All practices open before 2021 and are active. Organization creation
uses a fixed synthetic timestamp, not the current clock.

| Code | Region | Practice code range | States |
| --- | --- | --- | --- |
| R01 | Northeast | P01–P05 | MA, NH, RI, ME, CT |
| R02 | Mid-Atlantic | P06–P10 | PA, NJ, MD, VA, WV |
| R03 | Southeast | P11–P15 | NC, SC, GA, FL, TN |
| R04 | Midwest | P16–P20 | WI, IA, OH, MI, IN |
| R05 | Southwest | P21–P25 | AZ, NM, TX, NV, OK |

These are demonstration operating regions, not a claim about an official regional
classification. Practice types include Multispecialty, Primary Care, Cardiology,
Orthopedics, Internal Medicine, Endocrinology, Gastroenterology and Neurology.

The request's 8–10 specialty target applies to new provider assignments: new
providers use ten existing specialties. The original application already uses
12, so all 12 are preserved, including Ophthalmology and Otolaryngology for
legacy providers. Reducing the full catalog to ten would break compatibility.
No existing specialty is renamed or removed.

## Provider strategy and compatibility

`src/data.py:legacy_provider_records()` owns the original 48 identities shared by
the existing provider-day generator and the enterprise generator. The refactor
keeps the original generator's random-call order, names, rates, IDs, specialties,
clinic assignments and output unchanged. The existing CSV is not rewritten.

Legacy `SYN-001`–`SYN-048` keep their original names, specialties and exact
`clinic_name`. These six fictional clinics are explicitly represented as
Multispecialty practices; no matching is inferred from geographic names:

| Existing clinic label | Practice code | Practice ID | Region |
| --- | --- | ---: | --- |
| North Clinic | P01 | 10001 | Northeast |
| Central Clinic | P06 | 10006 | Mid-Atlantic |
| South Clinic | P11 | 10011 | Southeast |
| East Clinic | P07 | 10007 | Mid-Atlantic |
| West Clinic | P21 | 10021 | Southwest |
| Lakeside Clinic | P16 | 10016 | Midwest |

The other 102 providers use `SYN-049`–`SYN-150`, invented unique combinations from
the existing fictional first/last-name vocabulary, and no additional attributes.
Assignment cycles through all 25 practices, ensuring every practice is staffed
in the reference model. Specialty-only practices receive matching specialties;
Internal Medicine uses the existing Primary Care specialty, while new providers
at Multispecialty practices cycle through ten specialties. For every provider,
`clinic_name` equals the associated practice's name. Legacy clinics have more
providers because their original eight-provider groups stay intact.

Provider records alone do not create visits, revenue or available capacity.
Current PostgreSQL dashboard queries join through existing operational facts,
so the 102 new providers do not appear as newly measured provider-days. Current
CSV analytics and the optional appointment-event generator still use 48 providers.
No employees, staffing, capacity, encounters, referrals, payments or anomalies
are populated by Phase 1B. No appointment events or performance rows are added.

## Determinism and ID strategy

The generator has a fixed local random seed of 42 and does not alter the global
random state. Ordered constants define regions and practices. It does not depend
on the clock, network, database, randomized hashes or existing output files.
The full fixture is small, so no reduced mode is needed.

- Organization ID: `10001`; timestamp: `2021-01-01T00:00:00+00:00`.
- Region IDs: `10001`–`10005`; codes: `R01`–`R05`.
- Practice IDs: `10001`–`10025`; codes: `P01`–`P25`.
- Provider IDs: `SYN-001`–`SYN-150`.
- Fixture specialty IDs: `1`–`12` in alphabetical name order, matching the
  original loader on an empty database with default sequences.

IDs are table-local; sharing the same integer across tables is intentional.
Hierarchy IDs are deterministic fixture keys, not an exclusive database-reserved
namespace. Collisions with different existing records abort loading.

Existing database specialty IDs always take precedence. The loader matches
specialties by unique name and remaps provider foreign keys to stored IDs.
For a missing specialty it uses its fixture ID if free; otherwise it allocates
above the maximum currently stored specialty ID. Thus the exported fixture is
identical on every run, but destination specialty numbers may differ according
to existing data. Reruns against the same destination retain those numbers.

## Commands

Generate a reviewable JSON fixture without contacting PostgreSQL:

```sh
python scripts/generate_enterprise_reference_data.py --output /tmp/oppilot-enterprise-reference.json
```

The output directory must exist; the output file must not already exist.
Exclusive creation prevents overwriting existing datasets. No generated artifact
is required in Git. The JSON is a review/export artifact; the loader generates
the approved fixture itself rather than accepting arbitrary external data.

Apply the Phase 1A schema to a reviewed synthetic database if needed, then load:

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 --single-transaction -f db/schema.sql
python scripts/load_enterprise_reference_data.py
```

The loader is an explicit command, never called by the frontend. It does not
initialize/migrate schema, run the existing operational loader, or delete/truncate
any tables. Its success message counts fixture records, not total destination
rows or the number newly inserted. Unrelated records may remain in the database.

## Loader safeguards and operational considerations

The reusable loader uses one explicit PostgreSQL transaction (a savepoint if
called inside a transaction; the caller owns that outer commit). It locks the
five reference tables in a fixed order with SHARE ROW EXCLUSIVE locks, preventing
concurrent reference writes during comparison/insertion while permitting reads.
Run during a suitable maintenance window; loaders that acquire locks in other
orders may encounter PostgreSQL deadlock detection and need retrying.

Existing organization/region/practice rows must match the full approved fixture.
Provider rows must match IDs, names, resolved specialty IDs, clinic labels and
practice mappings. Only matching legacy providers with NULL practice_id can have
that field filled. Existing non-NULL mappings are not silently changed. A
conflicting primary/natural key or mismatched identity aborts the entire load.
The application must not use these synthetic fixture IDs for unrelated data.

No unconditional upsert is used: comparison plus INSERT, under table locks,
avoids overwriting unrelated rows. The only UPDATE fills a validated legacy
provider's empty practice reference. Repeated successful loads leave row values
and timestamps unchanged. There are no operational-table writes.

Explicit reference IDs require sequence coordination. The loader advances the
four affected BIGSERIAL sequences past stored IDs only when needed, never
rewinds them, and uses transactional ALTER SEQUENCE RESTART rather than setval.
A failure rolls back both reference changes and sequence restarts. This requires
ownership/appropriate privileges on those sequences plus reference-table write
privileges. It assumes the standard ascending sequences defined by Phase 1A;
custom sequence configurations require review. Do not concurrently reserve IDs
through direct nextval calls outside normal table inserts during loading.

Existing manually changed legacy identities/mappings or hierarchy ID/name
collisions require explicit reconciliation; the loader deliberately refuses to
resolve them by guessing. No automatic deletion or destructive reconciliation
is provided. Database schema drift is not repaired by this loader.

## Validation

Generation validates exact counts, approved field sets/types, unique IDs/names,
organization/region relationships, five practices per region, provider practice
and specialty relationships, clinic labels, practice-type compatibility and
legacy identities. It emits no operational or patient-level fields. This fixed
fixture generator is not a general-purpose real-data import validator.

```sh
python -m pytest -q tests/test_enterprise_reference.py
OPPILOT_TEST_DATABASE_URL=postgresql://localhost/oppilot_test python -m pytest -q
node tests/voice_frontend_test.cjs
```

Use a disposable PostgreSQL database. Integration tests create isolated random
schemas and roll back their changes; they never use DATABASE_URL. Without the
test URL, PostgreSQL cases explicitly skip. Full validation sets the test URL and
exercises real inserts, mappings, idempotence, conflict rollback, sequence
advancement and preservation of legacy operational data. Frozen pre-refactor
provider-day hashes for two seeds guard the existing generator's output.


## Phase 1C: independent operational baseline

`src/enterprise_operations.py` reuses the Phase 1B generator as the only source
of practices, providers and specialties. It adds only employee, provider_capacity
and staffing_daily data. No existing reference records, provider-day CSV,
appointment aggregates, performance, appointment events, encounters, referrals,
payments or ground-truth anomalies are generated or changed by this phase.
The Streamlit application does not read these new operational tables yet.

The fixed window is **2024-01-01 through 2025-12-31 inclusive**, exactly 24
calendar months and 731 days including February 29, 2024. Both daily tables
include weekends, represented by zero-valued rows. Default counts are:

| Table | Rows | Grain |
| --- | ---: | --- |
| employee | 462 | One fictional employee ID |
| provider_capacity | 109,650 | 150 providers × 731 dates |
| staffing_daily | 146,200 | 25 practices × 8 roles × 731 dates |

The legacy Provider Performance dataset retains its 2021–2025 coverage and
existing calculations. Matching dates do not imply the independent datasets
reconcile: do not substitute new capacity/staffing into old metrics or combine
the measures without a future explicit model integration.

### Employee model

All employees are represented by synthetic numeric IDs only, with no names,
contact details, credentials or personal/clinical attributes. For provider
headcount N at a practice, the fixed roster contains:

| Operational role | Employees per practice | Synthetic hourly cost range |
| --- | --- | --- |
| Medical Assistant | N + 1 | $20–$29 |
| RN | 3 for N ≥ 8; otherwise 2 | $34–$47 |
| LPN | 1 | $25–$34 |
| Front Desk | 3 | $18–$25 |
| Scheduler | 2 | $20–$28 |
| Practice Manager | 1 | $34–$48 |
| Referral Coordinator | 1 | $23–$31 |
| Billing Specialist | 2 for N ≥ 8; otherwise 1 | $24–$34 |

Organization totals are 175 MAs, 56 RNs, 25 LPNs, 75 Front Desk staff, 50
Schedulers, 25 Practice Managers, 25 Referral Coordinators and 31 Billing
Specialists. Counts vary with practice size rather than being identical.
Costs are illustrative nominal synthetic dollars, not researched market rates.
FTE is chosen from 0.6, 0.8 and 1.0, weighted toward 1.0; managers are 1.0 FTE.

This clean baseline uses a fixed cohort: all employees are active and have NULL
termination_date. Hire dates fall on/after practice opening and before 2024.
No turnover or dated leave episodes are modeled. Validation checks the schema's
active/on_leave/terminated status vocabulary and date consistency, but generation
uses active only. Individual employment histories are not reconstructed.

Employee IDs follow `1000000 + practice_offset * 1000 + role_index * 100 + slot`,
with zero-based role/slot indices. The formula gives stable, unique IDs for the
fixed reference fixture. These are not globally reserved database IDs; a
collision with a different existing record causes loading to fail.

### Provider-capacity model

Each provider has a deterministic profile: a 6.4- or 8-hour weekday template,
a 0.75/1/1.25-hour administrative allowance, and a specialty-based slot rate.
Approximately 15% of profiles have one regular weekday off. All weekends are
closed. The baseline does not model holidays, time zones, shifts or seasonal
closures. On eligible workdays, a 4% independent probability assigns routine
full-day PTO; this is ordinary baseline variation, not labeled anomaly injection.

For every provider/date:

- scheduled_hours = clinical_hours + admin_hours + pto_hours.
- scheduled_hours is the planned template, including paid PTO; maximum 8.
- Full-day PTO consumes the template, leaving zero clinical/admin hours and slots.
- Otherwise clinical_hours = template hours − administrative allowance.
- Gross slots = floor(clinical_hours × specialty daily slots / 7 × provider
  factor), using existing specialty slot assumptions and factor 0.9, 1 or 1.1.
- Routine blocked slots are drawn from 0, 0, 0, 1, 2 and capped at gross slots.
- available_slots = gross slots − blocked_slots. Blocked slots reserve clinical
  template time; they are not additional hours or additional available slots.

All quantities are nonnegative. A closed/off day has zero hours and slots.
Patterns differ by provider and specialty. No appointment statuses, visits or
revenue are inferred from these capacity rows.

### Daily staffing model

FTE here means an eight-hour-day equivalent, not a count of people present.
For every practice/date/role, weekday budgeted_fte is the sum of that roster's
contracted FTE. Each employee has a 3% daily chance of routine planned leave,
which removes their FTE from scheduled_fte. Of those scheduled, 2% have an
unplanned absence, removing their FTE from actual_fte. Weekends have zero budget,
schedule, actual staffing and supplemental hours. Manager counts remain lower
than MA and front-desk counts.

The following relationships hold:

- 0 ≤ actual_fte ≤ scheduled_fte ≤ budgeted_fte.
- absence_hours = (scheduled_fte − actual_fte) × 8.
- Coverage gap hours = (budgeted_fte − actual_fte) × 8.
- overtime_hours replaces 0%, 25% or 50% of that gap, capped at two extra hours
  per actual regular-staff FTE.
- When a gap remains for MA/RN/LPN roles, an 8% conditional chance supplies agency
  hours, capped at eight hours and at the remaining gap. Agency use is uncommon
  across the full dataset; it is not 8% of all staffing rows.
- overtime_hours + agency_hours never exceeds the coverage gap.
- Actual FTE excludes overtime and agency. Effective coverage, if needed later,
  is actual_fte + (overtime_hours + agency_hours) / 8; absence must not be deducted
  from actual_fte again.

Employee FTE sums link staffing to the roster. Provider headcounts determine MA
staffing and larger-practice RN/billing allocations. Staffing is not yet coupled
to realized provider clinical hours; no causal effect on capacity is asserted.
Planned leave and absences are independent daily variation, not persistent
shortage episodes. No root-cause or ground-truth labels are injected.

### Reproducibility and development windows

A fixed seed of 42 and SHA-256-derived per-entity/per-date random streams avoid
Python's process-randomized hash and the current clock. No global random state
is modified. Dates are inclusive. Numeric measures use at most two decimals.
A smaller date window generates exactly the matching full-run slice; employee
IDs and roster remain unchanged. This makes overlapping development loads safe.
Only subwindows inside the fixed 24-month period are accepted.

Export a full baseline into a **new** directory (existing directories are refused):

```sh
python scripts/generate_enterprise_operations.py --output-dir /tmp/oppilot-operations
```

The command produces employee.csv, provider_capacity.csv, staffing_daily.csv and
a manifest with date bounds/counts. Empty CSV termination_date values mean NULL.
If a disk error interrupts export, remove or choose another partial output
directory before retrying; file export is not a database transaction. Generated
files are review artifacts and need not be committed. No arbitrary CSV import
is introduced; the loader generates and validates the baseline itself.

After separately applying the existing schema and loading Phase 1B references:

```sh
python scripts/load_enterprise_operations.py
# Small development window, same identities and day values:
python scripts/load_enterprise_operations.py --start 2024-01-01 --end 2024-01-07
```

Both export and loading accept --start/--end. The loader uses DATABASE_URL only
when explicitly invoked. There is no automatic loading, background job or UI hook.

### Bulk loading and conflict policy

`src/enterprise_operations_loader.py` validates the complete requested window,
then verifies the stored Phase 1B practice hierarchy and provider identity,
specialty name, clinic label and practice mapping. Stored specialty numeric IDs
may differ, as allowed by the Phase 1B loader. Missing or conflicting references
cause an error; they are not repaired or silently loaded here.

One explicit transaction covers all three tables and the employee serial
sequence (a savepoint inside an existing transaction). Temporary staging uses
PostgreSQL COPY, followed by set-based row comparison and INSERT SELECT. There
are no per-record INSERT round trips, DELETEs, TRUNCATEs or unconditional updates.
All matching existing keys must have identical values; differing values abort
the entire load. Identical reruns insert zero rows, and overlapping subwindows
insert only missing dates. Unrelated keys and out-of-window rows are preserved.

Reference tables receive SHARE locks to prevent concurrent remapping. The three
operational targets receive SHARE ROW EXCLUSIVE locks, allowing ordinary reads
while serializing writes. Temporary staging tables are dropped after use.
Sequence advancement uses transactional ALTER SEQUENCE RESTART only when needed
and never rewinds; it protects subsequent default employee IDs. Failures roll
back earlier table inserts and sequence changes together. An outer caller can
still roll back a successful load.

A loading role needs reference reads/locking privileges, target write/locking
privileges, database TEMP permission and employee-sequence ownership or appropriate
privileges. Normal ascending Phase 1A sequences are assumed. Avoid direct external
nextval reservations and concurrent migrations during loading. Table locks may
block other writers; use a development database or maintenance window. No
application database is loaded as part of code validation.

### Phase 1C validation

Tests cover full counts and date coverage, leap day, keys and relationships,
role catalogs, employee dates, balanced capacity hours, nonnegative finite
measures, staffing reconciliation, rare agency use, deterministic full and sliced
runs, strict field allowlists, invalid inputs, full-size PostgreSQL COPY loading,
idempotence, overlapping windows, reference conflicts, data/sequence rollback and
preservation of legacy facts. No existing tests are weakened.

```sh
OPPILOT_TEST_DATABASE_URL=postgresql://localhost/oppilot_test python -m pytest -q tests/test_enterprise_operations.py
OPPILOT_TEST_DATABASE_URL=postgresql://localhost/oppilot_test python -m pytest -q
```

As in previous phases, PostgreSQL tests require a disposable test database and
otherwise explicitly skip. The existing synthetic-only/no-PHI policy applies;
no personal or patient fields are present in these three exports.

## Phase 1D appointment events

The enterprise appointment generator uses the existing 150-provider, 25-practice,
12-specialty reference fixture. It emits event IDs beginning at `2,000,001`, above
the legacy scale generator's `1`–`1,000,000` range. The default is one million
rows for January 1, 2024 through December 31, 2025; smaller counts and inclusive
date windows are supported for development. Rows stream from a fixed-seed local
random generator, so fixed inputs reproduce the same values without retaining
the full dataset in memory. The legacy generator and its five-column CSV/COPY
contract remain available unchanged.

The five original event fields stay in their existing order:
`appointment_id`, `provider_id`, `appointment_date`, `appointment_status`, and
`modeled_revenue`. The five appended enterprise fields are nullable for old
rows and old five-column inserts: `practice_id`, `appointment_type`,
`scheduled_at`, `slot_duration_minutes`, and `payer_category`. Each generated
provider/practice pair matches the reference hierarchy.

Statuses include `completed`, `no_show`, legacy `cancelled`,
`cancelled_patient`, `cancelled_provider`, `cancelled_practice`, and
`rescheduled`. The illustrative baseline uses 78% completed, 11% no-show and
11% total cancellation/reschedule weights; that final 11% is split across the
four cancellation/reschedule labels. This preserves the aggregate synthetic
weight model while adding operational detail. These are generated baseline
assumptions, with no explicit anomaly injection. Existing no-show SQL is
defined as `no_show / (completed + no_show)` for event-level analytics.
`cancelled`, `cancelled_patient`, `cancelled_provider`, `cancelled_practice`,
and `rescheduled` are excluded from the denominator. Legacy event datasets with
only `completed`, `no_show`, and `cancelled` return the same rate as the older
`appointment_status <> 'cancelled'` denominator.

Appointment types use a specialty-weighted catalog: `new_patient`, `follow_up`,
`annual`, `procedure`, `consult`, `urgent`, and `telehealth`. Payer categories
are `Commercial`, `Medicare`, `Medicaid`, `Self Pay`, and `Other`; they describe
synthetic categories, not contracts or people. Booking timestamps use UTC and
lead time varies by type: urgent visits are booked 1–3 days ahead, follow-ups
7–35 days, new/annual appointments 14–60 days, procedures 7–42 days, consults
21–75 days, and telehealth 2–21 days. Service dates are weekdays and booking
time always precedes service date. Slot durations are 15, 20, 30, 45, or 60
minutes, sampled from appointment-type-specific choices.

Modeled revenue remains a synthetic service-level amount, only for completed
events; every other status has zero modeled revenue. It is not payment,
collection, allowed amount, or a patient balance. No patient identifier, name,
diagnosis, note, or other PHI is present.

Export a deterministic CSV without loading one million rows into memory:

```sh
python scripts/generate_enterprise_appointment_events.py --output /tmp/enterprise-appointment-events.csv
python scripts/generate_enterprise_appointment_events.py --output /tmp/appointment-sample.csv --count 10000
```

The output path must be new. A companion manifest records the count, seed,
date window and status counts. To load into a disposable/development database
after applying the schema and loading Phase 1B reference data:

```sh
python scripts/load_enterprise_appointment_events.py --count 10000
```

The loader COPYs generated rows to a temporary staging table and performs a
set-based conflict check and insert inside one transaction. Identical reruns
insert zero rows; an existing event ID with different generated values aborts
the transaction. It preserves legacy event rows and does not touch provider-day
facts or other operational tables. Table locks serialize competing writes, so
large loads belong in a development database or a planned maintenance window.

## Phase 1E encounters, payments and referrals

Encounter and payment generation streams from the Phase 1D appointment-event
generator. Encounters are emitted only for `completed` appointment events, with
one encounter per completed appointment. Provider, practice, date and visit type
come from the appointment event. The default one-million appointment stream
therefore produces roughly the completed-event share as encounters and one
payment for each encounter; smaller deterministic counts are supported for
development and tests.

Financial fields are intentionally separate. `appointment_event.modeled_revenue`
is the legacy operational compatibility estimate. `encounter.modeled_charge` is
a synthetic gross charge. `encounter.allowed_amount` is a synthetic allowable
amount that does not exceed the modeled charge. `payment.paid_amount` is a
synthetic paid amount. None is profit, and modeled revenue is not treated as
collections. Phase 1E uses one payment per encounter; partial payments and
line-level variations are left for a later additive model.

Payment lags are synthetic and payer-category based: Commercial and Medicare
use moderate delays, Medicaid somewhat longer delays, and Self Pay/Other more
variable delays. Payment dates are never before the encounter date and can
spill beyond the 2024-2025 appointment window by up to 90 days.

Referral generation is independent operational demand by practice and specialty,
not a direct appointment foreign key. Statuses are `received`, `scheduled`,
`completed`, `expired` and `lost`. Scheduled and completed referrals include a
scheduled date on or after the referral date; lost and expired referrals remain
available for future access and leakage analysis. Sources are generic synthetic
categories: `internal`, `external_primary_care`, `specialist`, `self_referred`,
`hospital_discharge` and `other`.

```sh
python scripts/generate_enterprise_finance.py --output-dir /tmp/enterprise-finance --count 10000
python scripts/load_enterprise_finance.py --count 10000
python scripts/generate_enterprise_referrals.py --output /tmp/enterprise-referrals.csv --count 5000
python scripts/load_enterprise_referrals.py --count 5000
```

The finance loader requires matching Phase 1D appointment events to exist first.
Both Phase 1E loaders use temporary staging tables, set-based conflict checks,
insert-only semantics and transactions. Identical reruns insert zero rows;
conflicting existing rows abort without overwriting stored values.
