"""Measurement files in the ICOschema bundle format

With multi STU support (see :mod:`icoapi.scripts.features`) measurements are
stored as ICOschema bundles: HDF5 files with one *source* (one STU/STH
combination) per data stream. This module contains everything the API needs
to work with such a file that is not recording it (see
:mod:`icoapi.scripts.recording`): finding out if a file is a bundle, reading
it in the shape the API clients know from the old format, and changing
metadata and attachments of an existing file.

Files in the old format stay readable. Which code handles a file depends on
the file, never on the environment.

The API specific information that ICOschema has no field for (which streaming
slot each channel is, the sensors as configured, tool name, …) is stored as
JSON in the ``additional_data`` of the source, below the key ``icoapi``.
"""

# -- Imports ------------------------------------------------------------------

import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import h5py
import numpy as np
import pandas as pd
from fastapi import HTTPException
from icoschema.v2 import attachments
from tables import NoSuchNodeError

from icoapi.models.models import EmbeddedFileInfo, SourceInfo

# -- Globals ------------------------------------------------------------------

logger = logging.getLogger(__name__)

FORMAT_VERSION_ATTRIBUTE = "icoschema_format_version"
"""Root attribute that contains the format version of an ICOschema file"""

ADDITIONAL_DATA_KEY = "icoapi"
"""Key of the API specific information in the ``additional_data`` of a source"""

SLOTS = ("first", "second", "third")
"""Streaming slots, in the order of the channels of a source"""

AXES = {"first": "x", "second": "y", "third": "z"}
"""Name of the column in the old format for each streaming slot"""

# -- Classes ------------------------------------------------------------------


class BundleMetadataStorage(ABC):
    """Where pre and post metadata of a bundle is written to

    Same job as ``MetadataStorage`` in :mod:`icoapi.scripts.measurement` has
    for the old format. The metadata (a JSON string) is an attribute, pictures
    are stored as attachments of the bundle.
    """

    @abstractmethod
    def __setitem__(self, key: str, value: str) -> None:
        """Store metadata attribute (e.g. ``pre_metadata``)"""

    @abstractmethod
    def write_pictures(self, name: str, images: list[str]) -> None:
        """Store (and overwrite) the base64 encoded pictures called ``name``"""


class CollectedMetadata(BundleMetadataStorage):
    """Collect metadata until the file it belongs to exists"""

    def __init__(self) -> None:
        self.attributes: dict[str, str] = {}
        self.pictures: dict[str, list[str]] = {}

    def __setitem__(self, key: str, value: str) -> None:
        self.attributes[key] = value

    def write_pictures(self, name: str, images: list[str]) -> None:
        self.pictures[name] = images


