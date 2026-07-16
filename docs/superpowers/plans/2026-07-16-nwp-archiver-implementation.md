# S0-1 NWP Archiver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and start an idempotent ECMWF Open Data IFS + AIFS Single site-point archiver that writes audit-ready Parquet to Google Drive with separate issue, valid, and retrieval timestamps.

**Architecture:** A typed Python module discovers and retrieves explicit ECMWF issue cycles, decodes the nearest PLTS-IKN grid point with ecCodes, normalizes accumulated fields, validates a canonical dataframe, and creates an atomic local Parquet/manifest attempt. A shell launcher and GitHub Actions workflow own rclone, committed-manifest discovery, data-first/manifest-last upload, read-back verification, scheduling, and credential cleanup.

**Tech Stack:** Python 3.12, `ecmwf-opendata==0.3.30`, `eccodes==2.47.0`, `pandas==3.0.2`, `pyarrow==24.0.0`, `PyYAML==6.0.3`, `pytest==9.0.3`, rclone `1.74.4`, GitHub Actions, Google Drive.

## Global Constraints

- Treat `PRD_Forecasting_Irradiance_ML.md`, `MASTER_CONTEXT_Forecasting_Irradiance_ML.md`, `ROADMAP_Forecasting_Irradiance_ML.md`, and `docs/superpowers/specs/2026-07-16-nwp-archiver-design.md` as one contract.
- Build no forecasting model, MOS, separation model, interpolation, or ERA5 substitution in Sprint 0.
- Use ECMWF Open Data source `google`, model names `ifs` and `aifs-single`, resolution `0p25`, stream `oper`, type `fc`, and surface fields only.
- Archive the issue-specific IFS horizon and AIFS Single steps `0..144` every 6 hours; smoke retrieves an SSRD predecessor plus +48 h and publishes only +48 h.

## Execution correction (2026-07-16): IFS Cycle 50r1 horizons

The original plan treated every IFS issue as if it exposed steps `0..144`.
ECMWF's current real-time contract is issue-cycle dependent: 00/12 UTC IFS
issues expose `0..144` every 3 hours, while 06/18 UTC issues expose `0..90`
every 3 hours. AIFS Single remains `0..144` every 6 hours for all four cycles.
The authoritative schedule is:
https://confluence.ecmwf.int/spaces/DAC/pages/272310539/ECMWF+open+data+real-time+forecasts+from+IFS+and+AIFS

This erratum supersedes later IFS snippets that call
`request_profile_for(IFS, FULL)` without an explicit issue time when constructing
an archive request. Discovery must use the common IFS `0..90` inventory so a
latest 06/18 issue can be found. After discovery, profile selection receives the
exact issue time and chooses `0..144` for 00/12 or `0..90` for 06/18. Retrieval,
normalization, and manifest inventories must all use that same selected profile.
Non-synoptic explicit issue times are rejected. The smoke predecessor/+48
contract is unchanged.

- Never use unsupported client-side `area` cropping. Select the nearest grid point locally and store the actual grid coordinates and haversine distance.
- Store all timestamps as timezone-aware UTC. Keep `issue_time_utc`, `valid_time_utc`, and `retrieved_at_utc` as three independent columns.
- Keep Bronze append-only. Upload Parquet first and the complete manifest last; a run without a readable complete manifest is uncommitted.
- Never print, commit, cache, or upload the decoded rclone configuration. Keep `NWP_ARCHIVER_ENABLED=false` until smoke, full, read-back, and idempotency gates pass.
- The canonical GitHub repository is currently **public** and this plan includes exact site coordinates. Do not push any local commit until the user explicitly approves public disclosure or changes repository visibility.
- Preserve all unrelated untracked PRD/DOCX/image files. Remove only the user-approved zero-byte root `nwp_archiver.py` when the real module exists.
- Use TDD for every behavior: write one focused failing test, observe the intended failure, implement the minimum, rerun the targeted test, then run the relevant test file.
- Use `apply_patch` for repository file edits. Stage exact paths only; never stage the entire dirty working tree.

---

## File Map

| Path | Responsibility |
|---|---|
| `configs/site_plts-ikn.yaml` | Required PLTS-IKN site identity, coordinates, elevation, and timezone |
| `data_contracts/nwp_schema.py` | Canonical schema, primary key, validation, availability filtering, and manifest validation |
| `src/ingestion/nwp_archiver.py` | Profiles, cycle selection, ECMWF gateway, GRIB decode, unit conversion, local artifacts, and CLI |
| `scripts/start_nwp_archiver.sh` | Drive-aware orchestration for smoke/full/catchup/scheduled modes |
| `.github/workflows/nwp-archiver.yml` | Gated manual and hourly automation |
| `requirements-nwp.txt` | Exact Python dependency pins |
| `tests/conftest.py` | Shared deterministic site/run dataframe fixtures |
| `tests/unit/test_nwp_profiles.py` | Site config and exact model request profiles |
| `tests/unit/test_nwp_schema.py` | Dataframe and manifest contract tests |
| `tests/unit/test_nwp_cycles.py` | UTC, retained-window, and scheduled/catch-up selection tests |
| `tests/unit/test_units.py` | SSRD/precipitation de-accumulation and conversions |
| `tests/unit/test_nwp_artifact.py` | Partition, atomic Parquet, hash, and manifest tests |
| `tests/unit/test_nwp_gateway.py` | Explicit issue retrieval and post-download timestamp tests |
| `tests/unit/test_nwp_normalise.py` | Parameter completeness and canonical dataframe normalization |
| `tests/unit/test_nwp_cli.py` | Discovery, one-issue orchestration, CLI, and result-JSON contracts |
| `tests/unit/test_workflow_contract.py` | Static security/gating checks for launcher and workflow |
| `tests/leakage/test_nwp_issue_time.py` | Measured availability and no-future-NWP tests |
| `tests/integration/test_nwp_parquet.py` | Network-free synthetic GRIB to Parquet round trip |
| `README.md` | Quickstart, safety gates, and ECMWF attribution |

---

### Task 1: Package, Site Configuration, and Exact Request Profiles

**Files:**
- Create: `requirements-nwp.txt`
- Create: `configs/site_plts-ikn.yaml`
- Create: `src/__init__.py`
- Create: `src/ingestion/__init__.py`
- Create: `src/ingestion/nwp_archiver.py`
- Create: `tests/unit/test_nwp_profiles.py`

**Interfaces:**
- Produces: `NwpModel`, `ArchiveProfile`, `SitePoint`, `ParameterGroup`, `RequestProfile`, `load_site_point(Path)`, and `request_profile_for(NwpModel, ArchiveProfile)`.
- Consumed by: every later task.

- [ ] **Step 1: Write the failing profile/config tests**

Create `tests/unit/test_nwp_profiles.py`:

```python
from __future__ import annotations

import importlib
from datetime import datetime, timezone
from pathlib import Path

import pytest


MODULE_PATH = Path("src/ingestion/nwp_archiver.py")
UTC = timezone.utc


def load_archiver_module():
    assert MODULE_PATH.is_file(), "production module does not exist yet"
    importlib.invalidate_caches()
    return importlib.import_module("src.ingestion.nwp_archiver")


def test_site_config_loads_required_values() -> None:
    module = load_archiver_module()
    site = module.load_site_point(Path("configs/site_plts-ikn.yaml"))
    assert site == module.SitePoint(
        site_id="PLTS-IKN",
        latitude_deg=-0.9911713315158186,
        longitude_deg=116.63811127764585,
        elevation_m=85.0,
        timezone="Asia/Makassar",
    )


def test_site_config_rejects_null_required_value(tmp_path: Path) -> None:
    module = load_archiver_module()
    path = tmp_path / "site.yaml"
    path.write_text(
        "site:\n"
        "  site_id: PLTS-IKN\n"
        "  latitude_deg: null\n"
        "  longitude_deg: 116.63811127764585\n"
        "  elevation_m: 85\n"
        "  timezone: Asia/Makassar\n",
        encoding="utf-8",
    )
    with pytest.raises(module.SiteConfigError, match="latitude_deg"):
        module.load_site_point(path)


@pytest.mark.parametrize(("issue_hour", "last_step"), [(0, 144), (6, 90), (12, 144), (18, 90)])
def test_full_ifs_profile_is_issue_specific(
    issue_hour: int, last_step: int
) -> None:
    module = load_archiver_module()
    profile = module.request_profile_for(
        module.NwpModel.IFS,
        module.ArchiveProfile.FULL,
        issue_time_utc=datetime(2026, 7, 16, issue_hour, tzinfo=UTC),
    )
    assert profile.nwp_source == "ecmwf_ifs"
    assert profile.request_steps_h == tuple(range(0, last_step + 1, 3))
    assert profile.output_steps_h == tuple(range(0, last_step + 1, 3))
    assert profile.parameters == (
        "ssrd", "tcc", "2t", "2d", "10u", "10v", "tp", "sp", "tcwv", "mucape"
    )


def test_full_aifs_profile_is_exact() -> None:
    module = load_archiver_module()
    profile = module.request_profile_for(
        module.NwpModel.AIFS_SINGLE, module.ArchiveProfile.FULL
    )
    assert profile.nwp_source == "ecmwf_aifs_single"
    assert profile.request_steps_h == tuple(range(0, 145, 6))
    assert profile.output_steps_h == tuple(range(0, 145, 6))
    assert profile.parameters == (
        "ssrd", "tcc", "lcc", "mcc", "hcc", "2t", "2d", "10u", "10v", "tp", "sp", "cp"
    )


@pytest.mark.parametrize(
    ("model", "request_steps"),
    [("ifs", (45, 48)), ("aifs-single", (42, 48))],
)
def test_smoke_profile_retrieves_predecessor_but_outputs_only_48h(
    model: str, request_steps: tuple[int, ...]
) -> None:
    module = load_archiver_module()
    profile = module.request_profile_for(
        module.NwpModel(model), module.ArchiveProfile.SMOKE
    )
    assert profile.request_steps_h == request_steps
    assert profile.output_steps_h == (48,)
    assert profile.parameters == ("ssrd",)


@pytest.mark.parametrize("model", ["ifs", "aifs-single"])
def test_catchup_uses_the_full_inventory(model: str) -> None:
    module = load_archiver_module()
    full = module.request_profile_for(module.NwpModel(model), module.ArchiveProfile.FULL)
    catchup = module.request_profile_for(
        module.NwpModel(model), module.ArchiveProfile.CATCHUP
    )
    assert catchup == full
```

- [ ] **Step 2: Run the tests and observe the intended RED state**

Run:

```powershell
python -m pytest tests/unit/test_nwp_profiles.py -q
```

Expected: FAIL at `production module does not exist yet`. The failure must not be a typo or fixture error.

- [ ] **Step 3: Add the pinned dependencies and site configuration**

Create `requirements-nwp.txt`:

```text
ecmwf-opendata==0.3.30
eccodes==2.47.0
pandas==3.0.2
pyarrow==24.0.0
PyYAML==6.0.3
pytest==9.0.3
```

Create `configs/site_plts-ikn.yaml`:

```yaml
site:
  site_id: "PLTS-IKN"
  latitude_deg: -0.9911713315158186
  longitude_deg: 116.63811127764585
  elevation_m: 85.0
  timezone: "Asia/Makassar"
```

Create empty package markers `src/__init__.py` and `src/ingestion/__init__.py`.

- [ ] **Step 4: Implement the minimum profile/config module**

Create `src/ingestion/nwp_archiver.py` with:

```python
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml


class SiteConfigError(ValueError):
    pass


class NwpModel(StrEnum):
    IFS = "ifs"
    AIFS_SINGLE = "aifs-single"


class ArchiveProfile(StrEnum):
    SMOKE = "smoke"
    FULL = "full"
    CATCHUP = "catchup"


@dataclass(frozen=True)
class SitePoint:
    site_id: str
    latitude_deg: float
    longitude_deg: float
    elevation_m: float
    timezone: str


@dataclass(frozen=True)
class ParameterGroup:
    name: str
    parameters: tuple[str, ...]


@dataclass(frozen=True)
class RequestProfile:
    model: NwpModel
    nwp_source: Literal["ecmwf_ifs", "ecmwf_aifs_single"]
    request_steps_h: tuple[int, ...]
    output_steps_h: tuple[int, ...]
    groups: tuple[ParameterGroup, ...]

    @property
    def parameters(self) -> tuple[str, ...]:
        return tuple(parameter for group in self.groups for parameter in group.parameters)


IFS_GROUPS = (
    ParameterGroup("solar", ("ssrd", "tcc")),
    ParameterGroup("surface", ("2t", "2d", "10u", "10v", "sp")),
    ParameterGroup("water", ("tp", "tcwv")),
    ParameterGroup("convection", ("mucape",)),
)
AIFS_GROUPS = (
    ParameterGroup("solar", ("ssrd", "tcc", "lcc", "mcc", "hcc")),
    ParameterGroup("surface", ("2t", "2d", "10u", "10v", "sp")),
    ParameterGroup("water", ("tp", "cp")),
)


def load_site_point(config_path: Path) -> SitePoint:
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("site"), dict):
        raise SiteConfigError("site mapping is required")
    site = raw["site"]
    required = ("site_id", "latitude_deg", "longitude_deg", "elevation_m", "timezone")
    for key in required:
        if site.get(key) is None:
            raise SiteConfigError(f"{key} is required")
    try:
        result = SitePoint(
            site_id=str(site["site_id"]),
            latitude_deg=float(site["latitude_deg"]),
            longitude_deg=float(site["longitude_deg"]),
            elevation_m=float(site["elevation_m"]),
            timezone=str(site["timezone"]),
        )
        ZoneInfo(result.timezone)
    except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
        raise SiteConfigError(str(exc)) from exc
    if not -90.0 <= result.latitude_deg <= 90.0:
        raise SiteConfigError("latitude_deg must be in [-90, 90]")
    if not -180.0 <= result.longitude_deg <= 180.0:
        raise SiteConfigError("longitude_deg must be in [-180, 180]")
    return result


def request_profile_for(model: NwpModel, profile: ArchiveProfile) -> RequestProfile:
    if model is NwpModel.IFS:
        source: Literal["ecmwf_ifs", "ecmwf_aifs_single"] = "ecmwf_ifs"
        full_steps = tuple(range(0, 145, 3))
        groups = IFS_GROUPS
        smoke_steps = (45, 48)
    else:
        source = "ecmwf_aifs_single"
        full_steps = tuple(range(0, 145, 6))
        groups = AIFS_GROUPS
        smoke_steps = (42, 48)
    if profile is ArchiveProfile.SMOKE:
        return RequestProfile(
            model=model,
            nwp_source=source,
            request_steps_h=smoke_steps,
            output_steps_h=(48,),
            groups=(ParameterGroup("solar", ("ssrd",)),),
        )
    return RequestProfile(
        model=model,
        nwp_source=source,
        request_steps_h=full_steps,
        output_steps_h=full_steps,
        groups=groups,
    )
```

- [ ] **Step 5: Verify GREEN and commit Task 1**

Run:

```powershell
python -m pytest tests/unit/test_nwp_profiles.py -q
```

Expected: `8 passed`.

Then stage only Task 1 paths and commit:

```powershell
git add requirements-nwp.txt configs/site_plts-ikn.yaml src/__init__.py src/ingestion/__init__.py src/ingestion/nwp_archiver.py tests/unit/test_nwp_profiles.py
git diff --cached --check
git commit -m "feat: define NWP archive profiles"
```

---

### Task 2: Canonical Dataframe Contract and Measured Availability

**Files:**
- Create: `data_contracts/__init__.py`
- Create: `data_contracts/nwp_schema.py`
- Create: `tests/conftest.py`
- Create: `tests/unit/test_nwp_schema.py`
- Create: `tests/leakage/test_nwp_issue_time.py`

**Interfaces:**
- Produces: `NWP_SCHEMA_VERSION`, `NWP_PRIMARY_KEY`, `NWP_COLUMNS`, `NwpContractError`, `validate_nwp_frame(pd.DataFrame)`, `canonicalize_nwp_frame(pd.DataFrame)`, and `available_nwp_as_of(pd.DataFrame, datetime)`.
- Consumed by: dataframe normalization, artifact writing, and leakage-safe downstream reads.

- [ ] **Step 1: Write the shared deterministic dataframe fixture**

Create `tests/conftest.py`:

```python
from __future__ import annotations

import pandas as pd
import pytest


@pytest.fixture
def valid_ifs_frame() -> pd.DataFrame:
    issue = pd.Timestamp("2026-07-16T06:00:00Z")
    retrieved = pd.Timestamp("2026-07-16T07:15:30Z")
    common = {
        "site_id": "PLTS-IKN",
        "nwp_provider": "ecmwf_opendata",
        "nwp_source": "ecmwf_ifs",
        "nwp_model": "ifs",
        "issue_time_utc": issue,
        "retrieved_at_utc": retrieved,
        "site_latitude": -0.9911713315158186,
        "site_longitude": 116.63811127764585,
        "grid_latitude": -1.0,
        "grid_longitude": 116.75,
        "grid_distance_km": 12.478274049682074,
        "grid_selection_method": "nearest",
        "lcc_frac": None,
        "mcc_frac": None,
        "hcc_frac": None,
        "cp_accum_m": None,
        "cp_interval_m": None,
        "cp_mm": None,
        "ecmwf_client_source": "google",
        "ecmwf_client_version": "0.3.30",
        "eccodes_version": "2.47.0",
        "schema_version": 1,
        "ecmwf_dataset_url": "https://www.ecmwf.int/en/forecasts/datasets/open-data",
        "licence_id": "CC-BY-4.0",
    }
    rows = [
        {
            **common,
            "valid_time_utc": issue,
            "lead_time_min": 0,
            "ssrd_wm2": None,
            "ssrd_accum_jm2": 0.0,
            "ssrd_interval_jm2": None,
            "ssrd_interval_seconds": 0,
            "ssrd_conversion_method": "lead_zero",
            "grib_start_step_h": 0,
            "grib_end_step_h": 0,
            "grib_step_type": "accum",
            "tcc_frac": 0.20,
            "t2m_c": 25.0,
            "d2m_c": 24.0,
            "u10_ms": 2.0,
            "v10_ms": -1.0,
            "tp_accum_m": 0.0,
            "tp_interval_m": None,
            "tp_mm": None,
            "sp_pa": 100000.0,
            "sp_hpa": 1000.0,
            "tcwv_kgm2": 30.0,
            "mucape_jkg": 400.0,
        },
        {
            **common,
            "valid_time_utc": issue + pd.Timedelta(hours=3),
            "lead_time_min": 180,
            "ssrd_wm2": 100.0,
            "ssrd_accum_jm2": 1_080_000.0,
            "ssrd_interval_jm2": 1_080_000.0,
            "ssrd_interval_seconds": 10_800,
            "ssrd_conversion_method": "run_total_difference",
            "grib_start_step_h": 0,
            "grib_end_step_h": 3,
            "grib_step_type": "accum",
            "tcc_frac": 0.25,
            "t2m_c": 26.85,
            "d2m_c": 25.0,
            "u10_ms": 2.5,
            "v10_ms": -1.0,
            "tp_accum_m": 0.0012,
            "tp_interval_m": 0.0012,
            "tp_mm": 1.2,
            "sp_pa": 100000.0,
            "sp_hpa": 1000.0,
            "tcwv_kgm2": 30.0,
            "mucape_jkg": 400.0,
        },
    ]
    return pd.DataFrame(rows)
```

- [ ] **Step 2: Write failing schema and leakage tests**

Create `tests/unit/test_nwp_schema.py`:

