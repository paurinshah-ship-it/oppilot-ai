# Synthetic enterprise reference data — Phase 1B

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
