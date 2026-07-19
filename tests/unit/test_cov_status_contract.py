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

    audit_blocks: list[str] = []
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
        assert "**Sprint 0 parent-task acceptance:** **4/7 green**" in text
        assert "**Literal Gate M0 criterion coverage:** **6/7 evidenced**" in text
        assert "M0 is **not passed**" in text
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

        # The Sprint 0 progress board and evidence-backed S0-6 completion must
        # be present and identical in all three normative documents.
        assert "#### Sprint 0 progress board" in text
        assert "**S0-6 decision: COMPLETE.**" in text
        assert "actions/runs/29689204001" in text
        assert "actions/runs/29689455820" in text
        assert "actions/runs/29689693626" in text
        current_status = text.split(
            "**Sprint 0 parent-task acceptance:**", maxsplit=1
        )[1].split("#### Sprint 0 progress board", maxsplit=1)[0]
        assert "actions/runs/29689455820" in current_status
        assert "7798d091f8a87fd05534a4d5e2edf1c7ecbdb46c" in current_status
        audit_block = current_status.split(
            "#### Sprint 0 audit refresh — v2.1", maxsplit=1
        )[1].strip()
        audit_blocks.append(audit_block)
        assert "272 passing tests" in text
        assert "tests/leakage/test_no_future_leakage.py" in text
        s0_6_progress_lines = [
            line
            for line in text.splitlines()
            if line.startswith("| **S0-6** |") and "4/4" in line
        ]
        assert s0_6_progress_lines
        s0_7_progress_lines = [
            line
            for line in text.splitlines()
            if line.startswith("| **S0-7** |")
            and "GO / ready to start" in line
            and "0/1" in line
        ]
        assert s0_7_progress_lines
        assert "**S0-7 decision: GO / READY TO START.**" in text
        assert "sensor_metadata.dni_cosz.iso9060_class" in text
        assert (
            "site.horizons_min/site.daylight_elev_threshold_deg/"
            "site.clearsky_model/site.nrmse_denominator"
        ) in text
        expected_progress = {
            "S0-1": ("✅", "4/4"),
            "S0-2": ("🟡", "4/5"),
            "S0-3": ("✅", "4/4"),
            "S0-4": ("🟡", "5/6"),
            "S0-5": ("✅", "6/6"),
            "S0-6": ("✅", "4/4"),
            "S0-7": ("⏭️", "0/1"),
        }
        for task, (marker, fraction) in expected_progress.items():
            matching_lines = [
                line
                for line in audit_block.splitlines()
                if line.startswith(f"| **{task}** |")
                and marker in line
                and fraction in line
            ]
            assert len(matching_lines) == 1, (
                f"{path.name}: expected one audited {task} {marker} {fraction} row"
            )
        s0_5_status_lines = [
            line
            for line in text.splitlines()
            if line.startswith("| **S0-5** |") and "✅" in line
        ]
        assert s0_5_status_lines

    prd, master, roadmap = (
        path.read_text(encoding="utf-8") for path in NORMATIVE_DOCS
    )
    assert audit_blocks[0] == audit_blocks[1] == audit_blocks[2]
    assert "| Version | 2.1 (Sprint 0 audit; S0-7 GO) |" in prd
    assert "**Revision:** 2.1" in master
    assert "**Gate blocker / unresolved**" in master
    assert "**Revision:** 2.1" in roadmap
