import logging
import socket
from abc import abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from http.client import HTTPException

import requests

logger = logging.getLogger(__name__)

class HostNotFoundError(HTTPException):
    """Error for host not found"""


class AuthorizationError(HTTPException):
    """Error for authorization error"""


class PresignError(HTTPException):
    """Error representing failure in presigning"""


class CloudConnection:
    """
    Class that represents a cloud client
    """

    session: requests.Session

    def __init__(self):
        self.session = requests.Session()

    @abstractmethod
    def authenticate(self, *args, **kwargs):
        """Use this method to authenticate the client"""
        pass

    @abstractmethod
    def is_authenticated(self) -> bool:
        """Returns True if the client is authenticated"""
        pass

    @abstractmethod
    def refresh_authentication(self, *args, **kwargs):
        """Use this method to refresh the authentication"""
        pass

    @abstractmethod
    def request(self, method, path, **kwargs):
        """This is a generic HTTP request method"""
        pass

    def post(self, path, data):
        return self.request("POST", path, json=data)

    def put(self, path, data):
        return self.request("PUT", path, json=data)

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def delete(self, path, params=None):
        return self.request("DELETE", path, params=params)


class METHODS(StrEnum):
    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"


@dataclass
class RouteDescription:
    method: METHODS
    endpoint: str
    field_name: str|None = None


@dataclass
class BearerAuthRoutes:
    auth: RouteDescription
    refresh_auth: RouteDescription


class BearerAuthConnection(CloudConnection):
    """Base class for any cloud using bearer token authentication"""

    def __init__(
        self,
        service: str,
        username: str,
        password: str,
        domain: str,
        settings: BearerAuthRoutes
    ):
        super().__init__()
        self.service = service
        self.domain = domain
        self.secrets = {
            "username": username,
            "password": password
        }
        self.settings = settings


    def _update_tokens(self, auth_token: str, refresh_token: str):
        """Update the access and refresh tokens"""
        self.session.cookies.set(
            "refresh_token", refresh_token, domain=self.domain
        )
        self.session.headers.update(
            {"Authorization": f"Bearer {auth_token}"}
        )
        logger.info("Access and refresh token updated successfully.")


    def _acquire_access_token(self):
        """Retrieve access token from the authentication endpoint."""
        try:
            self.session.cookies.clear()
            response = self.session.post(
                f"{self.service}/{self.settings.auth.endpoint}",
                json=self.secrets
            )
            response.raise_for_status()

            token_data = response.json()

            self._update_tokens(
                token_data.get(self.settings.auth.field_name),
                token_data.get(self.settings.refresh_auth.field_name)
            )

            return

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection Error: {e}")
            raise HostNotFoundError(
                f"Could not establish connection to {self.service} " +
                f"under endpoint {self.settings.auth.endpoint}."
            )
        except requests.HTTPError as e:
            logger.error(f"Authorization failed - raised error: {e}")
            raise AuthorizationError(
                "Authorization failed."
            ) from e
        except socket.gaierror as e:
            logger.error(f"Socket failed! raised error: {e}")
            raise HostNotFoundError(
                f"Could not establish connection to {self.service} " 
                f"under endpoint {self.settings.auth.endpoint}."
            )
        except Exception as e:
            logger.error(
                f"Could not establish connection to {self.service} " 
                f"under endpoint {self.settings.auth.endpoint}."
                f" error: {e}"
            )
            raise HostNotFoundError(
                f"Could not establish connection to {self.service} " +
                f"under endpoint {self.settings.auth.endpoint}."
            ) from e

    def _refresh_with_refresh_token(self):
        """Refresh the access token using the refresh token."""
        refresh_token = self.session.cookies.get(
            "refresh_token", domain=self.domain
        )
        if not refresh_token:
            logger.error(
                "Refresh token not found when trying to refresh"
                " authentication."
            )

        try:
            response = self.session.post(
                f"{self.service}/{self.settings.refresh_auth.endpoint}",
                json={"refresh_token": refresh_token},
            )
            response.raise_for_status()

            token_data = response.json()
            new_access_token = token_data.get("access_token")
            new_refresh_token = token_data.get("refresh_token")

            self.session.cookies.set(
                "refresh_token", new_refresh_token, domain=self.domain
            )
            self.session.headers.update(
                {"Authorization": f"Bearer {new_access_token}"}
            )
            logger.info("Access and refresh token refreshed successfully.")
            return

        except requests.exceptions.RequestException as e:
            logger.error(f"Error refreshing access and refresh token: {e}")
            self.session.close()
            self.session = requests.Session()
            logger.warning("Refresh failed. Started new session.")
            self._ensure_auth()

    def _ensure_auth(self):
        """Ensure an access token is available before making a request."""
        if not self.is_authenticated():
            self._acquire_access_token()

    def authenticate(self, *args, **kwargs):
        self._ensure_auth()

    def is_authenticated(self) -> bool:
        return self.session.headers.get("Authorization") is not None

    def refresh_authentication(self):
        self._refresh_with_refresh_token()

    def request(self, method, path, **kwargs):
        self._refresh_with_refresh_token()
        self._ensure_auth()
        url = self.service + path

        try:
            logger.info(f"{method} request for {url}")
            response = self.session.request(method, url, **kwargs)
            if response.status_code == 401:
                logger.warning(
                    "Authentication expired during session. Refreshing..."
                )
                self._refresh_with_refresh_token()
                return self.session.request(
                    method, url, **kwargs
                )  # Retry with new token

            if response.status_code >= 500:
                logger.error(
                    "Trident API could not be reached, raised code"
                    f" {response.status_code}"
                )
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            raise HTTPException("Failed request") from e