```python
from __future__ import annotations

import pandas as pd
import pytest

from data_contracts.nwp_schema import (
    NwpContractError,
    canonicalize_nwp_frame,
    validate_nwp_frame,
)


def test_valid_ifs_frame_satisfies_schema(valid_ifs_frame: pd.DataFrame) -> None:
    result = validate_nwp_frame(valid_ifs_frame)
    assert result.equals(valid_ifs_frame)


def test_duplicate_primary_key_is_rejected(valid_ifs_frame: pd.DataFrame) -> None:
    duplicate = pd.concat([valid_ifs_frame, valid_ifs_frame.iloc[[1]]], ignore_index=True)
    with pytest.raises(NwpContractError, match="duplicate primary key"):
        validate_nwp_frame(duplicate)


def test_lead_time_must_equal_valid_minus_issue(valid_ifs_frame: pd.DataFrame) -> None:
    invalid = valid_ifs_frame.copy()
    invalid.loc[1, "lead_time_min"] = 179
    with pytest.raises(NwpContractError, match="lead_time_min"):
        validate_nwp_frame(invalid)


@pytest.mark.parametrize("value", [-0.0001, 1.0001])
def test_cloud_fraction_out_of_bounds_is_rejected(
    valid_ifs_frame: pd.DataFrame, value: float
) -> None:
    invalid = valid_ifs_frame.copy()
    invalid.loc[1, "tcc_frac"] = value
    with pytest.raises(NwpContractError, match="tcc_frac"):
        validate_nwp_frame(invalid)


def test_source_model_pair_must_match(valid_ifs_frame: pd.DataFrame) -> None:
    invalid = valid_ifs_frame.copy()
    invalid["nwp_model"] = "aifs-single"
    with pytest.raises(NwpContractError, match="source/model"):
        validate_nwp_frame(invalid)


def test_grid_coordinates_are_constant_within_run(valid_ifs_frame: pd.DataFrame) -> None:
    invalid = valid_ifs_frame.copy()
    invalid.loc[1, "grid_longitude"] = 116.50
    with pytest.raises(NwpContractError, match="grid coordinates"):
        validate_nwp_frame(invalid)


def test_all_null_model_specific_columns_receive_stable_numeric_dtypes(
    valid_ifs_frame: pd.DataFrame,
) -> None:
    canonical = canonicalize_nwp_frame(valid_ifs_frame)
    for column in ("lcc_frac", "mcc_frac", "hcc_frac", "cp_accum_m", "cp_interval_m", "cp_mm"):
        assert str(canonical[column].dtype) == "Float64"
    for column in ("lead_time_min", "schema_version"):
        assert str(canonical[column].dtype) == "Int64"
```

Create `tests/leakage/test_nwp_issue_time.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from data_contracts.nwp_schema import (
    NwpContractError,
    available_nwp_as_of,
    validate_nwp_frame,
)


def test_three_timestamps_are_distinct_non_null_utc_columns(
    valid_ifs_frame: pd.DataFrame,
) -> None:
    validate_nwp_frame(valid_ifs_frame)
    for column in ("issue_time_utc", "valid_time_utc", "retrieved_at_utc"):
        assert str(valid_ifs_frame[column].dtype) == "datetime64[ns, UTC]"
        assert valid_ifs_frame[column].notna().all()
    assert valid_ifs_frame.loc[1, "issue_time_utc"] != valid_ifs_frame.loc[1, "valid_time_utc"]
    assert valid_ifs_frame.loc[1, "issue_time_utc"] != valid_ifs_frame.loc[1, "retrieved_at_utc"]


def test_naive_timestamp_is_rejected(valid_ifs_frame: pd.DataFrame) -> None:
    invalid = valid_ifs_frame.astype({"issue_time_utc": "object"}).copy()
    invalid["issue_time_utc"] = datetime(2026, 7, 16, 6, 0, 0)
    with pytest.raises(NwpContractError, match="UTC"):
        validate_nwp_frame(invalid)


def test_retrieval_before_issue_is_rejected(valid_ifs_frame: pd.DataFrame) -> None:
    invalid = valid_ifs_frame.copy()
    invalid["retrieved_at_utc"] = pd.Timestamp("2026-07-16T05:59:00Z")
    with pytest.raises(NwpContractError, match="retrieved_at_utc"):
        validate_nwp_frame(invalid)


def test_row_is_unavailable_one_second_before_retrieval(
    valid_ifs_frame: pd.DataFrame,
) -> None:
    result = available_nwp_as_of(
        valid_ifs_frame, datetime(2026, 7, 16, 7, 15, 29, tzinfo=timezone.utc)
    )
    assert result.empty


def test_future_valid_forecast_is_available_at_retrieval(
    valid_ifs_frame: pd.DataFrame,
) -> None:
    result = available_nwp_as_of(
        valid_ifs_frame, datetime(2026, 7, 16, 7, 15, 30, tzinfo=timezone.utc)
    )
    assert len(result) == 2
    assert result["valid_time_utc"].max() == pd.Timestamp("2026-07-16T09:00:00Z")
```

- [ ] **Step 3: Run the targeted tests and observe RED**

Run:

```powershell
python -m pytest tests/unit/test_nwp_schema.py tests/leakage/test_nwp_issue_time.py -q
```

Expected: collection fails because `data_contracts.nwp_schema` does not exist. Confirm the file path is the only missing behavior, then continue.

- [ ] **Step 4: Implement the canonical validator and availability filter**

Create empty `data_contracts/__init__.py`, then create `data_contracts/nwp_schema.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from typing import Final

import pandas as pd
from pandas.api.types import is_numeric_dtype


NWP_SCHEMA_VERSION: Final[int] = 1
NWP_PRIMARY_KEY: Final[tuple[str, ...]] = (
    "site_id", "nwp_source", "issue_time_utc", "valid_time_utc"
)
TIMESTAMP_COLUMNS: Final[tuple[str, ...]] = (
    "issue_time_utc", "valid_time_utc", "retrieved_at_utc"
)
CLOUD_COLUMNS: Final[tuple[str, ...]] = (
    "tcc_frac", "lcc_frac", "mcc_frac", "hcc_frac"
)
NUMERIC_COLUMNS: Final[tuple[str, ...]] = (
    "lead_time_min", "ssrd_wm2", "ssrd_accum_jm2", "ssrd_interval_jm2",
    "ssrd_interval_seconds", "tcc_frac", "lcc_frac", "mcc_frac", "hcc_frac",
    "t2m_c", "d2m_c", "u10_ms", "v10_ms", "tp_accum_m", "tp_interval_m",
    "tp_mm", "sp_pa", "sp_hpa", "tcwv_kgm2", "cp_accum_m", "cp_interval_m",
    "cp_mm", "mucape_jkg", "site_latitude",
    "site_longitude", "grid_latitude", "grid_longitude", "grid_distance_km",
    "grib_start_step_h", "grib_end_step_h", "schema_version",
)
NWP_COLUMNS: Final[tuple[str, ...]] = (
    "site_id", "nwp_provider", "nwp_source", "nwp_model", "issue_time_utc",
    "valid_time_utc", "retrieved_at_utc", "lead_time_min", "ssrd_wm2",
    "ssrd_accum_jm2", "ssrd_interval_jm2", "ssrd_interval_seconds",
    "ssrd_conversion_method", "grib_start_step_h", "grib_end_step_h",
    "grib_step_type", "tcc_frac", "lcc_frac", "mcc_frac", "hcc_frac",
    "t2m_c", "d2m_c", "u10_ms", "v10_ms", "tp_accum_m", "tp_interval_m",
    "tp_mm", "sp_pa", "sp_hpa", "tcwv_kgm2", "cp_accum_m", "cp_interval_m",
    "cp_mm", "mucape_jkg", "site_latitude",
    "site_longitude", "grid_latitude", "grid_longitude", "grid_distance_km",
    "grid_selection_method", "ecmwf_client_source", "ecmwf_client_version",
    "eccodes_version", "schema_version", "ecmwf_dataset_url", "licence_id",
)
NWP_INTEGER_COLUMNS: Final[tuple[str, ...]] = (
    "lead_time_min",
    "ssrd_interval_seconds",
    "grib_start_step_h",
    "grib_end_step_h",
    "schema_version",
)
NWP_FLOAT_COLUMNS: Final[tuple[str, ...]] = tuple(
    column for column in NUMERIC_COLUMNS if column not in NWP_INTEGER_COLUMNS
)
NWP_STRING_COLUMNS: Final[tuple[str, ...]] = tuple(
    column
    for column in NWP_COLUMNS
    if column not in TIMESTAMP_COLUMNS and column not in NUMERIC_COLUMNS
)
SOURCE_MODEL = {"ecmwf_ifs": "ifs", "ecmwf_aifs_single": "aifs-single"}


class NwpContractError(ValueError):
    pass


def _require_utc_dtype(frame: pd.DataFrame, column: str) -> None:
    dtype = frame[column].dtype
    if not isinstance(dtype, pd.DatetimeTZDtype) or str(dtype.tz) != "UTC":
        raise NwpContractError(f"{column} must use timezone-aware UTC dtype")


def validate_nwp_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in NWP_COLUMNS if column not in frame.columns]
    if missing:
        raise NwpContractError(f"missing columns: {missing}")
    for column in TIMESTAMP_COLUMNS:
        _require_utc_dtype(frame, column)
        if frame[column].isna().any():
            raise NwpContractError(f"{column} must be non-null")
    for column in NUMERIC_COLUMNS:
        if not is_numeric_dtype(frame[column]) and frame[column].notna().any():
            raise NwpContractError(f"{column} must be numeric")
    if frame[list(NWP_PRIMARY_KEY)].isna().any().any():
        raise NwpContractError("primary key must be non-null")
    if frame.duplicated(list(NWP_PRIMARY_KEY)).any():
        raise NwpContractError("duplicate primary key")
    expected_model = frame["nwp_source"].map(SOURCE_MODEL)
    if expected_model.isna().any() or (expected_model != frame["nwp_model"]).any():
        raise NwpContractError("source/model pair is invalid")
    expected_lead = (
        (frame["valid_time_utc"] - frame["issue_time_utc"]).dt.total_seconds() / 60
    ).astype("int64")
    if not expected_lead.equals(frame["lead_time_min"].astype("int64")):
        raise NwpContractError("lead_time_min does not match valid minus issue")
    if (frame["valid_time_utc"] < frame["issue_time_utc"]).any():
        raise NwpContractError("valid_time_utc precedes issue_time_utc")
    if (frame["retrieved_at_utc"] < frame["issue_time_utc"]).any():
        raise NwpContractError("retrieved_at_utc precedes issue_time_utc")
    for column in CLOUD_COLUMNS:
        valid = frame[column].dropna()
        if not valid.between(0.0, 1.0, inclusive="both").all():
            raise NwpContractError(f"{column} must be in [0, 1]")
    if (frame["grid_distance_km"] > 25.0).any() or (frame["grid_distance_km"] < 0).any():
        raise NwpContractError("grid_distance_km must be in [0, 25]")
    grouped = frame.groupby(["nwp_source", "issue_time_utc"], dropna=False)
    if grouped["grid_latitude"].nunique().max() != 1 or grouped["grid_longitude"].nunique().max() != 1:
        raise NwpContractError("grid coordinates must be constant within a run")
    if not (frame["schema_version"] == NWP_SCHEMA_VERSION).all():
        raise NwpContractError("schema_version mismatch")
    return frame


def canonicalize_nwp_frame(frame: pd.DataFrame) -> pd.DataFrame:
    validated = validate_nwp_frame(frame)
    canonical = validated.copy()
    for column in NWP_INTEGER_COLUMNS:
        canonical[column] = pd.to_numeric(canonical[column]).astype("Int64")
    for column in NWP_FLOAT_COLUMNS:
        canonical[column] = pd.to_numeric(canonical[column]).astype("Float64")
    for column in NWP_STRING_COLUMNS:
        canonical[column] = canonical[column].astype("string")
    return validate_nwp_frame(canonical)


def available_nwp_as_of(frame: pd.DataFrame, as_of_utc: datetime) -> pd.DataFrame:
    if as_of_utc.tzinfo is None or as_of_utc.utcoffset() != timezone.utc.utcoffset(as_of_utc):
        raise NwpContractError("as_of_utc must be timezone-aware UTC")
    validated = validate_nwp_frame(frame)
    return validated.loc[validated["retrieved_at_utc"] <= pd.Timestamp(as_of_utc)].copy()
```

- [ ] **Step 5: Verify GREEN and commit Task 2**

Run:

```powershell
python -m pytest tests/unit/test_nwp_schema.py tests/leakage/test_nwp_issue_time.py -q
```

Expected: `13 passed`.

Then:

```powershell
git add data_contracts/__init__.py data_contracts/nwp_schema.py tests/conftest.py tests/unit/test_nwp_schema.py tests/leakage/test_nwp_issue_time.py
git diff --cached --check
git commit -m "feat: validate raw NWP archive schema"
```

---

### Task 3: UTC Discipline, Retained Cycles, and Catch-up Selection

**Files:**
- Modify: `src/ingestion/nwp_archiver.py`
- Create: `tests/unit/test_nwp_cycles.py`
- Modify: `tests/leakage/test_nwp_issue_time.py`

**Interfaces:**
- Consumes: `NwpModel`, `ArchiveProfile`, `RequestProfile` from Task 1.
- Produces: `SelectionMode`, `require_utc(datetime)`, `enumerate_retained_cycles(datetime, timedelta)`, `select_uncommitted_cycles(...)`, and `measured_latency_minutes(datetime, datetime)`.

- [ ] **Step 1: Write failing cycle-selection tests**

Create `tests/unit/test_nwp_cycles.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.nwp_archiver import (
    SelectionMode,
    enumerate_retained_cycles,
    select_uncommitted_cycles,
)


UTC = timezone.utc
LATEST = datetime(2026, 7, 16, 6, tzinfo=UTC)
EXPECTED = (
    datetime(2026, 7, 13, 18, tzinfo=UTC),
    datetime(2026, 7, 14, 0, tzinfo=UTC),
    datetime(2026, 7, 14, 6, tzinfo=UTC),
    datetime(2026, 7, 14, 12, tzinfo=UTC),
    datetime(2026, 7, 14, 18, tzinfo=UTC),
    datetime(2026, 7, 15, 0, tzinfo=UTC),
    datetime(2026, 7, 15, 6, tzinfo=UTC),
    datetime(2026, 7, 15, 12, tzinfo=UTC),
    datetime(2026, 7, 15, 18, tzinfo=UTC),
    datetime(2026, 7, 16, 0, tzinfo=UTC),
    datetime(2026, 7, 16, 6, tzinfo=UTC),
)


def test_retained_window_is_inclusive_and_oldest_first() -> None:
    assert enumerate_retained_cycles(LATEST, timedelta(hours=60)) == EXPECTED


def test_only_synoptic_cycles_are_accepted() -> None:
    with pytest.raises(ValueError, match="00/06/12/18"):
        enumerate_retained_cycles(
            datetime(2026, 7, 16, 7, tzinfo=UTC), timedelta(hours=60)
        )


def test_catchup_filters_committed_and_preserves_oldest_first() -> None:
    missing = {EXPECTED[2], EXPECTED[-1]}
    committed = set(EXPECTED) - missing
    assert select_uncommitted_cycles(EXPECTED, committed, SelectionMode.CATCHUP) == (
        EXPECTED[2], EXPECTED[-1]
    )


def test_scheduled_selects_latest_then_oldest_missing() -> None:
    missing = {EXPECTED[2], EXPECTED[-1]}
    committed = set(EXPECTED) - missing
    assert select_uncommitted_cycles(EXPECTED, committed, SelectionMode.SCHEDULED) == (
        EXPECTED[-1], EXPECTED[2]
    )


def test_scheduled_does_not_duplicate_latest() -> None:
    committed = set(EXPECTED[:-1])
    assert select_uncommitted_cycles(EXPECTED, committed, SelectionMode.SCHEDULED) == (
        EXPECTED[-1],
    )


@pytest.mark.parametrize("mode", [SelectionMode.SMOKE, SelectionMode.FULL])
def test_manual_single_run_modes_select_latest_only(mode: SelectionMode) -> None:
    assert select_uncommitted_cycles(EXPECTED, set(), mode) == (EXPECTED[-1],)
```

Append these tests to `tests/leakage/test_nwp_issue_time.py`:

```python
from src.ingestion.nwp_archiver import measured_latency_minutes, require_utc


def test_measured_latency_uses_retrieval_minus_issue() -> None:
    issue = datetime(2026, 7, 16, 6, tzinfo=timezone.utc)
    retrieved = datetime(2026, 7, 16, 7, 15, 30, tzinfo=timezone.utc)
    assert measured_latency_minutes(issue, retrieved) == 75.5


def test_require_utc_rejects_naive_and_non_utc() -> None:
    with pytest.raises(ValueError, match="UTC"):
        require_utc(datetime(2026, 7, 16, 6))
    wita = timezone(timedelta(hours=8))
    with pytest.raises(ValueError, match="UTC"):
        require_utc(datetime(2026, 7, 16, 14, tzinfo=wita))
```

Also extend the existing datetime import in that file to include `timedelta`.

- [ ] **Step 2: Run the targeted tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/test_nwp_cycles.py tests/leakage/test_nwp_issue_time.py -q
```

Expected: collection fails because `SelectionMode` and the cycle functions do not exist.

- [ ] **Step 3: Implement the pure UTC and cycle functions**

Add these imports and definitions to `src/ingestion/nwp_archiver.py`:

```python
from datetime import datetime, timedelta, timezone
from typing import AbstractSet, Sequence


UTC = timezone.utc


class SelectionMode(StrEnum):
    SMOKE = "smoke"
    FULL = "full"
    CATCHUP = "catchup"
    SCHEDULED = "scheduled"


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value


