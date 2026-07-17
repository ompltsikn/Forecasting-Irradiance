# S0-2 COV Characterisation Design

**Status:** Approved in conversation; awaiting review of this written specification
**Date:** 2026-07-17
**Site:** PLTS-IKN
**Contract sources:** `PRD_Forecasting_Irradiance_ML.md`, `MASTER_CONTEXT_Forecasting_Irradiance_ML.md`, and `ROADMAP_Forecasting_Irradiance_ML.md`

## 1. Goal

Build the Sprint 0 change-of-value (COV) characterisation workflow for the PLTS-IKN SCADA export. The workflow must read the raw ZIP/CSV event data, characterise every observed tag, recover defensible deadband and reporting-cadence evidence, and make a data-backed `canonical_freq` decision without building a model or a production resampler.

The implementation is complete only when it:

- reconciles the Shared Drive `raw_data` inventory with the local input inventory;
- reads every CSV entry from every ZIP while preserving ZIP, CSV, and row provenance;
- characterises all 136 observed tags;
- separates instantaneous irradiance, irradiance accumulation, and meteorological tags;
- estimates per-tag deadband, inter-arrival p50/p90/p99, maximum gap, and an observed heartbeat candidate where the evidence supports one;
- separates active-irradiance intervals from night/flat-zero intervals;
- derives `canonical_freq` from the 26 instantaneous irradiance tags only;
- produces deterministic tables, plots, a manifest, and `docs/phase0_cov_characterisation.md`;
- provides an editable Colab notebook that runs the same code as the CLI and tests; and
- updates the normative Sprint 0 ledgers according to the actual evidence.

## 2. Non-goals

This work does not include:

- any forecasting model, including persistence;
- production COV-to-grid resampling;
- feature engineering or rolling-window construction;
- QC state-machine implementation beyond the diagnostics needed to characterise COV behaviour;
- the S0-3 `GHI - DHI - DNI*cosZ` residual test;
- the S0-5 historical coverage, maintenance, outage, or empirical regime audit;
- interpreting `object_caeid` as a quality flag without source-system evidence;
- asserting that a configured historian deadband or max-report-time has been recovered when only an empirical candidate is visible; or
- embedding OAuth JSON, rclone configuration, Drive tokens, or any other credential.

## 3. Evidence baseline established before design

The following facts were measured from the current inputs and define the initial acceptance baseline:

| Evidence | Observed value |
|---|---:|
| Shared Drive `raw_data` ZIP files | 145 |
| Local `raw_data` ZIP files | 145 |
| Shared Drive/local metadata reconciliation | exact filename and byte-size match |
| Total ZIP bytes in each inventory | 23,776,109 |
| CSV entries inside ZIPs | 170 |
| Populated CSV entries | 163 |
| Zero-byte CSV entries | 7 |
| ZIPs containing more than one CSV | 9 |
| Maximum CSV entries in one ZIP | 9 |
| Unique full SCADA tags | 136 |
| Unique raw parameter labels | 40 |
| Data rows | 2,656,231 |
| Malformed-width rows in the initial scan | 0 |
| Non-numeric value rows in the initial scan | 0 |
| Within-entry timestamp order inversions | 12 |
| Timestamp representation | naive, fractional seconds on every row |
| `object_caeid` observed value | `0` on every row |
| Coverage as recorded | 2026-06-01 through 2026-06-30 |

The actual CSV contract differs from the earlier verbal description. The three-column header is:

```text
date_time ; <full SCADA tag> ; object_caeid
```

The full tag is the second **header name**. The second field in every data row is the numeric observation value. The third field is retained verbatim as `object_caeid_raw`; this design assigns it no quality semantics.

The separate `Data Weather Station` Shared Drive folder contains 2,028 XLSX files (approximately 2.65 GB) arranged by year, weather station, and period. Those workbooks are useful reference products but are not authoritative for COV deadband because their transformation and resampling history is not established. The raw ZIP events are the authoritative S0-2 source.

