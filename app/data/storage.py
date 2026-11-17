"""Local JSON and optional Cloud Storage archives, separated from collection."""

import hashlib
import json
from pathlib import Path
from typing import Any

from app.data.schema import MetricRecord


def serialize_records(records: list[MetricRecord]) -> str:
    """Return newline-delimited, standards-compliant JSON (never NaN)."""
    return "".join(
        json.dumps(record.model_dump(mode="json"), allow_nan=False, sort_keys=True) + "\n"
        for record in records
    )


def save_records(records: list[MetricRecord], path: Path) -> None:
    """Save an explicitly requested local snapshot, including an empty result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_records(records), encoding="utf-8")


def archive_records(
    records: list[MetricRecord], project: str, bucket: str, client: Any = None,
) -> str | None:
    """Archive to an existing bucket with create-only writes and content keys."""
    if not records:
        return None
    from google.api_core.exceptions import PreconditionFailed
    from google.cloud import storage

    payload = serialize_records(records)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    object_name = f"metrics/{records[0].timestamp:%Y/%m/%d}/{digest}.ndjson"
    client = client or storage.Client(project=project)
    blob = client.bucket(bucket).blob(object_name)
    try:
        blob.upload_from_string(
            payload, content_type="application/x-ndjson", if_generation_match=0,
        )
    except PreconditionFailed:
        # The immutable object name is derived from these exact contents.
        pass
    return f"gs://{bucket}/{object_name}"
