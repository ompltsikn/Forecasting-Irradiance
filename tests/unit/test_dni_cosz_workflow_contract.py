from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/s0-3-dni-cosz.yml")


def test_full_history_workflow_is_manual_read_only_and_pinned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "schedule:" not in text
    assert "contents: read" in text
    assert "persist-credentials: false" in text
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in text
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in text
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" in text


def test_full_history_workflow_verifies_both_source_inventories() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "EXPECTED_RAW_ZIP_COUNT: \"145\"" in text
    assert "EXPECTED_RAW_BYTES: \"23776109\"" in text
    assert "EXPECTED_XLSX_COUNT: \"156\"" in text
    assert "EXPECTED_XLSX_BYTES: \"291499871\"" in text
    assert "for prefix in GHI DHI DNI" in text
    assert "${prefix}*.xlsx" in text
    assert "*Accum*.xlsx" in text


def test_full_history_workflow_runs_strict_library_cli_and_excludes_raw_uploads() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python -m src.characterisation.dni_cosz_cli" in text
    assert "--diagnostic" not in text
    upload_start = text.index("actions/upload-artifact@")
    upload_block = text[upload_start:]
    assert "artifacts" in upload_block
    assert "raw_cov" not in upload_block
    assert "historical_xlsx" not in upload_block
    assert "if: always()" in text
    assert "rm -rf -- \"${S03_WORK_ROOT}\"" in text
