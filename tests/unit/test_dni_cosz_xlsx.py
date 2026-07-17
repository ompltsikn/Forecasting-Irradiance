from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.characterisation.dni_cosz_xlsx import ingest_historical_xlsx


def _write_workbook(path: Path, channel: str, values: list[float]) -> None:
    frame = pd.DataFrame(
        {
            "Unnamed: 0": range(len(values) + 1),
            "date_time": [
                pd.Timestamp("2026-06-01 12:00:00"),
                pd.Timestamp("2026-06-01 12:01:00"),
                pd.NaT,
            ],
            channel: [*values, 99999.0],
            "object_caeid": ["0", "0", "helper"],
            "Tanggal/Waktu": [
                pd.Timestamp("2026-06-01 00:00:00"),
                pd.Timestamp("2026-06-01 00:05:00"),
                pd.Timestamp("2026-06-01 00:10:00"),
            ],
        }
    )
    frame.to_excel(path, index=False)


def test_historical_xlsx_ingest_reads_only_raw_cov_columns(tmp_path: Path) -> None:
    path = tmp_path / "GHI_PLTS-IKN_WS-1_2026-Juni.xlsx"
    _write_workbook(path, "GHI_PLTS-IKN_WS-1_2026-Juni", [600.0, 601.0])
    _write_workbook(
        tmp_path / "GHI_Daily_Accum_PLTS-IKN_WS-1_2026-Juni.xlsx",
        "GHI_Daily_Accum_PLTS-IKN_WS-1_2026-Juni",
        [1000.0, 2000.0],
    )

    result = ingest_historical_xlsx(tmp_path)

    assert result.strict_errors == ()
    assert result.events[["emi", "channel_group", "value"]].to_dict("records") == [
        {"emi": "EMI01", "channel_group": "GHI", "value": 600.0},
        {"emi": "EMI01", "channel_group": "GHI", "value": 601.0},
    ]
    assert result.events["source_xlsx"].eq(path.name).all()
    assert result.events["object_caeid_raw"].tolist() == ["0", "0"]
    assert result.source_manifest["xlsx_name"].tolist() == [path.name]


def test_historical_xlsx_ingest_supports_legacy_filename_and_full_tag_header(
    tmp_path: Path,
) -> None:
    path = tmp_path / "DNI cosZ WS-1 PLTS IKN Agustus 2025.xlsx"
    full_tag = (
        "PLTS IKN / STS09 / WB09_EMI01 / MEAS / "
        "DIRECT HORIZONTAL IRRADIANCE (DNI*cosZ)"
    )
    _write_workbook(path, full_tag, [450.0, 451.0])

    result = ingest_historical_xlsx(tmp_path)

    assert result.strict_errors == ()
    assert result.events[["emi", "channel_group", "value"]].to_dict("records") == [
        {"emi": "EMI01", "channel_group": "DNIcosZ", "value": 450.0},
        {"emi": "EMI01", "channel_group": "DNIcosZ", "value": 451.0},
    ]
    assert result.source_manifest.loc[0, "filename_schema"] == "legacy"
