from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import AbstractSet, Iterable, Literal, Protocol, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pandas as pd
import yaml

from data_contracts.nwp_schema import (
    NWP_COLUMNS,
    NWP_SCHEMA_VERSION,
    canonicalize_nwp_frame,
)


UTC = timezone.utc
EARTH_RADIUS_KM = 6371.0088
SSRD_NEGATIVE_TOLERANCE_JM2 = 1e-6
PRECIP_NEGATIVE_TOLERANCE_M = 1e-9
ECMWF_DATASET_URL = "https://www.ecmwf.int/en/forecasts/datasets/open-data"
ECMWF_LICENCE_ID = "CC-BY-4.0"


class SiteConfigError(ValueError):
    pass


class AccumulationError(ValueError):
    pass


class GribDecodeError(ValueError):
    pass


class NwpModel(StrEnum):
    IFS = "ifs"
    AIFS_SINGLE = "aifs-single"


class ArchiveProfile(StrEnum):
    SMOKE = "smoke"
    FULL = "full"
    CATCHUP = "catchup"


class SelectionMode(StrEnum):
    SMOKE = "smoke"
    FULL = "full"
    CATCHUP = "catchup"
    SCHEDULED = "scheduled"


@dataclass(frozen=True)
class SitePoint:
    site_id: str
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    timezone: str


@dataclass(frozen=True)
class ParameterGroup:
    name: str
    parameters: tuple[str, ...]


@dataclass(frozen=True)
class RequestProfile:
    model: NwpModel
    nwp_source: Literal["ecmwf_ifs", "ecmwf_aifs_single"]
    request_steps_h: tuple[int, ...]
    output_steps_h: tuple[int, ...]
    groups: tuple[ParameterGroup, ...]

    @property
    def parameters(self) -> tuple[str, ...]:
        return tuple(parameter for group in self.groups for parameter in group.parameters)


@dataclass(frozen=True)
class DecodedField:
    parameter: str
    value: float
    units: str
    issue_time_utc: datetime
    valid_time_utc: datetime
    start_step_h: int
    end_step_h: int
    step_type: str
    grid_latitude: float
    grid_longitude: float


@dataclass(frozen=True)
class RetrievedRun:
    model: NwpModel
    issue_time_utc: datetime
    retrieved_at_utc: datetime
    files_by_group: Mapping[str, tuple[Path, ...]]


@dataclass(frozen=True)
class AccumulationResult:
    raw_value: float
    interval_value: float | None
    interval_seconds: int
    method: str


class OpenDataGateway(Protocol):
    def latest(self, *, model: NwpModel, request: dict[str, object]) -> datetime: ...

    def retrieve(
        self,
        *,
        model: NwpModel,
        request: dict[str, object],
        target: Path,
    ) -> None: ...


def _normalise_ecmwf_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class EcmwfOpenDataGateway:
    def __init__(self, *, source: str = "google") -> None:
        from ecmwf.opendata import Client

        self.source = source
        self._client_type = Client

    def _client(self, model: NwpModel):
        return self._client_type(
            source=self.source,
            model=model.value,
            resol="0p25",
            infer_stream_keyword=False,
        )

    def latest(self, *, model: NwpModel, request: dict[str, object]) -> datetime:
        return _normalise_ecmwf_datetime(self._client(model).latest(**request))

    def retrieve(
        self,
        *,
        model: NwpModel,
        request: dict[str, object],
        target: Path,
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        self._client(model).retrieve(**request, target=str(target))
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"ECMWF retrieval produced no data: {target}")


IFS_GROUPS = (
    ParameterGroup("solar", ("ssrd", "tcc")),
    ParameterGroup("surface", ("2t", "2d", "10u", "10v", "tp", "sp")),
    ParameterGroup("water", ("tcwv",)),
    ParameterGroup("convection", ("mucape",)),
)
AIFS_GROUPS = (
    ParameterGroup("solar", ("ssrd", "tcc", "lcc", "mcc", "hcc")),
    ParameterGroup("surface", ("2t", "2d", "10u", "10v", "tp", "sp")),
    ParameterGroup("water", ("cp",)),
)


