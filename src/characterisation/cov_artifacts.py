"""Deterministic evidence artifacts for Sprint 0 COV characterisation."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .cov_ingest import IngestionResult, ReconciliationResult
from .cov_stats import CanonicalFrequencyDecision, REQUIRED_CHANNEL_GROUPS


@dataclass(frozen=True)
class CovArtifactBundle:
    """Every measured table needed to render one internally consistent run."""

    ingestion: IngestionResult
    reconciliation: ReconciliationResult
    tag_stats: pd.DataFrame
    decision: CanonicalFrequencyDecision
    frequency_evidence: pd.DataFrame
    strict_errors: tuple[str, ...]
    report_path: Path | None = None


@dataclass(frozen=True)
class CovArtifactResult:
    """Paths and checksums returned to CLI and notebook callers."""

    manifest_path: Path
    manifest_sha256: str
    report_path: Path
    artifact_paths: dict[str, Path]


TABLE_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("source_manifest.csv", "source_manifest", ("zip_name",)),
    (
        "inventory_reconciliation.csv",
        "inventory_reconciliation",
        ("zip_name",),
    ),
    (
        "empty_csv_entries.csv",
        "empty_csv_entries",
        ("source_zip", "source_csv"),
    ),
    (
        "row_exceptions.csv",
        "row_exceptions",
        ("source_zip", "source_csv", "source_row", "reason"),
    ),
    (
        "timestamp_audit.csv",
        "timestamp_audit",
        ("source_zip", "source_csv", "full_tag"),
    ),
    ("tag_characterisation.csv", "tag_stats", ("full_tag",)),
    (
        "canonical_frequency_evidence.csv",
        "frequency_evidence",
        ("scope", "key"),
    ),
)

FIGURE_NAMES = (
    "figures/deadband_instantaneous.png",
    "figures/interarrival_instantaneous.png",
    "figures/canonical_frequency_evidence.png",
    "figures/timestamp_daylight_alignment.png",
    "figures/gap_heartbeat_evidence.png",
)

_COLORS = {
    "GHI": "#0072B2",
    "DHI": "#E69F00",
    "DNIcosZ": "#009E73",
    "POA": "#CC79A7",
    "RSI": "#D55E00",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _stable_table(frame: pd.DataFrame, keys: Iterable[str]) -> pd.DataFrame:
    result = frame.copy()
    available = [key for key in keys if key in result.columns]
    if available and not result.empty:
        result = result.sort_values(available, kind="stable", na_position="last")
    return result.reset_index(drop=True)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        path,
        index=False,
        encoding="utf-8",
        lineterminator="\n",
        float_format="%.9g",
    )


def _write_json(value: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def _new_figure(title: str, *, width: float = 9.0, height: float = 5.0):
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.alpha": 0.25,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
        }
    )
    figure, axis = plt.subplots(figsize=(width, height), constrained_layout=False)
    axis.set_title(title)
    return figure, axis


def _save_figure(figure, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        path,
        dpi=140,
        bbox_inches="tight",
        metadata={"Software": "Forecasting-Irradiance"},
    )
    plt.close(figure)


def _annotate_empty(axis, message: str = "insufficient evidence") -> None:
    axis.text(
        0.5,
        0.5,
        message,
        transform=axis.transAxes,
        ha="center",
        va="center",
        color="#555555",
    )
    axis.set_xticks([])
    axis.set_yticks([])


def _instantaneous(tag_stats: pd.DataFrame) -> pd.DataFrame:
    if "parameter_class" not in tag_stats:
        return tag_stats.iloc[0:0].copy()
    return tag_stats.loc[
        tag_stats["parameter_class"] == "instantaneous_irradiance"
    ].copy()


def _plot_deadband(tag_stats: pd.DataFrame, path: Path) -> None:
    figure, axis = _new_figure("Empirical COV floor — instantaneous irradiance")
    data = _instantaneous(tag_stats)
    if "deadband_estimate" in data:
        data = data.loc[data["deadband_estimate"].notna()].copy()
    else:
        data = data.iloc[0:0]
    if data.empty:
        _annotate_empty(axis)
    else:
        data = _stable_table(data, ("channel_group", "full_tag"))
        for channel, group in data.groupby("channel_group", dropna=False, sort=True):
            positions = group.index.to_numpy(dtype="float64")
            axis.scatter(
                positions,
                group["deadband_estimate"].to_numpy(dtype="float64"),
                label=str(channel),
                color=_COLORS.get(str(channel), "#666666"),
                s=28,
            )
        axis.set_xlabel("Supported tag (stable order)")
        axis.set_ylabel("Deadband candidate / |delta value|")
        axis.legend(loc="best", ncol=3)
    _save_figure(figure, path)


def _plot_interarrival(tag_stats: pd.DataFrame, path: Path) -> None:
    figure, axis = _new_figure(
        "Inter-arrival p50 — all, active, and flat/night intervals"
    )
    data = _stable_table(_instantaneous(tag_stats), ("full_tag",))
    metrics = (
        ("interarrival_p50_s", "all", "#333333", "o"),
        ("active_interarrival_p50_s", "active", "#0072B2", "^"),
        ("flat_interarrival_p50_s", "flat/night", "#E69F00", "s"),
    )
    plotted = False
    for column, label, color, marker in metrics:
        if column not in data:
            continue
        values = pd.to_numeric(data[column], errors="coerce")
        mask = values.notna()
        if not mask.any():
            continue
        plotted = True
        axis.scatter(
            np.flatnonzero(mask.to_numpy()),
            values.loc[mask],
            label=label,
            color=color,
            marker=marker,
            s=24,
        )
    if not plotted:
        _annotate_empty(axis)
    else:
        axis.set_yscale("log")
        axis.set_xlabel("Instantaneous tag (stable order)")
        axis.set_ylabel("Seconds (log scale)")
        axis.legend(loc="best")
    _save_figure(figure, path)


def _plot_frequency(
    decision: CanonicalFrequencyDecision,
    path: Path,
) -> None:
    figure, axis = _new_figure("Canonical-frequency evidence by channel")
    channels = [
        channel
        for channel in REQUIRED_CHANNEL_GROUPS
        if channel in decision.channel_medians_s
    ]
    if not channels:
        _annotate_empty(axis)
    else:
        values = [decision.channel_medians_s[channel] for channel in channels]
        axis.bar(
            channels,
            values,
            color=[_COLORS.get(channel, "#666666") for channel in channels],
        )
        for seconds, label in ((60, "1min"), (300, "5min"), (900, "15min")):
            axis.axhline(seconds, color="#555555", linewidth=0.8, linestyle="--")
            axis.text(len(channels) - 0.48, seconds, label, va="bottom", ha="right")
        axis.set_yscale("log")
        axis.set_ylabel("Median active p50 (seconds, log scale)")
        subtitle = (
            f"selected: {decision.canonical_freq}"
            if decision.canonical_freq
            else f"unresolved: {decision.unresolved_reason}"
        )
        axis.set_xlabel(subtitle)
    _save_figure(figure, path)


def _plot_daylight(events: pd.DataFrame, path: Path) -> None:
    figure, axis = _new_figure("Irradiance activity by as-recorded clock hour")
    required = {"parameter_class", "event_time", "value"}
    if not required.issubset(events.columns):
        _annotate_empty(axis)
        _save_figure(figure, path)
        return
    data = events.loc[
        (events["parameter_class"] == "instantaneous_irradiance")
        & (pd.to_numeric(events["value"], errors="coerce").abs() > 5.0),
        ["event_time", "value"],
    ].copy()
    if data.empty:
        _annotate_empty(axis)
    else:
        data["hour"] = pd.to_datetime(data["event_time"]).dt.hour
        hourly = data.groupby("hour", sort=True).size().reindex(range(24), fill_value=0)
        axis.bar(hourly.index, hourly.values, color="#0072B2")
        axis.set_xticks(range(0, 24, 2))
        axis.set_xlabel("Hour as recorded (no timezone conversion applied)")
        axis.set_ylabel("Events with |value| > 5")
        axis.text(
            0.01,
            0.98,
            "Daylight alignment is consistency evidence, not historian clock proof.",
            transform=axis.transAxes,
            va="top",
            fontsize=8,
        )
    _save_figure(figure, path)


def _plot_gap_heartbeat(tag_stats: pd.DataFrame, path: Path) -> None:
    figure, axis = _new_figure("Maximum active gaps and heartbeat evidence")
    data = _stable_table(_instantaneous(tag_stats), ("full_tag",))
    plotted = False
    if "max_active_gap_s" in data:
        gaps = pd.to_numeric(data["max_active_gap_s"], errors="coerce")
        mask = gaps.notna()
        if mask.any():
            plotted = True
            axis.scatter(
                np.flatnonzero(mask.to_numpy()),
                gaps.loc[mask],
                color="#D55E00",
                marker="o",
                label="max active gap",
            )
    if "observed_heartbeat_candidate_s" in data:
        heartbeat = pd.to_numeric(
            data["observed_heartbeat_candidate_s"], errors="coerce"
        )
        mask = heartbeat.notna()
        if mask.any():
            plotted = True
            axis.scatter(
                np.flatnonzero(mask.to_numpy()),
                heartbeat.loc[mask],
                color="#009E73",
                marker="x",
                label="observed heartbeat candidate",
            )
    if not plotted:
        _annotate_empty(axis)
    else:
        axis.set_yscale("log")
        axis.set_xlabel("Instantaneous tag (stable order)")
        axis.set_ylabel("Seconds (log scale)")
        axis.legend(loc="best")
    _save_figure(figure, path)


def _markdown_value(value: Any) -> str:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "—"
    if isinstance(value, float):
        return f"{value:.9g}"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _markdown_table(frame: pd.DataFrame, columns: list[str]) -> str:
    selected = [column for column in columns if column in frame.columns]
    if not selected:
        return "_No applicable fields._"
    lines = [
        "| " + " | ".join(selected) + " |",
        "|" + "|".join("---" for _ in selected) + "|",
    ]
    for row in frame[selected].itertuples(index=False, name=None):
        lines.append("| " + " | ".join(_markdown_value(value) for value in row) + " |")
    return "\n".join(lines)


def _render_report(bundle: CovArtifactBundle) -> str:
    source = _stable_table(bundle.ingestion.source_manifest, ("zip_name",))
    reconciliation = _stable_table(bundle.reconciliation.table, ("zip_name",))
    tags = _stable_table(bundle.tag_stats, ("full_tag",))
    timestamp = _stable_table(
        bundle.ingestion.timestamp_audit,
        ("source_zip", "source_csv", "full_tag"),
    )
    class_counts = (
        tags["parameter_class"].value_counts().sort_index().to_dict()
        if "parameter_class" in tags
        else {}
    )
    timestamp_shapes = (
        sorted(timestamp["timestamp_shape"].dropna().astype(str).unique())
        if "timestamp_shape" in timestamp
        else []
    )
    matched = (
        int((reconciliation["match_status"] == "matched").sum())
        if "match_status" in reconciliation
        else 0
    )
    heartbeat_supported = (
        int(tags["observed_heartbeat_candidate_s"].notna().sum())
        if "observed_heartbeat_candidate_s" in tags
        else 0
    )
    decision_text = bundle.decision.canonical_freq or "unresolved"
    blockers = []
    if bundle.strict_errors:
        blockers.append("strict source-integrity errors remain")
    if bundle.decision.unresolved_reason:
        blockers.append(bundle.decision.unresolved_reason)
    if "configured_max_report_time_status" in tags and (
        tags["configured_max_report_time_status"].astype(str) == "unknown"
    ).any():
        blockers.append("configured historian max-report-time is not confirmed")
    if "naive" in timestamp_shapes:
        blockers.append("historian timestamp timezone is not independently confirmed")
    acceptance = "YELLOW" if blockers else "COMPLETE"

    channel_rows = pd.DataFrame(
        [
            {
                "channel_group": channel,
                "median_active_p50_s": bundle.decision.channel_medians_s.get(channel),
            }
            for channel in REQUIRED_CHANNEL_GROUPS
        ]
    )
    appendix_columns = [
        "full_tag",
        "emi",
        "canonical_parameter",
        "parameter_class",
        "event_count_before_integrity",
        "event_count",
        "deadband_estimate",
        "deadband_confidence",
        "interarrival_p50_s",
        "interarrival_p90_s",
        "interarrival_p99_s",
        "max_gap_s",
        "observed_heartbeat_candidate_s",
        "heartbeat_confidence",
    ]
    blocker_text = "\n".join(f"- {item}" for item in blockers) or "- None"
    strict_text = "passed" if not bundle.strict_errors else "failed"
    return f"""# S0-2 COV Characterisation

