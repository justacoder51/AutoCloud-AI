"""Read a checksummed evaluation summary packaged without model weights."""

import hashlib
import json
from pathlib import Path


def load_recorded_evaluation(path: str, expected_sha256: str, project: str, region: str, service: str):
    contents = Path(path).read_bytes()
    if len(contents) > 2_000_000 or hashlib.sha256(contents).hexdigest() != expected_sha256:
        raise ValueError("Recorded evaluation checksum mismatch")
    record = json.loads(contents)
    if (record["project"], record["region"], record["service"]) != (project, region, service):
        raise ValueError("Recorded evaluation scope mismatch")
    evaluation = record["evaluation"]
    if evaluation["deployment_allowed"] is not False:
        raise ValueError("Recorded evaluation cannot authorize deployment")
    return evaluation
