"""Deterministic artifacts and evidence plot for the S0-3 diagnostic."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from .dni_cosz import DniCoszEventAnalysis, SemanticsDecision


@dataclass(frozen=True)
class DniCoszArtifactResult:
    """Canonical paths produced by one deterministic artifact run."""

    decision_path: Path
    manifest_path: Path
    figure_path: Path
    manifest_sha256: str


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(
        path,
        index=False,
        lineterminator="\n",
        float_format="%.12g",
        date_format="%Y-%m-%dT%H:%M:%S.%f",
    )


def _write_json(value: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_plot(analyses: dict[str, DniCoszEventAnalysis], path: Path) -> None:
    frames = [
        analysis.plot_points.assign(source_scope=scope)
        for scope, analysis in sorted(analyses.items())
        if not analysis.plot_points.empty
    ]
    points = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not points.empty:
        sort_columns = [
            column
            for column in ("source_scope", "emi", "grid_time")
            if column in points
        ]
        points = points.sort_values(sort_columns, kind="stable", ignore_index=True)
        if len(points) > 50_000:
            positions = np.linspace(0, len(points) - 1, 50_000, dtype="int64")
            points = points.iloc[positions].reset_index(drop=True)

    figure, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    panels = (
        ("zenith_assuming_naive_wita_deg", "Naive historian clock interpreted as WITA"),
        ("zenith_assuming_naive_utc_deg", "Sensitivity: naive historian clock interpreted as UTC"),
    )
    if points.empty:
        for axis in axes:
            axis.text(0.5, 0.5, "No aligned residual samples", ha="center", va="center")
            axis.set_axis_off()
    else:
        emis = sorted(points["emi"].astype(str).unique())
        colours = plt.get_cmap("tab10")
        for axis, (column, title) in zip(axes, panels, strict=True):
            for index, emi in enumerate(emis):
                subset = points.loc[points["emi"].astype(str) == emi]
                axis.scatter(
                    subset[column],
                    subset["residual_wm2"],
                    s=5,
                    alpha=0.25,
                    color=colours(index % 10),
                    label=emi,
                    rasterized=True,
                )
            axis.axhline(0.0, color="black", linewidth=0.8)
            axis.set_title(title)
            axis.set_xlabel("Solar zenith [deg] (provisional)")
            axis.grid(alpha=0.2)
        axes[0].set_ylabel("GHI - DHI - DNI*cosZ [W/m2]")
        axes[1].legend(loc="best", fontsize="small")
    figure.suptitle("S0-3 DNI*cosZ residual versus solar zenith")
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160, metadata={"Software": "Forecasting-Irradiance"})
    plt.close(figure)


def write_dni_cosz_artifacts(
    *,
    analyses: dict[str, DniCoszEventAnalysis],
    final_decision: SemanticsDecision,
    output_dir: Path,
    source_manifest: pd.DataFrame,
    quantization_evidence: pd.DataFrame,
    historical_scope_included: bool,
    strict_errors: tuple[str, ...],
) -> DniCoszArtifactResult:
    """Write tabular, JSON, provenance, and figure evidence with hashes."""

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    residual_summary = pd.concat(
        [analysis.residual_summary for _, analysis in sorted(analyses.items())],
        ignore_index=True,
    )
    per_emi_summary = pd.concat(
        [analysis.per_emi_summary for _, analysis in sorted(analyses.items())],
        ignore_index=True,
    )
    case_decisions = {
        key: value
        for _, analysis in sorted(analyses.items())
        for key, value in sorted(analysis.case_decisions.items())
    }

    paths = {
        "residual_summary.csv": output_dir / "residual_summary.csv",
        "per_emi_summary.csv": output_dir / "per_emi_summary.csv",
        "source_manifest.csv": output_dir / "source_manifest.csv",
        "quantization_evidence.csv": output_dir / "quantization_evidence.csv",
        "residual_summary.json": output_dir / "residual_summary.json",
        "figures/dni_cosz_residual_vs_zenith.png": (
            output_dir / "figures" / "dni_cosz_residual_vs_zenith.png"
        ),
    }
    _write_csv(residual_summary, paths["residual_summary.csv"])
    _write_csv(per_emi_summary, paths["per_emi_summary.csv"])
    _write_csv(source_manifest, paths["source_manifest.csv"])
    _write_csv(quantization_evidence, paths["quantization_evidence.csv"])
    _write_json(
        {
            **asdict(final_decision),
            "case_decisions": case_decisions,
            "historical_scope_included": bool(historical_scope_included),
            "source_scopes": sorted(analyses),
            "strict_error_count": len(strict_errors),
            "strict_errors": list(strict_errors),
            "timestamp_semantics_status": "unconfirmed",
            "zenith_interpretation_status": "provisional",
        },
        paths["residual_summary.json"],
    )
    _write_plot(analyses, paths["figures/dni_cosz_residual_vs_zenith.png"])

    artifact_sha256 = {
        name: _sha256(path) for name, path in sorted(paths.items())
    }
    manifest_path = output_dir / "run_manifest.json"
    _write_json(
        {
            "artifact_sha256": artifact_sha256,
            "historical_scope_included": bool(historical_scope_included),
            "strict_error_count": len(strict_errors),
            "strict_status": "passed" if not strict_errors else "failed",
        },
        manifest_path,
    )
    return DniCoszArtifactResult(
        decision_path=paths["residual_summary.json"],
        manifest_path=manifest_path,
        figure_path=paths["figures/dni_cosz_residual_vs_zenith.png"],
        manifest_sha256=_sha256(manifest_path),
    )
