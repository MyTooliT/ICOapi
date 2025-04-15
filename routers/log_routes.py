from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from utils.logging_setup import log_watchers, LOG_PATH

router = APIRouter(
    prefix="/logs",
    tags=["Logs"]
)

@router.get("")
def read_logs(limit: int = 500):
    with open(LOG_PATH, "r") as f:
        lines = f.readlines()
    return {"logs": "".join(lines[-limit:])}

@router.get("/download")
def download_logs():
    return FileResponse(LOG_PATH, media_type="text/plain", filename="icogui.log")

@router.websocket("/stream")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()
    log_watchers.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        log_watchers.remove(websocket)