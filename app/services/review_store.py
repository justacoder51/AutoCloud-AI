"""Durable local and Cloud Storage review records. Never authorizes execution."""

import inspect
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.agents.recommendation_agent import RecommendationPlan


EPOCH_UTC = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _supports_kwarg(func: Any, name: str) -> bool:
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return False
    return name in sig.parameters or any(
        param.kind == inspect.Parameter.VAR_KEYWORD for param in sig.parameters.values()
    )


class ReviewConflict(ValueError):
    """The evidence expired or a decision was already recorded."""


def _prepare_capture(
    plan: RecommendationPlan,
    now: datetime,
    *,
    owner_sub: str | None = None,
) -> tuple[str, datetime, list[tuple[str, dict]]]:
    """Validate freshness and build deterministic review identifiers and snapshots."""
    if plan.data_status != "fresh" or not plan.latest_observation:
        raise ReviewConflict("Fresh evidence is required to save recommendations.")
    expiry = plan.latest_observation + timedelta(seconds=900)
    if now > expiry:
        raise ReviewConflict("Evidence expired; refresh measurements.")
    scope = ReviewStore.scope(plan.project_id, plan.region, plan.service_name, owner_sub=owner_sub)
    entries = []
    for item in plan.recommendations:
        identity = scope + plan.evidence_fingerprint + item.model_dump_json()
        identifier = sha256(identity.encode()).hexdigest()
        snapshot = plan.model_dump(mode="json")
        snapshot["recommendations"] = [item.model_dump(mode="json")]
        entries.append((identifier, snapshot))
    return scope, expiry, entries


def _build_history_item(
    *,
    identifier: str,
    snapshot: dict,
    created_at: str,
    expires_at: str,
    decision: str | None,
    reviewer: str | None,
    note: str | None,
    decided_at: str | None,
    now: datetime,
    authenticated_principal: str | None = None,
    include_principal: bool = False,
) -> dict:
    item = {
        "id": identifier,
        "snapshot": snapshot,
        "created_at": created_at,
        "expires_at": expires_at,
        "decision": decision,
        "reviewer": reviewer,
        "note": note,
        "decided_at": decided_at,
        "status": decision or "pending_review",
        "evidence_expired": now > datetime.fromisoformat(expires_at),
        "execution_allowed": False,
    }
    if include_principal:
        item["calling_service_principal"] = authenticated_principal
        item["authenticated_principal"] = authenticated_principal
        item["reviewer_label"] = reviewer
        item["human_reviewer_verified"] = False
    return item


