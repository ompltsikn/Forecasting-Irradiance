from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import yaml

from src.characterisation.dni_cosz_cli import run_dni_cosz_test


LOCATIONS = {
    "EMI01": ("STS09", "WB09", "WS-1"),
    "EMI02": ("STS05", "WB05", "WS-2"),
    "EMI03": ("STS06", "WB06", "WS-3"),
    "EMI04": ("STS04", "WB04", "WS-4"),
}
RAW_PARAMETERS = {
    "GHI": "GLOBAL HORIZONTAL IRRADIANCE (GHI)",
    "DHI": "DIFFUSE HORIZONTAL IRRADIANCE (DHI)",
    "DNIcosZ": "DIRECT HORIZONTAL IRRADIANCE (DNI*cosZ)",
}


def _series() -> list[tuple[pd.Timestamp, dict[str, float]]]:
    start = pd.Timestamp("2026-06-01 10:00:00")
    return [
        (
            start + pd.Timedelta(minutes=minute),
            {"GHI": 600.0 + minute, "DHI": 100.0, "DNIcosZ": 500.0 + minute},
        )
        for minute in range(30)
    ]


def _write_raw_zip(raw_dir: Path) -> Path:
    raw_dir.mkdir()
    path = raw_dir / "trends_export_fixture.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for emi, (sts, wb, _) in LOCATIONS.items():
            for channel, parameter in RAW_PARAMETERS.items():
                tag = f"PLTS IKN / {sts} / {wb}_{emi} / MEAS / {parameter}"
                lines = [f"date_time;{tag};object_caeid"]
                for timestamp, values in _series():
                    lines.append(f"{timestamp.isoformat(sep=' ')};{values[channel]};0")
                archive.writestr(f"{emi}_{channel}.csv", "\n".join(lines) + "\n")
    return path


def _write_history(root: Path) -> None:
    root.mkdir()
    for emi, (_, _, ws) in LOCATIONS.items():
        for channel in RAW_PARAMETERS:
            name = f"{channel}_PLTS-IKN_{ws}_2026-Juni.xlsx"
            frame = pd.DataFrame(
                {
                    "Unnamed: 0": range(30),
                    "date_time": [timestamp for timestamp, _ in _series()],
                    name.removesuffix(".xlsx"): [
                        values[channel] for _, values in _series()
                    ],
                    "object_caeid": ["0"] * 30,
                    "Tanggal/Waktu": pd.date_range(
                        "2026-06-01", periods=30, freq="5min"
                    ),
                }
            )
            frame.to_excel(root / name, index=False)


def _write_tag_stats(path: Path) -> None:
    rows = []
    for emi in LOCATIONS:
        for channel in RAW_PARAMETERS:
            rows.append(
                {
                    "emi": emi,
                    "channel_group": channel,
                    "parameter_class": "instantaneous_irradiance",
                    "deadband_estimate": 1.0,
                    "deadband_confidence": "high",
                    "abs_delta_p01": 1.0,
                }
            )
    pd.DataFrame(rows).to_csv(path, index=False)


def test_pipeline_uses_raw_cov_and_raw_xlsx_columns_for_stable_decision(
    tmp_path: Path,
) -> None:
    raw_dir = tmp_path / "raw"
    history_dir = tmp_path / "history"
    output_dir = tmp_path / "artifacts"
    _write_raw_zip(raw_dir)
    _write_history(history_dir)
    tag_stats = tmp_path / "tag_stats.csv"
    _write_tag_stats(tag_stats)
    site_config = tmp_path / "site.yaml"
    site_config.write_text(
        yaml.safe_dump(
            {
                "site": {
                    "site_id": "PLTS-IKN",
                    "latitude_deg": -0.9911713315158186,
                    "longitude_deg": 116.63811127764585,
                    "elevation_m": 85.0,
                    "timezone": "Asia/Makassar",
                    "canonical_freq": "1min",
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = run_dni_cosz_test(
        raw_dir=raw_dir,
        historical_xlsx_root=history_dir,
        output_dir=output_dir,
        tag_stats_path=tag_stats,
        site_config_path=site_config,
        strict=True,
    )

    assert result.strict_errors == ()
    assert result.decision.decision == "derived"
    assert result.decision.is_derived_tag is True
    decision = json.loads(
        (output_dir / "residual_summary.json").read_text(encoding="utf-8")
    )
    assert decision["source_scopes"] == ["historical_xlsx", "raw_cov"]
    assert decision["historical_scope_included"] is True
