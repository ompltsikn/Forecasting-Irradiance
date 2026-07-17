"""Canonical SCADA tag parsing and parameter classification for S0-2."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class CovContractError(ValueError):
    """Raised when a SCADA tag violates the approved source contract."""


class ParameterClass(StrEnum):
    """Mutually exclusive parameter classes used by COV characterisation."""

    INSTANTANEOUS_IRRADIANCE = "instantaneous_irradiance"
    IRRADIANCE_ACCUMULATION = "irradiance_accumulation"
    METEOROLOGICAL = "meteorological"


@dataclass(frozen=True)
class TagIdentity:
    """Parsed and canonicalised identity of one SCADA tag."""

    full_tag: str
    site_label: str
    sts: str
    wb: str
    emi: str
    raw_parameter: str
    canonical_parameter: str
    parameter_class: ParameterClass
    channel_group: str | None


EMI_LOCATIONS: dict[str, tuple[str, str]] = {
    "EMI01": ("STS09", "WB09"),
    "EMI02": ("STS05", "WB05"),
    "EMI03": ("STS06", "WB06"),
    "EMI04": ("STS04", "WB04"),
    "EMI05": ("STS02", "WB02"),
}

INSTANTANEOUS: dict[str, tuple[str, str]] = {
    "DIFFUSE HORIZONTAL IRRADIANCE (DHI)": (
        "Diffuse Horizontal Irradiance (DHI)",
        "DHI",
    ),
    "DIRECT HORIZONTAL IRRADIANCE (DNI*COSZ)": (
        "Direct Horizontal Irradiance (DNIcosZ)",
        "DNIcosZ",
    ),
    "GLOBAL HORIZONTAL IRRADIANCE (GHI)": (
        "Global Horizontal Irradiance (GHI)",
        "GHI",
    ),
    "GLOBAL INCLINED IRRADIANCE (POA)": (
        "Global Inclined Irradiance (POA)",
        "POA",
    ),
    "IN-PLANE REAR-SIDE IRRADIANCE (RSI) 01": (
        "In-Plane Rear-Side Irradiance (RSI) 01",
        "RSI",
    ),
    "IN-PLANE REAR-SIDE IRRADIANCE (RSI) 02": (
        "In-Plane Rear-Side Irradiance (RSI) 02",
        "RSI",
    ),
    "IN-PLANE REAR-SIDE IRRADIANCE (RSI) 03": (
        "In-Plane Rear-Side Irradiance (RSI) 03",
        "RSI",
    ),
}

ACCUMULATION_BASES: dict[str, str] = {
    "DHI": "DHI",
    "DNI*COSZ": "DNIcosZ",
    "GHI": "GHI",
    "POA": "POA",
}

IRRADIANCE_MARKERS = (
    "IRRADIANCE",
    "RADIATION",
    "DHI",
    "DNI",
    "GHI",
    "POA",
    "RSI",
)

TAG_PATTERN = re.compile(
    r"^\s*(PLTS IKN)\s*/\s*(STS\d{2})\s*/\s*"
    r"(WB\d{2})_(EMI\d{2})\s*/\s*MEAS\s*/\s*(.+?)\s*$",
    re.IGNORECASE,
)


def _normalise_parameter(raw_parameter: str) -> str:
    return " ".join(raw_parameter.split())


def canonicalise_parameter(
    emi: str,
    raw_parameter: str,
) -> tuple[str, ParameterClass, str | None]:
    """Return canonical name, class, and optional five-channel group."""

    normalized = _normalise_parameter(raw_parameter)
    key = normalized.upper()
    emi = emi.upper()

    if emi == "EMI05":
        if key == "TOTAL IRRADIANCE":
            return (
                "Global Horizontal Irradiance (GHI)",
                ParameterClass.INSTANTANEOUS_IRRADIANCE,
                "GHI",
            )
        if key == "DAILY RADIATION":
            return (
                "GHI Daily Acummulation",
                ParameterClass.IRRADIANCE_ACCUMULATION,
                None,
            )
    else:
        instantaneous = INSTANTANEOUS.get(key)
        if instantaneous is not None:
            canonical, channel_group = instantaneous
            return (
                canonical,
                ParameterClass.INSTANTANEOUS_IRRADIANCE,
                channel_group,
            )

        accumulation = re.fullmatch(
            r"(DHI|DNI\*COSZ|GHI|POA) (DAILY|MONTHLY|YEARLY) ACCUM",
            key,
        )
        if accumulation:
            base, period = accumulation.groups()
            return (
                f"{ACCUMULATION_BASES[base]} {period.title()} Acummulation",
                ParameterClass.IRRADIANCE_ACCUMULATION,
                None,
            )

        rsi_accumulation = re.fullmatch(
            r"RSI (DAILY|MONTHLY|YEARLY) ACCUM (01|02|03)",
            key,
        )
        if rsi_accumulation:
            period, sensor = rsi_accumulation.groups()
            return (
                f"RSI {sensor} {period.title()} Acummulation",
                ParameterClass.IRRADIANCE_ACCUMULATION,
                None,
            )

    if any(marker in key for marker in IRRADIANCE_MARKERS):
        raise CovContractError(
            f"unknown irradiance-like parameter for {emi}: {raw_parameter}"
        )

    return normalized, ParameterClass.METEOROLOGICAL, None


def parse_scada_tag(full_tag: str) -> TagIdentity:
    """Parse a full SCADA header tag and validate its physical location."""

    match = TAG_PATTERN.fullmatch(full_tag)
    if match is None:
        raise CovContractError(f"invalid SCADA tag: {full_tag}")

    site_label, sts, wb, emi, raw_parameter = match.groups()
    site_label = site_label.upper()
    sts = sts.upper()
    wb = wb.upper()
    emi = emi.upper()
    raw_parameter = _normalise_parameter(raw_parameter)

    expected = EMI_LOCATIONS.get(emi)
    if expected is None:
        raise CovContractError(f"unknown EMI: {emi}")
    if (sts, wb) != expected:
        raise CovContractError(
            f"{emi} expects {expected[0]}/{expected[1]}, got {sts}/{wb}"
        )

    canonical, parameter_class, channel_group = canonicalise_parameter(
        emi,
        raw_parameter,
    )
    return TagIdentity(
        full_tag=full_tag,
        site_label=site_label,
        sts=sts,
        wb=wb,
        emi=emi,
        raw_parameter=raw_parameter,
        canonical_parameter=canonical,
        parameter_class=parameter_class,
        channel_group=channel_group,
    )
