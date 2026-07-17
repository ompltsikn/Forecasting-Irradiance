"""Ingest raw COV columns preserved inside historical Weather Station XLSX files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .cov_contract import ParameterClass
from .cov_ingest import sha256_file


INSTANTANEOUS_FILE = re.compile(
    r"^(GHI|DHI|DNIcosZ)_PLTS-IKN_WS-([1-5])_(\d{4})-(.+)\.xlsx$",
    re.IGNORECASE,
)
LEGACY_INSTANTANEOUS_FILE = re.compile(
    r"^(GHI|DHI|DNI\s*cosZ)\s+WS-([1-5])\s+PLTS\s+IKN(?:\s+.+)?\.xlsx$",
    re.IGNORECASE,
)
WS_TO_LOCATION = {
    "1": ("EMI01", "STS09", "WB09"),
    "2": ("EMI02", "STS05", "WB05"),
    "3": ("EMI03", "STS06", "WB06"),
    "4": ("EMI04", "STS04", "WB04"),
    "5": ("EMI05", "STS02", "WB02"),
}
CHANNEL_SPELLING = {"GHI": "GHI", "DHI": "DHI", "DNICOSZ": "DNIcosZ"}


@dataclass(frozen=True)
class HistoricalXlsxIngestion:
    """Historical instantaneous events and their file-level provenance."""

    events: pd.DataFrame
    source_manifest: pd.DataFrame
    strict_errors: tuple[str, ...]


def parse_instantaneous_filename(name: str) -> tuple[str, str, str] | None:
    """Return channel, WS number, and naming schema for an instantaneous file."""

    standard = INSTANTANEOUS_FILE.fullmatch(name)
    if standard is not None:
        channel = CHANNEL_SPELLING[standard.group(1).upper()]
        return channel, standard.group(2), "standardized"
    legacy = LEGACY_INSTANTANEOUS_FILE.fullmatch(name)
    if legacy is not None:
        token = re.sub(r"\s+", "", legacy.group(1)).upper()
        channel = CHANNEL_SPELLING[token]
        return channel, legacy.group(2), "legacy"
    return None


def _matching_files(root: Path) -> list[tuple[Path, tuple[str, str, str]]]:
    matches: list[tuple[Path, tuple[str, str, str]]] = []
    for path in sorted(Path(root).rglob("*.xlsx"), key=lambda item: item.as_posix()):
        identity = parse_instantaneous_filename(path.name)
        if identity is not None:
            matches.append((path, identity))
    return matches


def ingest_historical_xlsx(root: Path) -> HistoricalXlsxIngestion:
    """Read only raw date/value/object columns; never consume helper grids."""

    root = Path(root)
    event_frames: list[pd.DataFrame] = []
    manifest_rows: list[dict[str, object]] = []
    errors: list[str] = []
    for path, (channel, ws, filename_schema) in _matching_files(root):
        emi, sts, wb = WS_TO_LOCATION[ws]
        try:
            raw = pd.read_excel(path, usecols="A:E", engine="openpyxl")
        except Exception as exc:  # pandas/openpyxl expose several workbook errors
            errors.append(f"{path.name}: cannot read workbook: {exc}")
            continue
        if "date_time" not in raw.columns or "object_caeid" not in raw.columns:
            errors.append(f"{path.name}: missing raw date_time/object_caeid columns")
            continue
        columns = list(raw.columns)
        date_position = columns.index("date_time")
        object_position = columns.index("object_caeid")
        value_candidates = columns[date_position + 1 : object_position]
        if len(value_candidates) != 1:
            errors.append(
                f"{path.name}: expected one raw value column between date_time and "
                f"object_caeid, found {len(value_candidates)}"
            )
            continue
        value_column = value_candidates[0]
        parsed_time = pd.to_datetime(raw["date_time"], errors="coerce")
        parsed_value = pd.to_numeric(raw[value_column], errors="coerce")
        valid = parsed_time.notna() & parsed_value.notna()
        events = pd.DataFrame(
            {
                "emi": emi,
                "sts": sts,
                "wb": wb,
                "channel_group": channel,
                "parameter_class": ParameterClass.INSTANTANEOUS_IRRADIANCE.value,
                "event_time_raw": raw.loc[valid, "date_time"].astype(str),
                "event_time": parsed_time.loc[valid],
                "event_time_ns": parsed_time.loc[valid].astype("int64"),
                "value": parsed_value.loc[valid].astype("float64"),
                "object_caeid_raw": raw.loc[valid, "object_caeid"].astype("string"),
                "source_xlsx": path.name,
                "source_xlsx_relative_path": path.relative_to(root).as_posix(),
            }
        ).reset_index(drop=True)
        event_frames.append(events)
        manifest_rows.append(
            {
                "xlsx_name": path.name,
                "relative_path": path.relative_to(root).as_posix(),
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
                "ws": f"WS-{ws}",
                "emi": emi,
                "channel_group": channel,
                "filename_schema": filename_schema,
                "raw_row_count": int(len(events)),
                "coverage_start_raw": (
                    None if events.empty else str(events["event_time_raw"].iloc[0])
                ),
                "coverage_end_raw": (
                    None if events.empty else str(events["event_time_raw"].iloc[-1])
                ),
            }
        )

    events = (
        pd.concat(event_frames, ignore_index=True)
        if event_frames
        else pd.DataFrame(
            columns=[
                "emi",
                "sts",
                "wb",
                "channel_group",
                "parameter_class",
                "event_time_raw",
                "event_time",
                "event_time_ns",
                "value",
                "object_caeid_raw",
                "source_xlsx",
                "source_xlsx_relative_path",
            ]
        )
    )
    if not events.empty:
        events = events.sort_values(
            ["emi", "channel_group", "event_time_ns", "source_xlsx_relative_path"],
            kind="stable",
            ignore_index=True,
        ).drop_duplicates(
            ["emi", "channel_group", "event_time_ns", "value", "object_caeid_raw"],
            keep="first",
            ignore_index=True,
        )
    manifest = pd.DataFrame(manifest_rows)
    if not manifest.empty:
        manifest = manifest.sort_values(
            "relative_path", kind="stable", ignore_index=True
        )
    return HistoricalXlsxIngestion(events, manifest, tuple(errors))