The connector exposed Drive filename and byte-size metadata but not a content hash. The current reconciliation therefore proves metadata equality, not byte-for-byte Drive equality. The notebook closes that gap on rerun by hashing the mounted Drive files after copying them to the Colab VM and comparing them with the committed source manifest.

## 4. Architecture

```text
Drive raw_data or local raw_data
             |
             v
inventory + SHA-256 reconciliation
             |
             v
ZIP/CSV reader with row provenance
             |
             v
tag parser + canonical mapping + class label
             |
             v
pre-sort integrity audit
             |
             v
stable sort + exact dedup + conflict quarantine
             |
             v
per-tag COV statistics (all 136 tags)
             |
             +------> active instantaneous irradiance evidence (26 tags)
             |                         |
             |                         v
             |              canonical_freq decision
             v
deterministic CSV/JSON/PNG artifacts
             |
             v
phase0_cov_characterisation.md + config/docs ledger updates
```

The implementation is library-first. The notebook contains editable configuration and orchestration only; it does not reimplement parsing, mapping, statistics, or report logic.

## 5. Repository components

| Path | Responsibility |
|---|---|
| `src/characterisation/__init__.py` | Public package exports |
| `src/characterisation/cov_contract.py` | Tag identity, STS/WB/EMI validation, raw-to-canonical aliases, and parameter classification |
| `src/characterisation/cov_ingest.py` | Inventory, SHA-256, ZIP/CSV parsing, row provenance, timestamp-shape audit, ordering, duplicate, and conflict handling |
| `src/characterisation/cov_stats.py` | Delta distributions, deadband estimation, inter-arrival statistics, active/flat split, heartbeat evidence, and canonical-frequency decision |
| `src/characterisation/cov_artifacts.py` | Stable tables, JSON manifest, plots, and Markdown rendering |
| `src/characterisation/cov_cli.py` | Single CLI entry point shared by Windows, CI, and Colab |
| `notebooks/S0_2_COV_Characterisation.ipynb` | Editable Colab runner, Drive mount/copy, invocation, and artifact display |
| `artifacts/phase0_cov/` | Committed evidence tables, plots, and source manifest |
| `docs/phase0_cov_characterisation.md` | Required human-readable S0-2 report |
| `requirements-cov.txt` | Pinned runtime, plotting, notebook, and test dependencies |
| `tests/unit/test_cov_contract.py` | Tag parsing, EMI validation, aliases, and classification |
| `tests/unit/test_cov_ingest.py` | ZIP/CSV, multi-entry, empty, malformed, timestamp, ordering, duplicate, and conflict behaviour |
| `tests/unit/test_cov_stats.py` | Deadband, inter-arrival, active/flat, heartbeat, and frequency rules |
| `tests/unit/test_cov_artifacts.py` | Stable schemas, formatting, plots, manifest, and Markdown |
| `tests/integration/test_cov_pipeline.py` | Synthetic end-to-end pipeline and strict failure contract |
| `tests/integration/test_cov_notebook.py` | Notebook structure and local non-Drive execution contract |

The production entry point is:

```text
python -m src.characterisation.cov_cli
```

## 6. Tag parsing and canonical mapping

### 6.1 Full-tag parser

The parser uses the second CSV header name, never the ZIP or CSV filename. It accepts insignificant surrounding whitespace but requires this logical structure:

```text
PLTS IKN / STSxx / WBxx_EMIxx / MEAS / parameter
```

It extracts:

- `site_label`;
- `sts`;
- `wb`;
- `emi`;
- `raw_parameter`; and
- the original full tag unchanged.

The STS/WB/EMI tuple must match the approved mapping:

| EMI | STS | WB |
|---|---|---|
| EMI01 | STS09 | WB09 |
| EMI02 | STS05 | WB05 |
| EMI03 | STS06 | WB06 |
| EMI04 | STS04 | WB04 |
| EMI05 | STS02 | WB02 |

A syntactically valid tag with a mismatched tuple is not silently repaired. It is recorded as a contract error and causes strict execution to fail after diagnostic artifacts are written.

### 6.2 Canonical parameter names

Matching is case-insensitive and whitespace-normalized. The canonical spelling deliberately preserves `Acummulation` as approved by the product owner.

