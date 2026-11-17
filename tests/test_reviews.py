"""Review persistence and policy tests using synthetic fixtures, never cloud changes."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Lock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from google.api_core.exceptions import NotFound, PreconditionFailed
from pydantic import ValidationError
from starlette.requests import Request

from app.agents.recommendation_agent import build_plan
from app.config import Settings
from app.data.schema import MetricRecord
from app.data.storage import save_records
from app.main import create_app
from app.services.review_store import CloudReviewStore, ReviewConflict, ReviewStore


def evidence():
    now = datetime.now(timezone.utc)
    minute = now.replace(second=0, microsecond=0)
    rows = [MetricRecord(timestamp=minute-timedelta(minutes=i), collected_at=now,
                         project_id="test-project", region="asia-south1",
                         service_name="autocloud-api", cpu_utilization=.99) for i in (2, 1, 0)]
    plan = build_plan(rows, project="test-project", region="asia-south1", service="autocloud-api", now=now)
    return now, rows, plan


def test_persistence_deduplication_and_immutable_decisions(tmp_path):
    now, _, plan = evidence()
    store = ReviewStore(tmp_path / "reviews.db")
    scope = store.scope("test-project", "asia-south1", "autocloud-api")
    ids = store.capture(plan, now)
    assert store.capture(plan, now) == ids
    store.decide(scope, ids[0], "approved", "local reviewer", "Investigate CPU", now)
    store.decide(scope, ids[0], "approved", "local reviewer", "Investigate CPU", now)
    with pytest.raises(ReviewConflict):
        store.decide(scope, ids[0], "rejected", "local reviewer", "Changed mind", now)
    saved = ReviewStore(store.path).history(scope, now)
    assert len(saved) == 1 and saved[0]["status"] == "approved"
    assert saved[0]["snapshot"]["recommendations"][0]["evidence"]["values"] == [.99]*3
    assert saved[0]["execution_allowed"] is False
    assert store.history("another scope", now) == []


def test_expired_approval_blocked_but_rejection_allowed(tmp_path):
    now, _, plan = evidence()
    store = ReviewStore(tmp_path / "reviews.db")
    scope = store.scope("test-project", "asia-south1", "autocloud-api")
    identifier = store.capture(plan, now)[0]
    later = now + timedelta(minutes=16)
    with pytest.raises(ReviewConflict):
        store.capture(plan, later)
    with pytest.raises(ReviewConflict):
        store.decide(scope, identifier, "approved", "reviewer", "reason", later)
    store.decide(scope, identifier, "rejected", "reviewer", "Expired evidence", later)
    assert store.history(scope, later)[0]["evidence_expired"]


def test_concurrent_decisions_cannot_overwrite(tmp_path):
    now, _, plan = evidence()
    store = ReviewStore(tmp_path / "reviews.db")
    scope = store.scope("test-project", "asia-south1", "autocloud-api")
    identifier = store.capture(plan, now)[0]
    def decide(choice):
        try:
            store.decide(scope, identifier, choice, "reviewer", "reason", now)
            return "saved"
        except ReviewConflict:
            return "conflict"
    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(decide, ["approved", "rejected"])) == ["conflict", "saved"]


def test_api_revalidates_evidence_and_rejects_client_invented_content(tmp_path):
    _, rows, plan = evidence()
    save_records(rows, tmp_path / "processed/metrics.ndjson")
    app = create_app(Settings(environment="test", gcp_project_id="test-project"))
    app.state.analytics_data_root = tmp_path
    body = {"source": "local", "hours": 24, "evidence_fingerprint": plan.evidence_fingerprint}
    with TestClient(app) as client:
        assert client.post('/api/reviews/capture', json={**body, "evidence_fingerprint": "0"*64}).status_code == 409
        assert client.post('/api/reviews/capture', json={**body, "recommendations": []}).status_code == 422
        identifier = client.post('/api/reviews/capture', json=body).json()["saved_ids"][0]
        decision = {"decision": "approved", "reviewer": "Me", "note": "Review CPU evidence"}
        assert client.post(f'/api/reviews/{identifier}/decision', json={**decision, "reviewer": " "}).status_code == 422
        assert client.post('/api/reviews/missing/decision', json=decision).status_code == 404
        assert client.post(f'/api/reviews/{identifier}/decision', json=decision).json()["execution_allowed"] is False
        assert client.get('/api/reviews').json()["items"][0]["status"] == "approved"
        assert client.get('/api/reviews', headers={"origin": "https://example.com"}).status_code == 403
        save_records([row.model_copy(update={"cpu_utilization": .1}) for row in rows], tmp_path / "processed/metrics.ndjson")
        assert client.post('/api/reviews/capture', json=body).status_code == 409
    prod = create_app(Settings(environment="production", gcp_project_id="test-project"))
    with TestClient(prod) as client:
        assert client.get('/api/reviews').status_code == 403
    with TestClient(app, client=("192.0.2.10", 1234)) as client:
        assert client.get('/api/reviews').status_code == 403


def test_no_breach_does_not_invent_review(tmp_path):
    now, rows, _ = evidence()
    plan = build_plan([r.model_copy(update={"cpu_utilization": .1}) for r in rows],
                      project="test-project", region="asia-south1", service="autocloud-api", now=now)
    assert ReviewStore(tmp_path / 'reviews.db').capture(plan, now) == []


def test_dashboard_saves_reviews_only_after_explicit_actions(tmp_path, monkeypatch):
    import httpx
    from streamlit.testing.v1 import AppTest
    from unittest.mock import Mock

    now, _, plan = evidence()
    store = ReviewStore(tmp_path / 'ui.db')
    scope = store.scope('test-project', 'asia-south1', 'autocloud-api')
    calls = []
    def request(method, url, json=None):
        calls.append((method, url))
        if url.endswith('/capture'):
            payload = {'saved_ids': store.capture(plan, now)}
        elif url.endswith('/decision'):
            identifier = url.split('/')[-2]
            store.decide(scope, identifier, json['decision'], json['reviewer'], json['note'], now)
            payload = {'status': json['decision'], 'execution_allowed': False}
        else:
            payload = {'items': store.history(scope, now)}
        return Mock(status_code=200, json=Mock(return_value=payload))
    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.request.side_effect = request
    monkeypatch.setattr(httpx, 'Client', Mock(return_value=client))
    code = ('import json\nfrom app.dashboard.reviews import render_reviews\n'
            f'render_reviews("http://localhost:8080", json.loads({plan.model_dump_json()!r}), "Local snapshot", 24)')
    script = tmp_path / 'review_app.py'
    script.write_text(code, encoding='utf-8')
    app = AppTest.from_file(str(script)).run()
    assert not app.exception and calls == []
    app.button[0].click().run()
    assert not app.exception and len(store.history(scope, now)) == 1
    app.text_input[0].set_value('Reviewer')
    app.text_area[0].set_value('Investigate measured CPU pressure')
    app.checkbox[0].check()
    next(b for b in app.button if b.label == 'Record decision').click().run()
    assert not app.exception
    assert store.history(scope, now)[0]['status'] == 'approved'
    assert any('Decision: approved' in m.value for m in app.markdown)


class _FakeBlob:
    def __init__(self, bucket, name):
        self._bucket = bucket
        self.name = name

    def upload_from_string(
        self, data, content_type="application/json", if_generation_match=None, timeout=None,
    ):
        with self._bucket.lock:
            if if_generation_match == 0 and self.name in self._bucket.objects:
                raise PreconditionFailed("Object already exists")
            self._bucket.objects[self.name] = data

    def download_as_text(self, encoding="utf-8", timeout=None, retry=None):
        with self._bucket.lock:
            self._bucket.download_count += 1
            handler = self._bucket.on_download
        if handler is not None:
            return handler(self.name, timeout=timeout, retry=retry)
        with self._bucket.lock:
            if self.name not in self._bucket.objects:
                raise NotFound("Object not found")
            return self._bucket.objects[self.name]


class _FakeBucket:
    def __init__(self, name="autocloud-reviews", location="ASIA-SOUTH1"):
        self.name = name
        self.location = location
        self.lock = Lock()
        self.objects = {}
        self.download_count = 0
        self.list_calls = []
        self.on_download = None
        self.on_list = None
        self.on_get = None

    def blob(self, name):
        return _FakeBlob(self, name)

    def list_blobs(
        self,
        prefix="",
        max_results=None,
        page_size=None,
        timeout=None,
        retry=None,
        fields=None,
        page_token=None,
    ):
        self.list_calls.append((prefix, max_results, page_size, timeout, retry, fields, page_token))
        if self.on_list is not None:
            return self.on_list(
                prefix=prefix,
                max_results=max_results,
                page_size=page_size,
                timeout=timeout,
                retry=retry,
                fields=fields,
                page_token=page_token,
            )
        with self.lock:
            names = [name for name in sorted(self.objects) if name.startswith(prefix)]
        if max_results is not None:
            names = names[:max_results]
        return [_FakeBlob(self, name) for name in names]


class _FakeStorageClient:
    def __init__(self, bucket):
        self.bucket = bucket

    def get_bucket(self, name, timeout=None, retry=None):
        if name != self.bucket.name:
            raise NotFound(name)
        if self.bucket.on_get is not None:
            return self.bucket.on_get(name, timeout=timeout, retry=retry)
        return self.bucket


def _asgi_request(app, path="/api/reviews", method="GET", headers=None, client=("198.51.100.10", 443)):
    raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in (headers or {}).items()]
    return Request({
        "type": "http",
        "method": method,
        "path": path,
        "headers": raw_headers,
        "client": client,
        "app": app,
    })


def test_cloud_review_store_deduplication_immutability_and_expiry():
    now, _, plan = evidence()
    bucket = _FakeBucket()
    client = _FakeStorageClient(bucket)
    store = CloudReviewStore("test-project", "asia-south1", "autocloud-reviews", client=client)
    scope = ReviewStore.scope("test-project", "asia-south1", "autocloud-api")
    principal = "autocloud-dashboard@test-project.iam.gserviceaccount.com"

    ids = store.capture(plan, now, authenticated_principal=principal)
    assert len(ids) == 1
    assert store.capture(plan, now + timedelta(seconds=5), authenticated_principal=principal) == ids
    items = store.history(scope, now)
    assert len(items) == 1
    assert items[0]["created_at"] == now.isoformat()
    assert items[0]["status"] == "pending_review"
    assert items[0]["authenticated_principal"] is None
    assert items[0]["execution_allowed"] is False

    store.decide(
        scope, ids[0], "approved", "Operator", "Investigate CPU", now,
        authenticated_principal=principal,
    )
    # Safe retry with matching fields and principal succeeds.
    store.decide(
        scope, ids[0], "approved", "Operator", "Investigate CPU", now,
        authenticated_principal=principal,
    )
    # Conflicting decision or principal raises ReviewConflict.
    with pytest.raises(ReviewConflict):
        store.decide(
            scope, ids[0], "rejected", "Operator", "Changed mind", now,
            authenticated_principal=principal,
        )
    with pytest.raises(ReviewConflict):
        store.decide(
            scope, ids[0], "approved", "Operator", "Investigate CPU", now,
            authenticated_principal="other@test-project.iam.gserviceaccount.com",
        )

    saved = store.history(scope, now)
    assert saved[0]["status"] == "approved"
    assert saved[0]["calling_service_principal"] == principal
    assert saved[0]["authenticated_principal"] == principal
    assert saved[0]["human_reviewer_verified"] is False
    assert saved[0]["execution_allowed"] is False
    assert store.history(ReviewStore.scope("other-project", "asia-south1", "autocloud-api"), now) == []

    # Wrong region bucket is rejected.
    wrong_region = CloudReviewStore(
        "test-project", "asia-south1", "autocloud-reviews",
        client=_FakeStorageClient(_FakeBucket(location="US")),
    )
    with pytest.raises(ValueError):
        wrong_region.history(scope, now)

    # Expired approval blocked vs expired rejection allowed.
    later_now = now + timedelta(minutes=20)
    plan2 = build_plan(
        [
            MetricRecord(
                timestamp=(later_now.replace(second=0, microsecond=0) - timedelta(minutes=i)),
                collected_at=later_now,
                project_id="test-project",
                region="asia-south1",
                service_name="autocloud-api",
                memory_utilization=0.98,
            )
            for i in (2, 1, 0)
        ],
        project="test-project",
        region="asia-south1",
        service="autocloud-api",
        now=later_now,
    )
    ids2 = store.capture(plan2, later_now, authenticated_principal=principal)
    expired = later_now + timedelta(minutes=16)
    with pytest.raises(ReviewConflict):
        store.capture(plan2, expired, authenticated_principal=principal)
    with pytest.raises(ReviewConflict):
        store.decide(
            scope, ids2[0], "approved", "Operator", "Too late", expired,
            authenticated_principal=principal,
        )
    store.decide(
        scope, ids2[0], "rejected", "Operator", "Expired evidence", expired,
        authenticated_principal=principal,
    )
    items2 = store.history(scope, expired)
    by_id = {entry["id"]: entry for entry in items2}
    assert by_id[ids2[0]]["evidence_expired"] is True
    assert by_id[ids2[0]]["status"] == "rejected"


def test_cloud_review_store_concurrent_decisions_cannot_overwrite():
    now, _, plan = evidence()
    store = CloudReviewStore(
        "test-project", "asia-south1", "autocloud-reviews",
        client=_FakeStorageClient(_FakeBucket()),
    )
    scope = ReviewStore.scope("test-project", "asia-south1", "autocloud-api")
    principal = "autocloud-dashboard@test-project.iam.gserviceaccount.com"
    identifier = store.capture(plan, now, authenticated_principal=principal)[0]

    def decide(choice):
        try:
            store.decide(
                scope, identifier, choice, "Operator", "reason", now,
                authenticated_principal=principal,
            )
            return "saved"
        except ReviewConflict:
            return "conflict"

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(decide, ["approved", "rejected"])) == ["conflict", "saved"]


def test_cloud_review_store_history_bounds_reads():
    base_now = datetime.now(timezone.utc)
    minute = base_now.replace(second=0, microsecond=0)
    bucket = _FakeBucket()
    store = CloudReviewStore("test-project", "asia-south1", "autocloud-reviews", client=_FakeStorageClient(bucket))
    scope = ReviewStore.scope("test-project", "asia-south1", "autocloud-api")
    principal = "autocloud-dashboard@test-project.iam.gserviceaccount.com"

    for i in range(260):
        obs_now = base_now + timedelta(milliseconds=i)
        rows = [
            MetricRecord(
                timestamp=minute - timedelta(minutes=offset),
                collected_at=obs_now,
                project_id="test-project",
                region="asia-south1",
                service_name="autocloud-api",
                cpu_utilization=0.99,
                request_count=i + 1,
            )
            for offset in (2, 1, 0)
        ]
        plan = build_plan(rows, project="test-project", region="asia-south1", service="autocloud-api", now=obs_now)
        ids = store.capture(plan, obs_now, authenticated_principal=principal)
        store.decide(scope, ids[0], "approved", "Operator", f"Decision {i}", obs_now, authenticated_principal=principal)

    bucket.download_count = 0
    bucket.list_calls = []
    history_items = store.history(scope, base_now + timedelta(seconds=5))
    assert len(history_items) == 200
    assert history_items[0]["created_at"] == (base_now + timedelta(milliseconds=259)).isoformat()
    assert history_items[-1]["created_at"] == (base_now + timedelta(milliseconds=60)).isoformat()
    assert history_items[0]["calling_service_principal"] == principal
    assert history_items[0]["human_reviewer_verified"] is False
    # 200 indexed item downloads + 200 per-id decision downloads; never downloads older 60 indexed objects or scans decisions/.
    assert bucket.download_count == 400
    assert [call[0].rsplit("/", 2)[-2] for call in bucket.list_calls] == ["by_time", "items"]
    assert all(call[2] == CloudReviewStore.LIST_PAGE_SIZE for call in bucket.list_calls)
    assert all(call[5] == "items(name),nextPageToken" for call in bucket.list_calls)


def test_cloud_review_store_history_newest_200_over_200_legacy_records():
    base_now = datetime.now(timezone.utc)
    minute = base_now.replace(second=0, microsecond=0)
    bucket = _FakeBucket()
    store = CloudReviewStore("test-project", "asia-south1", "autocloud-reviews", client=_FakeStorageClient(bucket))
    scope = ReviewStore.scope("test-project", "asia-south1", "autocloud-api")
    principal = "autocloud-dashboard@test-project.iam.gserviceaccount.com"

    # Insert 245 legacy-only records out of timestamp order (non-indexed items/ only).
    shuffled_offsets = list(range(245))
    shuffled_offsets.reverse()
    shuffled_offsets = shuffled_offsets[1::2] + shuffled_offsets[0::2]
    for i in shuffled_offsets:
        obs_now = base_now + timedelta(milliseconds=i)
        rows = [
            MetricRecord(
                timestamp=minute - timedelta(minutes=offset),
                collected_at=obs_now,
                project_id="test-project",
                region="asia-south1",
                service_name="autocloud-api",
                cpu_utilization=0.99,
                request_count=i + 1,
            )
            for offset in (2, 1, 0)
        ]
        plan = build_plan(rows, project="test-project", region="asia-south1", service="autocloud-api", now=obs_now)
        store.capture(plan, obs_now, authenticated_principal=principal)

    # Also capture two distinct legacy records tied on the exact newest timestamp.
    tie_now = base_now + timedelta(milliseconds=300)
    tie_cpu = build_plan(
        [
            MetricRecord(
                timestamp=minute - timedelta(minutes=offset),
                collected_at=tie_now,
                project_id="test-project",
                region="asia-south1",
                service_name="autocloud-api",
                cpu_utilization=0.99,
            )
            for offset in (2, 1, 0)
        ],
        project="test-project",
        region="asia-south1",
        service="autocloud-api",
        now=tie_now,
    )
    tie_mem = build_plan(
        [
            MetricRecord(
                timestamp=minute - timedelta(minutes=offset),
                collected_at=tie_now,
                project_id="test-project",
                region="asia-south1",
                service_name="autocloud-api",
                memory_utilization=0.98,
            )
            for offset in (2, 1, 0)
        ],
        project="test-project",
        region="asia-south1",
        service="autocloud-api",
        now=tie_now,
    )
    tie_ids = store.capture(tie_cpu, tie_now, authenticated_principal=principal) + store.capture(
        tie_mem, tie_now, authenticated_principal=principal,
    )

    # Remove all by_time/ index objects to simulate a bucket with 247 legacy records.
    for key in [k for k in bucket.objects if "/by_time/" in k]:
        del bucket.objects[key]
    assert sum(1 for k in bucket.objects if "/items/" in k) == 247

    items = store.history(scope, base_now + timedelta(seconds=5))
    assert len(items) == 200
    assert [items[0]["id"], items[1]["id"]] == sorted(tie_ids)
    assert items[0]["created_at"] == tie_now.isoformat()
    expected_non_tie = [(base_now + timedelta(milliseconds=ms)).isoformat() for ms in range(244, 46, -1)]
    assert [entry["created_at"] for entry in items[2:]] == expected_non_tie


def test_cloud_review_store_history_newest_200_mixed_indexed_and_legacy():
    base_now = datetime.now(timezone.utc)
    minute = base_now.replace(second=0, microsecond=0)
    bucket = _FakeBucket()
    store = CloudReviewStore("test-project", "asia-south1", "autocloud-reviews", client=_FakeStorageClient(bucket))
    scope = ReviewStore.scope("test-project", "asia-south1", "autocloud-api")
    principal = "autocloud-dashboard@test-project.iam.gserviceaccount.com"

    legacy_ids: set[str] = set()
    for i in range(480):
        obs_now = base_now + timedelta(milliseconds=i)
        rows = [
            MetricRecord(
                timestamp=minute - timedelta(minutes=offset),
                collected_at=obs_now,
                project_id="test-project",
                region="asia-south1",
                service_name="autocloud-api",
                cpu_utilization=0.99,
                request_count=i + 1,
            )
            for offset in (2, 1, 0)
        ]
        plan = build_plan(rows, project="test-project", region="asia-south1", service="autocloud-api", now=obs_now)
        ids = store.capture(plan, obs_now, authenticated_principal=principal)
        if i % 2 == 0:
            legacy_ids.update(ids)

    # Strip by_time/ only for the 240 even records, keeping 240 odd records indexed.
    for key in [k for k in bucket.objects if "/by_time/" in k and any(lid in k for lid in legacy_ids)]:
        del bucket.objects[key]
    assert sum(1 for k in bucket.objects if "/by_time/" in k) == 240
    assert sum(1 for k in bucket.objects if "/items/" in k) == 480

    bucket.download_count = 0
    history_items = store.history(scope, base_now + timedelta(seconds=5))
    assert len(history_items) == 200
    assert [entry["created_at"] for entry in history_items] == [
        (base_now + timedelta(milliseconds=ms)).isoformat() for ms in range(479, 279, -1)
    ]
    # Exact read bound: 200 top indexed + 240 unindexed legacy + 200 decisions (no re-reads of indexed items/).
    assert bucket.download_count == 640


def test_cloud_review_store_history_enforces_30s_budget_across_calls_and_retries():
    from google.api_core.exceptions import ServiceUnavailable
    from app.api.reviews import history as api_history, review_access

    class _PagedIterator:
        def __init__(self, page_blobs, next_page_token):
            self._page_blobs = page_blobs
            self.next_page_token = next_page_token
            self._started = False

        @property
        def pages(self):
            # Mirror google.api_core.page_iterator.HTTPIterator single-use .pages property.
            if self._started:
                raise ValueError("Iterator has already started", self)
            self._started = True
            return iter([self._page_blobs])

    base_now = datetime.now(timezone.utc)
    bucket = _FakeBucket()
    fake_now = {"t": 100.0}
    store = CloudReviewStore(
        "test-project",
        "asia-south1",
        "autocloud-reviews",
        client=_FakeStorageClient(bucket),
        clock=lambda: fake_now["t"],
    )
    scope = ReviewStore.scope("test-project", "asia-south1", "autocloud-api")
    principal = "autocloud-dashboard@test-project.iam.gserviceaccount.com"
    _, _, plan = evidence()
    ids = store.capture(plan, base_now, authenticated_principal=principal)
    store.decide(scope, ids[0], "approved", "Operator", "Check CPU", base_now, authenticated_principal=principal)

    observed_calls: list[tuple[str, float | None, float | None, float | None]] = []

    def record_get(name, timeout=None, retry=None):
        observed_calls.append((
            "get_bucket",
            timeout,
            getattr(retry, "deadline", None),
            getattr(retry, "_maximum", None),
        ))
        fake_now["t"] += 5.0
        return bucket

    def record_list(*, prefix="", page_token=None, timeout=None, retry=None, **kwargs):
        observed_calls.append((
            f"list:{prefix.rsplit('/', 2)[-2]}:{page_token or 'p1'}",
            timeout,
            getattr(retry, "deadline", None),
            getattr(retry, "_maximum", None),
        ))
        all_blobs = [_FakeBlob(bucket, name) for name in sorted(bucket.objects) if name.startswith(prefix)]
        if "/by_time/" in prefix and page_token is None:
            fake_now["t"] += 7.0
            return _PagedIterator(all_blobs[:0], "page-2")
        if "/by_time/" in prefix and page_token == "page-2":
            fake_now["t"] += 4.0
            return _PagedIterator(all_blobs, None)
        fake_now["t"] += 3.0
        return _PagedIterator(all_blobs, None)

    def record_download(name, timeout=None, retry=None):
        observed_calls.append((
            f"download:{name.rsplit('/', 2)[-2]}",
            timeout,
            getattr(retry, "deadline", None),
            getattr(retry, "_maximum", None),
        ))
        fake_now["t"] += 2.0
        return bucket.objects[name]

    bucket.on_get = record_get
    bucket.on_list = record_list
    bucket.on_download = record_download

    result = store.history(scope, base_now)
    assert len(result) == 1
    assert observed_calls == [
        ("get_bucket", 10.0, 30.0, 30.0),
        ("list:by_time:p1", 10.0, 25.0, 25.0),
        ("list:by_time:page-2", 10.0, 18.0, 18.0),
        ("list:items:p1", 10.0, 14.0, 14.0),
        ("download:by_time", 10.0, 11.0, 11.0),
        ("download:decisions", 9.0, 9.0, 9.0),
    ]

    # Retry consuming elapsed time past 30s must halt immediately with TimeoutError,
    # never continuing remaining storage calls or falling back to 120s SDK defaults.
    fake_now["t"] = 200.0
    observed_calls.clear()

    def slow_get(name, timeout=None, retry=None):
        fake_now["t"] += 12.0
        return bucket

    def slow_list(*, prefix="", page_token=None, timeout=None, retry=None, **kwargs):
        all_blobs = [_FakeBlob(bucket, name) for name in sorted(bucket.objects) if name.startswith(prefix)]
        fake_now["t"] += 4.0
        return _PagedIterator(all_blobs, None)

    download_attempts = {"count": 0}

    def retry_exhausting_download(name, timeout=None, retry=None):
        download_attempts["count"] += 1
        observed_calls.append(("attempt", timeout, getattr(retry, "deadline", None), getattr(retry, "_maximum", None)))
        if download_attempts["count"] == 1:
            fake_now["t"] += 8.0
            # Simulate an underlying retry cycle exhausting the remaining budget.
            raise ServiceUnavailable("transient")
        fake_now["t"] += 7.0
        return bucket.objects[name]

    def single_retry_or_fail_download(name, timeout=None, retry=None):
        def _op():
            return retry_exhausting_download(name, timeout=timeout, retry=retry)

        # Emulate retry loop stopping once remaining deadline has elapsed.
        try:
            return _op()
        except ServiceUnavailable:
            assert retry is not None and retry.deadline <= 10.0
            return _op()

    bucket.on_get = slow_get
    bucket.on_list = slow_list
    bucket.on_download = single_retry_or_fail_download

    with pytest.raises(TimeoutError, match="30s"):
        store.history(scope, base_now)
    # 12 + 4 + 4 + 8 + 7 = 35s > 30s -> raised immediately after item download before decision read.
    assert download_attempts["count"] == 2
    assert observed_calls[0][2] == 10.0

    # API /api/reviews translates CloudReviewStore TimeoutError into HTTP 503.
    settings = Settings(
        environment="production",
        gcp_project_id="test-project",
        dashboard_review_bucket="autocloud-reviews",
        dashboard_review_audience="https://autocloud-api-example.run.app",
    )
    app = create_app(settings)
    app.state.review_token_verifier = lambda token, audience: principal

    class _TimingOutBucket(_FakeBucket):
        def list_blobs(self, *args, **kwargs):
            raise TimeoutError("Review history 30s storage budget exceeded")

    app.state.review_storage_client = _FakeStorageClient(_TimingOutBucket())
    req = _asgi_request(app, headers={"X-AutoCloud-Authorization": "Bearer hdr.pld.sig"})
    review_access(req)
    with pytest.raises(HTTPException) as exc:
        api_history(req)
    assert exc.value.status_code == 503


def test_cloud_review_store_handles_real_http_iterator_multi_page_and_empty():
    from google.api_core.page_iterator import HTTPIterator

    base_now = datetime.now(timezone.utc)
    bucket = _FakeBucket()
    store = CloudReviewStore("test-project", "asia-south1", "autocloud-reviews", client=_FakeStorageClient(bucket))
    scope = ReviewStore.scope("test-project", "asia-south1", "autocloud-api")
    scope_hash = store._scope_hash(scope)
    principal = "autocloud-dashboard@test-project.iam.gserviceaccount.com"

    # Populate 2 indexed items + 1 legacy item.
    minute = base_now.replace(second=0, microsecond=0)
    saved_ids = []
    for i in range(3):
        obs_now = base_now + timedelta(milliseconds=i)
        plan = build_plan(
            [
                MetricRecord(
                    timestamp=minute - timedelta(minutes=offset),
                    collected_at=obs_now,
                    project_id="test-project",
                    region="asia-south1",
                    service_name="autocloud-api",
                    cpu_utilization=0.99,
                    request_count=i + 1,
                )
                for offset in (2, 1, 0)
            ],
            project="test-project",
            region="asia-south1",
            service="autocloud-api",
            now=obs_now,
        )
        saved_ids.extend(store.capture(plan, obs_now, authenticated_principal=principal))
    for key in [k for k in bucket.objects if "/by_time/" in k and saved_ids[0] in k]:
        del bucket.objects[key]

    def paged_http_list(*, prefix="", page_token=None, fields=None, **kwargs):
        assert fields == "items(name),nextPageToken"
        names = [name for name in sorted(bucket.objects) if name.startswith(prefix)]
        if not names:
            api_response = lambda **_: {"items": []}
        elif page_token is None and len(names) > 1:
            api_response = lambda **_: {"items": [{"name": names[0]}], "nextPageToken": "tok-2"}
        elif page_token == "tok-2":
            api_response = lambda **_: {"items": [{"name": name} for name in names[1:]]}
        else:
            api_response = lambda **_: {"items": [{"name": name} for name in names]}
        return HTTPIterator(
            client=object(),
            api_request=api_response,
            path="/o",
            item_to_value=lambda _, item: _FakeBlob(bucket, item["name"]),
            page_token=page_token,
        )

    bucket.on_list = paged_http_list
    items = store.history(scope, base_now + timedelta(seconds=5))
    assert [entry["id"] for entry in items] == [saved_ids[2], saved_ids[1], saved_ids[0]]

    # Also verify empty bucket with real HTTPIterator returns [] cleanly without ValueError.
    bucket.objects.clear()
    assert store.history(scope, base_now + timedelta(seconds=5)) == []


def test_cloud_review_store_repairs_missing_index_on_capture_retry():
    from google.api_core.exceptions import ServiceUnavailable

    now, _, plan1 = evidence()
    bucket = _FakeBucket()
    orig_blob = bucket.blob
    fail_once = {"pending": True}

    def flaky_index_blob(name):
        blob = orig_blob(name)
        if "/by_time/" in name and fail_once["pending"]:
            def fail_upload(*args, **kwargs):
                fail_once["pending"] = False
                raise ServiceUnavailable("Transient GCS error on index write")
            blob.upload_from_string = fail_upload
        return blob

    bucket.blob = flaky_index_blob
    store = CloudReviewStore("test-project", "asia-south1", "autocloud-reviews", client=_FakeStorageClient(bucket))
    scope = ReviewStore.scope("test-project", "asia-south1", "autocloud-api")
    principal = "autocloud-dashboard@test-project.iam.gserviceaccount.com"

    # First save creates items/{id}.json then fails writing by_time/ index.
    with pytest.raises(ServiceUnavailable):
        store.capture(plan1, now, authenticated_principal=principal)
    assert not any("/by_time/" in k for k in bucket.objects)
    assert sum(1 for k in bucket.objects if "/items/" in k) == 1

    # Retrying the same plan repairs the missing index with original created_at.
    ids1 = store.capture(plan1, now + timedelta(seconds=5), authenticated_principal=principal)
    later = now + timedelta(seconds=10)
    plan2 = build_plan(
        [
            MetricRecord(
                timestamp=(later.replace(second=0, microsecond=0) - timedelta(minutes=i)),
                collected_at=later,
                project_id="test-project",
                region="asia-south1",
                service_name="autocloud-api",
                memory_utilization=0.98,
            )
            for i in (2, 1, 0)
        ],
        project="test-project",
        region="asia-south1",
        service="autocloud-api",
        now=later,
    )
    ids2 = store.capture(plan2, later, authenticated_principal=principal)

    items = store.history(scope, later)
    assert [item["id"] for item in items] == [ids2[0], ids1[0]]
    by_id = {item["id"]: item for item in items}
    assert by_id[ids1[0]]["created_at"] == now.isoformat()


def test_cloud_review_store_history_includes_legacy_unindexed_items_alongside_indexed():
    base_now = datetime.now(timezone.utc)
    minute = base_now.replace(second=0, microsecond=0)
    bucket = _FakeBucket()
    store = CloudReviewStore("test-project", "asia-south1", "autocloud-reviews", client=_FakeStorageClient(bucket))
    scope = ReviewStore.scope("test-project", "asia-south1", "autocloud-api")
    scope_hash = store._scope_hash(scope)
    principal = "autocloud-dashboard@test-project.iam.gserviceaccount.com"

    # Simulate an older unindexed review saved under items/ only.
    _, _, legacy_plan = evidence()
    legacy_ids = store.capture(legacy_plan, base_now - timedelta(minutes=5), authenticated_principal=principal)
    legacy_id = legacy_ids[0]
    for key in [k for k in bucket.objects if "/by_time/" in k]:
        del bucket.objects[key]

    # Save a newer indexed review that writes into by_time/.
    newer_now = base_now + timedelta(seconds=30)
    newer_plan = build_plan(
        [
            MetricRecord(
                timestamp=minute - timedelta(minutes=i),
                collected_at=newer_now,
                project_id="test-project",
                region="asia-south1",
                service_name="autocloud-api",
                memory_utilization=0.97,
            )
            for i in (2, 1, 0)
        ],
        project="test-project",
        region="asia-south1",
        service="autocloud-api",
        now=newer_now,
    )
    newer_ids = store.capture(newer_plan, newer_now, authenticated_principal=principal)

    bucket.download_count = 0
    items = store.history(scope, newer_now)
    assert [item["id"] for item in items] == [newer_ids[0], legacy_id]
    # 1 by_time item read + 1 legacy item read (indexed item skipped by name) + 2 decision probes = 4.
    assert bucket.download_count == 4
    assert f"reviews/{scope_hash}/items/{newer_ids[0]}.json" in bucket.objects


def test_cloud_review_settings_and_oidc_verification(monkeypatch):
    import base64
    import time
    from google.oauth2 import id_token
    from app.api.reviews import verify_oidc_principal

    valid = Settings(
        environment="production",
        gcp_project_id="test-project",
        dashboard_review_bucket="autocloud-reviews-1",
        dashboard_review_audience="https://autocloud-api-example.run.app",
    )
    assert valid.dashboard_review_bucket == "autocloud-reviews-1"
    for bad_bucket in ("google-reviews", "goog-test", "BadBucket", "ab"):
        with pytest.raises(ValidationError):
            Settings(gcp_project_id="test-project", dashboard_review_bucket=bad_bucket)
    for bad_audience in ("http://example.run.app", "https://example.com", "https://example.run.app/path"):
        with pytest.raises(ValidationError):
            Settings(gcp_project_id="test-project", dashboard_review_audience=bad_audience)

    signed_token = "hdr.pld.sig"
    monkeypatch.setattr(
        id_token,
        "verify_oauth2_token",
        lambda token, req, audience=None, **kwargs: {
            "iss": "https://accounts.google.com",
            "email_verified": True,
            "email": "autocloud-dashboard@test-project.iam.gserviceaccount.com",
            "aud": audience,
        },
    )
    assert verify_oidc_principal(signed_token, "https://autocloud-api-example.run.app") == (
        "autocloud-dashboard@test-project.iam.gserviceaccount.com"
    )
    with pytest.raises(ValueError):
        verify_oidc_principal(signed_token, None)

    # Generic Cloud SDK client ID or wrong audience must fail strict audience validation.
    sdk_client_id = "764086051850-6qr4p6gpi6hn506pt8ejuq83di341hur.apps.googleusercontent.com"
    for bad_claims in (
        {"iss": "https://evil.example", "email_verified": True, "email": "a@b.com", "aud": "https://autocloud-api-example.run.app"},
        {"iss": "https://accounts.google.com", "email_verified": False, "email": "a@b.com", "aud": "https://autocloud-api-example.run.app"},
        {"iss": "https://accounts.google.com", "email_verified": True, "aud": "https://autocloud-api-example.run.app"},
        {"iss": "https://accounts.google.com", "email_verified": True, "email": "a@b.com", "aud": "https://wrong.run.app"},
        {"iss": "https://accounts.google.com", "email_verified": True, "email": "a@b.com", "aud": sdk_client_id},
    ):
        monkeypatch.setattr(id_token, "verify_oauth2_token", lambda *a, _c=bad_claims, **kw: _c)
        with pytest.raises(ValueError):
            verify_oidc_principal(signed_token, "https://autocloud-api-example.run.app")

    def _expired(*args, **kwargs):
        raise ValueError("Token expired")

    monkeypatch.setattr(id_token, "verify_oauth2_token", _expired)
    with pytest.raises(ValueError):
        verify_oidc_principal(signed_token, "https://autocloud-api-example.run.app")

    def make_redacted_jwt(claims):
        header = base64.urlsafe_b64encode(b'{"alg":"RS256"}').decode().rstrip("=")
        payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        return f"{header}.{payload}.SIGNATURE_REMOVED_BY_GOOGLE"

    redacted_valid = make_redacted_jwt({
        "iss": "https://accounts.google.com",
        "aud": "https://autocloud-api-example.run.app",
        "email_verified": True,
        "email": "autocloud-dashboard@test-project.iam.gserviceaccount.com",
        "exp": time.time() + 300,
    })

    # Redacted or unsigned tokens must NEVER be accepted, even when K_SERVICE is set.
    verify_calls = []

    def track_verify(*args, **kwargs):
        verify_calls.append(True)
        return {
            "iss": "https://accounts.google.com",
            "aud": "https://autocloud-api-example.run.app",
            "email_verified": True,
            "email": "forged@evil.example",
        }

    monkeypatch.setattr(id_token, "verify_oauth2_token", track_verify)
    for env_set in (False, True):
        if env_set:
            monkeypatch.setenv("K_SERVICE", "autocloud-api")
        else:
            monkeypatch.delenv("K_SERVICE", raising=False)
        for bad_tok in (redacted_valid, "hdr.pld.", "not-a-jwt", ""):
            with pytest.raises(ValueError):
                verify_oidc_principal(bad_tok, "https://autocloud-api-example.run.app")
    assert verify_calls == []


def test_cloud_review_access_and_handlers_pure_python(tmp_path):
    from app.api.monitoring import monitoring_overview
    from app.api.reviews import Capture, Decision, capture, decide, history, review_access

    _, rows, plan = evidence()
    save_records(rows, tmp_path / "processed/metrics.ndjson")
    settings = Settings(
        environment="production",
        gcp_project_id="test-project",
        dashboard_review_bucket="autocloud-reviews",
        dashboard_review_audience="https://autocloud-api-example.run.app",
    )
    app = create_app(settings)
    app.state.analytics_data_root = tmp_path
    app.state.review_storage_client = _FakeStorageClient(_FakeBucket())

    def verifier(token, audience):
        if token != "hdr.pld.sig" or audience != "https://autocloud-api-example.run.app":
            raise ValueError("Invalid token")
        return "autocloud-dashboard@test-project.iam.gserviceaccount.com"

    app.state.review_token_verifier = verifier

    # Overview exposes cloud_reviews=True and local_reviews=False.
    overview_payload = monitoring_overview(_asgi_request(app, path="/api/overview"), source="local", hours=24)
    assert overview_payload["capabilities"]["local_reviews"] is False
    assert overview_payload["capabilities"]["cloud_reviews"] is True

    # Missing Bearer token rejected.
    with pytest.raises(HTTPException) as exc:
        review_access(_asgi_request(app))
    assert exc.value.status_code == 403

    # Browser Origin rejected even with valid token.
    with pytest.raises(HTTPException) as exc:
        review_access(_asgi_request(app, headers={
            "X-AutoCloud-Authorization": "Bearer hdr.pld.sig",
            "Origin": "https://evil.example",
        }))
    assert exc.value.status_code == 403

    # Invalid token rejected.
    with pytest.raises(HTTPException) as exc:
        review_access(_asgi_request(app, headers={"X-AutoCloud-Authorization": "Bearer bad.pld.sig"}))
    assert exc.value.status_code == 403

    # Edge-redacted Authorization alone and mixed-header substitution attacks are rejected.
    for forged_headers in (
        {"Authorization": "Bearer hdr.pld.SIGNATURE_REMOVED_BY_GOOGLE"},
        {
            "X-Serverless-Authorization": "Bearer edge.pld.sig",
            "Authorization": "Bearer hdr.pld.SIGNATURE_REMOVED_BY_GOOGLE",
        },
        {
            "X-Serverless-Authorization": "Bearer edge.pld.sig",
            "Authorization": "Bearer forged.pld.sig",
            "X-AutoCloud-Authorization": "Bearer hdr.pld.sig",
        },
        {
            "Authorization": "Bearer other.pld.sig",
            "X-AutoCloud-Authorization": "Bearer hdr.pld.sig",
        },
        {
            "Authorization": "Bearer other.pld.SIGNATURE_REMOVED_BY_GOOGLE",
            "X-AutoCloud-Authorization": "Bearer hdr.pld.sig",
        },
    ):
        with pytest.raises(HTTPException) as exc:
            review_access(_asgi_request(app, headers=forged_headers))
        assert exc.value.status_code == 403

    # Supported Cloud Run path: GFE redacts Authorization signature, preserves X-AutoCloud-Authorization intact.
    auth_req = _asgi_request(app, headers={
        "Authorization": "Bearer hdr.pld.SIGNATURE_REMOVED_BY_GOOGLE",
        "X-AutoCloud-Authorization": "Bearer hdr.pld.sig",
    })
    assert review_access(auth_req) == "autocloud-dashboard@test-project.iam.gserviceaccount.com"

    cap_res = capture(Capture(source="local", hours=24, evidence_fingerprint=plan.evidence_fingerprint), auth_req)
    assert len(cap_res["saved_ids"]) == 1
    assert cap_res["calling_service_principal"] == "autocloud-dashboard@test-project.iam.gserviceaccount.com"
    assert cap_res["authenticated_principal"] == "autocloud-dashboard@test-project.iam.gserviceaccount.com"
    assert cap_res["reviewer_identity"] == "service_authenticated_self_reported_label"
    assert cap_res["execution_allowed"] is False

    dec_res = decide(
        cap_res["saved_ids"][0],
        Decision(decision="approved", reviewer="Cloud Operator", note="Review sustained CPU"),
        auth_req,
    )
    assert dec_res == {
        "status": "approved",
        "execution_allowed": False,
        "reviewer_identity": "service_authenticated_self_reported_label",
        "calling_service_principal": "autocloud-dashboard@test-project.iam.gserviceaccount.com",
        "authenticated_principal": "autocloud-dashboard@test-project.iam.gserviceaccount.com",
    }

    hist_res = history(auth_req)
    assert hist_res["reviewer_identity"] == "service_authenticated_self_reported_label"
    assert hist_res["human_reviewer_verified"] is False
    assert hist_res["calling_service_principal"] == "autocloud-dashboard@test-project.iam.gserviceaccount.com"
    assert hist_res["authenticated_principal"] == "autocloud-dashboard@test-project.iam.gserviceaccount.com"
    assert hist_res["execution_allowed"] is False
    assert hist_res["items"][0]["status"] == "approved"
    assert hist_res["items"][0]["calling_service_principal"] == "autocloud-dashboard@test-project.iam.gserviceaccount.com"
    assert hist_res["items"][0]["human_reviewer_verified"] is False


def test_cloud_review_ui_forwards_headers_and_principal(monkeypatch):
    import httpx
    from contextlib import nullcontext
    from unittest.mock import Mock
    import app.dashboard.reviews as reviews_ui

    _, _, plan = evidence()
    calls = []
    writes = []

    class _FakeSt:
        session_state = {}

        @staticmethod
        def subheader(text):
            pass

        @staticmethod
        def caption(text):
            writes.append(("caption", text))

        @staticmethod
        def button(label, disabled=False):
            return label == "Load review history"

        @staticmethod
        def info(text):
            pass

        @staticmethod
        def warning(text):
            pass

        @staticmethod
        def success(text):
            pass

        @staticmethod
        def error(text):
            raise AssertionError(text)

        @staticmethod
        def expander(label):
            return nullcontext()

        @staticmethod
        def json(data):
            pass

        @staticmethod
        def write(text):
            writes.append(("write", text))

        @staticmethod
        def text(value):
            pass

    history_payload = {
        "items": [{
            "id": "a" * 64,
            "snapshot": plan.model_dump(mode="json"),
            "created_at": plan.assessed_at.isoformat(),
            "expires_at": (plan.assessed_at + timedelta(minutes=15)).isoformat(),
            "decision": "approved",
            "reviewer": "Cloud Operator",
            "authenticated_principal": "autocloud-dashboard@test-project.iam.gserviceaccount.com",
            "note": "Investigate CPU",
            "decided_at": plan.assessed_at.isoformat(),
            "status": "approved",
            "evidence_expired": False,
            "execution_allowed": False,
        }]
    }

    def fake_request(method, url, json=None, headers=None):
        calls.append((method, url, headers))
        return Mock(status_code=200, json=Mock(return_value=history_payload))

    client = Mock()
    client.__enter__ = Mock(return_value=client)
    client.__exit__ = Mock(return_value=False)
    client.request.side_effect = fake_request
    monkeypatch.setattr(httpx, "Client", Mock(return_value=client))
    monkeypatch.setattr(reviews_ui, "st", _FakeSt)

    reviews_ui.render_reviews(
        "https://api.example.run.app",
        plan.model_dump(mode="json"),
        "BigQuery",
        24,
        headers={
            "Authorization": "Bearer id-tok",
            "X-AutoCloud-Authorization": "Bearer id-tok",
        },
        cloud_reviews=True,
    )
    assert calls == [(
        "GET",
        "https://api.example.run.app/api/reviews",
        {"Authorization": "Bearer id-tok", "X-AutoCloud-Authorization": "Bearer id-tok"},
    )]
    assert any("autocloud-dashboard@test-project.iam.gserviceaccount.com" in msg for _, msg in writes)
    assert any("self-reported reviewer label" in msg for _, msg in writes)


def test_cloud_review_fastapi_integration(tmp_path):
    _, rows, plan = evidence()
    save_records(rows, tmp_path / "processed/metrics.ndjson")
    app = create_app(Settings(
        environment="production",
        gcp_project_id="test-project",
        dashboard_review_bucket="autocloud-reviews",
        dashboard_review_audience="https://autocloud-api-example.run.app",
    ))
    app.state.analytics_data_root = tmp_path
    app.state.review_storage_client = _FakeStorageClient(_FakeBucket())
    app.state.review_token_verifier = (
        lambda token, aud: "autocloud-dashboard@test-project.iam.gserviceaccount.com"
        if token == "hdr.pld.sig" else (_ for _ in ()).throw(ValueError("bad"))
    )
    with TestClient(app) as client:
        assert client.get("/api/reviews").status_code == 403
        assert client.get("/api/reviews", headers={"X-AutoCloud-Authorization": "Bearer bad.pld.sig"}).status_code == 403
        assert client.get("/api/reviews", headers={"Authorization": "Bearer hdr.pld.SIGNATURE_REMOVED_BY_GOOGLE"}).status_code == 403
        headers = {
            "Authorization": "Bearer hdr.pld.SIGNATURE_REMOVED_BY_GOOGLE",
            "X-AutoCloud-Authorization": "Bearer hdr.pld.sig",
        }
        assert client.get("/api/reviews", headers={**headers, "Origin": "https://evil.example"}).status_code == 403
        cap = client.post(
            "/api/reviews/capture",
            headers=headers,
            json={"source": "local", "hours": 24, "evidence_fingerprint": plan.evidence_fingerprint},
        )
        assert cap.status_code == 200
        assert cap.json()["calling_service_principal"] == "autocloud-dashboard@test-project.iam.gserviceaccount.com"
        identifier = cap.json()["saved_ids"][0]
        dec = client.post(
            f"/api/reviews/{identifier}/decision",
            headers=headers,
            json={"decision": "approved", "reviewer": "Operator", "note": "Check CPU"},
        )
        assert dec.status_code == 200
        assert dec.json()["calling_service_principal"] == "autocloud-dashboard@test-project.iam.gserviceaccount.com"
        assert dec.json()["reviewer_identity"] == "service_authenticated_self_reported_label"
        hist = client.get("/api/reviews", headers=headers).json()
        assert hist["reviewer_identity"] == "service_authenticated_self_reported_label"
        assert hist["human_reviewer_verified"] is False
        assert hist["items"][0]["status"] == "approved"
