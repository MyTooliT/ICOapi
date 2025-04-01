from fastapi import HTTPException, APIRouter
from fastapi.params import Depends, Annotated, Body
import os

from models.globals import get_trident_client
from models.models import TridentBucketObject
from models.trident import StorageClient
from scripts.file_handling import get_measurement_dir

router = APIRouter(
    prefix="/cloud",
    tags=["Cloud Connection"]
)

@router.post("/upload")
async def upload_file(filename: Annotated[str, Body(embed=True)], client: StorageClient = Depends(get_trident_client), measurement_dir: str = Depends(get_measurement_dir)):
    try:
        client.upload_file(os.path.join(measurement_dir, filename), filename)
        print(f"Successfully uploaded file <{filename}>")
    except HTTPException as e:
        print(e)


@router.post("/authenticate")
async def authenticate(storage: StorageClient = Depends(get_trident_client)):
    try:
        storage.authenticate()
    except HTTPException as e:
        print(e)


@router.get("")
async def get_cloud_files(storage: StorageClient = Depends(get_trident_client)) -> list[TridentBucketObject]:
    try:
        objects = storage.get_bucket_objects()
        return [TridentBucketObject(**obj) for obj in objects]
    except HTTPException as e:
        print(e)
        return []