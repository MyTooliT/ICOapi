"""Tests for measurement files in the ICOschema bundle format

The bundle format is used with multi STU support. Almost all tests record the
same measurement in the old and in the bundle format and check that the API
shows both in the same way.

Timestamps of the fake streams do not start with 0: A measurement that gets 0
as first timestamp sets its start time again with the second message.
"""

# -- Imports ------------------------------------------------------------------

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import h5py
from fastapi import HTTPException
from icoschema import DatasetBundle
from icoschema.v2 import (
    BundleWriter,
    ChannelMetadata,
    LinearConversion,
    SourceSpec,
)
from icoschema.v2 import (
    Sensor as SchemaSensor,
)
from icotronic.can.streaming import StreamingData
from pytest import MonkeyPatch, approx, fixture, mark, raises
from tables import NoSuchNodeError
from test_measurement_events import FakeStream, Measurement

from icoapi.models.event_bus import Channel
from icoapi.models.models import MeasuredSensor, Metadata, MetadataPrefix
from icoapi.routers.cloud_routes import upload_file
from icoapi.routers.file_routes import (
    get_analyzed_file,
    get_file_meta,
    list_files_and_capacity,
)
from icoapi.scripts import measurement, recording
from icoapi.scripts.bundle import is_bundle_file, source_name
from icoapi.scripts.data_handling import (
    AccelerationDataNotFoundError,
    get_file_data,
)
from icoapi.scripts.features import (
    MULTI_STU_SUPPORT_VARIABLES,
    multi_stu_support,
)
from icoapi.scripts.file_handling import (
    append_embedded_file_to_hdf5,
    delete_embedded_file_from_hdf5,
    get_embedded_file_from_hdf5,
)
from icoapi.scripts.measurement import (
    clear_metadata,
    open_metadata_storage,
    write_metadata,
)

# -- Fixtures -----------------------------------------------------------------

FORMATS = ["legacy", "bundle"]


def set_format(monkeypatch: MonkeyPatch, file_format: str) -> None:
    """Switch multi STU support on (for bundle) or off (for legacy)"""

    for name in MULTI_STU_SUPPORT_VARIABLES:
        monkeypatch.delenv(name, raising=False)
    if file_format == "bundle":
        monkeypatch.setenv(MULTI_STU_SUPPORT_VARIABLES[0], "1")


class CounterStream(FakeStream):
    """Stream that sends messages with the given counters"""

    def __init__(self, counters: list[int], timestamps: list[float]) -> None:
        super().__init__(timestamps)
        self.counters = counters

    async def _messages(self):
        for counter, timestamp in zip(
            self.counters, self.timestamps, strict=False
        ):
            yield (
                StreamingData(
                    counter=counter, timestamp=timestamp, values=[8000] * 3
                ),
                None,
            )


@fixture(name="recorded", params=FORMATS)
async def fixture_recorded(request, tmp_path: Path, monkeypatch: MonkeyPatch):
    """Measurement file in the old or in the bundle format"""

    set_format(monkeypatch, request.param)
    fake = Measurement(tmp_path, monkeypatch)
    await fake.run(FakeStream([100.0, 100.5, 101.0]))
    assert fake.channels == [Channel.RECORDING_FINISHED]
    assert is_bundle_file(fake.file_path) == (request.param == "bundle")
    return fake.file_path


# -- Tests --------------------------------------------------------------------


