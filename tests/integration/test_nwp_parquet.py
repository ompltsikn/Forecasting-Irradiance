from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

from src.ingestion.nwp_archiver import (
    ArchiveProfile,
    NwpModel,
    RetrievedRun,
    SitePoint,
    decode_nearest_site_fields,
    normalise_run,
    request_profile_for,
    sha256_file,
    write_archive_attempt,
)


UTC = timezone.utc
ISSUE = datetime(2026, 7, 16, 6, tzinfo=UTC)
RETRIEVED = datetime(2026, 7, 16, 7, 15, 30, tzinfo=UTC)
SITE = SitePoint(
    "PLTS-IKN",
    -0.9911713315158186,
    116.63811127764585,
    85.0,
    "Asia/Makassar",
)


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
            "Nj": 2,
            "latitudeOfFirstGridPointInDegrees": -0.75,
            "latitudeOfLastGridPointInDegrees": -1.0,
            "longitudeOfFirstGridPointInDegrees": 116.50,
            "longitudeOfLastGridPointInDegrees": 116.75,
            "iDirectionIncrementInDegrees": 0.25,
            "jDirectionIncrementInDegrees": 0.25,
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
        write_ssrd_message(
            stream,
            end_step=45,
            values=[
                8_100_000.0,
                16_200_000.0,
                8_100_000.0,
                16_200_000.0,
            ],
        )
        write_ssrd_message(
            stream,
            end_step=48,
            values=[
                8_640_000.0,
                17_280_000.0,
                8_640_000.0,
                17_280_000.0,
            ],
        )
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
    assert frame["grid_distance_km"].iloc[0] == pytest.approx(
        12.478274049682074
    )
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
