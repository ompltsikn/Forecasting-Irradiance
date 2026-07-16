from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.nwp_archiver import (
    AccumulationError,
    DecodedField,
    deaccumulate_fields,
    haversine_km,
    precipitation_mm,
    ssrd_mean_wm2,
)


UTC = timezone.utc
ISSUE = datetime(2026, 7, 16, 6, tzinfo=UTC)


def field(
    *,
    end: int,
    value: float,
    start: int = 0,
    units: str = "J m**-2",
    step_type: str = "accum",
    packing_error: float = 0.0,
) -> DecodedField:
    return DecodedField(
        parameter="ssrd",
        value=value,
        units=units,
        issue_time_utc=ISSUE,
        valid_time_utc=ISSUE + timedelta(hours=end),
        start_step_h=start,
        end_step_h=end,
        step_type=step_type,
        grid_latitude=-1.0,
        grid_longitude=116.75,
        packing_error=packing_error,
    )


def test_interval_accumulation_uses_raw_interval() -> None:
    result = deaccumulate_fields(
        (field(start=3, end=6, value=1_080_000.0),), (6,), "energy"
    )
    assert result[6].interval_value == 1_080_000.0
    assert result[6].interval_seconds == 10_800
    assert result[6].method == "interval_accumulation"
    assert ssrd_mean_wm2(result[6]) == 100.0


def test_run_total_is_differenced_against_predecessor() -> None:
    fields = (
        field(end=0, value=0.0),
        field(end=3, value=1_080_000.0),
        field(end=6, value=3_240_000.0),
    )
    result = deaccumulate_fields(fields, (0, 3, 6), "energy")
    assert result[0].interval_value is None
    assert result[0].interval_seconds == 0
    assert result[3].interval_value == 1_080_000.0
    assert result[6].interval_value == 2_160_000.0
    assert ssrd_mean_wm2(result[3]) == 100.0
    assert ssrd_mean_wm2(result[6]) == 200.0


def test_run_total_without_predecessor_is_rejected() -> None:
    with pytest.raises(AccumulationError, match="predecessor"):
        deaccumulate_fields((field(end=6, value=3_240_000.0),), (6,), "energy")


def test_tiny_negative_roundoff_is_zero_but_material_negative_fails() -> None:
    tiny = (field(end=0, value=1.0), field(end=3, value=1.0 - 5e-7))
    assert deaccumulate_fields(tiny, (3,), "energy")[3].interval_value == 0.0
    material = (field(end=0, value=1000.0), field(end=3, value=999.99))
    with pytest.raises(AccumulationError, match="negative"):
        deaccumulate_fields(material, (3,), "energy")


def test_negative_within_combined_grib_packing_error_is_zero() -> None:
    packed = (
        field(end=6, value=1_000_000.0, packing_error=256.0),
        field(end=12, value=999_488.0, packing_error=256.0),
    )
    assert deaccumulate_fields(packed, (12,), "energy")[12].interval_value == 0.0


def test_negative_beyond_combined_grib_packing_error_is_rejected() -> None:
    packed = (
        field(end=6, value=1_000_000.0, packing_error=256.0),
        field(end=12, value=999_487.0, packing_error=256.0),
    )
    with pytest.raises(AccumulationError, match="negative"):
        deaccumulate_fields(packed, (12,), "energy")


def test_trace_negative_precipitation_below_grib_floor_is_zero() -> None:
    packed = (
        field(end=6, value=0.001, units="m"),
        field(end=12, value=0.001 - 3.90625e-6, units="m"),
    )
    assert deaccumulate_fields(packed, (12,), "depth")[12].interval_value == 0.0


def test_negative_precipitation_above_grib_floor_is_rejected() -> None:
    packed = (
        field(end=6, value=0.001, units="m"),
        field(end=12, value=0.001 - 4.1e-5, units="m"),
    )
    with pytest.raises(AccumulationError, match="negative"):
        deaccumulate_fields(packed, (12,), "depth")


@pytest.mark.parametrize(
    ("start", "end", "step_type", "units", "match"),
    [
        (3, 3, "accum", "J m**-2", "positive"),
        (6, 3, "accum", "J m**-2", "positive"),
        (3, 6, "instant", "J m**-2", "step_type"),
        (3, 6, "accum", "W m**-2", "units"),
    ],
)
def test_invalid_accumulation_metadata_is_rejected(
    start: int, end: int, step_type: str, units: str, match: str
) -> None:
    with pytest.raises(AccumulationError, match=match):
        deaccumulate_fields(
            (field(start=start, end=end, value=1.0, step_type=step_type, units=units),),
            (end,),
            "energy",
        )


def test_precipitation_converts_interval_metres_to_mm() -> None:
    rain = field(start=0, end=3, value=0.0012, units="m")
    zero = field(start=0, end=0, value=0.0, units="m")
    result = deaccumulate_fields((zero, rain), (3,), "depth")[3]
    assert precipitation_mm(result) == 1.2


def test_precipitation_converts_kg_per_square_metre_to_metres_and_mm() -> None:
    zero = field(start=0, end=0, value=0.0, units="kg m**-2")
    rain = field(start=0, end=3, value=1.2, units="kg m**-2")
    result = deaccumulate_fields((zero, rain), (3,), "depth")[3]
    assert result.raw_value == pytest.approx(0.0012)
    assert result.interval_value == pytest.approx(0.0012)
    assert precipitation_mm(result) == pytest.approx(1.2)


def test_run_total_predecessor_metadata_is_validated() -> None:
    bad_predecessor = field(end=42, value=1.0, units="W m**-2")
    current = field(end=48, value=2.0)
    with pytest.raises(AccumulationError, match="predecessor.*units"):
        deaccumulate_fields((bad_predecessor, current), (48,), "energy")


def test_haversine_reference_distance() -> None:
    assert haversine_km(
        -0.9911713315158186, 116.63811127764585, -1.0, 116.75
    ) == pytest.approx(12.478274049682074, abs=1e-12)
