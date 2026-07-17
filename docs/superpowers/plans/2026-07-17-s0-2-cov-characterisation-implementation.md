# S0-2 COV Characterisation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and execute a library-first COV characterisation workflow that audits all 136 PLTS-IKN SCADA tags, generates deterministic evidence artifacts and a Colab runner, and derives `canonical_freq` from the 26 instantaneous irradiance tags without building a model.

**Architecture:** Focused Python modules own tag contracts, ZIP/CSV ingestion, per-tag statistics, canonical-frequency selection, and deterministic artifact rendering. A single CLI composes those modules; the Colab notebook only configures Drive/local paths, stages ZIPs on the VM, calls the CLI, and displays the same artifacts used by tests and local execution.

**Tech Stack:** Python 3.13.2 locally and Python 3.12+ in Colab; `pandas==3.0.2`, `numpy==2.4.4`, `matplotlib==3.10.9`, `PyYAML==6.0.3`, `pytest==9.0.3`, `nbformat==5.10.4`, `nbclient==0.10.2`, standard-library `csv`, `hashlib`, and `zipfile`.

## Global Constraints

- Treat `PRD_Forecasting_Irradiance_ML.md`, `MASTER_CONTEXT_Forecasting_Irradiance_ML.md`, `ROADMAP_Forecasting_Irradiance_ML.md`, and `docs/superpowers/specs/2026-07-17-s0-2-cov-characterisation-design.md` as one contract.
- Characterise all 136 tags, but derive `canonical_freq` only from the 26 `instantaneous_irradiance` tags.
- Preserve instantaneous, accumulation, and meteorological labels in every table and plot.
- Parse the full SCADA tag from CSV header column B; CSV row column B is the numeric value. Never infer a parameter from a ZIP or CSV filename.
- Preserve `Acummulation` exactly in canonical accumulation names.
- Preserve raw timestamps and do not call a naive value UTC. Inter-arrival durations may be calculated before timezone semantics are settled.
- Process all CSV entries in a ZIP, record every zero-byte CSV, and preserve ZIP/CSV/row provenance.
- Never silently drop a corrupt ZIP, malformed populated row, conflicting timestamp, missing input, or reconciliation mismatch.
- Copy mounted Drive ZIPs to Colab VM-local storage before analysis and verify count, size, and SHA-256.
- Commit no raw plant data, OAuth material, token, rclone configuration, or credential.
- Build no model, baseline, production resampler, feature, or S0-3/S0-5 analysis.
- Use TDD for production behaviour: write a focused test, observe the intended failure, implement the minimum, and rerun the focused and relevant test sets.
- Use `apply_patch` for repository edits and stage exact paths only.
- Keep Gate M0, S0-2 acceptance, and S0-1 scheduled observation as separate status decisions.

---

## File Map

| Path | Responsibility |
|---|---|
| `requirements-cov.txt` | Exact characterisation, plotting, notebook, and test dependencies |
| `src/characterisation/__init__.py` | Stable public exports |
| `src/characterisation/cov_contract.py` | SCADA tag parser, EMI tuple validation, canonical aliases, classification |
| `src/characterisation/cov_ingest.py` | Inventory, hashing, ZIP/CSV parser, timestamp audit, ordering, duplicate/conflict handling |
| `src/characterisation/cov_stats.py` | Deadband, inter-arrival, active/flat, heartbeat, sibling-liveness, frequency decision |
| `src/characterisation/cov_artifacts.py` | CSV/JSON/PNG/Markdown rendering and artifact hashing |
| `src/characterisation/cov_cli.py` | End-to-end orchestration and command-line exit contract |
| `notebooks/S0_2_COV_Characterisation.ipynb` | Editable Colab/local runner with no analysis logic |
| `artifacts/phase0_cov/drive_inventory.csv` | Connector-observed Drive filename/size/ID baseline |
| `artifacts/phase0_cov/*` | Full measured evidence output |
| `docs/phase0_cov_characterisation.md` | Required S0-2 report |
| `configs/site_plts-ikn.yaml` | Data-backed `canonical_freq` when resolved |
| `tests/unit/test_cov_contract.py` | Parser, mapping, and classification tests |
| `tests/unit/test_cov_ingest.py` | Manifest, ZIP/CSV, timestamp, ordering, duplicate, and conflict tests |
| `tests/unit/test_cov_stats.py` | Deadband, cadence, heartbeat, sibling-liveness, and frequency tests |
| `tests/unit/test_cov_artifacts.py` | Deterministic schemas, report, plot, and hash tests |
| `tests/integration/test_cov_pipeline.py` | Synthetic CLI pipeline and strict-error contract |
| `tests/integration/test_cov_notebook.py` | Notebook configuration and local execution contract |

---

### Task 1: Tag Contract, EMI Mapping, and Parameter Classification

**Files:**
- Create: `requirements-cov.txt`
- Create: `src/characterisation/__init__.py`
- Create: `src/characterisation/cov_contract.py`
- Create: `tests/unit/test_cov_contract.py`

