import logging

from fastapi import HTTPException, APIRouter
from fastapi.params import Depends, Annotated, Body
import os

from starlette.status import HTTP_502_BAD_GATEWAY

from icoapi.models.globals import get_trident_client, setup_trident
from icoapi.models.models import TridentBucketObject
from icoapi.models.trident import AuthorizationError, HostNotFoundError, StorageClient
from icoapi.scripts.file_handling import get_measurement_dir

router = APIRouter(
    prefix="/cloud",
    tags=["Cloud Connection"]
)

logger = logging.getLogger(__name__)

@router.post("/upload")
async def upload_file(filename: Annotated[str, Body(embed=True)], client: StorageClient = Depends(get_trident_client), measurement_dir: str = Depends(get_measurement_dir)):
    if client is None:
        logger.warning("Tried to upload file to cloud, but no cloud connection is available.")
    else:
        try:
            client.upload_file(os.path.join(measurement_dir, filename), filename)
            logger.info(f"Successfully uploaded file <{filename}>")
        except HTTPException as e:
            logger.error(e)


@router.post("/authenticate")
async def authenticate(storage: StorageClient = Depends(get_trident_client)):
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
            raise HTTPException(status_code=HTTP_502_BAD_GATEWAY, detail=str(e))
        except AuthorizationError as e:
            raise HTTPException(status_code=HTTP_502_BAD_GATEWAY, detail=str(e))


@router.get("")
async def get_cloud_files(storage: StorageClient = Depends(get_trident_client)) -> list[TridentBucketObject]:
    if storage is None:
        logger.warning("Tried to authenticate to cloud, but no cloud connection is available.")
        await setup_trident()
        return []
    else:
        try:
            objects = storage.get_bucket_objects()
            return [TridentBucketObject(**obj) for obj in objects]
        except Exception as e:
            logger.error(f"Error getting cloud files.")
            raise HTTPException(status_code=HTTP_502_BAD_GATEWAY) from e