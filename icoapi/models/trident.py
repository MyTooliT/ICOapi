# https://git.ift.tuwien.ac.at/lab/ift/infrastructure/trident-client/-/blob/main/main.py?ref_type=heads
import json
import socket
from http.client import HTTPException

import requests
import logging

from icoapi.scripts.file_handling import tries_to_traverse_directory

logger = logging.getLogger(__name__)

class HostNotFoundError(HTTPException):
    """Error for host not found"""

class AuthorizationError(HTTPException):
    """Error for authorization error"""

class PresignError(HTTPException):
    """Error representing failure in presigning"""

class TridentConnection:
    def __init__(self, service: str, username: str, password: str, domain: str):
        self.service = service
        self.username = username
        self.password = password
        self.domain = domain
        self.secrets = {"username": username, "password": password}
        self.session = requests.Session()

    def _get_access_token(self):
        """Retrieve access token from the authentication endpoint."""
        try:
            self.session.cookies.clear()
            response = self.session.post(f"{self.service}/auth/login", json=self.secrets)
            response.raise_for_status()

            token_data = response.json()
            access_token = token_data.get("access_token")
            refresh_token = token_data.get("refresh_token")

            self.session.headers.update({"Authorization": f"Bearer {access_token}"})
            self.session.cookies.set("refresh_token", refresh_token, domain=self.domain)

            logger.info("Successfully retrieved access and refresh token.")
            return access_token

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Connection Error: {e}")
            raise HostNotFoundError("Could not find Trident API under specified address.")
        except requests.HTTPError as e:
            logger.error(f"Authorization failed - raised error: {e}")
            raise AuthorizationError(f"Trident API valid, but authorization failed.") from e
        except socket.gaierror as e:
            logger.error(f"Socket failed! raised error: {e}")
            raise HostNotFoundError(f"Could not find Trident API under specified address.")
        except Exception as e:
            logger.error(f"Could not find Trident API under specified address - raised error: {e}")
            raise HostNotFoundError("Could not find Trident API under specified address.") from e


    def _refresh_with_refresh_token(self):
        """Refresh the access token using the refresh token."""
        refresh_token = self.session.cookies.get("refresh_token", domain=self.domain)
        if not refresh_token:
            logger.error("Refresh token not found when trying to refresh authentication.")

        try:
            response = self.session.post(f"{self.service}/auth/refresh", json={"refresh_token": refresh_token})
            response.raise_for_status()

            token_data = response.json()
            new_access_token = token_data.get("access_token")
            new_refresh_token = token_data.get("refresh_token")

            self.session.cookies.set("refresh_token", new_refresh_token, domain=self.domain)
            self.session.headers.update({"Authorization": f"Bearer {new_access_token}"})
            logger.info("Access and refresh token refreshed successfully.")
            return new_access_token
        except requests.exceptions.RequestException as e:
            logger.error(f"Error refreshing access and refresh token: {e}")
            self.session.close()
            self.session = requests.Session()
            logger.warning("Refresh failed. Started new session.")
            self._ensure_auth()

    def _ensure_auth(self):
        """Ensure an access token is available before making a request."""
        if not self.session.headers.get("Authorization"):
            self._get_access_token()

    def is_authenticated(self):
        """Return whether the authentication was successful."""
        return self.session.headers.get("Authorization") is not None

    def authenticate(self):
        self._ensure_auth()

    def refresh(self):
        self._refresh_with_refresh_token()

    def request(self, method, path, **kwargs):
        """Generic request handler with authentication and retry on token expiration."""
        self._refresh_with_refresh_token()
        self._ensure_auth()
        url = self.service + path

        try:
            logger.info(f"{method} request for {url}")
            response = self.session.request(method, url, **kwargs)
            if response.status_code == 401:
                logger.warning("Authentication expired during session. Refreshing...")
                self._refresh_with_refresh_token()
                return self.session.request(method, url, **kwargs)  # Retry with new token

            if response.status_code >= 500:
                logger.error(f"Trident API could not be reached, raised code {response.status_code}")
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {e}")
            raise HTTPException(f"Failed request. Response: {response.text}") from e

    def post(self, path, data):
        return self.request("POST", path, json=data)

    def put(self, path, data):
        return self.request("PUT", path, json=data)

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def delete(self, path, params=None):
        return self.request("DELETE", path, params=params)


class StorageClient:
    def __init__(self, service: str, username: str, password: str, default_bucket: str, domain: str):
        self.connection = TridentConnection(service, username, password, domain)
        self.default_bucket = default_bucket

    def get_client(self):
        return self.connection

    def get_buckets(self):
        return self.connection.get("/s3/buckets").json()

    def get_bucket_objects(self, bucket: str|None = None):
        try:
            response = self.connection.get(f"/s3/list?bucket={bucket if bucket else self.default_bucket}")
        except Exception as e:
            logger.error(f"Error getting bucket objects.")
            raise HTTPException

        try:
            return response.json()
        except json.decoder.JSONDecodeError as e:
            if response.status_code == 200:
                logger.info(f"No objects found in bucket <{bucket if bucket else self.default_bucket}>.")
                return []
            logger.error(f"Error with decoding JSON response: {e}")
            return []

    def upload_file(self, file_path: str, filename: str, bucket: str | None = None, folder: str | None = "default"):
        bucket = bucket if bucket else self.default_bucket
        complete_filename_with_folder = filename
        if folder is None:
            logger.info(f"Trying file <{filename}> to bucket <{bucket}> with no folder specified.")
        elif folder == "":
            logger.warning(f"Trying file <{filename}> to bucket <{bucket}> with folder incorrectly specified as empty string; assuming no folder.")
        elif tries_to_traverse_directory(folder):
            logger.error(f"Trying file <{filename}> to bucket <{bucket}> with folder <{folder}> trying to traverse directories!")
        else:
            complete_filename_with_folder = f"{folder}/{filename}"
            logger.info(f"Trying file <{filename}> to bucket <{bucket}> under folder <{folder}>.")

        presigned_url_response = self.connection.get("/s3/presigned-upload", params={
            "bucket": bucket,
            "key": complete_filename_with_folder,
            "expiresInSeconds": 600
        })

        if presigned_url_response.status_code != 200:
            logger.error(f"Error getting presigned URL for upload: code {presigned_url_response.status_code} with {presigned_url_response.text}")
            raise PresignError

        data = presigned_url_response.json()
        presigned_url = data["presignedUrl"]
        if not presigned_url:
            logger.error(f"Error getting presigned URL for upload: no presigned URL returned.")
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