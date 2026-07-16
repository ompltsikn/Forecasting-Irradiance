# S0-1 NWP Archiver Design

**Status:** Approved in conversation; awaiting review of this written specification
**Date:** 2026-07-16
**Site:** PLTS-IKN
**Contract sources:** `PRD_Forecasting_Irradiance_ML.md`, `MASTER_CONTEXT_Forecasting_Irradiance_ML.md`, and `ROADMAP_Forecasting_Irradiance_ML.md`

## 1. Goal

Build the Sprint 0 NWP archiver that continuously captures ECMWF Open Data forecasts as issued for the PLTS-IKN grid cell. The archive must preserve forecast provenance and grow from day zero without building a model.

The implementation is complete only when it:

- archives both IFS and AIFS Single forecasts;
- records issue, valid, and actual retrieval times separately in UTC;
- extracts the nearest site grid cell and writes validated Parquet;
- runs idempotently from GitHub Actions;
- uploads committed runs to the configured Google Drive destination; and
- demonstrates growth across at least two successive ECMWF issue cycles.

## 2. Non-goals

This work does not include:

- MOS or bias-correction training;
- GHI-to-DNI/DHI separation;
- clear-sky-index temporal downscaling;
- ERA5 substitution or third-party historical backfill beyond ECMWF's current rolling window;
- LightGBM, deep learning, or any other forecasting model;
- NWP-to-SCADA matching; or
- production backup/RPO/RTO design beyond retaining the archive in Google Drive.

## 3. Fixed inputs and decisions

| Item | Decision |
|---|---|
| Site ID | `PLTS-IKN` |
| Site latitude | `-0.9911713315158186` |
| Site longitude | `116.63811127764585` |
| Site timezone | `Asia/Makassar`; storage remains UTC |
| ECMWF client source | `google`, the mirror already proven by the Colab smoke test |
| ECMWF models | API names `ifs` and `aifs-single` |
| IFS horizon | 00/12 UTC: 0 through +144 h every 3 h; 06/18 UTC: 0 through +90 h every 3 h |
| AIFS horizon | 0 through +144 h, every 6 h |
| Spatial method | nearest grid point, selected locally from each GRIB message |
| Scheduler | canonical GitHub repository `ompltsikn/Forecasting-Irradiance` |
| Drive destination | GitHub variable `NWP_DESTINATION`, initially `gdrive:_staging/nwp` |
| Scheduler gate | GitHub variable `NWP_ARCHIVER_ENABLED`, initially `false` |
| Credential | GitHub secret `RCLONE_CONFIG_B64` |

ECMWF Open Data does not perform server-side `area` cropping through the Python client. The archiver therefore downloads only the required parameter/step GRIB messages and extracts the nearest site grid point locally. The first decoded field supplies the actual grid coordinates; the implementation must not hard-code the mathematically expected `-1.0, 116.75` point.

## 4. Architecture

```text
GitHub Actions trigger
        |
        v
discover latest complete run and retained candidate cycles
        |
        v
check Drive for an existing committed manifest
        |
        +---- committed run exists ---> clean skip
        |
        v
retrieve selected GRIB messages with explicit issue time
        |
        v
decode nearest PLTS-IKN grid point with ecCodes
        |
        v
validate schema, timestamps, horizons, and units
        |
        v
write local Parquet + SHA-256 manifest
        |
        v
rclone upload data first, manifest last
        |
        v
Drive Bronze archive
```

The Python code owns ECMWF discovery, retrieval, decoding, normalization, validation, and local artifact creation. The workflow owns secret reconstruction, Drive existence checks, upload, scheduling, and cleanup. Python never parses or stores the rclone credential.

## 5. Repository components