class TestFeatureFlag:
    """Test switch for multi STU support"""

    @mark.parametrize("value", ["1", "true", "TRUE", " yes ", "on"])
    @mark.parametrize("name", MULTI_STU_SUPPORT_VARIABLES)
    def test_enabled(self, monkeypatch: MonkeyPatch, name, value) -> None:
        """Both spellings of the variable switch the feature on"""

        for variable in MULTI_STU_SUPPORT_VARIABLES:
            monkeypatch.delenv(variable, raising=False)
        monkeypatch.setenv(name, value)

        assert multi_stu_support()

    @mark.parametrize("value", ["", "0", "false", "no", "off", "2"])
    def test_disabled(self, monkeypatch: MonkeyPatch, value) -> None:
        """Other values do not switch the feature on"""

        for variable in MULTI_STU_SUPPORT_VARIABLES:
            monkeypatch.setenv(variable, value)

        assert not multi_stu_support()

    def test_unset(self, monkeypatch: MonkeyPatch) -> None:
        """The feature is off by default"""

        for variable in MULTI_STU_SUPPORT_VARIABLES:
            monkeypatch.delenv(variable, raising=False)

        assert not multi_stu_support()

    def test_recording_file_class(self, monkeypatch: MonkeyPatch) -> None:
        """The variable selects the format of the measurement file"""

        config: Any = None
        set_format(monkeypatch, "legacy")
        assert isinstance(
            recording.open_recording_file(Path("a.hdf5"), config),
            recording.LegacyRecordingFile,
        )
        set_format(monkeypatch, "bundle")
        assert isinstance(
            recording.open_recording_file(Path("a.hdf5"), config),
            recording.BundleRecordingFile,
        )