**Interfaces:**
- Produces: `CovContractError`, `ParameterClass`, `TagIdentity`, `parse_scada_tag(str) -> TagIdentity`, `canonicalise_parameter(str, str) -> tuple[str, ParameterClass, str | None]`.
- Consumed by: ingestion, statistics, artifacts, and CLI tasks.

- [ ] **Step 1: Write failing parser and mapping tests**

Create `tests/unit/test_cov_contract.py` with focused tests equivalent to:

```python
from __future__ import annotations

import pytest

from src.characterisation.cov_contract import (
    CovContractError,
    ParameterClass,
    parse_scada_tag,
)


def test_parser_reads_tag_header_not_filename() -> None:
    tag = "PLTS IKN / STS09 / WB09_EMI01 / MEAS / GLOBAL HORIZONTAL IRRADIANCE (GHI)"
    identity = parse_scada_tag(tag)
    assert identity.sts == "STS09"
    assert identity.wb == "WB09"
    assert identity.emi == "EMI01"
    assert identity.canonical_parameter == "Global Horizontal Irradiance (GHI)"
    assert identity.parameter_class is ParameterClass.INSTANTANEOUS_IRRADIANCE
    assert identity.channel_group == "GHI"


@pytest.mark.parametrize(
    ("raw_parameter", "canonical", "parameter_class", "channel"),
    [
        ("DHI DAILY ACCUM", "DHI Daily Acummulation", ParameterClass.IRRADIANCE_ACCUMULATION, None),
        ("DIRECT HORIZONTAL IRRADIANCE (DNI*cosZ)", "Direct Horizontal Irradiance (DNIcosZ)", ParameterClass.INSTANTANEOUS_IRRADIANCE, "DNIcosZ"),
        ("IN-PLANE REAR-SIDE IRRADIANCE (RSI) 03", "In-Plane Rear-Side Irradiance (RSI) 03", ParameterClass.INSTANTANEOUS_IRRADIANCE, "RSI"),
    ],
)
def test_emi01_to_emi04_canonical_mapping(
    raw_parameter: str,
    canonical: str,
    parameter_class: ParameterClass,
    channel: str | None,
) -> None:
    identity = parse_scada_tag(f"PLTS IKN / STS05 / WB05_EMI02 / MEAS / {raw_parameter}")
    assert (identity.canonical_parameter, identity.parameter_class, identity.channel_group) == (
        canonical, parameter_class, channel
    )


@pytest.mark.parametrize(
    ("raw_parameter", "canonical", "parameter_class", "channel"),
    [
        ("Total Irradiance", "Global Horizontal Irradiance (GHI)", ParameterClass.INSTANTANEOUS_IRRADIANCE, "GHI"),
        ("Daily radiation", "GHI Daily Acummulation", ParameterClass.IRRADIANCE_ACCUMULATION, None),
    ],
)
def test_emi05_aliases(raw_parameter, canonical, parameter_class, channel) -> None:
    identity = parse_scada_tag(f"PLTS IKN / STS02 / WB02_EMI05 / MEAS / {raw_parameter}")
    assert (identity.canonical_parameter, identity.parameter_class, identity.channel_group) == (
        canonical, parameter_class, channel
    )


def test_mismatched_emi_tuple_is_rejected() -> None:
    with pytest.raises(CovContractError, match="EMI01 expects STS09/WB09"):
        parse_scada_tag("PLTS IKN / STS05 / WB05_EMI01 / MEAS / WIND SPEED")


def test_unknown_irradiance_like_parameter_is_rejected() -> None:
    with pytest.raises(CovContractError, match="unknown irradiance-like"):
        parse_scada_tag("PLTS IKN / STS09 / WB09_EMI01 / MEAS / NEW IRRADIANCE")


def test_unknown_non_irradiance_parameter_is_preserved_as_meteorological() -> None:
    identity = parse_scada_tag("PLTS IKN / STS09 / WB09_EMI01 / MEAS / PRESSURE")
    assert identity.canonical_parameter == "PRESSURE"
    assert identity.parameter_class is ParameterClass.METEOROLOGICAL
    assert identity.channel_group is None
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/unit/test_cov_contract.py -q`

Expected: collection fails because `src.characterisation.cov_contract` does not exist. The failure must be the missing production module, not a syntax or fixture error.

- [ ] **Step 3: Add dependencies and implement the minimum contract**

Create `requirements-cov.txt` with:

```text
pandas==3.0.2
numpy==2.4.4
matplotlib==3.10.9
PyYAML==6.0.3
pytest==9.0.3
nbformat==5.10.4
nbclient==0.10.2
```

Implement:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class CovContractError(ValueError):
    pass


class ParameterClass(StrEnum):
    INSTANTANEOUS_IRRADIANCE = "instantaneous_irradiance"
    IRRADIANCE_ACCUMULATION = "irradiance_accumulation"
    METEOROLOGICAL = "meteorological"


@dataclass(frozen=True)
class TagIdentity:
    full_tag: str
    site_label: str
    sts: str
    wb: str
    emi: str
    raw_parameter: str
    canonical_parameter: str
    parameter_class: ParameterClass
    channel_group: str | None


