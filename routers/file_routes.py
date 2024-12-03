from fastapi import APIRouter, HTTPException
from fastapi.params import Depends
from fastapi.responses import FileResponse
import os
from datetime import datetime
from models.models import MeasurementFileDetails
from scripts.file_handling import get_measurement_dir, tries_to_traverse_directory

router = APIRouter(prefix="/files")


@router.get("")
async def list_files(measurement_dir: str = Depends(get_measurement_dir)) -> list[MeasurementFileDetails]:
    try:
        files_info: list[MeasurementFileDetails] = []
        # Iterate over files in the directory
        for filename in os.listdir(measurement_dir):
            file_path = os.path.join(measurement_dir, filename)
            if os.path.isfile(file_path):
                # Get file creation time and size
                creation_time = datetime.fromtimestamp(os.path.getctime(file_path)).isoformat()
                file_size = os.path.getsize(file_path)

                details = MeasurementFileDetails(
                    name=filename,
                    size=file_size,
                    created=creation_time
                )
                files_info.append(details)
        return files_info
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{name}")
async def download_file(name: str, measurement_dir: str = Depends(get_measurement_dir)):

    # Prevent directory traversal
    if tries_to_traverse_directory(name):
        raise HTTPException(status_code=405, detail="Method not allowed")

    full_path = os.path.join(measurement_dir, name)
    print(full_path)
    if os.path.isfile(full_path):
        return FileResponse(path=full_path, filename=name)
    else:
        raise HTTPException(status_code=404, detail="File not found")

@router.delete("/{name}")
async def delete_file(name: str, measurement_dir: str = Depends(get_measurement_dir)):

    # Prevent directory traversal
    if tries_to_traverse_directory(name):
        raise HTTPException(status_code=405, detail="Method not allowed")

    full_path = os.path.join(measurement_dir, name)
    if os.path.isfile(full_path):
        try:
            os.remove(full_path)
            return {"detail": f"File '{name}' deleted successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")
    else:
        raise HTTPException(status_code=404, detail="File not found")