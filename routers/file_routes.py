from fastapi import APIRouter, HTTPException
from fastapi.params import Depends
from fastapi.responses import FileResponse
import os
from dotenv import load_dotenv
from datetime import datetime
from models.models import MeasurementFileDetails

router = APIRouter(prefix="/files")

def get_measurement_dir() -> str:
    """To be used for dependency injection."""
    measurement_dir = "icogui"
    env_loaded = load_dotenv("../ico-front/.env")
    if env_loaded:
        measurement_dir = os.getenv("VITE_BACKEND_MEASUREMENT_DIR")
    data_dir = ""

    if os.name == "nt":
        print("Found WINDOWS system.")
        data_dir = os.getenv("LOCALAPPDATA")
    elif os.name == "posix":
        print("Found POSIX system.")
        data_dir = linux_get_preferred_data_dir(measurement_dir)

    return os.path.join(data_dir, measurement_dir)


def linux_get_xdg_data_dirs() -> list[str]:
    """Get data directories for LINUX systems"""
    # Get XDG_DATA_DIRS or use the default value
    xdg_data_dirs = os.getenv("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    # Split the colon-separated paths into a list
    return xdg_data_dirs.split(":")


def linux_get_preferred_data_dir(app_name: str) -> str:
    """Get usable data directory for LINUX systems"""
    # Iterate through XDG_DATA_DIRS and pick the first writable directory
    for data_dir in linux_get_xdg_data_dirs():
        app_data_dir = os.path.join(data_dir, app_name)
        if os.access(data_dir, os.W_OK):  # Check if the directory is writable
            os.makedirs(app_data_dir, exist_ok=True)
            return app_data_dir
    raise PermissionError("No writable XDG_DATA_DIRS found")


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
    full_path = os.path.join(measurement_dir, name)
    if os.path.isfile(full_path):
        return FileResponse(path=full_path, filename=name)
    else:
        raise HTTPException(status_code=404, detail="File not found")

@router.delete("/{name}")
async def delete_file(name: str, measurement_dir: str = Depends(get_measurement_dir)):
    full_path = os.path.join(measurement_dir, name)
    if os.path.isfile(full_path):
        try:
            os.remove(full_path)
            return {"detail": f"File '{name}' deleted successfully"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed to delete file: {str(e)}")
    else:
        raise HTTPException(status_code=404, detail="File not found")