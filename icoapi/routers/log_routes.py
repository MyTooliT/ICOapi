"""Routes for logging functionality"""

import io
import logging
import os
import re
import zipfile
from collections import deque

from fastapi import (
    APIRouter,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
)
from starlette.responses import Response, StreamingResponse

from icoapi.models.models import LogFileMeta, LogListResponse, LogResponse
from icoapi.utils.logging_setup import (
    log_watchers,
    LOG_PATH,
    parse_timestamps,
    LOG_NAME,
    LOG_BACKUP_COUNT,
    LOG_MAX_BYTES,
)

router = APIRouter(prefix="/logs", tags=["Logs"])

logger = logging.getLogger(__name__)


@router.get("", response_model=LogListResponse)
def list_logs():
    """List log files"""

    base_dir = os.path.dirname(LOG_PATH)
    log_files = [f for f in os.listdir(base_dir) if f.startswith(LOG_NAME)]

    files = []
    for name in sorted(log_files):
        path = os.path.join(base_dir, name)
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            first_ts, last_ts = parse_timestamps(lines)
        except Exception:  # pylint: disable=broad-exception-caught
            first_ts = last_ts = None

        try:
            size = os.path.getsize(path)

            files.append(
                LogFileMeta(
                    name=name,
                    size=size,
                    first_timestamp=first_ts,
                    last_timestamp=last_ts,
                )
            )
        except FileNotFoundError:
            # This only happens when you change the files manually; and as soon
            # as the logs fill back up it is gone
            pass

    return LogListResponse(
        files=files,
        directory=base_dir,
        max_bytes=LOG_MAX_BYTES,
        backup_count=LOG_BACKUP_COUNT,
    )


@router.get("/view", response_model=LogResponse)
def view_log_file(file: str = Query(...), limit: int = Query(0)):
    """View log file"""

    base_dir = os.path.dirname(LOG_PATH)
    safe_base = os.path.abspath(base_dir)
    requested_path = os.path.abspath(os.path.join(base_dir, file))

    if not requested_path.startswith(safe_base):
        raise HTTPException(status_code=403, detail="Invalid log file path.")

    if not os.path.isfile(requested_path):
        raise HTTPException(status_code=404, detail="Log file not found.")

    try:
        with open(requested_path, "r", encoding="utf-8", errors="ignore") as f:
            if limit > 0:
                # Efficient line-limiting (no storing the whole file)
                lines = deque(f, maxlen=limit)
                content = "".join(lines)
            else:
                content = f.read()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error reading log file: {e}"
        ) from e

    return LogResponse(filename=file, content=content)


@router.get("/download/{file}")
def download_log_file(file: str):
    """Download log file"""

    base_dir = os.path.dirname(LOG_PATH)
    safe_base = os.path.abspath(base_dir)

    logger.info("Downloading log file: %s", file)

    requested_path = os.path.abspath(os.path.join(base_dir, file))

    if not requested_path.startswith(safe_base):
        raise HTTPException(status_code=403, detail="Invalid log file path.")

    if not os.path.isfile(requested_path):
        raise HTTPException(status_code=404, detail="Log file not found.")

    try:
        with open(requested_path, "rb") as f:
            content = f.read()
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Error reading log file: {e}"
        ) from e

    return Response(
        content=content,
        media_type="text/plain",
        headers={"Content-Disposition": f"attachment; filename={file}"},
    )


@router.get("/all", response_class=StreamingResponse)
async def download_logs_zip():
    """Download log files as zipped file"""

    base_dir = os.path.dirname(LOG_PATH)
    log_file_pattern = re.compile(r".*\.log(\.\d+)?$")
    log_files = [
        f for f in os.listdir(base_dir) if log_file_pattern.fullmatch(f)
    ]
    if not log_files:
        raise HTTPException(status_code=404, detail="No log files found.")

    # In-memory ZIP creation
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_name in log_files:
            file_path = os.path.join(base_dir, file_name)
            zip_file.write(file_path, arcname=file_name)

    zip_buffer.seek(0)  # Reset pointer to start of the file

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=logs.zip"},
    )


@router.websocket("/stream")
async def websocket_logs(websocket: WebSocket):
    """WebSocket for logging data"""

    await websocket.accept()
    log_watchers.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        log_watchers.remove(websocket)
