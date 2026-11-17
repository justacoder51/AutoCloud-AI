"""Narrow Cloud Run v2 adapter. Never changes revisions, IAM or traffic routing."""

import re


class CloudRunService:
    def __init__(self, project, region, service, session=None):
        if not all(re.fullmatch(r"[a-z][a-z0-9-]{0,62}", part) for part in (project, region, service)):
            raise ValueError("Invalid Cloud Run target")
        self.name = f"projects/{project}/locations/{region}/services/{service}"
        if session is None:
            import google.auth
            from google.auth.transport.requests import AuthorizedSession
            credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            session = AuthorizedSession(credentials)
        self.session = session

    def read(self):
        response = self.session.get(f"https://run.googleapis.com/v2/{self.name}", timeout=20)
        if response.status_code != 200:
            raise RuntimeError(f"Cloud Run read failed: HTTP {response.status_code}")
        data = response.json()
        if data.get("name") != self.name or not data.get("etag"):
            raise ValueError("Unexpected resource or missing concurrency token")
        return data

    def minimum(self, current, value, *, validate_only=True):
        if current.get("name") != self.name or not current.get("etag") or type(value) is not int or value not in (0, 1):
            raise ValueError("Only service minimum 0 or 1 is supported")
        response = self.session.patch(
            f"https://run.googleapis.com/v2/{self.name}", timeout=20,
            params={"updateMask": "scaling.minInstanceCount", "validateOnly": str(validate_only).lower()},
            json={"name": self.name, "etag": current["etag"], "scaling": {"minInstanceCount": value}},
        )
        if response.status_code != 200:
            raise RuntimeError(f"Cloud Run update failed or uncertain: HTTP {response.status_code}")
        operation = response.json()
        if operation.get("error"):
            raise RuntimeError("Cloud Run operation rejected")
        return operation