EMI_LOCATIONS = {
    "EMI01": ("STS09", "WB09"),
    "EMI02": ("STS05", "WB05"),
    "EMI03": ("STS06", "WB06"),
    "EMI04": ("STS04", "WB04"),
    "EMI05": ("STS02", "WB02"),
}

INSTANTANEOUS = {
    "DIFFUSE HORIZONTAL IRRADIANCE (DHI)": ("Diffuse Horizontal Irradiance (DHI)", "DHI"),
    "DIRECT HORIZONTAL IRRADIANCE (DNI*COSZ)": ("Direct Horizontal Irradiance (DNIcosZ)", "DNIcosZ"),
    "GLOBAL HORIZONTAL IRRADIANCE (GHI)": ("Global Horizontal Irradiance (GHI)", "GHI"),
    "GLOBAL INCLINED IRRADIANCE (POA)": ("Global Inclined Irradiance (POA)", "POA"),
    "IN-PLANE REAR-SIDE IRRADIANCE (RSI) 01": ("In-Plane Rear-Side Irradiance (RSI) 01", "RSI"),
    "IN-PLANE REAR-SIDE IRRADIANCE (RSI) 02": ("In-Plane Rear-Side Irradiance (RSI) 02", "RSI"),
    "IN-PLANE REAR-SIDE IRRADIANCE (RSI) 03": ("In-Plane Rear-Side Irradiance (RSI) 03", "RSI"),
}

ACCUMULATION_BASES = {
    "DHI": "DHI",
    "DNI*COSZ": "DNIcosZ",
    "GHI": "GHI",
    "POA": "POA",
}

TAG_PATTERN = re.compile(
    r"^\s*(PLTS IKN)\s*/\s*(STS\d{2})\s*/\s*(WB\d{2})_(EMI\d{2})\s*/\s*MEAS\s*/\s*(.+?)\s*$",
    re.IGNORECASE,
)


def canonicalise_parameter(emi: str, raw_parameter: str):
    normalized = " ".join(raw_parameter.split())
    key = normalized.upper()
    if emi == "EMI05":
        if key == "TOTAL IRRADIANCE":
            return "Global Horizontal Irradiance (GHI)", ParameterClass.INSTANTANEOUS_IRRADIANCE, "GHI"
        if key == "DAILY RADIATION":
            return "GHI Daily Acummulation", ParameterClass.IRRADIANCE_ACCUMULATION, None
    if key in INSTANTANEOUS:
        canonical, channel = INSTANTANEOUS[key]
        return canonical, ParameterClass.INSTANTANEOUS_IRRADIANCE, channel
    match = re.fullmatch(r"(DHI|DNI\*COSZ|GHI|POA) (DAILY|MONTHLY|YEARLY) ACCUM", key)
    if match:
        base, period = match.groups()
        return f"{ACCUMULATION_BASES[base]} {period.title()} Acummulation", ParameterClass.IRRADIANCE_ACCUMULATION, None
    match = re.fullmatch(r"RSI (DAILY|MONTHLY|YEARLY) ACCUM (01|02|03)", key)
    if match:
        period, sensor = match.groups()
        return f"RSI {sensor} {period.title()} Acummulation", ParameterClass.IRRADIANCE_ACCUMULATION, None
    if any(word in key for word in ("IRRADIANCE", "RADIATION", "DHI", "DNI", "GHI", "POA", "RSI")):
        raise CovContractError(f"unknown irradiance-like parameter: {raw_parameter}")
    return normalized, ParameterClass.METEOROLOGICAL, None


def parse_scada_tag(full_tag: str) -> TagIdentity:
    match = TAG_PATTERN.fullmatch(full_tag)
    if not match:
        raise CovContractError(f"invalid SCADA tag: {full_tag}")
    site, sts, wb, emi, raw_parameter = match.groups()
    sts, wb, emi = sts.upper(), wb.upper(), emi.upper()
    expected = EMI_LOCATIONS.get(emi)
    if expected is None:
        raise CovContractError(f"unknown EMI: {emi}")
    if (sts, wb) != expected:
        raise CovContractError(f"{emi} expects {expected[0]}/{expected[1]}")
    canonical, parameter_class, channel = canonicalise_parameter(emi, raw_parameter)
    return TagIdentity(full_tag, site.upper(), sts, wb, emi, raw_parameter, canonical, parameter_class, channel)
