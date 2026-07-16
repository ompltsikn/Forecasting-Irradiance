from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from data_contracts.nwp_schema import (
    NWP_COLUMNS,
    NWP_FLOAT_COLUMNS,
    NWP_INTEGER_COLUMNS,
    NWP_STRING_COLUMNS,
    TIMESTAMP_COLUMNS,
)
from src.ingestion.nwp_archiver import (
    ArchiveProfile,
    DecodedField,
    NwpModel,
    SitePoint,
    normalise_run,
    request_profile_for,
    validate_field_completeness,
)


UTC = timezone.utc
ISSUE = datetime(2026, 7, 16, 6, tzinfo=UTC)
RETRIEVED = datetime(2026, 7, 16, 7, 15, 30, tzinfo=UTC)
SITE = SitePoint(
    "PLTS-IKN",
    -0.9911713315158186,
    116.63811127764585,
    85.0,
    "Asia/Makassar",
)


def make_field(parameter: str, step: int) -> DecodedField:
    accumulated = parameter in {"ssrd", "tp", "cp"}
    # Synthetic fields represent ECMWF run-total accumulations. Keeping
    # startStep=0 lets the normaliser derive each interval from consecutive
    # endStep values, including the smoke predecessor before +48 h.
    start = 0
    if parameter == "ssrd":
        value, units = step * 3600 * 100.0, "J m**-2"
    elif parameter in {"tp", "cp"}:
        value, units = step * 0.0004, "m"
    elif parameter in {"tcc", "lcc", "mcc", "hcc"}:
        value, units = 0.25, "(0 - 1)"
    elif parameter == "2t":
        value, units = 300.0, "K"
    elif parameter == "2d":
        value, units = 298.15, "K"
    elif parameter == "10u":
        value, units = 2.5, "m s**-1"
    elif parameter == "10v":
        value, units = -1.0, "m s**-1"
    elif parameter == "sp":
        value, units = 100000.0, "Pa"
    elif parameter == "tcwv":
        value, units = 30.0, "kg m**-2"
    elif parameter == "mucape":
        value, units = 400.0, "J kg**-1"
    else:
        raise AssertionError(parameter)
    return DecodedField(
        parameter=parameter,
        value=value,
        units=units,
        issue_time_utc=ISSUE,
        valid_time_utc=ISSUE + timedelta(hours=step),
        start_step_h=start if accumulated else step,
        end_step_h=step,
        step_type="accum" if accumulated else "instant",
        grid_latitude=-1.0,
        grid_longitude=116.75,
    )


def fields_for(
    model: NwpModel,
    profile_name: ArchiveProfile,
) -> tuple[DecodedField, ...]:
    profile = request_profile_for(model, profile_name)
    return tuple(
        make_field(parameter, step)
        for parameter in profile.parameters
        for step in profile.request_steps_h
    )


def normalise(
    model: NwpModel,
    profile_name: ArchiveProfile,
    fields: tuple[DecodedField, ...] | None = None,
) -> pd.DataFrame:
    profile = request_profile_for(model, profile_name)
    return normalise_run(
        fields if fields is not None else fields_for(model, profile_name),
        site=SITE,
        profile=profile,
        retrieved_at_utc=RETRIEVED,
        ecmwf_client_source="google",
        ecmwf_client_version="0.3.30",
        eccodes_version="2.47.0",
    )


def test_missing_required_parameter_or_step_prevents_publish() -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.FULL)
    fields = fields_for(NwpModel.IFS, ArchiveProfile.FULL)
    missing_mucape = tuple(
        field
        for field in fields
        if not (field.parameter == "mucape" and field.end_step_h == 144)
    )
    with pytest.raises(ValueError, match="missing.*mucape.*144"):
        validate_field_completeness(missing_mucape, profile)


def test_unexpected_parameter_or_step_prevents_publish() -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.SMOKE)
    fields = fields_for(NwpModel.IFS, ArchiveProfile.SMOKE)
    with pytest.raises(ValueError, match="unexpected.*mucape.*48"):
        validate_field_completeness(fields + (make_field("mucape", 48),), profile)


def test_duplicate_parameter_step_is_rejected() -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.SMOKE)
    fields = fields_for(NwpModel.IFS, ArchiveProfile.SMOKE)
    with pytest.raises(ValueError, match="duplicate"):
        validate_field_completeness(fields + (fields[-1],), profile)


def test_smoke_publishes_only_lead_48_after_using_predecessor() -> None:
    frame = normalise(NwpModel.IFS, ArchiveProfile.SMOKE)
    assert frame["lead_time_min"].tolist() == [2880]
    assert frame.loc[0, "ssrd_wm2"] == 100.0
    assert frame.loc[0, "ssrd_accum_jm2"] == 17_280_000.0
    assert frame.loc[0, "ssrd_interval_jm2"] == 1_080_000.0


def test_full_ifs_has_exact_horizon_and_model_specific_nulls() -> None:
    frame = normalise(NwpModel.IFS, ArchiveProfile.FULL)
    assert len(frame) == 49
    assert frame["lead_time_min"].iloc[[0, -1]].tolist() == [0, 8640]
    assert (
        frame[
            [
                "lcc_frac",
                "mcc_frac",
                "hcc_frac",
                "cp_accum_m",
                "cp_interval_m",
                "cp_mm",
            ]
        ]
        .isna()
        .all()
        .all()
    )
    assert frame["tcwv_kgm2"].notna().all()
    assert frame["mucape_jkg"].notna().all()


