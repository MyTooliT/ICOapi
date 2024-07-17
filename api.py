from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import Settings
from .routers import devices, common

settings = Settings()

app = FastAPI()
app.include_router(prefix='/api/v1', router=devices.router)
app.include_router(prefix='/api/v1', router=common.router)

origins = [
    "http://localhost",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

if __name__ == "__main__":
    import asyncio
    import uvicorn

    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)

    event_loop.run_until_complete(uvicorn.run(app, host=settings.HOST, port=settings.PORT)) # type: ignore[func-returns-value]
