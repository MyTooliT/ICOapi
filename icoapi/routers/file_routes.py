"""Routes for measurement data"""

import json
import logging
import os
from datetime import datetime
from typing import Annotated, AsyncGenerator
from urllib.parse import quote
from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.params import Depends
from fastapi.responses import FileResponse, StreamingResponse
from icotronic.measurement import Storage
from starlette.responses import PlainTextResponse
from tables import HDF5ExtError, NoSuchNodeError, Node


from icoapi.models.globals import get_trident_client
from icoapi.models.models import (
    Dataset,
    EmbeddedFileDeleteResponse,
    EmbeddedFileUploadResponse,
    FileCloudStatus,
    FileCloudDetails,
    FileListResponseModel,
    MeasurementFileDetails,
    Metadata,
    MetadataPrefix,
    ParsedMeasurement,
    ParsedMetadata,
    Sensor,
)
from icoapi.models.trident import RemoteObjectDetails, StorageClient
from icoapi.scripts.cloud_scripts import get_cloud_details
from icoapi.scripts.data_handling import AccelerationDataNotFoundError, get_file_data
from icoapi.scripts.errors import (
    HTTP_404_FILE_NOT_FOUND_EXCEPTION,
    HTTP_404_FILE_NOT_FOUND_SPEC,
    HTTP_422_INVALID_HDF5_FILE_EXCEPTION,
    HTTP_422_INVALID_HDF5_FILE_SPEC,
)
from icoapi.scripts.file_handling import (
    append_embedded_file_to_hdf5,
    delete_embedded_file_from_hdf5,
    get_embedded_file_from_hdf5,
    get_disk_space_in_gib,
    get_drive_or_root_path,
    get_measurement_dir,
    get_suffixed_filename,
    is_dangerous_filename,
)

from icoapi.scripts.measurement import write_metadata

router = APIRouter(prefix="/files", tags=["File Handling"])

logger = logging.getLogger(__name__)


@router.get("")
async def list_files_and_capacity(
    measurement_dir: Annotated[str, Depends(get_measurement_dir)],
    storage: Annotated[StorageClient, Depends(get_trident_client)],
) -> FileListResponseModel:
    """Get file list and storage capacity information"""

    try:
        capacity = get_disk_space_in_gib(get_drive_or_root_path())
        files_info: list[MeasurementFileDetails] = []
        cloud_files: list[RemoteObjectDetails] = []
        if storage is not None:
            try:
                cloud_files = storage.get_remote_objects().files
            except HTTPException:
                logger.error("Error listing cloud files")
            except Exception as e:  # pylint: disable=broad-exception-caught
                logger.error(
                    "General exception when comparing files to cloud: %s", e
                )
        # Iterate over files in the directory
        for filename in os.listdir(measurement_dir):
            file_path = os.path.join(measurement_dir, filename)
            if os.path.isfile(file_path):
                # Get file creation time and size
                creation_time = datetime.fromtimestamp(
                    os.path.getctime(file_path)
                ).isoformat()
                file_size = os.path.getsize(file_path)
                try:
                    cloud_details = get_cloud_details(file_path, filename, cloud_files)
                except ValueError:
                    cloud_details = FileCloudDetails(
                        status=FileCloudStatus.ERROR,
                        upload_timestamp=None,
                        id=None
                    )
                cloud_details = (
                    cloud_details
                    if storage is not None
                    else FileCloudDetails(
                        status=FileCloudStatus.NOT_UPLOADED,
                        upload_timestamp=None,
                        id=None
                    )
                )

                details = MeasurementFileDetails(
                    name=filename,
                    size=file_size,
                    created=creation_time,
                    cloud=cloud_details,
                )
                files_info.append(details)
        return FileListResponseModel(capacity, files_info, measurement_dir)
    except FileNotFoundError as error:
        raise HTTPException(
            status_code=404, detail="Directory not found"
        ) from error
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/{name}")
async def download_file(
    name: str, measurement_dir: Annotated[str, Depends(get_measurement_dir)]
):
    """Download measurement files"""

    # Sanitization
    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(
            status_code=405, detail=f"Method not allowed: {cause}"
        )

    full_path = os.path.join(measurement_dir, name)
    if not os.path.isfile(full_path):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path=full_path, filename=name)


@router.delete("/{name}")
async def delete_file(
    name: str, measurement_dir: Annotated[str, Depends(get_measurement_dir)]
):
    """Delete measurement file"""

    # Sanitization
    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(
            status_code=405, detail=f"Method not allowed: {cause}"
        )

    full_path = os.path.join(measurement_dir, name)
    if os.path.isfile(full_path):
        try:
            os.remove(full_path)
            return {"detail": f"File '{name}' deleted successfully"}
        except Exception as e:
            raise HTTPException(
                status_code=500, detail=f"Failed to delete file: {str(e)}"
            ) from e
    else:
        raise HTTPException(status_code=404, detail="File not found")


