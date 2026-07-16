from __future__ import annotations

import importlib
from pathlib import Path

import pytest


MODULE_PATH = Path("src/ingestion/nwp_archiver.py")


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


def test_full_ifs_profile_is_exact() -> None:
    module = load_archiver_module()
    profile = module.request_profile_for(module.NwpModel.IFS, module.ArchiveProfile.FULL)
    assert profile.nwp_source == "ecmwf_ifs"
    assert profile.request_steps_h == tuple(range(0, 145, 3))
    assert profile.output_steps_h == tuple(range(0, 145, 3))
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
