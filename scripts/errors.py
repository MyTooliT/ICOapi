from pydantic import BaseModel


class Error(BaseModel):
    name: str
    message: str


class CANResponseError(Error):
    def __init__(self):
        super().__init__(
            name="CANResponseError",
            message="CAN Network did not respond."
        )


class ConnectionTimeoutError(Error):
    def __init__(self):
        super().__init__(
            name="ConnectionTimeoutError",
            message="STH was not reachable."
        )