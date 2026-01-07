"""File handling code"""

import logging
import os
import platform
import sys
from typing import Tuple
import shutil
import re
from importlib.resources import files


from dotenv import load_dotenv
from platformdirs import user_data_dir

from icoapi.models.models import DiskCapacity
from icoapi.scripts.config_helper import CONFIG_FILE_DEFINITIONS

logger = logging.getLogger(__name__)


def load_env_file():
    """Load environment configuration"""

    # First try: local development
    env_loaded = load_dotenv(
        os.path.join(
            os.path.abspath(os.path.join(os.getcwd(), os.pardir)),
            "config",
            ".env",
        ),
        verbose=True,
    )
    if not env_loaded:
        # Second try: configs directory
        logger.warning(
            "Environment variables not found in local directory. Trying to"
            " load from app data: %s",
            get_config_dir(),
        )
        env_loaded = load_dotenv(
            os.path.join(get_config_dir(), ".env"), verbose=True
        )
        if not env_loaded:
            env_loaded = load_dotenv(
                os.path.join(get_config_dir(), "default.env"), verbose=True
            )
    if not env_loaded and is_bundled():
        # Third try: we should be in the bundled state
        bundle_dir = sys._MEIPASS  # pylint: disable=protected-access
        logger.warning(
            "Environment variables not found in local directory. Trying to"
            " load from app data: %s",
            bundle_dir,
        )
        env_loaded = load_dotenv(
            os.path.join(bundle_dir, "config", ".env"), verbose=True
        )
    if not env_loaded:
        # Fourth try: load default configuration from package data
        package_data = files("icoapi").joinpath("config")
        logger.warning(
            "Environment variables not found in app data. Trying to load from"
            " package data: %s",
            package_data,
        )
        env_loaded = load_dotenv(
            stream=(
                package_data.joinpath("default.env").open(
                    "r", encoding="utf-8"
                )
            )
        )
    if not env_loaded:
        logger.critical("Environment variables not found")
        raise EnvironmentError(".env not found")


def is_bundled():
    """Check if in bundled state"""

    return getattr(sys, "frozen", False)


def get_application_dir() -> str:
    """Get application directory"""

    name = os.getenv("VITE_APPLICATION_FOLDER", "ICOdaq")
    return user_data_dir(name, appauthor=False)


def get_measurement_dir() -> str:
    """Get measurement directory"""

    measurement_dir = os.path.join(get_application_dir(), "measurements")
    logger.info("Measurement directory: %s", measurement_dir)
    return measurement_dir


def get_config_dir() -> str:
    """Get configuration directory"""

    config_dir = os.path.join(get_application_dir(), "config")
    logger.info("Config directory: %s", config_dir)
    return config_dir


def get_dataspace_file_path() -> str:
    """Get dataspace configuration path"""

    return os.path.join(
        get_config_dir(), CONFIG_FILE_DEFINITIONS.DATASPACE.filename
    )


def get_sensors_file_path() -> str:
    """Get path to sensor configuration file"""

    return os.path.join(
        get_config_dir(), CONFIG_FILE_DEFINITIONS.SENSORS.filename
    )


def get_metadata_file_path() -> str:
    """Get path of metadata configuration"""

    return os.path.join(
        get_config_dir(), CONFIG_FILE_DEFINITIONS.METADATA.filename
    )


def copy_config_files_if_not_exists(src_path: str, dest_path: str):
    """Copy configuration file, if it does not exist yet"""

    for f in os.listdir(src_path):
        if os.path.isfile(os.path.join(dest_path, f)):
            logger.info("Config file %s already exists in %s", f, dest_path)
        else:
            if f.endswith(".env"):
                shutil.copy(os.path.join(src_path, f), os.path.join(dest_path, ".env"))
            else:
                shutil.copy(os.path.join(src_path, f), os.path.join(dest_path, f))
            logger.info("Copied config file %s to %s", f, dest_path)


def tries_to_traverse_directory(received_filename: str | os.PathLike) -> bool:
    """Check if a received filename tries to traverse the dir hierarchy"""

    directory_traversal_linux_chars = ["/", "%2F"]
    directory_traversal_windows_chars = ["\\", "%5C"]
    forbidden_substrings = [
        "..",
        *directory_traversal_linux_chars,
        *directory_traversal_windows_chars,
    ]
    filename = str(received_filename)

    for substring in forbidden_substrings:
        if substring in filename:
            return True

    return False


def is_dangerous_filename(filename: str) -> Tuple[bool, str | None]:
    """
    Tries to determine if a filename is dangerous.
    Mainly by focussing on two aspects:
    - Is there an attempt to traverse directories
    - Is the *.hdf5 ending present in the filename
    """

    if tries_to_traverse_directory(filename):
        return True, "Tried to traverse directories"

    if not filename.endswith(".hdf5"):
        return True, "Tried to download non-HDF5-file"

    return False, None


def get_disk_space_in_gib(
    path_or_drive: str | os.PathLike = "/",
) -> DiskCapacity:
    """Get disk space in gibibyte"""

    try:
        total, _, free = shutil.disk_usage(path_or_drive)

        total_gb = round(total / (2**30), 2)
        available_gb = round(free / (2**30), 2)

        return DiskCapacity(total_gb, available_gb)
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error("Error retrieving disk space: %s", e)
        return DiskCapacity(None, None)


def get_drive_or_root_path() -> str:
    """Get root of filesystem"""

    os_type = platform.system()
    return "C:\\" if os_type == "Windows" else "/"


def get_suffixed_filename(base_name: str, directory: str) -> str:
    """Get suffixed filename"""

    possible_filename = base_name
    suffix: int = 0
    while possible_filename in os.listdir(directory):
        suffix += 1
        tokens = possible_filename.split(".")
        extension = tokens[-1]
        # reassemble filename if dots were used in it (bad user, bad!)
        name = ".".join(tokens[:-1])
        has_suffix = bool(re.search(r"__\d+$", name))
        if has_suffix:
            name = "__".join(name.split("__")[:-1])
        possible_filename = f"{name}__{suffix}.{extension}"

    return possible_filename


def ensure_folder_exists(path):
    """Create folder if it does not exist already"""

    if not os.path.exists(path):
        os.makedirs(path)
        logger.info("Created directory %s", path)
