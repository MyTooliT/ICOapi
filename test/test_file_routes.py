"""Tests for file routes"""

# -- Imports ------------------------------------------------------------------

import json
import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import tables
from pytest import fixture

from icoapi.api import app
from icoapi.models.globals import get_trident_client
from icoapi.models.trident import RemoteObjectDetails
from icoapi.scripts.file_handling import get_measurement_dir

# -- Fixtures -----------------------------------------------------------------


@fixture(name="temporary_measurement_dir")
def fixture_temporary_measurement_dir(tmp_path: Path):
    """Override the measurement directory with a temporary path"""

    app.dependency_overrides[get_measurement_dir] = lambda: str(tmp_path)
    yield tmp_path
    app.dependency_overrides.pop(get_measurement_dir, None)
    app.dependency_overrides.pop(get_trident_client, None)


@fixture(name="measurement_hdf5_file")
def fixture_measurement_hdf5_file(
    temporary_measurement_dir: Path,
) -> Path:
    """Create an empty measurement HDF5 file"""

    hdf5_path = temporary_measurement_dir / "measurement.hdf5"
    with tables.open_file(str(hdf5_path), mode="w"):
        pass

    return hdf5_path


@fixture(name="analyze_hdf5_file")
def fixture_analyze_hdf5_file(
    temporary_measurement_dir: Path,
) -> Path:
    """Create a minimal HDF5 measurement file for analyze tests"""

    hdf5_path = temporary_measurement_dir / "analyze.hdf5"
    with tables.open_file(str(hdf5_path), mode="w") as hdf5_file:
        acceleration_dtype = np.dtype([
            ("counter", np.uint32),
            ("timestamp", np.float64),
            ("first", np.float32),
        ])
        table = hdf5_file.create_table(
            "/", "acceleration", acceleration_dtype
        )
        row = table.row
        row["counter"] = 1
        row["timestamp"] = 1.5
        row["first"] = 2.5
        row.append()
        table.flush()

    return hdf5_path


# -- Tests --------------------------------------------------------------------


