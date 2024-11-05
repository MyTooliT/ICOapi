from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.websockets import WebSocket
from contextlib import asynccontextmanager

from routers import stu_routes, sth_routes, common, websockets, file_routes
from models.GlobalNetwork import NetworkSingleton
from scripts.setup import ensure_folder_exists


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    This function handles startup and shutdown of the API.
    Anything before <yield> will be run on startup; everything after on shutdown.
    See https://fastapi.tiangolo.com/advanced/events/#lifespan
    """
    await NetworkSingleton.create_instance_if_none()
    yield
    await NetworkSingleton.close_instance()

app = FastAPI(lifespan=lifespan)
app.include_router(prefix='/api/v1', router=stu_routes.router)
app.include_router(prefix='/api/v1', router=sth_routes.router)
app.include_router(prefix='/api/v1', router=common.router)
app.include_router(prefix='/api/v1', router=file_routes.router)
app.include_router(prefix='', router=websockets.router)

origins = [
    "http://localhost",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.websocket("/live")
async def live_websocket(websocket: WebSocket):
    await websocket.accept()


if __name__ == "__main__":
    import uvicorn
    from os import getenv
    from dotenv import load_dotenv

    load_dotenv(dotenv_path='../ico-front/.env')
    PORT = int(getenv("VITE_API_PORT"))
    HOST = getenv("VITE_API_HOSTNAME")

    PATH = getenv("VITE_BACKEND_MEASUREMENT_DIR")
    ensure_folder_exists(PATH)

    uvicorn.run(
        "api:app",
        host=HOST,
        port=PORT,
    )