def _normalise_accumulation_value(
    value: float,
    units: str,
    family: Literal["energy", "depth"],
) -> float:
    compact = units.replace(" ", "").lower()
    if family == "energy":
        if compact not in {"jm**-2", "jm-2", "j/m^2", "j/m2"}:
            raise AccumulationError(f"unexpected energy units: {units}")
        return value
    if compact in {"m", "metres", "meters"}:
        return value
    if compact in {"kgm**-2", "kgm-2", "kg/m^2", "kg/m2"}:
        # 1 kg m^-2 liquid-water equivalent = 1 mm = 0.001 m.
        return value / 1000.0
    raise AccumulationError(f"unexpected depth units: {units}")


def deaccumulate_fields(
    fields: Iterable[DecodedField],
    output_steps_h: Iterable[int],
    unit_family: Literal["energy", "depth"],
) -> dict[int, AccumulationResult]:
    by_end = {field.end_step_h: field for field in fields}
    tolerance = (
        SSRD_NEGATIVE_TOLERANCE_JM2
        if unit_family == "energy"
        else PRECIP_NEGATIVE_TOLERANCE_M
    )
    results: dict[int, AccumulationResult] = {}
    for end_step in output_steps_h:
        if end_step not in by_end:
            raise AccumulationError(f"missing accumulated field at step {end_step}")
        current = by_end[end_step]
        if current.step_type != "accum":
            raise AccumulationError("step_type must be accum")
        current_value = _normalise_accumulation_value(
            current.value, current.units, unit_family
        )
        if current.start_step_h == 0 and current.end_step_h == 0:
            results[end_step] = AccumulationResult(
                raw_value=current_value,
                interval_value=None,
                interval_seconds=0,
                method="lead_zero",
            )
            continue
        if current.end_step_h <= current.start_step_h:
            raise AccumulationError("accumulation interval must have positive duration")
        if current.start_step_h > 0:
            interval = current_value
            seconds = (current.end_step_h - current.start_step_h) * 3600
            method = "interval_accumulation"
        else:
            predecessors = [
                value
                for value in by_end.values()
                if value.start_step_h == 0 and value.end_step_h < current.end_step_h
            ]
            if not predecessors:
                raise AccumulationError(
                    f"run-total step {current.end_step_h} has no predecessor"
                )
            previous = max(predecessors, key=lambda value: value.end_step_h)
            if previous.step_type != "accum":
                raise AccumulationError("predecessor step_type must be accum")
            try:
                previous_value = _normalise_accumulation_value(
                    previous.value, previous.units, unit_family
                )
            except AccumulationError as exc:
                raise AccumulationError(f"predecessor {exc}") from exc
            interval = current_value - previous_value
            seconds = (current.end_step_h - previous.end_step_h) * 3600
            method = "run_total_difference"
        if interval < -tolerance:
            raise AccumulationError(f"material negative accumulation: {interval}")
        if interval < 0:
            interval = 0.0
        results[end_step] = AccumulationResult(
            raw_value=current_value,
            interval_value=interval,
            interval_seconds=seconds,
            method=method,
        )
    return results


def ssrd_mean_wm2(result: AccumulationResult) -> float | None:
    if result.interval_value is None:
        return None
    if result.interval_seconds <= 0:
        raise AccumulationError("SSRD interval_seconds must be positive")
    return result.interval_value / result.interval_seconds


