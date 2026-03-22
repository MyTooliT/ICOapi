"""Support for uploading data to cloud storage"""
import logging
import os
from typing import Optional

from fastapi import HTTPException, APIRouter
from fastapi.params import Depends, Annotated, Body
from starlette.status import HTTP_502_BAD_GATEWAY

from icoapi.models.globals import get_trident_client, setup_trident, get_dataspace_config
from icoapi.models.models import CloudConfig, FileCloudDetails, FileCloudStatus
from icoapi.models.trident import (
    AuthorizationError,
    FileUploadDetails, HostNotFoundError,
    PresignError, RemoteObjectDetails, StorageClient,
)
from icoapi.scripts.data_handling import get_file_data
from icoapi.scripts.errors import (
    HTTP_500_CLOUD_UPLOAD_PRESIGN_EXCEPTION,
    HTTP_500_CLOUD_UPLOAD_PRESIGN_SPEC,
)
from icoapi.scripts.file_handling import get_measurement_dir

router = APIRouter(prefix="/cloud", tags=["Cloud Connection"])

logger = logging.getLogger(__name__)


@router.post(
    "/upload",
    responses={
        500: HTTP_500_CLOUD_UPLOAD_PRESIGN_SPEC,
    },
)
async def upload_file(
    filename: Annotated[str, Body(embed=True)],
    client: Annotated[StorageClient, Depends(get_trident_client)],
    measurement_dir: Annotated[str, Depends(get_measurement_dir)],
    config: Annotated[CloudConfig, Depends(get_dataspace_config)]
):
    """Upload file to cloud storage"""

    if client is None:
        logger.warning(
            "Tried to upload file to cloud, but no cloud connection is"
            " available."
        )
    else:
        full_path = os.path.join(measurement_dir, filename)
        file_data = get_file_data(full_path)
        metadata = file_data.acceleration_meta

        for (key, item) in metadata.attributes["pre_metadata"]["parameters"].items():
            if key.endswith("_pictures"):
                metadata.attributes["pre_metadata"]["parameters"][key] = len(item)

        for (key, item) in metadata.attributes["post_metadata"]["parameters"].items():
            if key.endswith("_pictures"):
                metadata.attributes["post_metadata"]["parameters"][key] = len(item)

        upload_details = FileUploadDetails(
            key=filename,
            name=filename,
            metadata=metadata.__dict__,
        )

        root = config.virtual_group_root
        profile = metadata.attributes["pre_metadata"]["profile"]

        if config.virtual_group_root is not None:
            vg = root

            if profile is not None:
                vg = f"{root}/{profile}"

            upload_details.virtual_group = vg

        try:
            client.upload_file(
                os.path.join(measurement_dir, filename), upload_details
            )
            logger.info("Successfully uploaded file <%s>", filename)
        except PresignError as e:
            raise HTTP_500_CLOUD_UPLOAD_PRESIGN_EXCEPTION from e


@router.post("/update")
async def update_file(
    file_id: Annotated[Optional[int], Body(embed=True)],
    filename: Annotated[str, Body(embed=True)],
    client: Annotated[StorageClient, Depends(get_trident_client)],
    measurement_dir: Annotated[str, Depends(get_measurement_dir)],
) -> FileCloudDetails:
    """Update file in cloud storage"""
    if file_id is None:
        raise HTTPException(status_code=400, detail="File ID is required")

    try:
        client.update_file(file_id, os.path.join(measurement_dir, filename))
        logger.info("Successfully updated file <%s> with id <%i>", filename, file_id)
        return FileCloudDetails(
            id=file_id,
            status=FileCloudStatus.UP_TO_DATE,
            upload_timestamp=None
        )
    except PresignError as e:
        raise HTTPException(status_code=500, detail="Error getting presigned URL") from e
    except HTTPException as e:
        logger.error(e)
        raise HTTPException(status_code=500, detail="Error updating file") from e


@router.post("/authenticate")
async def authenticate(
    storage: Annotated[StorageClient, Depends(get_trident_client)],
):
    """Authenticate to cloud storage"""

    if storage is None:
        logger.warning(
            "Tried to authenticate to cloud, but no cloud connection is"
            " available."
        )
        await setup_trident()
    else:
        storage.revoke_auth()
        await setup_trident()
        try:
            storage.authenticate()
        except HTTPException as e:
            logger.error(e)
        except HostNotFoundError as e:
            raise HTTPException(  # pylint: disable=raise-missing-from
                status_code=HTTP_502_BAD_GATEWAY, detail=str(e)
            )
        except AuthorizationError as e:
            raise HTTPException(  # pylint: disable=raise-missing-from
                status_code=HTTP_502_BAD_GATEWAY, detail=str(e)
            )


@router.get("")
async def get_cloud_files(
    storage: Annotated[StorageClient, Depends(get_trident_client)],
) -> list[RemoteObjectDetails]:
    """Get files from cloud"""

    if storage is None:
        logger.warning(
            "Tried to authenticate to cloud, but no cloud connection is"
            " available."
        )
        await setup_trident()
        return []

    try:
        objects = storage.get_remote_objects()
        return objects.files
    except Exception as e:
        logger.error("Error getting cloud files.")
        logger.error(e)
        raise HTTPException(status_code=HTTP_502_BAD_GATEWAY) from e