For EMI01-EMI04, the mapping includes:

- `DIFFUSE HORIZONTAL IRRADIANCE (DHI)` -> `Diffuse Horizontal Irradiance (DHI)`;
- `DHI DAILY ACCUM` -> `DHI Daily Acummulation`;
- `DHI MONTHLY ACCUM` -> `DHI Monthly Acummulation`;
- `DHI YEARLY ACCUM` -> `DHI Yearly Acummulation`;
- `DIRECT HORIZONTAL IRRADIANCE (DNI*cosZ)` -> `Direct Horizontal Irradiance (DNIcosZ)`;
- `DNI*cosZ DAILY ACCUM` -> `DNIcosZ Daily Acummulation`;
- `DNI*cosZ MONTHLY ACCUM` -> `DNIcosZ Monthly Acummulation`;
- `DNI*cosZ YEARLY ACCUM` -> `DNIcosZ Yearly Acummulation`;
- `GLOBAL HORIZONTAL IRRADIANCE (GHI)` -> `Global Horizontal Irradiance (GHI)`;
- `GHI DAILY ACCUM` -> `GHI Daily Acummulation`;
- `GHI MONTHLY ACCUM` -> `GHI Monthly Acummulation`;
- `GHI YEARLY ACCUM` -> `GHI Yearly Acummulation`;
- `GLOBAL INCLINED IRRADIANCE (POA)` -> `Global Inclined Irradiance (POA)`;
- `POA DAILY ACCUM` -> `POA Daily Acummulation`;
- `POA MONTHLY ACCUM` -> `POA Monthly Acummulation`;
- `POA YEARLY ACCUM` -> `POA Yearly Acummulation`;
- `IN-PLANE REAR-SIDE IRRADIANCE (RSI) 01|02|03` -> the same title-cased canonical name; and
- `RSI DAILY|MONTHLY|YEARLY ACCUM 01|02|03` -> `RSI 01|02|03 Daily|Monthly|Yearly Acummulation`.

The EMI05 aliases are:

- `Total Irradiance` -> `Global Horizontal Irradiance (GHI)`; and
- `Daily radiation` -> `GHI Daily Acummulation`.

Every tag receives one class:

- `instantaneous_irradiance`;
- `irradiance_accumulation`; or
- `meteorological`.

The expected current distribution is 26 instantaneous irradiance tags, 76 irradiance accumulation tags, and 34 meteorological tags. The run reports the measured distribution and fails strict validation if the current source manifest no longer matches that approved classification without an explicit mapping update.

## 7. Input reconciliation and ingestion

### 7.1 Inventory contract

For each ZIP, the manifest records:

- relative path;
- filename;
- byte size;
- SHA-256;
- CSV entry count;
- populated/empty entry count; and
- uncompressed byte total.

The current Drive-to-local preflight compares filenames and byte sizes because those are the fields exposed by the Drive connector. The actual analysis computes SHA-256 over the local bytes. In Colab, every mounted Drive ZIP is copied to VM-local storage, hashed, and checked against the committed manifest before analysis.

No analysis reads repeatedly from DriveFS. A copy failure, missing ZIP, extra ZIP, size mismatch, or hash mismatch is fatal in strict mode.

### 7.2 CSV contract

The reader:

- opens ZIPs without extracting them to the repository;
- processes every `.csv` entry;
- accepts the observed UTF-8/UTF-8-BOM, semicolon-delimited, quoted format;
- treats a zero-byte CSV as an explicit empty-entry exception;
- requires exactly three header fields for populated entries;
- parses the tag from header field two;
- parses `date_time`, numeric value, and `object_caeid_raw` from each row; and
- preserves `source_zip`, `source_csv`, and one-based `source_row`.

Malformed-width, unparseable-timestamp, or non-numeric rows are written to the exception ledger with raw content and reason. Strict mode completes diagnostic artifacts and then exits non-zero if any populated row is excluded.

### 7.3 Ordering, duplicates, and conflicts

Ordering violations are counted before any sort. Statistics use a stable ordering by:

