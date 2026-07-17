from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.characterisation.cov_artifacts import (
    CovArtifactBundle,
    write_cov_artifacts,
)
from src.characterisation.cov_ingest import IngestionResult, ReconciliationResult
from src.characterisation.cov_stats import CanonicalFrequencyDecision


EXPECTED_ARTIFACTS = {
    "source_manifest.csv",
    "inventory_reconciliation.csv",
    "empty_csv_entries.csv",
    "row_exceptions.csv",
    "timestamp_audit.csv",
    "tag_characterisation.csv",
    "canonical_frequency_evidence.csv",
    "canonical_frequency_decision.json",
    "phase0_cov_characterisation.md",
    "figures/deadband_instantaneous.png",
    "figures/interarrival_instantaneous.png",
    "figures/canonical_frequency_evidence.png",
    "figures/timestamp_daylight_alignment.png",
    "figures/gap_heartbeat_evidence.png",
    "run_manifest.json",
}


def _bundle() -> CovArtifactBundle:
    events = pd.DataFrame(
        {
            "full_tag": ["tag-b", "tag-a", "tag-a", "tag-b"],
            "parameter_class": ["instantaneous_irradiance"] * 4,
            "channel_group": ["GHI", "DHI", "DHI", "GHI"],
            "event_time": pd.to_datetime(
                [
                    "2026-06-01 07:00:00",
                    "2026-06-01 08:00:00",
                    "2026-06-01 09:00:00",
                    "2026-06-01 10:00:00",
                ]
            ),
            "value": [10.0, 5.0, 6.0, 12.0],
        }
    )
    ingestion = IngestionResult(
        events=events,
        source_manifest=pd.DataFrame(
            [
                {
                    "zip_name": "b.zip",
                    "byte_size": 20,
                    "sha256": "b" * 64,
                    "csv_entry_count": 1,
                    "populated_csv_count": 1,
                    "empty_csv_count": 0,
                    "uncompressed_csv_bytes": 30,
                },
                {
                    "zip_name": "a.zip",
                    "byte_size": 10,
                    "sha256": "a" * 64,
                    "csv_entry_count": 2,
                    "populated_csv_count": 1,
                    "empty_csv_count": 1,
                    "uncompressed_csv_bytes": 15,
                },
            ]
        ),
        empty_entries=pd.DataFrame(
            [{"source_zip": "a.zip", "source_csv": "empty.csv", "uncompressed_bytes": 0}]
        ),
        row_exceptions=pd.DataFrame(
            columns=["source_zip", "source_csv", "source_row", "reason", "raw_row"]
        ),
        timestamp_audit=pd.DataFrame(
            [
                {
                    "source_zip": "a.zip",
                    "source_csv": "data.csv",
                    "full_tag": "tag-a",
                    "row_count": 2,
                    "timestamp_shape": "naive",
                    "coverage_start_raw": "2026-06-01 08:00:00",
                    "coverage_end_raw": "2026-06-01 09:00:00",
                    "order_violation_count": 0,
                }
            ]
        ),
        integrity_by_tag=pd.DataFrame(),
        strict_errors=(),
        exact_duplicate_count=0,
        timestamp_conflict_count=0,
    )
    reconciliation = ReconciliationResult(
        table=pd.DataFrame(
            [
                {"zip_name": "b.zip", "local_byte_size": 20, "reference_byte_size": 20, "status": "matched"},
                {"zip_name": "a.zip", "local_byte_size": 10, "reference_byte_size": 10, "status": "matched"},
            ]
        ),
        strict_errors=(),
    )
    tag_stats = pd.DataFrame(
        [
            {
                "full_tag": "tag-b",
                "emi": "EMI01",
                "canonical_parameter": "Global Horizontal Irradiance (GHI)",
                "parameter_class": "instantaneous_irradiance",
                "channel_group": "GHI",
                "event_count": 2,
                "coverage_start_raw": "2026-06-01 07:00:00",
                "coverage_end_raw": "2026-06-01 10:00:00",
                "deadband_estimate": 0.1,
                "deadband_confidence": "high",
                "deadband_unresolved_reason": None,
                "interarrival_p50_s": 20.0,
                "interarrival_p90_s": 30.0,
                "interarrival_p99_s": 40.0,
                "max_gap_s": 60.0,
                "active_interarrival_p50_s": 20.0,
                "flat_interarrival_p50_s": 50.0,
                "max_active_gap_s": 60.0,
                "observed_heartbeat_candidate_s": None,
                "heartbeat_confidence": "unresolved",
                "heartbeat_unresolved_reason": "insufficient evidence",
                "configured_max_report_time_status": "unknown",
                "sibling_events_during_max_active_gap": 3,
            },
            {
                "full_tag": "tag-a",
                "emi": "EMI01",
                "canonical_parameter": "Diffuse Horizontal Irradiance (DHI)",
                "parameter_class": "instantaneous_irradiance",
                "channel_group": "DHI",
                "event_count": 2,
                "coverage_start_raw": "2026-06-01 08:00:00",
                "coverage_end_raw": "2026-06-01 09:00:00",
                "deadband_estimate": None,
                "deadband_confidence": "unresolved",
                "deadband_unresolved_reason": "insufficient evidence",
                "interarrival_p50_s": 21.0,
                "interarrival_p90_s": 31.0,
                "interarrival_p99_s": 41.0,
                "max_gap_s": 61.0,
                "active_interarrival_p50_s": 21.0,
                "flat_interarrival_p50_s": 51.0,
                "max_active_gap_s": 61.0,
                "observed_heartbeat_candidate_s": None,
                "heartbeat_confidence": "unresolved",
                "heartbeat_unresolved_reason": "insufficient evidence",
                "configured_max_report_time_status": "unknown",
                "sibling_events_during_max_active_gap": 2,
            },
        ]
    )
    decision = CanonicalFrequencyDecision(
        canonical_freq="1min",
        canonical_seconds=60.0,
        decision_statistic_s=21.0,
        channel_medians_s={"DHI": 21.0, "GHI": 20.0},
        supported_tag_count=2,
        exception_tag_count=0,
        unresolved_reason=None,
    )
    frequency_evidence = pd.DataFrame(
        [
            {
                "scope": "decision",
                "key": "canonical_freq",
                "channel_group": None,
                "active_interarrival_p50_s": 21.0,
                "channel_median_s": 21.0,
                "canonical_freq": "1min",
                "canonical_seconds": 60.0,
                "unresolved_reason": None,
            }
        ]
    )
    return CovArtifactBundle(
        ingestion=ingestion,
        reconciliation=reconciliation,
        tag_stats=tag_stats,
        decision=decision,
        frequency_evidence=frequency_evidence,
        strict_errors=(),
    )


