from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

import pandas as pd

from src.characterisation.cov_cli import main, run_cov_characterisation


TAGS = {
    "GHI": "PLTS IKN / STS09 / WB09_EMI01 / MEAS / GLOBAL HORIZONTAL IRRADIANCE (GHI)",
    "DHI": "PLTS IKN / STS09 / WB09_EMI01 / MEAS / DIFFUSE HORIZONTAL IRRADIANCE (DHI)",
    "DNIcosZ": "PLTS IKN / STS09 / WB09_EMI01 / MEAS / DIRECT HORIZONTAL IRRADIANCE (DNI*cosZ)",
    "POA": "PLTS IKN / STS09 / WB09_EMI01 / MEAS / GLOBAL INCLINED IRRADIANCE (POA)",
    "RSI": "PLTS IKN / STS09 / WB09_EMI01 / MEAS / IN-PLANE REAR-SIDE IRRADIANCE (RSI) 01",
}


def _csv_bytes(tag: str, *, inverted: bool = False, offset: float = 0.0) -> bytes:
    rows = []
    for index in range(25):
        second = index * 10
        rows.append(
            [
                f"2026-06-01 08:00:{second:02d}.000" if second < 60 else f"2026-06-01 08:{second // 60:02d}:{second % 60:02d}.000",
                f"{10.0 + offset + index * 0.1:.6f}",
                "0",
            ]
        )
    if inverted:
        rows[10], rows[11] = rows[11], rows[10]
    output = [";".join(["date_time", f'"{tag}"', "object_caeid"])]
    output.extend(";".join(row) for row in rows)
    return ("\n".join(output) + "\n").encode("utf-8")


def _write_inputs(root: Path, *, conflict: bool = False) -> tuple[Path, Path, Path]:
    raw_dir = root / "raw"
    raw_dir.mkdir(parents=True)
    first = raw_dir / "generic-first.zip"
    with zipfile.ZipFile(first, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ghi.csv", _csv_bytes(TAGS["GHI"], inverted=True))
        archive.writestr("dhi.csv", _csv_bytes(TAGS["DHI"]))
        archive.writestr("empty.csv", b"")
        if conflict:
            archive.writestr(
                "ghi-conflict.csv",
                b'date_time;"' + TAGS["GHI"].encode() + b'";object_caeid\n'
                b"2026-06-01 08:00:00.000;999;0\n",
            )
    second = raw_dir / "generic-second.zip"
    with zipfile.ZipFile(second, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for channel in ("DNIcosZ", "POA", "RSI"):
            archive.writestr(f"{channel}.csv", _csv_bytes(TAGS[channel]))

    reference = root / "drive_inventory.csv"
    with reference.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=["drive_file_id", "zip_name", "byte_size"],
            lineterminator="\n",
        )
        writer.writeheader()
        for index, path in enumerate(sorted(raw_dir.glob("*.zip"))):
            writer.writerow(
                {
                    "drive_file_id": f"drive-{index}",
                    "zip_name": path.name,
                    "byte_size": path.stat().st_size,
                }
            )
    site_config = root / "site.yaml"
    site_config.write_text(
        "site:\n  site_id: PLTS-IKN\n  timezone: Asia/Makassar\n",
        encoding="utf-8",
    )
    return raw_dir, reference, site_config


def test_pipeline_writes_full_synthetic_evidence_and_resolves_frequency(
    tmp_path: Path,
) -> None:
    raw_dir, reference, site_config = _write_inputs(tmp_path)
    output_dir = tmp_path / "output"

    result = run_cov_characterisation(
        raw_dir,
        output_dir,
        reference,
        site_config,
    )

    assert result.strict_errors == ()
    assert result.decision.canonical_freq == "1min"
    assert result.summary["strict_status"] == "passed"
    assert result.summary["tag_count"] == 5
    assert result.summary["empty_csv_count"] == 1
    assert len(result.artifacts.artifact_paths) == 15
    tags = pd.read_csv(output_dir / "tag_characterisation.csv")
    assert set(tags["channel_group"]) == set(TAGS)
    assert "event_count_before_integrity" in tags
    assert int(tags["order_violation_count"].sum()) == 1


def test_pipeline_writes_diagnostics_and_cli_returns_two_on_strict_errors(
    tmp_path: Path,
    capsys,
) -> None:
    raw_dir, reference, site_config = _write_inputs(tmp_path, conflict=True)
    inventory = pd.read_csv(reference)
    inventory.loc[0, "byte_size"] += 1
    inventory.to_csv(reference, index=False, lineterminator="\n")
    output_dir = tmp_path / "failed-output"

    exit_code = main(
        [
            "--raw-dir",
            str(raw_dir),
            "--output-dir",
            str(output_dir),
            "--reference-inventory",
            str(reference),
            "--site-config",
            str(site_config),
        ]
    )
    summary = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert summary["strict_status"] == "failed"
    assert summary["strict_error_count"] >= 2
    assert (output_dir / "run_manifest.json").is_file()
    assert (output_dir / "row_exceptions.csv").is_file()


def test_diagnostic_flag_returns_zero_while_preserving_failed_status(
    tmp_path: Path,
    capsys,
) -> None:
    raw_dir, reference, site_config = _write_inputs(tmp_path, conflict=True)

    exit_code = main(
        [
            "--raw-dir",
            str(raw_dir),
            "--output-dir",
            str(tmp_path / "diagnostic-output"),
            "--reference-inventory",
            str(reference),
            "--site-config",
            str(site_config),
            "--diagnostic",
        ]
    )
    summary = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert summary["strict_status"] == "failed"
    assert summary["strict_error_count"] >= 1
