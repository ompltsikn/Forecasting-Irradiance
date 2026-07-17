"""Library/CLI composition point for the Sprint 0 DNI*cosZ diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import pandas as pd
import yaml

from .cov_ingest import CovInputError, ingest_cov_directory
from .dni_cosz import (
    CLOSURE_EMIS,
    DniCoszEventAnalysis,
    SemanticsDecision,
    analyse_dni_cosz_events,
    quantization_from_tag_stats,
    resolve_semantics,
)
from .dni_cosz_artifacts import DniCoszArtifactResult, write_dni_cosz_artifacts
from .dni_cosz_xlsx import ingest_historical_xlsx, parse_instantaneous_filename


DEFAULT_STALENESS_WINDOWS_S = (60.0, 120.0, 300.0, 900.0)


@dataclass(frozen=True)
class DniCoszRunResult:
    """Final decision, component analyses, and deterministic artifacts."""

    decision: SemanticsDecision
    analyses: dict[str, DniCoszEventAnalysis]
    artifacts: DniCoszArtifactResult
    strict_errors: tuple[str, ...]
    summary: dict[str, object]


@dataclass(frozen=True)
class DniCoszStagedInputs:
    """Hash-verified local-VM copies of both S0-3 source scopes."""

    raw_dir: Path
    historical_root: Path
    file_count: int
    byte_count: int
    sha256_verified: bool


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stage_dni_cosz_inputs(
    *,
    raw_source_dir: Path,
    historical_source_root: Path,
    local_stage_root: Path,
) -> DniCoszStagedInputs:
    """Copy required sources off DriveFS and verify every copy by SHA-256."""

    raw_source = Path(raw_source_dir).resolve()
    historical_source = Path(historical_source_root).resolve()
    stage_root = Path(local_stage_root).resolve()
    if not raw_source.is_dir():
        raise CovInputError(f"raw source directory does not exist: {raw_source}")
    if not historical_source.is_dir():
        raise CovInputError(
            f"historical XLSX source directory does not exist: {historical_source}"
        )
    if stage_root.exists() and any(stage_root.iterdir()):
        raise CovInputError(f"local stage must be empty: {stage_root}")

    raw_files = sorted(raw_source.glob("*.zip"), key=lambda path: path.name)
    historical_files = []
    for path in sorted(historical_source.rglob("*.xlsx"), key=lambda item: item.as_posix()):
        identity = parse_instantaneous_filename(path.name)
        if identity is not None and identity[1] in {"1", "2", "3", "4"}:
            historical_files.append(path)
    if not raw_files:
        raise CovInputError(f"no ZIP files found in raw source: {raw_source}")
    if not historical_files:
        raise CovInputError(
            "no EMI01-EMI04 instantaneous GHI/DHI/DNIcosZ workbooks found in "
            f"historical source: {historical_source}"
        )

    raw_target = stage_root / "raw_cov"
    historical_target = stage_root / "historical_xlsx"
    raw_target.mkdir(parents=True, exist_ok=True)
    historical_target.mkdir(parents=True, exist_ok=True)
    byte_count = 0
    copied_count = 0
    copy_pairs = [
        (path, raw_target / path.name) for path in raw_files
    ] + [
        (path, historical_target / path.relative_to(historical_source))
        for path in historical_files
    ]
    for source_path, target_path in copy_pairs:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_path, target_path)
        if (
            source_path.stat().st_size != target_path.stat().st_size
            or _sha256(source_path) != _sha256(target_path)
        ):
            raise CovInputError(f"copy verification failed: {source_path}")
        byte_count += source_path.stat().st_size
        copied_count += 1
    return DniCoszStagedInputs(
        raw_dir=raw_target,
        historical_root=historical_target,
        file_count=copied_count,
        byte_count=byte_count,
        sha256_verified=True,
    )


def _read_site_config(path: Path) -> dict[str, object]:
    if not path.is_file():
        raise CovInputError(f"site config does not exist: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("site"), dict):
        raise CovInputError("site config must contain a site mapping")
    site = value["site"]
    required = (
        "latitude_deg",
        "longitude_deg",
        "timezone",
        "canonical_freq",
    )
    missing = [key for key in required if site.get(key) in (None, "")]
    if missing:
        raise CovInputError(f"site config missing required values: {', '.join(missing)}")
    return value


def validate_sensor_metadata(
    site_config_path: Path,
    decision_artifact_path: Path,
) -> None:
    """Require the canonical metadata value to match the decision artifact."""

    config_path = Path(site_config_path)
    decision_path = Path(decision_artifact_path)
    if not config_path.is_file():
        raise CovInputError(f"site config does not exist: {config_path}")
    if not decision_path.is_file():
        raise CovInputError(f"decision artifact does not exist: {decision_path}")

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    try:
        actual = config["sensor_metadata"]["dni_cosz"]["is_derived_tag"]
    except (KeyError, TypeError) as exc:
        raise CovInputError(
            "site config must contain "
            "sensor_metadata.dni_cosz.is_derived_tag"
        ) from exc
    if actual is not None and not isinstance(actual, bool):
        raise CovInputError(
            "sensor_metadata.dni_cosz.is_derived_tag must be true, false, or null"
        )

    try:
        artifact = json.loads(decision_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CovInputError(f"invalid decision artifact: {decision_path}") from exc
    if not isinstance(artifact, dict) or "is_derived_tag" not in artifact:
        raise CovInputError("decision artifact must contain is_derived_tag")
    expected = artifact["is_derived_tag"]
    if expected is not None and not isinstance(expected, bool):
        raise CovInputError("decision artifact is_derived_tag must be boolean or null")
    if actual is not expected:
        raise CovInputError(
            "sensor_metadata.dni_cosz.is_derived_tag does not match "
            f"the deterministic decision artifact: {actual!r} != {expected!r}"
        )


def _eligible_emis(events: pd.DataFrame) -> set[str]:
    required = {"GHI", "DHI", "DNIcosZ"}
    return {
        str(emi)
        for emi, group in events.groupby("emi", sort=True, observed=True)
        if set(group["channel_group"].dropna().astype(str)) >= required
    }


def _raw_source_manifest(manifest: pd.DataFrame) -> pd.DataFrame:
    result = manifest.rename(columns={"zip_name": "source_name"}).copy()
    result.insert(0, "source_scope", "raw_cov")
    result["relative_path"] = result["source_name"]
    return result


def _historical_source_manifest(manifest: pd.DataFrame) -> pd.DataFrame:
    result = manifest.rename(columns={"xlsx_name": "source_name"}).copy()
    result.insert(0, "source_scope", "historical_xlsx")
    return result


def run_dni_cosz_test(
    *,
    raw_dir: Path,
    historical_xlsx_root: Path | None,
    output_dir: Path,
    tag_stats_path: Path,
    site_config_path: Path,
    strict: bool = True,
    staleness_windows_s: tuple[float, ...] = DEFAULT_STALENESS_WINDOWS_S,
    minimum_samples: int = 20,
) -> DniCoszRunResult:
    """Run authoritative raw COV plus audited raw-column XLSX sensitivity."""

    config = _read_site_config(Path(site_config_path))
    site = config["site"]
    frequency = str(site["canonical_freq"])
    tag_stats = pd.read_csv(tag_stats_path)
    quantization, quantization_evidence, quantization_errors = (
        quantization_from_tag_stats(tag_stats)
    )
    ingestion = ingest_cov_directory(Path(raw_dir))
    errors = list(ingestion.strict_errors) + list(quantization_errors)
    analyses: dict[str, DniCoszEventAnalysis] = {}
    source_manifests = [_raw_source_manifest(ingestion.source_manifest)]

    raw_emis = _eligible_emis(ingestion.events)
    missing_raw = sorted(set(CLOSURE_EMIS).difference(raw_emis))
    if missing_raw:
        errors.append(f"raw_cov missing complete channel sets: {', '.join(missing_raw)}")
    analyses["raw_cov"] = analyse_dni_cosz_events(
        ingestion.events,
        quantization_by_emi=quantization,
        frequency=frequency,
        staleness_windows_s=staleness_windows_s,
        latitude_deg=float(site["latitude_deg"]),
        longitude_deg=float(site["longitude_deg"]),
        local_timezone=str(site["timezone"]),
        source_scope="raw_cov",
        minimum_samples=minimum_samples,
    )

    historical_scope_included = False
    if historical_xlsx_root is None:
        errors.append("historical_xlsx scope was not supplied")
    else:
        historical = ingest_historical_xlsx(Path(historical_xlsx_root))
        errors.extend(historical.strict_errors)
        source_manifests.append(_historical_source_manifest(historical.source_manifest))
        historical_emis = _eligible_emis(historical.events)
        missing_historical = sorted(set(CLOSURE_EMIS).difference(historical_emis))
        if missing_historical:
            errors.append(
                "historical_xlsx missing complete channel sets: "
                + ", ".join(missing_historical)
            )
        elif historical.events.empty:
            errors.append("historical_xlsx contains no instantaneous closure events")
        else:
            historical_scope_included = True
        analyses["historical_xlsx"] = analyse_dni_cosz_events(
            historical.events,
            quantization_by_emi=quantization,
            frequency=frequency,
            staleness_windows_s=staleness_windows_s,
            latitude_deg=float(site["latitude_deg"]),
            longitude_deg=float(site["longitude_deg"]),
            local_timezone=str(site["timezone"]),
            source_scope="historical_xlsx",
            minimum_samples=minimum_samples,
        )

    unique_errors = tuple(dict.fromkeys(errors))
    all_cases = {
        key: value
        for _, analysis in sorted(analyses.items())
        for key, value in sorted(analysis.case_decisions.items())
    }
    decision = resolve_semantics(all_cases)
    if unique_errors or not historical_scope_included:
        decision = SemanticsDecision(
            "unresolved",
            None,
            "source/provenance completeness errors prevent a stable metadata boolean",
        )

    source_manifest = pd.concat(source_manifests, ignore_index=True, sort=False)
    artifacts = write_dni_cosz_artifacts(
        analyses=analyses,
        final_decision=decision,
        output_dir=Path(output_dir),
        source_manifest=source_manifest,
        quantization_evidence=quantization_evidence,
        historical_scope_included=historical_scope_included,
        strict_errors=unique_errors,
    )
    summary: dict[str, object] = {
        "decision": decision.decision,
        "historical_scope_included": historical_scope_included,
        "is_derived_tag": decision.is_derived_tag,
        "manifest_sha256": artifacts.manifest_sha256,
        "raw_zip_count": int(len(ingestion.source_manifest)),
        "source_scopes": sorted(analyses),
        "strict_error_count": len(unique_errors),
        "strict_mode": bool(strict),
        "strict_status": "passed" if not unique_errors else "failed",
    }
    return DniCoszRunResult(
        decision=decision,
        analyses=analyses,
        artifacts=artifacts,
        strict_errors=unique_errors,
        summary=summary,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the Sprint 0 DNI*cosZ test.")
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--historical-xlsx-root", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tag-stats", type=Path, required=True)
    parser.add_argument("--site-config", type=Path, required=True)
    parser.add_argument("--diagnostic", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    strict = not args.diagnostic
    result = run_dni_cosz_test(
        raw_dir=args.raw_dir,
        historical_xlsx_root=args.historical_xlsx_root,
        output_dir=args.output_dir,
        tag_stats_path=args.tag_stats,
        site_config_path=args.site_config,
        strict=strict,
    )
    print(json.dumps(result.summary, sort_keys=True, ensure_ascii=False))
    return 2 if strict and result.strict_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