@router.get("/analyze/{name}", response_model=ParsedMeasurement)
async def get_analyzed_file(
    name: str, measurement_dir: Annotated[str, Depends(get_measurement_dir)]
) -> StreamingResponse:
    """Analyze measurement file"""

    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(
            status_code=405, detail=f"Method not allowed: {cause}"
        )

    file_path = os.path.join(measurement_dir, name)
    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="File not found")

    parsed_file_content = get_file_data(file_path)

    # Total number of rows for progress tracking
    total_rows = len(parsed_file_content.acceleration_df)

    # Streaming generator function
    # We approach this as a StreamingResponse because reading, parsing and
    # sending the complete dataset takes forever
    async def data_generator() -> AsyncGenerator[str, None]:
        # First: yield metadata
        sensors_raw = parsed_file_content.sensor_df.to_dict(orient="records")
        for sensor_raw in sensors_raw:
            if "dimension" not in sensor_raw:
                sensor_raw["dimension"] = ""
        sensors: list[Sensor] = [Sensor(**sensor) for sensor in sensors_raw]
        embedded_files = [
            embedded_file.model_copy(
                update={
                    "download_path": (
                        f"files/{name}/embedded/"
                        f"{embedded_file.dataset_name}"
                    )
                }
            )
            for embedded_file in parsed_file_content.embedded_files
        ]
        yield ParsedMetadata(
            acceleration=parsed_file_content.acceleration_meta,
            pictures=parsed_file_content.pictures,
            sensors=sensors,
            embedded_files=embedded_files,
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
                datasets=[
                    Dataset(name=column, data=batch[column].tolist())
                    for column in datasets.columns
                ],
            )

            # Serialize the batch as JSON and yield it
            yield batch_dict.model_dump_json() + "\n"

            # Update progress
            parsed_rows += len(batch) * 10
            progress = parsed_rows / total_rows
            yield json.dumps({"progress": progress}) + "\n"

        # Final completion progress
        yield json.dumps({"progress": 1.0}) + "\n"

    return StreamingResponse(data_generator(), media_type="application/json")


@router.post("/analyze")
async def post_analyzed_file(
    file: UploadFile,
    measurement_dir: Annotated[str, Depends(get_measurement_dir)],
) -> PlainTextResponse:
    """Upload file for analysis"""

    assert file.filename is not None
    filename = get_suffixed_filename(file.filename, measurement_dir)

    file_path = os.path.join(measurement_dir, filename)

    with open(file_path, "wb") as f:
        f.write(file.file.read())

    return PlainTextResponse(filename)


@router.post(
    "/{name}/embedded",
    response_model=list[EmbeddedFileUploadResponse],
    responses={
        404: HTTP_404_FILE_NOT_FOUND_SPEC,
        422: HTTP_422_INVALID_HDF5_FILE_SPEC,
    },
)
async def upload_embedded_file(
    name: str,
    measurement_dir: Annotated[str, Depends(get_measurement_dir)],
    files: list[UploadFile] = File(
        ..., description="Files to store in HDF5"
    ),
) -> list[EmbeddedFileUploadResponse]:
    """Append uploaded files below the embedded_files group"""

    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(
            status_code=405, detail=f"Method not allowed: {cause}"
        )

    file_path = os.path.join(measurement_dir, name)
    if not os.path.isfile(file_path):
        raise HTTP_404_FILE_NOT_FOUND_EXCEPTION

    try:
        responses: list[EmbeddedFileUploadResponse] = []
        for file in files:
            payload = await file.read()
            responses.append(
                append_embedded_file_to_hdf5(
                    file_path,
                    file.filename,
                    payload,
                    file.content_type,
                )
            )
        return responses
    except HDF5ExtError as exc:
        raise HTTP_422_INVALID_HDF5_FILE_EXCEPTION from exc


