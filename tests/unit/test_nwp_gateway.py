from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ingestion.nwp_archiver import (
    ArchiveProfile,
    NwpModel,
    SitePoint,
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


def test_discovery_request_uses_inventory_available_to_every_ifs_cycle() -> None:
    gateway = FakeGateway()
    latest = discover_latest_issue(
        gateway,
        model=NwpModel.IFS,
        profile_name=ArchiveProfile.FULL,
    )
    assert latest == ISSUE
    request = gateway.latest_calls[0]
    assert request["stream"] == "oper"
    assert request["type"] == "fc"
    assert request["levtype"] == "sfc"
    assert request["step"] == list(range(0, 91, 3))
    assert request["param"] == [
        "ssrd",
        "tcc",
        "2t",
        "2d",
        "10u",
        "10v",
        "tp",
        "sp",
        "tcwv",
        "mucape",
    ]
    assert "date" not in request
    assert "time" not in request
    assert "area" not in request


def test_latest_result_is_frozen_into_explicit_retrieve(tmp_path: Path) -> None:
    profile = request_profile_for(NwpModel.IFS, ArchiveProfile.SMOKE)
    gateway = FakeGateway()
    latest = discover_latest_issue(
        gateway,
        model=NwpModel.IFS,
        profile_name=ArchiveProfile.SMOKE,
    )
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


def test_retrieval_timestamp_is_captured_only_after_every_download(
    tmp_path: Path,
) -> None:
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


def test_transient_retrieval_is_retried_with_a_finite_bound(
    tmp_path: Path,
) -> None:
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


def test_decoder_captures_grib_packing_error(monkeypatch, tmp_path: Path) -> None:
    module = __import__("src.ingestion.nwp_archiver", fromlist=["dummy"])
    path = tmp_path / "solar.grib2"
    path.write_bytes(b"GRIB")
    handle = object()
    handles = iter((handle, None))
    released: list[object] = []
    values: dict[str, object] = {
        "dataDate": 20260716,
        "dataTime": 600,
        "validityDate": 20260716,
        "validityTime": 1200,
        "shortName": "ssrd",
        "units": "J m**-2",
        "startStep": 0,
        "endStep": 6,
        "stepType": "accum",
        "packingError": 256.0,
    }
    monkeypatch.setitem(
        sys.modules,
        "eccodes",
        SimpleNamespace(
            codes_get=lambda _, key: values[key],
            codes_grib_find_nearest=lambda *_: (
                SimpleNamespace(value=999_488.0, lat=-1.0, lon=116.75),
            ),
            codes_grib_new_from_file=lambda _: next(handles),
            codes_release=released.append,
        ),
    )

    decoded = module._decode_grib_path(path, SITE)

    assert decoded[0].packing_error == 256.0
    assert released == [handle]