```text
(full_tag, parsed_event_time, source_zip, source_csv, source_row)
```

An exact duplicate has identical tag, timestamp, numeric value, and `object_caeid_raw`; only one copy enters statistics, and the removed count remains in the report.

Rows sharing tag and timestamp but carrying different values or different `object_caeid_raw` are conflicts. All rows for that conflicted tag/timestamp are quarantined from delta and inter-arrival statistics. The conflict appears in the exception ledger and makes strict execution fail.

## 8. Timestamp semantics

The ingestion layer classifies every raw timestamp as:

- naive;
- offset-aware;
- UTC/Z;
- invalid; or
- mixed at the dataset level.

It preserves `event_time_raw` and a parsed representation. It does not name a naive timestamp `event_time_utc` and does not apply the configured site timezone merely because `Asia/Makassar` is known.

Inter-arrival durations are invariant under a single fixed timezone offset, so S0-2 statistics can proceed on consistently naive timestamps without pretending their timezone is settled.

For the five forecast channel groups, the artifact set includes an hour-of-day diagnostic of non-flat irradiance. It compares the observed daily active window as recorded with the consequences of interpreting that clock as WITA or UTC. The report may conclude that the data are **consistent with naive WITA** when the evidence is strong, but it still distinguishes empirical consistency from a historian configuration record or clock audit.

If timestamp shapes are mixed, if a daylight pattern is inconsistent, or if the source contains offset-aware values with conflicting offsets, strict execution fails and `canonical_freq` remains unresolved.

## 9. Per-tag statistics

All 136 tags receive one output row, including tags with too little information for a supported estimate.

Required fields include:

- tag identity, STS, WB, EMI, raw parameter, canonical parameter, and class;
- event count before and after exact deduplication;
- source ZIP and CSV counts;
- coverage start/end as recorded;
- order-violation, exact-duplicate, timestamp-conflict, and excluded-row counts;
- zero-change and non-zero-change counts;
- positive `|delta value|` minimum, p01, p05, p50, p90, and p99;
- deadband estimate, support, dispersion, confidence, and unresolved reason;
- inter-arrival p50, p90, p99, and maximum gap for all intervals;
- active-irradiance and flat/night inter-arrival metrics where applicable;
- heartbeat candidate, support, confidence, and unresolved reason; and
- maximum observed active gap with sibling-tag liveness evidence where applicable.

Instantaneous and accumulation tags are never pooled for a statistic or plot without retaining their class label.

## 10. Deadband estimator

For each tag after conflict quarantine, stable sorting, and exact deduplication:

1. Compute consecutive absolute value differences.
2. Count exact zero and positive differences separately.
3. Preserve the full positive-delta distribution metrics.
4. Sort positive deltas and group adjacent values using `isclose(rtol=5e-4, atol=1e-6)`. This absorbs the observed float32 export jitter around decimal steps without rounding the raw values.
5. Starting from the lower edge, select the first cluster with support of at least `max(20, ceil(0.001 * n_positive))`.
6. Use that cluster median as the empirical deadband candidate.
7. Count smaller unsupported positive deltas as lower-edge anomalies rather than silently discarding them.

Confidence is deterministic:

- `high`: cluster support is at least 5% of positive deltas and relative median absolute deviation is at most 1%;
- `medium`: support is at least 1% and relative median absolute deviation is at most 5%;
- `low`: the cluster passes the minimum support rule but not the stronger rules; and
- `unresolved`: no cluster passes the minimum support rule or fewer than 20 positive deltas exist.

The report presents the candidate as an empirical COV floor. It does not call it the configured historian deadband without corroborating configuration evidence.

## 11. Inter-arrival, active/flat split, and maximum gaps

All valid consecutive event intervals contribute to the all-period p50/p90/p99 and maximum gap.

For `instantaneous_irradiance`, intervals are additionally classified using the two endpoint values. An interval is active when either endpoint magnitude exceeds:

```text
max(5 * supported_deadband_candidate, 5 W/m2)
```

