from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Literal

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from pandas.api.types import is_numeric_dtype


NWP_SCHEMA_VERSION: Final[int] = 1
NWP_PRIMARY_KEY: Final[tuple[str, ...]] = (
    "site_id",
    "nwp_source",
    "issue_time_utc",
    "valid_time_utc",
)
TIMESTAMP_COLUMNS: Final[tuple[str, ...]] = (
    "issue_time_utc",
    "valid_time_utc",
    "retrieved_at_utc",
)
CLOUD_COLUMNS: Final[tuple[str, ...]] = (
    "tcc_frac",
    "lcc_frac",
    "mcc_frac",
    "hcc_frac",
)
NUMERIC_COLUMNS: Final[tuple[str, ...]] = (
    "lead_time_min",
    "ssrd_wm2",
    "ssrd_accum_jm2",
    "ssrd_interval_jm2",
    "ssrd_interval_seconds",
    "tcc_frac",
    "lcc_frac",
    "mcc_frac",
    "hcc_frac",
    "t2m_c",
    "d2m_c",
    "u10_ms",
    "v10_ms",
    "tp_accum_m",
    "tp_interval_m",
    "tp_mm",
    "sp_pa",
    "sp_hpa",
    "tcwv_kgm2",
    "cp_accum_m",
    "cp_interval_m",
    "cp_mm",
    "mucape_jkg",
    "site_latitude",
    "site_longitude",
    "grid_latitude",
    "grid_longitude",
    "grid_distance_km",
    "grib_start_step_h",
    "grib_end_step_h",
    "schema_version",
)
NWP_COLUMNS: Final[tuple[str, ...]] = (
    "site_id",
    "nwp_provider",
    "nwp_source",
    "nwp_model",
    "issue_time_utc",
    "valid_time_utc",
    "retrieved_at_utc",
    "lead_time_min",
    "ssrd_wm2",
    "ssrd_accum_jm2",
    "ssrd_interval_jm2",
    "ssrd_interval_seconds",
    "ssrd_conversion_method",
    "grib_start_step_h",
    "grib_end_step_h",
    "grib_step_type",
    "tcc_frac",
    "lcc_frac",
    "mcc_frac",
    "hcc_frac",
    "t2m_c",
    "d2m_c",
    "u10_ms",
    "v10_ms",
    "tp_accum_m",
    "tp_interval_m",
    "tp_mm",
    "sp_pa",
    "sp_hpa",
    "tcwv_kgm2",
    "cp_accum_m",
    "cp_interval_m",
    "cp_mm",
    "mucape_jkg",
    "site_latitude",
    "site_longitude",
    "grid_latitude",
    "grid_longitude",
    "grid_distance_km",
    "grid_selection_method",
    "ecmwf_client_source",
    "ecmwf_client_version",
    "eccodes_version",
    "schema_version",
    "ecmwf_dataset_url",
    "licence_id",
)
NWP_INTEGER_COLUMNS: Final[tuple[str, ...]] = (
    "lead_time_min",
    "ssrd_interval_seconds",
    "grib_start_step_h",
    "grib_end_step_h",
    "schema_version",
)
NWP_FLOAT_COLUMNS: Final[tuple[str, ...]] = tuple(
    column for column in NUMERIC_COLUMNS if column not in NWP_INTEGER_COLUMNS
)
NWP_STRING_COLUMNS: Final[tuple[str, ...]] = tuple(
    column
    for column in NWP_COLUMNS
    if column not in TIMESTAMP_COLUMNS and column not in NUMERIC_COLUMNS
)
SOURCE_MODEL = {"ecmwf_ifs": "ifs", "ecmwf_aifs_single": "aifs-single"}


class NwpContractError(ValueError):
    pass


def _require_utc_dtype(frame: pd.DataFrame, column: str) -> None:
    dtype = frame[column].dtype
    if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
        raise NwpContractError(f"{column} must use timezone-aware UTC dtype")


