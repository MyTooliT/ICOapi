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

class TridentClient:
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
        #except requests.exceptions.RequestException as e:
            #logger.error(f"Error retrieving access and refresh token: {e}")
            # raise Exception(f"Failed to retrieve access and refresh token.") from e
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
        refresh_token = self.session.cookies.get("refresh_token", domain="iot.ift.tuwien.ac.at")
        if not refresh_token:
            logger.error("Refresh token not found when trying to refresh authentication.")
            # raise Exception("Refresh token not found when trying to refresh authentication.")

        try:
            response = self.session.post(f"{self.service}/auth/refresh", json={"refresh_token": refresh_token})
            response.raise_for_status()

            token_data = response.json()
            new_access_token = token_data.get("access_token")
            new_refresh_token = token_data.get("refresh_token")

            self.session.cookies.set("refresh_token", new_refresh_token, domain="iot.ift.tuwien.ac.at")
            self.session.headers.update({"Authorization": f"Bearer {new_access_token}"})
            logger.info("Access and refresh token refreshed successfully.")
            return new_access_token
        except requests.exceptions.RequestException as e:
            logger.error(f"Error refreshing access and refresh token: {e}")
            # raise Exception(f"Failed to refresh access token. Response: {response.text}") from e
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


class BaseClient:
    def get_buckets(self, *args, **kwargs):
        raise NotImplementedError

    def get_bucket_objects(self, *args, **kwargs):
        raise NotImplementedError

    def upload_file(self, *args, **kwargs):
        raise NotImplementedError

    def authenticate(self, *args, **kwargs):
        raise NotImplementedError

    def refresh(self, *args, **kwargs):
        raise NotImplementedError

    def request(self, *args, **kwargs):
        raise NotImplementedError

    def post(self, *args, **kwargs):
        raise NotImplementedError

    def put(self, *args, **kwargs):
        raise NotImplementedError

    def get(self, *args, **kwargs):
        raise NotImplementedError

    def delete(self, *args, **kwargs):
        raise NotImplementedError

    def is_authenticated(self):
        raise NotImplementedError



class StorageClient(BaseClient):
    def __init__(self, service: str, username: str, password: str, default_bucket: str, domain: str):
        self._client = TridentClient(service, username, password, domain)
        self.default_bucket = default_bucket

    def get_buckets(self):
        return self._client.get("/s3/buckets").json()

    def get_bucket_objects(self, bucket: str|None = None):
        try:
            response = self._client.get(f"/s3/list?bucket={bucket if bucket else self.default_bucket}")
        except Exception as e:
            logger.error(f"Error getting bucket objects.")
            raise HTTPException

        try:
            return response.json()
        except json.decoder.JSONDecodeError:
            logger.error(response.text)
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

        with open(file_path, "rb") as f:
            return self._client.request("POST", "/s3/upload", files={"file": f}, data={"bucket": bucket, "key": complete_filename_with_folder})

    def authenticate(self, *args, **kwargs):
        self._client.authenticate()

    def refresh(self, *args, **kwargs):
        self._client.refresh()

    def is_authenticated(self):
        return self._client.is_authenticated()


class NoopClient(BaseClient):
    def get_buckets(self, *args, **kwargs):
        logger.debug("No cloud connection. Skipped <get_buckets>")

    def get_bucket_objects(self, *args, **kwargs):
        logger.debug("No cloud connection. Skipped <get_bucket_objects>")

    def upload_file(self, *args, **kwargs):
        logger.debug("No cloud connection. Skipped <upload_file>")

    def authenticate(self, *args, **kwargs):
        logger.debug("No cloud connection. Skipped <authenticate>")

    def refresh(self, *args, **kwargs):
        logger.debug("No cloud connection. Skipped <refresh>")

    def is_authenticated(self, *args, **kwargs):
        logger.debug("No cloud connection. Skipped <is_authenticated>")