def enumerate_retained_cycles(
    latest_issue_time_utc: datetime,
    lookback: timedelta = timedelta(hours=60),
) -> tuple[datetime, ...]:
    latest = require_utc(latest_issue_time_utc)
    if latest.minute != 0 or latest.second != 0 or latest.microsecond != 0 or latest.hour not in {0, 6, 12, 18}:
        raise ValueError("latest issue must be an exact 00/06/12/18 UTC cycle")
    if lookback < timedelta(0) or lookback.total_seconds() % (6 * 3600) != 0:
        raise ValueError("lookback must be a non-negative multiple of 6 hours")
    count = int(lookback.total_seconds() // (6 * 3600))
    return tuple(latest - timedelta(hours=6 * offset) for offset in range(count, -1, -1))


def select_uncommitted_cycles(
    retained_cycles: Sequence[datetime],
    committed_cycles: AbstractSet[datetime],
    mode: SelectionMode,
) -> tuple[datetime, ...]:
    cycles = tuple(require_utc(value) for value in retained_cycles)
    if not cycles:
        return ()
    missing = tuple(value for value in cycles if value not in committed_cycles)
    if not missing:
        return ()
    if mode is SelectionMode.CATCHUP:
        return missing
    latest = cycles[-1]
    if mode in {SelectionMode.SMOKE, SelectionMode.FULL}:
        return (latest,) if latest in missing else ()
    selected: list[datetime] = []
    if latest in missing:
        selected.append(latest)
    oldest_prior = next((value for value in missing if value != latest), None)
    if oldest_prior is not None:
        selected.append(oldest_prior)
    return tuple(selected)


def measured_latency_minutes(issue_time_utc: datetime, retrieved_at_utc: datetime) -> float:
    issue = require_utc(issue_time_utc)
    retrieved = require_utc(retrieved_at_utc)
    if retrieved < issue:
        raise ValueError("retrieved_at_utc precedes issue_time_utc")
    return (retrieved - issue).total_seconds() / 60.0
```

- [ ] **Step 4: Verify GREEN and commit Task 3**

Run:

```powershell
python -m pytest tests/unit/test_nwp_cycles.py tests/leakage/test_nwp_issue_time.py -q
```

Expected: all tests in both files pass.

Then:

```powershell
git add src/ingestion/nwp_archiver.py tests/unit/test_nwp_cycles.py tests/leakage/test_nwp_issue_time.py
git diff --cached --check
git commit -m "feat: select retained NWP issue cycles"
```

---

### Task 4: Accumulation Semantics, Physical Units, and Grid Distance

**Files:**
- Modify: `src/ingestion/nwp_archiver.py`
- Create: `tests/unit/test_units.py`

**Interfaces:**
- Produces: `DecodedField`, `AccumulationResult`, `AccumulationError`, `deaccumulate_fields(...)`, `ssrd_mean_wm2(...)`, `precipitation_mm(...)`, and `haversine_km(...)`.
- Consumed by: run normalization and synthetic GRIB integration.

- [ ] **Step 1: Write failing reference conversion tests**

Create `tests/unit/test_units.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.ingestion.nwp_archiver import (
    AccumulationError,
    DecodedField,
    deaccumulate_fields,
    haversine_km,
    precipitation_mm,
    ssrd_mean_wm2,
)


UTC = timezone.utc
ISSUE = datetime(2026, 7, 16, 6, tzinfo=UTC)


def field(
    *,
    end: int,
    value: float,
    start: int = 0,
    units: str = "J m**-2",
    step_type: str = "accum",
) -> DecodedField:
    return DecodedField(
        parameter="ssrd",
        value=value,
        units=units,
        issue_time_utc=ISSUE,
        valid_time_utc=ISSUE + timedelta(hours=end),
        start_step_h=start,
        end_step_h=end,
        step_type=step_type,
        grid_latitude=-1.0,
        grid_longitude=116.75,
    )


def test_interval_accumulation_uses_raw_interval() -> None:
    result = deaccumulate_fields((field(start=3, end=6, value=1_080_000.0),), (6,), "energy")
    assert result[6].interval_value == 1_080_000.0
    assert result[6].interval_seconds == 10_800
    assert result[6].method == "interval_accumulation"
    assert ssrd_mean_wm2(result[6]) == 100.0


def test_run_total_is_differenced_against_predecessor() -> None:
    fields = (
        field(end=0, value=0.0),
        field(end=3, value=1_080_000.0),
        field(end=6, value=3_240_000.0),
    )
    result = deaccumulate_fields(fields, (0, 3, 6), "energy")
    assert result[0].interval_value is None
    assert result[0].interval_seconds == 0
    assert result[3].interval_value == 1_080_000.0
    assert result[6].interval_value == 2_160_000.0
    assert ssrd_mean_wm2(result[3]) == 100.0
    assert ssrd_mean_wm2(result[6]) == 200.0


def test_run_total_without_predecessor_is_rejected() -> None:
    with pytest.raises(AccumulationError, match="predecessor"):
        deaccumulate_fields((field(end=6, value=3_240_000.0),), (6,), "energy")


def test_tiny_negative_roundoff_is_zero_but_material_negative_fails() -> None:
    tiny = (field(end=0, value=1.0), field(end=3, value=1.0 - 5e-7))
    assert deaccumulate_fields(tiny, (3,), "energy")[3].interval_value == 0.0
    material = (field(end=0, value=1000.0), field(end=3, value=999.99))
    with pytest.raises(AccumulationError, match="negative"):
        deaccumulate_fields(material, (3,), "energy")


@pytest.mark.parametrize(
    ("start", "end", "step_type", "units", "match"),
    [
        (3, 3, "accum", "J m**-2", "positive"),
        (6, 3, "accum", "J m**-2", "positive"),
        (3, 6, "instant", "J m**-2", "step_type"),
        (3, 6, "accum", "W m**-2", "units"),
    ],
)
def test_invalid_accumulation_metadata_is_rejected(
    start: int, end: int, step_type: str, units: str, match: str
) -> None:
    with pytest.raises(AccumulationError, match=match):
        deaccumulate_fields(
            (field(start=start, end=end, value=1.0, step_type=step_type, units=units),),
            (end,),
            "energy",
        )


def test_precipitation_converts_interval_metres_to_mm() -> None:
    rain = field(start=0, end=3, value=0.0012, units="m")
    zero = field(start=0, end=0, value=0.0, units="m")
    result = deaccumulate_fields((zero, rain), (3,), "depth")[3]
    assert precipitation_mm(result) == 1.2


def test_precipitation_converts_kg_per_square_metre_to_metres_and_mm() -> None:
    zero = field(start=0, end=0, value=0.0, units="kg m**-2")
    rain = field(start=0, end=3, value=1.2, units="kg m**-2")
    result = deaccumulate_fields((zero, rain), (3,), "depth")[3]
    assert result.raw_value == pytest.approx(0.0012)
    assert result.interval_value == pytest.approx(0.0012)
    assert precipitation_mm(result) == pytest.approx(1.2)


def test_run_total_predecessor_metadata_is_validated() -> None:
    bad_predecessor = field(end=42, value=1.0, units="W m**-2")
    current = field(end=48, value=2.0)
    with pytest.raises(AccumulationError, match="predecessor.*units"):
        deaccumulate_fields((bad_predecessor, current), (48,), "energy")


def test_haversine_reference_distance() -> None:
    assert haversine_km(
        -0.9911713315158186, 116.63811127764585, -1.0, 116.75
    ) == pytest.approx(12.478274049682074, abs=1e-12)
```

- [ ] **Step 2: Run the unit tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/test_units.py -q
```

Expected: collection fails because the conversion interfaces do not exist.

- [ ] **Step 3: Implement the pure conversion functions**

Add these imports and definitions to `src/ingestion/nwp_archiver.py`:

```python
from math import asin, cos, radians, sin, sqrt
from typing import Iterable, Literal


EARTH_RADIUS_KM = 6371.0088
SSRD_NEGATIVE_TOLERANCE_JM2 = 1e-6
PRECIP_NEGATIVE_TOLERANCE_M = 1e-9


class AccumulationError(ValueError):
    pass


@dataclass(frozen=True)
class DecodedField:
    parameter: str
    value: float
    units: str
    issue_time_utc: datetime
    valid_time_utc: datetime
    start_step_h: int
    end_step_h: int
    step_type: str
    grid_latitude: float
    grid_longitude: float


@dataclass(frozen=True)
class AccumulationResult:
    raw_value: float
    interval_value: float | None
    interval_seconds: int
    method: str


def _normalise_accumulation_value(
    value: float,
    units: str,
    family: Literal["energy", "depth"],
) -> float:
    compact = units.replace(" ", "").lower()
    if family == "energy":
        if compact not in {"jm**-2", "jm-2", "j/m^2", "j/m2"}:
            raise AccumulationError(f"unexpected energy units: {units}")
        return value
    if compact in {"m", "metres", "meters"}:
        return value
    if compact in {"kgm**-2", "kgm-2", "kg/m^2", "kg/m2"}:
        # 1 kg m^-2 liquid-water equivalent = 1 mm = 0.001 m.
        return value / 1000.0
    raise AccumulationError(f"unexpected depth units: {units}")


def deaccumulate_fields(
    fields: Iterable[DecodedField],
    output_steps_h: Iterable[int],
    unit_family: Literal["energy", "depth"],
) -> dict[int, AccumulationResult]:
    by_end = {field.end_step_h: field for field in fields}
    tolerance = (
        SSRD_NEGATIVE_TOLERANCE_JM2
        if unit_family == "energy"
        else PRECIP_NEGATIVE_TOLERANCE_M
    )
    results: dict[int, AccumulationResult] = {}
    for end_step in output_steps_h:
        if end_step not in by_end:
            raise AccumulationError(f"missing accumulated field at step {end_step}")
        current = by_end[end_step]
        if current.step_type != "accum":
            raise AccumulationError("step_type must be accum")
        current_value = _normalise_accumulation_value(
            current.value, current.units, unit_family
        )
        if current.start_step_h == 0 and current.end_step_h == 0:
            results[end_step] = AccumulationResult(
                raw_value=current_value,
                interval_value=None,
                interval_seconds=0,
                method="lead_zero",
            )
            continue
        if current.end_step_h <= current.start_step_h:
            raise AccumulationError("accumulation interval must have positive duration")
        if current.start_step_h > 0:
            interval = current_value
            seconds = (current.end_step_h - current.start_step_h) * 3600
            method = "interval_accumulation"
        else:
            predecessors = [
                value
                for value in by_end.values()
                if value.start_step_h == 0 and value.end_step_h < current.end_step_h
            ]
            if not predecessors:
                raise AccumulationError(
                    f"run-total step {current.end_step_h} has no predecessor"
                )
            previous = max(predecessors, key=lambda value: value.end_step_h)
            if previous.step_type != "accum":
                raise AccumulationError("predecessor step_type must be accum")
            try:
                previous_value = _normalise_accumulation_value(
                    previous.value, previous.units, unit_family
                )
            except AccumulationError as exc:
                raise AccumulationError(f"predecessor {exc}") from exc
            interval = current_value - previous_value
            seconds = (current.end_step_h - previous.end_step_h) * 3600
            method = "run_total_difference"
        if interval < -tolerance:
            raise AccumulationError(f"material negative accumulation: {interval}")
        if interval < 0:
            interval = 0.0
        results[end_step] = AccumulationResult(
            raw_value=current_value,
            interval_value=interval,
            interval_seconds=seconds,
            method=method,
        )
    return results


def ssrd_mean_wm2(result: AccumulationResult) -> float | None:
    if result.interval_value is None:
        return None
    if result.interval_seconds <= 0:
        raise AccumulationError("SSRD interval_seconds must be positive")
    return result.interval_value / result.interval_seconds


def precipitation_mm(result: AccumulationResult) -> float | None:
    return None if result.interval_value is None else result.interval_value * 1000.0


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1, phi2 = radians(lat1), radians(lat2)
    delta_phi = radians(lat2 - lat1)
    delta_lambda = radians(lon2 - lon1)
    a = sin(delta_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(delta_lambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(a))
```

- [ ] **Step 4: Verify GREEN and commit Task 4**

Run:

```powershell
python -m pytest tests/unit/test_units.py -q
```

Expected: `12 passed`.

Then:

```powershell
git add src/ingestion/nwp_archiver.py tests/unit/test_units.py
git diff --cached --check
git commit -m "feat: normalize NWP accumulations"
```

---

### Task 5: Explicit ECMWF Discovery, Retrieval, and Nearest-Grid Decode

**Files:**
- Modify: `src/ingestion/nwp_archiver.py`
- Create: `tests/unit/test_nwp_gateway.py`

**Interfaces:**
- Consumes: site/profile dataclasses and UTC helpers.
- Produces: `RetrievedRun`, `OpenDataGateway`, `EcmwfOpenDataGateway`, `build_request(...)`, `discover_latest_issue(...)`, `retrieve_explicit_run(...)`, and `decode_nearest_site_fields(...)`.
- The gateway is injectable; default tests do not use the network.

- [ ] **Step 1: Write failing gateway and decode-boundary tests**

Create `tests/unit/test_nwp_gateway.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.ingestion.nwp_archiver import (
    ArchiveProfile,
    NwpModel,
    SitePoint,
    build_request,
    decode_nearest_site_fields,
    discover_latest_issue,
    request_profile_for,
    retrieve_explicit_run,
)


UTC = timezone.utc
ISSUE = datetime(2026, 7, 16, 6, tzinfo=UTC)
RETRIEVED = datetime(2026, 7, 16, 7, 15, 30, tzinfo=UTC)
SITE = SitePoint(
    site_id="PLTS-IKN",
    latitude_deg=-0.9911713315158186,
    longitude_deg=116.63811127764585,
    elevation_m=85.0,
    timezone="Asia/Makassar",
)


class FakeGateway:
    def __init__(self) -> None:
        self.latest_calls: list[dict[str, object]] = []
        self.retrieve_calls: list[tuple[dict[str, object], Path]] = []

    def latest(self, *, model: NwpModel, request: dict[str, object]) -> datetime:
        self.latest_calls.append({"model": model, **request})
        return ISSUE

    def retrieve(
        self,
        *,
        model: NwpModel,
        request: dict[str, object],
        target: Path,
    ) -> None:
        self.retrieve_calls.append(({"model": model, **request}, target))
        target.write_bytes(b"GRIB")


def test_discovery_request_has_no_issue_date_or_time() -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.FULL)
    request = build_request(profile, profile.groups[0], issue_time_utc=None)
    assert request["stream"] == "oper"
    assert request["type"] == "fc"
    assert request["levtype"] == "sfc"
    assert request["step"] == list(range(0, 145, 3))
    assert request["param"] == ["ssrd", "tcc"]
    assert "date" not in request
    assert "time" not in request
    assert "area" not in request


def test_latest_result_is_frozen_into_explicit_retrieve(tmp_path: Path) -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.SMOKE)
    gateway = FakeGateway()
    latest = discover_latest_issue(gateway, profile)
    run = retrieve_explicit_run(
        gateway,
        profile,
        latest,
        tmp_path,
        clock=lambda: RETRIEVED,
    )
    assert latest == ISSUE
    assert run.issue_time_utc == ISSUE
    assert run.retrieved_at_utc == RETRIEVED
    assert len(gateway.retrieve_calls) == 1
    request, target = gateway.retrieve_calls[0]
    assert request["date"] == "20260716"
    assert request["time"] == 600
    assert request["step"] == [45, 48]
    assert target.read_bytes() == b"GRIB"


def test_retrieval_timestamp_is_captured_only_after_every_download(tmp_path: Path) -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.FULL)
    gateway = FakeGateway()
    clock_calls: list[str] = []

    def clock() -> datetime:
        clock_calls.append("called")
        assert len(gateway.retrieve_calls) == len(profile.groups)
        return RETRIEVED

    run = retrieve_explicit_run(gateway, profile, ISSUE, tmp_path, clock=clock)
    assert clock_calls == ["called"]
    assert set(run.files_by_group) == {group.name for group in profile.groups}


def test_failed_group_does_not_capture_retrieval_time(tmp_path: Path) -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.FULL)

    class FailingGateway(FakeGateway):
        def retrieve(self, *, model, request, target) -> None:
            super().retrieve(model=model, request=request, target=target)
            if len(self.retrieve_calls) == 2:
                raise RuntimeError("upstream failed")

    gateway = FailingGateway()
    with pytest.raises(RuntimeError, match="upstream failed"):
        retrieve_explicit_run(
            gateway,
            profile,
            ISSUE,
            tmp_path,
            clock=lambda: pytest.fail("clock must not be called"),
        )


def test_transient_retrieval_is_retried_with_a_finite_bound(tmp_path: Path) -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.SMOKE)

    class FlakyGateway(FakeGateway):
        def retrieve(self, *, model, request, target) -> None:
            super().retrieve(model=model, request=request, target=target)
            if len(self.retrieve_calls) < 3:
                raise TimeoutError("temporary timeout")

    gateway = FlakyGateway()
    sleeps: list[float] = []
    run = retrieve_explicit_run(
        gateway,
        profile,
        ISSUE,
        tmp_path,
        clock=lambda: RETRIEVED,
        retry_attempts=3,
        retry_delay_seconds=0.25,
        sleep=sleeps.append,
    )
    assert run.retrieved_at_utc == RETRIEVED
    assert len(gateway.retrieve_calls) == 3
    assert sleeps == [0.25, 0.5]


def test_permanent_retrieval_error_is_not_retried(tmp_path: Path) -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.SMOKE)

    class InvalidRequestGateway(FakeGateway):
        def retrieve(self, *, model, request, target) -> None:
            self.retrieve_calls.append(({"model": model, **request}, target))
            raise ValueError("invalid request")

    gateway = InvalidRequestGateway()
    with pytest.raises(ValueError, match="invalid request"):
        retrieve_explicit_run(
            gateway,
            profile,
            ISSUE,
            tmp_path,
            clock=lambda: pytest.fail("clock must not be called"),
            sleep=lambda _: pytest.fail("permanent errors must not sleep"),
        )
    assert len(gateway.retrieve_calls) == 1


def test_decode_rejects_issue_time_mismatch(monkeypatch, tmp_path: Path) -> None:
    module = __import__("src.ingestion.nwp_archiver", fromlist=["dummy"])
    run = module.RetrievedRun(
        model=NwpModel.IFS,
        issue_time_utc=ISSUE,
        retrieved_at_utc=RETRIEVED,
        files_by_group={"solar": (tmp_path / "solar.grib2",)},
    )
    run.files_by_group["solar"][0].write_bytes(b"GRIB")
    mismatched = module.DecodedField(
        parameter="ssrd",
        value=1.0,
        units="J m**-2",
        issue_time_utc=datetime(2026, 7, 16, 12, tzinfo=UTC),
        valid_time_utc=datetime(2026, 7, 16, 15, tzinfo=UTC),
        start_step_h=0,
        end_step_h=3,
        step_type="accum",
        grid_latitude=-1.0,
        grid_longitude=116.75,
    )
    monkeypatch.setattr(module, "_decode_grib_path", lambda path, site: (mismatched,))
    with pytest.raises(module.GribDecodeError, match="issue time"):
        decode_nearest_site_fields(run, SITE)
```

- [ ] **Step 2: Run the gateway tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/test_nwp_gateway.py -q
```

Expected: collection fails because the gateway interfaces do not exist.

- [ ] **Step 3: Implement explicit requests and the real ECMWF gateway**

Add to `src/ingestion/nwp_archiver.py`:

```python
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Protocol
import time


class GribDecodeError(ValueError):
    pass


@dataclass(frozen=True)
class RetrievedRun:
    model: NwpModel
    issue_time_utc: datetime
    retrieved_at_utc: datetime
    files_by_group: Mapping[str, tuple[Path, ...]]


class OpenDataGateway(Protocol):
    def latest(self, *, model: NwpModel, request: dict[str, object]) -> datetime: ...

    def retrieve(
        self,
        *,
        model: NwpModel,
        request: dict[str, object],
        target: Path,
    ) -> None: ...


def _normalise_ecmwf_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class EcmwfOpenDataGateway:
    def __init__(self, *, source: str = "google") -> None:
        from ecmwf.opendata import Client

        self.source = source
        self._client_type = Client

    def _client(self, model: NwpModel):
        return self._client_type(
            source=self.source,
            model=model.value,
            resol="0p25",
            infer_stream_keyword=False,
        )

    def latest(self, *, model: NwpModel, request: dict[str, object]) -> datetime:
        return _normalise_ecmwf_datetime(self._client(model).latest(**request))

    def retrieve(
        self,
        *,
        model: NwpModel,
        request: dict[str, object],
        target: Path,
    ) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        self._client(model).retrieve(**request, target=str(target))
        if not target.is_file() or target.stat().st_size == 0:
            raise RuntimeError(f"ECMWF retrieval produced no data: {target}")


def build_request(
    profile: RequestProfile,
    group: ParameterGroup,
    *,
    issue_time_utc: datetime | None,
) -> dict[str, object]:
    request: dict[str, object] = {
        "stream": "oper",
        "type": "fc",
        "levtype": "sfc",
        "step": list(profile.request_steps_h),
        "param": list(group.parameters),
    }
    if issue_time_utc is not None:
        issue = require_utc(issue_time_utc)
        request["date"] = issue.strftime("%Y%m%d")
        request["time"] = issue.hour * 100
    return request


def discover_latest_issue(
    gateway: OpenDataGateway,
    profile: RequestProfile,
) -> datetime:
    combined = ParameterGroup("complete", profile.parameters)
    return require_utc(
        gateway.latest(
            model=profile.model,
            request=build_request(profile, combined, issue_time_utc=None),
        )
    )


def retrieve_explicit_run(
    gateway: OpenDataGateway,
    profile: RequestProfile,
    issue_time_utc: datetime,
    work_directory: Path,
    *,
    clock: Callable[[], datetime],
    retry_attempts: int = 3,
    retry_delay_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
) -> RetrievedRun:
    if retry_attempts < 1:
        raise ValueError("retry_attempts must be at least 1")
    issue = require_utc(issue_time_utc)
    files: dict[str, tuple[Path, ...]] = {}
    work_directory.mkdir(parents=True, exist_ok=True)
    for group in profile.groups:
        target = work_directory / f"{profile.model.value}-{issue:%Y%m%dT%HZ}-{group.name}.grib2"
        request = build_request(profile, group, issue_time_utc=issue)
        for attempt in range(1, retry_attempts + 1):
            try:
                gateway.retrieve(
                    model=profile.model,
                    request=request,
                    target=target,
                )
                break
            except (ConnectionError, OSError, TimeoutError):
                if attempt == retry_attempts:
                    raise
                sleep(retry_delay_seconds * attempt)
        files[group.name] = (target,)
    retrieved = require_utc(clock())
    if retrieved < issue:
        raise ValueError("retrieved_at_utc precedes issue_time_utc")
    return RetrievedRun(
        model=profile.model,
        issue_time_utc=issue,
        retrieved_at_utc=retrieved,
        files_by_group=files,
    )
```

- [ ] **Step 4: Implement low-level nearest-grid decoding**

Add:

```python
def _date_time_to_utc(date_value: int, time_value: int) -> datetime:
    return datetime.strptime(
        f"{date_value:08d}{time_value:04d}", "%Y%m%d%H%M"
    ).replace(tzinfo=UTC)


def _normalise_longitude(longitude: float) -> float:
    return longitude - 360.0 if longitude > 180.0 else longitude


def _decode_grib_path(path: Path, site: SitePoint) -> tuple[DecodedField, ...]:
    from eccodes import (
        codes_get,
        codes_grib_find_nearest,
        codes_grib_new_from_file,
        codes_release,
    )

    decoded: list[DecodedField] = []
    with path.open("rb") as stream:
        while True:
            handle = codes_grib_new_from_file(stream)
            if handle is None:
                break
            try:
                nearest = codes_grib_find_nearest(
                    handle, site.latitude_deg, site.longitude_deg
                )[0]
                issue = _date_time_to_utc(
                    int(codes_get(handle, "dataDate")),
                    int(codes_get(handle, "dataTime")),
                )
                valid = _date_time_to_utc(
                    int(codes_get(handle, "validityDate")),
                    int(codes_get(handle, "validityTime")),
                )
                decoded.append(
                    DecodedField(
                        parameter=str(codes_get(handle, "shortName")),
                        value=float(nearest.value),
                        units=str(codes_get(handle, "units")),
                        issue_time_utc=issue,
                        valid_time_utc=valid,
                        start_step_h=int(codes_get(handle, "startStep")),
                        end_step_h=int(codes_get(handle, "endStep")),
                        step_type=str(codes_get(handle, "stepType")),
                        grid_latitude=float(nearest.lat),
                        grid_longitude=_normalise_longitude(float(nearest.lon)),
                    )
                )
            finally:
                codes_release(handle)
    if not decoded:
        raise GribDecodeError(f"no GRIB messages decoded from {path}")
    return tuple(decoded)


def decode_nearest_site_fields(
    run: RetrievedRun,
    site: SitePoint,
) -> tuple[DecodedField, ...]:
    fields = tuple(
        field
        for paths in run.files_by_group.values()
        for path in paths
        for field in _decode_grib_path(path, site)
    )
    for field in fields:
        if field.issue_time_utc != run.issue_time_utc:
            raise GribDecodeError(
                f"decoded issue time {field.issue_time_utc.isoformat()} does not match "
                f"requested issue time {run.issue_time_utc.isoformat()}"
            )
        expected_valid = run.issue_time_utc + timedelta(hours=field.end_step_h)
        if field.valid_time_utc != expected_valid:
            raise GribDecodeError(
                f"valid time mismatch for {field.parameter} step {field.end_step_h}"
            )
    coordinates = {(field.grid_latitude, field.grid_longitude) for field in fields}
    if len(coordinates) != 1:
        raise GribDecodeError("grid coordinates changed within retrieved run")
    return fields
```

- [ ] **Step 5: Verify GREEN and commit Task 5**

Run:

```powershell
python -m pytest tests/unit/test_nwp_gateway.py -q
```

Expected: `7 passed`.

Then:

```powershell
git add src/ingestion/nwp_archiver.py tests/unit/test_nwp_gateway.py
git diff --cached --check
git commit -m "feat: retrieve explicit ECMWF issue runs"
```

---

### Task 6: Model-specific Completeness and Canonical Normalization

**Files:**
- Modify: `src/ingestion/nwp_archiver.py`
- Create: `tests/unit/test_nwp_normalise.py`

**Interfaces:**
- Consumes: decoded fields, accumulation helpers, request profiles, and `validate_nwp_frame`.
- Produces: `validate_field_completeness(...)` and `normalise_run(...)`.

- [ ] **Step 1: Write failing normalization tests**

Create `tests/unit/test_nwp_normalise.py`:

```python
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from src.ingestion.nwp_archiver import (
    ArchiveProfile,
    DecodedField,
    NwpModel,
    SitePoint,
    normalise_run,
    request_profile_for,
    validate_field_completeness,
)


UTC = timezone.utc
ISSUE = datetime(2026, 7, 16, 6, tzinfo=UTC)
RETRIEVED = datetime(2026, 7, 16, 7, 15, 30, tzinfo=UTC)
SITE = SitePoint("PLTS-IKN", -0.9911713315158186, 116.63811127764585, 85.0, "Asia/Makassar")


def make_field(parameter: str, step: int) -> DecodedField:
    accumulated = parameter in {"ssrd", "tp", "cp"}
    # Synthetic fields represent ECMWF run-total accumulations. Keeping
    # startStep=0 lets the normaliser derive each interval from consecutive
    # endStep values, including the 45h -> 48h smoke predecessor.
    start = 0
    if parameter == "ssrd":
        value, units = step * 3600 * 100.0, "J m**-2"
    elif parameter in {"tp", "cp"}:
        value, units = step * 0.0004, "m"
    elif parameter in {"tcc", "lcc", "mcc", "hcc"}:
        value, units = 0.25, "(0 - 1)"
    elif parameter == "2t":
        value, units = 300.0, "K"
    elif parameter == "2d":
        value, units = 298.15, "K"
    elif parameter == "10u":
        value, units = 2.5, "m s**-1"
    elif parameter == "10v":
        value, units = -1.0, "m s**-1"
    elif parameter == "sp":
        value, units = 100000.0, "Pa"
    elif parameter == "tcwv":
        value, units = 30.0, "kg m**-2"
    elif parameter == "mucape":
        value, units = 400.0, "J kg**-1"
    else:
        raise AssertionError(parameter)
    return DecodedField(
        parameter=parameter,
        value=value,
        units=units,
        issue_time_utc=ISSUE,
        valid_time_utc=ISSUE + timedelta(hours=step),
        start_step_h=start if accumulated else step,
        end_step_h=step,
        step_type="accum" if accumulated else "instant",
        grid_latitude=-1.0,
        grid_longitude=116.75,
    )


def fields_for(model: NwpModel, profile_name: ArchiveProfile) -> tuple[DecodedField, ...]:
    profile = request_profile_for(model, profile_name)
    values: list[DecodedField] = []
    for parameter in profile.parameters:
        for step in profile.request_steps_h:
            values.append(make_field(parameter, step))
    return tuple(values)


def test_missing_required_parameter_or_step_prevents_publish() -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.FULL)
    fields = fields_for(NwpModel.IFS, ArchiveProfile.FULL)
    missing_mucape = tuple(
        field for field in fields if not (field.parameter == "mucape" and field.end_step_h == 144)
    )
    with pytest.raises(ValueError, match="mucape.*144"):
        validate_field_completeness(missing_mucape, profile)