def precipitation_mm(result: AccumulationResult) -> float | None:
    return None if result.interval_value is None else result.interval_value * 1000.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lon2 - lon1)
    a = sin(delta_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


def enumerate_retained_cycles(
    latest_issue_time_utc: datetime,
    lookback: timedelta = timedelta(hours=60),
) -> tuple[datetime, ...]:
    latest = require_utc(latest_issue_time_utc)
    if (
        latest.minute != 0
        or latest.second != 0
        or latest.microsecond != 0
        or latest.hour not in {0, 6, 12, 18}
    ):
        raise ValueError("latest issue must be an exact 00/06/12/18 UTC cycle")
    if lookback < timedelta(0) or lookback.total_seconds() % (6 * 3600) != 0:
        raise ValueError("lookback must be a non-negative multiple of 6 hours")
    count = int(lookback.total_seconds() // (6 * 3600))
    return tuple(
        latest - timedelta(hours=6 * offset) for offset in range(count, -1, -1)
    )


def select_uncommitted_cycles(
    retained_cycles: Sequence[datetime],
    committed_cycles: AbstractSet[datetime],
    mode: SelectionMode,
) -> tuple[datetime, ...]:
    cycles = tuple(require_utc(value) for value in retained_cycles)
    if not cycles:
        return ()
    missing = tuple(value for value in cycles if value not in committed_cycles)
    if not missing:
        return ()
    if mode is SelectionMode.CATCHUP:
        return missing
    latest = cycles[-1]
    if mode in {SelectionMode.SMOKE, SelectionMode.FULL}:
        return (latest,) if latest in missing else ()
    selected: list[datetime] = []
    if latest in missing:
        selected.append(latest)
    oldest_prior = next((value for value in missing if value != latest), None)
    if oldest_prior is not None:
        selected.append(oldest_prior)
    return tuple(selected)


def measured_latency_minutes(
    issue_time_utc: datetime, retrieved_at_utc: datetime
) -> float:
    issue = require_utc(issue_time_utc)
    retrieved = require_utc(retrieved_at_utc)
    if retrieved < issue:
        raise ValueError("retrieved_at_utc precedes issue_time_utc")
    return (retrieved - issue).total_seconds() / 60.0


def load_site_point(config_path: Path) -> SitePoint:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("site"), dict):
        raise SiteConfigError("site mapping is required")
    site = raw["site"]
    required = ("site_id", "latitude_deg", "longitude_deg", "elevation_m", "timezone")
    for key in required:
        if site.get(key) is None:
            raise SiteConfigError(f"{key} is required")
    try:
        result = SitePoint(
            site_id=str(site["site_id"]),
            latitude_deg=float(site["latitude_deg"]),
            longitude_deg=float(site["longitude_deg"]),
            elevation_m=float(site["elevation_m"]),
            timezone=str(site["timezone"]),
        )
        ZoneInfo(result.timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise SiteConfigError(str(exc)) from exc
    if not -90.0 <= result.latitude_deg <= 90.0:
        raise SiteConfigError("latitude_deg must be in [-90, 90]")
    if not -180.0 <= result.longitude_deg <= 180.0:
        raise SiteConfigError("longitude_deg must be in [-180, 180]")
    return result


def request_profile_for(model: NwpModel, profile: ArchiveProfile) -> RequestProfile:
    if model is NwpModel.IFS:
        source: Literal["ecmwf_ifs", "ecmwf_aifs_single"] = "ecmwf_ifs"
        full_steps = tuple(range(0, 145, 3))
        groups = IFS_GROUPS
        smoke_steps = (45, 48)
    else:
        source = "ecmwf_aifs_single"
        full_steps = tuple(range(0, 145, 6))
        groups = AIFS_GROUPS
        smoke_steps = (42, 48)
    if profile is ArchiveProfile.SMOKE:
        return RequestProfile(
            model=model,
            nwp_source=source,
            request_steps_h=smoke_steps,
            output_steps_h=(48,),
            groups=(ParameterGroup("solar", ("ssrd",)),),
        )
    return RequestProfile(
        model=model,
        nwp_source=source,
        request_steps_h=full_steps,
        output_steps_h=full_steps,
        groups=groups,
    )


def build_request(
    profile: RequestProfile,
    group: ParameterGroup,
    *,
    issue_time_utc: datetime | None,
) -> dict[str, object]:
    request: dict[str, object] = {
        "stream": "oper",
        "type": "fc",
        "levtype": "sfc",
        "step": list(profile.request_steps_h),
        "param": list(group.parameters),
    }
    if issue_time_utc is not None:
        issue = require_utc(issue_time_utc)
        request["date"] = issue.strftime("%Y%m%d")
        request["time"] = issue.hour * 100
    return request


def discover_latest_issue(
    gateway: OpenDataGateway,
    profile: RequestProfile,
) -> datetime:
    combined = ParameterGroup("complete", profile.parameters)
    return require_utc(
        gateway.latest(
            model=profile.model,
            request=build_request(profile, combined, issue_time_utc=None),
        )
    )


def retrieve_explicit_run(
    gateway: OpenDataGateway,
    profile: RequestProfile,
    issue_time_utc: datetime,
    work_directory: Path,
    *,
    clock: Callable[[], datetime],
    retry_attempts: int = 3,
    retry_delay_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> RetrievedRun:
    if retry_attempts < 1:
        raise ValueError("retry_attempts must be at least 1")
    issue = require_utc(issue_time_utc)
    files: dict[str, tuple[Path, ...]] = {}
    work_directory.mkdir(parents=True, exist_ok=True)
    for group in profile.groups:
        target = (
            work_directory
            / f"{profile.model.value}-{issue:%Y%m%dT%HZ}-{group.name}.grib2"
        )
        request = build_request(profile, group, issue_time_utc=issue)
        for attempt in range(1, retry_attempts + 1):
            try:
                gateway.retrieve(
                    model=profile.model,
                    request=request,
                    target=target,
                )
                break
            except (ConnectionError, OSError, TimeoutError):
                if attempt == retry_attempts:
                    raise
                sleep(retry_delay_seconds * attempt)
        files[group.name] = (target,)
    retrieved = require_utc(clock())
    if retrieved < issue:
        raise ValueError("retrieved_at_utc precedes issue_time_utc")
    return RetrievedRun(
        model=profile.model,
        issue_time_utc=issue,
        retrieved_at_utc=retrieved,
        files_by_group=files,
    )


def _date_time_to_utc(date_value: int, time_value: int) -> datetime:
    return datetime.strptime(
        f"{date_value:08d}{time_value:04d}", "%Y%m%d%H%M"
    ).replace(tzinfo=UTC)


def _normalise_longitude(longitude: float) -> float:
    return longitude - 360.0 if longitude > 180.0 else longitude


def _decode_grib_path(path: Path, site: SitePoint) -> tuple[DecodedField, ...]:
    from eccodes import (
        codes_get,
        codes_grib_find_nearest,
        codes_grib_new_from_file,
        codes_release,
    )

    decoded: list[DecodedField] = []
    with path.open("rb") as stream:
        while True:
            handle = codes_grib_new_from_file(stream)
            if handle is None:
                break
            try:
                nearest = codes_grib_find_nearest(
                    handle, site.latitude_deg, site.longitude_deg
                )[0]
                issue = _date_time_to_utc(
                    int(codes_get(handle, "dataDate")),
                    int(codes_get(handle, "dataTime")),
                )
                valid = _date_time_to_utc(
                    int(codes_get(handle, "validityDate")),
                    int(codes_get(handle, "validityTime")),
                )
                decoded.append(
                    DecodedField(
                        parameter=str(codes_get(handle, "shortName")),
                        value=float(nearest.value),
                        units=str(codes_get(handle, "units")),
                        issue_time_utc=issue,
                        valid_time_utc=valid,
                        start_step_h=int(codes_get(handle, "startStep")),
                        end_step_h=int(codes_get(handle, "endStep")),
                        step_type=str(codes_get(handle, "stepType")),
                        grid_latitude=float(nearest.lat),
                        grid_longitude=_normalise_longitude(float(nearest.lon)),
                    )
                )
            finally:
                codes_release(handle)
    if not decoded:
        raise GribDecodeError(f"no GRIB messages decoded from {path}")
    return tuple(decoded)


def decode_nearest_site_fields(
    run: RetrievedRun,
    site: SitePoint,
) -> tuple[DecodedField, ...]:
    fields = tuple(
        field
        for paths in run.files_by_group.values()
        for path in paths
        for field in _decode_grib_path(path, site)
    )
    for field in fields:
        if field.issue_time_utc != run.issue_time_utc:
            raise GribDecodeError(
                f"decoded issue time {field.issue_time_utc.isoformat()} does not match "
                f"requested issue time {run.issue_time_utc.isoformat()}"
            )
        expected_valid = run.issue_time_utc + timedelta(hours=field.end_step_h)
        if field.valid_time_utc != expected_valid:
            raise GribDecodeError(
                f"valid time mismatch for {field.parameter} step {field.end_step_h}"
            )
    coordinates = {(field.grid_latitude, field.grid_longitude) for field in fields}
    if len(coordinates) != 1:
        raise GribDecodeError("grid coordinates changed within retrieved run")
    return fields


def validate_field_completeness(
    fields: Sequence[DecodedField],
    profile: RequestProfile,
) -> None:
    expected = {
        (parameter, step)
        for parameter in profile.parameters
        for step in profile.request_steps_h
    }
    actual_pairs = [(field.parameter, field.end_step_h) for field in fields]
    seen: set[tuple[str, int]] = set()
    duplicates: set[tuple[str, int]] = set()
    for pair in actual_pairs:
        if pair in seen:
            duplicates.add(pair)
        seen.add(pair)
    if duplicates:
        raise ValueError(f"duplicate parameter/step fields: {sorted(duplicates)}")
    actual = set(actual_pairs)
    missing = expected - actual
    unexpected = actual - expected
    if missing:
        raise ValueError(f"missing required parameter/step fields: {sorted(missing)}")
    if unexpected:
        raise ValueError(f"unexpected parameter/step fields: {sorted(unexpected)}")


def _field_index(
    fields: Sequence[DecodedField],
) -> dict[tuple[str, int], DecodedField]:
    return {(field.parameter, field.end_step_h): field for field in fields}


def _instant(
    index: Mapping[tuple[str, int], DecodedField],
    parameter: str,
    step: int,
) -> DecodedField | None:
    return index.get((parameter, step))


def _temperature_c(field: DecodedField | None) -> float | None:
    if field is None:
        return None
    if field.units != "K":
        raise ValueError(f"{field.parameter} units must be K, got {field.units}")
    return field.value - 273.15


def _cloud_fraction(field: DecodedField | None) -> float | None:
    if field is None:
        return None
    compact = field.units.replace(" ", "").lower()
    if compact in {"(0-1)", "1", "fraction", "proportion"}:
        value = field.value
    elif compact in {"%", "percent", "percentage"}:
        value = field.value / 100.0
    else:
        raise ValueError(
            f"{field.parameter} cloud units are unsupported: {field.units}"
        )
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field.parameter} cloud fraction outside [0, 1]")
    return value


def _value_with_units(
    field: DecodedField | None,
    accepted_compact_units: set[str],
) -> float | None:
    if field is None:
        return None
    compact = field.units.replace(" ", "").lower()
    if compact not in accepted_compact_units:
        raise ValueError(f"{field.parameter} units are unsupported: {field.units}")
    return field.value


def normalise_run(
    fields: Sequence[DecodedField],
    *,
    site: SitePoint,
    profile: RequestProfile,
    retrieved_at_utc: datetime,
    ecmwf_client_source: str,
    ecmwf_client_version: str,
    eccodes_version: str,
) -> pd.DataFrame:
    retrieved = require_utc(retrieved_at_utc)
    validate_field_completeness(fields, profile)
    issues = {field.issue_time_utc for field in fields}
    coordinates = {(field.grid_latitude, field.grid_longitude) for field in fields}
    if len(issues) != 1:
        raise ValueError("fields contain multiple issue times")
    if len(coordinates) != 1:
        raise ValueError("fields contain multiple grid coordinates")
    issue = require_utc(next(iter(issues)))
    grid_latitude, grid_longitude = next(iter(coordinates))
    distance = haversine_km(
        site.latitude_deg,
        site.longitude_deg,
        grid_latitude,
        grid_longitude,
    )
    if distance > 25.0:
        raise ValueError(
            f"nearest ECMWF grid point is too far away: {distance:.3f} km"
        )
    index = _field_index(fields)
    ssrd = deaccumulate_fields(
        (index[("ssrd", step)] for step in profile.request_steps_h),
        profile.output_steps_h,
        "energy",
    )
    tp = (
        deaccumulate_fields(
            (index[("tp", step)] for step in profile.request_steps_h),
            profile.output_steps_h,
            "depth",
        )
        if "tp" in profile.parameters
        else {}
    )
    cp = (
        deaccumulate_fields(
            (index[("cp", step)] for step in profile.request_steps_h),
            profile.output_steps_h,
            "depth",
        )
        if "cp" in profile.parameters
        else {}
    )
    rows: list[dict[str, object]] = []
    for step in profile.output_steps_h:
        ssrd_field = index[("ssrd", step)]
        tp_result = tp.get(step)
        cp_result = cp.get(step)
        sp = _value_with_units(_instant(index, "sp", step), {"pa"})
        row = {
            "site_id": site.site_id,
            "nwp_provider": "ecmwf_opendata",
            "nwp_source": profile.nwp_source,
            "nwp_model": profile.model.value,
            "issue_time_utc": issue,
            "valid_time_utc": issue + timedelta(hours=step),
            "retrieved_at_utc": retrieved,
            "lead_time_min": step * 60,
            "ssrd_wm2": ssrd_mean_wm2(ssrd[step]),
            "ssrd_accum_jm2": ssrd[step].raw_value,
            "ssrd_interval_jm2": ssrd[step].interval_value,
            "ssrd_interval_seconds": ssrd[step].interval_seconds,
            "ssrd_conversion_method": ssrd[step].method,
            "grib_start_step_h": ssrd_field.start_step_h,
            "grib_end_step_h": ssrd_field.end_step_h,
            "grib_step_type": ssrd_field.step_type,
            "tcc_frac": _cloud_fraction(_instant(index, "tcc", step)),
            "lcc_frac": _cloud_fraction(_instant(index, "lcc", step)),
            "mcc_frac": _cloud_fraction(_instant(index, "mcc", step)),
            "hcc_frac": _cloud_fraction(_instant(index, "hcc", step)),
            "t2m_c": _temperature_c(_instant(index, "2t", step)),
            "d2m_c": _temperature_c(_instant(index, "2d", step)),
            "u10_ms": _value_with_units(
                _instant(index, "10u", step),
                {"ms**-1", "ms-1", "m/s"},
            ),
            "v10_ms": _value_with_units(
                _instant(index, "10v", step),
                {"ms**-1", "ms-1", "m/s"},
            ),
            "tp_accum_m": None if tp_result is None else tp_result.raw_value,
            "tp_interval_m": None if tp_result is None else tp_result.interval_value,
            "tp_mm": None if tp_result is None else precipitation_mm(tp_result),
            "sp_pa": sp,
            "sp_hpa": None if sp is None else sp / 100.0,
            "tcwv_kgm2": _value_with_units(
                _instant(index, "tcwv", step),
                {"kgm**-2", "kgm-2", "kg/m2"},
            ),
            "cp_accum_m": None if cp_result is None else cp_result.raw_value,
            "cp_interval_m": None if cp_result is None else cp_result.interval_value,
            "cp_mm": None if cp_result is None else precipitation_mm(cp_result),
            "mucape_jkg": _value_with_units(
                _instant(index, "mucape", step),
                {"jkg**-1", "jkg-1", "j/kg"},
            ),
            "site_latitude": site.latitude_deg,
            "site_longitude": site.longitude_deg,
            "grid_latitude": grid_latitude,
            "grid_longitude": grid_longitude,
            "grid_distance_km": distance,
            "grid_selection_method": "nearest",
            "ecmwf_client_source": ecmwf_client_source,
            "ecmwf_client_version": ecmwf_client_version,
            "eccodes_version": eccodes_version,
            "schema_version": NWP_SCHEMA_VERSION,
            "ecmwf_dataset_url": ECMWF_DATASET_URL,
            "licence_id": ECMWF_LICENCE_ID,
        }
        rows.append(row)
    frame = pd.DataFrame(rows).reindex(columns=NWP_COLUMNS)
    for column in ("issue_time_utc", "valid_time_utc", "retrieved_at_utc"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return canonicalize_nwp_frame(frame)
