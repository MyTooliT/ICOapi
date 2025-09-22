from fastapi import HTTPException
from starlette import status

HTTP_404_STH_UNREACHABLE_EXCEPTION = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="STH could not be connected and must be out of reach or discharged.")
HTTP_404_STH_UNREACHABLE_SPEC = {
    "description": "STH could not be connected and must be out of reach or discharged.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "status_code": {"type": "integer"},
                },
                "required": ["detail", "status_code"]
            },
            "example": {
                "detail": "STH could not be connected and must be out of reach or discharged.",
                "status_code": 404,
            },
        }
    }
}

HTTP_404_FILE_NOT_FOUND_EXCEPTION = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found. Check your measurement directory.")
HTTP_404_FILE_NOT_FOUND_SPEC = {
    "description": "File not found. Check your measurement directory.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "status_code": {"type": "integer"},
                },
                "required": ["detail", "status_code"]
            },
            "example": {
                "detail": "File not found. Check your measurement directory.",
                "status_code": 404,
            },
        }
    }
}

HTTP_502_CAN_NO_RESPONSE_EXCEPTION = HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="The CAN network did not respond to the request.")
HTTP_502_CAN_NO_RESPONSE_SPEC = {
    "description": "The CAN network did not respond to the request.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "status_code": {"type": "integer"},
                },
                "required": ["detail", "status_code"]
            },
            "example": {
                "detail": "The CAN network did not respond to the request.",
                "status_code": 502,
            },
        }
    }
}
