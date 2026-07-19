from __future__ import annotations

import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
NORMATIVE_DOCS = (
    ROOT / "PRD_Forecasting_Irradiance_ML.md",
    ROOT / "MASTER_CONTEXT_Forecasting_Irradiance_ML.md",
    ROOT / "ROADMAP_Forecasting_Irradiance_ML.md",
)


def test_measured_cov_decision_is_consistent_across_config_and_ledgers() -> None:
    decision = json.loads(
        (ROOT / "artifacts/phase0_cov/canonical_frequency_decision.json").read_text(
            encoding="utf-8"
        )
    )
    site = yaml.safe_load(
        (ROOT / "configs/site_plts-ikn.yaml").read_text(encoding="utf-8")
    )["site"]
    report = (ROOT / "docs/phase0_cov_characterisation.md").read_text(
        encoding="utf-8"
    )

    assert decision["canonical_freq"] == "1min"
    assert site["canonical_freq"] == decision["canonical_freq"]
    assert "S0-2 acceptance status: **YELLOW**" in report
    assert "configured historian max-report-time is not confirmed" in report

    for path in NORMATIVE_DOCS:
        text = path.read_text(encoding="utf-8")
        s0_2_status_lines = [
            line
            for line in text.splitlines()
            if line.startswith("| **S0-2** |") and "🟡" in line
        ]
        assert s0_2_status_lines
        assert "`canonical_freq`: **1min**" in text
        assert "2,640,992" in text
        assert "15,239" in text
        assert "26 instantaneous" in text
        assert "76 accumulation" in text
        assert "34 meteorological" in text
        assert "configured max-report-time" in text
        assert "`unknown`" in text
        assert "3/7" in text
        assert "NO-GO for Phase 1" in text
        assert "docs/phase0_cov_characterisation.md" in text
        assert "Sprint 0 acceptance checklist" in text
        assert "**S0-3 decision: COMPLETE.**" in text
        assert (
            "**S0-4 decision: consolidation delivered; 🟡 pending "
            "serial/calibration certificates and mapping/geometry "
            "confirmations.**" in text
        )
        assert "observation **2/2**" in text
        assert "historian timestamp semantics, configured max-report-time, and configured deadband" in text

        s0_3_status_lines = [
            line
            for line in text.splitlines()
            if line.startswith("| **S0-3** |") and "✅" in line
        ]
        assert s0_3_status_lines

        # S0-5 must read identically as complete in all three normative
        # documents, and must point at its deliverable.
        assert "**S0-5 decision: COMPLETE.**" in text
        assert "docs/phase0_data_audit.md" in text

        # The Sprint 0 progress board and the S0-6 GO decision must be present
        # and identical in all three normative documents.
        assert "#### Sprint 0 progress board" in text
        assert "**S0-6 decision: GO now**" in text
        assert "tests/leakage/test_no_future_leakage.py" in text
        s0_6_progress_lines = [
            line
            for line in text.splitlines()
            if line.startswith("| **S0-6** |") and "2/4" in line
        ]
        assert s0_6_progress_lines
        s0_5_status_lines = [
            line
            for line in text.splitlines()
            if line.startswith("| **S0-5** |") and "✅" in line
        ]
        assert s0_5_status_lines