```

Export the public types/functions from `src/characterisation/__init__.py`.

- [ ] **Step 4: Verify GREEN and contract coverage**

Run: `python -m pytest tests/unit/test_cov_contract.py -q`

Expected: all contract tests pass.

- [ ] **Step 5: Commit Task 1**

Stage the four exact paths and commit: `feat: add COV tag contract`.

---

### Task 2: Source Manifest and ZIP/CSV Ingestion

**Files:**
- Create: `src/characterisation/cov_ingest.py`
- Create: `tests/unit/test_cov_ingest.py`

**Interfaces:**
- Consumes: `parse_scada_tag` and `TagIdentity`.
- Produces: `IngestionResult`, `ReconciliationResult`, `build_source_manifest(Path)`, `reconcile_inventory(pd.DataFrame, Path)`, `ingest_cov_directory(Path)`, and stable dataframe schemas for later tasks.

- [ ] **Step 1: Write failing manifest, multi-CSV, empty, and provenance tests**

Use `tmp_path`, `zipfile.ZipFile`, and a helper that writes semicolon CSV bytes. Tests must assert:

```python
result = ingest_cov_directory(tmp_path)
assert result.source_manifest[["zip_name", "csv_entry_count"]].to_dict("records") == [
    {"zip_name": "trends_export_1.zip", "csv_entry_count": 2}
]
assert result.empty_entries["source_csv"].tolist() == ["empty.csv"]
assert result.events[["source_zip", "source_csv", "source_row"]].to_dict("records") == [
    {"source_zip": "trends_export_1.zip", "source_csv": "data.csv", "source_row": 2}
]
assert result.events.loc[0, "value"] == 445.799988
assert result.events.loc[0, "object_caeid_raw"] == "0"
assert result.events.loc[0, "full_tag"].endswith("Total Irradiance")
```

Add separate tests for SHA-256 stability, malformed width, non-numeric value, invalid timestamp, and an unreadable ZIP.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/unit/test_cov_ingest.py -q`

Expected: import fails because `cov_ingest` does not exist.

- [ ] **Step 3: Implement manifest and row ingestion**

Implement immutable result metadata and dataframe-returning functions:

```python
@dataclass(frozen=True)
class IngestionResult:
    events: pd.DataFrame
    source_manifest: pd.DataFrame
    empty_entries: pd.DataFrame
    row_exceptions: pd.DataFrame
    timestamp_audit: pd.DataFrame
    strict_errors: tuple[str, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_source_manifest(raw_dir: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(raw_dir.glob("*.zip"), key=lambda item: item.name):
        with zipfile.ZipFile(path) as archive:
            csv_entries = [entry for entry in archive.infolist() if entry.filename.lower().endswith(".csv")]
            rows.append({
                "zip_name": path.name,
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
                "csv_entry_count": len(csv_entries),
                "populated_csv_count": sum(entry.file_size > 0 for entry in csv_entries),
                "empty_csv_count": sum(entry.file_size == 0 for entry in csv_entries),
                "uncompressed_csv_bytes": sum(entry.file_size for entry in csv_entries),
            })
    return pd.DataFrame(rows).sort_values("zip_name", kind="stable").reset_index(drop=True)
```

`ingest_cov_directory` must open every CSV entry, parse its three-field header with `csv.reader(delimiter=";")`, identify the full tag from header field two, parse all rows, preserve exceptions, and categorize repeated string columns after concatenation to keep the 2.65-million-row dataset memory-bounded.

- [ ] **Step 4: Add timestamp-shape, ordering, duplicate, and conflict behaviour**

Implement `classify_timestamp_text` with explicit regex checks for naive, offset, and Z forms. Parse homogeneous naive series without timezone and homogeneous offset/Z series with `utc=True`. Record mixed shapes as strict errors.

Before sorting, count negative within-entry time differences. After concatenation:

1. stable-sort by full tag, parsed time, ZIP, CSV, and row;
2. remove exact duplicates on tag/time/value/object;
3. find tag/time groups with more than one value or object;
4. quarantine every conflicted group from `events`; and
5. append each conflicting source row to `row_exceptions`.

Ordering violations remain evidence, not strict failures. Populated-row exclusions and conflicts become `strict_errors`.

- [ ] **Step 5: Verify GREEN and run Task 1+2 tests**

Run:

```powershell
python -m pytest tests/unit/test_cov_contract.py tests/unit/test_cov_ingest.py -q
```

Expected: all focused tests pass with no warnings.

- [ ] **Step 6: Commit Task 2**

Stage the two exact paths and commit: `feat: ingest raw COV ZIP exports`.

---

### Task 3: Per-Tag Deadband, Cadence, Gap, and Heartbeat Statistics

**Files:**
- Create: `src/characterisation/cov_stats.py`
- Create: `tests/unit/test_cov_stats.py`

**Interfaces:**
- Consumes: canonical event dataframe from `IngestionResult.events`.
- Produces: `DeadbandEstimate`, `HeartbeatEstimate`, `CanonicalFrequencyDecision`, `characterise_tags(pd.DataFrame)`, and `decide_canonical_frequency(pd.DataFrame) -> tuple[CanonicalFrequencyDecision, pd.DataFrame]`.

- [ ] **Step 1: Write failing known-deadband and inter-arrival tests**

Construct deterministic frames with known timestamps/values. Assert:

```python
estimate = estimate_deadband(np.array([0.099998, 0.100000, 0.100006] * 20 + [0.01]))
assert estimate.value == pytest.approx(0.1, abs=2e-5)
assert estimate.support == 60
assert estimate.lower_anomaly_count == 1

known_frame = pd.DataFrame(
    {
        "event_time": pd.to_datetime(
            [
                "2026-06-01 06:00:00",
                "2026-06-01 06:00:10",
                "2026-06-01 06:00:20",
                "2026-06-01 06:00:30",
                "2026-06-01 06:01:30",
            ]
        ),
        "value": [0.0, 0.1, 0.2, 0.2, 0.3],
        "parameter_class": ["instantaneous_irradiance"] * 5,
    }
)
stats = characterise_tag(known_frame)
assert stats["interarrival_p50_s"] == 10.0
assert stats["interarrival_p90_s"] == pytest.approx(45.0)
assert stats["interarrival_p99_s"] == pytest.approx(58.5)
assert stats["max_gap_s"] == 60.0
assert stats["zero_change_count"] == 1
assert stats["nonzero_change_count"] == 3
```

