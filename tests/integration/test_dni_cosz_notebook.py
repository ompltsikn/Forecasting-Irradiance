from __future__ import annotations

import asyncio
import json
import re
import sys
import zipfile
from pathlib import Path

import nbformat
import pandas as pd
from nbclient import NotebookClient


if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


NOTEBOOK = Path("notebooks/S0_3_DNIcosZ_Test.ipynb")
LOCATIONS = {
    "EMI01": ("STS09", "WB09", "WS-1"),
    "EMI02": ("STS05", "WB05", "WS-2"),
    "EMI03": ("STS06", "WB06", "WS-3"),
    "EMI04": ("STS04", "WB04", "WS-4"),
}
PARAMETERS = {
    "GHI": "GLOBAL HORIZONTAL IRRADIANCE (GHI)",
    "DHI": "DIFFUSE HORIZONTAL IRRADIANCE (DHI)",
    "DNIcosZ": "DIRECT HORIZONTAL IRRADIANCE (DNI*cosZ)",
}


def _write_inputs(root: Path) -> tuple[Path, Path, Path, Path]:
    raw_dir = root / "drive-raw"
    history_dir = root / "drive-history"
    raw_dir.mkdir()
    history_dir.mkdir()
    start = pd.Timestamp("2026-06-01 10:00:00")
    with zipfile.ZipFile(raw_dir / "generic.zip", "w") as archive:
        for emi, (sts, wb, ws) in LOCATIONS.items():
            for channel, parameter in PARAMETERS.items():
                tag = f"PLTS IKN / {sts} / {wb}_{emi} / MEAS / {parameter}"
                lines = [f"date_time;{tag};object_caeid"]
                values: list[float] = []
                times: list[pd.Timestamp] = []
                for minute in range(25):
                    timestamp = start + pd.Timedelta(minutes=minute)
                    ghi = 600.0 + minute
                    dhi = 100.0
                    value = {"GHI": ghi, "DHI": dhi, "DNIcosZ": ghi - dhi}[channel]
                    lines.append(f"{timestamp};{value};0")
                    values.append(value)
                    times.append(timestamp)
                archive.writestr(f"{emi}_{channel}.csv", "\n".join(lines) + "\n")
                name = f"{channel}_PLTS-IKN_{ws}_2026-Juni.xlsx"
                pd.DataFrame(
                    {
                        "Unnamed: 0": range(25),
                        "date_time": times,
                        name.removesuffix(".xlsx"): values,
                        "object_caeid": ["0"] * 25,
                        "Tanggal/Waktu": pd.date_range(
                            "2026-06-01", periods=25, freq="5min"
                        ),
                    }
                ).to_excel(history_dir / name, index=False)

    tag_stats = root / "tag_stats.csv"
    pd.DataFrame(
        [
            {
                "emi": emi,
                "channel_group": channel,
                "parameter_class": "instantaneous_irradiance",
                "deadband_estimate": 1.0,
                "deadband_confidence": "high",
                "abs_delta_p01": 1.0,
            }
            for emi in LOCATIONS
            for channel in PARAMETERS
        ]
    ).to_csv(tag_stats, index=False)
    site_config = root / "site.yaml"
    site_config.write_text(
        "site:\n"
        "  site_id: PLTS-IKN\n"
        "  latitude_deg: -0.9911713315158186\n"
        "  longitude_deg: 116.63811127764585\n"
        "  elevation_m: 85\n"
        "  timezone: Asia/Makassar\n"
        "  canonical_freq: 1min\n",
        encoding="utf-8",
    )
    return raw_dir, history_dir, tag_stats, site_config


def test_notebook_is_a_thin_library_runner() -> None:
    notebook = nbformat.read(NOTEBOOK, as_version=4)
    sources = "\n".join(cell.source for cell in notebook.cells)
    parameter_cells = [
        cell for cell in notebook.cells if "parameters" in cell.metadata.get("tags", [])
    ]

    assert len(parameter_cells) == 1
    for name in (
        "DRIVE_RAW_DATA_DIR",
        "DRIVE_HISTORICAL_XLSX_ROOT",
        "LOCAL_STAGE_ROOT",
        "OUTPUT_DIR",
        "TAG_STATS",
        "SITE_CONFIG",
        "STRICT_MODE",
        "SKIP_DRIVE_MOUNT",
    ):
        assert name in parameter_cells[0].source
    assert "stage_dni_cosz_inputs" in sources
    assert "run_dni_cosz_test" in sources
    assert "merge_asof" not in sources
    assert "residual_wm2" not in sources
    assert not re.search(r"def\s+(align_|classify_|summarise_)", sources)
    for forbidden in ("client_secret", "refresh_token", "oauth_json", "rclone.conf"):
        assert forbidden not in sources.lower()


def test_notebook_executes_locally_through_the_library(
    tmp_path: Path,
    monkeypatch,
) -> None:
    raw_dir, history_dir, tag_stats, site_config = _write_inputs(tmp_path)
    output_dir = tmp_path / "output"
    stage_root = tmp_path / "local-stage"
    repo_root = Path.cwd().resolve()
    overrides = {
        "S03_REPO_ROOT": str(repo_root),
        "S03_DRIVE_RAW_DATA_DIR": str(raw_dir),
        "S03_DRIVE_HISTORICAL_XLSX_ROOT": str(history_dir),
        "S03_LOCAL_STAGE_ROOT": str(stage_root),
        "S03_OUTPUT_DIR": str(output_dir),
        "S03_TAG_STATS": str(tag_stats),
        "S03_SITE_CONFIG": str(site_config),
        "S03_STRICT_MODE": "true",
        "S03_SKIP_DRIVE_MOUNT": "true",
    }
    for name, value in overrides.items():
        monkeypatch.setenv(name, value)

    notebook = nbformat.read(NOTEBOOK, as_version=4)
    executed = NotebookClient(
        notebook,
        timeout=600,
        kernel_name="python3",
        resources={"metadata": {"path": str(repo_root)}},
    ).execute()

    assert (output_dir / "residual_summary.json").is_file()
    assert (output_dir / "figures" / "dni_cosz_residual_vs_zenith.png").is_file()
    decision = json.loads(
        (output_dir / "residual_summary.json").read_text(encoding="utf-8")
    )
    assert decision["is_derived_tag"] is True
    outputs = "\n".join(
        str(output)
        for cell in executed.cells
        for output in cell.get("outputs", [])
    )
    assert "is_derived_tag" in outputs
