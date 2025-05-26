import logging

from fastapi import HTTPException, APIRouter
from fastapi.params import Depends, Annotated, Body
import os

from starlette.status import HTTP_502_BAD_GATEWAY

from models.globals import get_trident_client
from models.models import TridentBucketObject
from models.trident import StorageClient
from scripts.file_handling import get_measurement_dir

router = APIRouter(
    prefix="/cloud",
    tags=["Cloud Connection"]
)

logger = logging.getLogger(__name__)

@router.post("/upload")
async def upload_file(filename: Annotated[str, Body(embed=True)], client: StorageClient = Depends(get_trident_client), measurement_dir: str = Depends(get_measurement_dir)):
    try:
        client.upload_file(os.path.join(measurement_dir, filename), filename)
        logger.info(f"Successfully uploaded file <{filename}>")
    except HTTPException as e:
        logger.error(e)


@router.post("/authenticate")
async def authenticate(storage: StorageClient = Depends(get_trident_client)):
    try:
        storage.authenticate()
    except HTTPException as e:
        logger.error(e)


@router.get("")
async def get_cloud_files(storage: StorageClient = Depends(get_trident_client)) -> list[TridentBucketObject]:
    try:
        objects = storage.get_bucket_objects()
        return [TridentBucketObject(**obj) for obj in objects]
    except Exception as e:
        logger.error(f"Error getting cloud files.")
        raise HTTPException(status_code=HTTP_502_BAD_GATEWAY) from e