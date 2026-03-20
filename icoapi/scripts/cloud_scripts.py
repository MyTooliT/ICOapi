"""Helpers for comparing local files with cloud metadata"""

import os
from datetime import datetime, UTC

from icoapi.models.models import FileCloudStatus, FileCloudDetails
from icoapi.models.trident import RemoteObjectDetails


def parse_cloud_timestamp(timestamp: str) -> datetime:
    """Parse cloud timestamps into timezone-aware datetimes"""

    normalized = (
        timestamp.replace("Z", "+00:00")
        if timestamp.endswith("Z")
        else timestamp
    )
    parsed = datetime.fromisoformat(normalized)
    return (
        parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    )


def get_cloud_details(
    file_path: str,
    filename: str,
    cloud_files: list[RemoteObjectDetails],
) -> FileCloudDetails:
    """Build cloud sync details for a local file"""

    cloud_details = FileCloudDetails(
        status=FileCloudStatus.NOT_UPLOADED,
        upload_timestamp=None,
    )
    matches = [
        file for file in cloud_files
        if filename in file.objectname and file.last_status != "deleted"
    ]
    if not matches:
        return cloud_details

    latest_match = max(
        matches,
        key=lambda remote_file: parse_cloud_timestamp(
            remote_file.s3_lastmodified
        ),
    )
    cloud_details.upload_timestamp = latest_match.s3_lastmodified
    local_modified = datetime.fromtimestamp(os.path.getmtime(file_path), tz=UTC)
    cloud_modified = parse_cloud_timestamp(latest_match.s3_lastmodified)
    cloud_details.status = (
        FileCloudStatus.UP_TO_DATE
        if cloud_modified >= local_modified
        else FileCloudStatus.OUTDATED
    )
    return cloud_details
