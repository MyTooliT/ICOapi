from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple, TypedDict, Union
import numbers

import yaml

from icoapi.models.models import ConfigFileInfoHeader

ALLOWED_YAML_CONTENT_TYPES = {
    "application/x-yaml",
    "application/yaml",
    "text/yaml",
    "text/x-yaml",
    "application/octet-stream",
    "text/plain",
}

ALLOWED_ENV_CONTENT_TYPES = {
    "text/plain",
    "application/octet-stream",
}

FIELD_DEFINITION_REQUIRED_KEYS = {"id", "label", "datatype", "type"}
SENSOR_REQUIRED_FIELDS = {
    "name",
    "sensor_id",
    "unit",
    "dimension",
    "phys_min",
    "phys_max",
    "volt_min",
    "volt_max",
}

CONFIG_BACKUP_DIRNAME = "backup"
BACKUP_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"

PathLike = Union[str, Path]


@dataclass
class ConfigFileDescription:
    endpoint: str
    title: str
    description: str
    filename: str

@dataclass
class ConfigFileDefinition:
    METADATA: ConfigFileDescription
    SENSORS: ConfigFileDescription
    DATASPACE: ConfigFileDescription


CONFIG_FILE_DEFINITIONS = ConfigFileDefinition(
    METADATA = ConfigFileDescription(
        endpoint="meta",
        title="Metadata Configuration",
        description="Configuration file containing your pre- and post-measurement metadata profiles.",
        filename="metadata.yaml"
    ),
    SENSORS=ConfigFileDescription(
        endpoint="sensors",
        title="Sensor Configuration",
        description="Configuration file containing sensor definitions and tool holder configurations.",
        filename="sensors.yaml"
    ),
    DATASPACE=ConfigFileDescription(
        endpoint="dataspace",
        title="Data Space Configuration",
        description="Configuration file containing your data space connection settings.",
        filename="dataspace.yaml"
    )
)

def is_valid_string(value: Any) -> bool:
    return bool(value.strip()) if isinstance(value, str) else False


def validate_yaml_info_header(payload: Any) -> list[str]:
    errors: list[str] = []
    info = payload.get("info")
    if not isinstance(info, dict):
        return ["info: expected mapping with metadata info"]

    schema_name = info.get("schema_name")
    if not is_valid_string(schema_name):
        errors.append("info -> schema_name: expected non-empty string")

    schema_version = info.get("schema_version")
    if not is_valid_string(schema_version):
        errors.append("info -> schema_version: expected non-empty string")

    name = info.get("config_name")
    if not is_valid_string(name):
        errors.append("info -> config_name: expected non-empty string")

    version = info.get("config_version")
    if not is_valid_string(version):
        errors.append("info -> config_version: expected non-empty string")

    date = info.get("config_date")
    if not is_valid_string(date):
        errors.append("info -> config_date: expected non-empty string")
    else:
        try:
            assert isinstance(date, str)
            datetime.fromisoformat(date)
        except ValueError:
            errors.append("info -> date: expected date in UTC timestamp format")
    return errors


def validate_metadata_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["Root document must be a mapping"]

    errors = validate_yaml_info_header(payload)

    default_profile_id = payload.get("default_profile_id")
    if not is_valid_string(default_profile_id):
        errors.append("default_profile_id: expected non-empty string")

    profiles = payload.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        errors.append("profiles: expected at least one profile definition")
    else:
        for profile_key, profile_value in profiles.items():
            errors.extend(validate_profile(profile_key, profile_value))

    return errors


def validate_profile(profile_key: str, profile_value: dict) -> list[str]:
    path_prefix = f"profiles -> {profile_key}"
    errors: list[str] = []

    if not isinstance(profile_value, dict):
        errors.append(f"{path_prefix}: expected mapping with profile configuration")
        return errors

    for field_name in ("id", "name"):
        field_value = profile_value.get(field_name)
        if not isinstance(field_value, str) or not field_value.strip():
            errors.append(f"{path_prefix} -> {field_name}: expected non-empty string")

    for stage in ("pre", "post"):
        if stage in profile_value:
            section = profile_value[stage]
            if not isinstance(section, dict):
                errors.append(f"{path_prefix} -> {stage}: expected mapping of sections")
            else:
                validate_sections(section, ["profiles", str(profile_key), stage], errors)

    return errors