def validate_nwp_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in NWP_COLUMNS if column not in frame.columns]
    if missing:
        raise NwpContractError(f"missing columns: {missing}")
    for column in TIMESTAMP_COLUMNS:
        _require_utc_dtype(frame, column)
        if frame[column].isna().any():
            raise NwpContractError(f"{column} must be non-null")
    for column in NUMERIC_COLUMNS:
        if not is_numeric_dtype(frame[column]) and frame[column].notna().any():
            raise NwpContractError(f"{column} must be numeric")
    if frame[list(NWP_PRIMARY_KEY)].isna().any().any():
        raise NwpContractError("primary key must be non-null")
    if frame.duplicated(list(NWP_PRIMARY_KEY)).any():
        raise NwpContractError("duplicate primary key")
    expected_model = frame["nwp_source"].map(SOURCE_MODEL)
    if expected_model.isna().any() or (expected_model != frame["nwp_model"]).any():
        raise NwpContractError("source/model pair is invalid")
    expected_lead = (
        (frame["valid_time_utc"] - frame["issue_time_utc"]).dt.total_seconds() / 60
    ).astype("int64")
    if not expected_lead.equals(frame["lead_time_min"].astype("int64")):
        raise NwpContractError("lead_time_min does not match valid minus issue")
    if (frame["valid_time_utc"] < frame["issue_time_utc"]).any():
        raise NwpContractError("valid_time_utc precedes issue_time_utc")
    if (frame["retrieved_at_utc"] < frame["issue_time_utc"]).any():
        raise NwpContractError("retrieved_at_utc precedes issue_time_utc")
    for column in CLOUD_COLUMNS:
        valid = frame[column].dropna()
        if not valid.between(0.0, 1.0, inclusive="both").all():
            raise NwpContractError(f"{column} must be in [0, 1]")
    if (frame["grid_distance_km"] > 25.0).any() or (
        frame["grid_distance_km"] < 0
    ).any():
        raise NwpContractError("grid_distance_km must be in [0, 25]")
    grouped = frame.groupby(["nwp_source", "issue_time_utc"], dropna=False)
    if (
        grouped["grid_latitude"].nunique().max() != 1
        or grouped["grid_longitude"].nunique().max() != 1
    ):
        raise NwpContractError("grid coordinates must be constant within a run")
    if not (frame["schema_version"] == NWP_SCHEMA_VERSION).all():
        raise NwpContractError("schema_version mismatch")
    return frame


def canonicalize_nwp_frame(frame: pd.DataFrame) -> pd.DataFrame:
    validated = validate_nwp_frame(frame)
    canonical = validated.copy()
    for column in TIMESTAMP_COLUMNS:
        canonical[column] = canonical[column].astype("datetime64[ns, UTC]")
    for column in NWP_INTEGER_COLUMNS:
        canonical[column] = pd.to_numeric(canonical[column]).astype("Int64")
    for column in NWP_FLOAT_COLUMNS:
        canonical[column] = pd.to_numeric(canonical[column]).astype("Float64")
    for column in NWP_STRING_COLUMNS:
        canonical[column] = canonical[column].astype("string")
    return validate_nwp_frame(canonical)


def _iso_z(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise NwpContractError("manifest timestamps must be timezone-aware UTC")
    timestamp = pd.Timestamp(value.astimezone(timezone.utc)).as_unit("ns")
    return timestamp.isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RunManifest:
    schema_version: int
    status: Literal["complete"]
    site_id: str
    nwp_provider: Literal["ecmwf_opendata"]
    nwp_source: Literal["ecmwf_ifs", "ecmwf_aifs_single"]
    nwp_model: Literal["ifs", "aifs-single"]
    issue_time_utc: datetime
    retrieved_at_utc: datetime
    requested_parameters: tuple[str, ...]
    received_parameters: tuple[str, ...]
    requested_steps_h: tuple[int, ...]
    received_steps_h: tuple[int, ...]
    grid_latitude: float
    grid_longitude: float
    grid_distance_km: float
    row_count: int
    valid_time_min_utc: datetime
    valid_time_max_utc: datetime
    parquet_bytes: int
    parquet_sha256: str
    ecmwf_client_version: str
    eccodes_version: str
    dataset_url: str
    licence_id: Literal["CC-BY-4.0"]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "issue_time_utc",
            "retrieved_at_utc",
            "valid_time_min_utc",
            "valid_time_max_utc",
        ):
            payload[key] = _iso_z(payload[key])
        for key in (
            "requested_parameters",
            "received_parameters",
            "requested_steps_h",
            "received_steps_h",
        ):
            payload[key] = list(payload[key])
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> RunManifest:
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise NwpContractError("manifest JSON must contain an object")
        for key in (
            "issue_time_utc",
            "retrieved_at_utc",
            "valid_time_min_utc",
            "valid_time_max_utc",
        ):
            payload[key] = pd.Timestamp(payload[key]).as_unit("ns")
        for key in (
            "requested_parameters",
            "received_parameters",
            "requested_steps_h",
            "received_steps_h",
        ):
            payload[key] = tuple(payload[key])
        return cls(**payload)


