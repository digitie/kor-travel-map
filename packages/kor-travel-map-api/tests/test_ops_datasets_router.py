"""``/v1/ops/datasets`` 그룹 (ADR-064 T-ADM-C2) 라우터 테스트 — DB 무관(monkeypatch)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra.dataset_status_repo import DatasetIntegrityIssueCount
from kortravelmap.infra.feature_update_repo import (
    FeatureUpdateRequest,
    FeatureUpdateRequestPage,
)
from kortravelmap.infra.ops_repo import (
    OpsImportJob,
    OpsImportJobEvent,
    OpsImportJobEventPage,
)
from kortravelmap.infra.provider_refresh_policy_repo import ProviderRefreshPolicy
from kortravelmap.infra.sync_state_repo import SyncState

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings

_NOW = datetime(2026, 7, 14, tzinfo=UTC)
_JOB_ID = "22222222-2222-2222-2222-222222222222"


class _Tx:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    def __init__(self) -> None:
        self.begin_count = 0

    def begin(self) -> _Tx:
        self.begin_count += 1
        return _Tx()


@pytest.fixture
def session() -> _FakeSession:
    return _FakeSession()


@pytest.fixture
def client(session: _FakeSession) -> TestClient:
    app = create_app(ApiSettings())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield session

    app.dependency_overrides[get_session] = _fake_session
    return TestClient(app)


def _state(
    *,
    provider: str = "python-mois-api",
    dataset_key: str = "mois_license_features_bulk",
    sync_scope: str = "default",
    consecutive_failures: int = 0,
) -> SyncState:
    return SyncState(
        provider=provider,
        dataset_key=dataset_key,
        sync_scope=sync_scope,
        status="active",
        cursor={"last_modified_date": "2026-07-13"},
        last_success_at=_NOW,
        last_failure_at=None,
        consecutive_failures=consecutive_failures,
        next_run_after=_NOW,
    )


def _policy(
    *,
    provider: str = "python-mois-api",
    dataset_key: str = "mois_license_features_bulk",
) -> ProviderRefreshPolicy:
    return ProviderRefreshPolicy(
        provider=provider,
        dataset_key=dataset_key,
        source_kind="openapi",
        targeted_policy="allow_targeted",
        system_interval_seconds=3600,
        optimal_interval_seconds=1800,
        min_interval_seconds=60,
        max_requests_per_minute=60,
        max_requests_per_hour=None,
        max_requests_per_day=None,
        max_concurrent=2,
        burst_size=5,
        rate_limit_source={},
        config_source="db",
        enabled=True,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _issue_count(
    *,
    provider: str = "python-mois-api",
    dataset_key: str | None = "mois_license_features_bulk",
    open_total: int = 3,
) -> DatasetIntegrityIssueCount:
    return DatasetIntegrityIssueCount(
        provider=provider,
        dataset_key=dataset_key,
        open_total=open_total,
        by_severity={"error": open_total - 1, "warning": 1},
    )


def _update_request(*, job_id: str | None = _JOB_ID) -> FeatureUpdateRequest:
    return FeatureUpdateRequest(
        request_id="11111111-1111-1111-1111-111111111111",
        scope_type="provider_dataset",
        scope={
            "type": "provider_dataset",
            "provider": "python-mois-api",
            "dataset_key": "mois_license_features_bulk",
        },
        providers=(),
        dataset_keys=(),
        update_policy={},
        run_mode="queued",
        priority=50,
        status="succeeded",
        dry_run=False,
        matched_scope={"feature_count": 12},
        job_id=job_id,
        dagster_run_id="run-1",
        operator="tester",
        reason="unit",
        error_message=None,
        created_at=_NOW,
        started_at=_NOW,
        finished_at=_NOW,
        updated_at=_NOW,
    )


def _job(job_id: str = _JOB_ID) -> OpsImportJob:
    return OpsImportJob(
        job_id=job_id,
        kind="feature_update_request",
        load_batch_id=None,
        parent_job_id=None,
        payload={"request_id": "11111111-1111-1111-1111-111111111111"},
        status="done",
        progress=100,
        current_stage="loading",
        source_checksum=None,
        error_message=None,
        created_at=_NOW,
        started_at=_NOW,
        finished_at=_NOW,
        heartbeat_at=_NOW,
    )


def _event() -> OpsImportJobEvent:
    return OpsImportJobEvent(
        event_id="33333333-3333-3333-3333-333333333333",
        job_id=_JOB_ID,
        provider="python-mois-api",
        dataset_key="mois_license_features_bulk",
        feature_id=None,
        stage="loading",
        level="error",
        code="provider.timeout",
        message="provider timeout",
        payload={"attempt": 2},
        occurred_at=_NOW,
    )


def _patch_grid_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    states: list[SyncState],
    policies: tuple[ProviderRefreshPolicy, ...] = (),
    issue_counts: tuple[DatasetIntegrityIssueCount, ...] = (),
) -> None:
    from kortravelmap.api.routers import ops_datasets as mod

    async def _states(_s: Any) -> list[SyncState]:
        return states

    async def _policies(_s: Any, **_kw: Any) -> tuple[ProviderRefreshPolicy, ...]:
        return policies

    async def _issues(_s: Any, **_kw: Any) -> tuple[DatasetIntegrityIssueCount, ...]:
        return issue_counts

    monkeypatch.setattr(mod.sync_state_repo, "list_all_sync_states", _states)
    monkeypatch.setattr(mod, "list_provider_refresh_policies", _policies)
    monkeypatch.setattr(mod, "count_open_integrity_issues_by_dataset", _issues)


# ── OpenAPI 계약 ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_ops_datasets_routes_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/ops/datasets" in spec["paths"]
    assert "/v1/ops/datasets/{provider}/{dataset}" in spec["paths"]
    assert "/v1/ops/datasets/{provider}/{dataset}/refresh-policy" in spec["paths"]
    assert "/v1/ops/datasets/{provider}/{dataset}/preview" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "OpsDatasetsGridResponse" in schemas
    assert "OpsDatasetDetailResponse" in schemas
    assert "OpsDatasetRefreshPolicyResponse" in schemas
    assert "OpsDatasetPreviewResponse" in schemas


@pytest.mark.unit
def test_ops_datasets_absent_when_ops_routes_disabled() -> None:
    app = create_app(ApiSettings(features_routes_enabled=False, ops_routes_enabled=False))
    spec = TestClient(app).get("/openapi.json").json()
    assert not any(path.startswith("/v1/ops/datasets") for path in spec["paths"])


@pytest.mark.unit
def test_ops_datasets_requires_admin_frontend_gate() -> None:
    """admin_proxy_secret 설정 시 무인증 직접 호출은 403 — 조작 포함 그룹 게이트."""
    app = create_app(ApiSettings(admin_proxy_secret="proxy-secret"))
    client = TestClient(app)
    response = client.get("/v1/ops/datasets")
    assert response.status_code == 403


# ── GET /ops/datasets (그리드) ────────────────────────────────────────


@pytest.mark.unit
def test_grid_includes_never_run_catalog_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_grid_sources(monkeypatch, states=[])

    response = client.get("/v1/ops/datasets")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    by_key = {(i["provider"], i["dataset_key"]): i for i in items}
    row = by_key[("python-mois-api", "mois_license_features_bulk")]
    assert row["status"] == "never_run"
    assert row["sync_scope"] == "default"
    assert row["last_success_at"] is None
    assert row["consecutive_failures"] == 0
    assert row["open_issue_count"] == 0
    assert row["issue_severity_counts"] == {}
    assert row["catalog"]["feature_kind"] == "place"
    assert row["catalog"]["is_feature_load"] is True
    # 운영 내부 cursor는 그리드에 노출하지 않는다.
    assert "cursor" not in row
    # KMA 격자 dataset은 카탈로그 기본 scope를 따른다.
    kma = by_key[("python-kma-api", "kma_short_forecast")]
    assert kma["sync_scope"] == "target_grids"
    assert kma["catalog"]["is_refreshable"] is True
    # 정렬: provider → dataset_key → sync_scope.
    keys = [(i["provider"], i["dataset_key"], i["sync_scope"]) for i in items]
    assert keys == sorted(keys)


@pytest.mark.unit
def test_grid_joins_state_policy_and_issue_counts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_grid_sources(
        monkeypatch,
        states=[_state()],
        policies=(_policy(),),
        issue_counts=(_issue_count(),),
    )

    response = client.get("/v1/ops/datasets")

    assert response.status_code == 200
    items = response.json()["data"]["items"]
    by_key = {(i["provider"], i["dataset_key"]): i for i in items}
    row = by_key[("python-mois-api", "mois_license_features_bulk")]
    assert row["status"] == "active"
    assert row["last_success_at"].startswith("2026-07-14")
    assert row["refresh_policy"]["targeted_policy"] == "allow_targeted"
    assert row["open_issue_count"] == 3
    assert row["issue_severity_counts"] == {"error": 2, "warning": 1}
    # 다른 카탈로그 행은 여전히 never_run으로 공존한다.
    other = by_key[("python-krex-api", "krex_rest_areas")]
    assert other["status"] == "never_run"
    assert other["open_issue_count"] == 0


@pytest.mark.unit
def test_grid_expands_multi_scope_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sync row가 scope별로 여러 개면 3원 그리드 행도 여러 개다."""
    _patch_grid_sources(
        monkeypatch,
        states=[
            _state(
                provider="python-kma-api",
                dataset_key="kma_short_forecast",
                sync_scope="grid:60,127",
            ),
            _state(
                provider="python-kma-api",
                dataset_key="kma_short_forecast",
                sync_scope="grid:61,125",
                consecutive_failures=2,
            ),
        ],
    )

    response = client.get("/v1/ops/datasets")

    items = response.json()["data"]["items"]
    kma_rows = [
        i
        for i in items
        if (i["provider"], i["dataset_key"]) == ("python-kma-api", "kma_short_forecast")
    ]
    assert [row["sync_scope"] for row in kma_rows] == ["grid:60,127", "grid:61,125"]
    assert kma_rows[1]["consecutive_failures"] == 2
    # scope 행마다 카탈로그 메타는 동일하게 붙는다.
    assert all(row["catalog"]["default_sync_scope"] == "target_grids" for row in kma_rows)


