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
            "--model",
            "ifs",
            "--mode",
            "smoke",
            "--result-json",
            str(result_path),
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


@pytest.mark.parametrize(
    ("issue_hour", "expected_steps"),
    [
        (6, tuple(range(0, 91, 3))),
        (12, tuple(range(0, 145, 3))),
    ],
)
def test_archive_issue_uses_the_exact_issue_specific_ifs_inventory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    issue_hour: int,
    expected_steps: tuple[int, ...],
) -> None:
    issue = datetime(2026, 7, 16, issue_hour, tzinfo=UTC)
    run = nwp.RetrievedRun(
        model=nwp.NwpModel.IFS,
        issue_time_utc=issue,
        retrieved_at_utc=RETRIEVED,
        files_by_group={},
    )
    captured: dict[str, object] = {}
    sentinel = object()

    def fake_retrieve(gateway, profile, issue_time_utc, work_root, *, clock):
        captured["retrieve_profile"] = profile
        captured["retrieve_issue"] = issue_time_utc
        return run

    def fake_decode(retrieved_run, site):
        profile = captured["retrieve_profile"]
        return tuple(
            SimpleNamespace(parameter=parameter, end_step_h=step)
            for parameter in profile.parameters
            for step in profile.request_steps_h
        )

    def fake_normalise(fields, *, site, profile, **kwargs):
        captured["normalise_profile"] = profile
        return "frame"

    def fake_write(frame, **kwargs):
        captured.update({"frame": frame, **kwargs})
        return sentinel

    monkeypatch.setattr(nwp, "retrieve_explicit_run", fake_retrieve)
    monkeypatch.setattr(nwp, "decode_nearest_site_fields", fake_decode)
    monkeypatch.setattr(nwp, "normalise_run", fake_normalise)
    monkeypatch.setattr(nwp, "_dependency_versions", lambda: ("0.3.30", "2.47.0"))
    monkeypatch.setattr(nwp, "write_archive_attempt", fake_write)

    output_root = tmp_path / "out"
    result = nwp.archive_issue(
        gateway=LatestGateway(),
        site=nwp.load_site_point(Path("configs/site_plts-ikn.yaml")),
        model=nwp.NwpModel.IFS,
        profile_name=nwp.ArchiveProfile.FULL,
        issue_time_utc=issue,
        work_root=tmp_path / "work",
        output_root=output_root,
        clock=lambda: RETRIEVED,
    )

    assert result is sentinel
    assert captured["retrieve_issue"] == issue
    assert captured["retrieve_profile"] is captured["normalise_profile"]
    assert captured["requested_steps_h"] == expected_steps
    assert captured["received_steps_h"] == expected_steps
    assert captured["output_root"] == output_root
    assert captured["smoke"] is False


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
            "--mode",
            "scheduled",
            "--candidates-json",
            str(candidates_path),
            "--committed-json",
            str(committed_path),
            "--result-json",
            str(result_path),
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
            "--site-config",
            "configs/site_plts-ikn.yaml",
            "--model",
            "ifs",
            "--profile",
            "smoke",
            "--issue-time-utc",
            "2026-07-16T06:00:00Z",
            "--work-root",
            str(tmp_path / "work"),
            "--output-root",
            str(output_root),
            "--result-json",
            str(result_path),
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
            "--manifest",
            str(artifact.manifest_path),
            "--parquet",
            str(artifact.parquet_path),
            "--expected-source",
            "ecmwf_ifs",
            "--expected-model",
            "ifs",
            "--expected-issue-time-utc",
            "2026-07-16T06:00:00Z",
            "--result-json",
            str(result_path),
        ]
    ) == 0
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["manifest"]["row_count"] == 2
