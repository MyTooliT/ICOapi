"""Helpers for comparing local files with cloud metadata"""
import hashlib
import os
from datetime import datetime, UTC
import logging

from icoapi.models.models import FileCloudStatus, FileCloudDetails
from icoapi.models.trident import RemoteObjectDetails


logger = logging.getLogger(__name__)


def parse_cloud_timestamp(timestamp: str | None) -> datetime:
    """Parse cloud timestamps into timezone-aware datetimes"""

    if timestamp is None:
        return datetime.max.replace(tzinfo=UTC)

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
        id=None
    )

    matches = [
        file for file in cloud_files
        if file.name == filename and file.last_status != "deleted"
    ]

    if not matches:
        return cloud_details

    if len(matches) > 1:
        logger.error(
            "Multiple non-deleted matches for file %s: with statuses %s",
            filename, str(list(map(lambda x: x.last_status, matches))))
        raise ValueError(
            f"Multiple non-deleted matches for file {filename}: with "
            f"ids {list(map(lambda x: x.id, matches))} "
            f"statuses {list(map(lambda x: x.last_status, matches))}"
        )

    latest_match = matches[0]

    local_modified = datetime.fromtimestamp(os.path.getmtime(file_path), tz=UTC)
    cloud_modified = parse_cloud_timestamp(latest_match.s3_lastmodified)

    if local_modified > cloud_modified:
        print(f"id: {latest_match.id} | local_modified: {local_modified}, cloud_modified: {cloud_modified}")

    cloud_details.upload_timestamp = latest_match.s3_lastmodified
    cloud_details.id = latest_match.id

    if latest_match.last_status == 'available':
        if local_modified > cloud_modified:
            local_hash = hashlib.md5(open(file_path, "rb").read()).hexdigest()
            print(f"id: {latest_match.id} | local_hash: {local_hash}, cloud_hash: {latest_match.etag}")
            if local_hash != latest_match.etag:
                cloud_details.status = FileCloudStatus.OUTDATED
            else:
                cloud_details.status = FileCloudStatus.UP_TO_DATE
        else:
            cloud_details.status = FileCloudStatus.UP_TO_DATE
        return cloud_details

    if latest_match.last_status == "updating":
        cloud_details.status = FileCloudStatus.UPDATING
        return cloud_details

    return cloud_details
