"""Tests for file routes"""

# -- Imports ------------------------------------------------------------------

from pathlib import Path

import numpy as np
import tables
from pytest import fixture

from icoapi.api import app
from icoapi.scripts.file_handling import get_measurement_dir

# -- Fixtures -----------------------------------------------------------------


@fixture(name="temporary_measurement_dir")
def fixture_temporary_measurement_dir(tmp_path: Path):
    """Override the measurement directory with a temporary path"""

    app.dependency_overrides[get_measurement_dir] = lambda: str(tmp_path)
    yield tmp_path
    app.dependency_overrides.pop(get_measurement_dir, None)


@fixture(name="measurement_hdf5_file")
def fixture_measurement_hdf5_file(
    temporary_measurement_dir: Path,
) -> Path:
    """Create an empty measurement HDF5 file"""

    hdf5_path = temporary_measurement_dir / "measurement.hdf5"
    with tables.open_file(str(hdf5_path), mode="w"):
        pass

    return hdf5_path


# -- Tests --------------------------------------------------------------------


class TestFileRoutes:
    """File route test methods"""

    def test_upload_embedded_file(
        self, client, measurement_hdf5_file: Path
    ) -> None:
        """Test endpoint ``/{name}/embedded``"""

        payload = b"\x00\x10\xffabc"
        response = client.post(
            "files/measurement.hdf5/embedded",
            files={
                "file": ("hello.txt", payload, "text/plain"),
            },
        )

        assert response.status_code == 200
        assert response.json() == {
            "dataset_name": "hello_txt",
            "original_name": "hello.txt",
            "mime": "text/plain",
            "size": len(payload),
        }

        with tables.open_file(str(measurement_hdf5_file), mode="r") as hdf5_file:
            dataset = hdf5_file.get_node("/embedded_files/hello_txt")

            assert dataset.dtype.name == "uint8"
            assert dataset.read().tobytes() == payload
            assert dataset.attrs["size"] == len(payload)
            assert dataset.attrs["mime"] == "text/plain"
            assert dataset.attrs["original_name"] == "hello.txt"

    def test_upload_embedded_file_duplicate_name(
        self, client, measurement_hdf5_file: Path
    ) -> None:
        """Test endpoint ``/{name}/embedded`` for duplicate filenames"""

        with tables.open_file(str(measurement_hdf5_file), mode="a") as hdf5_file:
            group = hdf5_file.create_group("/", "embedded_files")
            hdf5_file.create_array(group, "hello_txt", np.array([1, 2, 3]))

        response = client.post(
            "files/measurement.hdf5/embedded",
            files={
                "file": ("hello.txt", b"new-payload", "text/plain"),
            },
        )

        assert response.status_code == 200
        assert response.json()["dataset_name"] == "hello_txt__1"

        with tables.open_file(str(measurement_hdf5_file), mode="r") as hdf5_file:
            dataset = hdf5_file.get_node("/embedded_files/hello_txt__1")
            assert dataset.read().tobytes() == b"new-payload"
            assert dataset.attrs["original_name"] == "hello.txt"

    def test_upload_embedded_file_not_found(self, client) -> None:
        """Test endpoint ``/{name}/embedded`` for missing HDF5 files"""

        response = client.post(
            "files/missing.hdf5/embedded",
            files={
                "file": ("hello.txt", b"payload", "text/plain"),
            },
        )

        assert response.status_code == 404
        assert response.json() == {
            "detail": "File not found. Check your measurement directory."
        }

    def test_upload_embedded_file_invalid_hdf5(
        self, client, temporary_measurement_dir: Path
    ) -> None:
        """Test endpoint ``/{name}/embedded`` for invalid HDF5 files"""

        invalid_hdf5_path = temporary_measurement_dir / "invalid.hdf5"
        invalid_hdf5_path.write_bytes(b"not-an-hdf5-file")

        response = client.post(
            "files/invalid.hdf5/embedded",
            files={
                "file": ("hello.txt", b"payload", "text/plain"),
            },
        )

        assert response.status_code == 422
        assert response.json() == {
            "detail": "Target file is not a valid HDF5 file."
        }