def validate_sections(section: dict, path: list[str], errors: list[str]) -> None:
    if not isinstance(section, dict):
        errors.append(" -> ".join(path) + ": expected mapping")
        return

    for key, value in section.items():
        current_path = path + [str(key)]
        if not isinstance(value, dict):
            errors.append(f" -> ".join(current_path) + ": expected mapping for field definition or nested section")
            continue

        if is_field_definition(value):
            validate_field_definition(value, current_path, errors)
        else:
            validate_sections(value, current_path, errors)


def is_field_definition(value: dict[str, Any]) -> bool:
    return FIELD_DEFINITION_REQUIRED_KEYS.issubset(value.keys())


def validate_field_definition(field: dict[str, Any], path: list[str], errors: list[str]) -> None:
    for key in FIELD_DEFINITION_REQUIRED_KEYS:
        field_value = field.get(key)
        if not isinstance(field_value, str) or not field_value.strip():
            errors.append(" -> ".join(path + [key]) + ": expected non-empty string")

    options = field.get("options")
    if options is not None and not isinstance(options, list):
        errors.append(" -> ".join(path + ["options"]) + ": expected list when provided")


def validate_sensors_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["Root document must be a mapping"]

    errors = validate_yaml_info_header(payload)

    sensors = payload.get("sensors")
    sensor_ids: set[str] = set()

    if not isinstance(sensors, list) or not sensors:
        errors.append("sensors: expected non-empty list of sensor definitions")
    else:
        for index, sensor in enumerate(sensors):
            if not isinstance(sensor, dict):
                errors.append(f"sensors[{index}]: expected mapping with sensor definition")
                continue

            for field in SENSOR_REQUIRED_FIELDS:
                value = sensor.get(field)
                if value is None or (isinstance(value, str) and not value.strip()):
                    errors.append(f"sensors[{index}] -> {field}: expected non-empty value")

            sensor_id = sensor.get("sensor_id")
            if isinstance(sensor_id, str):
                if sensor_id in sensor_ids:
                    errors.append(f"sensors[{index}] -> sensor_id: duplicate sensor_id '{sensor_id}'")
                else:
                    sensor_ids.add(sensor_id)
            else:
                errors.append(f"sensors[{index}] -> sensor_id: expected string")

            for numeric_field in ("phys_min", "phys_max", "volt_min", "volt_max"):
                value = sensor.get(numeric_field)
                if not isinstance(value, numbers.Real):
                    errors.append(f"sensors[{index}] -> {numeric_field}: expected numeric value")

            sensor_type = sensor.get("sensor_type")
            if sensor_type is not None and not isinstance(sensor_type, str):
                errors.append(f"sensors[{index}] -> sensor_type: expected string when provided")

    configs = payload.get("sensor_configurations")
    if configs is not None:
        if not isinstance(configs, list):
            errors.append("sensor_configurations: expected list when provided")
        else:
            for cfg_index, config in enumerate(configs):
                if not isinstance(config, dict):
                    errors.append(f"sensor_configurations[{cfg_index}]: expected mapping")
                    continue

                for key in ("configuration_id", "configuration_name"):
                    value = config.get(key)
                    if not isinstance(value, str) or not value.strip():
                        errors.append(f"sensor_configurations[{cfg_index}] -> {key}: expected non-empty string")

                channels = config.get("channels")
                if channels is None:
                    continue
                if not isinstance(channels, dict) or not channels:
                    errors.append(f"sensor_configurations[{cfg_index}] -> channels: expected mapping of channel definitions")
                    continue

                for channel_key, channel_value in channels.items():
                    if not isinstance(channel_value, dict):
                        errors.append(
                            f"sensor_configurations[{cfg_index}] -> channels -> {channel_key}: expected mapping with channel definition"
                        )
                        continue

                    sensor_id = channel_value.get("sensor_id")
                    if not isinstance(sensor_id, str) or not sensor_id.strip():
                        errors.append(
                            f"sensor_configurations[{cfg_index}] -> channels -> {channel_key} -> sensor_id: expected non-empty string"
                        )
                    elif sensor_ids and sensor_id not in sensor_ids:
                        errors.append(
                            f"sensor_configurations[{cfg_index}] -> channels -> {channel_key} -> sensor_id: unknown sensor_id '{sensor_id}'"
                        )

    default_configuration_id = payload.get("default_configuration_id")
    if default_configuration_id is not None:
        if not isinstance(default_configuration_id, str):
            errors.append("default_configuration_id: expected str when provided")

    return errors


