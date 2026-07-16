from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from pathlib import Path
from typing import AbstractSet, Literal, Sequence
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


UTC = timezone.utc


class SiteConfigError(ValueError):
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
