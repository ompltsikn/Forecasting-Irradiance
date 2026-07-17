"""DNI*cosZ derived-versus-measured diagnostics for Sprint 0."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .cov_contract import ParameterClass


REQUIRED_CHANNELS = ("GHI", "DHI", "DNIcosZ")
CLOSURE_EMIS = ("EMI01", "EMI02", "EMI03", "EMI04")


@dataclass(frozen=True)
class ResidualTolerances:
    """Numerical and sensor-resolution bounds used by the decision."""

    machine_atol_wm2: float
    quantization_atol_wm2: float
    deadband_atol_wm2: float


@dataclass(frozen=True)
class SemanticsDecision:
    """Deterministic metadata decision produced by all sensitivity cases."""

    decision: str
    is_derived_tag: bool | None
    reason: str


@dataclass(frozen=True)
class DniCoszEventAnalysis:
    """In-memory S0-3 evidence before deterministic artifact rendering."""

    decision: SemanticsDecision
    residual_summary: pd.DataFrame
    per_emi_summary: pd.DataFrame
    plot_points: pd.DataFrame
    case_decisions: dict[str, str]


def resolve_semantics(case_decisions: dict[str, str]) -> SemanticsDecision:
    """Keep metadata unresolved unless every required case agrees."""

    values = set(case_decisions.values())
    if not case_decisions:
        return SemanticsDecision(
            "unresolved",
            None,
            "no residual decision cases were available",
        )
    if values != {"derived"} and values != {"measured"}:
        return SemanticsDecision(
            "unresolved",
            None,
            "residual decision is not stable across alignment/staleness sensitivity",
        )
    decision = next(iter(values))
    return SemanticsDecision(
        decision,
        decision == "derived",
        f"all {len(case_decisions)} residual decision cases agree on {decision}",
    )


def derive_residual_tolerances(
    *,
    input_scale_wm2: float,
    channel_quantization_wm2: dict[str, float],
) -> ResidualTolerances:
    """Propagate observed channel resolution into residual tolerances."""

    missing = [
        channel for channel in REQUIRED_CHANNELS if channel not in channel_quantization_wm2
    ]
    if missing:
        raise ValueError(f"missing channel quantization: {', '.join(missing)}")
    steps = [float(channel_quantization_wm2[channel]) for channel in REQUIRED_CHANNELS]
    if any(not np.isfinite(step) or step <= 0 for step in steps):
        raise ValueError("channel quantization must contain finite positive values")
    scale = max(abs(float(input_scale_wm2)), 1.0)
    return ResidualTolerances(
        machine_atol_wm2=float(np.finfo("float64").eps * scale * 16.0),
        quantization_atol_wm2=round(sum(steps) / 2.0, 12),
        deadband_atol_wm2=round(sum(steps), 12),
    )


def quantization_from_tag_stats(
    tag_stats: pd.DataFrame,
) -> tuple[dict[str, dict[str, float]], pd.DataFrame, tuple[str, ...]]:
    """Resolve channel quantization from S0-2 evidence without guessing."""

    required_columns = {
        "emi",
        "channel_group",
        "parameter_class",
        "deadband_estimate",
        "deadband_confidence",
        "abs_delta_p01",
    }
    missing_columns = sorted(required_columns.difference(tag_stats.columns))
    if missing_columns:
        raise ValueError(
            f"tag statistics missing required columns: {', '.join(missing_columns)}"
        )
    selected = tag_stats.loc[
        (
            tag_stats["parameter_class"].astype(str)
            == ParameterClass.INSTANTANEOUS_IRRADIANCE.value
        )
        & tag_stats["emi"].isin(CLOSURE_EMIS)
        & tag_stats["channel_group"].isin(REQUIRED_CHANNELS)
    ].copy()
    mapping: dict[str, dict[str, float]] = {}
    evidence_rows: list[dict[str, object]] = []
    errors: list[str] = []
    for emi in CLOSURE_EMIS:
        emi_rows = selected.loc[selected["emi"] == emi]
        if emi_rows.empty:
            continue
        channel_steps: dict[str, float] = {}
        for channel in REQUIRED_CHANNELS:
            candidates = emi_rows.loc[emi_rows["channel_group"] == channel]
            if len(candidates) != 1:
                errors.append(
                    f"{emi}/{channel}: expected one instantaneous tag, found {len(candidates)}"
                )
                continue
            row = candidates.iloc[0]
            deadband = pd.to_numeric(
                pd.Series([row["deadband_estimate"]]), errors="coerce"
            ).iloc[0]
            p01 = pd.to_numeric(
                pd.Series([row["abs_delta_p01"]]), errors="coerce"
            ).iloc[0]
            confidence = str(row["deadband_confidence"])
            if pd.notna(deadband) and float(deadband) > 0 and confidence in {
                "high",
                "medium",
            }:
                step = float(deadband)
                source = "empirical_deadband"
            elif pd.notna(p01) and float(p01) > 0:
                step = float(p01)
                source = "abs_delta_p01_fallback"
            else:
                errors.append(
                    f"{emi}/{channel}: no positive deadband or p01 delta evidence"
                )
                continue
            channel_steps[channel] = step
            evidence_rows.append(
                {
                    "emi": emi,
                    "channel_group": channel,
                    "quantization_step_wm2": step,
                    "quantization_source": source,
                    "deadband_confidence": confidence,
                }
            )
        if set(channel_steps) == set(REQUIRED_CHANNELS):
            mapping[emi] = channel_steps
    return mapping, pd.DataFrame(evidence_rows), tuple(errors)


def classify_residuals(
    residuals: pd.Series,
    tolerance: ResidualTolerances,
    *,
    minimum_samples: int = 20,
) -> str:
    """Classify one residual case without inventing a convenient W/m2 bound."""

    finite = pd.to_numeric(residuals, errors="coerce").dropna().to_numpy(
        dtype="float64"
    )
    if finite.size < minimum_samples:
        return "unresolved"
    absolute = np.abs(finite)
    if float(np.max(absolute)) <= tolerance.quantization_atol_wm2:
        return "derived"
    if (
        float(np.median(absolute)) > tolerance.deadband_atol_wm2
        or (
            float(np.quantile(absolute, 0.95)) > tolerance.deadband_atol_wm2
            and float(np.std(finite)) > tolerance.deadband_atol_wm2
        )
    ):
        return "measured"
    return "unresolved"


def summarise_residuals(
    residuals: pd.Series,
    tolerance: ResidualTolerances,
) -> dict[str, float | int | None]:
    """Return the distribution and tolerance evidence required by S0-3."""

    finite = pd.to_numeric(residuals, errors="coerce").dropna().to_numpy(
        dtype="float64"
    )
    if finite.size == 0:
        return {
            "sample_count": 0,
            "mean_wm2": None,
            "median_wm2": None,
            "std_wm2": None,
            "mae_wm2": None,
            "rmse_wm2": None,
            "p01_wm2": None,
            "p05_wm2": None,
            "p50_wm2": None,
            "p95_wm2": None,
            "p99_wm2": None,
            "max_abs_wm2": None,
            "proportion_below_machine": None,
            "proportion_below_quantization": None,
            "proportion_below_deadband": None,
        }
    absolute = np.abs(finite)
    return {
        "sample_count": int(finite.size),
        "mean_wm2": float(np.mean(finite)),
        "median_wm2": float(np.median(finite)),
        "std_wm2": float(np.std(finite)),
        "mae_wm2": float(np.mean(absolute)),
        "rmse_wm2": float(np.sqrt(np.mean(np.square(finite)))),
        "p01_wm2": float(np.quantile(finite, 0.01)),
        "p05_wm2": float(np.quantile(finite, 0.05)),
        "p50_wm2": float(np.quantile(finite, 0.50)),
        "p95_wm2": float(np.quantile(finite, 0.95)),
        "p99_wm2": float(np.quantile(finite, 0.99)),
        "max_abs_wm2": float(np.max(absolute)),
        "proportion_below_machine": float(
            np.mean(absolute <= tolerance.machine_atol_wm2)
        ),
        "proportion_below_quantization": float(
            np.mean(absolute <= tolerance.quantization_atol_wm2)
        ),
        "proportion_below_deadband": float(
            np.mean(absolute <= tolerance.deadband_atol_wm2)
        ),
    }


def _approximate_solar_zenith_utc(
    times_utc: pd.DatetimeIndex,
    *,
    latitude_deg: float,
    longitude_deg: float,
) -> np.ndarray:
    """NOAA fractional-year approximation, sufficient for a provisional plot."""

    day = times_utc.dayofyear.to_numpy(dtype="float64")
    hour = (
        times_utc.hour.to_numpy(dtype="float64")
        + times_utc.minute.to_numpy(dtype="float64") / 60.0
        + times_utc.second.to_numpy(dtype="float64") / 3600.0
        + times_utc.microsecond.to_numpy(dtype="float64") / 3_600_000_000.0
    )
    gamma = 2.0 * np.pi / 365.0 * (day - 1.0 + (hour - 12.0) / 24.0)
    equation_of_time_min = 229.18 * (
        0.000075
        + 0.001868 * np.cos(gamma)
        - 0.032077 * np.sin(gamma)
        - 0.014615 * np.cos(2.0 * gamma)
        - 0.040849 * np.sin(2.0 * gamma)
    )
    declination = (
        0.006918
        - 0.399912 * np.cos(gamma)
        + 0.070257 * np.sin(gamma)
        - 0.006758 * np.cos(2.0 * gamma)
        + 0.000907 * np.sin(2.0 * gamma)
        - 0.002697 * np.cos(3.0 * gamma)
        + 0.00148 * np.sin(3.0 * gamma)
    )
    true_solar_minutes = (
        hour * 60.0 + equation_of_time_min + 4.0 * float(longitude_deg)
    ) % 1440.0
    hour_angle_deg = np.where(
        true_solar_minutes / 4.0 < 0.0,
        true_solar_minutes / 4.0 + 180.0,
        true_solar_minutes / 4.0 - 180.0,
    )
    latitude = np.deg2rad(float(latitude_deg))
    hour_angle = np.deg2rad(hour_angle_deg)
    cosine = (
        np.sin(latitude) * np.sin(declination)
        + np.cos(latitude) * np.cos(declination) * np.cos(hour_angle)
    )
    return np.rad2deg(np.arccos(np.clip(cosine, -1.0, 1.0)))


def solar_zenith_sensitivity(
    naive_times: pd.Series,
    *,
    latitude_deg: float,
    longitude_deg: float,
    local_timezone: str,
) -> pd.DataFrame:
    """Compare provisional naive-local and alternative naive-UTC zenith."""

    parsed = pd.DatetimeIndex(pd.to_datetime(naive_times, errors="raise"))
    if parsed.tz is not None:
        raise ValueError("zenith sensitivity expects naive historian timestamps")
    assuming_local = parsed.tz_localize(
        local_timezone,
        ambiguous="raise",
        nonexistent="raise",
    ).tz_convert("UTC")
    assuming_utc = parsed.tz_localize("UTC")
    return pd.DataFrame(
        {
            "zenith_assuming_naive_wita_deg": _approximate_solar_zenith_utc(
                assuming_local,
                latitude_deg=latitude_deg,
                longitude_deg=longitude_deg,
            ),
            "zenith_assuming_naive_utc_deg": _approximate_solar_zenith_utc(
                assuming_utc,
                latitude_deg=latitude_deg,
                longitude_deg=longitude_deg,
            ),
            "zenith_interpretation_status": "provisional",
        }
    )


def _decorate_residual_frame(
    frame: pd.DataFrame,
    *,
    time_column: str,
    tolerance: ResidualTolerances,
    latitude_deg: float,
    longitude_deg: float,
    local_timezone: str,
) -> pd.DataFrame:
    decorated = frame.copy().reset_index(drop=True)
    zenith = solar_zenith_sensitivity(
        decorated[time_column],
        latitude_deg=latitude_deg,
        longitude_deg=longitude_deg,
        local_timezone=local_timezone,
    )
    decorated = pd.concat([decorated, zenith], axis=1)
    decorated["active_components"] = (
        decorated["DHI"] + decorated["DNIcosZ"] > 50.0
    )
    decorated["night_flat"] = ~decorated["active_components"]
    decorated["daylight_provisional"] = (
        decorated["zenith_assuming_naive_wita_deg"] < 93.0
    )
    absolute = decorated["residual_wm2"].abs()
    decorated["below_machine"] = absolute <= tolerance.machine_atol_wm2
    decorated["below_quantization"] = (
        absolute <= tolerance.quantization_atol_wm2
    )
    decorated["below_deadband"] = absolute <= tolerance.deadband_atol_wm2
    return decorated


def _population_frames(frame: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {
        "all": frame,
        "active_components": frame.loc[frame["active_components"]],
        "night_flat": frame.loc[frame["night_flat"]],
        "daylight_provisional": frame.loc[frame["daylight_provisional"]],
    }


def analyse_dni_cosz_events(
    events: pd.DataFrame,
    *,
    quantization_by_emi: dict[str, dict[str, float]],
    frequency: str,
    staleness_windows_s: tuple[float, ...],
    latitude_deg: float,
    longitude_deg: float,
    local_timezone: str,
    source_scope: str,
    minimum_samples: int = 20,
) -> DniCoszEventAnalysis:
    """Analyse direct and backward-aligned residuals per complete EMI."""

    selected = _instantaneous_closure_events(events)
    eligible_emis = [
        str(emi)
        for emi, group in selected.groupby("emi", sort=True, observed=True)
        if set(group["channel_group"].astype(str)) == set(REQUIRED_CHANNELS)
    ]
    direct = coincident_residuals(events)
    summary_rows: list[dict[str, object]] = []
    emi_rows: list[dict[str, object]] = []
    plot_frames: list[pd.DataFrame] = []
    all_case_decisions: dict[str, str] = {}
    combined_case_frames: dict[tuple[str, float | None], list[pd.DataFrame]] = {}

    for emi in eligible_emis:
        emi_events = selected.loc[selected["emi"].astype(str) == emi].copy()
        channel_counts = {
            channel: int((emi_events["channel_group"] == channel).sum())
            for channel in REQUIRED_CHANNELS
        }
        channel_coverage_start = {
            channel: emi_events.loc[
                emi_events["channel_group"] == channel, "event_time"
            ].min()
            for channel in REQUIRED_CHANNELS
        }
        channel_coverage_end = {
            channel: emi_events.loc[
                emi_events["channel_group"] == channel, "event_time"
            ].max()
            for channel in REQUIRED_CHANNELS
        }
        quantization = quantization_by_emi.get(emi)
        if quantization is None:
            emi_rows.append(
                {
                    "source_scope": source_scope,
                    "emi": emi,
                    **{f"event_count_{key}": value for key, value in channel_counts.items()},
                    "coverage_start": min(channel_coverage_start.values()),
                    "coverage_end": max(channel_coverage_end.values()),
                    "exact_coincident_count": int((direct["emi"] == emi).sum()),
                    "decision": "unresolved",
                    "is_derived_tag": None,
                    "reason": "quantization evidence is unavailable",
                }
            )
            all_case_decisions[f"{source_scope}:{emi}:quantization"] = "unresolved"
            continue
        input_scale = float(emi_events["value"].abs().max())
        tolerance = derive_residual_tolerances(
            input_scale_wm2=input_scale,
            channel_quantization_wm2=quantization,
        )
        emi_case_decisions: dict[str, str] = {}

        direct_emi = direct.loc[direct["emi"].astype(str) == emi].copy()
        if not direct_emi.empty:
            decorated_direct = _decorate_residual_frame(
                direct_emi,
                time_column="event_time",
                tolerance=tolerance,
                latitude_deg=latitude_deg,
                longitude_deg=longitude_deg,
                local_timezone=local_timezone,
            )
            combined_case_frames.setdefault(("direct_coincident", None), []).append(
                decorated_direct
            )
            for population, population_frame in _population_frames(
                decorated_direct
            ).items():
                classification = classify_residuals(
                    population_frame["residual_wm2"],
                    tolerance,
                    minimum_samples=minimum_samples,
                )
                summary_rows.append(
                    {
                        "source_scope": source_scope,
                        "emi": emi,
                        "method": "direct_coincident",
                        "frequency": None,
                        "staleness_s": None,
                        "population": population,
                        "classification": classification,
                        "machine_atol_wm2": tolerance.machine_atol_wm2,
                        "quantization_atol_wm2": tolerance.quantization_atol_wm2,
                        "deadband_atol_wm2": tolerance.deadband_atol_wm2,
                        **summarise_residuals(
                            population_frame["residual_wm2"], tolerance
                        ),
                    }
                )
                if population == "active_components":
                    emi_case_decisions["direct_coincident"] = classification
        else:
            emi_case_decisions["direct_coincident"] = "unresolved"

        aligned_counts: dict[float, int] = {}
        for staleness_s in staleness_windows_s:
            aligned_all = align_cov_backward(
                emi_events,
                frequency=frequency,
                staleness_s=staleness_s,
            )
            aligned = aligned_all.loc[aligned_all["emi"].astype(str) == emi].copy()
            aligned_counts[float(staleness_s)] = int(len(aligned))
            if aligned.empty:
                emi_case_decisions[f"aligned_{staleness_s:g}s"] = "unresolved"
                continue
            decorated_aligned = _decorate_residual_frame(
                aligned,
                time_column="grid_time",
                tolerance=tolerance,
                latitude_deg=latitude_deg,
                longitude_deg=longitude_deg,
                local_timezone=local_timezone,
            )
            decorated_aligned["source_scope"] = source_scope
            decorated_aligned["staleness_s"] = float(staleness_s)
            combined_case_frames.setdefault(
                ("aligned_backward", float(staleness_s)), []
            ).append(decorated_aligned)
            if staleness_s == max(staleness_windows_s):
                plot_frames.append(decorated_aligned)
            for population, population_frame in _population_frames(
                decorated_aligned
            ).items():
                classification = classify_residuals(
                    population_frame["residual_wm2"],
                    tolerance,
                    minimum_samples=minimum_samples,
                )
                summary_rows.append(
                    {
                        "source_scope": source_scope,
                        "emi": emi,
                        "method": "aligned_backward",
                        "frequency": frequency,
                        "staleness_s": float(staleness_s),
                        "population": population,
                        "classification": classification,
                        "machine_atol_wm2": tolerance.machine_atol_wm2,
                        "quantization_atol_wm2": tolerance.quantization_atol_wm2,
                        "deadband_atol_wm2": tolerance.deadband_atol_wm2,
                        **summarise_residuals(
                            population_frame["residual_wm2"], tolerance
                        ),
                    }
                )
                if population == "active_components":
                    emi_case_decisions[f"aligned_{staleness_s:g}s"] = classification

        emi_decision = resolve_semantics(emi_case_decisions)
        all_case_decisions.update(
            {
                f"{source_scope}:{emi}:{key}": value
                for key, value in emi_case_decisions.items()
            }
        )
        emi_rows.append(
            {
                "source_scope": source_scope,
                "emi": emi,
                **{f"event_count_{key}": value for key, value in channel_counts.items()},
                **{
                    f"coverage_start_{key}": channel_coverage_start[key]
                    for key in REQUIRED_CHANNELS
                },
                **{
                    f"coverage_end_{key}": channel_coverage_end[key]
                    for key in REQUIRED_CHANNELS
                },
                "coverage_start": min(channel_coverage_start.values()),
                "coverage_end": max(channel_coverage_end.values()),
                "exact_coincident_count": int(len(direct_emi)),
                **{
                    f"aligned_count_{staleness:g}s": count
                    for staleness, count in aligned_counts.items()
                },
                "decision": emi_decision.decision,
                "is_derived_tag": emi_decision.is_derived_tag,
                "reason": emi_decision.reason,
            }
        )

    for (method, staleness_s), frames in sorted(
        combined_case_frames.items(),
        key=lambda item: (item[0][0], -1.0 if item[0][1] is None else item[0][1]),
    ):
        combined = pd.concat(frames, ignore_index=True)
        for population, population_frame in _population_frames(combined).items():
            matching_classifications = {
                str(row["classification"])
                for row in summary_rows
                if row["method"] == method
                and row["staleness_s"] == staleness_s
                and row["population"] == population
            }
            classification = (
                next(iter(matching_classifications))
                if len(matching_classifications) == 1
                else "unresolved"
            )
            statistics = summarise_residuals(
                population_frame["residual_wm2"],
                ResidualTolerances(0.0, 0.0, 0.0),
            )
            if not population_frame.empty:
                statistics["proportion_below_machine"] = float(
                    population_frame["below_machine"].mean()
                )
                statistics["proportion_below_quantization"] = float(
                    population_frame["below_quantization"].mean()
                )
                statistics["proportion_below_deadband"] = float(
                    population_frame["below_deadband"].mean()
                )
            summary_rows.append(
                {
                    "source_scope": source_scope,
                    "emi": "ALL",
                    "method": method,
                    "frequency": frequency if method == "aligned_backward" else None,
                    "staleness_s": staleness_s,
                    "population": population,
                    "classification": classification,
                    "machine_atol_wm2": None,
                    "quantization_atol_wm2": None,
                    "deadband_atol_wm2": None,
                    **statistics,
                }
            )

    decision = resolve_semantics(all_case_decisions)
    return DniCoszEventAnalysis(
        decision=decision,
        residual_summary=pd.DataFrame(summary_rows),
        per_emi_summary=pd.DataFrame(emi_rows),
        plot_points=(
            pd.concat(plot_frames, ignore_index=True)
            if plot_frames
            else pd.DataFrame()
        ),
        case_decisions=all_case_decisions,
    )


def _instantaneous_closure_events(events: pd.DataFrame) -> pd.DataFrame:
    selected = events.loc[
        (
            events["parameter_class"].astype(str)
            == ParameterClass.INSTANTANEOUS_IRRADIANCE.value
        )
        & events["channel_group"].isin(REQUIRED_CHANNELS),
        ["emi", "event_time", "channel_group", "parameter_class", "value"],
    ].copy()
    identity = ["emi", "event_time", "channel_group"]
    duplicate_keys = selected.loc[
        selected.duplicated(identity, keep=False),
        [*identity, "value"],
    ]
    if not duplicate_keys.empty:
        conflicting = (
            duplicate_keys.groupby(identity, observed=True, sort=False)["value"]
            .nunique(dropna=False)
            .gt(1)
        )
        if conflicting.any():
            examples = conflicting.loc[conflicting].index.tolist()[:3]
            raise ValueError(
                "conflicting values for duplicate EMI/timestamp/channel keys: "
                f"{examples}"
            )
    return selected.sort_values(
        ["emi", "event_time", "channel_group", "value"],
        kind="stable",
        ignore_index=True,
    ).drop_duplicates(
        ["emi", "event_time", "channel_group", "value"],
        keep="first",
        ignore_index=True,
    )


def coincident_residuals(events: pd.DataFrame) -> pd.DataFrame:
    """Return closure residuals only where all three raw channels coincide."""

    required = {
        "emi",
        "channel_group",
        "parameter_class",
        "event_time",
        "value",
    }
    missing = sorted(required.difference(events.columns))
    if missing:
        raise ValueError(f"events missing required columns: {', '.join(missing)}")

    selected = _instantaneous_closure_events(events)
    if selected.empty:
        return pd.DataFrame(
            columns=[
                "emi",
                "event_time",
                *REQUIRED_CHANNELS,
                "residual_wm2",
            ]
        )

    wide = selected.pivot(
        index=["emi", "event_time"],
        columns="channel_group",
        values="value",
    ).reset_index()
    complete = wide.dropna(subset=list(REQUIRED_CHANNELS)).copy()
    complete["residual_wm2"] = (
        complete["GHI"] - complete["DHI"] - complete["DNIcosZ"]
    )
    return complete[
        ["emi", "event_time", *REQUIRED_CHANNELS, "residual_wm2"]
    ].sort_values(["emi", "event_time"], kind="stable", ignore_index=True)


def align_cov_backward(
    events: pd.DataFrame,
    *,
    frequency: str,
    staleness_s: float,
) -> pd.DataFrame:
    """Reconstruct a diagnostic grid with backward-only COV as-of joins."""

    if staleness_s < 0:
        raise ValueError("staleness_s must be non-negative")
    selected = _instantaneous_closure_events(events)
    rows: list[pd.DataFrame] = []
    for emi, emi_events in selected.groupby("emi", sort=True, observed=True):
        channels = {
            channel: emi_events.loc[
                emi_events["channel_group"] == channel,
                ["event_time", "value"],
            ]
            .sort_values("event_time", kind="stable")
            .drop_duplicates("event_time", keep="last")
            for channel in REQUIRED_CHANNELS
        }
        if any(frame.empty for frame in channels.values()):
            continue
        coverage_start = max(frame["event_time"].min() for frame in channels.values())
        coverage_end = min(frame["event_time"].max() for frame in channels.values())
        grid_start = pd.Timestamp(coverage_start).ceil(frequency)
        grid_end = pd.Timestamp(coverage_end).floor(frequency)
        if grid_start > grid_end:
            continue
        aligned = pd.DataFrame(
            {"grid_time": pd.date_range(grid_start, grid_end, freq=frequency)}
        )
        aligned.insert(0, "emi", str(emi))
        for channel, channel_events in channels.items():
            source_column = f"{channel}_source_time"
            right = channel_events.rename(
                columns={"event_time": source_column, "value": channel}
            )
            aligned = pd.merge_asof(
                aligned.sort_values("grid_time"),
                right.sort_values(source_column),
                left_on="grid_time",
                right_on=source_column,
                direction="backward",
                allow_exact_matches=True,
            )
            aligned[f"{channel}_age_s"] = (
                aligned["grid_time"] - aligned[source_column]
            ).dt.total_seconds()
        age_columns = [f"{channel}_age_s" for channel in REQUIRED_CHANNELS]
        valid = aligned[list(REQUIRED_CHANNELS)].notna().all(axis=1)
        valid &= aligned[age_columns].ge(0).all(axis=1)
        valid &= aligned[age_columns].le(float(staleness_s)).all(axis=1)
        aligned = aligned.loc[valid].copy()
        aligned["residual_wm2"] = (
            aligned["GHI"] - aligned["DHI"] - aligned["DNIcosZ"]
        )
        rows.append(aligned)

    if not rows:
        columns = ["emi", "grid_time", *REQUIRED_CHANNELS]
        for channel in REQUIRED_CHANNELS:
            columns.extend([f"{channel}_source_time", f"{channel}_age_s"])
        columns.append("residual_wm2")
        return pd.DataFrame(columns=columns)
    return pd.concat(rows, ignore_index=True).sort_values(
        ["emi", "grid_time"], kind="stable", ignore_index=True
    )
