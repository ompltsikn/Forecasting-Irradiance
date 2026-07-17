from __future__ import annotations

import pandas as pd
import pytest

from src.characterisation.dni_cosz import (
    align_cov_backward,
    analyse_dni_cosz_events,
    classify_residuals,
    coincident_residuals,
    derive_residual_tolerances,
    quantization_from_tag_stats,
    resolve_semantics,
    solar_zenith_sensitivity,
    summarise_residuals,
)


def test_coincident_residuals_compute_physical_closure() -> None:
    timestamp = pd.Timestamp("2026-06-01 12:00:00")
    rows = [
        {
            "emi": "EMI01",
            "channel_group": channel,
            "parameter_class": "instantaneous_irradiance",
            "event_time": timestamp,
            "event_time_ns": timestamp.value,
            "value": value,
        }
        for channel, value in (("GHI", 600.0), ("DHI", 150.0), ("DNIcosZ", 450.0))
    ]

    result = coincident_residuals(pd.DataFrame(rows))

    assert result[["emi", "event_time", "residual_wm2"]].to_dict("records") == [
        {
            "emi": "EMI01",
            "event_time": timestamp,
            "residual_wm2": 0.0,
        }
    ]


def test_alignment_uses_only_past_cov_values() -> None:
    start = pd.Timestamp("2026-06-01 12:00:00")
    rows: list[dict[str, object]] = []
    for minute, values in (
        (0, {"GHI": 100.0, "DHI": 20.0, "DNIcosZ": 80.0}),
        (2, {"GHI": 200.0, "DHI": 30.0, "DNIcosZ": 170.0}),
    ):
        timestamp = start + pd.Timedelta(minutes=minute)
        for channel, value in values.items():
            rows.append(
                {
                    "emi": "EMI01",
                    "channel_group": channel,
                    "parameter_class": "instantaneous_irradiance",
                    "event_time": timestamp,
                    "event_time_ns": timestamp.value,
                    "value": value,
                }
            )

    aligned = align_cov_backward(
        pd.DataFrame(rows),
        frequency="1min",
        staleness_s=120.0,
    )

    middle = aligned.loc[aligned["grid_time"] == start + pd.Timedelta(minutes=1)].iloc[0]
    assert middle["GHI"] == 100.0
    assert middle["residual_wm2"] == 0.0
    for channel in ("GHI", "DHI", "DNIcosZ"):
        assert middle[f"{channel}_source_time"] <= middle["grid_time"]


def test_exact_zero_decision_is_invariant_to_a_fixed_timestamp_offset() -> None:
    start = pd.Timestamp("2026-06-01 09:00:00")
    rows: list[dict[str, object]] = []
    for minute in range(25):
        timestamp = start + pd.Timedelta(minutes=minute)
        for channel, value in (("GHI", 500.0), ("DHI", 100.0), ("DNIcosZ", 400.0)):
            rows.append(
                {
                    "emi": "EMI01",
                    "channel_group": channel,
                    "parameter_class": "instantaneous_irradiance",
                    "event_time": timestamp,
                    "value": value,
                }
            )
    original = coincident_residuals(pd.DataFrame(rows))
    shifted_rows = pd.DataFrame(rows)
    shifted_rows["event_time"] += pd.Timedelta(hours=8)
    shifted = coincident_residuals(shifted_rows)

    tolerance = derive_residual_tolerances(
        input_scale_wm2=500.0,
        channel_quantization_wm2={"GHI": 1.0, "DHI": 1.0, "DNIcosZ": 1.0},
    )
    assert original["residual_wm2"].tolist() == shifted["residual_wm2"].tolist()
    assert classify_residuals(original["residual_wm2"], tolerance) == "derived"
    assert classify_residuals(shifted["residual_wm2"], tolerance) == "derived"