def test_duplicate_parameter_step_is_rejected() -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.SMOKE)
    fields = fields_for(NwpModel.IFS, ArchiveProfile.SMOKE)
    with pytest.raises(ValueError, match="duplicate"):
        validate_field_completeness(fields + (fields[-1],), profile)


def test_smoke_publishes_only_lead_48_after_using_predecessor() -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.SMOKE)
    frame = normalise_run(
        fields_for(NwpModel.IFS, ArchiveProfile.SMOKE),
        site=SITE,
        profile=profile,
        retrieved_at_utc=RETRIEVED,
        ecmwf_client_source="google",
        ecmwf_client_version="0.3.30",
        eccodes_version="2.47.0",
    )
    assert frame["lead_time_min"].tolist() == [2880]
    assert frame.loc[0, "ssrd_wm2"] == 100.0
    assert frame.loc[0, "ssrd_accum_jm2"] == 17_280_000.0
    assert frame.loc[0, "ssrd_interval_jm2"] == 1_080_000.0


def test_full_ifs_has_exact_horizon_and_model_specific_nulls() -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.FULL)
    frame = normalise_run(
        fields_for(NwpModel.IFS, ArchiveProfile.FULL),
        site=SITE,
        profile=profile,
        retrieved_at_utc=RETRIEVED,
        ecmwf_client_source="google",
        ecmwf_client_version="0.3.30",
        eccodes_version="2.47.0",
    )
    assert len(frame) == 49
    assert frame["lead_time_min"].iloc[[0, -1]].tolist() == [0, 8640]
    assert frame[["lcc_frac", "mcc_frac", "hcc_frac", "cp_mm"]].isna().all().all()
    assert frame["tcwv_kgm2"].notna().all()
    assert frame["mucape_jkg"].notna().all()
    assert frame.loc[1, "t2m_c"] == pytest.approx(26.85)
    assert frame.loc[1, "sp_hpa"] == 1000.0


def test_full_aifs_has_exact_horizon_and_model_specific_nulls() -> None:
    profile = request_profile_for(NwpModel.AIFS_SINGLE, ArchiveProfile.FULL)
    frame = normalise_run(
        fields_for(NwpModel.AIFS_SINGLE, ArchiveProfile.FULL),
        site=SITE,
        profile=profile,
        retrieved_at_utc=RETRIEVED,
        ecmwf_client_source="google",
        ecmwf_client_version="0.3.30",
        eccodes_version="2.47.0",
    )
    assert len(frame) == 25
    assert frame["lead_time_min"].iloc[[0, -1]].tolist() == [0, 8640]
    assert frame[["lcc_frac", "mcc_frac", "hcc_frac", "cp_mm"]].iloc[1:].notna().all().all()
    assert frame[["tcwv_kgm2", "mucape_jkg"]].isna().all().all()
```

- [ ] **Step 2: Run the normalization tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/test_nwp_normalise.py -q
```

Expected: collection fails because `normalise_run` and `validate_field_completeness` do not exist.

- [ ] **Step 3: Implement completeness and unit-normalization helpers**

Add to `src/ingestion/nwp_archiver.py`:

```python
import pandas as pd

from data_contracts.nwp_schema import (
    NWP_COLUMNS,
    NWP_SCHEMA_VERSION,
    canonicalize_nwp_frame,
)


ECMWF_DATASET_URL = "https://www.ecmwf.int/en/forecasts/datasets/open-data"
ECMWF_LICENCE_ID = "CC-BY-4.0"


def validate_field_completeness(
    fields: Sequence[DecodedField],
    profile: RequestProfile,
) -> None:
    expected = {
        (parameter, step)
        for parameter in profile.parameters
        for step in profile.request_steps_h
    }
    actual_pairs = [(field.parameter, field.end_step_h) for field in fields]
    duplicates = {
        pair for pair in actual_pairs if actual_pairs.count(pair) > 1
    }
    if duplicates:
        raise ValueError(f"duplicate parameter/step fields: {sorted(duplicates)}")
    actual = set(actual_pairs)
    missing = expected - actual
    unexpected = actual - expected
    if missing:
        raise ValueError(f"missing required parameter/step fields: {sorted(missing)}")
    if unexpected:
        raise ValueError(f"unexpected parameter/step fields: {sorted(unexpected)}")


def _field_index(fields: Sequence[DecodedField]) -> dict[tuple[str, int], DecodedField]:
    return {(field.parameter, field.end_step_h): field for field in fields}


def _instant(
    index: Mapping[tuple[str, int], DecodedField],
    parameter: str,
    step: int,
) -> DecodedField | None:
    return index.get((parameter, step))


def _temperature_c(field: DecodedField | None) -> float | None:
    if field is None:
        return None
    if field.units != "K":
        raise ValueError(f"{field.parameter} units must be K, got {field.units}")
    return field.value - 273.15


def _cloud_fraction(field: DecodedField | None) -> float | None:
    if field is None:
        return None
    compact = field.units.replace(" ", "").lower()
    if compact in {"(0-1)", "1", "fraction", "proportion"}:
        value = field.value
    elif compact in {"%", "percent", "percentage"}:
        value = field.value / 100.0
    else:
        raise ValueError(f"{field.parameter} cloud units are unsupported: {field.units}")
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{field.parameter} cloud fraction outside [0, 1]")
    return value


def _value_with_units(
    field: DecodedField | None,
    accepted_compact_units: set[str],
) -> float | None:
    if field is None:
        return None
    compact = field.units.replace(" ", "").lower()
    if compact not in accepted_compact_units:
        raise ValueError(f"{field.parameter} units are unsupported: {field.units}")
    return field.value
```

- [ ] **Step 4: Implement canonical row construction**

Add:

```python
def normalise_run(
    fields: Sequence[DecodedField],
    *,
    site: SitePoint,
    profile: RequestProfile,
    retrieved_at_utc: datetime,
    ecmwf_client_source: str,
    ecmwf_client_version: str,
    eccodes_version: str,
) -> pd.DataFrame:
    retrieved = require_utc(retrieved_at_utc)
    validate_field_completeness(fields, profile)
    issues = {field.issue_time_utc for field in fields}
    coordinates = {(field.grid_latitude, field.grid_longitude) for field in fields}
    if len(issues) != 1:
        raise ValueError("fields contain multiple issue times")
    if len(coordinates) != 1:
        raise ValueError("fields contain multiple grid coordinates")
    issue = require_utc(next(iter(issues)))
    grid_latitude, grid_longitude = next(iter(coordinates))
    distance = haversine_km(
        site.latitude_deg, site.longitude_deg, grid_latitude, grid_longitude
    )
    if distance > 25.0:
        raise ValueError(f"nearest ECMWF grid point is too far away: {distance:.3f} km")
    index = _field_index(fields)
    ssrd = deaccumulate_fields(
        (index[("ssrd", step)] for step in profile.request_steps_h),
        profile.output_steps_h,
        "energy",
    )
    tp = (
        deaccumulate_fields(
            (index[("tp", step)] for step in profile.request_steps_h),
            profile.output_steps_h,
            "depth",
        )
        if "tp" in profile.parameters
        else {}
    )
    cp = (
        deaccumulate_fields(
            (index[("cp", step)] for step in profile.request_steps_h),
            profile.output_steps_h,
            "depth",
        )
        if "cp" in profile.parameters
        else {}
    )
    rows: list[dict[str, object]] = []
    for step in profile.output_steps_h:
        ssrd_field = index[("ssrd", step)]
        tp_result = tp.get(step)
        cp_result = cp.get(step)
        sp = _value_with_units(_instant(index, "sp", step), {"pa"})
        row = {
            "site_id": site.site_id,
            "nwp_provider": "ecmwf_opendata",
            "nwp_source": profile.nwp_source,
            "nwp_model": profile.model.value,
            "issue_time_utc": issue,
            "valid_time_utc": issue + timedelta(hours=step),
            "retrieved_at_utc": retrieved,
            "lead_time_min": step * 60,
            "ssrd_wm2": ssrd_mean_wm2(ssrd[step]),
            "ssrd_accum_jm2": ssrd[step].raw_value,
            "ssrd_interval_jm2": ssrd[step].interval_value,
            "ssrd_interval_seconds": ssrd[step].interval_seconds,
            "ssrd_conversion_method": ssrd[step].method,
            "grib_start_step_h": ssrd_field.start_step_h,
            "grib_end_step_h": ssrd_field.end_step_h,
            "grib_step_type": ssrd_field.step_type,
            "tcc_frac": _cloud_fraction(_instant(index, "tcc", step)),
            "lcc_frac": _cloud_fraction(_instant(index, "lcc", step)),
            "mcc_frac": _cloud_fraction(_instant(index, "mcc", step)),
            "hcc_frac": _cloud_fraction(_instant(index, "hcc", step)),
            "t2m_c": _temperature_c(_instant(index, "2t", step)),
            "d2m_c": _temperature_c(_instant(index, "2d", step)),
            "u10_ms": _value_with_units(
                _instant(index, "10u", step), {"ms**-1", "ms-1", "m/s"}
            ),
            "v10_ms": _value_with_units(
                _instant(index, "10v", step), {"ms**-1", "ms-1", "m/s"}
            ),
            "tp_accum_m": None if tp_result is None else tp_result.raw_value,
            "tp_interval_m": None if tp_result is None else tp_result.interval_value,
            "tp_mm": None if tp_result is None else precipitation_mm(tp_result),
            "sp_pa": sp,
            "sp_hpa": None if sp is None else sp / 100.0,
            "tcwv_kgm2": _value_with_units(
                _instant(index, "tcwv", step), {"kgm**-2", "kgm-2", "kg/m2"}
            ),
            "cp_accum_m": None if cp_result is None else cp_result.raw_value,
            "cp_interval_m": None if cp_result is None else cp_result.interval_value,
            "cp_mm": None if cp_result is None else precipitation_mm(cp_result),
            "mucape_jkg": _value_with_units(
                _instant(index, "mucape", step), {"jkg**-1", "jkg-1", "j/kg"}
            ),
            "site_latitude": site.latitude_deg,
            "site_longitude": site.longitude_deg,
            "grid_latitude": grid_latitude,
            "grid_longitude": grid_longitude,
            "grid_distance_km": distance,
            "grid_selection_method": "nearest",
            "ecmwf_client_source": ecmwf_client_source,
            "ecmwf_client_version": ecmwf_client_version,
            "eccodes_version": eccodes_version,
            "schema_version": NWP_SCHEMA_VERSION,
            "ecmwf_dataset_url": ECMWF_DATASET_URL,
            "licence_id": ECMWF_LICENCE_ID,
        }
        rows.append(row)
    frame = pd.DataFrame(rows).reindex(columns=NWP_COLUMNS)
    for column in ("issue_time_utc", "valid_time_utc", "retrieved_at_utc"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    return canonicalize_nwp_frame(frame)
```

- [ ] **Step 5: Verify GREEN and commit Task 6**

Run:

```powershell
python -m pytest tests/unit/test_nwp_normalise.py tests/unit/test_nwp_schema.py -q
```

Expected: all tests pass.

Then:

```powershell
git add src/ingestion/nwp_archiver.py tests/unit/test_nwp_normalise.py
git diff --cached --check
git commit -m "feat: normalize ECMWF site forecasts"
```

---

### Task 7: Atomic Parquet Attempt and Complete Manifest

**Files:**
- Modify: `data_contracts/nwp_schema.py`
- Modify: `src/ingestion/nwp_archiver.py`
- Create: `tests/unit/test_nwp_artifact.py`

**Interfaces:**
- Produces: `RunManifest`, `validate_manifest(...)`, `load_and_validate_manifest(...)`, `ArchiveArtifact`, `partition_relative_path(...)`, `sha256_file(...)`, and `write_archive_attempt(...)`.
- Consumed by: CLI and Drive launcher.

- [ ] **Step 1: Write failing path, hash, manifest, and Parquet tests**

Create `tests/unit/test_nwp_artifact.py`:

```python
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from data_contracts.nwp_schema import (
    RunManifest,
    validate_manifest,
)
from src.ingestion.nwp_archiver import (
    partition_relative_path,
    sha256_file,
    write_archive_attempt,
)


UTC = timezone.utc
ISSUE = datetime(2026, 7, 16, 6, tzinfo=UTC)
RETRIEVED = datetime(2026, 7, 16, 7, 15, 30, tzinfo=UTC)


def test_attempt_path_is_deterministic() -> None:
    assert partition_relative_path(
        nwp_source="ecmwf_ifs",
        issue_time_utc=ISSUE,
        retrieved_at_utc=RETRIEVED,
        smoke=False,
    ).as_posix() == (
        "nwp_source=ecmwf_ifs/issue_date=2026-07-16/issue_hour=06/"
        "retrieved_at=20260716T071530Z"
    )
    assert partition_relative_path(
        nwp_source="ecmwf_ifs",
        issue_time_utc=ISSUE,
        retrieved_at_utc=RETRIEVED,
        smoke=True,
    ).parts[0] == "_smoke"


def test_sha256_reference(tmp_path: Path) -> None:
    path = tmp_path / "abc.bin"
    path.write_bytes(b"abc")
    assert sha256_file(path) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )


def test_atomic_parquet_and_manifest_roundtrip(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    artifact = write_archive_attempt(
        valid_ifs_frame,
        output_root=tmp_path / "out",
        requested_parameters=("ssrd", "tcc"),
        requested_steps_h=(0, 3),
        received_parameters=("ssrd", "tcc"),
        received_steps_h=(0, 3),
        smoke=False,
    )
    assert artifact.parquet_path.is_file()
    assert artifact.manifest_path.is_file()
    restored = pd.read_parquet(artifact.parquet_path)
    assert str(restored["issue_time_utc"].dtype) == "datetime64[ns, UTC]"
    assert pd.isna(restored.loc[0, "ssrd_wm2"])
    assert restored.loc[1, "ssrd_wm2"] == 100.0
    validate_manifest(artifact.manifest, parquet_path=artifact.parquet_path)
    assert artifact.manifest.row_count == 2
    assert artifact.manifest.parquet_sha256 == sha256_file(artifact.parquet_path)


def test_manifest_hash_matches_independent_hash(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    artifact = write_archive_attempt(
        valid_ifs_frame,
        output_root=tmp_path,
        requested_parameters=("ssrd",),
        requested_steps_h=(0, 3),
        received_parameters=("ssrd",),
        received_steps_h=(0, 3),
        smoke=False,
    )
    independent = hashlib.sha256(artifact.parquet_path.read_bytes()).hexdigest()
    assert artifact.manifest.parquet_sha256 == independent


def test_all_null_model_columns_have_numeric_physical_parquet_type(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    artifact = write_archive_attempt(
        valid_ifs_frame,
        output_root=tmp_path,
        requested_parameters=("ssrd",),
        requested_steps_h=(0, 3),
        received_parameters=("ssrd",),
        received_steps_h=(0, 3),
        smoke=False,
    )
    schema = pq.read_schema(artifact.parquet_path)
    for column in ("lcc_frac", "mcc_frac", "hcc_frac", "cp_accum_m", "cp_interval_m", "cp_mm"):
        assert pa.types.is_floating(schema.field(column).type)


def test_hash_mismatch_is_rejected(tmp_path: Path, valid_ifs_frame: pd.DataFrame) -> None:
    artifact = write_archive_attempt(
        valid_ifs_frame,
        output_root=tmp_path,
        requested_parameters=("ssrd",),
        requested_steps_h=(0, 3),
        received_parameters=("ssrd",),
        received_steps_h=(0, 3),
        smoke=False,
    )
    artifact.parquet_path.write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="hash"):
        validate_manifest(artifact.manifest, parquet_path=artifact.parquet_path)


def test_validation_failure_leaves_no_final_attempt(
    tmp_path: Path, valid_ifs_frame: pd.DataFrame
) -> None:
    invalid = valid_ifs_frame.copy()
    invalid.loc[1, "lead_time_min"] = 179
    with pytest.raises(ValueError, match="lead_time_min"):
        write_archive_attempt(
            invalid,
            output_root=tmp_path,
            requested_parameters=("ssrd",),
            requested_steps_h=(0, 3),
            received_parameters=("ssrd",),
            received_steps_h=(0, 3),
            smoke=False,
        )
    assert list(tmp_path.rglob("retrieved_at=*")) == []
```

- [ ] **Step 2: Run the artifact tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/test_nwp_artifact.py -q
```

Expected: collection fails because `RunManifest` and artifact functions do not exist.

- [ ] **Step 3: Implement serializable manifest validation**

Add to `data_contracts/nwp_schema.py`:

```python
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Literal


