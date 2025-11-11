"""Support for uploading data to cloud storage"""

import logging
import os

from fastapi import HTTPException, APIRouter
from fastapi.params import Depends, Annotated, Body
from starlette.status import HTTP_502_BAD_GATEWAY

from icoapi.models.globals import get_trident_client, setup_trident
from icoapi.models.models import TridentBucketObject
from icoapi.models.trident import AuthorizationError, HostNotFoundError, StorageClient
from icoapi.scripts.file_handling import get_measurement_dir

router = APIRouter(prefix="/cloud", tags=["Cloud Connection"])

logger = logging.getLogger(__name__)


@router.post("/upload")
async def upload_file(
    filename: Annotated[str, Body(embed=True)],
    client: Annotated[StorageClient, Depends(get_trident_client)],
    measurement_dir: Annotated[str, Depends(get_measurement_dir)],
):
    """Upload file to cloud storage"""

    if client is None:
        logger.warning("Tried to upload file to cloud, but no cloud connection is available.")
    else:
        try:
            client.upload_file(os.path.join(measurement_dir, filename), filename)
            logger.info("Successfully uploaded file <%s>", filename)
        except HTTPException as e:
            logger.error(e)


@router.post("/authenticate")
async def authenticate(storage: Annotated[StorageClient, Depends(get_trident_client)]):
    """Authenticate to cloud storage"""

    if storage is None:
        logger.warning("Tried to authenticate to cloud, but no cloud connection is available.")
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
) -> list[TridentBucketObject]:
    """Get files from cloud"""

    if storage is None:
        logger.warning("Tried to authenticate to cloud, but no cloud connection is available.")
        await setup_trident()
        return []

    try:
        objects = storage.get_bucket_objects()
        return [TridentBucketObject(**obj) for obj in objects]
    except Exception as e:
        logger.error("Error getting cloud files.")
        raise HTTPException(status_code=HTTP_502_BAD_GATEWAY) from e
