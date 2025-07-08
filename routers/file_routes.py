import logging

import tables
from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.params import Body, Depends
from fastapi.responses import FileResponse, StreamingResponse
import os
from datetime import datetime
import json
import asyncio
from typing import Annotated, AsyncGenerator

from starlette.responses import PlainTextResponse
from tables import NoSuchNodeError

from models.globals import get_trident_client
from models.models import Dataset, DiskCapacity, FileCloudDetails, FileListResponseModel, HDF5NodeInfo, \
    MeasurementFileDetails, \
    ParsedHDF5FileContent, ParsedMeasurement, \
    ParsedMetadata, Sensor, TridentBucketObject
from models.trident import StorageClient
from scripts.file_handling import get_disk_space_in_gb, get_drive_or_root_path, get_measurement_dir, \
    get_suffixed_filename, is_dangerous_filename
import pandas as pd
router = APIRouter(
    prefix="/files",
    tags=["File Handling"]
)

logger = logging.getLogger(__name__)

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
        except HTTPException as e:
            logger.error(f"E    rror listing cloud files")
        except Exception as e:
            logger.error(f"General exception when comparing files to cloud: {e}")
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
                    matches = [file for file in cloud_files if filename in file.Key]
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


@router.get("/analyze/{name}", response_model=ParsedMeasurement)
async def get_analyzed_file(name: str, measurement_dir: str = Depends(get_measurement_dir)) -> StreamingResponse:

    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(status_code=405, detail=f"Method not allowed: {cause}")

    file_path = os.path.join(measurement_dir, name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    parsed_file_content = get_file_data(file_path)

    # Total number of rows for progress tracking
    total_rows = len(parsed_file_content.acceleration_df)

    # Streaming generator function
    # We approach this as a StreamingResponse because reading, parsing and sending the complete dataset
    # takes forever
    async def data_generator() -> AsyncGenerator[str, None]:
        # First: yield metadata
        sensors: list[Sensor] = [Sensor(**sensor) for sensor in parsed_file_content.sensor_df.to_dict(orient="records")]
        yield ParsedMetadata(
            acceleration=parsed_file_content.acceleration_meta,
            pictures=parsed_file_content.pictures,
            sensors=sensors
        ).model_dump_json() + "\n"

        # Then: yield measurement data
        batch_size = 1000
        parsed_rows = 0

        for start in range(0, total_rows, batch_size):
            end = min(start + batch_size, total_rows)
            batch = parsed_file_content.acceleration_df.iloc[start:end:10]
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


@router.post("/analyze")
async def post_analyzed_file(file: UploadFile, measurement_dir: str = Depends(get_measurement_dir)) -> PlainTextResponse:

    filename = get_suffixed_filename(file.filename, measurement_dir)

    file_path = os.path.join(measurement_dir, filename)

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    return PlainTextResponse(filename)


@router.get("/analyze/meta/{name}")
async def get_file_meta(name: str, measurement_dir: str = Depends(get_measurement_dir)) -> ParsedMetadata:
    data = get_file_data(os.path.join(measurement_dir, name))
    return ParsedMetadata(
        acceleration=data.acceleration_meta,
        pictures=data.pictures,
        sensors=[Sensor(**sensor) for sensor in data.sensor_df.to_dict(orient="records")]
    )


def get_node_names(hdf5_file_handle: tables.File) -> list[str]:
    nodes = hdf5_file_handle.list_nodes('/')
    return [node._v_pathname for node in nodes]


def get_picture_node_names(hdf5_file_handle: tables.File) -> list[str]:
    names = get_node_names(hdf5_file_handle)
    return [name for name in names if name.startswith("/pic_")]

def parse_json_if_possible(val):
    """
    If val is a str or bytes containing JSON, return the deserialized object.
    Otherwise, return val unchanged.
    """
    # Only attempt on str/bytes
    if isinstance(val, (bytes, bytearray)):
        try:
            text = val.decode('utf-8')
        except UnicodeDecodeError:
            return val
    elif isinstance(val, str):
        text = val
    else:
        return val

    # Try parsing
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return val


def node_to_dict(node):
    info = HDF5NodeInfo(
        name=node._v_name,
        path=node._v_pathname,
        type=node.__class__.__name__,
        attributes={}
    )

    for key in node._v_attrs._f_list():
        raw = node._v_attrs[key]
        # first coerce numpy‐types to Python
        if hasattr(raw, "tolist"):
            pyval = raw.tolist()
        elif hasattr(raw, "item"):
            pyval = raw.item()
        else:
            pyval = raw
        # then parse JSON if it is a JSON string
        info.attributes[key] = parse_json_if_possible(pyval)

    return info

def get_file_data(file_path: str,) -> ParsedHDF5FileContent:
    with tables.open_file(file_path, mode="r") as file_handle:
        try:
            acceleration_data = file_handle.get_node("/acceleration")
            assert isinstance(acceleration_data, tables.Table)
            acceleration_df = pd.DataFrame.from_records(acceleration_data.read(), columns=acceleration_data.colnames)
            acceleration_meta = node_to_dict(acceleration_data)
        except NoSuchNodeError:
            raise HTTPException(status_code=500, detail="Acceleration data not found in the file")
        except AssertionError:
            raise HTTPException(status_code=500, detail="Acceleration data is not a table")

        try:
            sensor_data = file_handle.get_node("/sensors")
            assert isinstance(sensor_data, tables.Table)
            sensor_df = pd.DataFrame.from_records(sensor_data.read(), columns=sensor_data.colnames)
        except NoSuchNodeError:
            # No sensor data available; pass
            pass
        except AssertionError:
            # sensor data available, but not in the right shape
            pass

        picture_node_names = get_picture_node_names(file_handle)
        pictures: dict[str, str] = {}
        for node_name in picture_node_names:
            node = file_handle.get_node(node_name)
            assert isinstance(node, tables.Array)
            pictures[node_name.removeprefix('/pic_')] = str(node.read())

    return ParsedHDF5FileContent(
        acceleration_df=acceleration_df,
        sensor_df=sensor_df,
        acceleration_meta=acceleration_meta,
        pictures=pictures
    )

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