Add tests for insufficient positive deltas, active versus flat intervals, stable heartbeat, unstable heartbeat, maximum active-gap endpoints, and sibling events during that gap.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/unit/test_cov_stats.py -q`

Expected: import fails because `cov_stats` does not exist.

- [ ] **Step 3: Implement delta clustering and deadband confidence**

Implement a reusable adjacent-cluster helper and the exact approved thresholds:

```python
def _clusters(values: np.ndarray, *, rtol: float, atol: float) -> list[np.ndarray]:
    ordered = np.sort(np.asarray(values, dtype="float64"))
    if ordered.size == 0:
        return []
    groups: list[list[float]] = [[float(ordered[0])]]
    for value in ordered[1:]:
        if np.isclose(value, groups[-1][-1], rtol=rtol, atol=atol):
            groups[-1].append(float(value))
        else:
            groups.append([float(value)])
    return [np.asarray(group, dtype="float64") for group in groups]


def estimate_deadband(positive_deltas: np.ndarray) -> DeadbandEstimate:
    positive = np.asarray(positive_deltas, dtype="float64")
    positive = positive[np.isfinite(positive) & (positive > 0)]
    minimum_support = max(20, math.ceil(0.001 * positive.size))
    for index, cluster in enumerate(_clusters(positive, rtol=5e-4, atol=1e-6)):
        if cluster.size < minimum_support:
            continue
        value = float(np.median(cluster))
        mad = float(np.median(np.abs(cluster - value)))
        relative_mad = mad / value if value else math.inf
        support_fraction = cluster.size / positive.size
        confidence = "high" if support_fraction >= 0.05 and relative_mad <= 0.01 else (
            "medium" if support_fraction >= 0.01 and relative_mad <= 0.05 else "low"
        )
        lower_count = sum(group.size for group in _clusters(positive, rtol=5e-4, atol=1e-6)[:index])
        return DeadbandEstimate(value, int(cluster.size), support_fraction, relative_mad, confidence, lower_count, None)
    return DeadbandEstimate(None, 0, 0.0, None, "unresolved", 0, "insufficient supported lower-edge cluster")
```

Compute min/p01/p05/p50/p90/p99 independently from the accepted cluster so the full distribution remains visible.

- [ ] **Step 4: Implement tag cadence, active/flat, heartbeat, and sibling liveness**

For each tag, calculate durations from consecutive sorted valid events. For instantaneous irradiance, use `max(5 * deadband, 5.0)` as the active threshold, falling back to 5.0 when deadband is unresolved.

Heartbeat uses same-value intervals, clusters them with `rtol=0.02` and `atol=1.0`, selects the largest cluster, and accepts only at support >=20, support fraction >=0.10, and coefficient of variation <=0.10.

For the maximum active gap, store its start/end. Count sibling instantaneous events in the same EMI during the open interval using `numpy.searchsorted` against each sibling's sorted nanosecond timestamps.

Return one stable row for every input tag, even when metrics are unresolved.

- [ ] **Step 5: Write and verify the canonical-frequency decision tests**

Create tag-stat fixtures covering GHI, DHI, DNIcosZ, POA, and RSI. Assert:

```python
decision, evidence = decide_canonical_frequency(tag_stats)
assert decision.canonical_freq == "1min"
assert decision.decision_statistic_s == 45.0
assert set(decision.channel_medians_s) == {"GHI", "DHI", "DNIcosZ", "POA", "RSI"}
assert set(evidence["scope"]) == {"tag", "channel", "decision"}
```

Add a 5-minute outcome, a 15-minute outcome, a missing-channel unresolved outcome, and a >15-minute unresolved outcome. Verify that accumulation and meteorological rows never enter channel medians.

- [ ] **Step 6: Verify GREEN and run all COV unit tests**

Run: `python -m pytest tests/unit/test_cov_contract.py tests/unit/test_cov_ingest.py tests/unit/test_cov_stats.py -q`

Expected: all focused tests pass.

- [ ] **Step 7: Commit Task 3**

Stage the two exact paths and commit: `feat: characterise COV cadence and deadband`.

---

### Task 4: Deterministic Evidence Artifacts and Markdown Report

**Files:**
- Create: `src/characterisation/cov_artifacts.py`
- Create: `tests/unit/test_cov_artifacts.py`

**Interfaces:**
- Consumes: ingestion tables, tag statistics, `CanonicalFrequencyDecision`, and reference Drive inventory.
- Produces: `CovArtifactBundle`, `CovArtifactResult`, `write_cov_artifacts(CovArtifactBundle, Path) -> CovArtifactResult`, deterministic CSV/PNG/JSON files, `docs/phase0_cov_characterisation.md`, and the manifest SHA printed by the caller.

- [ ] **Step 1: Write failing artifact schema and determinism tests**

Use small synthetic tables and two fresh output directories. Assert exact filenames, CSV columns, sorted row order, identical bytes between runs, five non-empty PNGs, stable Markdown headings, and manifest hashes for every artifact except `run_manifest.json` itself.

Required assertions include:

```python
first = write_cov_artifacts(bundle, first_dir)
second = write_cov_artifacts(bundle, second_dir)
for relative_path in EXPECTED_ARTIFACTS:
    assert (first_dir / relative_path).read_bytes() == (second_dir / relative_path).read_bytes()
