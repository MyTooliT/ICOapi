import os
from os import PathLike

from dotenv import load_dotenv

def get_measurement_dir() -> str:
    """To be used for dependency injection."""
    measurement_dir = "icogui"
    env_loaded = load_dotenv("../ico-front/.env")
    if env_loaded:
        measurement_dir = os.getenv("VITE_BACKEND_MEASUREMENT_DIR")
    data_dir = ""

    if os.name == "nt":
        print("Found WINDOWS system.")
        data_dir = os.getenv("LOCALAPPDATA")
    elif os.name == "posix":
        print("Found POSIX system.")
        data_dir = linux_get_preferred_data_dir(measurement_dir)

    return os.path.join(data_dir, measurement_dir)


def linux_get_xdg_data_dirs() -> list[str]:
    """Get data directories for LINUX systems"""
    # Get XDG_DATA_DIRS or use the default value
    xdg_data_dirs = os.getenv("XDG_DATA_DIRS", "/usr/local/share:/usr/share")
    # Split the colon-separated paths into a list
    return xdg_data_dirs.split(":")


def linux_get_preferred_data_dir(app_name: str) -> str:
    """Get usable data directory for LINUX systems"""
    # Iterate through XDG_DATA_DIRS and pick the first writable directory
    for data_dir in linux_get_xdg_data_dirs():
        app_data_dir = os.path.join(data_dir, app_name)
        if os.access(data_dir, os.W_OK):  # Check if the directory is writable
            os.makedirs(app_data_dir, exist_ok=True)
            return app_data_dir
    raise PermissionError("No writable XDG_DATA_DIRS found")


def tries_to_traverse_directory(received_filename: str | PathLike) -> bool:
    directory_traversal_linux_chars = ["/", "%2F"]
    directory_traversal_windows_chars = ["\\", "%5C"]
    forbidden_substrings = ["..", *directory_traversal_linux_chars, *directory_traversal_windows_chars]

    for substring in forbidden_substrings:
        if substring in received_filename:
            return True

    return False