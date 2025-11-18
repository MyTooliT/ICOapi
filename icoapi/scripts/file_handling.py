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
    # First try: local development
    env_loaded = load_dotenv(os.path.join(os.path.abspath(os.path.join(os.getcwd(), os.pardir)), "config", ".env"), verbose=True)
    if not env_loaded:
        # Second try: configs directory
        logger.warning(f"Environment variables not found in local directory. Trying to load from app data: {get_config_dir()}")
        env_loaded = load_dotenv(os.path.join(get_config_dir(), ".env"), verbose=True)
    if not env_loaded and is_bundled():
        # Third try: we should be in the bundled state
        bundle_dir = sys._MEIPASS
        logger.warning(f"Environment variables not found in local directory. Trying to load from app data: {bundle_dir}")
        env_loaded = load_dotenv(os.path.join(bundle_dir, "config", ".env"), verbose=True)
    if not env_loaded:
        # Fourth try: load default configuration from package data
        package_data = files('icoapi').joinpath("config")
        logger.warning(f"Environment variables not found in app data. Trying to load from package data: %s", package_data)
        env_loaded = load_dotenv(stream=(package_data.joinpath("default.env").open('r', encoding='utf-8')))
    if not env_loaded:
        logger.critical(f"Environment variables not found")
        raise EnvironmentError(".env not found")

def is_bundled():
    return getattr(sys, 'frozen', False)

def get_application_dir() -> str:
    name = os.getenv("VITE_APPLICATION_FOLDER", "ICOdaq")
    return user_data_dir(name, appauthor=False)

def get_measurement_dir() -> str:
    measurement_dir = os.path.join(get_application_dir(), "measurements")
    logger.info(f"Measurement directory: {measurement_dir}")
    return measurement_dir

def get_config_dir() -> str:
    config_dir = os.path.join(get_application_dir(), "config")
    logger.info(f"Config directory: {config_dir}")
    return config_dir

def get_dataspace_file_path() -> str:
    return os.path.join(get_config_dir(), CONFIG_FILE_DEFINITIONS.DATASPACE.filename)

def get_sensors_file_path() -> str:
    return os.path.join(get_config_dir(), CONFIG_FILE_DEFINITIONS.SENSORS.filename)

def get_metadata_file_path() -> str:
    return os.path.join(get_config_dir(), CONFIG_FILE_DEFINITIONS.METADATA.filename)

def copy_config_files_if_not_exists(src_path: str, dest_path: str):
    for f in os.listdir(src_path):
        if os.path.isfile(os.path.join(dest_path, f)):
            logger.info(f"Config file {f} already exists in {dest_path}")
        else:
            shutil.copy(os.path.join(src_path, f), os.path.join(dest_path, f))
            logger.info(f"Copied config file {f} to {dest_path}")

def tries_to_traverse_directory(received_filename: str | os.PathLike) -> bool:
    directory_traversal_linux_chars = ["/", "%2F"]
    directory_traversal_windows_chars = ["\\", "%5C"]
    forbidden_substrings = ["..", *directory_traversal_linux_chars, *directory_traversal_windows_chars]

    for substring in forbidden_substrings:
        if substring in received_filename:
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


def get_disk_space_in_gb(path_or_drive: str | os.PathLike= "/") -> DiskCapacity:
    try:
        total, used, free = shutil.disk_usage(path_or_drive)

        total_gb = round(total / (2**30), 2)
        available_gb = round(free / (2**30), 2)

        return DiskCapacity(total_gb, available_gb)
    except Exception as e:
        logger.error(f"Error retrieving disk space: {e}")
        return DiskCapacity(None, None)


def get_drive_or_root_path() -> str:
    os_type = platform.system()
    return "C:\\" if os_type == "Windows" else "/"


def get_suffixed_filename(base_name: str, directory: str) -> str:
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
    if not os.path.exists(path):
        os.makedirs(path)
        logger.info(f"Created directory {path}")
