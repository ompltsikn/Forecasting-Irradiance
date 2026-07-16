# Forecasting Irradiance — PLTS-IKN

Sprint 0 starts by measuring and archiving what actually exists. No forecasting model is built by the S0-1 NWP archiver.

## S0-1 NWP archive

The archiver captures ECMWF Open Data IFS and AIFS Single forecasts for the nearest PLTS-IKN grid point. Every Parquet row preserves:

- `issue_time_utc`: when ECMWF issued the forecast run;
- `valid_time_utc`: when the forecast applies; and
- `retrieved_at_utc`: when this system actually finished retrieving the run.

These columns must never be collapsed because observed retrieval time is required to prevent issue-time leakage.

## Local offline verification

```powershell
python -m pip install -r requirements-nwp.txt
python -m pytest tests/unit tests/leakage tests/integration -q
```

## GitHub Actions safety sequence

1. Keep the repository variable `NWP_ARCHIVER_ENABLED=false`.
2. Run the `smoke` profile for both models.
3. Run one `full` issue for both models.
4. Repeat the same full issue and confirm an idempotent skip.
5. Run `catchup` for ECMWF cycles still retained upstream.
6. Enable scheduling only after Parquet and manifest read-back checks pass.

The Google Drive destination comes from `NWP_DESTINATION`; the rclone credential comes only from the encrypted `RCLONE_CONFIG_B64` GitHub secret.

## Attribution

Forecast data is provided by the European Centre for Medium-Range Weather Forecasts (ECMWF) Open Data service under the Creative Commons Attribution 4.0 International licence (`CC-BY-4.0`):

https://www.ecmwf.int/en/forecasts/datasets/open-data

The archive manifest records the source URL, licence identifier, client versions, requested issue cycle, selected grid point, and Parquet SHA-256.