The 5 W/m2 floor is tied to the PRD's approximately -4 W/m2 instrument-offset allowance rather than an assumed sunrise time. If the deadband is unresolved, the threshold is 5 W/m2 and that dependency is disclosed.

Intervals below the threshold are reported as `flat_or_night`. This avoids making every overnight silence look like a communication outage. The report does not claim that every flat interval is night; the label intentionally preserves the ambiguity.

For each unusually long instantaneous-tag gap, the pipeline counts events from sibling instantaneous tags in the same EMI during that gap. A long gap with active endpoints and substantial sibling activity is evidence of tag-specific silence; a gap with no sibling activity remains ambiguous.

## 12. Heartbeat and max-report-time evidence

After exact duplicate removal, consecutive events with identical values are the primary heartbeat evidence because a pure COV stream would otherwise have no reason to repeat an unchanged value.

The estimator clusters same-value inter-arrival durations after rounding only for clustering display, retains the raw durations in tables, and accepts a heartbeat candidate only when:

- there are at least 20 same-value intervals;
- the dominant interval cluster contains at least 10% of those intervals; and
- the cluster coefficient of variation is at most 10%.

The candidate output includes its median seconds, support count, support fraction, and confidence. Day/active and flat/night evidence are shown separately.

Even a high-confidence periodic candidate is labelled `observed_heartbeat_candidate_s`. The field `configured_max_report_time_status` remains `unknown` unless a historian configuration, export setting, or equivalent source-system record confirms it.

If no stable candidate exists, that is a valid measured result. It is reported as `not_detected` or `insufficient_evidence`, not zero and not an invented max-report-time.

## 13. `canonical_freq` decision rule

Only the 26 `instantaneous_irradiance` tags enter the decision pool. The 76 accumulation tags and 34 meteorological tags remain fully characterised but cannot select the forecasting grid.

The instantaneous tags are grouped into the five product channels:

- GHI, including the EMI05 `Total Irradiance` alias;
- DHI;
- DNIcosZ;
- POA; and
- RSI, including sensor positions 01, 02, and 03.

For each supported tag, use the active-interval p50. Then calculate the median of those p50 values within each channel group. The decision statistic is the slowest of the five channel-group medians.

Evaluate the contract candidates in order:

```text
1min, 5min, 15min
```

Select the first candidate whose duration is not finer than the decision statistic. If any product channel has no supported active tag, or the decision statistic exceeds 15 minutes, `canonical_freq` is unresolved and the config is not pinned.

The evidence table also reports:

- every tag whose active p50 is slower than the selected grid;
- the share of supported tags at or faster than the selected grid;
- the channel-group medians;
- p90/p99 context; and
- whether the data show sub-minute headroom.

The workflow does not select a sub-minute production grid. The normative product candidates begin at 1 minute; faster COV reporting is evidence that 1 minute is supported, not a new product requirement.

## 14. Artifact contract

The committed output directory contains at least:

| Artifact | Content |
|---|---|
| `source_manifest.csv` | Per-ZIP size, SHA-256, and entry counts |
| `inventory_reconciliation.csv` | Drive/local filename and byte-size comparison |
| `empty_csv_entries.csv` | All seven empty CSVs with ZIP/CSV provenance |
| `row_exceptions.csv` | Malformed, invalid, and conflict quarantine ledger; header-only when empty |
| `timestamp_audit.csv` | Per-entry timestamp shapes, order violations, and as-recorded coverage |
| `tag_characterisation.csv` | Complete 136-tag metrics |
| `canonical_frequency_evidence.csv` | Per-tag and per-channel evidence plus final decision |
| `run_manifest.json` | Input-set digest, code/config schema versions, counts, strict status, and artifact hashes |
| `figures/deadband_instantaneous.png` | Instantaneous-tag lower-edge evidence |
| `figures/interarrival_instantaneous.png` | All/active/flat inter-arrival comparison |
| `figures/canonical_frequency_evidence.png` | Channel medians against candidate grids |
| `figures/timestamp_daylight_alignment.png` | Hour-of-day irradiance activity evidence |
| `figures/gap_heartbeat_evidence.png` | Maximum-gap and heartbeat support summary |

