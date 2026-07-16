from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from data_contracts.nwp_schema import (
    NwpContractError,
    available_nwp_as_of,
    validate_nwp_frame,
)
from src.ingestion.nwp_archiver import measured_latency_minutes, require_utc


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