@router.get(
    "/{name}/embedded/{dataset_name}",
    responses={
        404: HTTP_404_FILE_NOT_FOUND_SPEC,
        422: HTTP_422_INVALID_HDF5_FILE_SPEC,
    },
)
async def download_embedded_file(
    name: str,
    dataset_name: str,
    measurement_dir: Annotated[str, Depends(get_measurement_dir)],
) -> StreamingResponse:
    """Download an embedded file from an HDF5 file"""

    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(
            status_code=405, detail=f"Method not allowed: {cause}"
        )

    file_path = os.path.join(measurement_dir, name)
    if not os.path.isfile(file_path):
        raise HTTP_404_FILE_NOT_FOUND_EXCEPTION

    try:
        embedded_file = get_embedded_file_from_hdf5(file_path, dataset_name)
    except NoSuchNodeError as exc:
        raise HTTP_404_FILE_NOT_FOUND_EXCEPTION from exc
    except HDF5ExtError as exc:
        raise HTTP_422_INVALID_HDF5_FILE_EXCEPTION from exc

    quoted_name = quote(embedded_file.original_name)
    return StreamingResponse(
        iter([embedded_file.content]),
        media_type=embedded_file.mime,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{embedded_file.original_name}"; '
                f"filename*=UTF-8''{quoted_name}"
            )
        },
    )


@router.delete(
    "/{name}/embedded/{dataset_name}",
    responses={
        200: {"description": "Embedded file deleted successfully."},
        404: HTTP_404_FILE_NOT_FOUND_SPEC,
        422: HTTP_422_INVALID_HDF5_FILE_SPEC,
    },
)
async def delete_embedded_file(
    name: str,
    dataset_name: str,
    measurement_dir: Annotated[str, Depends(get_measurement_dir)],
) -> EmbeddedFileDeleteResponse:
    """Delete an embedded file from an HDF5 file"""

    danger, cause = is_dangerous_filename(name)
    if danger:
        raise HTTPException(
            status_code=405, detail=f"Method not allowed: {cause}"
        )

    file_path = os.path.join(measurement_dir, name)
    if not os.path.isfile(file_path):
        raise HTTP_404_FILE_NOT_FOUND_EXCEPTION

    try:
        delete_embedded_file_from_hdf5(file_path, dataset_name)
    except NoSuchNodeError as exc:
        raise HTTP_404_FILE_NOT_FOUND_EXCEPTION from exc
    except HDF5ExtError as exc:
        raise HTTP_422_INVALID_HDF5_FILE_EXCEPTION from exc

    return EmbeddedFileDeleteResponse(
        dataset_name=dataset_name,
        file_name=name
    )


@router.get("/analyze/meta/{name}")
async def get_file_meta(
    name: str, measurement_dir: Annotated[str, Depends(get_measurement_dir)]
) -> ParsedMetadata:

    """Get measurement file metadata"""

    data = get_file_data(os.path.join(measurement_dir, name))
    embedded_files = [
        embedded_file.model_copy(
            update={
                "download_path": (
                    f"/api/v1/files/{name}/embedded/"
                    f"{embedded_file.dataset_name}"
                )
            }
        )
        for embedded_file in data.embedded_files
    ]
    return ParsedMetadata(
        acceleration=data.acceleration_meta,
        pictures=data.pictures,
        sensors=[
            Sensor(**sensor)
            for sensor in data.sensor_df.to_dict(orient="records")
        ],
        embedded_files=embedded_files,
    )


@router.post(
    "/post_meta/{name}",
    responses={
        200: {"description": "Metadata successfully overwritten"},
        404: HTTP_404_FILE_NOT_FOUND_SPEC,
    },
)
async def overwrite_post_meta(
    name: str,
    metadata: Metadata,
    measurement_dir: Annotated[str, Depends(get_measurement_dir)],
):
    """Update post metadata in measurement file"""

    file_path = os.path.join(measurement_dir, name)
    if not os.path.isfile(file_path):
        raise HTTP_404_FILE_NOT_FOUND_EXCEPTION

    # we have the file and the metadata object
    with Storage(file_path) as storage:
        try:
            node: Node = storage.hdf.get_node("/acceleration")
            del node.attrs["post_metadata"]
        except NoSuchNodeError as error:
            raise AccelerationDataNotFoundError from error
        write_metadata(MetadataPrefix.POST, metadata, storage)


@router.post(
    "/pre_meta/{name}",
    responses={
        200: {"description": "Metadata successfully overwritten"},
        404: HTTP_404_FILE_NOT_FOUND_SPEC,
    },
)
async def overwrite_pre_meta(
    name: str,
    metadata: Metadata,
    measurement_dir: Annotated[str, Depends(get_measurement_dir)],
):
    """Update pre metadata in measurement file"""

    file_path = os.path.join(measurement_dir, name)
    if not os.path.isfile(file_path):
        raise HTTP_404_FILE_NOT_FOUND_EXCEPTION

    # we have the file and the metadata object
    with Storage(file_path) as storage:
        try:
            node: Node = storage.hdf.get_node("/acceleration")
            del node.attrs["pre_metadata"]
        except NoSuchNodeError as error:
            raise AccelerationDataNotFoundError from error
        write_metadata(MetadataPrefix.PRE, metadata, storage)
