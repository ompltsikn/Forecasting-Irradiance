from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from data_contracts.nwp_schema import (
    NWP_COLUMNS,
    RunManifest,
    load_and_validate_manifest,
    validate_manifest,
)
from src.ingestion.nwp_archiver import (
    partition_relative_path,
    sha256_file,
    write_archive_attempt,
)


UTC = timezone.utc
ISSUE = datetime(2026, 7, 16, 6, tzinfo=UTC)
RETRIEVED = datetime(2026, 7, 16, 7, 15, 30, tzinfo=UTC)


def _write_artifact(
    tmp_path: Path,
    valid_ifs_frame: pd.DataFrame,
):
    return write_archive_attempt(
        valid_ifs_frame,
        output_root=tmp_path,
        requested_parameters=("ssrd", "tcc"),
        requested_steps_h=(0, 3),
        received_parameters=("ssrd", "tcc"),
        received_steps_h=(0, 3),
        smoke=False,
    )


def _manifest_for_rewritten_parquet(
    manifest: RunManifest,
    parquet_path: Path,
) -> RunManifest:
    return replace(
        manifest,
        parquet_bytes=parquet_path.stat().st_size,
        parquet_sha256=hashlib.sha256(parquet_path.read_bytes()).hexdigest(),
    )


def test_attempt_path_is_deterministic() -> None:
    assert partition_relative_path(
        nwp_source="ecmwf_ifs",
        issue_time_utc=ISSUE,
        retrieved_at_utc=RETRIEVED,
        smoke=False,
    ).as_posix() == (
        "nwp_source=ecmwf_ifs/issue_date=2026-07-16/issue_hour=06/"
        "retrieved_at=20260716T071530Z"
    )
    assert partition_relative_path(
        nwp_source="ecmwf_ifs",
        issue_time_utc=ISSUE,
        retrieved_at_utc=RETRIEVED,
        smoke=True,
    ).parts[0] == "_smoke"


def test_sha256_reference(tmp_path: Path) -> None:
    path = tmp_path / "abc.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_atomic_parquet_and_manifest_roundtrip(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    artifact = _write_artifact(tmp_path / "out", valid_ifs_frame)
    assert artifact.parquet_path.is_file()
    assert artifact.manifest_path.is_file()
    assert {path.name for path in artifact.run_directory.iterdir()} == {
        "manifest.json",
        "weather_forecast_raw.parquet",
    }
    restored = pd.read_parquet(artifact.parquet_path)
    assert pq.read_schema(artifact.parquet_path).names == list(NWP_COLUMNS)
    assert str(restored["issue_time_utc"].dtype) == "datetime64[ns, UTC]"
    assert pd.isna(restored.loc[0, "ssrd_wm2"])
    assert restored.loc[1, "ssrd_wm2"] == 100.0
    validate_manifest(artifact.manifest, parquet_path=artifact.parquet_path)
    assert artifact.manifest.row_count == 2
    assert artifact.manifest.parquet_sha256 == sha256_file(artifact.parquet_path)
    assert json.loads(artifact.manifest_path.read_text(encoding="utf-8"))["status"] == (
        "complete"
    )


