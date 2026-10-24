"""``/v1/ops/geo-releases`` 라우터 단위 테스트 (ADR-109 결정 8, T-GR-04)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.dto.geo_dataset import DatasetRef
from kortravelmap.infra import geo_release_repo
from kortravelmap.infra.feature_geocode_stamp_repo import GeoCoverage

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_read_snapshot_session, get_session
from kortravelmap.api.routers import ops_geo_releases
from kortravelmap.api.settings import ApiSettings

_NOW = datetime(2026, 10, 16, 12, 0, tzinfo=UTC)
_CURRENT = DatasetRef(
    version_token="dv1-" + "a" * 32,
    data_token="dd1-" + "1" * 32,
    activated_at=_NOW,
    reference_months={"juso": "202609"},
)
_API_ROOT = Path(__file__).resolve().parents[1]


class _FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *_exc: object) -> None:
        return None


class _FakeSession:
    def begin(self) -> _FakeTransaction:
        return _FakeTransaction()


def _plan(plan_id: int = 7, *, state: str = "planned") -> geo_release_repo.GeoReleasePlan:
    return geo_release_repo.GeoReleasePlan(
        plan_id=plan_id,
        geo_data_token="dd1-" + "1" * 32,
        plan_seq=1,
        geo_version_token="dv1-" + "a" * 32,
        activated_at=_NOW,
        reference_months={"juso": "202609"},
        state=state,
        residual_stale=None,
        sweep_started_at=None,
        observed_at=_NOW,
        completed_at=None,
        items=(
            geo_release_repo.GeoReleaseItem(
                plan_id=plan_id,
                position=1,
                operation_key="feature_place_knps_points_job",
                datasets=(
                    geo_release_repo.GeoReleaseDataset(
                        provider_dataset_id=54,
                        provider="python-knps-api",
                        dataset_key="knps_visitor_centers",
                    ),
                ),
                run_config={"resources": {}},
                attempt_seq=1,
                state="pending",
                state_reason=None,
                run_key=None,
                dagster_run_id=None,
                requested_at=None,
            ),
        ),
    )


_COVERAGE = GeoCoverage(
    total_provider_with_coord=10,
    stamped_current=6,
    stamped_other=2,
    unstamped=1,
    not_called_by_kind={"place": 1},
    excluded_by_skip=3,
    unstamped_non_provider=0,
)


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    app = create_app(ApiSettings())

    async def _fake_session() -> AsyncIterator[_FakeSession]:
        yield _FakeSession()

    async def _current() -> DatasetRef | None:
        return _CURRENT

    async def _coverage(_session: Any, _plan: Any) -> GeoCoverage:
        return _COVERAGE

    monkeypatch.setattr(ops_geo_releases, "_current_dataset", _current)
    monkeypatch.setattr(geo_release_repo, "plan_coverage", _coverage)
    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[get_read_snapshot_session] = _fake_session
    return TestClient(app)


_PATHS = {
    "/v1/ops/geo-releases": {"get"},
    "/v1/ops/geo-releases/detect": {"post"},
    "/v1/ops/geo-releases/{plan_id}": {"get"},
    "/v1/ops/geo-releases/{plan_id}/items/{position}/skip": {"post"},
    "/v1/ops/geo-releases/{plan_id}/replan": {"post"},
}


@pytest.mark.unit
def test_five_operations_are_mounted_on_the_admin_surface(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    mounted = {
        path: {method for method in item if method in {"get", "post", "put", "delete", "patch"}}
        for path, item in spec["paths"].items()
        if path.startswith("/v1/ops/geo-releases")
    }
    assert mounted == _PATHS
    # GET은 ops:read principal도, POST(동사)는 admin BFF만.
    assert spec["paths"]["/v1/ops/geo-releases"]["get"]["security"] != [{"AdminBFF": []}]
    for path, methods in _PATHS.items():
        if "post" in methods:
            assert spec["paths"][path]["post"]["security"] == [{"AdminBFF": []}]


@pytest.mark.unit
@pytest.mark.parametrize("filename", ["openapi.user.json", "openapi.service.json"])
def test_user_and_service_contracts_do_not_carry_the_geo_release_api(filename: str) -> None:
    """admin 프로필만 — 센서는 API를 치지 않으므로 user·service 계약에 둘 이유가 없다."""
    raw = (_API_ROOT / filename).read_bytes()
    # 바이트 불변은 openapi-drift CI(재생성 결과와 커밋 파일 비교)가 고정한다 — 여기서는 경로가
    # 들어가지 않았음만 본다.
    assert b"/v1/ops/geo-releases" not in raw


@pytest.mark.unit
def test_admin_contract_carries_the_five_operations() -> None:
    spec = json.loads((_API_ROOT / "openapi.json").read_text(encoding="utf-8"))
    for path, methods in _PATHS.items():
        assert methods <= set(spec["paths"].get(path, {})), path


@pytest.mark.unit
def test_detect_calls_the_single_plan_function(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """센서(``client.create_geo_release_plan``)와 ``/detect``가 같은 함수를 부른다."""
    calls: list[DatasetRef] = []

    async def _fake_plan(_session: Any, current: DatasetRef) -> Any:
        calls.append(current)
        return geo_release_repo.GeoReleasePlanOutcome(kind="created", plan=_plan())

    monkeypatch.setattr(geo_release_repo, "plan_geo_release", _fake_plan)
    response = client.post("/v1/ops/geo-releases/detect")

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["outcome"] == "created"
    item = data["plan"]["items"][0]
    assert item["datasets"][0]["dataset_key"] == "knps_visitor_centers"
    assert item["launch_blocked_reason"] is None
    assert data["current"]["reference_months"] == {"juso": "202609"}
    assert calls == [_CURRENT]
    # 라우터와 client는 모듈 속성으로 부른다(복사본 없음) — 같은 함수 identity.
    assert ops_geo_releases.geo_release_repo is geo_release_repo
    from kortravelmap import client as client_module

    assert client_module.geo_release_repo is geo_release_repo


@pytest.mark.unit
def test_detect_without_a_current_dataset_is_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _none() -> DatasetRef | None:
        return None

    monkeypatch.setattr(ops_geo_releases, "_current_dataset", _none)
    assert client.post("/v1/ops/geo-releases/detect").status_code == 503


@pytest.mark.unit
def test_list_reports_the_current_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _list(_session: Any, *, limit: int) -> tuple[Any, ...]:
        assert limit == 20
        return (_plan(state="baseline"),)

    async def _no_token() -> DatasetRef | None:
        return DatasetRef(version_token="dv1-" + "b" * 32)

    monkeypatch.setattr(geo_release_repo, "list_geo_release_plans", _list)
    body = client.get("/v1/ops/geo-releases").json()["data"]
    assert body["current_status"] == "ok"
    assert body["plans"][0]["state"] == "baseline"

    monkeypatch.setattr(ops_geo_releases, "_current_dataset", _no_token)
    assert client.get("/v1/ops/geo-releases").json()["data"]["current_status"] == "no_token"


@pytest.mark.unit
def test_detail_skip_and_replan_map_errors(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _get(_session: Any, plan_id: int) -> Any:
        return _plan(plan_id) if plan_id in (7, 8) else None

    async def _skip(_session: Any, plan_id: int, position: int) -> Any:
        if plan_id == 9:
            raise geo_release_repo.GeoReleaseNotFound("없다")
        raise geo_release_repo.GeoReleaseConflict("이미 끝난 항목")

    async def _replan(_session: Any, plan_id: int) -> Any:
        if plan_id == 9:
            raise geo_release_repo.GeoReleaseNotFound("없다")
        if plan_id == 6:
            raise geo_release_repo.GeoReleaseConflict("최신 토큰이 아니다")
        return _plan(8)

    monkeypatch.setattr(geo_release_repo, "get_geo_release_plan", _get)
    monkeypatch.setattr(geo_release_repo, "skip_item", _skip)
    monkeypatch.setattr(geo_release_repo, "replan", _replan)

    detail = client.get("/v1/ops/geo-releases/7")
    assert detail.status_code == 200
    assert detail.json()["data"]["coverage"]["excluded_by_skip"] == 3
    assert client.get("/v1/ops/geo-releases/9").status_code == 404
    assert client.post("/v1/ops/geo-releases/9/items/1/skip").status_code == 404
    assert client.post("/v1/ops/geo-releases/7/items/1/skip").status_code == 409
    assert client.post("/v1/ops/geo-releases/9/replan").status_code == 404
    assert client.post("/v1/ops/geo-releases/6/replan").status_code == 409
    assert client.post("/v1/ops/geo-releases/7/replan").status_code == 200
