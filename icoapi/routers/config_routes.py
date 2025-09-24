from dataclasses import asdict
import logging
import os

import yaml
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from starlette.responses import FileResponse

from icoapi.models.models import ConfigFile, ConfigFileBackup, ConfigResponse
from icoapi.scripts.config_helper import (
    ALLOWED_ENV_CONTENT_TYPES,
    ALLOWED_YAML_CONTENT_TYPES,
    ENV_FILENAME,
    METADATA_FILENAME,
    SENSORS_FILENAME,
    list_config_backups,
    store_config_file,
    validate_metadata_payload,
    validate_sensors_payload,
)
from icoapi.scripts.errors import (
    HTTP_400_INVALID_YAML_EXCEPTION,
    HTTP_400_INVALID_YAML_SPEC,
    HTTP_404_FILE_NOT_FOUND_EXCEPTION,
    HTTP_404_FILE_NOT_FOUND_SPEC,
    HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_EXCEPTION,
    HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_SPEC,
    HTTP_422_METADATA_SCHEMA_EXCEPTION,
    HTTP_422_METADATA_SCHEMA_SPEC,
    HTTP_422_SENSORS_SCHEMA_EXCEPTION,
    HTTP_422_SENSORS_SCHEMA_SPEC,
    HTTP_500_CONFIG_LIST_EXCEPTION,
    HTTP_500_CONFIG_LIST_SPEC,
    HTTP_500_CONFIG_WRITE_EXCEPTION,
    HTTP_500_CONFIG_WRITE_SPEC,
)
from icoapi.scripts.file_handling import get_config_dir

router = APIRouter(
    prefix="/config",
    tags=["Configuration"]
)

logger = logging.getLogger(__name__)

CONFIG_FILE_DEFINITIONS = [
    ("Metadata configuration", METADATA_FILENAME),
    ("Sensors configuration", SENSORS_FILENAME),
    ("Environment variables", ENV_FILENAME),
]


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
    return file_response(config_dir, METADATA_FILENAME, "application/x-yaml")


@router.post(
    "/meta",
    responses={
        200: {"description": "Metadata configuration uploaded successfully."},
        400: HTTP_400_INVALID_YAML_SPEC,
        415: HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_SPEC,
        422: HTTP_422_METADATA_SCHEMA_SPEC,
        500: HTTP_500_CONFIG_WRITE_SPEC,
    },
)
async def upload_metadata_file(
    metadata_file: UploadFile = File(..., description="YAML metadata configuration file"),
    config_dir: str = Depends(get_config_dir),
):
    if metadata_file.content_type and metadata_file.content_type.lower() not in ALLOWED_YAML_CONTENT_TYPES:
        raise HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_EXCEPTION

    raw_content = await metadata_file.read()
    if not raw_content:
        logger.error("Received empty YAML payload for metadata upload")
        raise HTTP_400_INVALID_YAML_EXCEPTION

    try:
        parsed_yaml = yaml.safe_load(raw_content)
    except yaml.YAMLError as exc:
        logger.error(f"Failed to parse uploaded metadata YAML: {exc}")
        raise HTTP_400_INVALID_YAML_EXCEPTION

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

    store_config(raw_content, config_dir, METADATA_FILENAME)
    return {"detail": "Metadata configuration uploaded successfully."}


@router.get("/sensors", responses={
    200: {"description": "File was found and returned."},
    404: HTTP_404_FILE_NOT_FOUND_SPEC,
})
async def get_sensors_file(config_dir: str = Depends(get_config_dir)) -> FileResponse:
    return file_response(config_dir, SENSORS_FILENAME, "application/x-yaml")


@router.post(
    "/sensors",
    responses={
        200: {"description": "Sensor configuration uploaded successfully."},
        400: HTTP_400_INVALID_YAML_SPEC,
        415: HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_SPEC,
        422: HTTP_422_SENSORS_SCHEMA_SPEC,
        500: HTTP_500_CONFIG_WRITE_SPEC,
    },
)
async def upload_sensors_file(
    sensors_file: UploadFile = File(..., description="YAML sensors configuration file"),
    config_dir: str = Depends(get_config_dir),
):
    if sensors_file.content_type and sensors_file.content_type.lower() not in ALLOWED_YAML_CONTENT_TYPES:
        raise HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_EXCEPTION

    raw_content = await sensors_file.read()
    if not raw_content:
        logger.error("Received empty YAML payload for sensors upload")
        raise HTTP_400_INVALID_YAML_EXCEPTION

    try:
        parsed_yaml = yaml.safe_load(raw_content)
    except yaml.YAMLError as exc:
        logger.error(f"Failed to parse uploaded sensors YAML: {exc}")
        raise HTTP_400_INVALID_YAML_EXCEPTION

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

    store_config(raw_content, config_dir, SENSORS_FILENAME)
    return {"detail": "Sensor configuration uploaded successfully."}


@router.get("/env", responses={
    200: {"description": "File was found and returned."},
    404: HTTP_404_FILE_NOT_FOUND_SPEC,
})
async def get_env_file(config_dir: str = Depends(get_config_dir)) -> FileResponse:
    return file_response(config_dir, ENV_FILENAME, "text/plain")


@router.post(
    "/env",
    responses={
        200: {"description": "Environment file uploaded successfully."},
        415: HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_SPEC,
        500: HTTP_500_CONFIG_WRITE_SPEC,
    },
)
async def upload_env_file(
    env_file: UploadFile = File(..., description="Environment variables file"),
    config_dir: str = Depends(get_config_dir),
):
    if env_file.content_type and env_file.content_type.lower() not in ALLOWED_ENV_CONTENT_TYPES:
        raise HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_EXCEPTION

    raw_content = await env_file.read()
    if raw_content is None:
        raw_content = b""

    store_config(raw_content, config_dir, ENV_FILENAME)
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
        for display_name, filename in CONFIG_FILE_DEFINITIONS:
            backup_entries = [
                ConfigFileBackup(filename=backup_name, timestamp=timestamp)
                for backup_name, timestamp in list_config_backups(config_dir, filename)
            ]
            files.append(
                ConfigFile(
                    name=display_name,
                    filename=filename,
                    backup=backup_entries,
                )
            )
    except OSError as exc:
        logger.exception(f"Failed to list configuration backups in {config_dir}")
        raise HTTP_500_CONFIG_LIST_EXCEPTION from exc

    return ConfigResponse(files=files)
