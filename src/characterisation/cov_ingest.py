"""Inventory and ingest raw SCADA COV ZIP/CSV exports with provenance."""

from __future__ import annotations

import csv
import hashlib
import io
import math
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd

from .cov_contract import CovContractError, parse_scada_tag


class CovInputError(RuntimeError):
    """Raised when the input set cannot be inspected safely."""


@dataclass(frozen=True)
class IngestionResult:
    """Canonical events plus every source-integrity diagnostic."""

    events: pd.DataFrame
    source_manifest: pd.DataFrame
    empty_entries: pd.DataFrame
    row_exceptions: pd.DataFrame
    timestamp_audit: pd.DataFrame
    strict_errors: tuple[str, ...]
    exact_duplicate_count: int
    timestamp_conflict_count: int


@dataclass(frozen=True)
class ReconciliationResult:
    """Drive/local inventory comparison and strict mismatches."""

    table: pd.DataFrame
    strict_errors: tuple[str, ...]


MANIFEST_COLUMNS = (
    "zip_name",
    "byte_size",
    "sha256",
    "csv_entry_count",
    "populated_csv_count",
    "empty_csv_count",
    "uncompressed_csv_bytes",
)
EMPTY_COLUMNS = ("source_zip", "source_csv", "uncompressed_bytes")
EXCEPTION_COLUMNS = (
    "source_zip",
    "source_csv",
    "source_row",
    "reason",
    "raw_row",
)
AUDIT_COLUMNS = (
    "source_zip",
    "source_csv",
    "full_tag",
    "row_count",
    "timestamp_shape",
    "coverage_start_raw",
    "coverage_end_raw",
    "order_violation_count",
)
EVENT_COLUMNS = (
    "full_tag",
    "site_label",
    "sts",
    "wb",
    "emi",
    "raw_parameter",
    "canonical_parameter",
    "parameter_class",
    "channel_group",
    "event_time_raw",
    "event_time",
    "event_time_ns",
    "timestamp_shape",
    "value",
    "object_caeid_raw",
    "source_zip",
    "source_csv",
    "source_row",
)

OFFSET_PATTERN = re.compile(r"[+-]\d{2}:?\d{2}$")


