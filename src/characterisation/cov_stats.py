"""Per-tag COV statistics and data-backed canonical-frequency selection."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .cov_contract import ParameterClass


@dataclass(frozen=True)
class DeadbandEstimate:
    """Empirical lower-edge COV deadband candidate."""

    value: float | None
    support: int
    support_fraction: float
    relative_mad: float | None
    confidence: str
    lower_anomaly_count: int
    unresolved_reason: str | None


@dataclass(frozen=True)
class HeartbeatEstimate:
    """Observed repeated-value cadence candidate."""

    value_s: float | None
    support: int
    support_fraction: float
    coefficient_of_variation: float | None
    confidence: str
    unresolved_reason: str | None


@dataclass(frozen=True)
class CanonicalFrequencyDecision:
    """Frequency selection and all decision context."""

    canonical_freq: str | None
    canonical_seconds: float | None
    decision_statistic_s: float | None
    channel_medians_s: dict[str, float]
    supported_tag_count: int
    exception_tag_count: int
    unresolved_reason: str | None


REQUIRED_CHANNEL_GROUPS = ("GHI", "DHI", "DNIcosZ", "POA", "RSI")
FREQUENCY_CANDIDATES = ((60.0, "1min"), (300.0, "5min"), (900.0, "15min"))


def _clusters(
    values: np.ndarray,
    *,
    rtol: float,
    atol: float,
) -> list[np.ndarray]:
    ordered = np.sort(np.asarray(values, dtype="float64"))
    ordered = ordered[np.isfinite(ordered)]
    if ordered.size == 0:
        return []
    groups: list[list[float]] = [[float(ordered[0])]]
    for value in ordered[1:]:
        if np.isclose(value, groups[-1][-1], rtol=rtol, atol=atol):
            groups[-1].append(float(value))
        else:
            groups.append([float(value)])
    return [np.asarray(group, dtype="float64") for group in groups]


def estimate_deadband(positive_deltas: np.ndarray) -> DeadbandEstimate:
    """Recover a supported lower-edge cluster from positive absolute deltas."""

    positive = np.asarray(positive_deltas, dtype="float64")
    positive = positive[np.isfinite(positive) & (positive > 0)]
    if positive.size < 20:
        return DeadbandEstimate(
            None,
            0,
            0.0,
            None,
            "unresolved",
            0,
            "insufficient positive deltas for a supported lower-edge cluster",
        )

    minimum_support = max(20, math.ceil(0.001 * positive.size))
    clusters = _clusters(positive, rtol=5e-4, atol=1e-6)
    lower_count = 0
    for cluster in clusters:
        if cluster.size < minimum_support:
            lower_count += int(cluster.size)
            continue
        value = float(np.median(cluster))
        mad = float(np.median(np.abs(cluster - value)))
        relative_mad = mad / value if value else math.inf
        support_fraction = float(cluster.size / positive.size)
        if support_fraction >= 0.05 and relative_mad <= 0.01:
            confidence = "high"
        elif support_fraction >= 0.01 and relative_mad <= 0.05:
            confidence = "medium"
        else:
            confidence = "low"
        return DeadbandEstimate(
            value=value,
            support=int(cluster.size),
            support_fraction=support_fraction,
            relative_mad=relative_mad,
            confidence=confidence,
            lower_anomaly_count=lower_count,
            unresolved_reason=None,
        )

    return DeadbandEstimate(
        None,
        0,
        0.0,
        None,
        "unresolved",
        lower_count,
        "insufficient supported lower-edge cluster",
    )


def estimate_heartbeat(same_value_intervals_s: np.ndarray) -> HeartbeatEstimate:
    """Find a stable, repeated cadence among same-value observations."""

    intervals = np.asarray(same_value_intervals_s, dtype="float64")
    intervals = intervals[np.isfinite(intervals) & (intervals > 0)]
    if intervals.size < 20:
        return HeartbeatEstimate(
            None,
            0,
            0.0,
            None,
            "unresolved",
            "insufficient same-value intervals",
        )

    clusters = _clusters(intervals, rtol=0.02, atol=1.0)
    candidate = max(clusters, key=lambda group: group.size)
    support = int(candidate.size)
    support_fraction = float(support / intervals.size)
    mean = float(np.mean(candidate))
    coefficient = float(np.std(candidate) / mean) if mean else math.inf
    if support < 20 or support_fraction < 0.10 or coefficient > 0.10:
        return HeartbeatEstimate(
            None,
            support,
            support_fraction,
            coefficient,
            "unresolved",
            "no stable repeated-value interval cluster",
        )

    if support_fraction >= 0.50 and coefficient <= 0.02:
        confidence = "high"
    elif support_fraction >= 0.25 and coefficient <= 0.05:
        confidence = "medium"
    else:
        confidence = "low"
    return HeartbeatEstimate(
        value_s=float(np.median(candidate)),
        support=support,
        support_fraction=support_fraction,
        coefficient_of_variation=coefficient,
        confidence=confidence,
        unresolved_reason=None,
    )


def _percentile(values: np.ndarray, quantile: float) -> float | None:
    finite = np.asarray(values, dtype="float64")
    finite = finite[np.isfinite(finite)]
    return float(np.quantile(finite, quantile)) if finite.size else None


def _distribution_fields(prefix: str, values: np.ndarray) -> dict[str, float | None]:
    finite = np.asarray(values, dtype="float64")
    finite = finite[np.isfinite(finite)]
    return {
        f"{prefix}_min": float(np.min(finite)) if finite.size else None,
        f"{prefix}_p01": _percentile(finite, 0.01),
        f"{prefix}_p05": _percentile(finite, 0.05),
        f"{prefix}_p50": _percentile(finite, 0.50),
        f"{prefix}_p90": _percentile(finite, 0.90),
        f"{prefix}_p99": _percentile(finite, 0.99),
    }


def characterise_tag(frame: pd.DataFrame) -> dict[str, Any]:
    """Calculate all COV evidence for one full tag."""

    if frame.empty:
        raise ValueError("cannot characterise an empty tag frame")
    ordered = frame.sort_values("event_time_ns", kind="stable", ignore_index=True)
    first = ordered.iloc[0]
    values = ordered["value"].to_numpy(dtype="float64")
    times_ns = ordered["event_time_ns"].to_numpy(dtype="int64")
    deltas = np.diff(values)
    absolute_deltas = np.abs(deltas)
    positive_deltas = absolute_deltas[absolute_deltas > 0]
    zero_mask = absolute_deltas == 0
    intervals_s = np.diff(times_ns).astype("float64") / 1_000_000_000.0
    valid_interval_mask = intervals_s > 0
    intervals_s = intervals_s[valid_interval_mask]
    if valid_interval_mask.size:
        zero_mask = zero_mask[valid_interval_mask]
        absolute_deltas = absolute_deltas[valid_interval_mask]
        positive_deltas = absolute_deltas[absolute_deltas > 0]

    deadband = estimate_deadband(positive_deltas)
    heartbeat = estimate_heartbeat(intervals_s[zero_mask])
    parameter_class = str(first["parameter_class"])
    instantaneous = (
        parameter_class == ParameterClass.INSTANTANEOUS_IRRADIANCE.value
    )

    active_intervals = np.asarray([], dtype="float64")
    flat_intervals = np.asarray([], dtype="float64")
    max_active_gap_start_ns: int | None = None
    max_active_gap_end_ns: int | None = None
    if instantaneous and intervals_s.size:
        threshold = max(5.0 * (deadband.value or 0.0), 5.0)
        pair_max = np.maximum(np.abs(values[:-1]), np.abs(values[1:]))
        pair_max = pair_max[valid_interval_mask]
        active_mask = pair_max > threshold
        active_intervals = intervals_s[active_mask]
        flat_intervals = intervals_s[~active_mask]
        if active_intervals.size:
            original_positions = np.flatnonzero(valid_interval_mask)
            active_positions = original_positions[active_mask]
            position = int(active_positions[np.argmax(active_intervals)])
            max_active_gap_start_ns = int(times_ns[position])
            max_active_gap_end_ns = int(times_ns[position + 1])

    result: dict[str, Any] = {
        "full_tag": str(first["full_tag"]),
        "site_label": str(first["site_label"]),
        "sts": str(first["sts"]),
        "wb": str(first["wb"]),
        "emi": str(first["emi"]),
        "raw_parameter": str(first["raw_parameter"]),
        "canonical_parameter": str(first["canonical_parameter"]),
        "parameter_class": parameter_class,
        "channel_group": (
            None if pd.isna(first["channel_group"]) else str(first["channel_group"])
        ),
        "event_count": int(len(ordered)),
        "source_zip_count": int(ordered["source_zip"].nunique()),
        "source_csv_count": int(ordered["source_csv"].nunique()),
        "coverage_start_raw": str(ordered.iloc[0]["event_time_raw"]),
        "coverage_end_raw": str(ordered.iloc[-1]["event_time_raw"]),
        "timestamp_shape": "+".join(
            sorted(ordered["timestamp_shape"].astype(str).unique())
        ),
        "zero_change_count": int(zero_mask.sum()),
        "nonzero_change_count": int((absolute_deltas > 0).sum()),
        "deadband_estimate": deadband.value,
        "deadband_support": deadband.support,
        "deadband_support_fraction": deadband.support_fraction,
        "deadband_relative_mad": deadband.relative_mad,
        "deadband_confidence": deadband.confidence,
        "deadband_lower_anomaly_count": deadband.lower_anomaly_count,
        "deadband_unresolved_reason": deadband.unresolved_reason,
        "interarrival_p50_s": _percentile(intervals_s, 0.50),
        "interarrival_p90_s": _percentile(intervals_s, 0.90),
        "interarrival_p99_s": _percentile(intervals_s, 0.99),
        "max_gap_s": float(np.max(intervals_s)) if intervals_s.size else None,
        "active_interval_count": int(active_intervals.size),
        "active_interarrival_p50_s": _percentile(active_intervals, 0.50),
        "active_interarrival_p90_s": _percentile(active_intervals, 0.90),
        "active_interarrival_p99_s": _percentile(active_intervals, 0.99),
        "max_active_gap_s": (
            float(np.max(active_intervals)) if active_intervals.size else None
        ),
        "max_active_gap_start_ns": max_active_gap_start_ns,
        "max_active_gap_end_ns": max_active_gap_end_ns,
        "flat_or_night_interval_count": int(flat_intervals.size),
        "flat_interarrival_p50_s": _percentile(flat_intervals, 0.50),
        "flat_interarrival_p90_s": _percentile(flat_intervals, 0.90),
        "flat_interarrival_p99_s": _percentile(flat_intervals, 0.99),
        "observed_heartbeat_candidate_s": heartbeat.value_s,
        "heartbeat_support": heartbeat.support,
        "heartbeat_support_fraction": heartbeat.support_fraction,
        "heartbeat_coefficient_of_variation": heartbeat.coefficient_of_variation,
        "heartbeat_confidence": heartbeat.confidence,
        "heartbeat_unresolved_reason": heartbeat.unresolved_reason,
        "configured_max_report_time_status": "unknown",
        "sibling_events_during_max_active_gap": 0,
    }
    result.update(_distribution_fields("abs_delta", positive_deltas))
    return result


def _count_sibling_events(
    events: pd.DataFrame,
    *,
    full_tag: str,
    emi: str,
    start_ns: int,
    end_ns: int,
) -> int:
    siblings = events.loc[
        (events["full_tag"].astype(str) != full_tag)
        & (events["emi"].astype(str) == emi)
        & (
            events["parameter_class"].astype(str)
            == ParameterClass.INSTANTANEOUS_IRRADIANCE.value
        ),
        "event_time_ns",
    ].to_numpy(dtype="int64", copy=True)
    siblings.sort()
    return int(
        np.searchsorted(siblings, end_ns, side="left")
        - np.searchsorted(siblings, start_ns, side="right")
    )


def characterise_tags(events: pd.DataFrame) -> pd.DataFrame:
    """Return one stable statistics row for every full tag."""

    rows = [
        characterise_tag(group)
        for _, group in events.groupby("full_tag", observed=True, sort=True)
    ]
    result = pd.DataFrame(rows).sort_values(
        ["emi", "parameter_class", "canonical_parameter", "full_tag"],
        kind="stable",
        ignore_index=True,
    )
    for index, row in result.iterrows():
        start = row["max_active_gap_start_ns"]
        end = row["max_active_gap_end_ns"]
        if pd.isna(start) or pd.isna(end):
            continue
        result.at[index, "sibling_events_during_max_active_gap"] = (
            _count_sibling_events(
                events,
                full_tag=str(row["full_tag"]),
                emi=str(row["emi"]),
                start_ns=int(start),
                end_ns=int(end),
            )
        )
    result["sibling_events_during_max_active_gap"] = result[
        "sibling_events_during_max_active_gap"
    ].astype("int64")
    return result


def decide_canonical_frequency(
    tag_stats: pd.DataFrame,
) -> tuple[CanonicalFrequencyDecision, pd.DataFrame]:
    """Select the first approved grid no finer than the slowest channel median."""

    supported = tag_stats.loc[
        (
            tag_stats["parameter_class"]
            == ParameterClass.INSTANTANEOUS_IRRADIANCE.value
        )
        & tag_stats["channel_group"].isin(REQUIRED_CHANNEL_GROUPS)
        & tag_stats["active_interarrival_p50_s"].notna()
    ].copy()
    channel_medians = {
        channel: float(
            supported.loc[
                supported["channel_group"] == channel,
                "active_interarrival_p50_s",
            ].median()
        )
        for channel in REQUIRED_CHANNEL_GROUPS
        if not supported.loc[
            supported["channel_group"] == channel,
            "active_interarrival_p50_s",
        ].empty
    }
    missing = [
        channel for channel in REQUIRED_CHANNEL_GROUPS if channel not in channel_medians
    ]
    canonical_freq: str | None = None
    canonical_seconds: float | None = None
    decision_statistic: float | None = (
        max(channel_medians.values()) if channel_medians else None
    )
    unresolved_reason: str | None = None
    if missing:
        unresolved_reason = f"missing supported channel groups: {', '.join(missing)}"
    elif decision_statistic is not None:
        for candidate_seconds, candidate_name in FREQUENCY_CANDIDATES:
            if decision_statistic <= candidate_seconds:
                canonical_seconds = candidate_seconds
                canonical_freq = candidate_name
                break
        if canonical_freq is None:
            unresolved_reason = (
                f"decision statistic {decision_statistic:g}s exceeds 15min"
            )

    exception_count = (
        int(
            (supported["active_interarrival_p50_s"] > canonical_seconds).sum()
        )
        if canonical_seconds is not None
        else 0
    )
    decision = CanonicalFrequencyDecision(
        canonical_freq=canonical_freq,
        canonical_seconds=canonical_seconds,
        decision_statistic_s=decision_statistic,
        channel_medians_s=channel_medians,
        supported_tag_count=int(len(supported)),
        exception_tag_count=exception_count,
        unresolved_reason=unresolved_reason,
    )

    evidence_rows: list[dict[str, Any]] = []
    for row in supported.sort_values("full_tag", kind="stable").itertuples(
        index=False
    ):
        evidence_rows.append(
            {
                "scope": "tag",
                "key": row.full_tag,
                "channel_group": row.channel_group,
                "active_interarrival_p50_s": row.active_interarrival_p50_s,
                "channel_median_s": channel_medians.get(row.channel_group),
                "canonical_freq": canonical_freq,
                "canonical_seconds": canonical_seconds,
                "unresolved_reason": unresolved_reason,
            }
        )
    for channel in REQUIRED_CHANNEL_GROUPS:
        if channel not in channel_medians:
            continue
        evidence_rows.append(
            {
                "scope": "channel",
                "key": channel,
                "channel_group": channel,
                "active_interarrival_p50_s": None,
                "channel_median_s": channel_medians[channel],
                "canonical_freq": canonical_freq,
                "canonical_seconds": canonical_seconds,
                "unresolved_reason": unresolved_reason,
            }
        )
    evidence_rows.append(
        {
            "scope": "decision",
            "key": "canonical_freq",
            "channel_group": None,
            "active_interarrival_p50_s": decision_statistic,
            "channel_median_s": decision_statistic,
            "canonical_freq": canonical_freq,
            "canonical_seconds": canonical_seconds,
            "unresolved_reason": unresolved_reason,
        }
    )
    evidence = pd.DataFrame(evidence_rows)
    return decision, evidence