| Path | Responsibility |
|---|---|
| `src/ingestion/nwp_archiver.py` | ECMWF discovery, explicit-run retrieval, nearest-grid extraction, normalization, validation, and CLI |
| `data_contracts/nwp_schema.py` | Canonical column names, types, primary key, nullability, and dataframe validation |
| `tests/unit/test_nwp_archiver.py` | Request profiles, grid metadata, timestamps, paths, manifests, and idempotency helpers |
| `tests/unit/test_units.py` | SSRD accumulation/de-accumulation and J/m2-to-W/m2 conversion |
| `tests/leakage/test_nwp_issue_time.py` | Issue/valid/retrieval discipline and measured dissemination latency |
| `tests/integration/test_nwp_parquet.py` | Local synthetic GRIB-to-Parquet contract test |
| `scripts/start_nwp_archiver.sh` | Reproducible Linux entry point used by GitHub Actions |
| `.github/workflows/nwp-archiver.yml` | Manual smoke/full runs and gated polling schedule |
| `requirements-nwp.txt` | Pinned archiver/runtime/test dependencies |
| root `nwp_archiver.py` | The current zero-byte root file is removed after this specification is approved |

The production entry point is always `python -m src.ingestion.nwp_archiver`; no production logic is placed in a notebook.

## 6. ECMWF request profiles

### 6.1 Full archive profile

IFS uses an issue-specific Cycle 50r1 horizon. The 00/12 UTC issues use steps
`0, 3, ..., 144`; the 06/18 UTC issues use steps `0, 3, ..., 90`. Its solar
and supporting weather inventory includes `ssrd`, `tcc`, `2t`, `2d`, `10u`,
`10v`, `tp`, `sp`, `tcwv`, and `mucape`.

AIFS Single uses steps `0, 6, ..., 144`. Its inventory includes `ssrd`, `tcc`, `lcc`, `mcc`, `hcc`, `2t`, `2d`, `10u`, `10v`, `tp`, `sp`, and `cp`.

Parameters are requested in model-specific groups so an error identifies the exact missing group. A committed full run requires every parameter declared for that model. A partial download is never published as a committed run.

The client first calls `latest()` with the IFS `0..90` step inventory that is
available in every 00/06/12/18 cycle (or the unchanged AIFS inventory). It then
calls `retrieve()` with that returned issue time explicitly and selects the
correct issue-specific IFS horizon. This allows a newly available 06/18 issue
to win discovery while preventing a run rollover between discovery and
download. The exact issue-specific requested steps are carried through
retrieval, validation, Parquet normalization, and the manifest.

After discovering the latest complete issue time, the archiver derives the expected 00/06/12/18 UTC issue cycles within the preceding 60 hours. It checks committed Drive manifests for those explicit cycles. This recovers scheduler gaps while runs remain inside ECMWF's rolling window; it is not a substitute for a licensed historical archive.

### 6.2 Smoke profile

The smoke profile requests `ssrd` at lead +48 h for both models. It verifies GitHub secret reconstruction, ECMWF connectivity, GRIB decoding, site extraction, Parquet generation, Drive upload, and read-back without claiming that the full archive profile works.

Smoke artifacts are stored beneath a `_smoke` child of `NWP_DESTINATION` and are excluded from the Bronze dataset.

### 6.3 Catch-up profile

The catch-up profile processes every uncommitted explicit issue cycle still visible within the preceding 60 hours, oldest first. It is run manually before the scheduler is first enabled and after any outage long enough to miss a cycle. A missing upstream run is reported explicitly and never replaced with reanalysis.

## 7. Canonical Parquet contract

Each Parquet row represents one model, issue time, and valid time at the selected PLTS-IKN grid point. The canonical primary key is:

```text
(site_id, nwp_source, issue_time_utc, valid_time_utc)
```

To avoid a collision between IFS and AIFS, `nwp_source` is model-qualified:

- `ecmwf_ifs`
- `ecmwf_aifs_single`

`nwp_provider` remains `ecmwf_opendata` for attribution and grouping.

Required canonical columns are:

