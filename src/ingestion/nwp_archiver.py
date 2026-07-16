from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


class SiteConfigError(ValueError):
    pass


class NwpModel(StrEnum):
    IFS = "ifs"
    AIFS_SINGLE = "aifs-single"


class ArchiveProfile(StrEnum):
    SMOKE = "smoke"
    FULL = "full"
    CATCHUP = "catchup"


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
