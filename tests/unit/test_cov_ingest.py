from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from src.characterisation.cov_ingest import (
    CovInputError,
    build_source_manifest,
    ingest_cov_directory,
    reconcile_inventory,
)


EMI01_GHI = (
    "PLTS IKN / STS09 / WB09_EMI01 / MEAS / "
    "GLOBAL HORIZONTAL IRRADIANCE (GHI)"
)
EMI05_GHI = "PLTS IKN / STS02 / WB02_EMI05 / MEAS / Total Irradiance"


def csv_bytes(tag: str, rows: list[tuple[str, str, str]]) -> bytes:
    lines = [f'"date_time";"{tag}";"object_caeid"']
    lines.extend(f'"{timestamp}";"{value}";"{object_id}"' for timestamp, value, object_id in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_zip(path: Path, entries: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)


def test_manifest_and_ingestion_cover_multi_csv_empty_and_provenance(
    tmp_path: Path,
) -> None:
    zip_path = tmp_path / "trends_export_1.zip"
    write_zip(
        zip_path,
        {
            "data.csv": csv_bytes(
                EMI05_GHI,
                [
                    ("2026-06-01 05:53:12.603", "445.799988", "0"),
                    ("2026-06-01 05:53:14.103", "446.399994", "0"),
                ],
            ),
            "empty.csv": b"",
        },
    )

    result = ingest_cov_directory(tmp_path)

    assert result.source_manifest[["zip_name", "csv_entry_count"]].to_dict(
        "records"
    ) == [{"zip_name": zip_path.name, "csv_entry_count": 2}]
    assert result.empty_entries[["source_zip", "source_csv"]].to_dict(
        "records"
    ) == [{"source_zip": zip_path.name, "source_csv": "empty.csv"}]
    assert result.events[["source_zip", "source_csv", "source_row"]].to_dict(
        "records"
    ) == [
        {"source_zip": zip_path.name, "source_csv": "data.csv", "source_row": 2},
        {"source_zip": zip_path.name, "source_csv": "data.csv", "source_row": 3},
    ]
    assert result.events["value"].tolist() == [445.799988, 446.399994]
    assert result.events["object_caeid_raw"].astype(str).tolist() == ["0", "0"]
    assert result.events["full_tag"].astype(str).unique().tolist() == [EMI05_GHI]
    assert result.events["timestamp_shape"].astype(str).unique().tolist() == [
        "naive"
    ]
    assert not result.strict_errors


def test_source_manifest_records_stable_sha256(tmp_path: Path) -> None:
    zip_path = tmp_path / "trends_export_2.zip"
    write_zip(zip_path, {"data.csv": csv_bytes(EMI01_GHI, [])})

    manifest = build_source_manifest(tmp_path)

    expected = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    assert manifest.loc[0, "sha256"] == expected
    assert manifest.loc[0, "byte_size"] == zip_path.stat().st_size
    assert manifest.loc[0, "populated_csv_count"] == 1
    assert manifest.loc[0, "empty_csv_count"] == 0


def test_malformed_rows_are_quarantined_and_make_strict_errors(
    tmp_path: Path,
) -> None:
    content = (
        f'"date_time";"{EMI01_GHI}";"object_caeid"\n'
        '"2026-06-01 06:00:00.000";"10.0";"0"\n'
        '"2026-06-01 06:00:01.000";"11.0"\n'
        '"2026-06-01 06:00:02.000";"not-a-number";"0"\n'
        '"not-a-timestamp";"12.0";"0"\n'
    ).encode("utf-8")
    write_zip(tmp_path / "bad_rows.zip", {"data.csv": content})

    result = ingest_cov_directory(tmp_path)

    assert result.events["value"].tolist() == [10.0]
    assert set(result.row_exceptions["reason"]) == {
        "invalid_timestamp",
        "malformed_width",
        "non_numeric_value",
    }
    assert len(result.strict_errors) == 1
    assert "3 populated rows excluded" in result.strict_errors[0]


def test_order_inversion_is_measured_before_stable_sort(tmp_path: Path) -> None:
    write_zip(
        tmp_path / "unordered.zip",
        {
            "data.csv": csv_bytes(
                EMI01_GHI,
                [
                    ("2026-06-01 06:00:02.000", "12.0", "0"),
                    ("2026-06-01 06:00:01.000", "11.0", "0"),
                ],
            )
        },
    )

    result = ingest_cov_directory(tmp_path)

    audit = result.timestamp_audit.iloc[0]
    assert audit["order_violation_count"] == 1
    assert result.events["value"].tolist() == [11.0, 12.0]
    assert not result.strict_errors


def test_exact_duplicates_are_removed_and_conflicts_are_quarantined(
    tmp_path: Path,
) -> None:
    duplicate = ("2026-06-01 06:00:00.000", "10.0", "0")
    write_zip(
        tmp_path / "duplicates.zip",
        {
            "one.csv": csv_bytes(EMI01_GHI, [duplicate]),
            "two.csv": csv_bytes(
                EMI01_GHI,
                [
                    duplicate,
                    ("2026-06-01 06:00:01.000", "11.0", "0"),
                    ("2026-06-01 06:00:01.000", "12.0", "0"),
                    ("2026-06-01 06:00:02.000", "13.0", "0"),
                ],
            ),
        },
    )

    result = ingest_cov_directory(tmp_path)

    assert result.exact_duplicate_count == 1
    assert result.timestamp_conflict_count == 1
    assert result.events["value"].tolist() == [10.0, 13.0]
    assert (result.row_exceptions["reason"] == "timestamp_conflict").sum() == 2
    assert any("1 conflicting tag/timestamp" in error for error in result.strict_errors)


def test_mixed_timestamp_shapes_are_explicit_strict_error(tmp_path: Path) -> None:
    write_zip(
        tmp_path / "mixed.zip",
        {
            "data.csv": csv_bytes(
                EMI01_GHI,
                [
                    ("2026-06-01 06:00:00.000", "10.0", "0"),
                    ("2026-06-01T06:00:01.000Z", "11.0", "0"),
                ],
            )
        },
    )

    result = ingest_cov_directory(tmp_path)

    assert set(result.events["timestamp_shape"].astype(str)) == {"naive", "utc_z"}
    assert any("mixed timestamp shapes" in error for error in result.strict_errors)


def test_drive_inventory_reconciliation_reports_exact_and_mismatch(
    tmp_path: Path,
) -> None:
    zip_path = tmp_path / "one.zip"
    write_zip(zip_path, {"data.csv": csv_bytes(EMI01_GHI, [])})
    local = build_source_manifest(tmp_path)
    reference = tmp_path / "drive_inventory.csv"
    pd.DataFrame(
        [
            {
                "drive_file_id": "drive-one",
                "zip_name": "one.zip",
                "byte_size": zip_path.stat().st_size,
            }
        ]
    ).to_csv(reference, index=False)

    exact = reconcile_inventory(local, reference)
    assert exact.table["match_status"].tolist() == ["matched"]
    assert not exact.strict_errors

    frame = pd.read_csv(reference)
    frame.loc[0, "byte_size"] += 1
    frame.to_csv(reference, index=False)
    mismatch = reconcile_inventory(local, reference)
    assert mismatch.table["match_status"].tolist() == ["size_mismatch"]
    assert mismatch.strict_errors == ("1 inventory reconciliation error",)


def test_corrupt_zip_is_rejected(tmp_path: Path) -> None:
    (tmp_path / "corrupt.zip").write_bytes(b"not a zip")

    with pytest.raises(CovInputError, match="corrupt.zip"):
        build_source_manifest(tmp_path)
