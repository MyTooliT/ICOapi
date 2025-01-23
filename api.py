from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mytoolit.can.network import CANInitError
from contextlib import asynccontextmanager
from routers import stu_routes, sth_routes, common, websockets, file_routes
from models.GlobalNetwork import NetworkSingleton
from scripts.file_handling import ensure_folder_exists


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    This function handles startup and shutdown of the API.
    Anything before <yield> will be run on startup; everything after on shutdown.
    See https://fastapi.tiangolo.com/advanced/events/#lifespan
    """
    try:
        await NetworkSingleton.create_instance_if_none()
    except CANInitError:
        print("Error initializing CAN network. CAN adapter may not be connected.")
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


if __name__ == "__main__":
    import uvicorn
    from os import getenv, path
    from dotenv import load_dotenv

    PORT: int = 33215
    HOST: str = "0.0.0.0"
    measurement_dir: str = "icogui"


    env_found = load_dotenv(dotenv_path='../.env')
    if env_found:
        PORT = int(getenv("VITE_API_PORT"))
        HOST = getenv("VITE_API_HOSTNAME")
        measurement_dir = getenv("VITE_BACKEND_MEASUREMENT_DIR")

    # This is system-wide on Windows and thus not dependent on .env
    local_appdata = getenv("LOCALAPPDATA")

    # Check / Create measurements path
    full_measurement_path = path.join(local_appdata, measurement_dir)
    ensure_folder_exists(full_measurement_path)

    uvicorn.run(
        "api:app",
        host=HOST,
        port=PORT,
    )
