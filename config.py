import os
import sys
from enum import Enum

from pydantic_settings import BaseSettings, SettingsConfigDict


def getEnvPath() -> str:
    extDataDir = os.getcwd()
    if getattr(sys, 'frozen', False):
        extDataDir = sys._MEIPASS # type: ignore[attr-defined]
    return os.path.join(extDataDir, '.env')


class Mode(Enum):
    DEV = 'development'
    PROD = 'production'


class Settings(BaseSettings):
    HOST: str = '127.0.0.1'
    PORT: int = 1234
    MODE: Mode = Mode.DEV

    model_config = SettingsConfigDict(env_file=getEnvPath())
