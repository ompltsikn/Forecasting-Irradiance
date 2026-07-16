from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import AbstractSet, Iterable, Literal, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


UTC = timezone.utc
EARTH_RADIUS_KM = 6371.0088
SSRD_NEGATIVE_TOLERANCE_JM2 = 1e-6
PRECIP_NEGATIVE_TOLERANCE_M = 1e-9


class SiteConfigError(ValueError):
    pass


class AccumulationError(ValueError):
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
class AccumulationResult:
    raw_value: float
    interval_value: float | None
    interval_seconds: int
    method: str


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
