# Provider Performance Copilot

A local Streamlit MVP for synthetic ambulatory provider performance, built with Python, Pandas, and Plotly. No PHI, patient identifiers, or patient-level records are generated.

## Run

Python 3.10+ recommended.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python scripts/generate_data.py
python -m streamlit run app.py --server.address 127.0.0.1
```

Open http://localhost:8501. If an environment already exists, use `.venv/bin/python` directly. Regenerating the CSV with the same seed produces identical data; rerun the app after regeneration; the file modification time refreshes its cache.

## Included

- Date, specialty, clinic, and provider filters.
- Visits, staffed appointment capacity, weighted utilization, revenue, unused capacity, and visits per staffed hour.
- Monthly Plotly charts, specialty peer benchmarks, opportunity ranking, executive insights, and CSV export.
- A deterministic local copilot demo with metric-backed answers. A conversational language-model integration is a future increment; no API key is needed for this version.

## Project layout

```text
app.py                       Streamlit dashboard
src/data.py                  Synthetic generation and CSV loading
src/analytics.py             Metrics, opportunities, demo answers
scripts/generate_data.py     Reproducible data generator
data/provider_performance.csv  Generated provider-day dataset
tests/test_app.py            Metric and Streamlit interaction tests
.streamlit/config.toml       Theme and local configuration
```

## Data and assumptions

The fixed demo covers staffed weekdays within five complete calendar years, January 1, 2021–December 31, 2025, with 48 fictional named providers, 12 specialties, and six fictional clinics. Rows represent staffed provider-days. Fields: date, provider_id, provider, specialty, clinic, fte, staffed_hours, capacity, booked, no_shows, visits, revenue. Leave days are excluded from staffed capacity. Visits plus no-shows equals bookings, which never exceed capacity.

Utilization is completed visits divided by capacity. Unused capacity includes unbooked appointments and no-shows. Opportunity is the sum of each provider's positive gap to the selected utilization target multiplied by that provider's realized revenue per visit. It is a scenario, excludes costs, and assumes sufficient demand. The 85% default is an illustrative assumption, not an industry standard. Specialty comparisons reflect current filters and include the provider in the peer group. This is operational analysis, not a measure of quality of care.

## Test

```sh
.venv/bin/python -m pytest -q
```

Next increments: aggregate-data import workflows, richer scheduling scenarios, and an optional language-model copilot with grounded metric tools. This MVP has no authentication or production deployment configuration.

## MVP architecture and KPI contract

CSV → validated Pandas DataFrame → Streamlit filters → shared KPI and monthly aggregates → Plotly charts and executive insights.

- `src/data.py` loads and validates the provider-day schema, finite nonnegative values, integer appointment counts, unique provider-days, and booking reconciliation. Invalid files produce a visible error in the app.
- `src/analytics.py` owns `calculate_kpis`, provider benchmarks, monthly rollups, and opportunity calculations.
- `src/charts.py` turns aggregates into Plotly figures.
- `src/insights.py` generates executive observations from the same filtered data.
- `app.py` composes the Streamlit interface. CSV modification time invalidates the data cache on the next app rerun.

| KPI | Calculation over the selected records |
| --- | --- |
| Provider visits | Sum of completed visits |
| Appointment capacity | Sum of staffed appointment slots |
| Utilization | Total visits / total capacity |
| Revenue | Sum of synthetic realized revenue |
| Provider productivity | Total visits / total staffed hours |
| Unused capacity | Total capacity − total visits |

Ratios use summed denominators, never an average of daily percentages. The same formulas apply to each provider and the overall selection. Empty selections display guidance instead of metrics. The provider-day contract requires positive capacity and staffed hours. Zero-visit providers have no inferred revenue per visit, so their monetary opportunity is unknown, represented as zero in the modeled total with an explanatory insight.

Use `requirements-lock.txt` to reproduce the installed dependency versions.

## Executive dashboard

The dashboard includes seven KPI cards, linked specialty/clinic/provider filters, monthly visits and revenue trends, a utilization trend with a scenario target, and ranked provider productivity, utilization, and revenue charts. Specialty colors remain consistent across views. Provider comparisons reflect the selected period; volumes are not adjusted for visit complexity. Productivity normalizes visits by staffed hours.

If an existing development server retains old imported modules after an edit, restart it. Use `--server.fileWatcherType poll` when running without Watchdog.

## Advanced analytics

The generator defaults to 1,826 calendar days (five complete years including leap year 2024). Staffed weekdays exclude simulated leave. The fixed seed is reproducible. Date filters include both endpoints and apply to every metric, chart, benchmark, and opportunity rule.

Formulas and edge cases are documented next to calculations in `src/analytics.py`. Benchmarks include the provider in the currently selected specialty group. A peer count of one means a self-comparison; peer-gap detection requires at least two providers. The productivity index is provider visits/hour divided by weighted specialty visits/hour (1.0 = specialty average).

Opportunity detection flags utilization below the selected target, unbooked slots at least 15% of capacity, no-shows at least 10% of bookings, or utilization at least 5 percentage points below the specialty benchmark. These illustrative thresholds are not clinical standards. Multiple flags can describe the same unused slots; monetary opportunity is calculated once per provider, never summed across flags.

### Worked calculation

Provider A: capacity 100, bookings 80, completed visits 60, staffed hours 40, revenue $6,000.
Provider B in the same specialty: capacity 100, bookings 100, visits 90, hours 30, revenue $9,000.

- A utilization = 60 / 100 = 60%; productivity = 60 / 40 = 1.5 visits/hour.
- A unused slots = 100 − 60 = 40: 20 unbooked plus 20 no-shows.
- A booking rate = 80%; no-show rate = 20 / 80 = 25%.
- At an 85% target, A recoverable visits = max(0, 85 − 60) = 25.
- A observed revenue/visit = $6,000 / 60 = $100; estimated opportunity = 25 × $100 = $2,500.
- B exceeds the target, so its opportunity is $0.
- Specialty utilization = 150 / 200 = 75%; A gap = −15 percentage points.
- Specialty productivity = 150 / 70 = 2.142857; A productivity index = 1.5 / 2.142857 = 0.70.

These values and inclusive date filtering are asserted in the test suite.

## AI Executive Brief

`copilot_prompt.py` defines the healthcare operations policy, approved action catalog, and strict response schema. `ai_copilot.py` verifies synthetic provenance, calculates facts, calls the OpenAI Responses API, validates responses, and renders locally computed findings plus approved action text.

The AI prioritizes management actions; it cannot supply numbers or unrestricted narrative. Strongest and weakest mean highest and lowest utilization within the selection, with ties retained. This is not a clinical quality ranking or an adjustment for visit complexity.

### Configuration

Set `OPENAI_API_KEY` securely in the Streamlit server environment and `OPENAI_MODEL` to an available model supporting Responses API structured outputs. Restart Streamlit after changing its environment. Never commit credentials. `.env.example` lists variable names; `.env` files are ignored and are not loaded automatically.

The **AI Executive Brief** tab offers a local preview without credentials and a live generation button when configured. A live generation makes one API request and may incur charges. Inspect the calculated payload in the tab. Changed filters or targets hide stale results.

### Healthcare guardrails

Every selected row and column must match the default bundled synthetic dataset before transmission. Added fields, changed labels, and altered records are rejected. Only calculated aggregates, generated provider aliases, and fixed action text enter the API payload. No raw rows, dates, clinic labels, patient data, or chat input are sent. This deliberately blocks real-data use; it is not a general PHI detector or de-identification service.

The API uses a fixed HTTPS endpoint, timeouts, disabled redirects, and `store: false`. This is not a guarantee of zero provider-side retention or a HIPAA compliance claim. The app does not log credentials or requests. API errors are sanitized; refusals, incomplete responses, unknown action IDs, and additional output fields are rejected. The model has no tools and cannot take actions.

Recommendations are operational suggestions requiring human review. They cannot provide diagnosis, treatment, employment decisions, care denial, unsafe overbooking, or guaranteed financial outcomes. Revenue opportunity is a gross scenario excluding costs. Real-data use requires a separately reviewed privacy and governance architecture.

Reference: [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs). Tests mock the API; live generation requires configured credentials.

## Conversational copilot and evaluation

The Copilot tab includes suggested questions, session-only chat history (up to 20 exchanges), clear-chat, and explicit provider follow-ups. Changing the selected data or utilization target clears history to avoid stale answers. Chat text stays local; this version uses a conservative rule-based intent router, not an external language model. The AI Executive Brief remains a separate optional API feature.

Supported questions include unused-capacity rankings, modeled revenue opportunity, operational investigation priorities, productivity, summaries, and individual provider comparisons. Rankings retain ties. Revenue opportunities use the same selected-period calculations as the dashboard. Investigation priority is modeled revenue opportunity, not an employment or clinical-quality recommendation.

Unknown or filtered-out providers are refused. Dr. Patel resolves to the invented Dr. Maya Patel. Full names and unique doctor surnames are supported; unknown names are refused. Legacy Provider 01–48 aliases resolve by synthetic ID. For known providers, why-questions report unbooked/no-show decomposition and weighted specialty comparisons while explicitly refusing to infer causation. Forecasts, unsupported time comparisons, clinical advice, patient data, and employment decisions are refused. No user instruction can change the metric formulas. The router is intentionally limited and may refuse valid paraphrases; this is not a general-purpose assistant or a PHI detector. Do not enter PHI; clear chat to discard in-session text.

Run `.venv/bin/python scripts/evaluate_copilot.py` to regenerate `ai_evaluation.csv`. It records synthetic test questions, expected behavior, actual status, actual response, and PASS/FAIL. Assertions check independently calculated values, refusals, and provider follow-up resolution. Streamlit tests separately check history, suggestions, clearing, and filter resets. This basic behavioral evaluation is not a clinical safety certification or a live-model evaluation.


## Five-year analytical demo

The current CSV contains 58,858 provider-day records for 2021–2025. All 48 clinician names are invented for this demo; any resemblance to real people is coincidental. The specialties are Primary Care, Cardiology, Dermatology, Orthopedics, Neurology, Gastroenterology, Endocrinology, Pulmonology, Rheumatology, Urology, Ophthalmology, and Otolaryngology (four providers each).

Synthetic annual provider trends, seasonal booking variation, different no-show probabilities, and nominal annual revenue-rate growth make longitudinal comparisons useful. These are generation assumptions, not evidence about real healthcare. The external executive-brief provenance gate uses this updated canonical dataset and still rejects changed or extra records.

Reporting shortcuts offer all five years, the latest year, the latest two years, and custom dates. The annual scorecard marks incomplete observed years. Deeper suggested questions cover:

- Complete consecutive-year changes in visits, utilization, and revenue.
- Same-provider utilization improvement and decline across the latest two complete consecutive years.
- Specialty revenue opportunity and clinic weighted utilization.
- No-show rates with numerator and denominator, and unused-slot decomposition.
- Top-five revenue-opportunity concentration and gaps to specialty peers.
- A 90% utilization scenario without modifying the selected dashboard target.

All analyses use the current filters. Annual utilization = annual visits / annual staffed slots; productivity = annual visits / staffed hours. Utilization changes are percentage points; revenue growth = (current revenue / prior revenue − 1) × 100, undefined with a zero baseline. A year is complete only if the observed dates cover its first and last weekday; missing boundary days conservatively mark it partial. Improvement/decline comparisons join the same provider IDs in both years. Opportunity concentration = top-five provider opportunities / total opportunity, undefined when the total is zero. See src/deep_analysis.py for formulas and edge cases.

There are 14 suggested questions. The local copilot still cannot establish causes, assess clinical quality, forecast, or interpret arbitrary unsupported questions. ai_evaluation.csv now covers 26 cases, including deeper analyses and fictional-name resolution.

## Navigation and theme

The dashboard uses a plum/lavender palette. Filters are in a right-hand column rather than Streamlit's left sidebar. Expand Specialties, Clinics, or Providers to narrow the scope. The shorter tabs are Overview, Compare, Opportunities, Executive brief, and Ask copilot. Suggested questions are grouped into Quick answers, Trends, and Operational opportunities.

Date presets initialize the range widget directly with a distinct key for each preset. The widget owns its value, avoiding conflicting session-state defaults; incomplete date ranges display guidance instead of raising an exception.

## Continuous interruptible local voice

Open **Ask copilot → Voice conversation**, press **Start voice**, and allow microphone access. Speak in English and pause for about a second. The app transcribes locally, answers from the selected dashboard data, and reads the answer with a device-local English voice. Speaking again or pressing **Interrupt answer** immediately cancels playback; superseded responses are not spoken. **Stop voice** releases the microphone. Headphones are recommended because speaker echo can falsely trigger interruption. Sensitivity controls the volume threshold: lower values detect quieter speech.

Setup on another computer:

```sh
.venv/bin/python -m pip install -r requirements-voice.txt
.venv/bin/python scripts/setup_voice.py
```

The one-time setup downloads the public tiny.en model into ignored `.models/`. Runtime transcription uses faster-whisper on CPU with `local_files_only=True`; it does not call a cloud speech service. Audio is transported to this localhost Streamlit process and processed in memory, never intentionally written to disk. Transcripts and answers remain in session chat history; Clear chat removes that history and stops voice. Do not enter PHI. This local-only design assumes the app is run on localhost; deploying the server elsewhere would send audio to that server and needs a separate privacy review.

Browser speech synthesis is restricted to voices marked `localService`; if no local English voice is available, the answer is displayed and cloud voices are not used. Browser support and microphone permissions vary; use Chrome or Edge at localhost if the embedded browser cannot access audio. Microphone capture stops on Stop, filter/scope changes, Clear chat, page hiding, component hiding, or navigation away. Speech is segmented by an energy threshold and pauses, limited to 20 seconds per question. This is continuous listening with utterance-level transcription, not streaming partial transcription. CPU latency and recognition errors vary, particularly for fictional names. Read the transcript and repeat or type corrections as needed.

Validation includes audio bounds/format/silence checks, grounded/refused responses, JavaScript tests for stale/duplicate replies, interruption, stop, speech onset, and WAV resampling. Run `node tests/voice_frontend_test.cjs` for frontend checks. A synthetic spoken question is also tested through the installed model. Physical microphone, echo behavior, and audible playback require a user/device test and are not claimed as automatically verified.

### Natural-language date ranges

Copilot exchanges display newest first while preserving chronological context for follow-up questions. Enter a year alone, such as `2023`, for a full-calendar-year summary and provider, clinic, and specialty comparison tables within the current team selections.

Explicit copilot dates are parsed deterministically using Python's current date. Supported expressions include last/this year, last/this month, Q1–Q4 with optional year, month names with optional year, named or ISO start-to-end ranges, and “available period”. Missing years use the current year. Explicit dates override only the dashboard date window for that query; provider, specialty, and clinic selections remain in force. Undated questions keep the dashboard scope.

`src/date_ranges.py` returns requested and effective inclusive dates plus a coverage status. Missing or partial coverage produces an explanation without calculating an answer; it is not a safety refusal. Available queries filter raw provider-day rows before recalculating metrics, and show the effective dates in their grounding. Coverage checks compare dataset bounds; they do not prove that every provider has observations on every day. Visit counts are not unique patient counts.


### Answerability and recovery

The conversational copilot returns an answer when its supported analytics can resolve the question. For refusals and partial answers, it explains the limitation and offers three supported alternative questions. Alternatives are tailored to revenue requests, provider/causal requests, or general operations, and use an actual provider from the current selection. Empty selections explicitly require choosing available data first. Suggestions appear in both text and spoken replies; successful answers are unchanged.

### Comparative conversation (Release 1)

- `Compare July vs August 2025` compares weighted metrics on the same providers in both windows. `Compare July vs August` uses the current Python calendar year. A single supplied year applies to both months; explicit years on each month support cross-year comparisons.
- `year to date` / `YTD` means January 1 through today. `last 30 days` includes today and the preceding 29 days. The current demo ends in 2025, so newer requests correctly report unavailable data.
- `Compare Dr. Patel and Dr. Chen in July 2025` gives visits, utilization, no-show rate, revenue, revenue per visit, and unused capacity. Use actual selected roster names: Dr. Garcia is not in this demo. Unknown or ambiguous names require clarification. Collections are not measured and are never inferred from revenue.
- `Which providers are improving?` and `Whose utilization dropped the most?` default to the latest two complete calendar months inside the dashboard's observed date bounds. The chosen periods are printed in every answer. `Which no-show rates increased this month?` compares month-to-date with the same day numbers in the previous month (capped at that month's end). Explicit two-period questions can also request trends.
- Rate changes are **percentage points**. Count and currency changes show absolute change and percentage change, with an undefined relative change at a zero baseline. Rates with zero denominators are unavailable. Comparisons use providers observed in both periods and report excluded providers; they do not imply causal explanations or equal staffing exposure.
- Follow-ups remember structured provider, metric, and period context from the latest assistant response. After a unique no-show leader, ask `How does that compare with last month?` (previous calendar month relative to today's clock), or click **Compare with previous period** (relative to the prior answer's dates), **Estimate revenue impact**, or **Show provider trend**. Tied leaders need an explicit provider choice. Filter changes and Clear chat remove context; buttons use the same safety checks as text and voice.
- Both comparison windows must be within available date bounds before any comparison is calculated. Explicit dates override the dashboard date selection only for that query, preserving team selections. Grounding includes both dates, provider counts, and record counts. Bounds are not proof of daily completeness: absent provider-days may represent leave or unscheduled days.

No additional model API calls or credentials are needed for these features.

### Executive operations workspace (Release 2)

Open **Executive workspace** for:

- **Generate Executive Summary**: a local narrative with weighted selected-period KPIs, visit-volume and unused-capacity leaders, modeled revenue opportunity, and a separately labeled comparison of the latest two complete calendar months. It needs no API credentials. Changes to dashboard filters or the utilization target invalidate the saved summary.
- **Top Opportunities**: highest unused slots, highest observed no-show rate, lowest below-target utilization, largest modeled revenue opportunity, and the biggest available month-over-month utilization decline. Ties are retained. Categories overlap and have different units; do not add their impacts together. Unknown revenue rates are flagged rather than treated as zero opportunity.
- **Provider detail**: choose a provider to see separate dimensions and monthly changes without a composite score. Zero-booking rates and zero-visit revenue rates are unavailable; collections are not measured. Changing the detail selection does not change the dashboard team filters.
- **Specialty comparisons**: selected-specialty totals, weighted utilization and no-show rates, and sums of provider-level opportunities. Unknown provider revenue rates are counted. An entirely unknown specialty opportunity remains unavailable.
- **Explain a metric**: definitions tied to the actual formulas, denominators, zero-denominator behavior, and scenario assumptions.

In **Ask copilot**, try `Why did Dr. Patel's utilization decrease in August 2025?`, `Which specialty has the highest utilization?`, `Compare cardiology and primary care`, or `How is revenue opportunity calculated?`. A temporal “why” answer verifies the actual direction of utilization change and lists completed visits, capacity, bookings, and no-shows from both periods. It describes associations, not causes; cancellations and appointment mix are not measured. Existing safety checks run before these analytical routes.