def validate_dataspace_payload(payload: Any) -> list[str]:
    if not isinstance(payload, dict):
        return ["Root document must be a mapping"]

    errors = validate_yaml_info_header(payload)

    connection = payload.get("connection")
    if not isinstance(connection, dict):
        errors.append("connection: expected mapping with connection details")
    else:
        if not isinstance(connection.get("enabled"), bool):
            errors.append("connection -> enabled: expected boolean")
        else:
            if connection.get("enabled") is False:
                return errors

            for key in ["protocol", "domain", "base_path", "username", "password", "bucket"]:
                value = connection.get(key)
                if not is_valid_string(value):
                    errors.append(f"connection -> {key}: expected non-empty string")



    return errors


def store_config_file(content: bytes, config_dir: PathLike, filename: str) -> Tuple[Optional[Path], Path]:
    config_path = Path(config_dir)
    config_path.mkdir(parents=True, exist_ok=True)

    target_path = config_path / filename
    backup_path = move_file_to_backup(target_path) if target_path.exists() else None

    target_path.write_bytes(content)
    return backup_path, target_path


def move_file_to_backup(file_path: Path) -> Path:
    backup_dir = file_path.parent / CONFIG_BACKUP_DIRNAME
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime(BACKUP_TIMESTAMP_FORMAT)
    backup_path = build_backup_path(backup_dir, file_path.name, timestamp)

    file_path.replace(backup_path)
    return backup_path


def build_backup_path(backup_dir: Path, filename: str, timestamp: str) -> Path:
    base_name, suffix = split_base_and_suffix(filename)
    backup_path = backup_dir / f"{base_name}__{timestamp}{suffix}"

    counter = 1
    while backup_path.exists():
        backup_path = backup_dir / f"{base_name}__{timestamp}_{counter}{suffix}"
        counter += 1

    return backup_path


def split_base_and_suffix(filename: str) -> tuple[str, str]:
    path = Path(filename)
    suffix = ''.join(path.suffixes)
    if suffix:
        base = filename[:-len(suffix)]
        if not base:
            base = filename
    else:
        base = filename
    return base, suffix


def parse_info_header_from_file(config_file: Path) -> ConfigFileInfoHeader | None:
    if config_file.suffix == ".yaml":
        with open(config_file, "r") as f:
            content = yaml.safe_load(f)
            errors = validate_yaml_info_header(content)
            if len(errors) > 0:
                return None
            else:
                info = content.get("info")
                return ConfigFileInfoHeader(
                    schema_name=info.get("schema_name"),
                    schema_version=info.get("schema_version"),
                    config_name=info.get("config_name"),
                    config_date=info.get("config_date"),
                    config_version=info.get("config_version")
                )
    else:
        return None


def list_config_backups(config_dir: PathLike, filename: str) -> list[tuple[str, str, ConfigFileInfoHeader | None]]:
    config_path = Path(config_dir)
    backup_dir = config_path / CONFIG_BACKUP_DIRNAME
    if not backup_dir.is_dir():
        return []

    base_name, suffix = split_base_and_suffix(filename)
    prefix = f"{base_name}__"
    entries: list[tuple[str, str, ConfigFileInfoHeader | None]] = []

    for entry in backup_dir.iterdir():
        if not Path.is_file(entry):
            continue

        entry_base, entry_suffix = split_base_and_suffix(entry.name)
        if entry_suffix != suffix or not entry_base.startswith(prefix):
            continue

        remainder = entry_base[len(prefix):]
        timestamp_piece, _, _ = remainder.partition('_')
        if not timestamp_piece:
            continue
        try:
            dt = datetime.strptime(timestamp_piece, BACKUP_TIMESTAMP_FORMAT)
        except ValueError:
            continue

        timestamp_iso = dt.isoformat()

        if filename.endswith(".yaml"):
            info_header = parse_info_header_from_file(entry)
        else:
            info_header = None

        entries.append((entry.name, timestamp_iso, info_header))

    entries.sort(key=lambda item: item[1], reverse=True)
    return entries

def is_backup_file_for(filename: str, backup_filename: str) -> bool:
    base_name, suffix = split_base_and_suffix(filename)
    backup_base, backup_suffix = split_base_and_suffix(backup_filename)

    if suffix != backup_suffix:
        return False

    prefix = f"{base_name}__"
    if not backup_base.startswith(prefix):
        return False

    remainder = backup_base[len(prefix):]
    timestamp_piece, _, _ = remainder.partition('_')
    if not timestamp_piece:
        return False

    try:
        datetime.strptime(timestamp_piece, BACKUP_TIMESTAMP_FORMAT)
    except ValueError:
        return False

    return True