| Column | Contract |
|---|---|
| `site_id` | string, always `PLTS-IKN` |
| `nwp_provider` | string, always `ecmwf_opendata` |
| `nwp_source` | `ecmwf_ifs` or `ecmwf_aifs_single` |
| `nwp_model` | ECMWF API model name |
| `issue_time_utc` | timezone-aware UTC timestamp |
| `valid_time_utc` | timezone-aware UTC timestamp |
| `retrieved_at_utc` | timezone-aware UTC timestamp captured after successful download |
| `lead_time_min` | integer difference between valid and issue time |
| `ssrd_wm2` | interval mean surface solar flux |
| `tcc_frac`, `lcc_frac`, `mcc_frac`, `hcc_frac` | cloud-cover fractions where supplied |
| `t2m_c`, `d2m_c` | Celsius |
| `u10_ms`, `v10_ms` | m/s |
| `tp_mm` | millimetres over the GRIB interval |
| `mucape_jkg` | J/kg where supplied |

Audit columns preserve the extraction and conversion evidence:

- `site_latitude`, `site_longitude`;
- `grid_latitude`, `grid_longitude`, `grid_distance_km`;
- `grid_selection_method`, always `nearest`;
- `ssrd_accum_jm2`, `ssrd_interval_jm2`, `ssrd_interval_seconds`;
- `ssrd_conversion_method`;
- `grib_start_step_h`, `grib_end_step_h`, and `grib_step_type`;
- `ecmwf_client_source`, client version, ecCodes version;
- `schema_version`, initially `1`; and
- ECMWF dataset URL and `CC-BY-4.0` licence identifier.

Cloud cover must be normalized to `[0, 1]`. Kelvin-to-Celsius and metres-to-millimetres conversions are explicit and tested. Source values used for each conversion remain available in audit columns when conversion would otherwise be irreversible.

## 8. SSRD conversion

`ssrd` is accumulated energy in J/m2. The implementation reads `startStep`, `endStep`, and `stepType` from each GRIB message instead of assuming every field is accumulated from hour zero.

For an interval accumulation, the raw message value is the interval energy. For a run-total accumulation beginning at hour zero, the current cumulative value is differenced against the preceding cumulative value. The mean flux is:

```text
ssrd_wm2 = ssrd_interval_jm2 / ssrd_interval_seconds
```

The lead-zero row has no positive-duration solar interval and therefore stores `ssrd_wm2` as null while retaining its raw value. A negative de-accumulated energy beyond floating-point tolerance fails validation rather than being silently clipped.

## 9. Local artifact and Drive layout

The local run is assembled under a temporary directory and renamed only after validation. A successful attempt produces:

```text
nwp_source=<source>/
  issue_date=YYYY-MM-DD/
    issue_hour=HH/
      retrieved_at=YYYYMMDDTHHMMSSZ/
        weather_forecast_raw.parquet
        manifest.json
```

The manifest contains:

- run identity and retrieval time;
- requested and received parameters/steps;
- actual grid coordinates and distance;
- row count and minimum/maximum valid times;
- schema and dependency versions;
- Parquet byte size and SHA-256 hash; and
- status `complete`.

The workflow uploads Parquet first and `manifest.json` last. Only an attempt directory with a valid complete manifest belongs to the dataset. An interrupted upload has no committed manifest and is ignored. A retry uses a new retrieval-time attempt directory, preserving append-only semantics.

Before downloading, the workflow checks whether any complete attempt manifest already exists for the model/issue-time partition. If one exists, the job exits successfully without retrieving or uploading that run again.

## 10. Workflow behavior

The workflow supports `workflow_dispatch` and an hourly polling cron at minute 17. Polling rather than assuming a publication hour tolerates ECMWF dissemination delays and GitHub scheduling delays.

Rules:

- a manual run is allowed while `NWP_ARCHIVER_ENABLED=false`;
- scheduled runs immediately skip unless `NWP_ARCHIVER_ENABLED=true`;
- `concurrency` permits only one canonical archiver job at a time;
- job permissions are `contents: read`;
- no `pull_request` trigger is defined;
- the base64 rclone config is decoded only beneath `RUNNER_TEMP`, mode `0600`;
- secret values and decoded config are never printed or uploaded as artifacts;
- cleanup runs under `if: always()`; and
- the job has a finite timeout and bounded retries.