Undated investigations and workspace trends use the latest two complete calendar months inside the selected observed date bounds. Explicit investigation periods are checked against dataset bounds and compared with the preceding window using Release 1's calendar rules. Missing or partial windows are explained without calculating a purported full-period change. Current-period totals remain usable when monthly trends are unavailable.

### Scenarios and ask-to-chart (Release 3)

Open **Scenarios** to choose providers and adjust independent utilization and no-show targets. An optional revenue-per-visit slider supplies a clearly labeled common assumption; without it, the model uses each provider's observed revenue rate. These controls do not change dashboard filters, dashboard targets, or chat scope.

No-show recovery = min(unused slots, max(0, observed no-shows − target no-show rate × bookings)). Utilization recovery = min(unused slots, max(0, target utilization × capacity − completed visits)). Each revenue estimate multiplies recovered visits by the observed or assumed rate. The scenarios overlap and must **not** be added together. Bookings and capacity remain fixed; estimates require demand and feasibility, exclude costs, and apply to exactly the selected analysis period. They are not collections, profit, forecasts, or automatically monthly amounts. Zero-visit revenue rates are unknown unless explicitly overridden; aggregate revenue totals exclude unknown rates and report their count.

In **Ask copilot → Scenarios and charts**, try:

- `What if Dr. Patel reduces no-shows from 14% to 8% in August 2025?` — the supplied starting rate is disclosed but the calculation uses observed counts, not the user's claim.
- `What if Dr. Patel reduces no-shows to 2% in August 2025 assuming $250 per visit?`
- `Chart monthly utilization by provider in 2025` — weighted sums, missing months shown as gaps, boundary months restricted to the requested dates.
- `Show no-show rates from highest to lowest in August 2025` — providers without bookings are excluded and counted rather than assigned a zero rate.