Tables are sorted by stable identity keys, floats use fixed documented formatting, JSON keys are sorted, and plots use fixed dimensions/style. `run_manifest.json` records the SHA-256 of every other committed artifact; the manifest's own SHA-256 is reported by the CLI and release verification to avoid an impossible self-referential hash. Re-running on the same source bytes, code, and config produces byte-stable analytical tables and plots; notebook display timestamps are not part of the committed artifacts.

`docs/phase0_cov_characterisation.md` is rendered from those same tables and includes:

- executive decision and caveats;
- source reconciliation and empty-entry exceptions;
- actual CSV/schema correction;
- timestamp-semantics evidence;
- methods and thresholds;
- five-channel canonical-frequency evidence;
- heartbeat/max-report-time outcome;
- complete per-tag appendix or a generated table covering all 136 tags;
- artifact links; and
- S0-2 acceptance status and remaining blocker, if any.

## 15. Colab notebook contract

The notebook exposes one clearly marked editable configuration cell with:

- repository root or clone URL;
- mounted Drive raw-data directory;
- VM-local staging directory;
- output directory;
- strict-mode flag; and
- optional environment-variable overrides for local verification.

Its execution flow is:

1. install `requirements-cov.txt`;
2. mount Google Drive only when running in Colab and not explicitly disabled;
3. enumerate the mounted source;
4. copy every ZIP to VM-local storage;
5. verify count, size, and SHA-256 against the source manifest;
6. invoke the library entry point;
7. display the summary, decision, exception counts, and plots; and
8. copy final artifacts to the configured Drive output directory when requested.

The notebook contains no business logic and no credential material. A local execution mode allows the test suite to execute the notebook against synthetic fixtures and allows final verification against the local 145-ZIP dataset without Drive mounting.

## 16. Failure policy

| Condition | Behaviour |
|---|---|
| Empty CSV entry | Record explicitly; continue |
| Multi-CSV ZIP | Process every entry; preserve provenance |
| Missing/extra ZIP, size mismatch, or hash mismatch | Write reconciliation evidence; strict failure |
| Corrupt/unreadable ZIP | Record source failure; strict failure |
| Unexpected populated CSV header | Record exception; strict failure |
| Invalid tag structure or STS/WB/EMI tuple | Record contract error; strict failure |
| Unknown meteorological parameter | Preserve raw name and classify meteorological; warn |
| Unknown irradiance-like parameter | Record mapping error; strict failure |
| Malformed row, invalid timestamp, non-numeric value | Quarantine row; strict failure after artifacts |
| Exact duplicate | Deduplicate for statistics; report count |
| Same tag/timestamp with conflicting data | Quarantine timestamp; strict failure |
| Mixed timestamp semantics | Report; strict failure; no frequency decision |
| Insufficient deadband or heartbeat evidence | Mark unresolved; do not invent a value |
| Missing supported product channel for frequency decision | Leave `canonical_freq` unresolved |

This policy permits a diagnostic report to exist when source defects are present while preventing a partial run from being labelled complete.

## 17. Testing strategy

Implementation follows red-green-refactor. Every production behaviour begins with a failing test that fails for the intended missing behaviour.

Unit and integration coverage includes:

- valid and invalid full-tag parsing;
- every EMI tuple and all approved irradiance aliases;
- EMI05 `Total Irradiance` and `Daily radiation` aliases;
- canonical `Acummulation` spelling;
- all three parameter classes and the expected current 26/76/34 split;
- one- and multi-CSV ZIPs;
- zero-byte CSVs;
- BOM, delimiter, and quoted headers;
- malformed width, timestamp, and numeric values;
- naive, offset-aware, UTC/Z, and mixed timestamp inputs;
- pre-sort order-violation counting;
- exact duplicate removal and conflicting-timestamp quarantine;
- known-deadband synthetic series with float32-like jitter;
- unsupported lower-edge outliers and insufficient evidence;
- inter-arrival p50/p90/p99 and maximum gap;
- active versus flat/night classification;
- stable and unstable heartbeat candidates;
- all five channel-group medians and each candidate frequency outcome;
- unresolved frequency when a product channel is missing;
- deterministic CSV/JSON/Markdown/PNG output;
- strict versus diagnostic failure behaviour;
- CLI argument/config handling; and
- notebook local execution without Drive.