def test_full_aifs_has_exact_horizon_and_model_specific_nulls() -> None:
    frame = normalise(NwpModel.AIFS_SINGLE, ArchiveProfile.FULL)
    assert len(frame) == 25
    assert frame["lead_time_min"].iloc[[0, -1]].tolist() == [0, 8640]
    assert (
        frame[["lcc_frac", "mcc_frac", "hcc_frac", "cp_mm"]]
        .iloc[1:]
        .notna()
        .all()
        .all()
    )
    assert frame[["tcwv_kgm2", "mucape_jkg"]].isna().all().all()


def test_unit_conversions_retain_source_audit_values() -> None:
    frame = normalise(NwpModel.IFS, ArchiveProfile.FULL)
    row = frame.loc[1]
    assert row["tcc_frac"] == 0.25
    assert row["t2m_c"] == pytest.approx(26.85)
    assert row["d2m_c"] == 25.0
    assert row["u10_ms"] == 2.5
    assert row["v10_ms"] == -1.0
    assert row["sp_pa"] == 100000.0
    assert row["sp_hpa"] == 1000.0
    assert row["tp_accum_m"] == pytest.approx(0.0012)
    assert row["tp_interval_m"] == pytest.approx(0.0012)
    assert row["tp_mm"] == pytest.approx(1.2)
    assert row["ssrd_accum_jm2"] == 1_080_000.0
    assert row["ssrd_interval_jm2"] == 1_080_000.0
    assert row["ssrd_interval_seconds"] == 10_800
    assert row["ssrd_conversion_method"] == "run_total_difference"
    assert row["grib_start_step_h"] == 0
    assert row["grib_end_step_h"] == 3
    assert row["grib_step_type"] == "accum"


def test_precipitation_kgm2_units_normalize_to_m_and_mm() -> None:
    fields = tuple(
        replace(field, value=field.value * 1000.0, units="kg m**-2")
        if field.parameter in {"tp", "cp"}
        else field
        for field in fields_for(NwpModel.AIFS_SINGLE, ArchiveProfile.FULL)
    )
    frame = normalise(NwpModel.AIFS_SINGLE, ArchiveProfile.FULL, fields)
    row = frame.loc[1]
    for prefix in ("tp", "cp"):
        assert row[f"{prefix}_accum_m"] == pytest.approx(0.0024)
        assert row[f"{prefix}_interval_m"] == pytest.approx(0.0024)
        assert row[f"{prefix}_mm"] == pytest.approx(2.4)


def test_percentage_cloud_units_normalize_to_fraction() -> None:
    fields = tuple(
        replace(field, value=25.0, units="%")
        if field.parameter == "tcc" and field.end_step_h == 3
        else field
        for field in fields_for(NwpModel.IFS, ArchiveProfile.FULL)
    )
    frame = normalise(NwpModel.IFS, ArchiveProfile.FULL, fields)
    assert frame.loc[1, "tcc_frac"] == 0.25


def test_normalized_frame_records_actual_selected_grid() -> None:
    frame = normalise(NwpModel.IFS, ArchiveProfile.SMOKE)
    assert frame.loc[0, "grid_latitude"] == -1.0
    assert frame.loc[0, "grid_longitude"] == 116.75
    assert frame.loc[0, "grid_selection_method"] == "nearest"
    assert 0.0 < frame.loc[0, "grid_distance_km"] <= 25.0


def test_selected_grid_beyond_25_km_is_rejected() -> None:
    fields = tuple(
        replace(field, grid_latitude=-0.5, grid_longitude=116.75)
        for field in fields_for(NwpModel.IFS, ArchiveProfile.SMOKE)
    )
    with pytest.raises(ValueError, match="too far away"):
        normalise(NwpModel.IFS, ArchiveProfile.SMOKE, fields)


def test_frame_identity_and_three_utc_timestamps_are_exact() -> None:
    frame = normalise(NwpModel.AIFS_SINGLE, ArchiveProfile.FULL)
    assert frame["site_id"].unique().tolist() == ["PLTS-IKN"]
    assert frame["nwp_provider"].unique().tolist() == ["ecmwf_opendata"]
    assert frame["nwp_source"].unique().tolist() == ["ecmwf_aifs_single"]
    assert frame["nwp_model"].unique().tolist() == ["aifs-single"]
    assert (frame["issue_time_utc"] == pd.Timestamp(ISSUE)).all()
    assert frame.loc[0, "valid_time_utc"] == pd.Timestamp(ISSUE)
    assert frame.loc[24, "valid_time_utc"] == pd.Timestamp(
        ISSUE + timedelta(hours=144)
    )
    assert (frame["retrieved_at_utc"] == pd.Timestamp(RETRIEVED)).all()
    assert frame.loc[1, "valid_time_utc"] != frame.loc[1, "issue_time_utc"]
    assert frame.loc[1, "retrieved_at_utc"] != frame.loc[1, "valid_time_utc"]


def test_canonical_column_order_and_dtypes_are_stable() -> None:
    frame = normalise(NwpModel.IFS, ArchiveProfile.FULL)
    assert tuple(frame.columns) == NWP_COLUMNS
    for column in TIMESTAMP_COLUMNS:
        assert str(frame[column].dtype) == "datetime64[ns, UTC]"
    for column in NWP_INTEGER_COLUMNS:
        assert str(frame[column].dtype) == "Int64"
    for column in NWP_FLOAT_COLUMNS:
        assert str(frame[column].dtype) == "Float64"
    for column in NWP_STRING_COLUMNS:
        assert str(frame[column].dtype) == "string"