In normal scheduled mode, each model processes the latest complete run plus at most one oldest missing retained cycle. This prevents a backlog from hiding the newest run while gradually repairing short gaps. The manual catch-up profile removes the per-poll limit and is the required recovery path for initial bootstrap or a multi-cycle outage.

The scheduler processes IFS and AIFS independently. If one model is not yet complete, the available model may commit successfully while the other fails and is retried by the next poll. The workflow result remains failed or degraded until both model outcomes are visible in the job summary.

## 11. Error handling and observability

The archiver fails loudly for:

- missing required parameters or steps;
- an issue-time mismatch between requested and decoded GRIB messages;
- naive or non-UTC timestamps;
- duplicate primary keys;
- inconsistent selected grid coordinates within a run;
- invalid units or unsupported GRIB step semantics;
- negative lead times;
- invalid cloud fractions;
- Parquet/manifest hash mismatch; or
- Drive upload/read-back failure.

Every job summary reports, per model:

- discovered issue time;
- archive status: `skipped`, `committed`, or `failed`;
- retrieval latency computed from `retrieved_at_utc - issue_time_utc`;
- row and parameter counts;
- grid coordinates and distance; and
- final Drive path without credentials.

The workflow retains no successful local GRIB file. GRIB is a transport artifact; the immutable Bronze record begins at the raw selected-grid values plus their GRIB metadata in Parquet.

## 12. Test strategy

The default test suite is network-free. It covers:

1. exact model names, parameter inventories, and step sequences;
   for IFS this includes the 00/12 long horizon, 06/18 short horizon, and
   common discovery inventory;
2. timezone-aware issue, valid, and retrieval timestamps;
3. lead-time calculation and primary-key uniqueness;
4. nearest-grid longitude normalization and stored grid evidence;
5. interval and run-total SSRD conversion reference cases;
6. rejection of unsupported or negative accumulations;
7. schema type/unit/range validation;
8. deterministic partition paths and manifest hashes;
9. committed-manifest skip behavior; and
10. issue-time leakage discipline using measured retrieval latency;
11. retained-cycle enumeration and oldest-first catch-up ordering; and
12. refusal to substitute an unavailable cycle with another issue time.

The integration sequence is:

1. run offline tests locally and in CI;
2. trigger the smoke profile manually and verify Drive read-back;
3. trigger one full run manually for both models;
4. inspect the Parquet schema and all three timestamps;
5. rerun the same issue time and verify a clean skip;
6. trigger the catch-up profile for the still-retained issue cycles;
7. set `NWP_ARCHIVER_ENABLED=true`; and
8. observe two successive scheduled issue cycles before declaring S0-1 complete.

## 13. Acceptance criteria

Implementation readiness requires:

- all offline tests passing;
- the workflow committed to the canonical repository;
- a successful full manual IFS and AIFS archive;
- Parquet read-back from Google Drive with a valid manifest/hash;
- separate non-null `issue_time_utc`, `valid_time_utc`, and `retrieved_at_utc`;
- a measured retrieval-latency value;
- correct site-grid evidence;
- an idempotent second invocation; and
- no secret exposure in logs or artifacts.

S0-1 itself is complete only after the scheduler is enabled and the Drive archive contains at least two successive issue cycles for both models. Until then the status is implementation-ready or smoke-tested, not a running/growing archive.

## 14. Attribution

Every manifest records ECMWF as the source, the Open Data dataset URL, and the `CC-BY-4.0` licence identifier. Repository documentation must include the same attribution before the scheduler is enabled.

The current real-time issue-cycle and horizon behavior is sourced from ECMWF's
[official IFS and AIFS Open Data forecast schedule](https://confluence.ecmwf.int/spaces/DAC/pages/272310539/ECMWF+open+data+real-time+forecasts+from+IFS+and+AIFS).