manifest = json.loads((first_dir / "run_manifest.json").read_text(encoding="utf-8"))
assert "run_manifest.json" not in manifest["artifact_sha256"]
assert set(manifest["artifact_sha256"]) == set(EXPECTED_ARTIFACTS) - {"run_manifest.json"}
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m pytest tests/unit/test_cov_artifacts.py -q`

Expected: import fails because `cov_artifacts` does not exist.

- [ ] **Step 3: Implement stable CSV/JSON/PNG writers**

Write CSV with UTF-8, LF, `index=False`, `lineterminator="\n"`, `float_format="%.9g"`, and explicit sorting keys. Write JSON with `sort_keys=True`, `indent=2`, `ensure_ascii=False`, and a final newline.

Use Matplotlib's non-interactive `Agg` backend, fixed figure sizes, fixed colors, and:

```python
figure.savefig(
    path,
    dpi=140,
    bbox_inches="tight",
    metadata={"Software": "Forecasting-Irradiance"},
)
```

Generate the five approved figures even when a panel has no supported estimate; render an explicit `insufficient evidence` annotation instead of failing.

- [ ] **Step 4: Implement Markdown rendering and artifact manifest**

Render the executive decision, reconciliation, schema correction, timestamp evidence, methods, heartbeat outcome, frequency evidence, exceptions, and all 136 per-tag rows from the same tables written to CSV.

After all non-manifest artifacts exist, hash each one and write `run_manifest.json`. Return a result object containing `manifest_path`, `manifest_sha256`, `report_path`, and `artifact_paths`.

- [ ] **Step 5: Verify GREEN and run all COV unit tests**

Run: `python -m pytest tests/unit/test_cov_contract.py tests/unit/test_cov_ingest.py tests/unit/test_cov_stats.py tests/unit/test_cov_artifacts.py -q`

Expected: all focused tests pass and the repeated-output byte comparison is green.

- [ ] **Step 6: Commit Task 4**

Stage the two exact paths and commit: `feat: render COV evidence artifacts`.

---

### Task 5: CLI Composition, Reconciliation, and Synthetic End-to-End Gate

**Files:**
- Create: `src/characterisation/cov_cli.py`
- Create: `tests/integration/test_cov_pipeline.py`
- Create: `artifacts/phase0_cov/drive_inventory.csv`

**Interfaces:**
- Consumes: every library module from Tasks 1-4.
- Produces: `run_cov_characterisation(...) -> CovRunResult`, JSON summary on stdout, and process exit 0/2 according to source-integrity strictness.

- [ ] **Step 1: Write failing synthetic pipeline tests**

Build two ZIP fixtures with multiple entries, one empty entry, one order inversion, and all five instantaneous channel groups. Supply a reference inventory CSV. Assert the run writes every artifact, emits the selected frequency, records the empty entry, and exits cleanly despite the order inversion.

Add a separate size mismatch and conflicting-timestamp fixture. Assert artifacts are written but CLI returns exit code 2 and `strict_status` is `failed`.

- [ ] **Step 2: Run the focused integration test and verify RED**

Run: `python -m pytest tests/integration/test_cov_pipeline.py -q`

Expected: import fails because `cov_cli` does not exist.

- [ ] **Step 3: Implement reconciliation and CLI orchestration**

Implement:

```python
def run_cov_characterisation(
    raw_dir: Path,
    output_dir: Path,
    reference_inventory: Path,
    site_config: Path,
    *,
    strict: bool = True,
) -> CovRunResult:
    ingestion = ingest_cov_directory(raw_dir)
    reconciliation = reconcile_inventory(ingestion.source_manifest, reference_inventory)
    tag_stats = characterise_tags(ingestion.events)
    decision, frequency_evidence = decide_canonical_frequency(tag_stats)
    strict_errors = (*ingestion.strict_errors, *reconciliation.strict_errors)
    bundle = CovArtifactBundle(ingestion, reconciliation, tag_stats, decision, frequency_evidence, strict_errors)
    artifacts = write_cov_artifacts(bundle, output_dir)
    return CovRunResult(decision, strict_errors, artifacts)