class ReviewStore:
    def __init__(self, path: Path):
        self.path = path

    @contextmanager
    def connection(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        try:
            db.row_factory = sqlite3.Row
            db.execute('''CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, snapshot TEXT NOT NULL,
                created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                decision TEXT, reviewer TEXT, note TEXT, decided_at TEXT)''')
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def scope(project, region, service, *, owner_sub: str | None = None):
        if owner_sub:
            return json.dumps({"owner": owner_sub, "project": project, "region": region, "service": service}, sort_keys=True)
        return json.dumps([project, region, service])

    def capture(self, plan: RecommendationPlan, now: datetime, *, owner_sub: str | None = None):
        scope, expiry, entries = _prepare_capture(plan, now, owner_sub=owner_sub)
        ids = []
        with self.connection() as db:
            for identifier, snapshot in entries:
                db.execute("INSERT OR IGNORE INTO reviews (id,scope,snapshot,created_at,expires_at) VALUES (?,?,?,?,?)",
                           (identifier, scope, json.dumps(snapshot), now.isoformat(), expiry.isoformat()))
                ids.append(identifier)
        return ids

    def history(self, scope: str, now: datetime):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM reviews WHERE scope=? ORDER BY created_at DESC,id LIMIT 200", (scope,)).fetchall()
        return [
            _build_history_item(
                identifier=row["id"],
                snapshot=json.loads(row["snapshot"]),
                created_at=row["created_at"],
                expires_at=row["expires_at"],
                decision=row["decision"],
                reviewer=row["reviewer"],
                note=row["note"],
                decided_at=row["decided_at"],
                now=now,
            )
            for row in rows
        ]

    def decide(self, scope, identifier, decision, reviewer, note, now):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM reviews WHERE id=? AND scope=?", (identifier, scope)).fetchone()
            if row is None:
                raise KeyError(identifier)
            if row["decision"]:
                if (row["decision"], row["reviewer"], row["note"]) == (decision, reviewer, note):
                    return  # Safe retry of the same submission.
                raise ReviewConflict("A final review decision already exists.")
            if decision == "approved" and now > datetime.fromisoformat(row["expires_at"]):
                raise ReviewConflict("Evidence expired; refresh and save a new recommendation.")
            db.execute("UPDATE reviews SET decision=?,reviewer=?,note=?,decided_at=? WHERE id=?",
                       (decision, reviewer, note, now.isoformat(), identifier))


class CloudReviewStore:
    """Durable, immutable review snapshots and decisions backed by Cloud Storage."""

    PAGE_LIMIT = 200
    LIST_PAGE_SIZE = 1000
    GCS_TIMEOUT_SECONDS = 10
    HISTORY_BUDGET_SECONDS = 30.0
    EPOCH_US_CEILING = 9_999_999_999_999_999
    _INDEX_FILENAME_RE = re.compile(r"^(\d+)_([a-f0-9]{64})\.json$")
    _ITEM_FILENAME_RE = re.compile(r"^([a-f0-9]{64})\.json$")

    def __init__(self, project: str, region: str, bucket: str, client: Any = None, *, clock: Any = None):
        if re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project) is None:
            raise ValueError("Invalid project identifier")
        if re.fullmatch(r"[a-z][a-z0-9-]{0,62}", region) is None:
            raise ValueError("Invalid region identifier")
        if (re.fullmatch(r"[a-z0-9][a-z0-9._-]{1,61}[a-z0-9]", bucket) is None
                or bucket.startswith("goog") or "google" in bucket):
            raise ValueError("Invalid Cloud Storage review bucket")
        if client is None:
            from google.cloud import storage

            client = storage.Client(project=project)
        self.project = project
        self.region = region
        self.bucket_name = bucket
        self.client = client
        self.clock = clock or time.monotonic

    def _remaining_budget(self, deadline: float) -> float:
        remaining = deadline - float(self.clock())
        if remaining <= 0:
            raise TimeoutError("Review history 30s storage budget exceeded")
        return remaining

    def _check_budget_after(self, deadline: float) -> None:
        if float(self.clock()) > deadline:
            raise TimeoutError("Review history 30s storage budget exceeded")

    @staticmethod
    def _bounded_retry(remaining: float) -> Any:
        try:
            from google.cloud.storage.retry import DEFAULT_RETRY
        except ImportError:  # pragma: no cover - minimal test environments without GCS SDK
            return None
        bounded = DEFAULT_RETRY.with_deadline(remaining)
        initial = getattr(bounded, "_initial", None)
        maximum = getattr(bounded, "_maximum", None)
        new_initial = min(initial, remaining) if initial is not None else None
        new_maximum = min(maximum, remaining) if maximum is not None else None
        if new_initial != initial or new_maximum != maximum:
            bounded = bounded.with_delay(initial=new_initial, maximum=new_maximum)
        return bounded

    def _storage_call_kwargs(self, func: Any, *, deadline: float | None = None) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if deadline is None:
            if _supports_kwarg(func, "timeout"):
                kwargs["timeout"] = self.GCS_TIMEOUT_SECONDS
            return kwargs
        remaining = self._remaining_budget(deadline)
        if _supports_kwarg(func, "timeout"):
            kwargs["timeout"] = min(float(self.GCS_TIMEOUT_SECONDS), remaining)
        if _supports_kwarg(func, "retry"):
            bounded_retry = self._bounded_retry(remaining)
            if bounded_retry is not None:
                kwargs["retry"] = bounded_retry
        return kwargs

    def _bucket(self, *, deadline: float | None = None):
        kwargs = self._storage_call_kwargs(self.client.get_bucket, deadline=deadline)
        bucket = self.client.get_bucket(self.bucket_name, **kwargs)
        if deadline is not None:
            self._check_budget_after(deadline)
        if (getattr(bucket, "location", None) or "").lower() != self.region.lower():
            raise ValueError("Review bucket location must match the configured region")
        return bucket

    def _upload_json(self, blob: Any, payload: dict) -> None:
        kwargs: dict[str, Any] = {
            "content_type": "application/json",
            "if_generation_match": 0,
        }
        if _supports_kwarg(blob.upload_from_string, "timeout"):
            kwargs["timeout"] = self.GCS_TIMEOUT_SECONDS
        blob.upload_from_string(
            json.dumps(payload, allow_nan=False, sort_keys=True),
            **kwargs,
        )

    def _download_json(self, blob: Any, *, deadline: float | None = None) -> dict:
        kwargs: dict[str, Any] = {"encoding": "utf-8"}
        kwargs.update(self._storage_call_kwargs(blob.download_as_text, deadline=deadline))
        data = json.loads(blob.download_as_text(**kwargs))
        if deadline is not None:
            self._check_budget_after(deadline)
        return data

    def _list_all_blobs(self, bucket: Any, prefix: str, *, deadline: float) -> list[Any]:
        blobs: list[Any] = []
        page_token: str | None = None
        supports_page_token = _supports_kwarg(bucket.list_blobs, "page_token")
        while True:
            kwargs: dict[str, Any] = {"prefix": prefix}
            if _supports_kwarg(bucket.list_blobs, "page_size"):
                kwargs["page_size"] = self.LIST_PAGE_SIZE
            if _supports_kwarg(bucket.list_blobs, "fields"):
                kwargs["fields"] = "items(name),nextPageToken"
            if page_token is not None and supports_page_token:
                kwargs["page_token"] = page_token
            kwargs.update(self._storage_call_kwargs(bucket.list_blobs, deadline=deadline))
            iterator = bucket.list_blobs(**kwargs)
            pages_iter = getattr(iterator, "pages", None)
            if pages_iter is not None and supports_page_token:
                page = next(iter(pages_iter), None)
                if page is not None:
                    blobs.extend(page)
                self._check_budget_after(deadline)
                next_token = getattr(iterator, "next_page_token", None)
                if not next_token:
                    break
                page_token = next_token
            elif pages_iter is not None:
                for page in pages_iter:
                    blobs.extend(page)
                    self._check_budget_after(deadline)
                break
            else:
                for blob in iterator:
                    self._check_budget_after(deadline)
                    blobs.append(blob)
                self._check_budget_after(deadline)
                break
        return blobs

    @staticmethod
    def _scope_hash(scope: str) -> str:
        return sha256(scope.encode()).hexdigest()

    @staticmethod
    def _validate_identifier(identifier: str) -> None:
        if not isinstance(identifier, str) or re.fullmatch(r"[a-f0-9]{64}", identifier) is None:
            raise KeyError(identifier)

    def _item_path(self, scope_hash: str, identifier: str) -> str:
        return f"reviews/{scope_hash}/items/{identifier}.json"

    def _index_path(self, scope_hash: str, created_at: datetime, identifier: str) -> str:
        ts_us = int((created_at.astimezone(timezone.utc) - EPOCH_UTC) // timedelta(microseconds=1))
        reverse_us = max(0, self.EPOCH_US_CEILING - ts_us)
        return f"reviews/{scope_hash}/by_time/{reverse_us:016d}_{identifier}.json"

    def _decision_path(self, scope_hash: str, identifier: str) -> str:
        return f"reviews/{scope_hash}/decisions/{identifier}.json"

    def _check_existing_decision(
        self,
        decision_blob,
        *,
        decision: str,
        reviewer: str,
        note: str,
        authenticated_principal: str | None,
    ) -> bool:
        from google.api_core.exceptions import NotFound

        try:
            existing = self._download_json(decision_blob)
        except NotFound:
            return False
        existing_principal = existing.get("calling_service_principal") or existing.get("authenticated_principal")
        if (
            existing.get("decision"),
            existing.get("reviewer"),
            existing.get("note"),
            existing_principal,
        ) == (decision, reviewer, note, authenticated_principal):
            return True
        raise ReviewConflict("A final review decision already exists.")

    def capture(
        self,
        plan: RecommendationPlan,
        now: datetime,
        *,
        authenticated_principal: str | None = None,
        owner_sub: str | None = None,
    ) -> list[str]:
        from google.api_core.exceptions import PreconditionFailed

        scope, expiry, entries = _prepare_capture(plan, now, owner_sub=owner_sub)
        bucket = self._bucket()
        scope_hash = self._scope_hash(scope)
        ids = []
        for identifier, snapshot in entries:
            payload = {
                "id": identifier,
                "scope": scope,
                "snapshot": snapshot,
                "created_at": now.isoformat(),
                "expires_at": expiry.isoformat(),
                "captured_by": authenticated_principal,
            }
            item_blob = bucket.blob(self._item_path(scope_hash, identifier))
            index_now = now
            index_payload = payload
            try:
                self._upload_json(item_blob, payload)
            except PreconditionFailed:
                existing = self._download_json(item_blob)
                if existing.get("scope") != scope or existing.get("id") != identifier:
                    raise ReviewConflict("Existing review record scope mismatch.") from None
                index_payload = existing
                index_now = datetime.fromisoformat(existing["created_at"])
            try:
                self._upload_json(
                    bucket.blob(self._index_path(scope_hash, index_now, identifier)),
                    index_payload,
                )
            except PreconditionFailed:
                pass
            ids.append(identifier)
        return ids

    def history(self, scope: str, now: datetime) -> list[dict]:
        from google.api_core.exceptions import NotFound

        deadline = float(self.clock()) + self.HISTORY_BUDGET_SECONDS
        bucket = self._bucket(deadline=deadline)
        scope_hash = self._scope_hash(scope)

        # List both by_time/ (reverse-timestamp sorted) and legacy items/ refs so
        # no recent legacy unindexed record is ever masked, while indexed records
        # only trigger JSON downloads for the newest PAGE_LIMIT index entries.
        indexed_entries: list[tuple[tuple[int, str], str, Any]] = []
        indexed_ids: set[str] = set()
        for blob in self._list_all_blobs(
            bucket,
            f"reviews/{scope_hash}/by_time/",
            deadline=deadline,
        ):
            filename = blob.name.rsplit("/", 1)[-1]
            match = self._INDEX_FILENAME_RE.fullmatch(filename)
            if not match:
                continue
            reverse_us = int(match.group(1))
            item_id = match.group(2)
            if item_id in indexed_ids:
                continue
            indexed_ids.add(item_id)
            indexed_entries.append(((reverse_us, item_id), item_id, blob))

        indexed_entries.sort(key=lambda entry: entry[0])
        top_indexed_blobs = [blob for _, _, blob in indexed_entries[: self.PAGE_LIMIT]]

        unindexed_blobs: list[Any] = []
        for blob in self._list_all_blobs(
            bucket,
            f"reviews/{scope_hash}/items/",
            deadline=deadline,
        ):
            filename = blob.name.rsplit("/", 1)[-1]
            match = self._ITEM_FILENAME_RE.fullmatch(filename)
            if not match:
                continue
            item_id = match.group(1)
            if item_id in indexed_ids:
                continue
            unindexed_blobs.append(blob)

        items: list[dict] = []
        seen_ids: set[str] = set()
        for blob in [*top_indexed_blobs, *unindexed_blobs]:
            raw = self._download_json(blob, deadline=deadline)
            item_id = raw.get("id")
            if raw.get("scope") == scope and item_id and item_id not in seen_ids:
                seen_ids.add(item_id)
                items.append(raw)

        items.sort(key=lambda item: item["id"])
        items.sort(key=lambda item: datetime.fromisoformat(item["created_at"]), reverse=True)

        result = []
        for raw in items[: self.PAGE_LIMIT]:
            dec = None
            try:
                candidate = self._download_json(
                    bucket.blob(self._decision_path(scope_hash, raw["id"])),
                    deadline=deadline,
                )
                if candidate.get("scope") == scope and candidate.get("id") == raw["id"]:
                    dec = candidate
            except NotFound:
                self._check_budget_after(deadline)
                dec = None
            principal = (
                (dec.get("calling_service_principal") or dec.get("authenticated_principal"))
                if dec else None
            )
            result.append(
                _build_history_item(
                    identifier=raw["id"],
                    snapshot=raw["snapshot"],
                    created_at=raw["created_at"],
                    expires_at=raw["expires_at"],
                    decision=dec.get("decision") if dec else None,
                    reviewer=dec.get("reviewer") if dec else None,
                    note=dec.get("note") if dec else None,
                    decided_at=dec.get("decided_at") if dec else None,
                    now=now,
                    authenticated_principal=principal,
                    include_principal=True,
                )
            )
        return result

    def decide(
        self,
        scope: str,
        identifier: str,
        decision: str,
        reviewer: str,
        note: str,
        now: datetime,
        *,
        authenticated_principal: str | None = None,
    ) -> None:
        from google.api_core.exceptions import NotFound, PreconditionFailed

        self._validate_identifier(identifier)
        bucket = self._bucket()
        scope_hash = self._scope_hash(scope)
        item_blob = bucket.blob(self._item_path(scope_hash, identifier))
        try:
            item_data = self._download_json(item_blob)
        except NotFound:
            raise KeyError(identifier) from None
        if item_data.get("scope") != scope or item_data.get("id") != identifier:
            raise KeyError(identifier)
        decision_blob = bucket.blob(self._decision_path(scope_hash, identifier))
        if self._check_existing_decision(
            decision_blob,
            decision=decision,
            reviewer=reviewer,
            note=note,
            authenticated_principal=authenticated_principal,
        ):
            return
        if decision == "approved" and now > datetime.fromisoformat(item_data["expires_at"]):
            raise ReviewConflict("Evidence expired; refresh and save a new recommendation.")
        payload = {
            "id": identifier,
            "scope": scope,
            "decision": decision,
            "reviewer": reviewer,
            "reviewer_label": reviewer,
            "calling_service_principal": authenticated_principal,
            "authenticated_principal": authenticated_principal,
            "human_reviewer_verified": False,
            "note": note,
            "decided_at": now.isoformat(),
        }
        try:
            self._upload_json(decision_blob, payload)
        except PreconditionFailed:
            if self._check_existing_decision(
                decision_blob,
                decision=decision,
                reviewer=reviewer,
                note=note,
                authenticated_principal=authenticated_principal,
            ):
                return
            raise ReviewConflict("A final review decision already exists.") from None
