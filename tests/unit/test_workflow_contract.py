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
    assert (
        "fe435e0c36228e7c2f116a8701f01127bb1f694005fc11d1f27186c8bca4115d"
        in text
    )
    assert "persist-credentials: false" in text


def test_rclone_secret_is_step_scoped_and_cleaned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "RCLONE_CONFIG_B64: ${{ secrets.RCLONE_CONFIG_B64 }}" in text
    assert 'printf \'%s\' "${RCLONE_CONFIG_B64}" | base64 --decode' in text
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
    assert 'status == "complete"' in text
    assert "src.ingestion.nwp_archiver verify" in text


def test_launcher_uses_tested_python_selection_and_full_summary_contract() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "src.ingestion.nwp_archiver select" in text
    assert "select_uncommitted_cycles" not in text
    assert "jq -cn '$ARGS.positional' --args" in text
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


def test_launcher_normalises_fractional_timestamps_for_latency_summary() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    assert text.count('sub("\\\\.[0-9]+Z$"; "Z")') == 2


def test_launcher_treats_an_empty_selection_as_a_clean_idempotent_skip() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    assert (
        "mapfile -t selected < <(jq -r "
        "'.selected_issue_times_utc[]?' \"${selection_json}\")"
    ) in text
    assert "jq -er '.selected_issue_times_utc[]'" not in text


def test_workflow_cleans_the_exact_launcher_work_root() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    archive_start = text.index("\n  archive:")
    strategy_start = text.index("\n    strategy:", archive_start)
    job_preamble = text[archive_start:strategy_start]
    assert "runner.temp" not in job_preamble
    assert text.count(
        'NWP_WORK_ROOT: ${{ runner.temp }}/nwp-archiver-work'
    ) == 2
    assert 'rm -rf -- "${NWP_WORK_ROOT}"' in text
    assert "nwp-archiver.*" not in text


def test_workflow_serialises_google_drive_writes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    strategy_start = text.index("\n    strategy:")
    steps_start = text.index("\n    steps:", strategy_start)
    strategy = text[strategy_start:steps_start]
    assert "max-parallel: 1" in strategy


def test_readme_contains_safety_gate_and_ecmwf_attribution() -> None:
    text = Path("README.md").read_text(encoding="utf-8")
    assert "NWP_ARCHIVER_ENABLED=false" in text
    assert "ECMWF" in text
    assert "CC-BY-4.0" in text
    assert "issue_time_utc" in text
    assert "valid_time_utc" in text
    assert "retrieved_at_utc" in text
    assert "No forecasting model" in text


def test_cov_requirements_pin_the_xlsx_reader_used_by_s0_3() -> None:
    requirements = Path("requirements-cov.txt").read_text(encoding="utf-8")
    assert "openpyxl==3.1.5" in requirements.splitlines()


def test_nwp_workflow_installs_dependencies_for_the_suite_it_runs() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "requirements-nwp.txt" in text
    assert "requirements-cov.txt" in text
