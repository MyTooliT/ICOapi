from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.params import Body, Depends
from fastapi.responses import FileResponse, StreamingResponse
import os
from datetime import datetime
import json
import asyncio
from typing import Annotated, AsyncGenerator

from starlette.responses import PlainTextResponse

from models.globals import get_trident_client
from models.models import Dataset, DiskCapacity, FileCloudDetails, FileListResponseModel, MeasurementFileDetails, \
    ParsedMeasurement, \
    TridentBucketObject
from models.trident import StorageClient
from scripts.file_handling import get_disk_space_in_gb, get_drive_or_root_path, get_measurement_dir, \
    get_suffixed_filename, is_dangerous_filename
import pandas as pd
router = APIRouter(
    prefix="/files",
    tags=["File Handling"]
)


@router.get("")
async def list_files_and_capacity(
        measurement_dir: str = Depends(get_measurement_dir),
        storage: StorageClient = Depends(get_trident_client)
) -> FileListResponseModel:
    try:
        capacity = get_disk_space_in_gb(get_drive_or_root_path())
        files_info: list[MeasurementFileDetails] = []
        cloud_files: list[TridentBucketObject] = []
        try:
            objects = storage.get_bucket_objects()
            cloud_files = [TridentBucketObject(**obj) for obj in objects]
        except Exception as e:
            print(e)
        # Iterate over files in the directory
        for filename in os.listdir(measurement_dir):
            file_path = os.path.join(measurement_dir, filename)
            if os.path.isfile(file_path):
                # Get file creation time and size
                creation_time = datetime.fromtimestamp(os.path.getctime(file_path)).isoformat()
                file_size = os.path.getsize(file_path)
                cloud_details = FileCloudDetails(
                    is_uploaded=False,
                    upload_timestamp=None
                )
                if os.getenv("TRIDENT_API_ENABLED") == "True":
                    matches = [file for file in cloud_files if file.Key == filename]
                    if matches:
                        cloud_details.is_uploaded = True
                        cloud_details.upload_timestamp = matches[0].LastModified

                details = MeasurementFileDetails(
                    name=filename,
                    size=file_size,
                    created=creation_time,
                    cloud=cloud_details
                )
                files_info.append(details)
        return FileListResponseModel(capacity, files_info, measurement_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{name}")
async def download_file(name: str, measurement_dir: str = Depends(get_measurement_dir)):

    # Sanitization
    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(status_code=405, detail=f"Method not allowed: {cause}")

    full_path = os.path.join(measurement_dir, name)
    print(full_path)
    if os.path.isfile(full_path):
        return FileResponse(path=full_path, filename=name)
    else:
        raise HTTPException(status_code=404, detail="File not found")

@router.delete("/{name}")
async def delete_file(name: str, measurement_dir: str = Depends(get_measurement_dir)):

    # Sanitization
    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(status_code=405, detail=f"Method not allowed: {cause}")

    full_path = os.path.join(measurement_dir, name)
    if os.path.isfile(full_path):
        try:
            os.remove(full_path)
            return {"detail": f"File '{name}' deleted successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")
    else:
        raise HTTPException(status_code=404, detail="File not found")


@router.get("/analyze/{name}")
async def get_analyzed_file(name: str, measurement_dir: str = Depends(get_measurement_dir)) -> StreamingResponse:

    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(status_code=405, detail=f"Method not allowed: {cause}")

    file_path = os.path.join(measurement_dir, name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    try:
        try:
            df = pd.read_hdf(file_path, key="acceleration")
        except KeyError:
            raise HTTPException(status_code=404, detail="Key 'acceleration' not found in the file")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to read the HDF5 file: {str(e)}")


        # Total number of rows for progress tracking
        total_rows = len(df)

        # Streaming generator function
        # We approach this as a StreamingResponse because reading, parsing and sending the complete dataset
        # takes forever
        async def data_generator() -> AsyncGenerator[str, None]:
            batch_size = 1000
            parsed_rows = 0

            for start in range(0, total_rows, batch_size):
                end = min(start + batch_size, total_rows)
                batch = df.iloc[start:end:10]
                batch_counter = batch["counter"].tolist()
                batch_timestamp = batch["timestamp"].tolist()
                datasets = batch.drop(columns=["counter", "timestamp"])

                batch_dict = ParsedMeasurement(
                    name=name,
                    counter=batch_counter,
                    timestamp=batch_timestamp,
                    datasets=[Dataset(name=column, data=batch[column].tolist()) for column in datasets.columns],
                )

                # Serialize the batch as JSON and yield it
                yield batch_dict.model_dump_json() + "\n"

                # Update progress
                parsed_rows += len(batch) * 10
                progress = parsed_rows / total_rows
                yield json.dumps({"progress": progress}) + "\n"

                # Simulate async behavior to avoid blocking
                await asyncio.sleep(0.01)

            # Final completion progress
            yield json.dumps({"progress": 1.0}) + "\n"

        return StreamingResponse(data_generator(), media_type="application/json")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/analyze")
async def post_analyzed_file(file: UploadFile, measurement_dir: str = Depends(get_measurement_dir)) -> PlainTextResponse:

    filename = get_suffixed_filename(file.filename, measurement_dir)

    file_path = os.path.join(measurement_dir, filename)

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    return PlainTextResponse(filename)

def ensure_dataframe_with_columns(df, required_columns) -> pd.DataFrame:
    """
    Ensures the object is a DataFrame and contains the required columns.

    Parameters:
        df: The object to check.
        required_columns: A list or set of column names that must be present.

    Returns:
        The DataFrame if it meets the requirements.

    Raises:
        TypeError: If the object is not a DataFrame.
        ValueError: If required columns are missing.
    """
    # Ensure the object is a DataFrame
    if not isinstance(df, pd.DataFrame):
        raise TypeError(f"Expected a pandas DataFrame, but got {type(df).__name__}")

    # Check for required columns
    missing_columns = set(required_columns) - set(df.columns)
    if missing_columns:
        raise ValueError(f"Missing required columns: {', '.join(missing_columns)}")

    return df