Chart requests select fixed Plotly builders; no generated code or LLM-guessed numbers are executed. Charts remain in chat history with their grounding and work through the same local voice-response path. Only the supported chart types are accepted. Explicit dates retain the established availability checks and selected-team scope. The synthetic roster contains Dr. Patel and Dr. Chen, not Dr. Garcia.

### Release 4: Data & Reporting

Open **Data source and CSV upload** above the dashboard to download the CSV
header template, stage a CSV, confirm column mappings, and activate it. Files
are limited to 20 MB, 200,000 rows and 100 columns. Dates must be ISO
`YYYY-MM-DD`; all twelve fields in the template are required. The app trims
identifier whitespace and converts numeric fields, but never imputes missing
measures, drops invalid rows, or silently repairs appointment counts.

Unique aliases such as `physician` and `appts_completed` are suggested.
Ambiguous aliases require a selection. Collections and cancellations are never
suggested as revenue and no-shows: they are different measures. Confirm the
field semantics and that the data is synthetic or verified non-PHI aggregate
provider-day data before activation. This attestation is not an automated PHI
detector. Do not upload patient-level data. Unmapped columns are discarded;
uploaded datasets cannot invoke cloud executive briefs, even if their provider
names resemble the demo roster. Conversation, summaries and reports run locally.

