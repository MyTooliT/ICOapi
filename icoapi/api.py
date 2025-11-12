import os
import sys
from os import getenv
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from icoapi.routers import config_routes, sensor_routes, stu_routes, sth_routes, common, file_routes, \
    measurement_routes, cloud_routes, log_routes
from icoapi.scripts.file_handling import copy_config_files_if_not_exists, ensure_folder_exists, get_application_dir, \
    get_config_dir, \
    get_measurement_dir, \
    is_bundled, load_env_file
from icoapi.models.globals import MeasurementSingleton, NetworkSingleton, setup_trident
from icoapi.utils.logging_setup import setup_logging
import logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    This function handles startup and shutdown of the API.
    Anything before <yield> will be run on startup; everything after on shutdown.
    See https://fastapi.tiangolo.com/advanced/events/#lifespan
    """
    MeasurementSingleton.create_instance_if_none()
    try:
        await setup_trident()
    except Exception as e:
        logger.error(f"Error when setting up Trident: {e}")
    try:
        await NetworkSingleton.create_instance_if_none()
    except Exception as e:
        logger.error(f"Error when initializing CAN network: {e}")
    yield
    MeasurementSingleton.clear_clients()
    await NetworkSingleton.close_instance()

app = FastAPI(lifespan=lifespan)
app.include_router(prefix='/api/v1', router=stu_routes.router)
app.include_router(prefix='/api/v1', router=sth_routes.router)
app.include_router(prefix='/api/v1', router=common.router)
app.include_router(prefix='/api/v1', router=file_routes.router)
app.include_router(prefix='/api/v1', router=cloud_routes.router)
app.include_router(prefix='/api/v1', router=measurement_routes.router)
app.include_router(prefix='/api/v1', router=log_routes.router)
app.include_router(prefix='/api/v1', router=sensor_routes.router)
app.include_router(prefix='/api/v1', router=config_routes.router)


logger = logging.getLogger(__name__)
origins = getenv("VITE_API_ORIGINS", "")
origins = origins.split(",")
logger.info(f"Accepted origins for CORS: {origins}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

def main():
    import uvicorn
    load_env_file()
    setup_logging()

    ensure_folder_exists(get_application_dir())
    ensure_folder_exists(get_measurement_dir())
    ensure_folder_exists(get_config_dir())

    if is_bundled():
        config_src = os.path.join(sys._MEIPASS, "config")
    else:
        config_src = Path(__file__).parent / "config"
    copy_config_files_if_not_exists(
        config_src,
        get_config_dir()
    )

    PORT = int(getenv("VITE_API_PORT", 33215))
    HOST = getenv("VITE_API_HOSTNAME", "0.0.0.0")

    uvicorn.run(
        "icoapi.api:app",
        host=HOST,
        port=PORT,
        log_config=None
    )

if __name__ == "__main__":
    main()
