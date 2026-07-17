from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.characterisation.cov_contract import ParameterClass, parse_scada_tag
from src.characterisation.cov_stats import (
    characterise_tag,
    characterise_tags,
    decide_canonical_frequency,
    estimate_deadband,
    estimate_heartbeat,
)


EMI01_GHI = (
    "PLTS IKN / STS09 / WB09_EMI01 / MEAS / "
    "GLOBAL HORIZONTAL IRRADIANCE (GHI)"
)
EMI01_DHI = (
    "PLTS IKN / STS09 / WB09_EMI01 / MEAS / "
    "DIFFUSE HORIZONTAL IRRADIANCE (DHI)"
)


def event_frame(
    tag: str,
    offsets_s: list[float],
    values: list[float],
) -> pd.DataFrame:
    identity = parse_scada_tag(tag)
    base = pd.Timestamp("2026-06-01 06:00:00")
    times = [base + pd.Timedelta(seconds=offset) for offset in offsets_s]
    return pd.DataFrame(
        {
            "full_tag": tag,
            "site_label": identity.site_label,
            "sts": identity.sts,
            "wb": identity.wb,
            "emi": identity.emi,
            "raw_parameter": identity.raw_parameter,
            "canonical_parameter": identity.canonical_parameter,
            "parameter_class": identity.parameter_class.value,
            "channel_group": identity.channel_group,
            "event_time_raw": [time.isoformat(sep=" ") for time in times],
            "event_time": times,
            "event_time_ns": [time.value for time in times],
            "timestamp_shape": "naive",
            "value": values,
            "object_caeid_raw": "0",
            "source_zip": "source.zip",
            "source_csv": "source.csv",
            "source_row": range(2, len(times) + 2),
        }
    )


def test_deadband_recovers_supported_float32_like_lower_edge() -> None:
    estimate = estimate_deadband(
        np.array([0.099998, 0.100000, 0.100006] * 20 + [0.01])
    )

    assert estimate.value == pytest.approx(0.1, abs=2e-5)
    assert estimate.support == 60
    assert estimate.support_fraction == pytest.approx(60 / 61)
    assert estimate.confidence == "high"
    assert estimate.lower_anomaly_count == 1
    assert estimate.unresolved_reason is None


def test_deadband_is_unresolved_with_fewer_than_twenty_positive_deltas() -> None:
    estimate = estimate_deadband(np.array([0.1] * 19))

    assert estimate.value is None
    assert estimate.confidence == "unresolved"
    assert "insufficient" in (estimate.unresolved_reason or "")


def test_tag_statistics_compute_interarrival_and_change_counts() -> None:
    frame = event_frame(
        EMI01_GHI,
        [0, 10, 20, 30, 90],
        [0.0, 0.1, 0.2, 0.2, 0.3],
    )

    stats = characterise_tag(frame)

    assert stats["interarrival_p50_s"] == 10.0
    assert stats["interarrival_p90_s"] == pytest.approx(45.0)
    assert stats["interarrival_p99_s"] == pytest.approx(58.5)
    assert stats["max_gap_s"] == 60.0
    assert stats["zero_change_count"] == 1
    assert stats["nonzero_change_count"] == 3


def test_active_and_flat_intervals_are_reported_separately() -> None:
    frame = event_frame(
        EMI01_GHI,
        [0, 60, 120, 180],
        [0.0, 0.0, 10.0, 20.0],
    )

    stats = characterise_tag(frame)

    assert stats["active_interval_count"] == 2
    assert stats["flat_or_night_interval_count"] == 1
    assert stats["active_interarrival_p50_s"] == 60.0
    assert stats["flat_interarrival_p50_s"] == 60.0


def test_heartbeat_accepts_stable_repeated_value_cadence() -> None:
    intervals = np.array([59.8, 60.0, 60.2] * 10 + [10.0])

    estimate = estimate_heartbeat(intervals)

    assert estimate.value_s == pytest.approx(60.0, abs=0.2)
    assert estimate.support == 30
    assert estimate.support_fraction == pytest.approx(30 / 31)
    assert estimate.confidence == "high"
    assert estimate.unresolved_reason is None