def test_coincident_residuals_sort_and_deduplicate_without_using_accumulations() -> None:
    timestamp = pd.Timestamp("2026-06-01 12:00:00")
    rows = [
        {
            "emi": "EMI01",
            "channel_group": channel,
            "parameter_class": "instantaneous_irradiance",
            "event_time": timestamp,
            "event_time_ns": timestamp.value,
            "value": value,
        }
        for channel, value in (("DNIcosZ", 450.0), ("DHI", 150.0), ("GHI", 600.0))
    ]
    rows.append(dict(rows[-1]))
    rows.extend(
        [
            {
                "emi": "EMI01",
                "channel_group": None,
                "parameter_class": "irradiance_accumulation",
                "event_time": timestamp,
                "event_time_ns": timestamp.value,
                "value": 99999.0,
            },
            {
                "emi": "EMI05",
                "channel_group": "GHI",
                "parameter_class": "instantaneous_irradiance",
                "event_time": timestamp,
                "event_time_ns": timestamp.value,
                "value": 600.0,
            },
        ]
    )

    result = coincident_residuals(pd.DataFrame(list(reversed(rows))))

    assert result["emi"].tolist() == ["EMI01"]
    assert result["residual_wm2"].tolist() == [0.0]


def test_conflicting_duplicate_values_are_rejected_explicitly() -> None:
    timestamp = pd.Timestamp("2026-06-01 12:00:00")
    rows = [
        {
            "emi": "EMI01",
            "channel_group": channel,
            "parameter_class": "instantaneous_irradiance",
            "event_time": timestamp,
            "value": value,
        }
        for channel, value in (("GHI", 600.0), ("DHI", 150.0), ("DNIcosZ", 450.0))
    ]
    rows.append({**rows[0], "value": 601.0})

    with pytest.raises(ValueError, match="conflicting values"):
        coincident_residuals(pd.DataFrame(rows))


def test_rounding_noise_is_classified_as_derived_from_quantization() -> None:
    tolerance = derive_residual_tolerances(
        input_scale_wm2=800.0,
        channel_quantization_wm2={"GHI": 0.1, "DHI": 0.1, "DNIcosZ": 0.1},
    )
    residuals = pd.Series([0.02, -0.04, 0.05, -0.01] * 10, dtype="float64")

    decision = classify_residuals(residuals, tolerance, minimum_samples=20)

    assert tolerance.quantization_atol_wm2 == 0.15
    assert decision == "derived"


def test_physical_residual_distribution_is_classified_as_measured() -> None:
    tolerance = derive_residual_tolerances(
        input_scale_wm2=800.0,
        channel_quantization_wm2={"GHI": 0.1, "DHI": 0.1, "DNIcosZ": 0.1},
    )
    residuals = pd.Series([-8.0, -5.0, -2.0, 3.0, 7.0, 11.0] * 10)

    decision = classify_residuals(residuals, tolerance, minimum_samples=20)

    assert decision == "measured"


def test_semantics_stays_unresolved_when_sensitivity_changes_decision() -> None:
    result = resolve_semantics(
        {
            "direct_coincident": "derived",
            "aligned_60s": "derived",
            "aligned_120s": "measured",
        }
    )

    assert result.decision == "unresolved"
    assert result.is_derived_tag is None
    assert "not stable" in result.reason


@pytest.mark.parametrize(
    ("label", "expected_boolean"),
    [("derived", True), ("measured", False)],
)
def test_stable_semantics_maps_to_metadata_boolean(
    label: str,
    expected_boolean: bool,
) -> None:
    result = resolve_semantics(
        {"direct_coincident": label, "aligned_60s": label, "aligned_120s": label}
    )

    assert result.decision == label
    assert result.is_derived_tag is expected_boolean


def test_residual_summary_reports_required_distribution_statistics() -> None:
    tolerance = derive_residual_tolerances(
        input_scale_wm2=100.0,
        channel_quantization_wm2={"GHI": 1.0, "DHI": 1.0, "DNIcosZ": 1.0},
    )

    summary = summarise_residuals(pd.Series([-2.0, 0.0, 2.0]), tolerance)

    assert summary["sample_count"] == 3
    assert summary["mean_wm2"] == 0.0
    assert summary["median_wm2"] == 0.0
    assert summary["mae_wm2"] == pytest.approx(4.0 / 3.0)
    assert summary["rmse_wm2"] == pytest.approx((8.0 / 3.0) ** 0.5)
    assert summary["p01_wm2"] == pytest.approx(-1.96)
    assert summary["p99_wm2"] == pytest.approx(1.96)
    assert summary["max_abs_wm2"] == 2.0
    assert summary["proportion_below_quantization"] == pytest.approx(1.0 / 3.0)


