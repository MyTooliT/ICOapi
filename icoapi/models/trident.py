from dataclasses import dataclass, field
import json
from http.client import HTTPException
from typing import Any, Optional

import requests
import logging

from icoapi.models.cloud import BearerAuthConnection, BearerAuthRoutes, METHODS, RouteDescription

logger = logging.getLogger(__name__)


class HostNotFoundError(HTTPException):
    """Error for host not found"""


class AuthorizationError(HTTPException):
    """Error for authorization error"""


class PresignError(HTTPException):
    """Error representing failure in presigning"""


@dataclass
class FileUploadDetails:
    key: str
    name: str
    description: str
    author: str
    expiresInSeconds: int = 600
    metadata: dict = field(default_factory=dict)


@dataclass
class RemoteObjectDetails:
    id: int
    bucket: str
    objectname: str
    name: str
    description: Optional[str]
    metadata: dict
    created_at: str
    s3_lastmodified: str
    s3_size: int
    origin: str
    author: str
    type: str
    last_status: str
    last_status_time: str
    secrets_count: int
    access_total_count: int
    access_week_count: int
    last_access_time: Optional[str]
    active_offerings_count: int
    virtual_group: Optional[Any]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RemoteObjectDetails":
        return cls(**d)


@dataclass
class RemoteObjectListDetails:
    files: list[RemoteObjectDetails]
    total: int
    page: int
    size: int

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RemoteObjectListDetails":
        files = [RemoteObjectDetails.from_dict(x) for x in d.get("files", [])]
        return cls(
            files=files,
            total=d["total"],
            page=d["page"],
            size=d["size"],
        )


class StorageClient:
    def __init__(
        self,
        service: str,
        username: str,
        password: str,
        domain: str,
    ):
        settings = BearerAuthRoutes(
            auth=RouteDescription(
                method=METHODS.POST,
                endpoint="auth/login",
                field_name="access_token"
            ),
            refresh_auth=RouteDescription(
                method=METHODS.POST,
                endpoint="auth/refresh",
                field_name="refresh_token"
            )
        )
        self.connection = BearerAuthConnection(
            service, username, password, domain, settings
        )

    def get_client(self):
        return self.connection

    def get_remote_objects(self) -> RemoteObjectListDetails:
        try:
            response = self.connection.get("/management/files")
        except Exception:
            logger.error("Error getting remote objects.")
            raise HTTPException

        try:
            return RemoteObjectListDetails.from_dict(response.json())
        except json.decoder.JSONDecodeError as e:
            if response.status_code == 200:
                logger.info("No remote objects found.")
                return RemoteObjectListDetails([], 0, 0, 0)
            logger.error(f"Error with decoding JSON response: {e}")
            return RemoteObjectListDetails([], 0, 0, 0)

    def upload_file(
        self,
        file_path: str,
        object_details: FileUploadDetails,
    ):
        presigned_url_response = self.connection.post(
            "/management/files",
            data=object_details.__dict__,
        )

        print(presigned_url_response)

        if not presigned_url_response.status_code // 100 == 2:
            logger.error(
                "Error getting presigned URL for upload: code"
                f" {presigned_url_response.status_code} with"
                f" {presigned_url_response.text}"
            )
            raise PresignError

        data = presigned_url_response.json()
        presigned_url = data["presignedUrl"]
        if not presigned_url:
            logger.error(
                "Error getting presigned URL for upload: no presigned URL"
                " returned."
            )
            raise PresignError
        logger.info(f"Got presigned URL for upload: {presigned_url}")

        with open(file_path, "rb") as f:
            return requests.put(presigned_url, data=f)

    def authenticate(self, *args, **kwargs):
        self.connection.authenticate()

    def refresh(self, *args, **kwargs):
        self.connection.refresh()

    def is_authenticated(self):
        return self.connection.is_authenticated()

    def revoke_auth(self):
        self.connection.session.close()
        self.connection.session = requests.Session()