This report is generated from the same measured tables and code used by the CLI and Colab runner. It characterises change-of-value reporting only; it builds no forecasting model or baseline.

## Executive decision

- S0-2 acceptance status: **{acceptance}**
- Source-integrity strict status: **{strict_text}**
- Data-backed `canonical_freq`: **{decision_text}**
- Decision statistic (slowest five-channel median active p50): **{_markdown_value(bundle.decision.decision_statistic_s)} seconds**
- Supported instantaneous tags in the decision: **{bundle.decision.supported_tag_count}**
- Supported tags slower than the selected grid: **{bundle.decision.exception_tag_count}**

Remaining acceptance blockers:

{blocker_text}

Gate M0 and Phase 1 are separate decisions. This report does not authorize modelling.

## Source reconciliation and integrity

- Local ZIP files: **{len(source)}**
- ZIPs matched to the reference inventory: **{matched}**
- CSV entries: **{int(source['csv_entry_count'].sum()) if 'csv_entry_count' in source else 0}**
- Populated CSV entries: **{int(source['populated_csv_count'].sum()) if 'populated_csv_count' in source else 0}**
- Empty CSV entries: **{len(bundle.ingestion.empty_entries)}**
- Events after integrity handling: **{len(bundle.ingestion.events)}**
- Exact duplicates removed: **{bundle.ingestion.exact_duplicate_count}**
- Conflicting tag/timestamps quarantined: **{bundle.ingestion.timestamp_conflict_count}**
- Strict errors: **{len(bundle.strict_errors)}**

