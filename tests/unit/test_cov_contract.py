from __future__ import annotations

import pytest

from src.characterisation.cov_contract import (
    CovContractError,
    ParameterClass,
    parse_scada_tag,
)


def test_parser_reads_identity_from_full_tag() -> None:
    identity = parse_scada_tag(
        "PLTS IKN / STS09 / WB09_EMI01 / MEAS / "
        "GLOBAL HORIZONTAL IRRADIANCE (GHI)"
    )

    assert identity.site_label == "PLTS IKN"
    assert identity.sts == "STS09"
    assert identity.wb == "WB09"
    assert identity.emi == "EMI01"
    assert identity.raw_parameter == "GLOBAL HORIZONTAL IRRADIANCE (GHI)"
    assert identity.canonical_parameter == "Global Horizontal Irradiance (GHI)"
    assert identity.parameter_class is ParameterClass.INSTANTANEOUS_IRRADIANCE
    assert identity.channel_group == "GHI"


@pytest.mark.parametrize(
    ("emi", "sts", "wb"),
    [
        ("EMI01", "STS09", "WB09"),
        ("EMI02", "STS05", "WB05"),
        ("EMI03", "STS06", "WB06"),
        ("EMI04", "STS04", "WB04"),
        ("EMI05", "STS02", "WB02"),
    ],
)
def test_approved_emi_location_mapping(emi: str, sts: str, wb: str) -> None:
    raw_parameter = "Total Irradiance" if emi == "EMI05" else "WIND SPEED"
    identity = parse_scada_tag(
        f"PLTS IKN / {sts} / {wb}_{emi} / MEAS / {raw_parameter}"
    )
    assert (identity.emi, identity.sts, identity.wb) == (emi, sts, wb)


@pytest.mark.parametrize(
    ("raw_parameter", "canonical", "parameter_class", "channel"),
    [
        (
            "DIFFUSE HORIZONTAL IRRADIANCE (DHI)",
            "Diffuse Horizontal Irradiance (DHI)",
            ParameterClass.INSTANTANEOUS_IRRADIANCE,
            "DHI",
        ),
        (
            "DIRECT HORIZONTAL IRRADIANCE (DNI*cosZ)",
            "Direct Horizontal Irradiance (DNIcosZ)",
            ParameterClass.INSTANTANEOUS_IRRADIANCE,
            "DNIcosZ",
        ),
        (
            "GLOBAL INCLINED IRRADIANCE (POA)",
            "Global Inclined Irradiance (POA)",
            ParameterClass.INSTANTANEOUS_IRRADIANCE,
            "POA",
        ),
        (
            "IN-PLANE REAR-SIDE IRRADIANCE (RSI) 03",
            "In-Plane Rear-Side Irradiance (RSI) 03",
            ParameterClass.INSTANTANEOUS_IRRADIANCE,
            "RSI",
        ),
        (
            "DHI DAILY ACCUM",
            "DHI Daily Acummulation",
            ParameterClass.IRRADIANCE_ACCUMULATION,
            None,
        ),
        (
            "DNI*cosZ MONTHLY ACCUM",
            "DNIcosZ Monthly Acummulation",
            ParameterClass.IRRADIANCE_ACCUMULATION,
            None,
        ),
        (
            "RSI YEARLY ACCUM 02",
            "RSI 02 Yearly Acummulation",
            ParameterClass.IRRADIANCE_ACCUMULATION,
            None,
        ),
    ],
)
def test_emi01_to_emi04_canonical_mapping(
    raw_parameter: str,
    canonical: str,
    parameter_class: ParameterClass,
    channel: str | None,
) -> None:
    identity = parse_scada_tag(
        f"PLTS IKN / STS05 / WB05_EMI02 / MEAS / {raw_parameter}"
    )
    assert (
        identity.canonical_parameter,
        identity.parameter_class,
        identity.channel_group,
    ) == (canonical, parameter_class, channel)


@pytest.mark.parametrize(
    ("raw_parameter", "canonical", "parameter_class", "channel"),
    [
        (
            "Total Irradiance",
            "Global Horizontal Irradiance (GHI)",
            ParameterClass.INSTANTANEOUS_IRRADIANCE,
            "GHI",
        ),
        (
            "Daily radiation",
            "GHI Daily Acummulation",
            ParameterClass.IRRADIANCE_ACCUMULATION,
            None,
        ),
    ],
)
def test_emi05_aliases(
    raw_parameter: str,
    canonical: str,
    parameter_class: ParameterClass,
    channel: str | None,
) -> None:
    identity = parse_scada_tag(
        f"PLTS IKN / STS02 / WB02_EMI05 / MEAS / {raw_parameter}"
    )
    assert (
        identity.canonical_parameter,
        identity.parameter_class,
        identity.channel_group,
    ) == (canonical, parameter_class, channel)


def test_mapping_is_case_and_whitespace_tolerant() -> None:
    identity = parse_scada_tag(
        " plts ikn / sts02 / wb02_emi05 / meas /   daily   radiation "
    )
    assert identity.canonical_parameter == "GHI Daily Acummulation"


def test_mismatched_emi_tuple_is_rejected() -> None:
    with pytest.raises(CovContractError, match="EMI01 expects STS09/WB09"):
        parse_scada_tag(
            "PLTS IKN / STS05 / WB05_EMI01 / MEAS / WIND SPEED"
        )


def test_unknown_irradiance_like_parameter_is_rejected() -> None:
    with pytest.raises(CovContractError, match="unknown irradiance-like"):
        parse_scada_tag(
            "PLTS IKN / STS09 / WB09_EMI01 / MEAS / NEW IRRADIANCE"
        )


def test_unknown_non_irradiance_parameter_is_preserved_as_meteorological() -> None:
    identity = parse_scada_tag(
        "PLTS IKN / STS09 / WB09_EMI01 / MEAS / PRESSURE"
    )
    assert identity.canonical_parameter == "PRESSURE"
    assert identity.parameter_class is ParameterClass.METEOROLOGICAL
    assert identity.channel_group is None