@pytest.mark.unit
def test_grid_keeps_leftover_state_and_policy_rows(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """카탈로그에서 빠진 잔존 sync/policy row도 catalog=null로 계속 보인다."""
    _patch_grid_sources(
        monkeypatch,
        states=[_state(provider="python-legacy-api", dataset_key="legacy_dataset")],
        policies=(_policy(provider="python-old-api", dataset_key="old_dataset"),),
    )

    response = client.get("/v1/ops/datasets")

    items = response.json()["data"]["items"]
    by_key = {(i["provider"], i["dataset_key"]): i for i in items}
    leftover_state = by_key[("python-legacy-api", "legacy_dataset")]
    assert leftover_state["status"] == "active"
    assert leftover_state["catalog"] is None
    policy_only = by_key[("python-old-api", "old_dataset")]
    assert policy_only["status"] == "never_run"
    assert policy_only["catalog"] is None
    assert policy_only["refresh_policy"]["provider"] == "python-old-api"


# ── GET /ops/datasets/{provider}/{dataset} (상세) ─────────────────────


def _patch_detail_sources(
    monkeypatch: pytest.MonkeyPatch,
    *,
    states: list[SyncState],
    policy: ProviderRefreshPolicy | None = None,
    requests: tuple[FeatureUpdateRequest, ...] = (),
    jobs: tuple[OpsImportJob, ...] = (),
    events: tuple[OpsImportJobEvent, ...] = (),
    issue_counts: tuple[DatasetIntegrityIssueCount, ...] = (),
) -> None:
    from kortravelmap.api.routers import ops_datasets as mod

    async def _states(_s: Any, **_kw: Any) -> list[SyncState]:
        return states

    async def _policy_fn(_s: Any, **_kw: Any) -> ProviderRefreshPolicy | None:
        return policy

    async def _requests(_s: Any, **kw: Any) -> FeatureUpdateRequestPage:
        assert kw["limit"] == 10
        return FeatureUpdateRequestPage(items=requests, next_cursor=None)

    async def _jobs(_s: Any, job_ids: Any) -> tuple[OpsImportJob, ...]:
        assert list(job_ids) == [r.job_id for r in requests if r.job_id]
        return jobs

    async def _events(_s: Any, **kw: Any) -> OpsImportJobEventPage:
        assert kw["provider"] is not None
        assert kw["dataset_key"] is not None
        return OpsImportJobEventPage(items=events, next_cursor=None)

    async def _issues(_s: Any, **_kw: Any) -> tuple[DatasetIntegrityIssueCount, ...]:
        return issue_counts

    monkeypatch.setattr(mod.sync_state_repo, "list_sync_states", _states)
    monkeypatch.setattr(mod, "get_provider_refresh_policy", _policy_fn)
    monkeypatch.setattr(mod, "list_update_requests", _requests)
    monkeypatch.setattr(mod, "list_ops_import_jobs_by_ids", _jobs)
    monkeypatch.setattr(mod, "list_ops_import_job_events", _events)
    monkeypatch.setattr(mod, "count_open_integrity_issues_by_dataset", _issues)


@pytest.mark.unit
def test_detail_404_when_unknown_everywhere(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_detail_sources(monkeypatch, states=[])

    response = client.get("/v1/ops/datasets/unknown-provider/unknown_dataset")

    assert response.status_code == 404
    assert "unknown-provider" in response.json()["detail"]


@pytest.mark.unit
def test_detail_never_run_catalog_synthesizes_scope(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """sync/policy row가 없어도 카탈로그 조합은 200 + never_run scope 합성."""
    _patch_detail_sources(monkeypatch, states=[])

    response = client.get(
        "/v1/ops/datasets/python-mois-api/mois_license_features_bulk"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["catalog"]["feature_kind"] == "place"
    assert data["scopes"] == [
        {
            "sync_scope": "default",
            "status": "never_run",
            "cursor": {},
            "last_success_at": None,
            "last_failure_at": None,
            "consecutive_failures": 0,
            "next_run_after": None,
        }
    ]
    assert data["recent_runs"] == []
    assert data["recent_events"] == []
    assert data["open_issue_count"] == 0


@pytest.mark.unit
def test_detail_returns_scopes_runs_events_and_policy(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_detail_sources(
        monkeypatch,
        states=[
            _state(sync_scope="kr"),
            _state(sync_scope="jeju", consecutive_failures=1),
        ],
        policy=_policy(),
        requests=(_update_request(), _update_request(job_id=None)),
        jobs=(_job(),),
        events=(_event(),),
        issue_counts=(_issue_count(),),
    )

    response = client.get(
        "/v1/ops/datasets/python-mois-api/mois_license_features_bulk"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    # scope 배열(3원) — 운영 상세라 cursor를 노출한다.
    assert [s["sync_scope"] for s in data["scopes"]] == ["kr", "jeju"]
    assert data["scopes"][0]["cursor"] == {"last_modified_date": "2026-07-13"}
    assert data["scopes"][1]["consecutive_failures"] == 1
    assert data["refresh_policy"]["max_concurrent"] == 2
    # 최근 실행 — update request + 연결 import job 요약 join.
    first_run, second_run = data["recent_runs"]
    assert first_run["request_id"].startswith("11111111")
    assert first_run["job_id"] == _JOB_ID
    assert first_run["job_status"] == "done"
    assert first_run["job_progress"] == 100
    assert first_run["dagster_run_id"] == "run-1"
    assert second_run["job_id"] is None
    assert second_run["job_status"] is None
    # 최근 이벤트.
    event = data["recent_events"][0]
    assert event["level"] == "error"
    assert event["code"] == "provider.timeout"
    # 이슈 카운트.
    assert data["open_issue_count"] == 3
    assert data["issue_severity_counts"] == {"error": 2, "warning": 1}


# ── PUT /ops/datasets/{provider}/{dataset}/refresh-policy ─────────────


_POLICY_BODY = {
    "source_kind": "openapi",
    "targeted_policy": "allow_targeted",
    "system_interval_seconds": 3600,
    "optimal_interval_seconds": 1800,
    "min_interval_seconds": 60,
    "max_requests_per_minute": 60,
    "max_concurrent": 2,
    "burst_size": 5,
    "rate_limit_source": {},
    "enabled": True,
}


@pytest.mark.unit
def test_refresh_policy_upsert_for_catalog_dataset(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import ops_datasets as mod

    async def _upsert(_s: Any, **kwargs: Any) -> ProviderRefreshPolicy:
        assert kwargs["provider"] == "python-mois-api"
        assert kwargs["dataset_key"] == "mois_license_features_bulk"
        assert kwargs["source_kind"] == "openapi"
        assert kwargs["max_concurrent"] == 2
        return _policy()

    monkeypatch.setattr(mod, "upsert_provider_refresh_policy", _upsert)

    response = client.put(
        "/v1/ops/datasets/python-mois-api/mois_license_features_bulk/refresh-policy",
        json=_POLICY_BODY,
    )

    assert response.status_code == 200
    assert response.json()["data"]["provider"] == "python-mois-api"
    assert session.begin_count == 1


@pytest.mark.unit
def test_refresh_policy_404_for_unknown_dataset(
    client: TestClient,
    session: _FakeSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """카탈로그·sync state·기존 policy 어디에도 없는 조합은 404.

    존재 검증이 transaction 안으로 들어갔으므로(리뷰 S2) begin은 1회 열리고
    HTTPException으로 롤백된다.
    """
    from kortravelmap.api.routers import ops_datasets as mod

    async def _no_states(_s: Any, **_kw: Any) -> list[SyncState]:
        return []

    async def _no_policy(_s: Any, **_kw: Any) -> ProviderRefreshPolicy | None:
        return None

    monkeypatch.setattr(mod.sync_state_repo, "list_sync_states", _no_states)
    monkeypatch.setattr(mod, "get_provider_refresh_policy", _no_policy)

    response = client.put(
        "/v1/ops/datasets/unknown-provider/unknown_dataset/refresh-policy",
        json=_POLICY_BODY,
    )

    assert response.status_code == 404
    assert session.begin_count == 1


# NOTE(리뷰 S2): 아래 두 성공-경로 unit 테스트는 허용 집합 **분기 로직만**
# 고정한다. `_FakeSession`은 SQLAlchemy autobegin("SELECT가 시작한 transaction
# 위에서 begin() 금지")을 흉내내지 못해 transaction 순서 결함(500)을 잡을 수
# 없다 — 실세션(fresh AsyncSession) 회귀는
# `tests/integration/test_ops_datasets_refresh_policy.py`가 고정한다.


@pytest.mark.unit
def test_refresh_policy_allows_leftover_sync_state_dataset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """카탈로그에서 빠졌어도 sync state가 남아 있으면 정책 편집을 허용한다."""
    from kortravelmap.api.routers import ops_datasets as mod

    async def _states(_s: Any, **_kw: Any) -> list[SyncState]:
        return [_state(provider="python-legacy-api", dataset_key="legacy_dataset")]

    async def _upsert(_s: Any, **kwargs: Any) -> ProviderRefreshPolicy:
        return _policy(
            provider=kwargs["provider"], dataset_key=kwargs["dataset_key"]
        )

    monkeypatch.setattr(mod.sync_state_repo, "list_sync_states", _states)
    monkeypatch.setattr(mod, "upsert_provider_refresh_policy", _upsert)

    response = client.put(
        "/v1/ops/datasets/python-legacy-api/legacy_dataset/refresh-policy",
        json=_POLICY_BODY,
    )

    assert response.status_code == 200
    assert response.json()["data"]["dataset_key"] == "legacy_dataset"


@pytest.mark.unit
def test_refresh_policy_allows_existing_policy_only_dataset(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """카탈로그·sync state 없이 기존 policy row만 있어도 편집을 허용한다(리뷰 S3).

    그리드(policy-only 잔존 행)/상세가 노출하는 행의 정책 저장(예: enabled
    끄기)이 404가 되면 read 표면과 자기모순 — C6b에서 구 라우터가 삭제되면
    해당 정책을 수정할 API가 사라진다.
    """
    from kortravelmap.api.routers import ops_datasets as mod

    async def _no_states(_s: Any, **_kw: Any) -> list[SyncState]:
        return []

    async def _existing_policy(_s: Any, **_kw: Any) -> ProviderRefreshPolicy:
        return _policy(provider="python-old-api", dataset_key="old_dataset")

    async def _upsert(_s: Any, **kwargs: Any) -> ProviderRefreshPolicy:
        return _policy(
            provider=kwargs["provider"], dataset_key=kwargs["dataset_key"]
        )

    monkeypatch.setattr(mod.sync_state_repo, "list_sync_states", _no_states)
    monkeypatch.setattr(mod, "get_provider_refresh_policy", _existing_policy)
    monkeypatch.setattr(mod, "upsert_provider_refresh_policy", _upsert)

    response = client.put(
        "/v1/ops/datasets/python-old-api/old_dataset/refresh-policy",
        json=_POLICY_BODY,
    )

    assert response.status_code == 200
    assert response.json()["data"]["provider"] == "python-old-api"


@pytest.mark.unit
def test_refresh_policy_rejects_rate_limit_exceeding_interval(
    client: TestClient,
    session: _FakeSession,
) -> None:
    response = client.put(
        "/v1/ops/datasets/python-mois-api/mois_license_features_bulk/refresh-policy",
        json={
            "source_kind": "openapi",
            "system_interval_seconds": 1,
            "max_requests_per_minute": 10,
        },
    )

    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"
    assert session.begin_count == 0


# ── POST /ops/datasets/{provider}/{dataset}/preview ───────────────────


@pytest.mark.unit
def test_preview_fixture_runs_offline(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/datasets/data.go.kr-standard/datagokr_cultural_festivals/preview"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "fixture"
    assert data["variant"] == "FeatureBundle"
    assert data["items"]
    assert "count" not in data


@pytest.mark.unit
def test_preview_no_fixture_returns_404_hint(client: TestClient) -> None:
    response = client.post(
        "/v1/ops/datasets/python-mois-api/mois_license_features_bulk/preview"
    )

    assert response.status_code == 404
    assert "no preview fixture" in response.json()["detail"]


@pytest.mark.unit
def test_preview_unknown_dataset_404(client: TestClient) -> None:
    response = client.post("/v1/ops/datasets/unknown-provider/unknown_dataset/preview")
    assert response.status_code == 404


@pytest.mark.unit
def test_preview_live_forbidden_by_default(client: TestClient) -> None:
    """live preview는 opt-in flag 없이는 403 — 실 provider 쿼터 보호 (ADR-064)."""
    response = client.post(
        "/v1/ops/datasets/python-kma-api/kma_short_forecast/preview?source=live"
    )

    assert response.status_code == 403
    assert "ETL_LIVE_PREVIEW_ENABLED" in response.json()["detail"]


def _live_client() -> TestClient:
    return TestClient(create_app(ApiSettings(etl_live_preview_enabled=True)))


@pytest.mark.unit
def test_preview_live_enabled_calls_loader(monkeypatch: pytest.MonkeyPatch) -> None:
    from kortravelmap.api.routers import ops_datasets as mod

    async def _loader(_settings: Any, params: dict[str, str]) -> list[dict[str, Any]]:
        assert params == {"nx": "60"}
        return [{"metric_key": "temperature_c", "value": 21.5}]

    monkeypatch.setattr(mod, "find_live_loader", lambda *_a: _loader)

    response = _live_client().post(
        "/v1/ops/datasets/python-kma-api/kma_short_forecast/preview?source=live&nx=60"
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["source"] == "live"
    assert data["items"] == [{"metric_key": "temperature_c", "value": 21.5}]


@pytest.mark.unit
def test_preview_live_missing_key_maps_503(monkeypatch: pytest.MonkeyPatch) -> None:
    from kortravelmap.api.etl_live import LiveLoaderError
    from kortravelmap.api.routers import ops_datasets as mod

    async def _loader(_settings: Any, _params: dict[str, str]) -> list[dict[str, Any]]:
        raise LiveLoaderError("KMA_SERVICE_KEY 미설정 (.env 확인).")

    monkeypatch.setattr(mod, "find_live_loader", lambda *_a: _loader)

    response = _live_client().post(
        "/v1/ops/datasets/python-kma-api/kma_short_forecast/preview?source=live"
    )

    assert response.status_code == 503


@pytest.mark.unit
def test_preview_live_provider_failure_maps_502(monkeypatch: pytest.MonkeyPatch) -> None:
    from kortravelmap.api.etl_live import LiveLoaderError
    from kortravelmap.api.routers import ops_datasets as mod

    async def _loader(_settings: Any, _params: dict[str, str]) -> list[dict[str, Any]]:
        raise LiveLoaderError("provider 5xx")

    monkeypatch.setattr(mod, "find_live_loader", lambda *_a: _loader)

    response = _live_client().post(
        "/v1/ops/datasets/python-kma-api/kma_short_forecast/preview?source=live"
    )

    assert response.status_code == 502


@pytest.mark.unit
def test_preview_live_unwired_dataset_501(monkeypatch: pytest.MonkeyPatch) -> None:
    from kortravelmap.api.routers import ops_datasets as mod

    monkeypatch.setattr(mod, "find_live_loader", lambda *_a: None)

    response = _live_client().post(
        "/v1/ops/datasets/python-mois-api/mois_license_features_bulk/preview?source=live"
    )

    assert response.status_code == 501