The Drive connector reconciliation proves filename and byte-size equality. Content equality is established when the notebook copies mounted Drive files to VM-local storage and verifies SHA-256.

## Actual CSV schema correction

The second CSV **header name** is the full SCADA tag. The second field in each data row is the numeric observation. The third field is preserved as `object_caeid_raw`; no quality semantics are assigned without a source-system record. ZIP and CSV filenames are never used to infer the parameter.

## Timestamp semantics

Observed timestamp shapes: **{', '.join(timestamp_shapes) if timestamp_shapes else 'none'}**.

Naive timestamps are preserved as recorded. No UTC conversion is applied. Hour-of-day irradiance activity is used only to assess consistency with the site clock (Asia/Makassar/WITA); it does not substitute for historian clock/configuration evidence.

## Methods

All tags retain source provenance. Exact duplicates are removed before statistics and conflicting tag/timestamps are quarantined. Deadband is the first supported lower-edge cluster of positive `|delta value|` using `isclose(rtol=5e-4, atol=1e-6)`. Active instantaneous intervals use `max(5 * deadband, 5 W/m2)`; lower intervals are labelled `flat_or_night`, not automatically outage. Inter-arrival p50/p90/p99 and maximum gaps remain in seconds.

Measured parameter-class counts: `{json.dumps(class_counts, sort_keys=True)}`.