Validation finishes before the active dataset changes. A failed upload preserves
the previous dataset. Successful activation resets filter widgets to the new
roster/date bounds. **Restore synthetic demo** switches back. Uploads live only
in the current Streamlit session and do not overwrite the built-in CSV.

The **Data & Reporting** tab shows quality checks for the selected rows, including
nulls, invalid counts, duplicates, negative/infinite measures, inconsistent
identities and potential weekday gaps. Gaps may represent leave or unscheduled
days; completeness cannot be proven without a staffing roster. Invalid candidate
uploads show their checks before rejection.

**Generate Performance Report**, then **Export Performance Report**, creates a
local PDF with the exact selected rows, target, requested/observed dates, KPIs,
provider comparisons, monthly trends, opportunities, calculated executive
summary, quality notes and formulas. Reports are invalidated by scope or source
changes. Unknown rates remain unavailable; edge months may be partial. The
summary is deterministic, not an LLM-generated narrative. Install updated
`requirements.txt` for ReportLab; `requirements-dev.txt` includes the PDF test
reader. Run `python -m pytest` to verify onboarding and export behavior.

### Day 11: Semantic analytics layer

`src/semantic_metrics.py` is the reusable metric catalog and Pandas executor.
Each metric declares aliases, source columns, operation, formula, unit and
availability. Supported dimensions are provider (ID + name), clinic, specialty
and calendar month. It includes completed_visits, utilization, no_show_rate,
revenue, capacity, productivity, unused_capacity, revenue_per_visit,
revenue_opportunity and collections. **Collections is explicitly unavailable**
in the current data contract; the app never substitutes revenue.

