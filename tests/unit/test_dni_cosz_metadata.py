from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from src.characterisation.cov_ingest import CovInputError
from src.characterisation.dni_cosz_cli import validate_sensor_metadata


def _write_config(path: Path, value: bool | None) -> None:
    path.write_text(
        yaml.safe_dump(
            {
                "site": {"site_id": "PLTS-IKN"},
                "sensor_metadata": {
                    "dni_cosz": {"is_derived_tag": value}
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )


def test_metadata_boolean_must_equal_deterministic_decision_artifact(
    tmp_path: Path,
) -> None:
    config = tmp_path / "site.yaml"
    decision = tmp_path / "decision.json"
    _write_config(config, True)
    decision.write_text(
        json.dumps({"decision": "derived", "is_derived_tag": True}),
        encoding="utf-8",
    )

    validate_sensor_metadata(config, decision)

    _write_config(config, False)
    with pytest.raises(CovInputError, match="does not match"):
        validate_sensor_metadata(config, decision)


def test_unresolved_decision_requires_null_metadata(tmp_path: Path) -> None:
    config = tmp_path / "site.yaml"
    decision = tmp_path / "decision.json"
    _write_config(config, None)
    decision.write_text(
        json.dumps({"decision": "unresolved", "is_derived_tag": None}),
        encoding="utf-8",
    )

    validate_sensor_metadata(config, decision)

    _write_config(config, True)
    with pytest.raises(CovInputError, match="does not match"):
        validate_sensor_metadata(config, decision)


def test_metadata_rejects_non_boolean_values(tmp_path: Path) -> None:
    config = tmp_path / "site.yaml"
    decision = tmp_path / "decision.json"
    config.write_text(
        "site:\n  site_id: PLTS-IKN\nsensor_metadata:\n  dni_cosz:\n"
        "    is_derived_tag: unknown\n",
        encoding="utf-8",
    )
    decision.write_text(
        json.dumps({"decision": "unresolved", "is_derived_tag": None}),
        encoding="utf-8",
    )

    with pytest.raises(CovInputError, match="true, false, or null"):
        validate_sensor_metadata(config, decision)
