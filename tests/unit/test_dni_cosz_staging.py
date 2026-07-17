from __future__ import annotations

from pathlib import Path

import pytest

from src.characterisation.cov_ingest import CovInputError
from src.characterisation.dni_cosz_cli import stage_dni_cosz_inputs


def test_stage_copies_and_hash_verifies_only_required_input_types(
    tmp_path: Path,
) -> None:
    raw_source = tmp_path / "drive-raw"
    history_source = tmp_path / "drive-history"
    stage_root = tmp_path / "local-stage"
    raw_source.mkdir()
    (history_source / "2026" / "WS-1" / "Juni").mkdir(parents=True)
    (raw_source / "generic.zip").write_bytes(b"zip-fixture")
    xlsx = (
        history_source
        / "2026"
        / "WS-1"
        / "Juni"
        / "GHI_PLTS-IKN_WS-1_2026-Juni.xlsx"
    )
    xlsx.write_bytes(b"xlsx-fixture")
    legacy_xlsx = (
        history_source
        / "2025"
        / "WS-1"
        / "Agustus"
        / "DNI cosZ WS-1 PLTS IKN Agustus 2025.xlsx"
    )
    legacy_xlsx.parent.mkdir(parents=True)
    legacy_xlsx.write_bytes(b"legacy-xlsx-fixture")
    (history_source / "ignore.txt").write_text("ignore", encoding="utf-8")

    result = stage_dni_cosz_inputs(
        raw_source_dir=raw_source,
        historical_source_root=history_source,
        local_stage_root=stage_root,
    )

    assert result.raw_dir == stage_root / "raw_cov"
    assert result.historical_root == stage_root / "historical_xlsx"
    assert (result.raw_dir / "generic.zip").read_bytes() == b"zip-fixture"
    assert (
        result.historical_root
        / "2026"
        / "WS-1"
        / "Juni"
        / "GHI_PLTS-IKN_WS-1_2026-Juni.xlsx"
    ).read_bytes() == b"xlsx-fixture"
    assert not (result.historical_root / "ignore.txt").exists()
    assert (
        result.historical_root
        / "2025"
        / "WS-1"
        / "Agustus"
        / "DNI cosZ WS-1 PLTS IKN Agustus 2025.xlsx"
    ).read_bytes() == b"legacy-xlsx-fixture"
    assert result.file_count == 3
    assert result.byte_count == (
        len(b"zip-fixture") + len(b"xlsx-fixture") + len(b"legacy-xlsx-fixture")
    )
    assert result.sha256_verified is True


def test_stage_refuses_a_nonempty_target_to_avoid_stale_inputs(tmp_path: Path) -> None:
    raw_source = tmp_path / "drive-raw"
    history_source = tmp_path / "drive-history"
    stage_root = tmp_path / "local-stage"
    raw_source.mkdir()
    history_source.mkdir()
    stage_root.mkdir()
    (raw_source / "generic.zip").write_bytes(b"zip-fixture")
    (history_source / "GHI_PLTS-IKN_WS-1_2026-Juni.xlsx").write_bytes(
        b"xlsx-fixture"
    )
    (stage_root / "stale.txt").write_text("stale", encoding="utf-8")

    with pytest.raises(CovInputError, match="must be empty"):
        stage_dni_cosz_inputs(
            raw_source_dir=raw_source,
            historical_source_root=history_source,
            local_stage_root=stage_root,
        )