`src/semantic_query.py` interprets compositional descriptive questions into an
allowlisted plan: metrics, dimensions, named providers, deterministic date range
and optional ranking. It filters raw dated rows before executing grouped metrics.
Without an explicit date, it uses the dashboard selection. Explicit dates retain
team filters and do not change dashboard controls. Partial/out-of-bounds dates
are explained without calculating a misleading partial result.

Examples:
- Show completed visits and utilization by clinic in 2025
- Show no-show rate by specialty and month in July 2025
- Show highest utilization by provider during the available period
- Show revenue opportunity by clinic
- Show completed_visits for Dr. Patel in July 2025

The copilot runs the safety check first and shows the structured plan under
**How this answer was calculated**. The catalog and examples are in **Ask
copilot → Semantic analytics: metrics and example questions**. Unknown filters
and dimensions are not guessed. This is a deterministic parser, not an LLM or
arbitrary SQL/code execution engine. Specialized comparison, trend, scenario,
chart and legacy narrative handlers remain available; comparison calculations
now reuse catalog definitions for their shared metrics.

Rollups sum first, then divide. Revenue opportunity sums independently modeled
provider opportunities within each group; an unknown provider revenue rate makes
that group's total unavailable. No-show/revenue-per-visit zero denominators are
unavailable, not zero. Rankings include all groups (ties retained); responses
show at most 100 groups with an explicit truncation note. These metrics measure
operations, not clinical quality or unique patients. Test fixtures verify
weighted rates, provider-rate opportunity, date filtering, aliases, dimensions,
safety and fail-closed interpretation.