class TestRecording:
    """Test what is stored in a measurement file"""

    async def test_bundle(self, tmp_path: Path, monkeypatch: MonkeyPatch):
        """The bundle contains the data and the description of the source"""

        set_format(monkeypatch, "bundle")
        fake = Measurement(tmp_path, monkeypatch)
        await fake.run(FakeStream([100.0, 100.5, 101.0]))

        bundle = DatasetBundle.from_hdf5(str(fake.file_path))
        source = bundle.recording.only_source()  # type: ignore[union-attr]

        assert source.name == "sth"
        assert source.stu_mac == "00-00-00-00-00-01"
        assert source.sth_mac == "00-11-22-33-44-55"
        hardware = source.hardware_metadata
        assert (
            hardware.adc_prescaler,
            hardware.adc_acquisition_time,
            hardware.adc_oversample_rate,
            hardware.adc_reference_voltage,
        ) == (2, 8, 64, "3.3")
        assert source.channel_count == 1
        assert hardware.channel1_metadata.sensor.sensor_id == "acc"
        assert hardware.channel1_metadata.sensor.unit == "g"
        conversion = hardware.channel1_metadata.conversion
        assert isinstance(conversion, LinearConversion)
        assert conversion.gain == 200 / 3.3
        assert conversion.offset == 100 - 200 / 3.3 * 3.3

        # One channel: Three values per message
        assert source.counter.tolist() == [0, 0, 0, 1, 1, 1, 2, 2, 2]
        assert source.timestamps.tolist() == (
            [0] * 3 + [500_000] * 3 + [1_000_000] * 3
        )
        assert source.recording_metadata.start_time is not None

    async def test_same_data(self, tmp_path: Path, monkeypatch: MonkeyPatch):
        """Both formats store the same values"""

        data = {}
        for file_format in FORMATS:
            set_format(monkeypatch, file_format)
            directory = tmp_path / file_format
            directory.mkdir()
            fake = Measurement(directory, monkeypatch)
            await fake.run(FakeStream([100.0, 100.25, 100.5, 101.0]))
            data[file_format] = get_file_data(str(fake.file_path))

        legacy, bundle = data["legacy"], data["bundle"]
        assert list(legacy.acceleration_df.columns) == [
            "counter",
            "timestamp",
            "x",
        ]
        assert list(bundle.acceleration_df.columns) == list(
            legacy.acceleration_df.columns
        )
        assert (
            bundle.acceleration_df.to_numpy()
            == legacy.acceleration_df.to_numpy()
        ).all()
        assert bundle.acceleration_df["timestamp"].dtype == "uint64"

    async def test_dataloss(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Both formats report the same amount of lost messages"""

        reported: dict[str, float] = {}
        for file_format in FORMATS:
            set_format(monkeypatch, file_format)
            directory = tmp_path / file_format
            directory.mkdir()
            fake = Measurement(directory, monkeypatch)

            async def send_dataloss(_state, dataloss, name=file_format):
                reported[name] = dataloss

            monkeypatch.setattr(measurement, "send_dataloss", send_dataloss)
            await fake.run(
                CounterStream(
                    [0, 1, 4, 5, 255, 2],
                    [100.0, 100.2, 100.4, 100.6, 100.8, 101.0],
                )
            )

        assert reported["legacy"] > 0
        assert reported["bundle"] == reported["legacy"]

    async def test_failure_without_file(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Only the name is published if the bundle could not be created"""

        def writer(*_arguments: Any) -> None:
            raise OSError("Unable to create file")

        set_format(monkeypatch, "bundle")
        monkeypatch.setattr(recording, "ThreadedBundleWriter", writer)
        fake = Measurement(tmp_path, monkeypatch)

        await fake.run(FakeStream([0.0]))

        assert fake.channels == [Channel.RECORDING_FAILED]
        assert fake.messenger.events[0][1]["size"] is None

    async def test_failure_without_data(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """A measurement without data has a file, but no data to show"""

        set_format(monkeypatch, "bundle")
        fake = Measurement(tmp_path, monkeypatch)
        await fake.run(FakeStream([], failure=TimeoutError("No data")))

        assert fake.channels == [Channel.RECORDING_FAILED]
        assert fake.messenger.file_usable_when_stopped == [True]
        with raises(AccelerationDataNotFoundError):
            get_file_data(str(fake.file_path))

    def test_source_name(self) -> None:
        """The name of a source is a valid name for a HDF5 node"""

        assert source_name("Test-STH") == "Test-STH"
        assert source_name("A/B") == "A_B"
        assert source_name(".hidden") == "hidden"
        assert source_name("") == "sth"
        assert source_name(None) == "sth"


class TestFileData:
    """Test what the API shows for measurement files"""

    async def test_data_and_metadata(self, recorded: Path) -> None:
        """Files look the same, no matter how they are stored"""

        data = get_file_data(str(recorded))

        assert len(data.acceleration_df) == 9
        attributes = data.acceleration_meta.attributes
        assert (
            attributes["conversion"] is True
            or attributes["conversion"] == "true"
        )
        assert attributes["adc_prescaler"] == 2
        assert attributes["adc_acquisition_time"] == 8
        assert attributes["adc_oversampling_rate"] == 64
        assert attributes["adc_reference_voltage"] == 3.3
        assert attributes["sth_mac_address"] == "00-11-22-33-44-55"
        assert attributes["stu_mac_address"] == "00-00-00-00-00-01"
        assert "Start_Time" in attributes
        assert data.acceleration_meta.name == "acceleration"

        sensors = data.sensor_df.to_dict(orient="records")
        assert len(sensors) == 1
        # Old files contain bytes, the API converts them to text
        assert MeasuredSensor(**sensors[0]).sensor_id == "acc"
        assert sensors[0]["phys_min"] == -100
        assert sensors[0]["phys_max"] == 100
        assert sensors[0]["volt_max"] == approx(3.3)  # old: 32 bit
        assert sensors[0]["channel_number"] == 1

    async def test_same_shape(self, tmp_path: Path, monkeypatch: MonkeyPatch):
        """Both formats have the same metadata and sensor information"""

        shown = {}
        for file_format in FORMATS:
            set_format(monkeypatch, file_format)
            directory = tmp_path / file_format
            directory.mkdir()
            fake = Measurement(directory, monkeypatch)
            await fake.run(FakeStream([100.0, 100.5, 101.0]))
            data = get_file_data(str(fake.file_path))
            # PyTables adds information about its tables, the time differs
            attributes = {
                key: value
                for key, value in data.acceleration_meta.attributes.items()
                if key != "Start_Time"
                and not re.match(
                    r"^(CLASS|TITLE|VERSION|NROWS|FIELD_\d+_(NAME|FILL))$", key
                )
            }
            sensors = [
                MeasuredSensor(**sensor).model_dump()
                for sensor in data.sensor_df.to_dict(orient="records")
            ]
            shown[file_format] = (
                attributes,
                sensors,
                data.acceleration_meta.type,
            )

        assert shown["legacy"][0] == shown["bundle"][0]
        assert shown["legacy"][2] == shown["bundle"][2]
        # Old files store numbers with 32 bit and no sensor type as empty text
        legacy_sensors, bundle_sensors = shown["legacy"][1], shown["bundle"][1]
        assert len(legacy_sensors) == len(bundle_sensors) == 1
        for key, value in bundle_sensors[0].items():
            if isinstance(value, float):
                assert legacy_sensors[0][key] == approx(value), key
            else:
                assert (legacy_sensors[0][key] or None) == (value or None), key

    async def test_old_files_are_read_with_the_feature_on(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """The format of a file does not depend on the environment"""

        set_format(monkeypatch, "legacy")
        fake = Measurement(tmp_path, monkeypatch)
        await fake.run(FakeStream([100.0, 100.5, 101.0]))
        set_format(monkeypatch, "bundle")

        assert not is_bundle_file(fake.file_path)
        assert len(get_file_data(str(fake.file_path)).acceleration_df) == 9
        with open_metadata_storage(fake.file_path) as storage:
            write_metadata(
                MetadataPrefix.POST, Metadata("1", "profile", {}), storage
            )
        assert (
            get_file_data(str(fake.file_path)).acceleration_meta.attributes[
                "post_metadata"
            ]["profile"]
            == "profile"
        )


class TestSources:
    """Test files with more than one source"""

    @staticmethod
    def write(path: Path) -> None:
        """Write a bundle with two sources that start 0.25 seconds apart"""

        def spec(name: str, mac: str, start: str, gain: float) -> SourceSpec:
            return SourceSpec(
                name=name,
                channels=[
                    ChannelMetadata(
                        sensor=SchemaSensor(sensor_id="acc", unit="g"),
                        conversion=LinearConversion(gain=gain, offset=0.0),
                    )
                ],
                start_time=start,
                stu_mac=f"00-00-00-00-00-{mac}",
                sth_mac=f"11-11-11-11-11-{mac}",
                pre_metadata='{"version": "1", "profile": "milling",'
                ' "parameters": {}}',
                additional_data=json.dumps({"icoapi": {"slots": ["first"]}}),
            )

        specs = [
            spec("Test-STH", "01", "2026-01-01T00:00:00.000000", 1.0),
            spec("Other-STH", "02", "2026-01-01T00:00:00.250000", 2.0),
        ]
        with BundleWriter(str(path), specs) as writer:
            for index in range(4):
                writer["Test-STH"].append_row(
                    index * 1000, [1.0 + index], index
                )
                writer["Other-STH"].append_row(
                    index * 1000, [100.0 + index], index
                )

    @fixture(name="two")
    def fixture_two(self, tmp_path: Path) -> Path:
        """Path of a measurement file with two sources"""

        path = tmp_path / "two.hdf5"
        self.write(path)
        return path

    def test_source_is_required(self, two: Path) -> None:
        """A file with more than one source does not show one by default"""

        with raises(HTTPException) as error:
            get_file_data(str(two))

        assert error.value.status_code == 422
        assert "Test-STH" in error.value.detail
        assert "Other-STH" in error.value.detail

    def test_every_source_has_its_data(self, two: Path) -> None:
        """The data and the metadata of the selected source is shown"""

        first = get_file_data(str(two), "Test-STH")
        second = get_file_data(str(two), "Other-STH")

        assert first.acceleration_df["x"].tolist() == [1, 2, 3, 4]
        assert second.acceleration_df["x"].tolist() == [100, 101, 102, 103]
        assert first.acceleration_meta.attributes["sth_mac_address"] == (
            "11-11-11-11-11-01"
        )
        assert second.acceleration_meta.attributes["stu_mac_address"] == (
            "00-00-00-00-00-02"
        )
        assert second.sensor_df["scaling_factor"].tolist() == [2.0]

    def test_sources_are_listed(self, two: Path) -> None:
        """Every source is described, with its start relative to the others"""

        for source in ("Test-STH", "Other-STH"):
            sources = get_file_data(str(two), source).sources
            assert [info.name for info in sources] == ["Test-STH", "Other-STH"]
            assert [info.start_offset for info in sources] == [0.0, 0.25]
            assert sources[1].sth_mac == "11-11-11-11-11-02"
            assert sources[1].start_time == "2026-01-01T00:00:00.250000"

    def test_unknown_source(self, two: Path) -> None:
        """There is no data for a source that does not exist"""

        with raises(HTTPException) as error:
            get_file_data(str(two), "Nothing")

        assert error.value.status_code == 404
        assert "Test-STH" in error.value.detail

    async def test_single_source(self, recorded: Path) -> None:
        """A file with one source (or none) works with and without source"""

        if not is_bundle_file(recorded):
            with raises(HTTPException) as error:
                get_file_data(str(recorded), "sth")
            assert error.value.status_code == 404
            assert not get_file_data(str(recorded)).sources
            return

        without = get_file_data(str(recorded))
        assert [info.name for info in without.sources] == ["sth"]
        assert get_file_data(str(recorded), "sth").sources == without.sources
        with raises(HTTPException) as error:
            get_file_data(str(recorded), "other")
        assert error.value.status_code == 404

    async def test_file_list_names_the_sources(self, two: Path) -> None:
        """The file list has the names of the sources of a file"""

        old = two.parent / "old.hdf5"
        old.write_bytes(b"not a bundle")
        listed = await list_files_and_capacity(
            str(two.parent),
            None,  # type: ignore[arg-type]
        )

        sources = {file.name: file.sources for file in listed.files}
        assert sources == {
            "two.hdf5": ["Test-STH", "Other-STH"],
            "old.hdf5": None,
        }

    async def test_metadata_route(self, two: Path) -> None:
        """The route shows the sources and the data of the selected one"""

        directory = str(two.parent)
        with raises(HTTPException) as error:
            await get_file_meta(two.name, directory)
        assert error.value.status_code == 422

        shown = await get_file_meta(two.name, directory, "Other-STH")
        assert [info.name for info in shown.sources] == [
            "Test-STH",
            "Other-STH",
        ]
        assert shown.acceleration.attributes["sth_mac_address"] == (
            "11-11-11-11-11-02"
        )

    async def test_analyze_route(self, two: Path) -> None:
        """The route streams the data of the selected source"""

        directory = str(two.parent)
        with raises(HTTPException):
            await get_analyzed_file(two.name, directory)

        response = await get_analyzed_file(two.name, directory, "Other-STH")
        lines = [
            json.loads(line)
            async for line in response.body_iterator
            for line in str(line).splitlines()
        ]
        assert [info["name"] for info in lines[0]["sources"]] == [
            "Test-STH",
            "Other-STH",
        ]
        assert lines[1]["datasets"][0]["data"][0] == 100.0

    async def test_metadata_is_changed_for_every_source(
        self, two: Path
    ) -> None:
        """Pre and post metadata are the same for every source"""

        with open_metadata_storage(two) as storage:
            clear_metadata(MetadataPrefix.POST, storage)
            write_metadata(
                MetadataPrefix.POST,
                Metadata("2", "turning", {"feed": 3}),
                storage,
            )

        for source in ("Test-STH", "Other-STH"):
            attributes = get_file_data(
                str(two), source
            ).acceleration_meta.attributes
            assert attributes["post_metadata"]["profile"] == "turning"
            assert attributes["pre_metadata"]["profile"] == "milling"

    async def test_cloud_upload(self, two: Path) -> None:
        """The whole file is uploaded, described by the first source"""

        # The upload expects pre and post metadata
        with open_metadata_storage(two) as storage:
            write_metadata(
                MetadataPrefix.POST, Metadata("1", "milling", {}), storage
            )
        client = MagicMock()
        config: Any = SimpleNamespace(virtual_group_root="root")

        await upload_file(two.name, client, str(two.parent), config)

        client.upload_file.assert_called_once()
        path, details = client.upload_file.call_args.args
        assert path == str(two)
        assert details.virtual_group == "root/milling"
        assert details.metadata["attributes"]["sth_mac_address"] == (
            "11-11-11-11-11-01"
        )


class TestMetadata:
    """Test changing the metadata of a measurement file"""

    @staticmethod
    def metadata(**parameters: Any) -> Metadata:
        """Create metadata"""

        return Metadata("1.2.3", "milling", {"speed": 1000, **parameters})

    async def test_post_metadata(self, recorded: Path) -> None:
        """Post metadata can be written, overwritten and removed"""

        with open_metadata_storage(recorded) as storage:
            clear_metadata(MetadataPrefix.POST, storage)
            write_metadata(MetadataPrefix.POST, self.metadata(), storage)

        attributes = get_file_data(str(recorded)).acceleration_meta.attributes
        assert attributes["post_metadata"]["profile"] == "milling"
        assert attributes["post_metadata"]["parameters"] == {"speed": 1000}
        assert "pre_metadata" not in attributes

        with open_metadata_storage(recorded) as storage:
            clear_metadata(MetadataPrefix.POST, storage)
            write_metadata(
                MetadataPrefix.POST,
                Metadata("2", "turning", {"feed": 2}),
                storage,
            )
        attributes = get_file_data(str(recorded)).acceleration_meta.attributes
        assert attributes["post_metadata"]["profile"] == "turning"
        assert attributes["post_metadata"]["parameters"] == {"feed": 2}

        with open_metadata_storage(recorded) as storage:
            clear_metadata(MetadataPrefix.POST, storage)
        attributes = get_file_data(str(recorded)).acceleration_meta.attributes
        assert "post_metadata" not in attributes

    async def test_pictures(self, recorded: Path) -> None:
        """Pictures are part of the metadata they belong to"""

        pictures = {"0": "aGVsbG8=", "1": "d29ybGQ="}
        with open_metadata_storage(recorded) as storage:
            write_metadata(
                MetadataPrefix.PRE,
                self.metadata(workpiece_pictures=pictures),
                storage,
            )
            write_metadata(
                MetadataPrefix.POST,
                self.metadata(pictures={"0": "dGVzdA=="}),
                storage,
            )

        data = get_file_data(str(recorded))
        assert data.pictures == {
            "pre__workpiece_pictures": ["aGVsbG8=", "d29ybGQ="],
            "post__pictures": ["dGVzdA=="],
        }
        attributes = data.acceleration_meta.attributes
        assert attributes["pre_metadata"]["parameters"] == {
            "speed": 1000,
            "workpiece_pictures": {0: "aGVsbG8=", 1: "d29ybGQ="},
        }
        assert attributes["post_metadata"]["parameters"]["pictures"] == {
            0: "dGVzdA=="
        }

        # Removing metadata removes its pictures, but not the others
        with open_metadata_storage(recorded) as storage:
            clear_metadata(MetadataPrefix.PRE, storage)
        assert list(get_file_data(str(recorded)).pictures) == [
            "post__pictures"
        ]

    async def test_pre_metadata_of_measurement(
        self, tmp_path: Path, monkeypatch: MonkeyPatch
    ) -> None:
        """Metadata that is part of the instructions is stored in the file"""

        for file_format in FORMATS:
            set_format(monkeypatch, file_format)
            directory = tmp_path / file_format
            directory.mkdir()
            fake = Measurement(directory, monkeypatch)
            monkeypatch.setattr(
                measurement,
                "open_recording_file",
                _with_pre_metadata(measurement.open_recording_file),
            )
            await fake.run(FakeStream([100.0, 101.0]))
            monkeypatch.undo()

            data = get_file_data(str(fake.file_path))
            attributes = data.acceleration_meta.attributes
            # The API shows pictures as part of the metadata
            assert attributes["pre_metadata"] == {
                "version": "1",
                "profile": "p",
                "parameters": {"a": 1, "pictures": {0: "aGk="}},
            }, file_format
            assert data.pictures == {"pre__pictures": ["aGk="]}, file_format

    async def test_file_without_data(self, tmp_path: Path) -> None:
        """A file without measurement data has no metadata to edit"""

        path = tmp_path / "other.hdf5"
        with h5py.File(path, "w") as file:
            file.attrs["icoschema_format_version"] = "2.0"
        with raises(NoSuchNodeError), open_metadata_storage(path):
            pass


class TestEmbeddedFiles:
    """Test files that are stored in measurement files"""

    async def test_embedded_files(self, recorded: Path) -> None:
        """Files can be added, read, listed and deleted"""

        upload = append_embedded_file_to_hdf5(
            str(recorded), "My Report 1.pdf", b"%PDF-1.4", "application/pdf"
        )
        again = append_embedded_file_to_hdf5(
            str(recorded), "My Report 1.pdf", b"other", None
        )

        assert upload.dataset_name == "My_Report_1_pdf"
        assert upload.original_name == "My Report 1.pdf"
        assert upload.mime == "application/pdf"
        assert upload.size == 8
        assert again.dataset_name != upload.dataset_name
        assert again.mime == "application/octet-stream"

        infos = get_file_data(str(recorded)).embedded_files
        assert {info.dataset_name for info in infos} == {
            upload.dataset_name,
            again.dataset_name,
        }

        content = get_embedded_file_from_hdf5(
            str(recorded), upload.dataset_name
        )
        assert content.content == b"%PDF-1.4"
        assert content.original_name == "My Report 1.pdf"
        assert content.mime == "application/pdf"

        delete_embedded_file_from_hdf5(str(recorded), upload.dataset_name)
        assert [
            info.dataset_name
            for info in get_file_data(str(recorded)).embedded_files
        ] == [again.dataset_name]
        with raises(NoSuchNodeError):
            get_embedded_file_from_hdf5(str(recorded), upload.dataset_name)
        with raises(NoSuchNodeError):
            delete_embedded_file_from_hdf5(str(recorded), upload.dataset_name)


# -- Functions ----------------------------------------------------------------


def _with_pre_metadata(open_file):
    """Wrap ``open_recording_file`` to measure with pre metadata"""

    def wrapper(path, streaming_configuration):
        recording_file = open_file(path, streaming_configuration)
        original = recording_file.start

        def start(**arguments):
            arguments["instructions"].meta = Metadata(
                "1", "p", {"a": 1, "pictures": {"0": "aGk="}}
            )
            original(**arguments)

        recording_file.start = start
        return recording_file

    return wrapper


def test_downsample_keeps_peaks() -> None:
    """Reducing data keeps the smallest and largest values"""

    import numpy as np
    import pandas as pd

    from icoapi.scripts.data_handling import downsample_min_max

    rows = 100_001
    values = np.sin(np.arange(rows) / 50.0)
    values[12_345] = 99.0
    values[77_777] = -99.0
    data = pd.DataFrame(
        {
            "counter": np.arange(rows) % 256,
            "timestamp": np.arange(rows),
            "x": values,
        }
    )

    reduced = downsample_min_max(data, 2_000)
    assert len(reduced) <= 2_100
    assert reduced["x"].max() == 99.0 and reduced["x"].min() == -99.0
    assert reduced["timestamp"].is_monotonic_increasing
    assert reduced["timestamp"].iloc[-1] >= rows - 1 - rows // 1000
    # Small data stays as it is
    assert len(downsample_min_max(data.iloc[:500], 2_000)) == 500


def test_downsample_min_max_covers_all_rows() -> None:
    """The reduced data has no stretch that is reduced to two rows

    The size of the buckets used to be rounded down, so the rows after the
    last full bucket (up to as many as `max_rows / 2`) all ended up in the
    last bucket (a recording of 146 403 rows lost its last five seconds)."""

    import numpy as np
    import pandas as pd

    from icoapi.scripts.data_handling import downsample_min_max

    rows = 146_403
    data = pd.DataFrame(
        {
            "counter": np.arange(rows) % 256,
            "timestamp": np.arange(rows),
            "x": np.sin(np.arange(rows) / 7.0),
        }
    )

    reduced = downsample_min_max(data, 100_000)
    gaps = np.diff(reduced["timestamp"].to_numpy())
    assert len(reduced) <= 100_100
    assert gaps.max() <= 6
    assert reduced["timestamp"].iloc[-1] >= rows - 6
