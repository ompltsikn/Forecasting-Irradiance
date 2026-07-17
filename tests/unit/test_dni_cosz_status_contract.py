from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from src.characterisation.dni_cosz_cli import validate_sensor_metadata


ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_DIR = ROOT / "artifacts/phase0_dni_cosz"
NORMATIVE_DOCS = (
    ROOT / "PRD_Forecasting_Irradiance_ML.md",
    ROOT / "MASTER_CONTEXT_Forecasting_Irradiance_ML.md",
    ROOT / "ROADMAP_Forecasting_Irradiance_ML.md",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_measured_dni_cosz_decision_is_consistent_across_evidence_and_ledgers() -> None:
    decision_path = ARTIFACT_DIR / "residual_summary.json"
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    manifest = json.loads(
        (ARTIFACT_DIR / "run_manifest.json").read_text(encoding="utf-8")
    )
    config_path = ROOT / "configs/site_plts-ikn.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    report = (ROOT / "docs/phase0_dni_cosz_test.md").read_text(encoding="utf-8")

    assert decision["decision"] == "measured"
    assert decision["is_derived_tag"] is False
    assert len(decision["case_decisions"]) == 40
    assert set(decision["case_decisions"].values()) == {"measured"}
    assert decision["strict_error_count"] == 0
    assert config["sensor_metadata"]["dni_cosz"]["is_derived_tag"] is False
    validate_sensor_metadata(config_path, decision_path)

    for relative_path, expected_hash in manifest["artifact_sha256"].items():
        assert _sha256(ARTIFACT_DIR / relative_path) == expected_hash

    assert "S0-3 acceptance status: **GREEN**" in report
    assert "319,332" in report
    assert "8,027,772" in report
    assert "zenith interpretation remains provisional" in report
    assert "No forecasting model" in report

    for path in NORMATIVE_DOCS:
        text = path.read_text(encoding="utf-8")
        assert "| 1.3 | 2026-07-17 |" in text
        assert "**S0-3 decision: COMPLETE.**" in text
        assert "40/40" in text
        assert "8,027,772" in text
        assert "319,332" in text
        assert "`sensor_metadata.is_derived_tag=false`" in text
        assert "29589030480" in text
        assert "**S0-4 decision: GO now.**" in text
        assert "NO-GO for Phase 1" in text