### Days 12–13: Query plans and analytical memory

`src/query_planner.py` separates deterministic planning from validated Python
execution. A specialty period comparison produces a serializable plan containing
`metric`, `dimension`, `providers`, `specialties`, `period`,
`comparison_period`, explicit ISO ranges, and `comparison_kind`. The executor
independently validates the metric, entities, date bounds and operation before
filtering raw rows and calling the semantic catalog. No generated SQL or Python
is executed.

Try **Compare cardiology utilization Q3 2025 versus Q2 2025** against the built-in
data. **This quarter** means the full current calendar quarter, not quarter to
date; **last quarter** / **previous quarter** use the preceding calendar quarter,
including year rollover. Partial and missing periods produce availability
messages without partial calculations. Relative dates follow the Python clock,
so current 2026 queries are unavailable in the default 2021–2025 dataset.
Temporal plans compare matched providers and disclose exclusions. Change is the
first requested period minus the comparator; rate changes use percentage points.

`src/analytical_memory.py` stores versioned structured state on assistant turns:
provider references, metric, dates, dimension, comparison and specialty. It never
reads facts from generated answer text. A fingerprint binds state to the data,
team, selected dashboard rows and target. Clearing chat, changing scope, or a
failed/unsupported answer prevents stale references from being silently reused.
Tied or absent provider references require an explicit choice.

