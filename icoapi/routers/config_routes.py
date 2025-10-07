from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
import logging
import os
from typing import Any

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from starlette.responses import FileResponse

from icoapi.models.globals import TridentHandler, get_trident_client, setup_trident
from icoapi.models.models import ConfigFile, ConfigFileBackup, ConfigFileInfoHeader, ConfigResponse, \
    ConfigRestoreRequest
from icoapi.models.trident import StorageClient
from icoapi.scripts.config_helper import (
    ALLOWED_ENV_CONTENT_TYPES,
    ALLOWED_YAML_CONTENT_TYPES,
    CONFIG_BACKUP_DIRNAME,
    CONFIG_FILE_DEFINITIONS,
    is_backup_file_for,
    list_config_backups,
    parse_info_header_from_file, store_config_file,
    validate_dataspace_payload,
    validate_metadata_payload,
    validate_sensors_payload
)
from icoapi.scripts.errors import (
    HTTP_400_INVALID_CONFIG_RESTORE_EXCEPTION,
    HTTP_400_INVALID_CONFIG_RESTORE_SPEC, HTTP_400_INVALID_YAML_EXCEPTION,
    HTTP_400_INVALID_YAML_SPEC,
    HTTP_404_CONFIG_BACKUP_NOT_FOUND_EXCEPTION,
    HTTP_404_CONFIG_BACKUP_NOT_FOUND_SPEC,
    HTTP_404_FILE_NOT_FOUND_EXCEPTION,
    HTTP_404_FILE_NOT_FOUND_SPEC,
    HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_EXCEPTION,
    HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_SPEC,
    HTTP_422_DATASPACE_SCHEMA_EXCEPTION, HTTP_422_DATASPACE_SCHEMA_SPEC, HTTP_422_METADATA_SCHEMA_EXCEPTION,
    HTTP_422_METADATA_SCHEMA_SPEC,
    HTTP_422_SENSORS_SCHEMA_EXCEPTION,
    HTTP_422_SENSORS_SCHEMA_SPEC,
    HTTP_500_CONFIG_LIST_EXCEPTION,
    HTTP_500_CONFIG_LIST_SPEC,
    HTTP_500_CONFIG_RESTORE_EXCEPTION,
    HTTP_500_CONFIG_RESTORE_SPEC,
    HTTP_500_CONFIG_WRITE_EXCEPTION,
    HTTP_500_CONFIG_WRITE_SPEC,
)
from icoapi.scripts.file_handling import get_config_dir

router = APIRouter(
    prefix="/config",
    tags=["Configuration"]
)

logger = logging.getLogger(__name__)

async def validate_and_parse_yaml_file(file: UploadFile) -> (Any, bytes):
    if file.content_type and file.content_type.lower() not in ALLOWED_YAML_CONTENT_TYPES:
        raise HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_EXCEPTION

    raw_content = await file.read()
    if not raw_content:
        logger.error("Received empty YAML payload for sensors upload")
        raise HTTP_400_INVALID_YAML_EXCEPTION

    try:
        parsed_yaml = yaml.safe_load(raw_content)
    except yaml.YAMLError as exc:
        logger.error(f"Failed to parse uploaded sensors YAML: {exc}")
        raise HTTP_400_INVALID_YAML_EXCEPTION

    return parsed_yaml, raw_content


def get_info_header_from_yaml(parsed_yaml: Any) -> ConfigFileInfoHeader:
    info = parsed_yaml["info"]
    return ConfigFileInfoHeader(
        config_version=info["config_version"],
        config_date=info["config_date"],
        config_name=info["config_name"],
        schema_name=info["schema_name"],
        schema_version=info["schema_version"],
    )


def file_response(config_dir: str, filename: str, media_type: str) -> FileResponse:
    try:
        return FileResponse(
            os.path.join(config_dir, filename),
            media_type=media_type,
            filename=filename,
        )
    except FileNotFoundError:
        raise HTTP_404_FILE_NOT_FOUND_EXCEPTION


def store_config(content: bytes, config_dir: str, filename: str):
    try:
        backup_path, target_path = store_config_file(content, config_dir, filename)
    except OSError as exc:
        logger.exception(f"Failed to store {filename} in {config_dir}")
        raise HTTP_500_CONFIG_WRITE_EXCEPTION from exc

    if backup_path:
        logger.info(f"Existing {filename} moved to backup at {backup_path}")
    else:
        logger.info(f"No existing {filename} found in {config_dir}; storing new file")

    logger.info(f"{filename} saved to {target_path}")
    return backup_path, target_path


