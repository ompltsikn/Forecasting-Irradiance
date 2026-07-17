"""Single CLI/library composition point for S0-2 COV characterisation."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd
import yaml

from .cov_artifacts import (
    CovArtifactBundle,
    CovArtifactResult,
    write_cov_artifacts,
)
from .cov_ingest import CovInputError, ingest_cov_directory, reconcile_inventory
from .cov_stats import (
    CanonicalFrequencyDecision,
    characterise_tags,
    decide_canonical_frequency,
)


@dataclass(frozen=True)
class CovRunResult:
    """Measured outcome returned to notebook, tests, and CLI."""

    decision: CanonicalFrequencyDecision
    strict_errors: tuple[str, ...]
    artifacts: CovArtifactResult
    summary: dict[str, object]


def _read_site_config(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise CovInputError(f"site config does not exist: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("site"), dict):
        raise CovInputError("site config must contain a site mapping")
    site = value["site"]
    if not site.get("timezone"):
        raise CovInputError("site config must contain site.timezone")
    return value


def _merge_integrity(tag_stats: pd.DataFrame, integrity: pd.DataFrame) -> pd.DataFrame:
    if integrity.empty:
        return tag_stats.copy()
    merged = tag_stats.merge(
        integrity,
        on="full_tag",
        how="left",
        validate="one_to_one",
        sort=False,
    )
    integer_columns = (
        "event_count_before_integrity",
        "event_count_after_integrity",
        "exact_duplicate_count",
        "timestamp_conflict_count",
        "order_violation_count",
    )
    for column in integer_columns:
        if column in merged:
            merged[column] = merged[column].fillna(0).astype("int64")
    return merged.sort_values("full_tag", kind="stable", ignore_index=True)


def _report_path_for(output_dir: Path) -> Path | None:
    """Publish the canonical report when using the repository artifact location."""

    output_dir = output_dir.resolve()
    if output_dir.name == "phase0_cov" and output_dir.parent.name == "artifacts":
        return output_dir.parent.parent / "docs" / "phase0_cov_characterisation.md"
    return None


def run_cov_characterisation(
    raw_dir: Path,
    output_dir: Path,
    reference_inventory: Path,
    site_config: Path,
    *,
    strict: bool = True,
) -> CovRunResult:
    """Execute ingestion, reconciliation, statistics, and evidence rendering."""

    raw_dir = Path(raw_dir)
    output_dir = Path(output_dir)
    reference_inventory = Path(reference_inventory)
    site_config = Path(site_config)
    _read_site_config(site_config)

    ingestion = ingest_cov_directory(raw_dir)
    reconciliation = reconcile_inventory(
        ingestion.source_manifest,
        reference_inventory,
    )
    tag_stats = _merge_integrity(
        characterise_tags(ingestion.events),
        ingestion.integrity_by_tag,
    )
    decision, frequency_evidence = decide_canonical_frequency(tag_stats)
    strict_errors = tuple(
        dict.fromkeys((*ingestion.strict_errors, *reconciliation.strict_errors))
    )
    bundle = CovArtifactBundle(
        ingestion=ingestion,
        reconciliation=reconciliation,
        tag_stats=tag_stats,
        decision=decision,
        frequency_evidence=frequency_evidence,
        strict_errors=strict_errors,
        report_path=_report_path_for(output_dir),
    )
    artifacts = write_cov_artifacts(bundle, output_dir)
    summary: dict[str, object] = {
        "canonical_freq": decision.canonical_freq,
        "canonical_seconds": decision.canonical_seconds,
        "decision_statistic_s": decision.decision_statistic_s,
        "empty_csv_count": int(len(ingestion.empty_entries)),
        "event_count_after_integrity": int(len(ingestion.events)),
        "manifest_sha256": artifacts.manifest_sha256,
        "populated_csv_count": int(
            ingestion.source_manifest["populated_csv_count"].sum()
        ),
        "csv_entry_count": int(
            ingestion.source_manifest["csv_entry_count"].sum()
        ),
        "strict_error_count": len(strict_errors),
        "strict_mode": bool(strict),
        "strict_status": "passed" if not strict_errors else "failed",
        "tag_count": int(len(tag_stats)),
        "zip_count": int(len(ingestion.source_manifest)),
    }
    return CovRunResult(
        decision=decision,
        strict_errors=strict_errors,
        artifacts=artifacts,
        summary=summary,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Characterise PLTS-IKN SCADA change-of-value reporting."
    )
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--reference-inventory", type=Path, required=True)
    parser.add_argument("--site-config", type=Path, required=True)
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help="write diagnostics but return zero despite strict source errors",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    strict = not args.diagnostic
    result = run_cov_characterisation(
        args.raw_dir,
        args.output_dir,
        args.reference_inventory,
        args.site_config,
        strict=strict,
    )
    print(json.dumps(result.summary, sort_keys=True, ensure_ascii=False))
    return 2 if strict and result.strict_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