def test_artifact_bundle_is_byte_stable_and_manifest_is_complete(tmp_path: Path) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"

    first = write_cov_artifacts(_bundle(), first_dir)
    second = write_cov_artifacts(_bundle(), second_dir)

    assert set(first.artifact_paths) == EXPECTED_ARTIFACTS
    assert set(second.artifact_paths) == EXPECTED_ARTIFACTS
    for relative_path in EXPECTED_ARTIFACTS:
        assert (first_dir / relative_path).read_bytes() == (
            second_dir / relative_path
        ).read_bytes()

    manifest = json.loads(
        (first_dir / "run_manifest.json").read_text(encoding="utf-8")
    )
    assert "run_manifest.json" not in manifest["artifact_sha256"]
    assert set(manifest["artifact_sha256"]) == EXPECTED_ARTIFACTS - {
        "run_manifest.json"
    }
    assert first.manifest_sha256 == second.manifest_sha256
    assert first.report_path.name == "phase0_cov_characterisation.md"


def test_artifact_tables_are_sorted_and_report_has_required_sections(tmp_path: Path) -> None:
    result = write_cov_artifacts(_bundle(), tmp_path)

    source = pd.read_csv(tmp_path / "source_manifest.csv")
    tags = pd.read_csv(tmp_path / "tag_characterisation.csv")
    report = result.report_path.read_text(encoding="utf-8")

    assert source["zip_name"].tolist() == ["a.zip", "b.zip"]
    assert tags["full_tag"].tolist() == ["tag-a", "tag-b"]
    assert "# S0-2 COV Characterisation" in report
    assert "## Executive decision" in report
    assert "## Timestamp semantics" in report
    assert "## Heartbeat and configured max-report-time" in report
    assert "## Complete per-tag appendix" in report
    assert "tag-a" in report and "tag-b" in report
    for figure in (tmp_path / "figures").glob("*.png"):
        assert figure.stat().st_size > 1_000
