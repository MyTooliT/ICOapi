from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
import os
from dotenv import load_dotenv
from typing import List

router = APIRouter(prefix="/files")


@router.get("")
async def list_files():
    load_dotenv("../../ico-front/.env")
    local_appdata = os.getenv("LOCALAPPDATA")
    measurement_dir = os.getenv("VITE_BACKEND_MEASUREMENT_DIR")
    full_path = os.path.join(local_appdata, measurement_dir)
    print(full_path)
    try:
        files = [f for f in os.listdir(full_path) if os.path.isfile(os.path.join(full_path, f))]
        return files
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Directory not found")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{name}")
async def download_file(name: str):
    load_dotenv("../../ico-front/.env")
    local_appdata = os.getenv("LOCALAPPDATA")
    measurement_dir = os.getenv("VITE_BACKEND_MEASUREMENT_DIR")
    file_path = os.path.join(local_appdata, measurement_dir, name)
    if os.path.isfile(file_path):
        return FileResponse(path=file_path, filename=name)
    else:
        raise HTTPException(status_code=404, detail="File not found")