The full-data verification is separate from CI because raw plant data is not committed. It must prove that all 145 ZIPs and 170 CSV entries were considered and that every one of the 136 tags appears in the output.

## 18. Documentation and status updates

After the measured run:

- set `configs/site_plts-ikn.yaml` `canonical_freq` only if the decision rule resolves it;
- write the complete `docs/phase0_cov_characterisation.md`;
- update the PRD, Master Context, and Roadmap Sprint 0 ledgers with exact counts, evidence, and artifact links;
- keep Gate M0 separate from S0-2 status; and
- keep Phase 1 and all modelling NO-GO regardless of S0-2 outcome.

S0-2 becomes complete only if its required report, per-tag evidence, heartbeat/max-report-time conclusion, and data-backed frequency decision satisfy the normative acceptance language. If configured max-report-time remains unconfirmed or another evidence requirement is unresolved, the ledger remains yellow with the exact blocker rather than being forced green.

The release audit also rechecks the time-sensitive S0-1 observation gate. S0-1 is updated only if two successive six-hour ECMWF issue cycles were written by qualifying GitHub `schedule` events after the Shared Drive cutover. Manual and pre-cutover runs do not count.

## 19. Verification and release

Before any completion claim or push:

1. run the focused COV unit and integration tests;
2. run the complete repository test suite and report the exact pass/fail count;
3. execute the CLI in strict mode against all 145 local ZIPs;
4. execute the notebook in local mode against the same input;
5. verify artifact schemas, row counts, file hashes, plots, and Markdown links;
6. inspect the complete git diff and confirm no raw data or credentials are tracked;
7. verify the live S0-1 schedule evidence separately;
8. commit the implementation and evidence;
9. push `main` to `ompltsikn/Forecasting-Irradiance`; and
10. push the identical commit to `nabilhaidr/Forecasting-Irradiance` and verify both remote SHAs.

## 20. Acceptance criteria

The implementation is accepted when fresh evidence proves all applicable items below:

- [ ] 145 local ZIPs reconcile with the Drive inventory by filename and byte size.
- [ ] Every processed ZIP has a SHA-256 in the source manifest.
- [ ] All 170 CSV entries are represented, including the 7 empty entries.
- [ ] All 136 tags have a row in `tag_characterisation.csv` and the Markdown report.
- [ ] Tag parsing is independent of ZIP and CSV filenames.
- [ ] The 26 instantaneous irradiance tags alone drive the frequency decision.
- [ ] Accumulation and meteorological statistics remain separately labelled.
- [ ] Timestamp semantics and the lack of embedded offset are reported without an unjustified conversion.
- [ ] Deadband, inter-arrival p50/p90/p99, maximum gap, and heartbeat evidence are present per tag or carry an explicit unresolved reason.
- [ ] Night/flat-zero intervals are not automatically labelled outages.
- [ ] `canonical_freq` is selected by the approved rule or remains explicitly unresolved.
- [ ] The notebook runs the library rather than reimplementing it.
- [ ] Tests and full-data execution pass their applicable strict gates.
- [ ] No model, credential, or raw plant data is committed.
- [ ] PRD, Master Context, and Roadmap reflect the exact evidence-backed status.
- [ ] Both GitHub remotes point to the same released commit.

## 21. Known limitations that remain visible

- The raw COV extract currently covers only June 2026. It supports event-cadence characterisation but not a full seasonal or historical-availability claim.
- Filename and size equality with the Drive connector is not content-hash equality. The Colab copy-and-hash gate supplies byte evidence when run against the mounted Drive.
- Daylight alignment can strongly support naive WITA semantics but does not replace a historian clock/configuration record.
- An empirical repeated-value cadence can reveal a heartbeat candidate but may not prove the configured historian max-report-time.
- Maximum observed gaps in one month are observations, not guaranteed upper bounds for future operation.