def sha256_file(path: Path) -> str:
    """Hash a file without loading it all into memory."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _zip_csv_entries(path: Path) -> list[zipfile.ZipInfo]:
    try:
        with zipfile.ZipFile(path) as archive:
            return [
                entry
                for entry in archive.infolist()
                if entry.filename.lower().endswith(".csv")
            ]
    except (OSError, zipfile.BadZipFile) as exc:
        raise CovInputError(f"cannot read ZIP {path.name}: {exc}") from exc


def build_source_manifest(raw_dir: Path) -> pd.DataFrame:
    """Build a deterministic, content-hashed manifest for all ZIP inputs."""

    raw_dir = Path(raw_dir)
    paths = sorted(raw_dir.glob("*.zip"), key=lambda item: item.name)
    if not paths:
        raise CovInputError(f"no ZIP files found in {raw_dir}")

    rows: list[dict[str, object]] = []
    for path in paths:
        entries = _zip_csv_entries(path)
        rows.append(
            {
                "zip_name": path.name,
                "byte_size": path.stat().st_size,
                "sha256": sha256_file(path),
                "csv_entry_count": len(entries),
                "populated_csv_count": sum(entry.file_size > 0 for entry in entries),
                "empty_csv_count": sum(entry.file_size == 0 for entry in entries),
                "uncompressed_csv_bytes": sum(entry.file_size for entry in entries),
            }
        )
    return pd.DataFrame(rows, columns=MANIFEST_COLUMNS).sort_values(
        "zip_name",
        kind="stable",
        ignore_index=True,
    )


def classify_timestamp_text(value: str) -> str:
    """Classify timestamp representation without assigning timezone semantics."""

    stripped = value.strip()
    if stripped.upper().endswith("Z"):
        return "utc_z"
    if OFFSET_PATTERN.search(stripped):
        return "offset"
    return "naive"


def _parse_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.upper().endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    return datetime.fromisoformat(normalized)


def _empty_frame(columns: tuple[str, ...]) -> pd.DataFrame:
    return pd.DataFrame(columns=list(columns))


def _entry_audit(
    *,
    source_zip: str,
    source_csv: str,
    full_tag: str,
    times: list[datetime],
    shapes: list[str],
) -> dict[str, object]:
    violations = 0
    for previous, current in zip(times, times[1:], strict=False):
        try:
            violations += current < previous
        except TypeError:
            pass
    unique_shapes = sorted(set(shapes))
    homogeneous = len(unique_shapes) == 1
    coverage_start = min(times).isoformat(sep=" ") if times and homogeneous else None
    coverage_end = max(times).isoformat(sep=" ") if times and homogeneous else None
    return {
        "source_zip": source_zip,
        "source_csv": source_csv,
        "full_tag": full_tag,
        "row_count": len(times),
        "timestamp_shape": "+".join(unique_shapes),
        "coverage_start_raw": coverage_start,
        "coverage_end_raw": coverage_end,
        "order_violation_count": int(violations),
    }


def _read_csv_entry(
    archive: zipfile.ZipFile,
    entry: zipfile.ZipInfo,
    *,
    source_zip: str,
) -> tuple[pd.DataFrame | None, list[dict[str, object]], dict[str, object] | None, list[str]]:
    exceptions: list[dict[str, object]] = []
    strict_errors: list[str] = []

    with archive.open(entry) as raw_stream:
        text_stream = io.TextIOWrapper(
            raw_stream,
            encoding="utf-8-sig",
            newline="",
        )
        reader = csv.reader(text_stream, delimiter=";", quotechar='"')
        try:
            header = next(reader)
        except StopIteration:
            exceptions.append(
                {
                    "source_zip": source_zip,
                    "source_csv": entry.filename,
                    "source_row": 1,
                    "reason": "missing_header",
                    "raw_row": "",
                }
            )
            strict_errors.append(
                f"{source_zip}/{entry.filename}: populated entry has no header"
            )
            return None, exceptions, None, strict_errors

        if len(header) != 3 or header[0].strip() != "date_time" or header[2].strip() != "object_caeid":
            exceptions.append(
                {
                    "source_zip": source_zip,
                    "source_csv": entry.filename,
                    "source_row": 1,
                    "reason": "unexpected_header",
                    "raw_row": ";".join(header),
                }
            )
            strict_errors.append(
                f"{source_zip}/{entry.filename}: unexpected populated CSV header"
            )
            return None, exceptions, None, strict_errors

        full_tag = header[1].strip()
        try:
            identity = parse_scada_tag(full_tag)
        except CovContractError as exc:
            exceptions.append(
                {
                    "source_zip": source_zip,
                    "source_csv": entry.filename,
                    "source_row": 1,
                    "reason": "invalid_tag_contract",
                    "raw_row": ";".join(header),
                }
            )
            strict_errors.append(f"{source_zip}/{entry.filename}: {exc}")
            return None, exceptions, None, strict_errors

        valid_rows: list[dict[str, object]] = []
        times: list[datetime] = []
        shapes: list[str] = []
        excluded_rows = 0
        for source_row, row in enumerate(reader, start=2):
            if len(row) != 3:
                excluded_rows += 1
                exceptions.append(
                    {
                        "source_zip": source_zip,
                        "source_csv": entry.filename,
                        "source_row": source_row,
                        "reason": "malformed_width",
                        "raw_row": ";".join(row),
                    }
                )
                continue

            event_time_raw, value_raw, object_caeid_raw = (
                field.strip() for field in row
            )
            try:
                event_time = _parse_timestamp(event_time_raw)
            except ValueError:
                excluded_rows += 1
                exceptions.append(
                    {
                        "source_zip": source_zip,
                        "source_csv": entry.filename,
                        "source_row": source_row,
                        "reason": "invalid_timestamp",
                        "raw_row": ";".join(row),
                    }
                )
                continue

            try:
                value = float(value_raw)
            except ValueError:
                value = math.nan
            if not math.isfinite(value):
                excluded_rows += 1
                exceptions.append(
                    {
                        "source_zip": source_zip,
                        "source_csv": entry.filename,
                        "source_row": source_row,
                        "reason": "non_numeric_value",
                        "raw_row": ";".join(row),
                    }
                )
                continue

            timestamp_shape = classify_timestamp_text(event_time_raw)
            times.append(event_time)
            shapes.append(timestamp_shape)
            valid_rows.append(
                {
                    "full_tag": identity.full_tag,
                    "site_label": identity.site_label,
                    "sts": identity.sts,
                    "wb": identity.wb,
                    "emi": identity.emi,
                    "raw_parameter": identity.raw_parameter,
                    "canonical_parameter": identity.canonical_parameter,
                    "parameter_class": identity.parameter_class.value,
                    "channel_group": identity.channel_group,
                    "event_time_raw": event_time_raw,
                    "event_time": event_time,
                    "event_time_ns": pd.Timestamp(event_time).value,
                    "timestamp_shape": timestamp_shape,
                    "value": value,
                    "object_caeid_raw": object_caeid_raw,
                    "source_zip": source_zip,
                    "source_csv": entry.filename,
                    "source_row": source_row,
                }
            )

        if excluded_rows:
            strict_errors.append(
                f"{source_zip}/{entry.filename}: {excluded_rows} populated rows excluded"
            )
        audit = _entry_audit(
            source_zip=source_zip,
            source_csv=entry.filename,
            full_tag=full_tag,
            times=times,
            shapes=shapes,
        )
        frame = pd.DataFrame(valid_rows, columns=EVENT_COLUMNS)
        return frame, exceptions, audit, strict_errors


def _quarantine_duplicates_and_conflicts(
    events: pd.DataFrame,
    exceptions: list[dict[str, object]],
) -> tuple[pd.DataFrame, int, int, list[str]]:
    if events.empty:
        return events, 0, 0, []

    sort_columns = [
        "full_tag",
        "event_time_ns",
        "source_zip",
        "source_csv",
        "source_row",
    ]
    events = events.sort_values(sort_columns, kind="stable", ignore_index=True)
    exact_key = ["full_tag", "event_time_ns", "value", "object_caeid_raw"]
    exact_duplicate_count = int(events.duplicated(exact_key, keep="first").sum())
    events = events.drop_duplicates(exact_key, keep="first", ignore_index=True)

    conflict_mask = events.duplicated(
        ["full_tag", "event_time_ns"],
        keep=False,
    )
    conflicted = events.loc[conflict_mask].copy()
    timestamp_conflict_count = int(
        conflicted[["full_tag", "event_time_ns"]].drop_duplicates().shape[0]
    )
    if timestamp_conflict_count:
        for row in conflicted.itertuples(index=False):
            exceptions.append(
                {
                    "source_zip": row.source_zip,
                    "source_csv": row.source_csv,
                    "source_row": int(row.source_row),
                    "reason": "timestamp_conflict",
                    "raw_row": (
                        f"{row.event_time_raw};{row.value};{row.object_caeid_raw}"
                    ),
                }
            )
        events = events.loc[~conflict_mask].reset_index(drop=True)

    strict_errors = (
        [f"{timestamp_conflict_count} conflicting tag/timestamp groups quarantined"]
        if timestamp_conflict_count
        else []
    )
    return (
        events,
        exact_duplicate_count,
        timestamp_conflict_count,
        strict_errors,
    )


def _categorize_event_strings(events: pd.DataFrame) -> pd.DataFrame:
    categorical_columns = (
        "full_tag",
        "site_label",
        "sts",
        "wb",
        "emi",
        "raw_parameter",
        "canonical_parameter",
        "parameter_class",
        "channel_group",
        "timestamp_shape",
        "object_caeid_raw",
        "source_zip",
        "source_csv",
    )
    for column in categorical_columns:
        if column in events:
            events[column] = events[column].astype("category")
    if "source_row" in events:
        events["source_row"] = events["source_row"].astype("int32")
    return events


def ingest_cov_directory(raw_dir: Path) -> IngestionResult:
    """Read every CSV entry from every ZIP and return audited canonical events."""

    raw_dir = Path(raw_dir)
    manifest = build_source_manifest(raw_dir)
    frames: list[pd.DataFrame] = []
    empty_entries: list[dict[str, object]] = []
    exceptions: list[dict[str, object]] = []
    audits: list[dict[str, object]] = []
    strict_errors: list[str] = []

    for manifest_row in manifest.itertuples(index=False):
        path = raw_dir / manifest_row.zip_name
        try:
            with zipfile.ZipFile(path) as archive:
                entries = sorted(
                    (
                        entry
                        for entry in archive.infolist()
                        if entry.filename.lower().endswith(".csv")
                    ),
                    key=lambda entry: entry.filename,
                )
                for entry in entries:
                    if entry.file_size == 0:
                        empty_entries.append(
                            {
                                "source_zip": path.name,
                                "source_csv": entry.filename,
                                "uncompressed_bytes": 0,
                            }
                        )
                        continue
                    frame, entry_exceptions, audit, entry_errors = _read_csv_entry(
                        archive,
                        entry,
                        source_zip=path.name,
                    )
                    exceptions.extend(entry_exceptions)
                    strict_errors.extend(entry_errors)
                    if audit is not None:
                        audits.append(audit)
                    if frame is not None and not frame.empty:
                        frames.append(frame)
        except (OSError, zipfile.BadZipFile) as exc:
            raise CovInputError(f"cannot read ZIP {path.name}: {exc}") from exc

    events = (
        pd.concat(frames, ignore_index=True)
        if frames
        else _empty_frame(EVENT_COLUMNS)
    )
    timestamp_shapes = sorted(set(events.get("timestamp_shape", pd.Series(dtype=str)).astype(str)))
    if len(timestamp_shapes) > 1:
        strict_errors.append(
            f"mixed timestamp shapes: {', '.join(timestamp_shapes)}"
        )

    (
        events,
        exact_duplicate_count,
        timestamp_conflict_count,
        conflict_errors,
    ) = _quarantine_duplicates_and_conflicts(events, exceptions)
    strict_errors.extend(conflict_errors)
    events = _categorize_event_strings(events)

    exception_frame = pd.DataFrame(exceptions, columns=EXCEPTION_COLUMNS)
    if not exception_frame.empty:
        exception_frame = exception_frame.sort_values(
            ["source_zip", "source_csv", "source_row", "reason"],
            kind="stable",
            ignore_index=True,
        )

    return IngestionResult(
        events=events,
        source_manifest=manifest,
        empty_entries=pd.DataFrame(empty_entries, columns=EMPTY_COLUMNS).sort_values(
            ["source_zip", "source_csv"],
            kind="stable",
            ignore_index=True,
        )
        if empty_entries
        else _empty_frame(EMPTY_COLUMNS),
        row_exceptions=exception_frame,
        timestamp_audit=pd.DataFrame(audits, columns=AUDIT_COLUMNS).sort_values(
            ["source_zip", "source_csv"],
            kind="stable",
            ignore_index=True,
        )
        if audits
        else _empty_frame(AUDIT_COLUMNS),
        strict_errors=tuple(strict_errors),
        exact_duplicate_count=exact_duplicate_count,
        timestamp_conflict_count=timestamp_conflict_count,
    )


def reconcile_inventory(
    local_manifest: pd.DataFrame,
    reference_inventory: Path,
) -> ReconciliationResult:
    """Compare local ZIP filename/size metadata with connector-observed Drive data."""

    reference = pd.read_csv(reference_inventory, dtype={"drive_file_id": "string"})
    required = {"drive_file_id", "zip_name", "byte_size"}
    missing = required - set(reference.columns)
    if missing:
        raise CovInputError(
            f"reference inventory missing columns: {', '.join(sorted(missing))}"
        )

    local = local_manifest[["zip_name", "byte_size"]].rename(
        columns={"byte_size": "local_byte_size"}
    )
    drive = reference[["drive_file_id", "zip_name", "byte_size"]].rename(
        columns={"byte_size": "drive_byte_size"}
    )
    table = local.merge(drive, on="zip_name", how="outer", sort=True)

    def status(row: pd.Series) -> str:
        if pd.isna(row["local_byte_size"]):
            return "drive_only"
        if pd.isna(row["drive_byte_size"]):
            return "local_only"
        if int(row["local_byte_size"]) != int(row["drive_byte_size"]):
            return "size_mismatch"
        return "matched"

    table["match_status"] = table.apply(status, axis=1)
    table = table[
        [
            "zip_name",
            "drive_file_id",
            "local_byte_size",
            "drive_byte_size",
            "match_status",
        ]
    ].sort_values("zip_name", kind="stable", ignore_index=True)
    error_count = int((table["match_status"] != "matched").sum())
    strict_errors = (
        (f"{error_count} inventory reconciliation error",)
        if error_count
        else ()
    )
    return ReconciliationResult(table=table, strict_errors=strict_errors)