class TestFileRoutes:
    """File route test methods"""

    def test_list_files_cloud_status(
        self, client, temporary_measurement_dir: Path
    ) -> None:
        """Test endpoint ``/files`` reports cloud sync status"""

        not_uploaded = temporary_measurement_dir / "not_uploaded.hdf5"
        outdated = temporary_measurement_dir / "outdated.hdf5"
        up_to_date = temporary_measurement_dir / "up_to_date.hdf5"
        for file_path in (not_uploaded, outdated, up_to_date):
            file_path.write_bytes(b"content")

        os.utime(not_uploaded, (1735689600, 1735689600))
        os.utime(outdated, (1736035200, 1736035200))
        os.utime(up_to_date, (1735776000, 1735776000))

        remote_files = [
            RemoteObjectDetails(
                id=1,
                bucket="bucket",
                objectname="outdated.hdf5",
                name="outdated.hdf5",
                description=None,
                metadata={},
                created_at="2025-01-01T00:00:00Z",
                s3_lastmodified="2025-01-03T00:00:00Z",
                s3_size=7,
                origin="origin",
                author="author",
                type="file",
                last_status="uploaded",
                last_status_time="2025-01-03T00:00:00Z",
                secrets_count=0,
                access_total_count=0,
                access_week_count=0,
                last_access_time=None,
                active_offerings_count=0,
                virtual_group=None,
            ),
            RemoteObjectDetails(
                id=2,
                bucket="bucket",
                objectname="up_to_date.hdf5",
                name="up_to_date.hdf5",
                description=None,
                metadata={},
                created_at="2025-01-01T00:00:00Z",
                s3_lastmodified="2025-01-03T00:00:00Z",
                s3_size=7,
                origin="origin",
                author="author",
                type="file",
                last_status="uploaded",
                last_status_time="2025-01-03T00:00:00Z",
                secrets_count=0,
                access_total_count=0,
                access_week_count=0,
                last_access_time=None,
                active_offerings_count=0,
                virtual_group=None,
            ),
        ]

        def get_remote_objects():
            """Return controlled remote object data for tests"""

            return SimpleNamespace(files=remote_files)

        def get_fake_trident_client():
            """Return a storage client stub for tests"""

            return SimpleNamespace(get_remote_objects=get_remote_objects)

        app.dependency_overrides[get_trident_client] = get_fake_trident_client

        response = client.get("files")

        assert response.status_code == 200
        files_by_name = {
            file["name"]: file["cloud"] for file in response.json()["files"]
        }
        assert files_by_name["not_uploaded.hdf5"] == {
            "status": "not_uploaded",
            "upload_timestamp": None,
        }
        assert files_by_name["outdated.hdf5"] == {
            "status": "outdated",
            "upload_timestamp": "2025-01-03T00:00:00Z",
        }
        assert files_by_name["up_to_date.hdf5"] == {
            "status": "up_to_date",
            "upload_timestamp": "2025-01-03T00:00:00Z",
        }

    def test_upload_embedded_file(
        self, client, measurement_hdf5_file: Path
    ) -> None:
        """Test endpoint ``/{name}/embedded``"""

        payload = b"\x00\x10\xffabc"
        response = client.post(
            "files/measurement.hdf5/embedded",
            files=[
                ("files", ("hello.txt", payload, "text/plain")),
            ],
        )

        assert response.status_code == 200
        assert response.json() == [{
            "dataset_name": "hello_txt",
            "original_name": "hello.txt",
            "mime": "text/plain",
            "size": len(payload),
        }]

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
            files=[
                ("files", ("hello.txt", b"new-payload", "text/plain")),
            ],
        )

        assert response.status_code == 200
        assert response.json()[0]["dataset_name"] == "hello_txt__1"

        with tables.open_file(str(measurement_hdf5_file), mode="r") as hdf5_file:
            dataset = hdf5_file.get_node("/embedded_files/hello_txt__1")
            assert dataset.read().tobytes() == b"new-payload"
            assert dataset.attrs["original_name"] == "hello.txt"

    def test_upload_multiple_embedded_files(
        self, client, measurement_hdf5_file: Path
    ) -> None:
        """Test endpoint ``/{name}/embedded`` for multiple files"""

        response = client.post(
            "files/measurement.hdf5/embedded",
            files=[
                ("files", ("hello.txt", b"first", "text/plain")),
                ("files", ("world.bin", b"\x01\x02", "application/octet-stream")),
            ],
        )

        assert response.status_code == 200
        assert response.json() == [
            {
                "dataset_name": "hello_txt",
                "original_name": "hello.txt",
                "mime": "text/plain",
                "size": 5,
            },
            {
                "dataset_name": "world_bin",
                "original_name": "world.bin",
                "mime": "application/octet-stream",
                "size": 2,
            },
        ]

        with tables.open_file(str(measurement_hdf5_file), mode="r") as hdf5_file:
            hello = hdf5_file.get_node("/embedded_files/hello_txt")
            world = hdf5_file.get_node("/embedded_files/world_bin")
            assert hello.read().tobytes() == b"first"
            assert world.read().tobytes() == b"\x01\x02"

    def test_upload_embedded_file_not_found(self, client) -> None:
        """Test endpoint ``/{name}/embedded`` for missing HDF5 files"""

        response = client.post(
            "files/missing.hdf5/embedded",
            files=[
                ("files", ("hello.txt", b"payload", "text/plain")),
            ],
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
            files=[
                ("files", ("hello.txt", b"payload", "text/plain")),
            ],
        )

        assert response.status_code == 422
        assert response.json() == {
            "detail": "Target file is not a valid HDF5 file."
        }

    def test_download_embedded_file(
        self, client, measurement_hdf5_file: Path
    ) -> None:
        """Test endpoint ``/{name}/embedded/{dataset_name}``"""

        payload = b"download-payload"
        with tables.open_file(str(measurement_hdf5_file), mode="a") as hdf5_file:
            group = hdf5_file.create_group("/", "embedded_files")
            dataset = hdf5_file.create_array(group, "hello_txt", payload)
            dataset.attrs["mime"] = "text/plain"
            dataset.attrs["original_name"] = "hello.txt"

        response = client.get("files/measurement.hdf5/embedded/hello_txt")

        assert response.status_code == 200
        assert response.content == payload
        assert response.headers["content-type"] == "text/plain; charset=utf-8"
        assert (
            response.headers["content-disposition"]
            == (
                'attachment; filename="hello.txt";'
                " filename*=UTF-8''hello.txt"
            )
        )

    def test_download_embedded_file_not_found(
        self, client, measurement_hdf5_file: Path
    ) -> None:
        """Test endpoint ``/{name}/embedded/{dataset_name}`` for missing data"""

        assert measurement_hdf5_file.is_file()

        response = client.get("files/measurement.hdf5/embedded/missing")

        assert response.status_code == 404
        assert response.json() == {
            "detail": "File not found. Check your measurement directory."
        }

    def test_delete_embedded_file(
        self, client, measurement_hdf5_file: Path
    ) -> None:
        """Test endpoint ``/{name}/embedded/{dataset_name}`` for deletion"""

        with tables.open_file(str(measurement_hdf5_file), mode="a") as hdf5_file:
            group = hdf5_file.create_group("/", "embedded_files")
            hdf5_file.create_array(group, "hello_txt", b"payload")

        response = client.delete("files/measurement.hdf5/embedded/hello_txt")

        assert response.status_code == 200
        assert response.json() == {'dataset_name': 'hello_txt', 'file_name': 'measurement.hdf5'}

        with tables.open_file(str(measurement_hdf5_file), mode="r") as hdf5_file:
            assert "/embedded_files/hello_txt" not in hdf5_file

    def test_delete_embedded_file_not_found(
        self, client, measurement_hdf5_file: Path
    ) -> None:
        """Test delete endpoint for missing embedded data"""

        assert measurement_hdf5_file.is_file()

        response = client.delete("files/measurement.hdf5/embedded/missing")

        assert response.status_code == 404
        assert response.json() == {
            "detail": "File not found. Check your measurement directory."
        }

    def test_delete_embedded_file_invalid_hdf5(
        self, client, temporary_measurement_dir: Path
    ) -> None:
        """Test delete endpoint for invalid HDF5 files"""

        invalid_hdf5_path = temporary_measurement_dir / "invalid_delete.hdf5"
        invalid_hdf5_path.write_bytes(b"not-an-hdf5-file")

        response = client.delete(
            "files/invalid_delete.hdf5/embedded/hello_txt"
        )

        assert response.status_code == 422
        assert response.json() == {
            "detail": "Target file is not a valid HDF5 file."
        }

    def test_analyze_file_includes_embedded_file_information(
        self, client, analyze_hdf5_file: Path
    ) -> None:
        """Test endpoint ``/analyze/{name}`` includes embedded file info"""

        payload = b"download-payload"
        with tables.open_file(str(analyze_hdf5_file), mode="a") as hdf5_file:
            group = hdf5_file.create_group("/", "embedded_files")
            dataset = hdf5_file.create_array(group, "hello_txt", payload)
            dataset.attrs["mime"] = "text/plain"
            dataset.attrs["original_name"] = "hello.txt"
            dataset.attrs["size"] = len(payload)

        response = client.get("files/analyze/analyze.hdf5")

        assert response.status_code == 200

        metadata = json.loads(response.text.splitlines()[0])
        assert metadata["embedded_files"] == [{
            "dataset_name": "hello_txt",
            "original_name": "hello.txt",
            "mime": "text/plain",
            "size": len(payload),
            "download_path": "files/analyze.hdf5/embedded/hello_txt",
        }]