def test_heartbeat_rejects_unstable_or_sparse_evidence() -> None:
    estimate = estimate_heartbeat(np.arange(1.0, 20.0))

    assert estimate.value_s is None
    assert estimate.confidence == "unresolved"


def test_characterise_tags_counts_sibling_activity_during_max_active_gap() -> None:
    ghi = event_frame(EMI01_GHI, [0, 100], [10.0, 20.0])
    dhi = event_frame(EMI01_DHI, [20, 40, 60, 80], [2.0, 4.0, 6.0, 8.0])

    result = characterise_tags(pd.concat([ghi, dhi], ignore_index=True))

    ghi_stats = result.set_index("full_tag").loc[EMI01_GHI]
    assert ghi_stats["max_active_gap_s"] == 100.0
    assert ghi_stats["sibling_events_during_max_active_gap"] == 4


def frequency_frame(seconds_by_channel: dict[str, list[float]]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for channel, values in seconds_by_channel.items():
        for index, value in enumerate(values):
            rows.append(
                {
                    "full_tag": f"{channel}-{index}",
                    "parameter_class": ParameterClass.INSTANTANEOUS_IRRADIANCE.value,
                    "channel_group": channel,
                    "active_interarrival_p50_s": value,
                }
            )
    rows.append(
        {
            "full_tag": "accumulation-sentinel",
            "parameter_class": ParameterClass.IRRADIANCE_ACCUMULATION.value,
            "channel_group": None,
            "active_interarrival_p50_s": 10_000.0,
        }
    )
    return pd.DataFrame(rows)


def test_frequency_decision_uses_slowest_channel_median_and_ignores_accumulation() -> None:
    tag_stats = frequency_frame(
        {
            "GHI": [10.0, 20.0],
            "DHI": [20.0, 30.0],
            "DNIcosZ": [30.0, 40.0],
            "POA": [40.0, 50.0],
            "RSI": [40.0, 50.0],
        }
    )

    decision, evidence = decide_canonical_frequency(tag_stats)

    assert decision.canonical_freq == "1min"
    assert decision.decision_statistic_s == 45.0
    assert set(decision.channel_medians_s) == {
        "GHI",
        "DHI",
        "DNIcosZ",
        "POA",
        "RSI",
    }
    assert set(evidence["scope"]) == {"tag", "channel", "decision"}
    assert "accumulation-sentinel" not in set(evidence["key"])


@pytest.mark.parametrize(
    ("slowest_seconds", "expected_frequency"),
    [(61.0, "5min"), (301.0, "15min")],
)
def test_frequency_decision_coarsens_when_channel_median_requires_it(
    slowest_seconds: float,
    expected_frequency: str,
) -> None:
    frame = frequency_frame(
        {
            "GHI": [10.0],
            "DHI": [20.0],
            "DNIcosZ": [30.0],
            "POA": [40.0],
            "RSI": [slowest_seconds],
        }
    )

    decision, _ = decide_canonical_frequency(frame)

    assert decision.canonical_freq == expected_frequency


def test_frequency_is_unresolved_when_product_channel_is_missing() -> None:
    frame = frequency_frame(
        {
            "GHI": [10.0],
            "DHI": [20.0],
            "DNIcosZ": [30.0],
            "POA": [40.0],
        }
    )

    decision, _ = decide_canonical_frequency(frame)

    assert decision.canonical_freq is None
    assert decision.unresolved_reason == "missing supported channel groups: RSI"


def test_frequency_is_unresolved_above_fifteen_minutes() -> None:
    frame = frequency_frame(
        {
            "GHI": [10.0],
            "DHI": [20.0],
            "DNIcosZ": [30.0],
            "POA": [40.0],
            "RSI": [901.0],
        }
    )

    decision, _ = decide_canonical_frequency(frame)

    assert decision.canonical_freq is None
    assert "exceeds 15min" in (decision.unresolved_reason or "")