```

CLI arguments are `--raw-dir`, `--output-dir`, `--reference-inventory`, `--site-config`, and `--diagnostic` (sets strict false). Print one sorted-key JSON summary. Return 2 only when strict mode is enabled and strict source errors exist; unresolved statistical evidence remains an acceptance blocker in the report, not a parser crash.

- [ ] **Step 4: Materialize the connector-observed Drive inventory**

Write `artifacts/phase0_cov/drive_inventory.csv` with columns `drive_file_id`, `zip_name`, and `byte_size`, sorted by ZIP name, using the 145 records returned by the Google Drive connector. Do not derive IDs from filenames and do not include local paths.

- [ ] **Step 5: Verify GREEN and run the complete COV test slice**

Run:

```powershell
python -m pytest tests/unit/test_cov_contract.py tests/unit/test_cov_ingest.py tests/unit/test_cov_stats.py tests/unit/test_cov_artifacts.py tests/integration/test_cov_pipeline.py -q
```

Expected: every COV test passes.

- [ ] **Step 6: Commit Task 5**

Stage the three exact paths and commit: `feat: add COV characterisation CLI`.

---

### Task 6: Colab Notebook Runner and Local Notebook Execution

**Files:**
- Create: `notebooks/S0_2_COV_Characterisation.ipynb`
- Create: `tests/integration/test_cov_notebook.py`

**Interfaces:**
- Consumes: `requirements-cov.txt`, the CLI module, Drive/raw paths, and reference inventory.
- Produces: a user-editable notebook that runs identically in Colab or local verification mode.

- [ ] **Step 1: Write the failing notebook contract test**

Test that the notebook exists, parses with `nbformat`, contains one cell tagged `parameters`, exposes `DRIVE_RAW_DATA_DIR`, `LOCAL_STAGE_DIR`, `OUTPUT_DIR`, `STRICT_MODE`, and `SKIP_DRIVE_MOUNT`, contains no credential-like keys, imports `run_cov_characterisation`, copies files with `shutil.copy2`, and has no function definition whose name begins with `estimate_`, `characterise_`, or `parse_scada_`.

Add a local-execution test that creates synthetic ZIP/reference inventory fixtures, injects environment overrides, and executes the notebook with `nbclient.NotebookClient(timeout=600, kernel_name="python3")`. Assert the final summary and artifacts exist.

- [ ] **Step 2: Install notebook dependencies and verify RED**

Run:

```powershell
python -m pip install -r requirements-cov.txt
python -m pytest tests/integration/test_cov_notebook.py -q
```

Expected after dependency installation: FAIL because the notebook file does not exist.

- [ ] **Step 3: Create the thin notebook**

Create these ordered cells:

1. Markdown scope/no-model warning.
2. Tagged editable parameter cell.
3. Runtime/environment detection and repository import path.
4. Conditional `google.colab.drive.mount('/content/drive')`.
5. Source enumeration, clean VM-local staging directory creation, `shutil.copy2`, and pre/post-copy SHA-256 verification.
6. `run_cov_characterisation(...)` invocation.
7. Summary dataframe and report display.
8. Five figure displays.
9. Optional artifact copy to Drive output.

Environment variables override the editable defaults so the test can run locally without modifying the notebook.

- [ ] **Step 4: Verify GREEN locally**

Run: `python -m pytest tests/integration/test_cov_notebook.py -q`

Expected: notebook contract and local execution tests pass.

- [ ] **Step 5: Commit Task 6**

Stage the notebook, notebook test, and dependency file if it changed; commit: `feat: add S0-2 Colab runner`.

---

### Task 7: Full 145-ZIP Execution and Evidence Review

**Files:**
- Generate/modify: `artifacts/phase0_cov/*`
- Generate: `docs/phase0_cov_characterisation.md`
- Modify tests/code only through a new failing regression test if the real data exposes a defect.

**Interfaces:**
- Consumes: local `raw_data`, Drive inventory baseline, site config, and committed code.
- Produces: measured S0-2 evidence and the actual `canonical_freq` decision.

- [ ] **Step 1: Run the strict full-data CLI**

Run:

```powershell
python -m src.characterisation.cov_cli --raw-dir raw_data --output-dir artifacts/phase0_cov --reference-inventory artifacts/phase0_cov/drive_inventory.csv --site-config configs/site_plts-ikn.yaml
```

Expected input coverage: 145 ZIPs, 170 CSV entries, 163 populated, 7 empty, 136 tags. Do not assume the exit code or frequency before reading the result.

- [ ] **Step 2: Audit actual source exceptions and statistical outcomes**

Read the JSON summary, exception ledger, timestamp audit, tag table, frequency evidence, and figures. Verify:

- every inventory count reconciles;
- row counts and excluded rows agree across tables;
- the 12 previously observed within-entry inversions are represented;
- all 136 tags are present exactly once;
- the 26/76/34 class split is confirmed or any discrepancy is explained;
- timestamp evidence is described without an unsupported UTC conversion;
- accumulation tags do not enter the frequency evidence; and
- heartbeat and deadband unresolved states are not coerced to numbers.

- [ ] **Step 3: Handle any real-data defect through TDD**

If the full run exposes an implementation defect, create the smallest synthetic failing regression test in the appropriate existing test file, observe RED, patch the production module, and rerun the focused test plus the full-data CLI. Data-quality findings are reported; they are not patched away.

- [ ] **Step 4: Execute the notebook locally against all 145 ZIPs**

Set the notebook environment overrides for local mode and execute it with `nbclient`. Verify its output artifact hashes match the CLI run for all deterministic artifacts.

- [ ] **Step 5: Commit Task 7 evidence**

Stage only generated evidence/report files and any TDD-backed correction. Confirm `raw_data/` remains ignored. Commit: `docs: add S0-2 COV evidence`.

---

### Task 8: Pin Config and Synchronize PRD, Master Context, and Roadmap

**Files:**
- Modify: `configs/site_plts-ikn.yaml`
- Modify: `PRD_Forecasting_Irradiance_ML.md`
- Modify: `MASTER_CONTEXT_Forecasting_Irradiance_ML.md`
- Modify: `ROADMAP_Forecasting_Irradiance_ML.md`
- Modify: `tests/unit/test_cov_artifacts.py` or add a focused config/status contract test.

**Interfaces:**
- Consumes: measured full-data report, frequency decision, heartbeat conclusion, and acceptance blockers.
- Produces: one consistent evidence-backed Sprint 0 ledger bundle.

- [ ] **Step 1: Write a failing config/status contract test**

The test reads the generated decision JSON/CSV, config YAML, and three normative documents. It asserts that a resolved `canonical_freq` matches config and appears consistently in all three ledgers. It also asserts that S0-2 is not marked complete when the report lists acceptance blockers.

- [ ] **Step 2: Run the focused test and verify RED**

Run the exact new test. Expected: FAIL because config/docs still hold the pre-S0-2 state.

- [ ] **Step 3: Apply the evidence-backed updates**

If the decision is resolved, update the YAML from the measured result:

```python
decision_value = measured_decision.canonical_freq
if decision_value is not None:
    site_config["site"]["canonical_freq"] = decision_value
```

Write `site_config` with `yaml.safe_dump(..., sort_keys=False)`. If unresolved, leave the config unpinned and document the blocker.

Update all three normative documents with:

- exact source and row counts;
- schema correction (tag in header, value in row column B);
- timestamp semantics outcome;
- deadband and cadence summary;
- observed heartbeat/configured max-report-time conclusion;
- the frequency decision and rule;
- artifact/report links;
- exact S0-2 status; and
- Gate M0 and Phase 1 status kept separate.

- [ ] **Step 4: Re-run the status contract and COV tests**

Run the focused status test, all COV unit/integration tests, and `git diff --check`.

Expected: all tests pass and the ledger values agree.

- [ ] **Step 5: Commit Task 8**

Stage the config, three Markdown documents, and test; commit: `docs: record S0-2 COV decision`.

---

### Task 9: Fresh Verification, S0-1 Observation Audit, and Dual-Remote Release

**Files:**
- Modify normative ledgers only if fresh S0-1 evidence changes its status.

**Interfaces:**
- Consumes: the complete working tree and live GitHub/Drive schedule evidence.
- Produces: verified commits with identical `main` SHA on `origin` and `mirror`.

- [ ] **Step 1: Run fresh complete verification**

Run:

```powershell
python -m pytest -q
python -m src.characterisation.cov_cli --raw-dir raw_data --output-dir artifacts/phase0_cov --reference-inventory artifacts/phase0_cov/drive_inventory.csv --site-config configs/site_plts-ikn.yaml
git diff --check
git status --short
```

Read full outputs and record the exact test count, CLI counts, decision, strict status, and worktree state.

- [ ] **Step 2: Recheck S0-1 scheduled observation evidence**

Use `gh run list`/`gh run view` on `ompltsikn/Forecasting-Irradiance` to identify workflow runs whose event is `schedule` and whose issue cycles were written after the 2026-07-17 05:40 UTC Shared Drive cutover. Verify destination manifests/read-back. Count only two successive six-hour issue cycles; exclude manual and pre-cutover runs.

If the evidence changes S0-1 status, update all affected normative ledgers, run the relevant tests/diff checks, and commit that evidence separately. Otherwise report the unchanged blocker.

- [ ] **Step 3: Inspect release scope and secret hygiene**

Run `git status`, `git diff HEAD^`, `git ls-files raw_data`, and targeted secret-pattern scans. Confirm no raw data, notebook outputs containing credentials, Drive tokens, rclone config, `.env`, or client-secret files are tracked.

- [ ] **Step 4: Push and verify canonical remote**

Push `main` to `origin`. Query `refs/heads/main` and verify it equals local `HEAD`.

- [ ] **Step 5: Push and verify mirror remote**

Push the same `main` to `mirror`. Query `refs/heads/main` on both remotes and verify both equal local `HEAD`.

- [ ] **Step 6: Final handoff**

Report:

- S0-2 acceptance status and exact blocker if yellow;
- canonical-frequency decision and key per-channel evidence;
- source/row/tag/empty/exception counts;
- configured versus observed heartbeat distinction;
- timestamp-semantics conclusion;
- test count and notebook/full-data verification;
- S0-1 observation-gate status;
- Gate M0 count and Phase 1 NO-GO state;
- commit SHA and both verified remote SHAs; and
- the next exact Sprint 0 scope without proposing a model.
