from os import getenv

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from httpx import HTTPStatusError
from mytoolit.can.network import CANInitError
from contextlib import asynccontextmanager

from routers import stu_routes, sth_routes, common, file_routes, measurement_routes, cloud_routes
from scripts.file_handling import ensure_folder_exists, get_measurement_dir
from models.globals import MeasurementSingleton, NetworkSingleton, TridentHandler, get_trident_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    This function handles startup and shutdown of the API.
    Anything before <yield> will be run on startup; everything after on shutdown.
    See https://fastapi.tiangolo.com/advanced/events/#lifespan
    """
    MeasurementSingleton.create_instance_if_none()
    try:
        handler = await get_trident_client()
        handler.authenticate()

    except HTTPStatusError:
        print("Cannot establish Trident connection")

    try:
        await NetworkSingleton.create_instance_if_none()
    except CANInitError:
        print("Error initializing CAN network. CAN adapter may not be connected.")
    yield
    MeasurementSingleton.clear_clients()
    await NetworkSingleton.close_instance()

app = FastAPI(lifespan=lifespan)
app.include_router(prefix='/api/v1', router=stu_routes.router)
app.include_router(prefix='/api/v1', router=sth_routes.router)
app.include_router(prefix='/api/v1', router=common.router)
app.include_router(prefix='/api/v1', router=file_routes.router)
app.include_router(prefix='/api/v1', router=cloud_routes.router)
app.include_router(prefix='/api/v1/measurement', router=measurement_routes.router)

origins = getenv("VITE_API_ORIGINS", "")
origins = origins.split(",")
print(f"origins: {origins}")
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
    from dotenv import load_dotenv

    PORT: int = 33215
    HOST: str = "0.0.0.0"

    env_found = load_dotenv(".env")
    if env_found:
        PORT = int(getenv("VITE_API_PORT", PORT))
        HOST = getenv("VITE_API_HOSTNAME")

    ensure_folder_exists(get_measurement_dir())

    uvicorn.run(
        "api:app",
        host=HOST,
        port=PORT,
    )
