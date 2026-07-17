from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.characterisation.dni_cosz import analyse_dni_cosz_events
from src.characterisation.dni_cosz_artifacts import write_dni_cosz_artifacts


def _derived_analysis():
    start = pd.Timestamp("2026-06-01 10:00:00")
    rows = []
    for minute in range(30):
        timestamp = start + pd.Timedelta(minutes=minute)
        for channel, value in (
            ("GHI", 600.0),
            ("DHI", 100.0),
            ("DNIcosZ", 500.0),
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
    return analyse_dni_cosz_events(
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


def test_artifact_writer_publishes_decision_summary_plot_and_hashes(
    tmp_path: Path,
) -> None:
    analysis = _derived_analysis()

    result = write_dni_cosz_artifacts(
        analyses={"synthetic": analysis},
        final_decision=analysis.decision,
        output_dir=tmp_path,
        source_manifest=pd.DataFrame(
            [{"source_scope": "synthetic", "source_name": "fixture"}]
        ),
        quantization_evidence=pd.DataFrame(
            [
                {
                    "emi": "EMI01",
                    "channel_group": "GHI",
                    "quantization_step_wm2": 1.0,
                }
            ]
        ),
        historical_scope_included=True,
        strict_errors=(),
    )

    decision = json.loads(result.decision_path.read_text(encoding="utf-8"))
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert decision["decision"] == "derived"
    assert decision["is_derived_tag"] is True
    assert decision["historical_scope_included"] is True
    residual = pd.read_csv(tmp_path / "residual_summary.csv")
    assert "ALL" in residual["emi"].astype(str).tolist()
    assert (tmp_path / "per_emi_summary.csv").is_file()
    assert result.figure_path.stat().st_size > 0
    assert set(manifest["artifact_sha256"]) >= {
        "residual_summary.csv",
        "per_emi_summary.csv",
        "residual_summary.json",
        "figures/dni_cosz_residual_vs_zenith.png",
    }