def test_manifest_json_roundtrip_is_loaded_and_validated(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    artifact = _write_artifact(tmp_path, valid_ifs_frame)
    assert load_and_validate_manifest(
        artifact.manifest_path,
        parquet_path=artifact.parquet_path,
    ) == artifact.manifest


def test_manifest_hash_matches_independent_hash(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    artifact = _write_artifact(tmp_path, valid_ifs_frame)
    independent = hashlib.sha256(artifact.parquet_path.read_bytes()).hexdigest()
    assert artifact.manifest.parquet_sha256 == independent


def test_all_null_model_columns_have_numeric_physical_parquet_type(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    artifact = _write_artifact(tmp_path, valid_ifs_frame)
    schema = pq.read_schema(artifact.parquet_path)
    for column in (
        "lcc_frac",
        "mcc_frac",
        "hcc_frac",
        "cp_accum_m",
        "cp_interval_m",
        "cp_mm",
    ):
        assert pa.types.is_floating(schema.field(column).type)


def test_noncanonical_all_null_physical_type_is_rejected(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    artifact = _write_artifact(tmp_path, valid_ifs_frame)
    table = pq.read_table(artifact.parquet_path, partitioning=None)
    column_index = table.schema.get_field_index("lcc_frac")
    arrays = list(table.columns)
    arrays[column_index] = pa.chunked_array(
        [pa.nulls(table.num_rows, type=pa.string())]
    )
    fields = list(table.schema)
    fields[column_index] = pa.field("lcc_frac", pa.string())
    pq.write_table(
        pa.Table.from_arrays(arrays, schema=pa.schema(fields)),
        artifact.parquet_path,
    )
    rewritten_manifest = _manifest_for_rewritten_parquet(
        artifact.manifest,
        artifact.parquet_path,
    )

    with pytest.raises(ValueError, match="schema"):
        validate_manifest(rewritten_manifest, parquet_path=artifact.parquet_path)


@pytest.mark.parametrize(
    ("manifest_change", "message"),
    [
        ({"site_id": "OTHER"}, "site_id"),
        ({"grid_latitude": -1.25}, "grid_latitude"),
        ({"row_count": 3}, "row count"),
        (
            {"valid_time_min_utc": datetime(2026, 7, 16, 7, tzinfo=UTC)},
            "minimum valid time",
        ),
        (
            {"valid_time_max_utc": datetime(2026, 7, 16, 10, tzinfo=UTC)},
            "maximum valid time",
        ),
    ],
)
def test_manifest_metadata_must_match_parquet(
    tmp_path: Path,
    valid_ifs_frame: pd.DataFrame,
    manifest_change: dict[str, object],
    message: str,
) -> None:
    artifact = _write_artifact(tmp_path, valid_ifs_frame)
    inconsistent = replace(artifact.manifest, **manifest_change)
    with pytest.raises(ValueError, match=message):
        validate_manifest(inconsistent, parquet_path=artifact.parquet_path)


@pytest.mark.parametrize(
    "manifest_change",
    [
        {"received_parameters": ("ssrd",)},
        {"requested_parameters": ("ssrd", "ssrd")},
        {"received_steps_h": (0,)},
        {"requested_steps_h": (0, 3, 3)},
    ],
)
def test_manifest_rejects_incomplete_or_duplicate_inventory(
    tmp_path: Path,
    valid_ifs_frame: pd.DataFrame,
    manifest_change: dict[str, object],
) -> None:
    artifact = _write_artifact(tmp_path, valid_ifs_frame)
    incomplete = replace(artifact.manifest, **manifest_change)
    with pytest.raises(ValueError, match="inventory"):
        validate_manifest(incomplete, parquet_path=artifact.parquet_path)


def test_hash_mismatch_is_rejected(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    artifact = _write_artifact(tmp_path, valid_ifs_frame)
    artifact.parquet_path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash"):
        validate_manifest(artifact.manifest, parquet_path=artifact.parquet_path)


def test_validation_failure_leaves_no_final_attempt(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    invalid = valid_ifs_frame.copy()
    invalid.loc[1, "lead_time_min"] = 179
    with pytest.raises(ValueError, match="lead_time_min"):
        _write_artifact(tmp_path, invalid)
    assert list(tmp_path.rglob("retrieved_at=*")) == []


def test_post_write_validation_failure_cleans_temporary_attempt(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    with pytest.raises(ValueError, match="parameter inventory"):
        write_archive_attempt(
            valid_ifs_frame,
            output_root=tmp_path,
            requested_parameters=("ssrd",),
            requested_steps_h=(0, 3),
            received_parameters=("tcc",),
            received_steps_h=(0, 3),
            smoke=False,
        )
    assert list(tmp_path.rglob("retrieved_at=*")) == []
    temporary_root = tmp_path / ".tmp"
    assert not temporary_root.exists() or list(temporary_root.iterdir()) == []


def test_existing_attempt_is_append_only(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    artifact = _write_artifact(tmp_path, valid_ifs_frame)
    original_hash = sha256_file(artifact.parquet_path)

    with pytest.raises(FileExistsError, match="attempt already exists"):
        _write_artifact(tmp_path, valid_ifs_frame)

    assert sha256_file(artifact.parquet_path) == original_hash
