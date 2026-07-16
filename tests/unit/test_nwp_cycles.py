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
        EXPECTED[2],
        EXPECTED[-1],
    )


def test_scheduled_selects_latest_then_oldest_missing() -> None:
    missing = {EXPECTED[2], EXPECTED[-1]}
    committed = set(EXPECTED) - missing
    assert select_uncommitted_cycles(EXPECTED, committed, SelectionMode.SCHEDULED) == (
        EXPECTED[-1],
        EXPECTED[2],
    )


def test_scheduled_does_not_duplicate_latest() -> None:
    committed = set(EXPECTED[:-1])
    assert select_uncommitted_cycles(EXPECTED, committed, SelectionMode.SCHEDULED) == (
        EXPECTED[-1],
    )


@pytest.mark.parametrize("mode", [SelectionMode.SMOKE, SelectionMode.FULL])
def test_manual_single_run_modes_select_latest_only(mode: SelectionMode) -> None:
    assert select_uncommitted_cycles(EXPECTED, set(), mode) == (EXPECTED[-1],)