@router.get("/meta", responses={
    200: {"description": "File was found and returned."},
    404: HTTP_404_FILE_NOT_FOUND_SPEC,
})
async def get_metadata_file(config_dir: str = Depends(get_config_dir)) -> FileResponse:
    return file_response(config_dir, CONFIG_FILE_DEFINITIONS.METADATA.filename, "application/x-yaml")


@router.post(
    "/meta",
    responses={
        200: {"description": "Metadata configuration uploaded successfully."},
        400: HTTP_400_INVALID_YAML_SPEC,
        415: HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_SPEC,
        422: HTTP_422_METADATA_SCHEMA_SPEC,
        500: HTTP_500_CONFIG_WRITE_SPEC,
    },
    response_model=ConfigFileInfoHeader
)
async def upload_metadata_file(
    file: UploadFile = File(..., description="YAML metadata configuration file"),
    config_dir: str = Depends(get_config_dir),
):
    parsed_yaml, raw_content = await validate_and_parse_yaml_file(file)

    if parsed_yaml is None:
        errors = ["YAML document must not be empty"]
    else:
        errors = validate_metadata_payload(parsed_yaml)

    if errors:
        logger.error(f"Metadata YAML validation failed: {errors}")
        error_detail = f"{HTTP_422_METADATA_SCHEMA_EXCEPTION.detail} Errors: {'; '.join(errors)}"
        raise HTTPException(
            status_code=HTTP_422_METADATA_SCHEMA_EXCEPTION.status_code,
            detail=error_detail,
        )

    header = get_info_header_from_yaml(parsed_yaml)

    store_config(raw_content, config_dir, CONFIG_FILE_DEFINITIONS.METADATA.filename)
    return header


@router.get("/sensors", responses={
    200: {"description": "File was found and returned."},
    404: HTTP_404_FILE_NOT_FOUND_SPEC,
})
async def get_sensors_file(config_dir: str = Depends(get_config_dir)) -> FileResponse:
    return file_response(config_dir, CONFIG_FILE_DEFINITIONS.SENSORS.filename, "application/x-yaml")


@router.post(
    "/sensors",
    responses={
        200: {"description": "Sensor configuration uploaded successfully."},
        400: HTTP_400_INVALID_YAML_SPEC,
        415: HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_SPEC,
        422: HTTP_422_SENSORS_SCHEMA_SPEC,
        500: HTTP_500_CONFIG_WRITE_SPEC,
    },
    response_model=ConfigFileInfoHeader
)
async def upload_sensors_file(
    file: UploadFile = File(..., description="YAML sensors configuration file"),
    config_dir: str = Depends(get_config_dir),
):
    parsed_yaml, raw_content = await validate_and_parse_yaml_file(file)

    if parsed_yaml is None:
        errors = ["YAML document must not be empty"]
    else:
        errors = validate_sensors_payload(parsed_yaml)

    if errors:
        logger.error(f"Sensors YAML validation failed: {errors}")
        error_detail = f"{HTTP_422_SENSORS_SCHEMA_EXCEPTION.detail} Errors: {'; '.join(errors)}"
        raise HTTPException(
            status_code=HTTP_422_SENSORS_SCHEMA_EXCEPTION.status_code,
            detail=error_detail,
        )

    header = get_info_header_from_yaml(parsed_yaml)

    store_config(raw_content, config_dir, CONFIG_FILE_DEFINITIONS.SENSORS.filename)
    return header


@router.post(
    "/dataspace",
    responses={
        200: {"description": "Dataspace configuration uploaded successfully."},
        400: HTTP_400_INVALID_YAML_SPEC,
        415: HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_SPEC,
        422: HTTP_422_DATASPACE_SCHEMA_SPEC,
        500: HTTP_500_CONFIG_WRITE_SPEC,
    },
    response_model=ConfigFileInfoHeader
)
async def upload_dataspace_file(
    file: UploadFile = File(..., description="YAML sensors configuration file"),
    config_dir: str = Depends(get_config_dir),
):
    parsed_yaml, raw_content = await validate_and_parse_yaml_file(file)

    if parsed_yaml is None:
        errors = ["YAML document must not be empty"]
    else:
        errors = validate_dataspace_payload(parsed_yaml)

    if errors:
        logger.error(f"Dataspace YAML validation failed: {errors}")
        error_detail = f"{HTTP_422_DATASPACE_SCHEMA_EXCEPTION.detail} Errors: {'; '.join(errors)}"
        raise HTTPException(
            status_code=HTTP_422_DATASPACE_SCHEMA_EXCEPTION.status_code,
            detail=error_detail,
        )

    header = get_info_header_from_yaml(parsed_yaml)

    store_config(raw_content, config_dir, CONFIG_FILE_DEFINITIONS.DATASPACE.filename)

    TridentHandler.client = None
    await setup_trident()

    return header


