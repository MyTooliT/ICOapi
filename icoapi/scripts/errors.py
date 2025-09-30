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

HTTP_400_INVALID_YAML_EXCEPTION = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to parse YAML payload.")
HTTP_400_INVALID_YAML_SPEC = {
    "description": "Failed to parse YAML payload.",
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
                "detail": "Failed to parse YAML payload.",
                "status_code": 400,
            },
        }
    }
}

HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_EXCEPTION = HTTPException(
    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
    detail="Unsupported media type for configuration upload."
)
HTTP_415_UNSUPPORTED_YAML_MEDIA_TYPE_SPEC = {
    "description": "Unsupported media type for configuration upload.",
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
                "detail": "Unsupported media type for configuration upload.",
                "status_code": 415,
            },
        }
    }
}

HTTP_422_METADATA_SCHEMA_EXCEPTION = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="Provided YAML does not satisfy metadata schema."
)
HTTP_422_METADATA_SCHEMA_SPEC = {
    "description": "Provided YAML does not satisfy metadata schema.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "status_code": {"type": "integer"}
                },
                "required": ["detail", "status_code"]
            },
            "example": {
                "detail": "Provided YAML does not satisfy metadata schema.",
                "status_code": 422
            },
        }
    }
}

HTTP_422_SENSORS_SCHEMA_EXCEPTION = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="Provided YAML does not satisfy sensors schema."
)
HTTP_422_SENSORS_SCHEMA_SPEC = {
    "description": "Provided YAML does not satisfy sensors schema.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "status_code": {"type": "integer"}
                },
                "required": ["detail", "status_code"]
            },
            "example": {
                "detail": "Provided YAML does not satisfy sensors schema.",
                "status_code": 422
            },
        }
    }
}

HTTP_422_DATASPACE_SCHEMA_EXCEPTION = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="Provided YAML does not satisfy sensors schema."
)
HTTP_422_DATASPACE_SCHEMA_SPEC = {
    "description": "Provided YAML does not satisfy sensors schema.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "status_code": {"type": "integer"}
                },
                "required": ["detail", "status_code"]
            },
            "example": {
                "detail": "Provided YAML does not satisfy sensors schema.",
                "status_code": 422
            },
        }
    }
}

HTTP_500_CONFIG_WRITE_EXCEPTION = HTTPException(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail="Failed to store configuration file."
)
HTTP_500_CONFIG_WRITE_SPEC = {
    "description": "Failed to store configuration file.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "status_code": {"type": "integer"}
                },
                "required": ["detail", "status_code"]
            },
            "example": {
                "detail": "Failed to store configuration file.",
                "status_code": 500
            },
        }
    }
}

HTTP_500_CONFIG_LIST_EXCEPTION = HTTPException(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail="Failed to list configuration backups."
)
HTTP_500_CONFIG_LIST_SPEC = {
    "description": "Failed to list configuration backups.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "status_code": {"type": "integer"}
                },
                "required": ["detail", "status_code"]
            },
            "example": {
                "detail": "Failed to list configuration backups.",
                "status_code": 500
            },
        }
    }
}

HTTP_404_CONFIG_BACKUP_NOT_FOUND_EXCEPTION = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND,
    detail="Requested configuration backup not found."
)
HTTP_404_CONFIG_BACKUP_NOT_FOUND_SPEC = {
    "description": "Requested configuration backup not found.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "status_code": {"type": "integer"}
                },
                "required": ["detail", "status_code"]
            },
            "example": {
                "detail": "Requested configuration backup not found.",
                "status_code": 404
            },
        }
    }
}

HTTP_400_INVALID_CONFIG_RESTORE_EXCEPTION = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="Invalid configuration restore request."
)
HTTP_400_INVALID_CONFIG_RESTORE_SPEC = {
    "description": "Invalid configuration restore request.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "status_code": {"type": "integer"}
                },
                "required": ["detail", "status_code"]
            },
            "example": {
                "detail": "Invalid configuration restore request.",
                "status_code": 400
            },
        }
    }
}

HTTP_500_CONFIG_RESTORE_EXCEPTION = HTTPException(
    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    detail="Failed to restore configuration file."
)
HTTP_500_CONFIG_RESTORE_SPEC = {
    "description": "Failed to restore configuration file.",
    "content": {
        "application/json": {
            "schema": {
                "type": "object",
                "properties": {
                    "detail": {"type": "string"},
                    "status_code": {"type": "integer"}
                },
                "required": ["detail", "status_code"]
            },
            "example": {
                "detail": "Failed to restore configuration file.",
                "status_code": 500
            },
        }
    }
}

