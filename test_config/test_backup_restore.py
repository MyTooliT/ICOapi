from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
import yaml

CONFIG_BACKUP_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _upload_metadata(client, payload: dict[str, Any], content_type: str = "application/x-yaml") -> None:
    body = yaml.safe_dump(payload, sort_keys=False).encode("utf-8")
    response = client.post(
        "/config/meta",
        files={"metadata_file": ("metadata.yaml", io.BytesIO(body), content_type)},
    )
    assert response.status_code == 200, response.text


def _get_file_entry(files: list[dict[str, Any]], filename: str) -> dict[str, Any]:
    for entry in files:
        if entry["filename"] == filename:
            return entry
    raise AssertionError(f"No config entry for {filename}")


@pytest.mark.config
def test_backup_listing_initially_empty(client, temp_config_dir: Path):
    response = client.get("/config/backup")
    assert response.status_code == 200
    data = response.json()

    assert {file_["filename"] for file_ in data["files"]} == {
        "metadata.yaml",
        "sensors.yaml",
        ".env",
    }

    for file_ in data["files"]:
        assert file_["backup"] == []
        # ensure no backup directory created yet
        assert not (temp_config_dir / "backup").exists()


@pytest.mark.config
def test_metadata_backup_created_after_second_upload(client, temp_config_dir: Path):
    payload_v1 = {
        "info": {"version": "1.0"},
        "profiles": {
            "default": {
                "id": "default",
                "name": "Default",
            }
        },
    }
    payload_v2 = {
        "info": {"version": "2.0"},
        "profiles": {
            "default": {
                "id": "default",
                "name": "Default",
            }
        },
    }

    _upload_metadata(client, payload_v1)
    _upload_metadata(client, payload_v2)

    response = client.get("/config/backup")
    assert response.status_code == 200
    metadata_entry = _get_file_entry(response.json()["files"], "metadata.yaml")

    assert len(metadata_entry["backup"]) == 1
    backup_info = metadata_entry["backup"][0]
    backup_filename = backup_info["filename"]
    timestamp = backup_info["timestamp"]

    # timestamp is returned in ISO format (UTC)
    datetime.strptime(timestamp, CONFIG_BACKUP_TIMESTAMP_FORMAT)

    backup_path = temp_config_dir / "backup" / backup_filename
    assert backup_path.is_file()

    with backup_path.open("r", encoding="utf-8") as fh:
        backup_content = yaml.safe_load(fh)
    assert backup_content["info"]["version"] == "1.0"

    with (temp_config_dir / "metadata.yaml").open("r", encoding="utf-8") as fh:
        active_content = yaml.safe_load(fh)
    assert active_content["info"]["version"] == "2.0"


@pytest.mark.config
def test_restore_uses_backup_without_deleting_source(client, temp_config_dir: Path):
    payload_v1 = {
        "info": {"version": "1.0"},
        "profiles": {
            "default": {
                "id": "default",
                "name": "Default",
            }
        },
    }
    payload_v2 = {
        "info": {"version": "2.0"},
        "profiles": {
            "default": {
                "id": "default",
                "name": "Default",
            }
        },
    }

    _upload_metadata(client, payload_v1)
    _upload_metadata(client, payload_v2)
    response = client.get("/config/backup")
    metadata_entry = _get_file_entry(response.json()["files"], "metadata.yaml")
    backup_filename = metadata_entry["backup"][0]["filename"]

    # mutate active file to a different variant so restore has something to replace
    (temp_config_dir / "metadata.yaml").write_text(
        yaml.safe_dump({"info": {"version": "3.0"}, "profiles": {"default": {"id": "default", "name": "Default"}}}, sort_keys=False),
        encoding="utf-8",
    )

    restore_response = client.put(
        "/config/restore",
        json={"filename": "metadata.yaml", "backup_filename": backup_filename},
    )
    assert restore_response.status_code == 200, restore_response.text
    assert restore_response.json()["detail"] == "Configuration restored successfully."

    # active file now matches v1 again
    restored_content = yaml.safe_load((temp_config_dir / "metadata.yaml").read_text(encoding="utf-8"))
    assert restored_content["info"]["version"] == "1.0"

    # the source backup is still present alongside the newly created backup (for v3)
    backups = list((temp_config_dir / "backup").iterdir())
    assert any(path.name == backup_filename for path in backups)
    backup_versions = {
        yaml.safe_load(path.read_text(encoding="utf-8"))["info"]["version"]
        for path in backups
    }
    assert "3.0" in backup_versions


@pytest.mark.config
def test_restore_rejects_invalid_backup_for_target(client, temp_config_dir: Path):
    payload_v1 = {
        "info": {"version": "1.0"},
        "profiles": {
            "default": {
                "id": "default",
                "name": "Default",
            }
        },
    }
    _upload_metadata(client, payload_v1)
    _upload_metadata(client, payload_v1)

    response = client.get("/config/backup")
    metadata_entry = _get_file_entry(response.json()["files"], "metadata.yaml")
    backup_filename = metadata_entry["backup"][0]["filename"]

    restore_response = client.put(
        "/config/restore",
        json={"filename": "sensors.yaml", "backup_filename": backup_filename},
    )
    assert restore_response.status_code == 400
    assert "Invalid configuration restore" in restore_response.json()["detail"]

    missing_response = client.put(
        "/config/restore",
        json={"filename": "metadata.yaml", "backup_filename": "does-not-exist.yaml"},
    )
    assert missing_response.status_code == 404
    assert "Requested configuration backup not found." in missing_response.json()["detail"]