@router.get("/env", responses={
    200: {"description": "File was found and returned."},
    404: HTTP_404_FILE_NOT_FOUND_SPEC,
})
async def get_env_file(config_dir: str = Depends(get_config_dir)) -> FileResponse:
    return file_response(config_dir, CONFIG_FILE_DEFINITIONS.ENV.filename, "text/plain")


@router.post(
    "/env",
    responses={
        200: {"description": "Environment file uploaded successfully."},
        415: HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_SPEC,
        500: HTTP_500_CONFIG_WRITE_SPEC,
    },
)
async def upload_env_file(
    file: UploadFile = File(..., description="Environment variables file"),
    config_dir: str = Depends(get_config_dir),
):
    if file.content_type and file.content_type.lower() not in ALLOWED_ENV_CONTENT_TYPES:
        raise HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_EXCEPTION

    raw_content = await file.read()
    if raw_content is None:
        raw_content = b""

    store_config(raw_content, config_dir, CONFIG_FILE_DEFINITIONS.ENV.filename)
    return {"detail": "Environment file uploaded successfully."}


@router.get(
    "/backup",
    responses={
        200: {"description": "Configuration backups returned successfully."},
        500: HTTP_500_CONFIG_LIST_SPEC,
    },
)
async def get_config_backups(config_dir: str = Depends(get_config_dir)) -> ConfigResponse:
    try:
        files: list[ConfigFile] = []
        for f in fields(CONFIG_FILE_DEFINITIONS):
            DEF = getattr(CONFIG_FILE_DEFINITIONS, f.name)
            backup_entries = [
                ConfigFileBackup(filename=backup_name, timestamp=timestamp, info_header=info_header)
                for backup_name, timestamp, info_header in list_config_backups(config_dir, DEF.filename)
            ]
            info_header = parse_info_header_from_file(Path(config_dir) / DEF.filename)
            files.append(
                ConfigFile(
                    name=DEF.title,
                    filename=DEF.filename,
                    backup=backup_entries,
                    endpoint=DEF.endpoint,
                    timestamp=datetime.fromtimestamp(os.path.getmtime(f"{config_dir}/{DEF.filename}")).isoformat(),
                    description=DEF.description,
                    info_header=info_header,
                )
            )
    except OSError as exc:
        logger.exception(f"Failed to list configuration backups in {config_dir}")
        raise HTTP_500_CONFIG_LIST_EXCEPTION from exc

    return ConfigResponse(files=files)


@router.put(
    "/restore",
    responses={
        200: {"description": "Configuration restored successfully."},
        400: HTTP_400_INVALID_CONFIG_RESTORE_SPEC,
        404: HTTP_404_CONFIG_BACKUP_NOT_FOUND_SPEC,
        500: HTTP_500_CONFIG_RESTORE_SPEC,
    },
)
async def restore_config_file(
    payload: ConfigRestoreRequest,
    config_dir: str = Depends(get_config_dir),
):
    config_lookup = [d.filename for d in vars(CONFIG_FILE_DEFINITIONS).values()]
    if payload.filename not in config_lookup:
        logger.error(f"Restore requested for unknown configuration file: {payload.filename}")
        raise HTTP_400_INVALID_CONFIG_RESTORE_EXCEPTION

    backup_dir = Path(config_dir) / CONFIG_BACKUP_DIRNAME
    backup_path = backup_dir / payload.backup_filename

    if not backup_path.is_file():
        logger.error(f"Requested backup for restore not found: {backup_path}")
        raise HTTP_404_CONFIG_BACKUP_NOT_FOUND_EXCEPTION

    if not is_backup_file_for(payload.filename, payload.backup_filename):
        logger.error(
            f"Backup {payload.backup_filename} does not match configuration {payload.filename}")
        raise HTTP_400_INVALID_CONFIG_RESTORE_EXCEPTION

    try:
        backup_content = backup_path.read_bytes()
    except OSError as exc:
        logger.exception(f"Failed to read backup file {backup_path}")
        raise HTTP_500_CONFIG_RESTORE_EXCEPTION from exc

    try:
        store_config(backup_content, config_dir, payload.filename)
    except HTTPException as exc:
        if exc is HTTP_500_CONFIG_WRITE_EXCEPTION:
            raise HTTP_500_CONFIG_RESTORE_EXCEPTION from exc
        raise

    logger.info(
        f"Restored {payload.filename} from backup {payload.backup_filename}")

    if payload.filename == CONFIG_FILE_DEFINITIONS.DATASPACE.filename:
        TridentHandler.client = None
        await setup_trident()
        logger.info("Trident client re-initialized")
    return {"detail": "Configuration restored successfully."}
