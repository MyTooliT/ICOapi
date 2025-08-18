import logging
import os
import platform
import sys
from typing import Tuple
import shutil
import re

from dotenv import load_dotenv
from platformdirs import user_data_dir

from icoapi.models.models import DiskCapacity

logger = logging.getLogger(__name__)

def load_env_file():
    env_loaded = load_dotenv(".env")
    if getattr(sys, 'frozen', False):
        # we are running in a bundle
        bundle_dir = sys._MEIPASS
        logger.info(f"Detected installed application state - bundle directory: {bundle_dir}")
        env_loaded = env_loaded | load_dotenv(os.path.join(bundle_dir, ".env"))
    if not env_loaded:
        logger.critical(f"Environment variables not found")
        raise EnvironmentError(".env not found")

def get_measurement_dir() -> str:
    """To be used for dependency injection."""
    load_env_file()

    # Check for full path in .env
    full_path = os.getenv("VITE_BACKEND_FULL_MEASUREMENT_PATH")
    if full_path:
        logger.info(f"Used full / absolute path for measurements: {full_path}")
        return os.path.abspath(full_path)
    else:
        # No full path, so combine measurement directory with default location
        measurement_dir = os.getenv("VITE_BACKEND_MEASUREMENT_DIR", "icodaq")
        data_dir = user_data_dir(measurement_dir)

        logger.info(f"Measurement directory: {data_dir}")
        return data_dir


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
