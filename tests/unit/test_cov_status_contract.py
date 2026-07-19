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
OT_ESCALATION_BRIEF = ROOT / "docs/phase0_ot_security_escalation.md"
OT_DECISION_RECORD = (
    ROOT / "artifacts/phase0_ot_security/decision_record.json"
)


def test_sprint_0_status_contract_is_consistent_across_artifacts_and_ledgers() -> None:
    decision = json.loads(
        (ROOT / "artifacts/phase0_cov/canonical_frequency_decision.json").read_text(
            encoding="utf-8"
        )
    )
    ot_record = json.loads(OT_DECISION_RECORD.read_text(encoding="utf-8"))
    ot_brief = OT_ESCALATION_BRIEF.read_text(encoding="utf-8")
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

    # A prepared S0-7 pack is deliberately non-evidence until OT Security
    # supplies either a decision or a named decision owner plus a target date.
    assert ot_record["schema_version"] == 1
    assert ot_record["task_id"] == "S0-7"
    assert ot_record["decision_id"] == "OD-1"
    assert ot_record["record_status"] == "pending"
    assert ot_record["acceptance_evidence"] is False
    assert ot_record["current_offline_path"]["mode"] == "manual_scada_export"
    assert ot_record["current_offline_path"]["production_approved"] is False
    assert ot_record["current_offline_path"]["cadence_seconds"] is None
    assert ot_record["current_offline_path"]["latency_p95_seconds"] is None
    assert ot_record["escalation"]["sent_at_utc"] is None
    assert ot_record["escalation"]["named_decision_owner"] is None
    assert ot_record["escalation"]["decision_due_date"] is None
    assert ot_record["escalation"]["external_evidence_refs"] == []
    assert ot_record["decision"]["selected_path"] is None
    assert ot_record["decision"]["cadence_seconds"] is None
    assert ot_record["decision"]["latency_p95_seconds"] is None
    assert ot_record["decision"]["latency_max_seconds"] is None
    assert ot_record["decision"]["approved_by"] is None
    assert ot_record["decision"]["served_horizons_min"] == []
    assert {
        candidate["id"] for candidate in ot_record["candidate_paths"]
    } == {"manual_csv", "sftp_push", "opcua_gateway", "other_one_way"}
    assert ot_record["candidate_freshness_budgets"] == [
        {
            "horizon_scope": "5_min",
            "max_end_to_end_latency_seconds": 60,
            "status": "evaluation_target_only",
        },
        {
            "horizon_scope": "15_min",
            "max_end_to_end_latency_seconds": 180,
            "status": "evaluation_target_only",
        },
        {
            "horizon_scope": "at_least_60_min",
            "max_end_to_end_latency_seconds": 600,
            "status": "evaluation_target_only",
        },
    ]
    assert ot_record["guardrails"]["read_only"] is True
    assert ot_record["guardrails"]["writeback_allowed"] is False
    assert ot_record["guardrails"]["reverse_path_allowed"] is False
    assert ot_record["guardrails"]["ot_to_it_only"] is True
    assert [
        item["horizon_minutes"]
        for item in ot_record["horizon_servability"]
    ] == [5, 10, 15, 30, 60, 120, 180, 360, 1440, 2880]
    assert all(
        item["served"] is None
        and item["status"] == "provisional_pending_od1"
        for item in ot_record["horizon_servability"]
    )
    assert ot_record["manual_csv_contingency"] == {
        "if_selected_permanently": {
            "horizons_below_minutes": 360,
            "served": False,
            "still_allowed": [
                "backtesting",
                "quality_control",
                "sensor_health",
                "intraday_research",
                "day_ahead_research",
            ],
        }
    }
    assert "S0-7 acceptance status: **PENDING**" in ot_brief
    assert "This brief does not constitute OT approval." in ot_brief
    assert "OT → DMZ → IT analytics host" in ot_brief
    assert "Manual CSV" in ot_brief
    assert "SFTP push" in ot_brief
    assert "OPC-UA" in ot_brief
    assert "named OT decision owner" in ot_brief
    assert "target decision date" in ot_brief

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
        assert (
            "NO-GO for Phase 1 and for any model." in text
            or "NO-GO for Phase 1 and all modelling." in text
        )
        assert "docs/phase0_ot_security_escalation.md" in text
        assert "artifacts/phase0_ot_security/decision_record.json" in text
        assert "template is not acceptance evidence" in text
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
        assert "actions/runs/29691093243" in text
        assert "actions/runs/29693115223" in text
        assert "actions/runs/29694308142" in text
        current_status = text.split(
            "**Sprint 0 parent-task acceptance:**", maxsplit=1
        )[1].split("#### Sprint 0 progress board", maxsplit=1)[0]
        assert "actions/runs/29693115223" in current_status
        assert "actions/runs/29694308142" in current_status
        assert "fd954edd6293f5d063a4ae17226f6ef59ef810fc" in current_status
        audit_block = current_status.split(
            "#### Sprint 0 audit refresh — v2.3", maxsplit=1
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
    assert "| Version | 2.3 (Sprint 0 release audit; S0-7 evidence pending) |" in prd
    assert "**Revision:** 2.3" in master
    assert "**Gate blocker / unresolved**" in master
    horizon_block = master.split("horizons:", maxsplit=1)[1].split(
        "evaluation:", maxsplit=1
    )[0]
    assert "served: true" not in horizon_block
    assert horizon_block.count("served: false") == 10
    assert "**Revision:** 2.3" in roadmap

    # Accepted discovery decisions must not be contradicted by stale prose or
    # an unsafe serving default elsewhere in the normative contract.
    assert "which is currently unverified" not in prd
    assert (
        "Whether the racking is fixed or tracking is currently unknown"
        not in prd
    )
    assert "served: bool = Field(\n        False," in prd
    assert "The site location is `[TBC]`" not in roadmap
    assert "**S0-3 measured decision:**" in master