## Canonical-frequency evidence

Only instantaneous irradiance tags enter this decision. Accumulation and meteorological tags remain characterised but cannot select the grid.

{_markdown_table(channel_rows, ['channel_group', 'median_active_p50_s'])}

The approved candidate sequence is 1min, 5min, then 15min. The first grid no finer than the slowest channel median is selected. Sub-minute reporting is evidence supporting 1min, not a new product requirement.

## Heartbeat and configured max-report-time

Supported observed repeated-value heartbeat candidates: **{heartbeat_supported} of {len(tags)} tags**.

An empirical candidate is never labelled the configured historian max-report-time. `configured_max_report_time_status` remains `unknown` until source-system configuration evidence is available.

## Exceptions and caveats

- Empty CSVs are explicit source artifacts and are not silently ignored.
- `flat_or_night` preserves ambiguity between night and other flat conditions.
- Maximum observed gaps over this extract are observations, not future guarantees.
- The raw extract supports COV cadence characterisation, not seasonal historical-coverage acceptance.

## Complete per-tag appendix

{_markdown_table(tags, appendix_columns)}

## Artifact index

- `source_manifest.csv`
- `inventory_reconciliation.csv`
- `empty_csv_entries.csv`
- `row_exceptions.csv`
- `timestamp_audit.csv`
- `tag_characterisation.csv`
- `canonical_frequency_evidence.csv`
- `canonical_frequency_decision.json`
- `run_manifest.json`
- `figures/` (five approved diagnostic plots)
"""


def _input_digest(source_manifest: pd.DataFrame) -> str:
    source = _stable_table(source_manifest, ("zip_name",))
    digest = hashlib.sha256()
    for row in source.itertuples(index=False):
        digest.update(str(getattr(row, "zip_name", "")).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(getattr(row, "sha256", "")).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def write_cov_artifacts(
    bundle: CovArtifactBundle,
    output_dir: Path,
) -> CovArtifactResult:
    """Render all evidence files, then hash them into a stable run manifest."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = bundle.report_path or output_dir / "phase0_cov_characterisation.md"

    table_values = {
        "source_manifest": bundle.ingestion.source_manifest,
        "inventory_reconciliation": bundle.reconciliation.table,
        "empty_csv_entries": bundle.ingestion.empty_entries,
        "row_exceptions": bundle.ingestion.row_exceptions,
        "timestamp_audit": bundle.ingestion.timestamp_audit,
        "tag_stats": bundle.tag_stats,
        "frequency_evidence": bundle.frequency_evidence,
    }
    artifact_paths: dict[str, Path] = {}
    for filename, table_name, sort_keys in TABLE_SPECS:
        path = output_dir / filename
        _write_csv(_stable_table(table_values[table_name], sort_keys), path)
        artifact_paths[filename] = path

    decision_path = output_dir / "canonical_frequency_decision.json"
    _write_json(asdict(bundle.decision), decision_path)
    artifact_paths["canonical_frequency_decision.json"] = decision_path

    figure_paths = {name: output_dir / name for name in FIGURE_NAMES}
    _plot_deadband(bundle.tag_stats, figure_paths[FIGURE_NAMES[0]])
    _plot_interarrival(bundle.tag_stats, figure_paths[FIGURE_NAMES[1]])
    _plot_frequency(bundle.decision, figure_paths[FIGURE_NAMES[2]])
    _plot_daylight(bundle.ingestion.events, figure_paths[FIGURE_NAMES[3]])
    _plot_gap_heartbeat(bundle.tag_stats, figure_paths[FIGURE_NAMES[4]])
    artifact_paths.update(figure_paths)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        _render_report(bundle),
        encoding="utf-8",
        newline="\n",
    )
    artifact_paths["phase0_cov_characterisation.md"] = report_path

    counts = {
        "zip_count": int(len(bundle.ingestion.source_manifest)),
        "csv_entry_count": int(
            bundle.ingestion.source_manifest.get(
                "csv_entry_count", pd.Series(dtype="int64")
            ).sum()
        ),
        "empty_csv_count": int(len(bundle.ingestion.empty_entries)),
        "event_count_after_integrity": int(len(bundle.ingestion.events)),
        "tag_count": int(len(bundle.tag_stats)),
        "row_exception_count": int(len(bundle.ingestion.row_exceptions)),
        "exact_duplicate_count": int(bundle.ingestion.exact_duplicate_count),
        "timestamp_conflict_count": int(bundle.ingestion.timestamp_conflict_count),
    }
    manifest = {
        "artifact_schema_version": 1,
        "characterisation_schema_version": 1,
        "input_set_sha256": _input_digest(bundle.ingestion.source_manifest),
        "strict_status": "passed" if not bundle.strict_errors else "failed",
        "strict_errors": list(bundle.strict_errors),
        "counts": counts,
        "decision": asdict(bundle.decision),
        "artifact_sha256": {
            name: _sha256(path)
            for name, path in sorted(artifact_paths.items())
        },
    }
    manifest_path = output_dir / "run_manifest.json"
    _write_json(manifest, manifest_path)
    artifact_paths["run_manifest.json"] = manifest_path
    return CovArtifactResult(
        manifest_path=manifest_path,
        manifest_sha256=_sha256(manifest_path),
        report_path=report_path,
        artifact_paths=artifact_paths,
    )
