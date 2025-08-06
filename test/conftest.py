# -- Imports ------------------------------------------------------------------

from posixpath import join

from httpx import ASGITransport, AsyncClient
from pytest import fixture

from icoapi.api import app

# -- Fixtures -----------------------------------------------------------------


@fixture
def prefix():
    return "/api/v1"


@fixture
def stu_prefix(prefix):
    return join(prefix, "stu")


@fixture(scope="session")
def anyio_backend():
    return "asyncio"


@fixture(scope="session")
async def client():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        yield client