def test_zenith_sensitivity_labels_naive_wita_interpretation_provisional() -> None:
    times = pd.Series([pd.Timestamp("2026-06-21 12:00:00")])

    result = solar_zenith_sensitivity(
        times,
        latitude_deg=-0.9911713315158186,
        longitude_deg=116.63811127764585,
        local_timezone="Asia/Makassar",
    )

    assert result["zenith_assuming_naive_wita_deg"].between(0.0, 90.0).all()
    assert result["zenith_assuming_naive_utc_deg"].between(90.0, 180.0).all()
    assert result["zenith_interpretation_status"].eq("provisional").all()


def test_event_analysis_produces_stable_derived_metadata_decision() -> None:
    start = pd.Timestamp("2026-06-01 10:00:00")
    rows: list[dict[str, object]] = []
    for minute in range(40):
        timestamp = start + pd.Timedelta(minutes=minute)
        ghi = 500.0 + minute
        dhi = 100.0 + minute % 3
        for channel, value in (
            ("GHI", ghi),
            ("DHI", dhi),
            ("DNIcosZ", ghi - dhi),
        ):
            rows.append(
                {
                    "emi": "EMI01",
                    "channel_group": channel,
                    "parameter_class": "instantaneous_irradiance",
                    "event_time": timestamp,
                    "event_time_ns": timestamp.value,
                    "value": value,
                }
            )

    result = analyse_dni_cosz_events(
        pd.DataFrame(rows),
        quantization_by_emi={
            "EMI01": {"GHI": 1.0, "DHI": 1.0, "DNIcosZ": 1.0}
        },
        frequency="1min",
        staleness_windows_s=(60.0, 120.0),
        latitude_deg=-0.9911713315158186,
        longitude_deg=116.63811127764585,
        local_timezone="Asia/Makassar",
        source_scope="synthetic",
        minimum_samples=20,
    )

    assert result.decision.decision == "derived"
    assert result.decision.is_derived_tag is True
    per_emi = result.per_emi_summary.set_index("emi").loc["EMI01"]
    assert per_emi["exact_coincident_count"] == 40
    assert per_emi["event_count_DNIcosZ"] == 40
    assert set(result.residual_summary["method"]) == {
        "direct_coincident",
        "aligned_backward",
    }


def test_sparse_dni_cosz_keeps_semantics_unresolved() -> None:
    start = pd.Timestamp("2026-06-01 10:00:00")
    rows: list[dict[str, object]] = []
    for minute in range(40):
        timestamp = start + pd.Timedelta(minutes=minute)
        channels = [("GHI", 500.0 + minute), ("DHI", 100.0)]
        if minute in {0, 20, 39}:
            channels.append(("DNIcosZ", 400.0 + minute))
        for channel, value in channels:
            rows.append(
                {
                    "emi": "EMI01",
                    "channel_group": channel,
                    "parameter_class": "instantaneous_irradiance",
                    "event_time": timestamp,
                    "value": value,
                }
            )

    result = analyse_dni_cosz_events(
        pd.DataFrame(rows),
        quantization_by_emi={
            "EMI01": {"GHI": 1.0, "DHI": 1.0, "DNIcosZ": 1.0}
        },
        frequency="1min",
        staleness_windows_s=(60.0, 300.0),
        latitude_deg=-0.9911713315158186,
        longitude_deg=116.63811127764585,
        local_timezone="Asia/Makassar",
        source_scope="synthetic_sparse",
        minimum_samples=20,
    )

    assert result.decision.decision == "unresolved"
    assert result.decision.is_derived_tag is None


def test_quantization_uses_measured_deadband_with_explicit_delta_fallback() -> None:
    rows = []
    for channel, deadband, confidence, p01 in (
        ("GHI", 1.0, "high", 1.0),
        ("DHI", 1.0, "high", 1.0),
        ("DNIcosZ", None, "unresolved", 2.0),
    ):
        rows.append(
            {
                "emi": "EMI01",
                "channel_group": channel,
                "parameter_class": "instantaneous_irradiance",
                "deadband_estimate": deadband,
                "deadband_confidence": confidence,
                "abs_delta_p01": p01,
            }
        )

    mapping, evidence, errors = quantization_from_tag_stats(pd.DataFrame(rows))

    assert errors == ()
    assert mapping["EMI01"] == {"GHI": 1.0, "DHI": 1.0, "DNIcosZ": 2.0}
    fallback = evidence.loc[evidence["channel_group"] == "DNIcosZ"].iloc[0]
    assert fallback["quantization_source"] == "abs_delta_p01_fallback"
