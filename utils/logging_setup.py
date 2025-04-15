import logging
from fastapi import WebSocket
from typing import List
from dotenv import load_dotenv
import os
from pathlib import Path
import platform
import asyncio

log_watchers: List[WebSocket] = []

# Determine a sensible default log file path
def get_default_log_path() -> str:
    app_folder = "icogui"
    file_name = "icogui.log"
    if platform.system() == "Windows":
        base = os.getenv("LOCALAPPDATA", str(Path.home()))
    else:
        base = os.path.join(Path.home(), ".local", "share")
    full_path = os.path.join(base, app_folder, "logs")
    os.makedirs(full_path, exist_ok=True)
    return os.path.join(full_path, file_name)

# Load from .env or fallback to platform-based default
load_dotenv()
LOG_PATH = os.getenv("LOG_PATH", get_default_log_path())

class WebSocketLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord):
        try:
            message = self.format(record)
            asyncio.create_task(self.broadcast(message))
        except Exception:
            pass  # Don't break on logging errors

    async def broadcast(self, message: str):
        for ws in list(log_watchers):
            try:
                await ws.send_text(message)
            except Exception:
                log_watchers.remove(ws)

def setup_logging() -> None:
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter("%(asctime)s [PYTHON] [%(levelname)s] %(message)s")

    file_handler = logging.FileHandler(LOG_PATH)
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    ws_handler = WebSocketLogHandler()
    ws_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    logger.addHandler(ws_handler)