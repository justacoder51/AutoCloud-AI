"""Per-user isolated tenant project onboarding using keyless IAM delegation."""

from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator


PROJECT_PATTERN = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
REGION_PATTERN = re.compile(r"^[a-z]+-[a-z]+[0-9]+$")
SERVICE_PATTERN = re.compile(r"^(?:[a-z][a-z0-9-]{0,48}[a-z0-9]|[a-z])$")
DISPLAY_NAME_PATTERN = re.compile(r"^[A-Za-z0-9 _.-]{1,64}$")
EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)

FORBIDDEN_KEY_NAMES = frozenset({
    "private_key",
    "private_key_id",
    "service_account",
    "service_account_json",
    "service_account_key",
    "client_email",
    "credentials",
    "json_key",
    "key_file",
})


class ForbiddenCredentialInput(ValueError):
    """Raised when uploaded service-account private keys or key JSONs are supplied."""


class ProjectAccessDenied(PermissionError):
    """Raised when the signed-in user fails GCP project ownership verification."""


def contains_forbidden_key_material(payload: Any) -> bool:
    """Detect service-account JSON keys or PEM material anywhere in a request payload."""
    if isinstance(payload, dict):
        if payload.get("type") == "service_account":
            return True
        for k, v in payload.items():
            if str(k).strip().lower() in FORBIDDEN_KEY_NAMES:
                return True
            if contains_forbidden_key_material(v):
                return True
        return False
    if isinstance(payload, (list, tuple)):
        return any(contains_forbidden_key_material(item) for item in payload)
    if isinstance(payload, str):
        lowered = payload.lower()
        return (
            "begin private key" in lowered
            or '"private_key"' in lowered
            or '"type": "service_account"' in lowered
            or '"type":"service_account"' in lowered
        )
    return False


def validate_project_target(project_id: str, region: str, service: str | None = None) -> None:
    if not isinstance(project_id, str) or PROJECT_PATTERN.fullmatch(project_id) is None:
        raise ValueError("Invalid GCP project ID")
    if not isinstance(region, str) or REGION_PATTERN.fullmatch(region) is None:
        raise ValueError("Invalid GCP region")
    if service is not None and (not isinstance(service, str) or SERVICE_PATTERN.fullmatch(service) is None):
        raise ValueError("Invalid Cloud Run service name")


def keyless_iam_commands(project_id: str, reader_sa_email: str) -> list[str]:
    """Return explicit read-only gcloud IAM commands using keyless delegation."""
    validate_project_target(project_id, "asia-south1")
    return [
        (
            f"gcloud projects add-iam-policy-binding {project_id} "
            f"--member=serviceAccount:{reader_sa_email} "
            "--role=roles/monitoring.viewer"
        ),
        (
            f"gcloud projects add-iam-policy-binding {project_id} "
            f"--member=serviceAccount:{reader_sa_email} "
            "--role=roles/run.viewer"
        ),
    ]


class OnboardProjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    project_id: str = Field(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
    region: str = Field(default="asia-south1", pattern=r"^[a-z]+-[a-z]+[0-9]+$")
    display_name: str | None = Field(default=None, max_length=64)
    cloud_run_service: str | None = Field(default=None, pattern=r"^(?:[a-z][a-z0-9-]{0,48}[a-z0-9]|[a-z])$")

    @field_validator("display_name")
    @classmethod
    def check_display_name(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        if DISPLAY_NAME_PATTERN.fullmatch(v) is None:
            raise ValueError("Display name contains unsupported characters")
        return v


class OnboardedProject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    owner_sub: str
    owner_email: str
    project_id: str
    region: str
    display_name: str
    auth_method: Literal["keyless_iam_delegation", "oauth_session_probe"] = "keyless_iam_delegation"
    status: Literal["verified_active", "pending_iam_delegation", "revoked"]
    verified_permissions: tuple[str, ...] = ()
    sa_delegated_permissions: tuple[str, ...] = ()
    services: tuple[str, ...] = ()
    created_at: str
    updated_at: str
    verified_at: str | None = None


REQUIRED_USER_PERMISSIONS = ("monitoring.timeSeries.list", "run.services.list")


def gcp_test_iam_permissions(project_id: str, bearer_token: str, permissions: tuple[str, ...]) -> list[str]:
    """Query Resource Manager testIamPermissions using the supplied bearer token."""
    validate_project_target(project_id, "asia-south1")
    url = f"https://cloudresourcemanager.googleapis.com/v1/projects/{project_id}:testIamPermissions"
    with httpx.Client(timeout=15.0, trust_env=False) as client:
        resp = client.post(
            url,
            headers={"Authorization": f"Bearer {bearer_token}"},
            json={"permissions": list(permissions)},
        )
    if resp.status_code in {401, 403, 404}:
        return []
    if resp.status_code != 200:
        raise ValueError(f"Resource Manager check returned HTTP {resp.status_code}")
    granted = resp.json().get("permissions", [])
    return [str(p) for p in granted if p in permissions]


def gcp_discover_run_services(project_id: str, region: str, bearer_token: str) -> list[str]:
    """Discover Cloud Run v2 services in (project_id, region) using an authorized bearer token."""
    validate_project_target(project_id, region)
    url = f"https://run.googleapis.com/v2/projects/{project_id}/locations/{region}/services"
    with httpx.Client(timeout=15.0, trust_env=False) as client:
        resp = client.get(url, headers={"Authorization": f"Bearer {bearer_token}"})
    if resp.status_code != 200:
        return []
    services = []
    for item in resp.json().get("services", []):
        name = str(item.get("name", "")).rsplit("/", 1)[-1]
        if SERVICE_PATTERN.fullmatch(name):
            services.append(name)
    return sorted(set(services))


class LocalTenantStore:
    """SQLite-backed per-user isolated onboarding registry and replay-guarded nonces."""

    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute("""
                CREATE TABLE IF NOT EXISTS user_projects (
                    owner_sub TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (owner_sub, project_id)
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS oauth_nonces (
                    jti TEXT PRIMARY KEY,
                    expires_at INTEGER NOT NULL
                )
            """)
            with db:
                yield db
        finally:
            db.close()

    def consume_oauth_nonce(self, jti: str, expires_at: int) -> bool:
        now_ts = int(time.time())
        with self.connection() as db:
            db.execute("DELETE FROM oauth_nonces WHERE expires_at < ?", (now_ts,))
            cur = db.execute(
                "INSERT OR IGNORE INTO oauth_nonces (jti, expires_at) VALUES (?, ?)",
                (jti, expires_at),
            )
            return cur.rowcount == 1

    def upsert_project(self, record: OnboardedProject) -> OnboardedProject:
        with self.connection() as db:
            db.execute(
                """
                INSERT INTO user_projects (owner_sub, project_id, payload, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(owner_sub, project_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (record.owner_sub, record.project_id, record.model_dump_json(), record.updated_at),
            )
        return record

    def list_projects(self, owner_sub: str, *, include_revoked: bool = False) -> list[OnboardedProject]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT payload FROM user_projects WHERE owner_sub = ? ORDER BY updated_at DESC, project_id ASC",
                (owner_sub,),
            ).fetchall()
        projects = [OnboardedProject.model_validate_json(row["payload"]) for row in rows]
        if include_revoked:
            return projects
        return [p for p in projects if p.status != "revoked"]

    def get_project(self, owner_sub: str, project_id: str) -> OnboardedProject | None:
        with self.connection() as db:
            row = db.execute(
                "SELECT payload FROM user_projects WHERE owner_sub = ? AND project_id = ?",
                (owner_sub, project_id),
            ).fetchone()
        if row is None:
            return None
        record = OnboardedProject.model_validate_json(row["payload"])
        return None if record.status == "revoked" else record

    def revoke_project(self, owner_sub: str, project_id: str, now: datetime) -> bool:
        existing = self.get_project(owner_sub, project_id)
        if existing is None:
            return False
        updated = existing.model_copy(update={"status": "revoked", "updated_at": now.isoformat()})
        self.upsert_project(updated)
        return True


class CloudTenantStore:
    """Append-only immutable GCS tenant project events (if_generation_match=0, zero delete needed)."""

    BUDGET_SECONDS = 30.0
    GCS_TIMEOUT_SECONDS = 10
    EPOCH_US_CEILING = 9_999_999_999_999_999

    def __init__(self, project: str, region: str, bucket: str, client: Any = None, *, clock: Any = None):
        self.project = project
        self.region = region
        self.bucket_name = bucket
        if client is None:
            from google.cloud import storage

            client = storage.Client(project=project)
        self.client = client
        self.clock = clock or time.monotonic

    @staticmethod
    def _owner_hash(owner_sub: str) -> str:
        return sha256(owner_sub.encode("utf-8")).hexdigest()

    def _bucket(self):
        kwargs = {"timeout": self.GCS_TIMEOUT_SECONDS}
        try:
            bucket = self.client.get_bucket(self.bucket_name, **kwargs)
        except TypeError:
            bucket = self.client.get_bucket(self.bucket_name)
        if (getattr(bucket, "location", None) or "").lower() != self.region.lower():
            raise ValueError("Tenant bucket location must match configured region")
        return bucket

    def _event_path(self, owner_sub: str, project_id: str, ts: datetime) -> str:
        ts_us = int((ts.astimezone(timezone.utc) - EPOCH_UTC) // timedelta(microseconds=1))
        reverse_us = max(0, self.EPOCH_US_CEILING - ts_us)
        return f"tenants/{self._owner_hash(owner_sub)}/projects/{project_id}/events/{reverse_us:016d}_{uuid4().hex}.json"

    def consume_oauth_nonce(self, jti: str, expires_at: int) -> bool:
        from google.api_core.exceptions import PreconditionFailed

        if re.fullmatch(r"[A-Za-z0-9_-]{8,128}", jti) is None:
            return False
        bucket = self._bucket()
        blob = bucket.blob(f"oauth_nonces/{jti}.json")
        payload = json.dumps({"jti": jti, "expires_at": expires_at}, sort_keys=True)
        try:
            blob.upload_from_string(payload, content_type="application/json", if_generation_match=0)
            return True
        except PreconditionFailed:
            return False

    def upsert_project(self, record: OnboardedProject) -> OnboardedProject:
        bucket = self._bucket()
        ts = datetime.fromisoformat(record.updated_at)
        blob = bucket.blob(self._event_path(record.owner_sub, record.project_id, ts))
        blob.upload_from_string(
            record.model_dump_json(),
            content_type="application/json",
            if_generation_match=0,
        )
        return record

    def list_projects(self, owner_sub: str, *, include_revoked: bool = False) -> list[OnboardedProject]:
        deadline = float(self.clock()) + self.BUDGET_SECONDS
        bucket = self._bucket()
        prefix = f"tenants/{self._owner_hash(owner_sub)}/projects/"
        blobs = list(bucket.list_blobs(prefix=prefix))
        # Event blobs sort newest-first per project via reverse_us; read newest per project_id.
        newest_by_project: dict[str, tuple[str, Any]] = {}
        for blob in blobs:
            if float(self.clock()) > deadline:
                raise TimeoutError("Tenant listing budget exceeded")
            parts = blob.name.split("/")
            if len(parts) >= 6 and parts[2] == "projects" and parts[4] == "events" and parts[5].endswith(".json"):
                pid = parts[3]
                prev = newest_by_project.get(pid)
                if prev is None or parts[5] < prev[0]:
                    newest_by_project[pid] = (parts[5], blob)
        records: list[OnboardedProject] = []
        for _, blob in sorted(newest_by_project.values(), key=lambda pair: pair[0]):
            if float(self.clock()) > deadline:
                raise TimeoutError("Tenant listing budget exceeded")
            rec = OnboardedProject.model_validate_json(blob.download_as_text(encoding="utf-8"))
            if rec.owner_sub != owner_sub:
                continue
            if include_revoked or rec.status != "revoked":
                records.append(rec)
        records.sort(key=lambda r: (r.updated_at, r.project_id), reverse=True)
        return records

    def get_project(self, owner_sub: str, project_id: str) -> OnboardedProject | None:
        validate_project_target(project_id, self.region)
        bucket = self._bucket()
        prefix = f"tenants/{self._owner_hash(owner_sub)}/projects/{project_id}/events/"
        blobs = sorted((b for b in bucket.list_blobs(prefix=prefix) if b.name.endswith(".json")), key=lambda b: b.name)
        if not blobs:
            return None
        rec = OnboardedProject.model_validate_json(blobs[0].download_as_text(encoding="utf-8"))
        if rec.owner_sub != owner_sub or rec.project_id != project_id or rec.status == "revoked":
            return None
        return rec

    def revoke_project(self, owner_sub: str, project_id: str, now: datetime) -> bool:
        existing = self.get_project(owner_sub, project_id)
        if existing is None:
            return False
        updated = existing.model_copy(update={"status": "revoked", "updated_at": now.isoformat()})
        self.upsert_project(updated)
        return True