Example sequence (choose dates present in the dataset):
1. Which provider has the highest no-show rate?
2. How about August 2025?
3. Compare him with the specialty average.

The second turn retains the provider and metric, and updates the period. The
third retains that period and compares with the weighted same-specialty rate
within the selected team, including the provider. At least one other provider
must be present; otherwise the comparison is unavailable. Pronouns reference the
stored provider, without inferring gender. Explicit metric changes such as
“How about utilization last month?” replace the remembered metric. Specialty
averages support ratio metrics; count or dollar totals are not mislabeled as
averages. The UI exposes **Analytical memory** and the query plan for inspection.

`src/query_explanation.py` optionally adds **Explain this result with AI** for a
successful plan. It revalidates bundled-synthetic provenance and recalculates
facts before calling the existing structured-output adapter. Only allowlisted
numeric results and metric/unit IDs are sent—no raw rows, labels, question or
history. The model selects vetted management guidance; factual prose, numbers
and deltas remain Python-rendered. This is constrained AI interpretation, not
unrestricted generated commentary. Unknown action IDs are rejected. Uploaded
data is blocked and the button requires `OPENAI_API_KEY` and `OPENAI_MODEL` from
the server environment. Local planning, calculation and memory need no API key.
The adapter follows the [official Structured Outputs guide](https://developers.openai.com/api/docs/guides/structured-outputs).

### Days 14–15: Anomalies and associated-change investigations

The **Executive workspace → Anomalies and investigation** section automatically
screens the latest two complete calendar months within the selected date bounds.
`src/investigations.py` contains the calculations; `src/investigations_ui.py`
contains presentation. Copilot examples:

- Show anomalies
- Show anomalies in August 2025
- Why did revenue decline in August 2025?
- Investigate revenue decline
- Why did collections decline? (explains that collections are not measured)

An explicit month is compared with its preceding calendar month. Two explicit
periods separated by `versus` are ordered chronologically and must not overlap.
No-date questions use the latest two complete months within the dashboard
selection; explicit dates use raw dated rows while preserving team filters.
Partial or missing periods do not produce a full-period result.

Rules are documented demo heuristics, **not statistical significance tests**:
- Utilization: `(later / earlier - 1) <= -15%`, with at least 100 capacity slots
  in both periods. Also shows the separate percentage-point change.
- No-show spike: `100 * (later rate - earlier rate) >= 5` percentage points,
  with at least 30 bookings in both periods.
- Revenue falls while completed visits rise, with at least 100 slots per period.
- Provider utilization change differs by at least 15 percentage points from the
  median change of at least three **other** matched same-specialty providers,
  each meeting the capacity minimum. Self is excluded from this peer median.

Matched-provider screening discloses excluded providers. A lack of flags is not
evidence of normal performance. Schedule completeness, appointment complexity,
payer mix and clinical outcomes are not established by this dataset.

The revenue investigation compares visits, no-show rate, revenue per visit,
utilization, capacity, unused capacity and productivity. Collections and
cancellations remain explicitly unavailable. Its exact symmetric decomposition
uses `R = visits * revenue_per_visit`:

- volume component = `(V1 - V0) * (P0 + P1) / 2`
- rate component = `(P1 - P0) * (V0 + V1) / 2`

These sum to revenue change when both rates are defined. The largest negative
component is labeled an **arithmetic association**, never a root cause. Zero-visit
rates cannot be decomposed. Provider mix shows newly/no-longer observed IDs,
their revenue, and visit-share redistribution (`0.5 * sum(abs(share1-share0))`).
Observation changes are not assumed to be hires or departures. Provider mix can
affect aggregate revenue per visit, so these are not additive causal effects.
All investigation text is grounded, deterministic and local; no PHI or model
calls are needed. The existing clinical and employment guardrails still run first.

### Publication-ready answerability and supported-question guidance

Every non-successful copilot route now uses `src/answerability.py` to preserve
its limitation or safety explanation and offer three relevant supported
questions. Suggestions come from a bounded catalog (overview, revenue,
appointments, definitions) and are checked through the internal router against
the same data and application clock before display. Probing does not call a
model, recurse into the public responder, or mutate conversation memory.
Date-specific failures do not suggest hard-coded unavailable years. Unavailable, partial and invalid requests offer relevant metric-definition questions without triggering aggregation for a different period. Empty data
selections receive metric-definition questions that work without records.

In **Ask copilot**, open **Supported questions — choose one** to run a catalog
question, or click an alternative below the newest unsupported answer. Selected
questions use the current dashboard scope. Text and voice share the same
response policy. Safety restrictions, data coverage explanations and unknown
metrics are retained; an unsupported request is not silently converted into a
different analysis. This is a bounded operations copilot, not a promise to answer
arbitrary general, clinical, identifying or causal questions.