class BundleFileMetadata(BundleMetadataStorage):
    """Change the metadata of an existing bundle file

    The metadata is stored for every source of the bundle. The file is opened
    for every operation, so no file stays open between operations.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = str(path)

        with h5py.File(self.path, "r") as file:
            if not _primary_tables(file):
                raise NoSuchNodeError(
                    f"No measurement data in file “{self.path}”"
                )

    def __setitem__(self, key: str, value: str) -> None:
        with h5py.File(self.path, "a") as file:
            for table in _primary_tables(file):
                table.attrs[key] = value

    def write_pictures(self, name: str, images: list[str]) -> None:
        attachments.add_picture(self.path, name, images, overwrite=True)

    def clear(self, prefix: str) -> None:
        """Remove metadata and pictures of the given prefix, if there are any"""

        with h5py.File(self.path, "a") as file:
            for table in _primary_tables(file):
                table.attrs.pop(f"{prefix}_metadata", None)
            group = file.get("pictures")
            if isinstance(group, h5py.Group):
                for name in [
                    name for name in group if name.startswith(f"{prefix}__")
                ]:
                    del group[name]


@dataclass
class BundleFileData:
    """Content of a bundle file in the shape of the old format

    The attributes are text, like in the old format, so the same code can
    process them.
    """

    acceleration_df: pd.DataFrame
    sensor_df: pd.DataFrame
    attributes: dict[str, str]
    pictures: dict[str, list[str]]
    embedded_files: list[EmbeddedFileInfo]
    sources: list[SourceInfo]


# -- Functions ----------------------------------------------------------------


def _text(value: Any) -> str:
    """Convert (HDF5) attribute value to text"""

    return value.decode() if isinstance(value, bytes) else str(value)


def is_bundle_file(path: Path | str) -> bool:
    """Check if the given file is an ICOschema bundle

    Returns:

        ``True``, if the file is a HDF5 file of ICOschema (schema version 2),
        ``False`` for everything else, including files in the old format and
        files that are not HDF5 files.

    """

    try:
        with h5py.File(path, "r") as file:
            version = file.attrs.get(FORMAT_VERSION_ATTRIBUTE)
    except OSError:
        return False

    return version is not None and _text(version).startswith("2.")


def _source_groups(file: h5py.File) -> list[h5py.Group]:
    """Get the groups (or the file) that contain the sources of a bundle"""

    if "sources" in file.attrs and "sources" in file:
        return [
            file["sources"][_text(name)]
            for name in np.atleast_1d(file.attrs["sources"])
        ]
    return [file]


def _primary_tables(file: h5py.File) -> list[h5py.Dataset]:
    """Get the tables that store the measurement data of the sources"""

    if "primary_table" not in file.attrs:
        return []
    name = _text(file.attrs["primary_table"])
    return [group[name] for group in _source_groups(file) if name in group]


def _named_tables(file: h5py.File) -> list[tuple[str, h5py.Dataset]]:
    """Get the name and the table with the measurement data of each source"""

    if "primary_table" not in file.attrs:
        return []
    table_name = _text(file.attrs["primary_table"])
    if "sources" in file.attrs and "sources" in file:
        names = [_text(name) for name in np.atleast_1d(file.attrs["sources"])]
        return [
            (name, file["sources"][name][table_name])
            for name in names
            if table_name in file["sources"][name]
        ]
    if table_name not in file:
        return []
    table = file[table_name]
    # Name of the only source if the file does not say
    return [(_text(table.attrs.get("source_name", "source1")), table)]


def _start_offsets(times: list[str | None]) -> list[float | None]:
    """Get the seconds between the earliest start time and each start time"""

    parsed: list[datetime | None] = []
    for time in times:
        try:
            parsed.append(datetime.fromisoformat(time) if time else None)
        except ValueError:
            parsed.append(None)
    known = [time for time in parsed if time is not None]
    earliest = min(known) if known else None
    return [
        None
        if time is None or earliest is None
        else (time - earliest).total_seconds()
        for time in parsed
    ]


def list_sources(path: Path | str) -> list[SourceInfo]:
    """Get the sources of a bundle file (also those without data)"""

    with h5py.File(path, "r") as file:
        tables = _named_tables(file)
        attributes = [
            {key: _text(value) for key, value in table.attrs.items()}
            for _name, table in tables
        ]

    offsets = _start_offsets(
        [attribute.get("Start_Time") for attribute in attributes]
    )
    return [
        SourceInfo(
            name=name,
            stu_mac=attribute.get("stu_mac"),
            sth_mac=attribute.get("sth_mac"),
            start_time=attribute.get("Start_Time"),
            start_offset=offset,
        )
        for (name, _table), attribute, offset in zip(
            tables, attributes, offsets, strict=False
        )
    ]


def source_name(tool_name: str | None) -> str:
    """Get a valid name for the source of a measurement with the given tool"""

    name = (tool_name or "").strip().replace("/", "_").lstrip(".")
    return name if name else "sth"


def read_bundle_file(
    path: Path | str, source: str | None = None
) -> BundleFileData:
    """Read the data and metadata of a source of a bundle file in the old shape

    Args:

        path:
            The path of the bundle file

        source:
            The name of the source (see :func:`list_sources`). A file with a
            single source does not need it.

    Raises:

        NoSuchNodeError:
            If the file does not contain measurement data (yet)

        HTTPException:
            If the file has more than one source and ``source`` does not say
            which one to show (422), or if there is no such source (404)

    """

    sources = list_sources(path)
    names = [info.name for info in sources]
    if source is None and len(names) > 1:
        raise HTTPException(
            status_code=422,
            detail=(
                f"File contains {len(names)} sources. Select one with the "
                f"parameter “source”: {', '.join(names)}"
            ),
        )
    if source is not None and source not in names:
        raise HTTPException(
            status_code=404,
            detail=(
                f"File has no source “{source}”. "
                + (
                    f"Sources: {', '.join(names)}"
                    if names
                    else "It has no sources"
                )
            ),
        )

    with h5py.File(path, "r") as file:
        tables = [
            table
            for name, table in _named_tables(file)
            if source is None or name == source
        ]
        if not tables:
            raise NoSuchNodeError(f"No measurement data in file “{path}”")

        table = tables[0]
        rows = table[()]
        if len(rows) == 0:
            raise NoSuchNodeError(f"No measurement data in file “{path}”")
        attributes = {
            name: _text(value) for name, value in table.attrs.items()
        }
        sensors = (
            table.parent["sensors"][()] if "sensors" in table.parent else []
        )

    extra = json.loads(attributes.get("additional_data", "{}")).get(
        ADDITIONAL_DATA_KEY, {}
    )

    channels = [
        name
        for name in rows.dtype.names
        if name not in ("counter", "timestamp")
    ]
    slots = extra.get("slots") or list(SLOTS[: len(channels)])
    data: dict[str, Any] = {
        "counter": (
            rows["counter"]
            if "counter" in rows.dtype.names
            else np.zeros(len(rows), dtype=np.uint8)
        ),
        "timestamp": rows["timestamp"],
    }
    for slot, channel in zip(slots, channels, strict=False):
        data[AXES[slot]] = rows[channel]

    return BundleFileData(
        acceleration_df=pd.DataFrame(data),
        sensor_df=pd.DataFrame(
            extra.get("sensors") or _sensors_from_table(sensors, slots)
        ),
        attributes=_old_attributes(attributes, extra),
        sources=sources,
        pictures=attachments.read_pictures(str(path)),
        embedded_files=[
            EmbeddedFileInfo(
                dataset_name=info.name,
                original_name=info.original_name,
                mime=info.mime,
                size=info.size,
                download_path="",
            )
            for info in attachments.list_files(str(path))
        ],
    )


def _sensors_from_table(
    sensors: Any, slots: list[str]
) -> list[dict[str, Any]]:
    """Describe sensors of a file that was not written by this API

    The ranges of the sensors are not part of ICOschema. They are chosen so
    that they describe the conversion of the channel.
    """

    result = []
    for number, (_slot, row) in enumerate(
        zip(slots, sensors, strict=False), start=1
    ):
        gain, offset = float(row["gain"]), float(row["offset"])
        result.append(
            {
                "name": row["name"].decode(),
                "sensor_type": row["sensor_type"].decode() or None,
                "sensor_id": row["sensor_id"].decode(),
                "unit": row["unit"].decode(),
                "dimension": row["dimension"].decode(),
                "phys_min": offset,
                "phys_max": gain + offset,
                "volt_min": 0.0,
                "volt_max": 1.0,
                "scaling_factor": gain,
                "offset": offset,
                "channel_number": number,
            }
        )
    return result


def _old_attributes(
    attributes: dict[str, str], extra: dict[str, Any]
) -> dict[str, str]:
    """Get the table attributes the old format has for a source"""

    old: dict[str, str] = {}

    def copy(old_name: str, name: str) -> None:
        if name in attributes:
            old[old_name] = attributes[name]

    copy("Start_Time", "Start_Time")
    copy("adc_prescaler", "adc_prescaler")
    copy("adc_acquisition_time", "adc_acquisition_time")
    copy("adc_oversampling_rate", "adc_oversample_rate")
    copy("adc_reference_voltage", "adc_reference_voltage")
    old["conversion"] = "true"
    copy("sth_mac_address", "sth_mac")
    copy("stu_mac_address", "stu_mac")
    for name in ("tool_name", "start_supply_voltage", "simulated"):
        if extra.get(name) is not None:
            old[name] = str(extra[name])
    copy("pre_metadata", "pre_metadata")
    copy("post_metadata", "post_metadata")

    return old


# -- Embedded Files -----------------------------------------------------------


def embedded_file_names(path: Path | str) -> list[str]:
    """Get the dataset names of the embedded files of a bundle file"""

    return [info.name for info in attachments.list_files(str(path))]


def add_embedded_file(
    path: Path | str,
    dataset_name: str,
    content: bytes,
    mime_type: str,
    original_name: str,
) -> None:
    """Store a file in a bundle file"""

    attachments.add_file(
        str(path),
        dataset_name,
        content,
        mime=mime_type,
        original_name=original_name,
    )


def get_embedded_file(path: Path | str, dataset_name: str):
    """Read an embedded file of a bundle file

    Raises:

        NoSuchNodeError: If the bundle does not contain the file

    """

    try:
        return attachments.read_file(str(path), dataset_name)
    except KeyError as error:
        raise NoSuchNodeError(dataset_name) from error


def delete_embedded_file(path: Path | str, dataset_name: str) -> None:
    """Remove an embedded file from a bundle file

    Raises:

        NoSuchNodeError: If the bundle does not contain the file

    """

    try:
        attachments.remove_file(str(path), dataset_name)
    except KeyError as error:
        raise NoSuchNodeError(dataset_name) from error