def _iso_z(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
        raise NwpContractError("manifest timestamps must be timezone-aware UTC")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class RunManifest:
    schema_version: int
    status: Literal["complete"]
    site_id: str
    nwp_provider: Literal["ecmwf_opendata"]
    nwp_source: Literal["ecmwf_ifs", "ecmwf_aifs_single"]
    nwp_model: Literal["ifs", "aifs-single"]
    issue_time_utc: datetime
    retrieved_at_utc: datetime
    requested_parameters: tuple[str, ...]
    received_parameters: tuple[str, ...]
    requested_steps_h: tuple[int, ...]
    received_steps_h: tuple[int, ...]
    grid_latitude: float
    grid_longitude: float
    grid_distance_km: float
    row_count: int
    valid_time_min_utc: datetime
    valid_time_max_utc: datetime
    parquet_bytes: int
    parquet_sha256: str
    ecmwf_client_version: str
    eccodes_version: str
    dataset_url: str
    licence_id: Literal["CC-BY-4.0"]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        for key in (
            "issue_time_utc",
            "retrieved_at_utc",
            "valid_time_min_utc",
            "valid_time_max_utc",
        ):
            payload[key] = _iso_z(payload[key])
        for key in (
            "requested_parameters",
            "received_parameters",
            "requested_steps_h",
            "received_steps_h",
        ):
            payload[key] = list(payload[key])
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_json(cls, text: str) -> "RunManifest":
        payload = json.loads(text)
        for key in (
            "issue_time_utc",
            "retrieved_at_utc",
            "valid_time_min_utc",
            "valid_time_max_utc",
        ):
            payload[key] = datetime.fromisoformat(payload[key].replace("Z", "+00:00"))
        for key in (
            "requested_parameters",
            "received_parameters",
            "requested_steps_h",
            "received_steps_h",
        ):
            payload[key] = tuple(payload[key])
        return cls(**payload)


def validate_manifest(manifest: RunManifest, *, parquet_path: Path) -> None:
    if manifest.status != "complete":
        raise NwpContractError("manifest status must be complete")
    if manifest.schema_version != NWP_SCHEMA_VERSION:
        raise NwpContractError("manifest schema version mismatch")
    if (
        len(set(manifest.requested_parameters)) != len(manifest.requested_parameters)
        or len(set(manifest.received_parameters)) != len(manifest.received_parameters)
        or set(manifest.requested_parameters) != set(manifest.received_parameters)
    ):
        raise NwpContractError("manifest parameter inventory mismatch")
    if (
        len(set(manifest.requested_steps_h)) != len(manifest.requested_steps_h)
        or len(set(manifest.received_steps_h)) != len(manifest.received_steps_h)
        or set(manifest.requested_steps_h) != set(manifest.received_steps_h)
    ):
        raise NwpContractError("manifest step inventory mismatch")
    if manifest.nwp_provider != "ecmwf_opendata":
        raise NwpContractError("manifest provider mismatch")
    if SOURCE_MODEL.get(manifest.nwp_source) != manifest.nwp_model:
        raise NwpContractError("manifest source/model mismatch")
    for value in (
        manifest.issue_time_utc,
        manifest.retrieved_at_utc,
        manifest.valid_time_min_utc,
        manifest.valid_time_max_utc,
    ):
        _iso_z(value)
    if manifest.retrieved_at_utc < manifest.issue_time_utc:
        raise NwpContractError("manifest retrieval precedes issue")
    if manifest.valid_time_min_utc < manifest.issue_time_utc:
        raise NwpContractError("manifest valid range precedes issue")
    if manifest.valid_time_max_utc < manifest.valid_time_min_utc:
        raise NwpContractError("manifest valid range is reversed")
    if not (-90.0 <= manifest.grid_latitude <= 90.0):
        raise NwpContractError("manifest grid latitude is invalid")
    if not (-180.0 <= manifest.grid_longitude <= 180.0):
        raise NwpContractError("manifest grid longitude is invalid")
    if not (0.0 <= manifest.grid_distance_km <= 25.0):
        raise NwpContractError("manifest grid distance is invalid")
    if manifest.row_count <= 0:
        raise NwpContractError("manifest row_count must be positive")
    if not parquet_path.is_file():
        raise NwpContractError("manifest Parquet file is missing")
    if parquet_path.stat().st_size != manifest.parquet_bytes:
        raise NwpContractError("manifest Parquet byte size mismatch")
    if manifest.parquet_bytes <= 0:
        raise NwpContractError("manifest Parquet byte size must be positive")
    if re.fullmatch(r"[0-9a-f]{64}", manifest.parquet_sha256) is None:
        raise NwpContractError("manifest Parquet hash format is invalid")
    actual_hash = hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    if actual_hash != manifest.parquet_sha256:
        raise NwpContractError("manifest Parquet hash mismatch")
    if manifest.dataset_url != "https://www.ecmwf.int/en/forecasts/datasets/open-data":
        raise NwpContractError("manifest dataset URL mismatch")
    if manifest.licence_id != "CC-BY-4.0":
        raise NwpContractError("manifest licence mismatch")
    frame = validate_nwp_frame(pd.read_parquet(parquet_path))
    if len(frame) != manifest.row_count:
        raise NwpContractError("manifest row count mismatch")
    identity_checks = {
        "site_id": manifest.site_id,
        "nwp_source": manifest.nwp_source,
        "nwp_model": manifest.nwp_model,
        "issue_time_utc": pd.Timestamp(manifest.issue_time_utc),
        "retrieved_at_utc": pd.Timestamp(manifest.retrieved_at_utc),
        "grid_latitude": manifest.grid_latitude,
        "grid_longitude": manifest.grid_longitude,
        "grid_distance_km": manifest.grid_distance_km,
    }
    for column, expected in identity_checks.items():
        values = frame[column].drop_duplicates()
        if len(values) != 1 or values.iloc[0] != expected:
            raise NwpContractError(f"manifest {column} does not match Parquet")
    if frame["valid_time_utc"].min() != pd.Timestamp(manifest.valid_time_min_utc):
        raise NwpContractError("manifest minimum valid time mismatch")
    if frame["valid_time_utc"].max() != pd.Timestamp(manifest.valid_time_max_utc):
        raise NwpContractError("manifest maximum valid time mismatch")


def load_and_validate_manifest(
    manifest_path: Path,
    *,
    parquet_path: Path,
) -> RunManifest:
    manifest = RunManifest.from_json(manifest_path.read_text(encoding="utf-8"))
    validate_manifest(manifest, parquet_path=parquet_path)
    return manifest
```

- [ ] **Step 4: Implement atomic attempt creation**

Add to `src/ingestion/nwp_archiver.py`:

```python
import hashlib
import shutil
import tempfile
from pathlib import PurePosixPath

from data_contracts.nwp_schema import (
    RunManifest,
    canonicalize_nwp_frame,
    load_and_validate_manifest,
    validate_manifest,
)


@dataclass(frozen=True)
class ArchiveArtifact:
    run_directory: Path
    parquet_path: Path
    manifest_path: Path
    manifest: RunManifest


def partition_relative_path(
    *,
    nwp_source: str,
    issue_time_utc: datetime,
    retrieved_at_utc: datetime,
    smoke: bool,
) -> PurePosixPath:
    issue = require_utc(issue_time_utc)
    retrieved = require_utc(retrieved_at_utc)
    parts = (
        f"nwp_source={nwp_source}",
        f"issue_date={issue:%Y-%m-%d}",
        f"issue_hour={issue:%H}",
        f"retrieved_at={retrieved:%Y%m%dT%H%M%SZ}",
    )
    return PurePosixPath("_smoke", *parts) if smoke else PurePosixPath(*parts)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _single_value(frame: pd.DataFrame, column: str):
    values = frame[column].drop_duplicates()
    if len(values) != 1:
        raise ValueError(f"{column} must be constant within an archive attempt")
    return values.iloc[0]


def write_archive_attempt(
    frame: pd.DataFrame,
    *,
    output_root: Path,
    requested_parameters: tuple[str, ...],
    requested_steps_h: tuple[int, ...],
    received_parameters: tuple[str, ...],
    received_steps_h: tuple[int, ...],
    smoke: bool,
) -> ArchiveArtifact:
    validated = canonicalize_nwp_frame(frame)
    issue = pd.Timestamp(_single_value(validated, "issue_time_utc")).to_pydatetime()
    retrieved = pd.Timestamp(_single_value(validated, "retrieved_at_utc")).to_pydatetime()
    nwp_source = str(_single_value(validated, "nwp_source"))
    relative = partition_relative_path(
        nwp_source=nwp_source,
        issue_time_utc=issue,
        retrieved_at_utc=retrieved,
        smoke=smoke,
    )
    final_directory = output_root.joinpath(*relative.parts)
    if final_directory.exists():
        raise FileExistsError(f"attempt already exists: {final_directory}")
    output_root.mkdir(parents=True, exist_ok=True)
    temporary_root = output_root / ".tmp"
    temporary_root.mkdir(exist_ok=True)
    temporary_directory = Path(tempfile.mkdtemp(prefix="nwp-", dir=temporary_root))
    try:
        parquet_path = temporary_directory / "weather_forecast_raw.parquet"
        validated.to_parquet(parquet_path, index=False)
        manifest = RunManifest(
            schema_version=NWP_SCHEMA_VERSION,
            status="complete",
            site_id=str(_single_value(validated, "site_id")),
            nwp_provider="ecmwf_opendata",
            nwp_source=nwp_source,
            nwp_model=str(_single_value(validated, "nwp_model")),
            issue_time_utc=issue,
            retrieved_at_utc=retrieved,
            requested_parameters=requested_parameters,
            received_parameters=received_parameters,
            requested_steps_h=requested_steps_h,
            received_steps_h=received_steps_h,
            grid_latitude=float(_single_value(validated, "grid_latitude")),
            grid_longitude=float(_single_value(validated, "grid_longitude")),
            grid_distance_km=float(_single_value(validated, "grid_distance_km")),
            row_count=len(validated),
            valid_time_min_utc=pd.Timestamp(validated["valid_time_utc"].min()).to_pydatetime(),
            valid_time_max_utc=pd.Timestamp(validated["valid_time_utc"].max()).to_pydatetime(),
            parquet_bytes=parquet_path.stat().st_size,
            parquet_sha256=sha256_file(parquet_path),
            ecmwf_client_version=str(_single_value(validated, "ecmwf_client_version")),
            eccodes_version=str(_single_value(validated, "eccodes_version")),
            dataset_url=str(_single_value(validated, "ecmwf_dataset_url")),
            licence_id="CC-BY-4.0",
        )
        validate_manifest(manifest, parquet_path=parquet_path)
        (temporary_directory / "manifest.json").write_text(
            manifest.to_json(), encoding="utf-8"
        )
        final_directory.parent.mkdir(parents=True, exist_ok=True)
        temporary_directory.replace(final_directory)
        final_parquet = final_directory / "weather_forecast_raw.parquet"
        final_manifest = final_directory / "manifest.json"
        return ArchiveArtifact(
            run_directory=final_directory,
            parquet_path=final_parquet,
            manifest_path=final_manifest,
            manifest=manifest,
        )
    except Exception:
        shutil.rmtree(temporary_directory, ignore_errors=True)
        raise
```

- [ ] **Step 5: Verify GREEN and commit Task 7**

Run:

```powershell
python -m pytest tests/unit/test_nwp_artifact.py tests/unit/test_nwp_schema.py -q
```

Expected: all tests pass.

Then:

```powershell
git add data_contracts/nwp_schema.py src/ingestion/nwp_archiver.py tests/unit/test_nwp_artifact.py
git diff --cached --check
git commit -m "feat: write atomic NWP Parquet attempts"
```

---

### Task 8: One-Issue Orchestration, CLI, and Synthetic GRIB Round Trip

**Files:**
- Modify: `src/ingestion/nwp_archiver.py`
- Delete: root `nwp_archiver.py`
- Create: `tests/unit/test_nwp_cli.py`
- Create: `tests/integration/test_nwp_parquet.py`

**Interfaces:**
- Produces: `discover_candidate_cycles(...)`, `archive_issue(...)`, and `main(argv=None)`.
- CLI:
  - `python -m src.ingestion.nwp_archiver discover --model ... --mode ... --result-json ...`
  - `python -m src.ingestion.nwp_archiver select --mode ... --candidates-json ... --committed-json ... --result-json ...`
  - `python -m src.ingestion.nwp_archiver archive --site-config ... --model ... --profile ... --issue-time-utc ... --work-root ... --output-root ... --result-json ...`
  - `python -m src.ingestion.nwp_archiver verify --manifest ... --parquet ... --expected-source ... --expected-model ... --expected-issue-time-utc ... --result-json ...`

- [ ] **Step 1: Write failing orchestration and CLI contract tests**

Create `tests/unit/test_nwp_cli.py`:

```python
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

import src.ingestion.nwp_archiver as nwp


UTC = timezone.utc
ISSUE = datetime(2026, 7, 16, 6, tzinfo=UTC)
RETRIEVED = datetime(2026, 7, 16, 7, 15, 30, tzinfo=UTC)


class LatestGateway:
    source = "google"

    def latest(self, *, model, request):
        return ISSUE

    def retrieve(self, *, model, request, target):
        raise AssertionError("discovery must not retrieve")


def test_explicit_issue_is_rejected_for_scheduled_mode() -> None:
    with pytest.raises(ValueError, match="explicit issue"):
        nwp.discover_candidate_cycles(
            LatestGateway(),
            model=nwp.NwpModel.IFS,
            mode=nwp.SelectionMode.SCHEDULED,
            explicit_issue_time_utc=ISSUE,
        )


def test_discover_cli_writes_machine_readable_candidates(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(
        nwp, "EcmwfOpenDataGateway", lambda *, source: LatestGateway()
    )
    result_path = tmp_path / "discover.json"
    assert nwp.main(
        [
            "discover",
            "--model", "ifs",
            "--mode", "smoke",
            "--result-json", str(result_path),
        ]
    ) == 0
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload == {
        "candidate_issue_times_utc": ["2026-07-16T06:00:00Z"],
        "mode": "smoke",
        "model": "ifs",
        "nwp_source": "ecmwf_ifs",
    }


def test_archive_issue_runs_the_validated_pipeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = nwp.RetrievedRun(
        model=nwp.NwpModel.IFS,
        issue_time_utc=ISSUE,
        retrieved_at_utc=RETRIEVED,
        files_by_group={},
    )
    fields = (
        SimpleNamespace(parameter="ssrd", end_step_h=45),
        SimpleNamespace(parameter="ssrd", end_step_h=48),
    )
    captured: dict[str, object] = {}
    sentinel = object()
    monkeypatch.setattr(nwp, "retrieve_explicit_run", lambda *args, **kwargs: run)
    monkeypatch.setattr(nwp, "decode_nearest_site_fields", lambda *args: fields)
    monkeypatch.setattr(nwp, "normalise_run", lambda *args, **kwargs: "frame")
    monkeypatch.setattr(
        nwp,
        "_dependency_versions",
        lambda: ("0.3.30", "2.47.0"),
    )

    def fake_write(frame, **kwargs):
        captured.update({"frame": frame, **kwargs})
        return sentinel

    monkeypatch.setattr(nwp, "write_archive_attempt", fake_write)
    result = nwp.archive_issue(
        gateway=LatestGateway(),
        site=nwp.load_site_point(Path("configs/site_plts-ikn.yaml")),
        model=nwp.NwpModel.IFS,
        profile_name=nwp.ArchiveProfile.SMOKE,
        issue_time_utc=ISSUE,
        work_root=tmp_path / "work",
        output_root=tmp_path / "out",
        clock=lambda: RETRIEVED,
    )
    assert result is sentinel
    assert captured["frame"] == "frame"
    assert captured["requested_steps_h"] == (45, 48)
    assert captured["received_parameters"] == ("ssrd",)
    assert captured["received_steps_h"] == (45, 48)
    assert captured["smoke"] is True


def test_select_cli_uses_tested_latest_plus_oldest_scheduler_policy(
    tmp_path: Path,
) -> None:
    candidates = [
        "2026-07-15T18:00:00Z",
        "2026-07-16T00:00:00Z",
        "2026-07-16T06:00:00Z",
    ]
    candidates_path = tmp_path / "candidates.json"
    committed_path = tmp_path / "committed.json"
    result_path = tmp_path / "selected.json"
    candidates_path.write_text(json.dumps(candidates), encoding="utf-8")
    committed_path.write_text(
        json.dumps(["2026-07-16T00:00:00Z"]), encoding="utf-8"
    )
    assert nwp.main(
        [
            "select",
            "--mode", "scheduled",
            "--candidates-json", str(candidates_path),
            "--committed-json", str(committed_path),
            "--result-json", str(result_path),
        ]
    ) == 0
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["selected_issue_times_utc"] == [
        "2026-07-16T06:00:00Z",
        "2026-07-15T18:00:00Z",
    ]


def test_archive_cli_writes_artifact_result_contract(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    output_root = tmp_path / "out"
    run_directory = output_root / "_smoke" / "attempt"

    class FakeManifest:
        def to_dict(self):
            return {
                "status": "complete",
                "issue_time_utc": "2026-07-16T06:00:00Z",
                "parquet_sha256": "a" * 64,
            }

    artifact = SimpleNamespace(
        run_directory=run_directory,
        parquet_path=run_directory / "weather_forecast_raw.parquet",
        manifest_path=run_directory / "manifest.json",
        manifest=FakeManifest(),
    )
    monkeypatch.setattr(
        nwp, "EcmwfOpenDataGateway", lambda *, source: LatestGateway()
    )
    monkeypatch.setattr(nwp, "archive_issue", lambda **kwargs: artifact)
    result_path = tmp_path / "archive.json"
    assert nwp.main(
        [
            "archive",
            "--site-config", "configs/site_plts-ikn.yaml",
            "--model", "ifs",
            "--profile", "smoke",
            "--issue-time-utc", "2026-07-16T06:00:00Z",
            "--work-root", str(tmp_path / "work"),
            "--output-root", str(output_root),
            "--result-json", str(result_path),
        ]
    ) == 0
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["relative_path"] == "_smoke/attempt"
    assert payload["manifest"]["parquet_sha256"] == "a" * 64


def test_verify_cli_reads_parquet_and_full_manifest(
    tmp_path: Path, valid_ifs_frame
) -> None:
    artifact = nwp.write_archive_attempt(
        valid_ifs_frame,
        output_root=tmp_path / "out",
        requested_parameters=("ssrd",),
        requested_steps_h=(0, 3),
        received_parameters=("ssrd",),
        received_steps_h=(0, 3),
        smoke=False,
    )
    result_path = tmp_path / "verified.json"
    assert nwp.main(
        [
            "verify",
            "--manifest", str(artifact.manifest_path),
            "--parquet", str(artifact.parquet_path),
            "--expected-source", "ecmwf_ifs",
            "--expected-model", "ifs",
            "--expected-issue-time-utc", "2026-07-16T06:00:00Z",
            "--result-json", str(result_path),
        ]
    ) == 0
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["manifest"]["row_count"] == 2
```

- [ ] **Step 2: Run the CLI tests and observe RED**

Run:

```powershell
python -m pytest tests/unit/test_nwp_cli.py -q
```

Expected: collection fails because Task 8 orchestration and CLI interfaces do not yet exist.

- [ ] **Step 3: Write the failing synthetic GRIB round-trip test**

Create `tests/integration/test_nwp_parquet.py`:

```python
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.nwp_archiver import (
    ArchiveProfile,
    RetrievedRun,
    SitePoint,
    decode_nearest_site_fields,
    normalise_run,
    request_profile_for,
    sha256_file,
    write_archive_attempt,
    NwpModel,
)


UTC = timezone.utc
ISSUE = datetime(2026, 7, 16, 6, tzinfo=UTC)
RETRIEVED = datetime(2026, 7, 16, 7, 15, 30, tzinfo=UTC)
SITE = SitePoint("PLTS-IKN", -0.9911713315158186, 116.63811127764585, 85.0, "Asia/Makassar")


def write_ssrd_message(stream, *, end_step: int, values: list[float]) -> None:
    from eccodes import (
        codes_grib_new_from_samples,
        codes_release,
        codes_set,
        codes_set_values,
        codes_write,
    )

    handle = codes_grib_new_from_samples("regular_ll_sfc_grib2")
    try:
        settings = {
            "Ni": 2,
            "Nj": 1,
            "latitudeOfFirstGridPointInDegrees": -1.0,
            "latitudeOfLastGridPointInDegrees": -1.0,
            "longitudeOfFirstGridPointInDegrees": 116.50,
            "longitudeOfLastGridPointInDegrees": 116.75,
            "iDirectionIncrementInDegrees": 0.25,
            "dataDate": 20260716,
            "dataTime": 600,
            "shortName": "ssrd",
            "stepType": "accum",
            "startStep": 0,
            "endStep": end_step,
        }
        for key, value in settings.items():
            codes_set(handle, key, value)
        codes_set_values(handle, values)
        codes_write(handle, stream)
    finally:
        codes_release(handle)


def test_synthetic_grib_roundtrip_to_parquet(tmp_path: Path) -> None:
    path = tmp_path / "smoke.grib2"
    with path.open("wb") as stream:
        write_ssrd_message(stream, end_step=45, values=[8_100_000.0, 16_200_000.0])
        write_ssrd_message(stream, end_step=48, values=[8_640_000.0, 17_280_000.0])
    run = RetrievedRun(
        model=NwpModel.IFS,
        issue_time_utc=ISSUE,
        retrieved_at_utc=RETRIEVED,
        files_by_group={"solar": (path,)},
    )
    fields = decode_nearest_site_fields(run, SITE)
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.SMOKE)
    frame = normalise_run(
        fields,
        site=SITE,
        profile=profile,
        retrieved_at_utc=RETRIEVED,
        ecmwf_client_source="google",
        ecmwf_client_version="0.3.30",
        eccodes_version="2.47.0",
    )
    assert frame["grid_longitude"].tolist() == [116.75]
    assert frame["grid_distance_km"].iloc[0] == pytest.approx(12.478274049682074)
    assert frame["ssrd_wm2"].tolist() == [100.0]
    artifact = write_archive_attempt(
        frame,
        output_root=tmp_path / "out",
        requested_parameters=("ssrd",),
        requested_steps_h=(45, 48),
        received_parameters=("ssrd",),
        received_steps_h=(45, 48),
        smoke=True,
    )
    restored = pd.read_parquet(artifact.parquet_path)
    assert str(restored["issue_time_utc"].dtype) == "datetime64[ns, UTC]"
    assert restored["lead_time_min"].tolist() == [2880]
    assert artifact.manifest.parquet_sha256 == sha256_file(artifact.parquet_path)
```

- [ ] **Step 4: Run the integration test and verify RED or environment failure**

Install the Task 1 dependencies in the current environment:

```powershell
python -m pip install -r requirements-nwp.txt
```

Then run:

```powershell
python -m pytest tests/integration/test_nwp_parquet.py -q
```

Expected: the synthetic fixture either reaches the intended decode/normalize assertions or fails on a specific invalid ecCodes fixture key. Correct only fixture metadata until it creates two valid messages. A GREEN result here proves the lower-level GRIB boundary; the new Task 8 behavior remains RED in `test_nwp_cli.py` until Steps 5-6 are implemented.

- [ ] **Step 5: Add orchestration and machine-readable result helpers**

Add to `src/ingestion/nwp_archiver.py`:

```python
import argparse
import importlib.metadata
import json


def discover_candidate_cycles(
    gateway: OpenDataGateway,
    *,
    model: NwpModel,
    mode: SelectionMode,
    explicit_issue_time_utc: datetime | None = None,
) -> tuple[datetime, ...]:
    if explicit_issue_time_utc is not None:
        if mode in {SelectionMode.CATCHUP, SelectionMode.SCHEDULED}:
            raise ValueError("explicit issue time is not allowed for catchup/scheduled")
        return (require_utc(explicit_issue_time_utc),)
    profile_name = (
        ArchiveProfile.SMOKE if mode is SelectionMode.SMOKE else ArchiveProfile.FULL
    )
    latest = discover_latest_issue(gateway, request_profile_for(model, profile_name))
    if mode in {SelectionMode.SMOKE, SelectionMode.FULL}:
        return (latest,)
    return enumerate_retained_cycles(latest)


def archive_issue(
    *,
    gateway: OpenDataGateway,
    site: SitePoint,
    model: NwpModel,
    profile_name: ArchiveProfile,
    issue_time_utc: datetime,
    work_root: Path,
    output_root: Path,
    clock: Callable[[], datetime],
) -> ArchiveArtifact:
    profile = request_profile_for(model, profile_name)
    run = retrieve_explicit_run(
        gateway, profile, issue_time_utc, work_root, clock=clock
    )
    fields = decode_nearest_site_fields(run, site)
    ecmwf_version, eccodes_version = _dependency_versions()
    frame = normalise_run(
        fields,
        site=site,
        profile=profile,
        retrieved_at_utc=run.retrieved_at_utc,
        ecmwf_client_source=getattr(gateway, "source", "injected"),
        ecmwf_client_version=ecmwf_version,
        eccodes_version=eccodes_version,
    )
    actual_parameters = {field.parameter for field in fields}
    actual_steps = {field.end_step_h for field in fields}
    # Completeness validation has already proven set equality. Record the
    # actual inventory in canonical request order so GRIB message ordering
    # cannot create a false manifest mismatch.
    received_parameters = tuple(
        parameter for parameter in profile.parameters if parameter in actual_parameters
    )
    received_steps = tuple(
        step for step in profile.request_steps_h if step in actual_steps
    )
    return write_archive_attempt(
        frame,
        output_root=output_root,
        requested_parameters=profile.parameters,
        requested_steps_h=profile.request_steps_h,
        received_parameters=received_parameters,
        received_steps_h=received_steps,
        smoke=profile_name is ArchiveProfile.SMOKE,
    )


def _dependency_versions() -> tuple[str, str]:
    ecmwf_version = importlib.metadata.version("ecmwf-opendata")
    try:
        from eccodes import codes_get_api_version

        eccodes_version = str(codes_get_api_version())
    except ImportError:
        eccodes_version = importlib.metadata.version("eccodes")
    return ecmwf_version, eccodes_version


def _parse_utc(text: str) -> datetime:
    return require_utc(datetime.fromisoformat(text.replace("Z", "+00:00")))


def _write_result_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
```

- [ ] **Step 6: Implement the CLI**

Add:

```python
def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Archive ECMWF Open Data for PLTS-IKN")
    subparsers = parser.add_subparsers(dest="command", required=True)
    discover = subparsers.add_parser("discover")
    discover.add_argument("--model", choices=[value.value for value in NwpModel], required=True)
    discover.add_argument("--mode", choices=[value.value for value in SelectionMode], required=True)
    discover.add_argument("--issue-time-utc")
    discover.add_argument("--result-json", type=Path, required=True)
    select = subparsers.add_parser("select")
    select.add_argument("--mode", choices=[value.value for value in SelectionMode], required=True)
    select.add_argument("--candidates-json", type=Path, required=True)
    select.add_argument("--committed-json", type=Path, required=True)
    select.add_argument("--result-json", type=Path, required=True)
    archive = subparsers.add_parser("archive")
    archive.add_argument("--site-config", type=Path, required=True)
    archive.add_argument("--model", choices=[value.value for value in NwpModel], required=True)
    archive.add_argument("--profile", choices=[value.value for value in ArchiveProfile], required=True)
    archive.add_argument("--issue-time-utc", required=True)
    archive.add_argument("--work-root", type=Path, required=True)
    archive.add_argument("--output-root", type=Path, required=True)
    archive.add_argument("--result-json", type=Path, required=True)
    verify = subparsers.add_parser("verify")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--parquet", type=Path, required=True)
    verify.add_argument(
        "--expected-source",
        choices=["ecmwf_ifs", "ecmwf_aifs_single"],
        required=True,
    )
    verify.add_argument(
        "--expected-model",
        choices=[value.value for value in NwpModel],
        required=True,
    )
    verify.add_argument("--expected-issue-time-utc", required=True)
    verify.add_argument("--result-json", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.command == "select":
        candidate_text = json.loads(arguments.candidates_json.read_text(encoding="utf-8"))
        committed_text = json.loads(arguments.committed_json.read_text(encoding="utf-8"))
        if not isinstance(candidate_text, list) or not isinstance(committed_text, list):
            raise ValueError("candidate and committed JSON inputs must be arrays")
        candidates = tuple(_parse_utc(value) for value in candidate_text)
        committed = {_parse_utc(value) for value in committed_text}
        selected = select_uncommitted_cycles(
            candidates, committed, SelectionMode(arguments.mode)
        )
        _write_result_json(
            arguments.result_json,
            {
                "selected_issue_times_utc": [
                    value.isoformat().replace("+00:00", "Z") for value in selected
                ]
            },
        )
        return 0
    if arguments.command == "verify":
        manifest = load_and_validate_manifest(
            arguments.manifest,
            parquet_path=arguments.parquet,
        )
        expected_issue = _parse_utc(arguments.expected_issue_time_utc)
        if (
            manifest.nwp_source != arguments.expected_source
            or manifest.nwp_model != arguments.expected_model
            or manifest.issue_time_utc != expected_issue
        ):
            raise ValueError("verified artifact identity does not match expectation")
        _write_result_json(
            arguments.result_json,
            {"status": "complete", "manifest": manifest.to_dict()},
        )
        return 0
    gateway = EcmwfOpenDataGateway(source="google")
    if arguments.command == "discover":
        explicit = _parse_utc(arguments.issue_time_utc) if arguments.issue_time_utc else None
        candidates = discover_candidate_cycles(
            gateway,
            model=NwpModel(arguments.model),
            mode=SelectionMode(arguments.mode),
            explicit_issue_time_utc=explicit,
        )
        profile_name = (
            ArchiveProfile.SMOKE
            if arguments.mode == SelectionMode.SMOKE.value
            else ArchiveProfile.FULL
        )
        profile = request_profile_for(NwpModel(arguments.model), profile_name)
        _write_result_json(
            arguments.result_json,
            {
                "model": arguments.model,
                "nwp_source": profile.nwp_source,
                "mode": arguments.mode,
                "candidate_issue_times_utc": [
                    value.isoformat().replace("+00:00", "Z") for value in candidates
                ],
            },
        )
        return 0
    artifact = archive_issue(
        gateway=gateway,
        site=load_site_point(arguments.site_config),
        model=NwpModel(arguments.model),
        profile_name=ArchiveProfile(arguments.profile),
        issue_time_utc=_parse_utc(arguments.issue_time_utc),
        work_root=arguments.work_root,
        output_root=arguments.output_root,
        clock=lambda: datetime.now(UTC),
    )
    _write_result_json(
        arguments.result_json,
        {
            "status": "complete",
            "run_directory": str(artifact.run_directory),
            "relative_path": artifact.run_directory.relative_to(
                arguments.output_root
            ).as_posix(),
            "parquet_path": str(artifact.parquet_path),
            "manifest_path": str(artifact.manifest_path),
            "manifest": artifact.manifest.to_dict(),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Remove the zero-byte root placeholder**

Verify it is still zero bytes, then delete only that file:

```powershell
if ((Get-Item -LiteralPath .\nwp_archiver.py).Length -ne 0) {
    throw "Root nwp_archiver.py is no longer the approved zero-byte placeholder."
}
```

Delete `nwp_archiver.py` with `apply_patch`.

- [ ] **Step 8: Verify the full offline suite and commit Task 8**

Run:

```powershell
python -m pytest `
  tests/unit/test_nwp_profiles.py `
  tests/unit/test_nwp_schema.py `
  tests/unit/test_nwp_cycles.py `
  tests/unit/test_units.py `
  tests/unit/test_nwp_gateway.py `
  tests/unit/test_nwp_normalise.py `
  tests/unit/test_nwp_artifact.py `
  tests/unit/test_nwp_cli.py `
  tests/leakage/test_nwp_issue_time.py `
  tests/integration/test_nwp_parquet.py `
  -q
```

Expected: all tests pass with zero failures.

Then:

```powershell
git add src/ingestion/nwp_archiver.py tests/unit/test_nwp_cli.py tests/integration/test_nwp_parquet.py
git diff --cached --check
git commit -m "feat: orchestrate one NWP archive issue"
```

---

### Task 9: Drive Launcher and Gated GitHub Actions Workflow

**Files:**
- Create: `scripts/start_nwp_archiver.sh`
- Create: `.github/workflows/nwp-archiver.yml`
- Create: `tests/unit/test_workflow_contract.py`

**Interfaces:**
- Launcher:
  `scripts/start_nwp_archiver.sh --profile smoke|full|catchup|scheduled --model ifs|aifs-single --destination gdrive:PATH [--issue-time-utc ISO-Z]`.
- Workflow owns rclone credential reconstruction, remote manifest discovery, upload order, read-back verification, cleanup, and model matrix.

- [ ] **Step 1: Write failing static workflow/security tests**

Create `tests/unit/test_workflow_contract.py`:

```python
from __future__ import annotations

from pathlib import Path


WORKFLOW = Path(".github/workflows/nwp-archiver.yml")
LAUNCHER = Path("scripts/start_nwp_archiver.sh")


def test_workflow_has_manual_and_hourly_gated_triggers() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert 'cron: "17 * * * *"' in text
    assert "pull_request:" not in text
    assert "NWP_ARCHIVER_ENABLED" in text
    assert "contents: read" in text
    assert "cancel-in-progress: false" in text


def test_actions_and_rclone_are_pinned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0" in text
    assert "actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1" in text
    assert "rclone-v1.74.4-linux-amd64.zip" in text
    assert "fe435e0c36228e7c2f116a8701f01127bb1f694005fc11d1f27186c8bca4115d" in text
    assert "persist-credentials: false" in text


def test_rclone_secret_is_step_scoped_and_cleaned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "RCLONE_CONFIG_B64: ${{ secrets.RCLONE_CONFIG_B64 }}" in text
    assert "printf '%s' \"${RCLONE_CONFIG_B64}\" | base64 --decode" in text
    assert "chmod 600" in text
    assert "if: always()" in text
    assert "rclone config show" not in text
    assert "set -x" not in text


def test_launcher_uploads_data_before_manifest_and_verifies_readback() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    parquet_upload = text.index('rclone copyto "${parquet_path}"')
    readback = text.index('rclone copyto "${remote_parquet}"')
    manifest_upload = text.index('rclone copyto "${manifest_path}"')
    assert parquet_upload < readback < manifest_upload
    assert "sha256sum" in text
    assert "status == \"complete\"" in text
    assert "src.ingestion.nwp_archiver verify" in text


def test_launcher_uses_tested_python_selection_and_full_summary_contract() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "src.ingestion.nwp_archiver select" in text
    assert "select_uncommitted_cycles" not in text
    for field in (
        "latency_min=",
        "rows=",
        "parameters=",
        "grid=",
        "distance_km=",
        "valid_range=",
        "path=",
    ):
        assert field in text
    assert "trap report_failure ERR" in text


def test_workflow_cleans_the_exact_launcher_work_root() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'NWP_WORK_ROOT: ${{ runner.temp }}/nwp-archiver-work' in text
    assert 'rm -rf -- "${NWP_WORK_ROOT}"' in text
    assert 'nwp-archiver.*' not in text
```

- [ ] **Step 2: Run the static tests and verify RED**

Run:

```powershell
python -m pytest tests/unit/test_workflow_contract.py -q
```

Expected: FAIL because the launcher and workflow do not exist.

- [ ] **Step 3: Implement the Drive-aware launcher**

Create `scripts/start_nwp_archiver.sh`:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

profile=""
model=""
destination=""
issue_time_utc=""

while (($#)); do
  case "$1" in
    --profile) profile="${2:?}"; shift 2 ;;
    --model) model="${2:?}"; shift 2 ;;
    --destination) destination="${2:?}"; shift 2 ;;
    --issue-time-utc) issue_time_utc="${2:?}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

[[ "${profile}" =~ ^(smoke|full|catchup|scheduled)$ ]] || {
  echo "Invalid profile: ${profile}" >&2; exit 2;
}
[[ "${model}" =~ ^(ifs|aifs-single)$ ]] || {
  echo "Invalid model: ${model}" >&2; exit 2;
}
[[ "${destination}" == gdrive:* && "${destination}" != "gdrive:" ]] || {
  echo "NWP destination must be a non-root gdrive: path" >&2; exit 2;
}
[[ "${destination}" != *$'\n'* && "${destination}" != *".."* ]] || {
  echo "Unsafe NWP destination" >&2; exit 2;
}
[[ -n "${RCLONE_CONFIG:-}" && -s "${RCLONE_CONFIG}" ]] || {
  echo "RCLONE_CONFIG is missing or empty" >&2; exit 2;
}
if [[ "${profile}" =~ ^(catchup|scheduled)$ && -n "${issue_time_utc}" ]]; then
  echo "--issue-time-utc is not allowed for ${profile}" >&2
  exit 2
fi

runner_temp="${RUNNER_TEMP:-/tmp}"
if [[ -n "${NWP_WORK_ROOT:-}" ]]; then
  work_root="${NWP_WORK_ROOT}"
  [[ "${work_root}" == "${runner_temp%/}"/nwp-archiver-* ]] || {
    echo "NWP_WORK_ROOT must be a dedicated child of RUNNER_TEMP" >&2; exit 2;
  }
  [[ ! -e "${work_root}" ]] || {
    echo "NWP_WORK_ROOT already exists: ${work_root}" >&2; exit 2;
  }
  install -d -m 700 "${work_root}"
else
  work_root="$(mktemp -d "${runner_temp%/}/nwp-archiver.XXXXXX")"
fi
output_root="${work_root}/outbox"
verify_root="${work_root}/verify"
mkdir -p "${output_root}" "${verify_root}"

cleanup() {
  rm -rf -- "${work_root}"
}
trap cleanup EXIT

summary() {
  local line="$1"
  printf '%s\n' "${line}"
  if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
    printf '%s\n' "${line}" >> "${GITHUB_STEP_SUMMARY}"
  fi
}

current_issue="not-started"
report_failure() {
  local status=$?
  trap - ERR
  summary "- ${model} ${current_issue}: failed (exit=${status})"
  exit "${status}"
}
trap report_failure ERR

summary_manifest() {
  local archive_status="$1"
  local manifest="$2"
  local remote_path="$3"
  local manifest_issue latency rows parameters grid_lat grid_lon distance
  local valid_min valid_max
  manifest_issue="$(jq -er '.issue_time_utc' <<< "${manifest}")"
  latency="$(jq -er '
    ((.retrieved_at_utc | fromdateiso8601) -
     (.issue_time_utc | fromdateiso8601)) / 60
  ' <<< "${manifest}")"
  rows="$(jq -er '.row_count' <<< "${manifest}")"
  parameters="$(jq -er '.received_parameters | length' <<< "${manifest}")"
  grid_lat="$(jq -er '.grid_latitude' <<< "${manifest}")"
  grid_lon="$(jq -er '.grid_longitude' <<< "${manifest}")"
  distance="$(jq -er '.grid_distance_km' <<< "${manifest}")"
  valid_min="$(jq -er '.valid_time_min_utc' <<< "${manifest}")"
  valid_max="$(jq -er '.valid_time_max_utc' <<< "${manifest}")"
  summary "- ${model} ${manifest_issue}: ${archive_status}; latency_min=${latency}; rows=${rows}; parameters=${parameters}; grid=${grid_lat},${grid_lon}; distance_km=${distance}; valid_range=${valid_min}..${valid_max}; path=${remote_path}"
}

committed_manifest=""
committed_remote_base=""
manifest_is_committed() {
  local partition="$1"
  local issue="$2"
  local source="$3"
  local listing
  if ! listing="$(rclone lsf "${destination}" \
      --config "${RCLONE_CONFIG}" \
      --recursive --files-only \
      --include "${partition}/retrieved_at=*/manifest.json")"; then
    echo "Drive manifest listing failed for ${partition}" >&2
    return 2
  fi
  local path
  while IFS= read -r path; do
    [[ -n "${path}" ]] || continue
    local manifest
    if ! manifest="$(rclone cat "${destination}/${path}" --config "${RCLONE_CONFIG}")"; then
      echo "Drive manifest read failed: ${path}" >&2
      return 2
    fi
    if ! jq -e --arg issue "${issue}" --arg source "${source}" --arg model "${model}" '
        type == "object" and
        .status == "complete" and
        .schema_version == 1 and
        .issue_time_utc == $issue and
        .nwp_source == $source and
        .nwp_model == $model and
        (.retrieved_at_utc | type == "string") and
        (.requested_parameters | type == "array" and length > 0) and
        (.received_parameters | type == "array" and length > 0) and
        ((.requested_parameters | length) == (.requested_parameters | unique | length)) and
        ((.received_parameters | length) == (.received_parameters | unique | length)) and
        ((.requested_parameters | sort) == (.received_parameters | sort)) and
        (.requested_steps_h | type == "array" and length > 0) and
        (.received_steps_h | type == "array" and length > 0) and
        ((.requested_steps_h | length) == (.requested_steps_h | unique | length)) and
        ((.received_steps_h | length) == (.received_steps_h | unique | length)) and
        ((.requested_steps_h | sort) == (.received_steps_h | sort)) and
        (.row_count | type == "number" and . > 0) and
        (.grid_latitude | type == "number") and
        (.grid_longitude | type == "number") and
        (.grid_distance_km | type == "number" and . >= 0 and . <= 25) and
        (.parquet_bytes | type == "number" and . > 0) and
        (.parquet_sha256 | type == "string" and test("^[0-9a-f]{64}$")) and
        .dataset_url == "https://www.ecmwf.int/en/forecasts/datasets/open-data" and
        .licence_id == "CC-BY-4.0"
      ' <<< "${manifest}" >/dev/null; then
      echo "Malformed or incomplete committed manifest: ${path}" >&2
      return 2
    fi
    committed_manifest="${manifest}"
    committed_remote_base="${destination}/${path%/manifest.json}"
    return 0
  done <<< "${listing}"
  return 1
}

discovery_json="${work_root}/discovery.json"
discover_args=(
  python -m src.ingestion.nwp_archiver discover
  --model "${model}"
  --mode "${profile}"
  --result-json "${discovery_json}"
)
if [[ -n "${issue_time_utc}" ]]; then
  discover_args+=(--issue-time-utc "${issue_time_utc}")
fi
"${discover_args[@]}"

source_name="$(jq -er '.nwp_source' "${discovery_json}")"
mapfile -t candidates < <(jq -er '.candidate_issue_times_utc[]' "${discovery_json}")
((${#candidates[@]} > 0)) || {
  echo "No ECMWF candidate cycles discovered" >&2; exit 1;
}

committed=()
for issue in "${candidates[@]}"; do
  issue_date="${issue:0:10}"
  issue_hour="${issue:11:2}"
  partition="nwp_source=${source_name}/issue_date=${issue_date}/issue_hour=${issue_hour}"
  if [[ "${profile}" == "smoke" ]]; then
    continue
  elif manifest_is_committed "${partition}" "${issue}" "${source_name}"; then
    committed+=("${issue}")
    summary_manifest "skipped" "${committed_manifest}" "${committed_remote_base}"
  else
    status=$?
    ((status == 1)) || exit "${status}"
  fi
done

candidates_json="${work_root}/candidate-list.json"
committed_json="${work_root}/committed-list.json"
selection_json="${work_root}/selection.json"
jq -c '.candidate_issue_times_utc' "${discovery_json}" > "${candidates_json}"
jq -cn --args "${committed[@]}" '$ARGS.positional' > "${committed_json}"
python -m src.ingestion.nwp_archiver select \
  --mode "${profile}" \
  --candidates-json "${candidates_json}" \
  --committed-json "${committed_json}" \
  --result-json "${selection_json}"
mapfile -t selected < <(jq -er '.selected_issue_times_utc[]' "${selection_json}")

if ((${#selected[@]} == 0)); then
  summary "- ${model}: no uncommitted cycles"
  exit 0
fi

archive_profile="full"
[[ "${profile}" == "smoke" ]] && archive_profile="smoke"

for issue in "${selected[@]}"; do
  current_issue="${issue}"
  safe_issue="${issue//[:\-]/}"
  result_json="${work_root}/archive-${model}-${safe_issue}.json"
  python -m src.ingestion.nwp_archiver archive \
    --site-config configs/site_plts-ikn.yaml \
    --model "${model}" \
    --profile "${archive_profile}" \
    --issue-time-utc "${issue}" \
    --work-root "${work_root}/grib-${model}-${safe_issue}" \
    --output-root "${output_root}" \
    --result-json "${result_json}"

  parquet_path="$(jq -er '.parquet_path' "${result_json}")"
  manifest_path="$(jq -er '.manifest_path' "${result_json}")"
  relative_path="$(jq -er '.relative_path' "${result_json}")"
  local_sha="$(jq -er '.manifest.parquet_sha256' "${result_json}")"
  remote_base="${destination}/${relative_path}"
  remote_parquet="${remote_base}/weather_forecast_raw.parquet"
  remote_manifest="${remote_base}/manifest.json"
  readback="${verify_root}/${model}-${safe_issue}.parquet"
  readback_manifest="${verify_root}/${model}-${safe_issue}.manifest.json"
  verified_json="${verify_root}/${model}-${safe_issue}.verified.json"

  rclone copyto "${parquet_path}" "${remote_parquet}" \
    --config "${RCLONE_CONFIG}" --immutable --retries 3
  rclone copyto "${remote_parquet}" "${readback}" \
    --config "${RCLONE_CONFIG}" --retries 3
  remote_sha="$(sha256sum "${readback}" | awk '{print $1}')"
  [[ "${remote_sha}" == "${local_sha}" ]] || {
    echo "Remote Parquet SHA-256 mismatch for ${model} ${issue}" >&2
    exit 1
  }
  rclone copyto "${manifest_path}" "${remote_manifest}" \
    --config "${RCLONE_CONFIG}" --immutable --retries 3
  rclone copyto "${remote_manifest}" "${readback_manifest}" \
    --config "${RCLONE_CONFIG}" --retries 3
  python -m src.ingestion.nwp_archiver verify \
    --manifest "${readback_manifest}" \
    --parquet "${readback}" \
    --expected-source "${source_name}" \
    --expected-model "${model}" \
    --expected-issue-time-utc "${issue}" \
    --result-json "${verified_json}"
  verified_manifest="$(jq -cer '.manifest' "${verified_json}")"
  [[ "$(jq -er '.parquet_sha256' <<< "${verified_manifest}")" == "${local_sha}" ]]
  summary_manifest "committed" "${verified_manifest}" "${remote_base}"
done
```

- [ ] **Step 4: Implement the gated workflow**

Create `.github/workflows/nwp-archiver.yml`:

```yaml
name: NWP Archiver

on:
  workflow_dispatch:
    inputs:
      profile:
        description: Archive execution profile
        type: choice
        options: [smoke, full, catchup]
        default: smoke
        required: true
      models:
        description: ECMWF model selection
        type: choice
        options: [both, ifs, aifs-single]
        default: both
        required: true
      issue_time_utc:
        description: Optional exact cycle YYYY-MM-DDTHH:00:00Z for smoke/full
        type: string
        required: false
  schedule:
    - cron: "17 * * * *"

permissions:
  contents: read

concurrency:
  group: nwp-archiver-${{ github.repository }}
  cancel-in-progress: false

jobs:
  configure:
    runs-on: ubuntu-24.04
    outputs:
      run: ${{ steps.configure.outputs.run }}
      profile: ${{ steps.configure.outputs.profile }}
      issue_time_utc: ${{ steps.configure.outputs.issue_time_utc }}
      matrix: ${{ steps.configure.outputs.matrix }}
    steps:
      - name: Configure invocation
        id: configure
        env:
          EVENT_NAME: ${{ github.event_name }}
          ENABLED: ${{ vars.NWP_ARCHIVER_ENABLED }}
          INPUT_PROFILE: ${{ inputs.profile }}
          INPUT_MODELS: ${{ inputs.models }}
          INPUT_ISSUE_TIME: ${{ inputs.issue_time_utc }}
        shell: bash
        run: |
          set -Eeuo pipefail
          if [[ "${EVENT_NAME}" == "schedule" ]]; then
            if [[ "${ENABLED}" != "true" ]]; then
              echo "run=false" >> "${GITHUB_OUTPUT}"
              echo 'profile=scheduled' >> "${GITHUB_OUTPUT}"
              echo 'issue_time_utc=' >> "${GITHUB_OUTPUT}"
              echo 'matrix={"model":["ifs","aifs-single"]}' >> "${GITHUB_OUTPUT}"
              exit 0
            fi
            profile="scheduled"
            models="both"
            issue_time=""
          else
            profile="${INPUT_PROFILE}"
            models="${INPUT_MODELS}"
            issue_time="${INPUT_ISSUE_TIME}"
          fi
          if [[ "${profile}" == "catchup" && -n "${issue_time}" ]]; then
            echo "catchup does not accept issue_time_utc" >&2
            exit 2
          fi
          if [[ "${models}" == "both" ]]; then
            matrix='{"model":["ifs","aifs-single"]}'
          else
            matrix="$(jq -cn --arg model "${models}" '{model:[$model]}')"
          fi
          echo "run=true" >> "${GITHUB_OUTPUT}"
          echo "profile=${profile}" >> "${GITHUB_OUTPUT}"
          echo "issue_time_utc=${issue_time}" >> "${GITHUB_OUTPUT}"
          echo "matrix=${matrix}" >> "${GITHUB_OUTPUT}"

  archive:
    needs: configure
    if: needs.configure.outputs.run == 'true'
    runs-on: ubuntu-24.04
    timeout-minutes: 180
    env:
      NWP_WORK_ROOT: ${{ runner.temp }}/nwp-archiver-work
    strategy:
      fail-fast: false
      matrix: ${{ fromJSON(needs.configure.outputs.matrix) }}
    steps:
      - name: Checkout
        uses: actions/checkout@9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0
        with:
          persist-credentials: false

      - name: Set up Python 3.12
        uses: actions/setup-python@ece7cb06caefa5fff74198d8649806c4678c61a1
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: requirements-nwp.txt

      - name: Install Python dependencies
        shell: bash
        run: |
          set -Eeuo pipefail
          python -m pip install --disable-pip-version-check -r requirements-nwp.txt
          python -m pytest tests/unit tests/leakage tests/integration -q
          bash -n scripts/start_nwp_archiver.sh

      - name: Install pinned rclone
        shell: bash
        run: |
          set -Eeuo pipefail
          archive="${RUNNER_TEMP}/rclone-v1.74.4-linux-amd64.zip"
          curl --fail --silent --show-error --location \
            --output "${archive}" \
            "https://downloads.rclone.org/v1.74.4/rclone-v1.74.4-linux-amd64.zip"
          echo "fe435e0c36228e7c2f116a8701f01127bb1f694005fc11d1f27186c8bca4115d  ${archive}" |
            sha256sum --check
          unzip -q "${archive}" -d "${RUNNER_TEMP}/rclone"
          rclone_dir="${RUNNER_TEMP}/rclone/rclone-v1.74.4-linux-amd64"
          chmod 755 "${rclone_dir}/rclone"
          echo "${rclone_dir}" >> "${GITHUB_PATH}"

      - name: Reconstruct rclone configuration
        env:
          RCLONE_CONFIG_B64: ${{ secrets.RCLONE_CONFIG_B64 }}
        shell: bash
        run: |
          set -Eeuo pipefail
          umask 077
          config_dir="${RUNNER_TEMP}/nwp-rclone"
          config_path="${config_dir}/rclone.conf"
          install -d -m 700 "${config_dir}"
          printf '%s' "${RCLONE_CONFIG_B64}" | base64 --decode > "${config_path}"
          test -s "${config_path}"
          chmod 600 "${config_path}"
          printf 'RCLONE_CONFIG=%s\n' "${config_path}" >> "${GITHUB_ENV}"

      - name: Run NWP archiver
        env:
          NWP_DESTINATION: ${{ vars.NWP_DESTINATION }}
          RUN_PROFILE: ${{ needs.configure.outputs.profile }}
          RUN_MODEL: ${{ matrix.model }}
          RUN_ISSUE_TIME: ${{ needs.configure.outputs.issue_time_utc }}
        shell: bash
        run: |
          set -Eeuo pipefail
          args=(
            --profile "${RUN_PROFILE}"
            --model "${RUN_MODEL}"
            --destination "${NWP_DESTINATION}"
          )
          if [[ -n "${RUN_ISSUE_TIME}" ]]; then
            args+=(--issue-time-utc "${RUN_ISSUE_TIME}")
          fi
          bash scripts/start_nwp_archiver.sh "${args[@]}"

      - name: Cleanup credentials and transient files
        if: always()
        shell: bash
        run: |
          set -Eeuo pipefail
          rm -f -- "${RCLONE_CONFIG:-${RUNNER_TEMP}/nwp-rclone/rclone.conf}"
          rm -rf -- "${RUNNER_TEMP}/nwp-rclone" "${NWP_WORK_ROOT}"
```

- [ ] **Step 5: Verify workflow tests and shell syntax**

Run:

```powershell
python -m pytest tests/unit/test_workflow_contract.py -q
bash -n scripts/start_nwp_archiver.sh
```

Expected: `6 passed`; `bash -n` exits `0` with no output.

- [ ] **Step 6: Commit Task 9**

```powershell
git add scripts/start_nwp_archiver.sh .github/workflows/nwp-archiver.yml tests/unit/test_workflow_contract.py
git diff --cached --check
git commit -m "ci: automate NWP archive collection"
```

---

### Task 10: Operator Documentation, Attribution, and Full Local Gate

**Files:**
- Create: `README.md`
- Modify: `tests/unit/test_workflow_contract.py`

**Interfaces:**
- Produces: a safe operator quickstart and explicit ECMWF attribution.

- [ ] **Step 1: Add the failing documentation contract test**

Append to `tests/unit/test_workflow_contract.py`:

```python
def test_readme_contains_safety_gate_and_ecmwf_attribution() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    assert "NWP_ARCHIVER_ENABLED=false" in text
    assert "ECMWF" in text
    assert "CC-BY-4.0" in text
    assert "issue_time_utc" in text
    assert "valid_time_utc" in text
    assert "retrieved_at_utc" in text
    assert "No forecasting model" in text
```

- [ ] **Step 2: Run the documentation test and verify RED**

Run:

```powershell
python -m pytest tests/unit/test_workflow_contract.py::test_readme_contains_safety_gate_and_ecmwf_attribution -q
```

Expected: FAIL because `README.md` does not exist.

- [ ] **Step 3: Create the operator README**

Create `README.md`:

````markdown
# Forecasting Irradiance — PLTS-IKN

Sprint 0 starts by measuring and archiving what actually exists. No forecasting model is built by the S0-1 NWP archiver.

## S0-1 NWP archive

The archiver captures ECMWF Open Data IFS and AIFS Single forecasts for the nearest PLTS-IKN grid point. Every Parquet row preserves:

- `issue_time_utc`: when ECMWF issued the forecast run;
- `valid_time_utc`: when the forecast applies; and
- `retrieved_at_utc`: when this system actually finished retrieving the run.

These columns must never be collapsed because observed retrieval time is required to prevent issue-time leakage.

## Local offline verification

```powershell
python -m pip install -r requirements-nwp.txt
python -m pytest tests/unit tests/leakage tests/integration -q
```

## GitHub Actions safety sequence

1. Keep the repository variable `NWP_ARCHIVER_ENABLED=false`.
2. Run the `smoke` profile for both models.
3. Run one `full` issue for both models.
4. Repeat the same full issue and confirm an idempotent skip.
5. Run `catchup` for ECMWF cycles still retained upstream.
6. Enable scheduling only after Parquet and manifest read-back checks pass.

The Google Drive destination comes from `NWP_DESTINATION`; the rclone credential comes only from the encrypted `RCLONE_CONFIG_B64` GitHub secret.

## Attribution

Forecast data is provided by the European Centre for Medium-Range Weather Forecasts (ECMWF) Open Data service under the Creative Commons Attribution 4.0 International licence (`CC-BY-4.0`):

https://www.ecmwf.int/en/forecasts/datasets/open-data

The archive manifest records the source URL, licence identifier, client versions, requested issue cycle, selected grid point, and Parquet SHA-256.
````

- [ ] **Step 4: Run the complete local verification gate**

Run:

```powershell
python -m compileall -q src data_contracts
python -m pytest tests/unit tests/leakage tests/integration -q
bash -n scripts/start_nwp_archiver.sh
git diff --check
```

Expected: every command exits `0`; pytest reports zero failures.

- [ ] **Step 5: Audit repository and secret boundaries**

Run:

```powershell
$trackedFiles = @(git ls-files)
$credentialHits = rg -n -i `
  '(client_secret|refresh_token|access_token|token)\s*=\s*[A-Za-z0-9_./+-]{12,}|"(client_secret|refresh_token|access_token)"\s*:\s*"[^$][^"]{8,}"' `
  -- $trackedFiles
if ($LASTEXITCODE -gt 1) {
    throw "Repository credential scan failed to run."
}
if ($credentialHits) {
    throw "Potential credential value found in $($credentialHits.Count) tracked line(s); inspect locally without pasting values."
}

git status --short
git diff --stat
```

Expected:

- no credential value appears;
- only the secret **name** appears in workflow/documentation;
- unrelated PRD/DOCX/image files remain untracked and unmodified; and
- generated GRIB/Parquet/outbox files are ignored.

- [ ] **Step 6: Commit Task 10**

```powershell
git add README.md tests/unit/test_workflow_contract.py
git diff --cached --check
git commit -m "docs: document NWP archive operation"
```

---

### Task 11: Public-repository Checkpoint and Live Rollout

**Files:**
- No new source files.
- External state: canonical GitHub repository, GitHub Actions, and Google Drive staging archive.

**Interfaces:**
- Produces: live smoke/full/catch-up evidence and, only after approval, enabled scheduling.

- [ ] **Step 1: Reconfirm the public-disclosure boundary before push**

Run:

```powershell
gh repo view ompltsikn/Forecasting-Irradiance `
  --json nameWithOwner,visibility,isPrivate,viewerPermission

git log --oneline --decorate origin/main..main
git diff --stat origin/main..main
```

Expected: repository visibility is currently `PUBLIC`, permission is `ADMIN`, and the outgoing commits include the exact site configuration. Stop here and obtain one explicit user decision:

- approve pushing the exact site coordinates to the public repository; or
- change the canonical repository to private before pushing.

Do not infer this authorization from approval of the local design or plan.

- [ ] **Step 2: Push only after the disclosure decision**

After explicit authorization:

```powershell
git push origin main
git status --short --branch
```

Expected: push succeeds and `main...origin/main` is not ahead.

- [ ] **Step 3: Run and watch the credential/network smoke**

Define one race-safe dispatch helper in the same PowerShell session. It filters by workflow, `workflow_dispatch`, branch, exact pushed commit, and dispatch timestamp rather than assuming the newest run is ours:

```powershell
$repo = "ompltsikn/Forecasting-Irradiance"

function Invoke-NwpWorkflow {
    param(
        [Parameter(Mandatory)][ValidateSet("smoke", "full", "catchup")]
        [string]$Profile,
        [Parameter(Mandatory)][ValidateSet("both", "ifs", "aifs-single")]
        [string]$Models,
        [string]$IssueTimeUtc = ""
    )

    $headSha = (gh api "repos/$repo/commits/main" --jq .sha).Trim()
    if (-not $headSha) { throw "Unable to resolve canonical main SHA." }
    $dispatchedAfter = (Get-Date).ToUniversalTime().AddSeconds(-5)
    $createdFilter = ">=$($dispatchedAfter.ToString('yyyy-MM-ddTHH:mm:ssZ'))"

    gh workflow run nwp-archiver.yml `
      --repo $repo `
      -f "profile=$Profile" `
      -f "models=$Models" `
      -f "issue_time_utc=$IssueTimeUtc"
    if ($LASTEXITCODE -ne 0) { throw "Workflow dispatch failed." }

    $runId = $null
    for ($attempt = 1; $attempt -le 30 -and -not $runId; $attempt++) {
        Start-Sleep -Seconds 5
        $runs = gh run list `
          --repo $repo `
          --workflow nwp-archiver.yml `
          --event workflow_dispatch `
          --branch main `
          --commit $headSha `
          --created $createdFilter `
          --limit 20 `
          --json databaseId,createdAt,headSha,event |
            ConvertFrom-Json
        $runId = $runs |
            Where-Object {
                $_.headSha -eq $headSha -and $_.event -eq "workflow_dispatch"
            } |
            Sort-Object createdAt |
            Select-Object -First 1 -ExpandProperty databaseId
    }
    if (-not $runId) { throw "Dispatched workflow was not indexed within 150 seconds." }

    gh run watch $runId --repo $repo --exit-status
    if ($LASTEXITCODE -ne 0) { throw "NWP workflow $runId failed." }
    return [long]$runId
}

$smokeRunId = Invoke-NwpWorkflow -Profile smoke -Models both
```

Expected: both matrix jobs pass and each reports a `_smoke` Parquet upload plus remote SHA-256/manifest read-back.

- [ ] **Step 4: Verify smoke files from the configured Drive root**

Use the existing local config without printing it:

```powershell
$configPath = "$env:USERPROFILE\.config\rclone\nwp-rclone.conf"
$destination = "gdrive:_staging/nwp"
if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) {
    throw "rclone config is missing."
}

function Test-NwpRemoteAttempt {
    param([Parameter(Mandatory)][string]$RelativeManifestPath)

    $pattern = '^(?:_smoke/)?nwp_source=(ecmwf_ifs|ecmwf_aifs_single)/issue_date=(\d{4}-\d{2}-\d{2})/issue_hour=(\d{2})/retrieved_at=\d{8}T\d{6}Z/manifest\.json$'
    $match = [regex]::Match($RelativeManifestPath, $pattern)
    if (-not $match.Success) {
        throw "Unexpected manifest path: $RelativeManifestPath"
    }
    $source = $match.Groups[1].Value
    $model = if ($source -eq "ecmwf_ifs") { "ifs" } else { "aifs-single" }
    $issue = "$($match.Groups[2].Value)T$($match.Groups[3].Value):00:00Z"
    $relativeBase = $RelativeManifestPath.Substring(
        0, $RelativeManifestPath.Length - "/manifest.json".Length
    )
    $attemptRoot = Join-Path $env:TEMP ("nwp-verify-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $attemptRoot | Out-Null
    try {
        $manifestPath = Join-Path $attemptRoot "manifest.json"
        $parquetPath = Join-Path $attemptRoot "weather_forecast_raw.parquet"
        $resultPath = Join-Path $attemptRoot "verified.json"
        rclone copyto "$destination/$RelativeManifestPath" $manifestPath `
          --config $configPath
        if ($LASTEXITCODE -ne 0) { throw "Manifest download failed." }
        rclone copyto "$destination/$relativeBase/weather_forecast_raw.parquet" `
          $parquetPath --config $configPath
        if ($LASTEXITCODE -ne 0) { throw "Parquet download failed." }
        python -m src.ingestion.nwp_archiver verify `
          --manifest $manifestPath `
          --parquet $parquetPath `
          --expected-source $source `
          --expected-model $model `
          --expected-issue-time-utc $issue `
          --result-json $resultPath
        if ($LASTEXITCODE -ne 0) { throw "Remote artifact verification failed." }
        return Get-Content -LiteralPath $resultPath -Raw | ConvertFrom-Json
    }
    finally {
        $resolvedTemp = [IO.Path]::GetFullPath($env:TEMP).TrimEnd('\') + '\'
        $resolvedAttempt = [IO.Path]::GetFullPath($attemptRoot)
        if (-not $resolvedAttempt.StartsWith($resolvedTemp, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to clean a path outside TEMP: $resolvedAttempt"
        }
        Remove-Item -LiteralPath $resolvedAttempt -Recurse -Force
    }
}

$smokeManifests = @(
    rclone lsf "$destination/_smoke" `
      --config $configPath `
      --recursive `
      --files-only `
      --include "nwp_source=*/issue_date=*/issue_hour=*/retrieved_at=*/manifest.json"
)
if ($LASTEXITCODE -ne 0) { throw "Smoke manifest listing failed." }
$smokeEvidence = @(
    $smokeManifests | ForEach-Object {
        Test-NwpRemoteAttempt -RelativeManifestPath "_smoke/$_"
    }
)
$smokeSources = @($smokeEvidence.manifest.nwp_source | Sort-Object -Unique)
if (Compare-Object $smokeSources @("ecmwf_aifs_single", "ecmwf_ifs")) {
    throw "Smoke evidence does not contain both ECMWF sources."
}
```

Expected: at least one fully validated smoke attempt for both `ecmwf_ifs` and `ecmwf_aifs_single`; every manifest identity, schema, inventory, byte size, SHA-256, row count, valid range, and Parquet contract passes.

- [ ] **Step 5: Run one full issue and then prove idempotency**

Trigger `full` for both models, extract the committed issue identities from that exact run, then snapshot each partition before and after its explicit rerun:

```powershell
$runIds = @($smokeRunId)
$fullRunId = Invoke-NwpWorkflow -Profile full -Models both
$runIds += $fullRunId
$fullLog = gh run view $fullRunId --repo $repo --log
if ($LASTEXITCODE -ne 0) { throw "Unable to read full-run log." }

$commitPattern = '(?<model>ifs|aifs-single) (?<issue>\d{4}-\d{2}-\d{2}T\d{2}:00:00Z): committed;[^\r\n]*path=(?<path>gdrive:[^\r\n]+)'
$commits = @(
    [regex]::Matches(($fullLog -join "`n"), $commitPattern) |
        ForEach-Object {
            [pscustomobject]@{
                Model = $_.Groups["model"].Value
                Issue = $_.Groups["issue"].Value
                Path = $_.Groups["path"].Value.Trim()
            }
        } |
        Sort-Object Model, Issue -Unique
)
if ($commits.Count -ne 2) {
    throw "Expected exactly one newly committed full issue for each model."
}

foreach ($commit in $commits) {
    $source = if ($commit.Model -eq "ifs") { "ecmwf_ifs" } else { "ecmwf_aifs_single" }
    $issueDate = $commit.Issue.Substring(0, 10)
    $issueHour = $commit.Issue.Substring(11, 2)
    $partition = "nwp_source=$source/issue_date=$issueDate/issue_hour=$issueHour"
    $before = @(
        rclone lsf "$destination/$partition" `
          --config $configPath `
          --recursive --files-only `
          --include "retrieved_at=*/manifest.json"
    )
    if ($LASTEXITCODE -ne 0) { throw "Pre-rerun manifest snapshot failed." }

    $skipRunId = Invoke-NwpWorkflow `
      -Profile full `
      -Models $commit.Model `
      -IssueTimeUtc $commit.Issue
    $runIds += $skipRunId
    $skipLog = gh run view $skipRunId --repo $repo --log
    if (($skipLog -join "`n") -notmatch "$($commit.Model) $([regex]::Escape($commit.Issue)): skipped;") {
        throw "Explicit rerun did not report a committed-manifest skip."
    }

    $after = @(
        rclone lsf "$destination/$partition" `
          --config $configPath `
          --recursive --files-only `
          --include "retrieved_at=*/manifest.json"
    )
    if ($LASTEXITCODE -ne 0) { throw "Post-rerun manifest snapshot failed." }
    if (Compare-Object $before $after) {
        throw "Idempotent rerun changed the committed-attempt set."
    }
}
```

Expected: both explicit second invocations report `skipped`; the before/after manifest path sets are byte-for-byte identical, proving no new committed attempt was uploaded.

- [ ] **Step 6: Run the retained-window catch-up**

```powershell
$catchupRunId = Invoke-NwpWorkflow -Profile catchup -Models both
$runIds += $catchupRunId
```

If a 180-minute timeout leaves older uncommitted cycles, inspect the exact failed run, then invoke catch-up again. Idempotency must skip completed cycles and continue the remainder; do not treat timeout as success.

- [ ] **Step 7: Present evidence and request activation approval**

First validate every committed Bronze attempt and scan logs from the exact run IDs without printing any matched secret-like value:

```powershell
$bronzeManifests = @(
    rclone lsf $destination `
      --config $configPath `
      --recursive --files-only `
      --include "nwp_source=*/issue_date=*/issue_hour=*/retrieved_at=*/manifest.json"
)
if ($LASTEXITCODE -ne 0) { throw "Bronze manifest listing failed." }
$bronzeEvidence = @(
    $bronzeManifests | ForEach-Object {
        Test-NwpRemoteAttempt -RelativeManifestPath $_
    }
)
if (@($bronzeEvidence.manifest.nwp_source | Sort-Object -Unique).Count -ne 2) {
    throw "Bronze archive does not contain both model-qualified sources."
}

$allRunLogs = foreach ($runId in ($runIds | Sort-Object -Unique)) {
    gh run view $runId --repo $repo --log
    if ($LASTEXITCODE -ne 0) { throw "Unable to inspect log for run $runId." }
}
$secretLikePattern = '(?im)\[gdrive\]|(client_id|client_secret|refresh_token|access_token|token)\s*[=:]\s*(?!\*{3})(\S{8,})'
if (($allRunLogs -join "`n") -match $secretLikePattern) {
    throw "A credential-like value appears in an exact rollout run log; keep scheduling disabled."
}
```

Before enabling, report:

- exact smoke/full/catch-up run IDs and conclusions;
- IFS/AIFS issue cycles committed;
- row counts and valid-time ranges;
- actual selected grid coordinates/distance;
- measured retrieval latency;
- idempotent skip evidence;
- remote Drive paths; and
- confirmation that logs contain no credential values.

Keep:

```text
NWP_ARCHIVER_ENABLED=false
```

until the user explicitly approves activation based on this evidence.

- [ ] **Step 8: Enable scheduling only after explicit approval**

```powershell
$activatedAtUtc = (Get-Date).ToUniversalTime()
gh variable set NWP_ARCHIVER_ENABLED `
  --body "true" `
  --repo ompltsikn/Forecasting-Irradiance

gh variable list --repo ompltsikn/Forecasting-Irradiance
```

Expected: `NWP_ARCHIVER_ENABLED` is exactly `true`.

Define the rollback command immediately and use it on any scheduled failure, unexpected duplicate attempt, artifact validation/hash failure, or credential/log anomaly:

```powershell
function Disable-NwpScheduler {
    gh variable set NWP_ARCHIVER_ENABLED `
      --body "false" `
      --repo $repo
    if ($LASTEXITCODE -ne 0) {
        throw "URGENT: failed to disable NWP scheduler."
    }
}
```

- [ ] **Step 9: Observe two successive issue cycles before closing S0-1**

For both `ecmwf_ifs` and `ecmwf_aifs_single`, verify two successive scheduled issue cycles. Wrap the verification so any anomaly immediately restores the kill switch:

```powershell
try {
    $activeHeadSha = (gh api "repos/$repo/commits/main" --jq .sha).Trim()
    $activatedFilter = ">=$($activatedAtUtc.ToString('yyyy-MM-ddTHH:mm:ssZ'))"
    $scheduledRuns = @(
        gh run list `
          --repo $repo `
          --workflow nwp-archiver.yml `
          --event schedule `
          --branch main `
          --commit $activeHeadSha `
          --created $activatedFilter `
          --limit 20 `
          --json databaseId,status,conclusion,headSha,createdAt |
            ConvertFrom-Json |
            Where-Object {
                $_.status -eq "completed" -and
                $_.conclusion -eq "success" -and
                $_.headSha -eq $activeHeadSha
            }
    )
    if ($scheduledRuns.Count -lt 2) {
        throw "Fewer than two successful scheduled workflow runs are available."
    }
    $scheduledRunIds = @($scheduledRuns.databaseId)
    $scheduledLogs = foreach ($runId in $scheduledRunIds) {
        gh run view $runId --repo $repo --log
        if ($LASTEXITCODE -ne 0) { throw "Unable to read scheduled run $runId." }
    }
    if (($scheduledLogs -join "`n") -match $secretLikePattern) {
        throw "Credential-like text found in scheduled logs."
    }

    $currentManifestPaths = @(
        rclone lsf $destination `
          --config $configPath `
          --recursive --files-only `
          --include "nwp_source=*/issue_date=*/issue_hour=*/retrieved_at=*/manifest.json"
    )
    if ($LASTEXITCODE -ne 0) { throw "Scheduled archive listing failed." }
    $currentEvidence = @(
        $currentManifestPaths | ForEach-Object {
            Test-NwpRemoteAttempt -RelativeManifestPath $_
        }
    )

    $duplicateAttempts = $currentEvidence.manifest |
        Group-Object nwp_source, issue_time_utc |
        Where-Object Count -ne 1
    if ($duplicateAttempts) {
        throw "More than one committed attempt exists for a source/issue partition."
    }
    foreach ($source in @("ecmwf_ifs", "ecmwf_aifs_single")) {
        $latestTwo = @(
            $currentEvidence.manifest |
                Where-Object nwp_source -eq $source |
                Sort-Object { [datetimeoffset]$_.issue_time_utc } -Descending |
                Select-Object -First 2
        )
        if ($latestTwo.Count -ne 2) {
            throw "$source has fewer than two verified issue cycles."
        }
        $newest = [datetimeoffset]$latestTwo[0].issue_time_utc
        $previous = [datetimeoffset]$latestTwo[1].issue_time_utc
        if (($newest - $previous).TotalHours -ne 6) {
            throw "$source latest verified cycles are not successive 6-hour issues."
        }
    }
}
catch {
    Disable-NwpScheduler
    throw
}
```

The full validator invoked by `Test-NwpRemoteAttempt` proves, for every attempt:

- one complete manifest per source/issue primary partition;
- valid Parquet SHA-256 read-back;
- separate non-null issue, valid, and retrieval times; and
- no duplicate primary keys across committed attempts.

Only then mark S0-1 complete. Until then use the precise status `implemented`, `smoke-tested`, `full-tested`, or `scheduler-enabled`, whichever is supported by fresh evidence.

---

## Final Verification Matrix

| Claim | Required fresh evidence |
|---|---|
| Offline implementation works | complete pytest suite, compileall, `bash -n`, and `git diff --check` exit `0` |
| Canonical Parquet is stable | nullable numeric casts and physical Arrow schema tests pass even when model-specific columns are all null |
| Credential works in GitHub | manual smoke succeeds with remote upload, full manifest/Parquet validator read-back, and no credential-like log text |
| Full inventories work | full IFS and AIFS run succeeds with exact required parameters/steps, including supported `m` and `kg m^-2` precipitation encodings |
| Idempotency works | same explicit full issue reports skip without a new committed attempt |
| Catch-up works | retained missing cycles commit oldest-first and rerun skips completed cycles |
| Scheduler is safe to enable | all preceding evidence plus explicit user approval |
| S0-1 is complete | two successive scheduled issue cycles for both models |
