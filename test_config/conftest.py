from collections.abc import Generator
from pathlib import Path
from typing import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from icoapi.routers import config_routes
from icoapi.scripts.file_handling import get_config_dir


@pytest.fixture()
def temp_config_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture()
def config_test_app(temp_config_dir: Path) -> Generator[FastAPI, None, None]:
    app = FastAPI()
    app.include_router(config_routes.router)

    def override_get_config_dir() -> str:
        return str(temp_config_dir)

    app.dependency_overrides[get_config_dir] = override_get_config_dir
    try:
        yield app
    finally:
        app.dependency_overrides.clear()


@pytest.fixture()
def client(config_test_app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(config_test_app) as client:
        yield client