def _validate_inventory(
    requested: tuple[Any, ...],
    received: tuple[Any, ...],
    *,
    kind: Literal["parameter", "step"],
) -> None:
    if (
        not requested
        or not received
        or len(set(requested)) != len(requested)
        or len(set(received)) != len(received)
        or set(requested) != set(received)
    ):
        raise NwpContractError(f"manifest {kind} inventory mismatch")
    if kind == "parameter":
        if any(
            not isinstance(value, str) or not value
            for value in requested + received
        ):
            raise NwpContractError("manifest parameter inventory is invalid")
    elif any(
        not isinstance(value, int) or isinstance(value, bool) or value < 0
        for value in requested + received
    ):
        raise NwpContractError("manifest step inventory is invalid")


def _validate_parquet_schema(parquet_path: Path) -> None:
    try:
        schema = pq.read_schema(parquet_path)
    except Exception as exc:
        raise NwpContractError("manifest Parquet schema is unreadable") from exc
    if tuple(schema.names) != NWP_COLUMNS:
        raise NwpContractError("manifest Parquet schema columns mismatch")
    expected_types = {
        **{column: pa.timestamp("ns", tz="UTC") for column in TIMESTAMP_COLUMNS},
        **{column: pa.int64() for column in NWP_INTEGER_COLUMNS},
        **{column: pa.float64() for column in NWP_FLOAT_COLUMNS},
        **{column: pa.large_string() for column in NWP_STRING_COLUMNS},
    }
    for column in NWP_COLUMNS:
        if schema.field(column).type != expected_types[column]:
            raise NwpContractError(
                f"manifest Parquet schema type mismatch for {column}"
            )


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_manifest(manifest: RunManifest, *, parquet_path: Path) -> None:
    parquet_path = Path(parquet_path)
    if manifest.status != "complete":
        raise NwpContractError("manifest status must be complete")
    if manifest.schema_version != NWP_SCHEMA_VERSION:
        raise NwpContractError("manifest schema version mismatch")
    _validate_inventory(
        manifest.requested_parameters,
        manifest.received_parameters,
        kind="parameter",
    )
    _validate_inventory(
        manifest.requested_steps_h,
        manifest.received_steps_h,
        kind="step",
    )
    if not manifest.site_id:
        raise NwpContractError("manifest site_id must be non-empty")
    if manifest.nwp_provider != "ecmwf_opendata":
        raise NwpContractError("manifest provider mismatch")
    if SOURCE_MODEL.get(manifest.nwp_source) != manifest.nwp_model:
        raise NwpContractError("manifest source/model mismatch")
    for value in (
        manifest.issue_time_utc,
        manifest.retrieved_at_utc,
        manifest.valid_time_min_utc,
        manifest.valid_time_max_utc,
    ):
        _iso_z(value)
    if manifest.retrieved_at_utc < manifest.issue_time_utc:
        raise NwpContractError("manifest retrieval precedes issue")
    if manifest.valid_time_min_utc < manifest.issue_time_utc:
        raise NwpContractError("manifest valid range precedes issue")
    if manifest.valid_time_max_utc < manifest.valid_time_min_utc:
        raise NwpContractError("manifest valid range is reversed")
    if not (-90.0 <= manifest.grid_latitude <= 90.0):
        raise NwpContractError("manifest grid latitude is invalid")
    if not (-180.0 <= manifest.grid_longitude <= 180.0):
        raise NwpContractError("manifest grid longitude is invalid")
    if not (0.0 <= manifest.grid_distance_km <= 25.0):
        raise NwpContractError("manifest grid distance is invalid")
    if not isinstance(manifest.row_count, int) or manifest.row_count <= 0:
        raise NwpContractError("manifest row_count must be positive")
    if not parquet_path.is_file():
        raise NwpContractError("manifest Parquet file is missing")
    if (
        not isinstance(manifest.parquet_bytes, int)
        or isinstance(manifest.parquet_bytes, bool)
        or manifest.parquet_bytes <= 0
    ):
        raise NwpContractError("manifest Parquet byte size must be positive")
    if re.fullmatch(r"[0-9a-f]{64}", manifest.parquet_sha256) is None:
        raise NwpContractError("manifest Parquet hash format is invalid")
    if _sha256_path(parquet_path) != manifest.parquet_sha256:
        raise NwpContractError("manifest Parquet hash mismatch")
    if parquet_path.stat().st_size != manifest.parquet_bytes:
        raise NwpContractError("manifest Parquet byte size mismatch")
    if (
        manifest.dataset_url
        != "https://www.ecmwf.int/en/forecasts/datasets/open-data"
    ):
        raise NwpContractError("manifest dataset URL mismatch")
    if manifest.licence_id != "CC-BY-4.0":
        raise NwpContractError("manifest licence mismatch")
    if not manifest.ecmwf_client_version or not manifest.eccodes_version:
        raise NwpContractError("manifest dependency versions must be non-empty")
    _validate_parquet_schema(parquet_path)
    try:
        frame = validate_nwp_frame(pd.read_parquet(parquet_path))
    except NwpContractError:
        raise
    except Exception as exc:
        raise NwpContractError("manifest Parquet data is unreadable") from exc
    if len(frame) != manifest.row_count:
        raise NwpContractError("manifest row count mismatch")
    identity_checks = {
        "site_id": manifest.site_id,
        "nwp_provider": manifest.nwp_provider,
        "nwp_source": manifest.nwp_source,
        "nwp_model": manifest.nwp_model,
        "issue_time_utc": pd.Timestamp(manifest.issue_time_utc),
        "retrieved_at_utc": pd.Timestamp(manifest.retrieved_at_utc),
        "grid_latitude": manifest.grid_latitude,
        "grid_longitude": manifest.grid_longitude,
        "grid_distance_km": manifest.grid_distance_km,
        "ecmwf_client_version": manifest.ecmwf_client_version,
        "eccodes_version": manifest.eccodes_version,
        "schema_version": manifest.schema_version,
        "ecmwf_dataset_url": manifest.dataset_url,
        "licence_id": manifest.licence_id,
    }
    for column, expected in identity_checks.items():
        values = frame[column].drop_duplicates()
        if (
            len(values) != 1
            or pd.isna(values.iloc[0])
            or values.iloc[0] != expected
        ):
            raise NwpContractError(f"manifest {column} does not match Parquet")
    if frame["valid_time_utc"].min() != pd.Timestamp(manifest.valid_time_min_utc):
        raise NwpContractError("manifest minimum valid time mismatch")
    if frame["valid_time_utc"].max() != pd.Timestamp(manifest.valid_time_max_utc):
        raise NwpContractError("manifest maximum valid time mismatch")


def load_and_validate_manifest(
    manifest_path: Path,
    *,
    parquet_path: Path,
) -> RunManifest:
    manifest = RunManifest.from_json(
        Path(manifest_path).read_text(encoding="utf-8")
    )
    validate_manifest(manifest, parquet_path=parquet_path)
    return manifest


def available_nwp_as_of(frame: pd.DataFrame, as_of_utc: datetime) -> pd.DataFrame:
    if (
        as_of_utc.tzinfo is None
        or as_of_utc.utcoffset() != timezone.utc.utcoffset(as_of_utc)
    ):
        raise NwpContractError("as_of_utc must be timezone-aware UTC")
    validated = validate_nwp_frame(frame)
    return validated.loc[
        validated["retrieved_at_utc"] <= pd.Timestamp(as_of_utc)
    ].copy()
