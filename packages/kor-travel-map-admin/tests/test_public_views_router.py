"""``/v1/public/*`` 공개 view 라우터 단위 테스트 (T-222b)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient
from kortravelmap.infra import public_views_repo

from kortravelmap.admin.app import create_app
from kortravelmap.admin.settings import AdminSettings

pytestmark = pytest.mark.unit

_KST = timezone(timedelta(hours=9))
_UPDATED = datetime(2026, 6, 12, 9, 0, tzinfo=_KST)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(AdminSettings()))


async def _fake_session() -> AsyncIterator[Any]:
    yield object()


def _beach_row() -> public_views_repo.PublicBeachRow:
    return public_views_repo.PublicBeachRow(
        feature_id="f_beach_1",
        display_name="광안리 해수욕장",
        lon=129.118,
        lat=35.155,
        sido_code="26",
        sigungu_code="26110",
        legal_dong_code="2611010100",
        address={"road": "부산광역시 수영구 광안해변로", "legal": "부산 수영구 광안동"},
        detail={
            "place_kind": "beach",
            "phones": ["051-000-0000"],
            "facility_info": {
                "beach_kind": "일반",
                "beach_width_m": "25",
                "beach_length_m": 1400,
                "beach_material": "모래",
                "image_url": "https://example.test/beach.jpg",
            },
        },
        urls={"homepage": "https://example.test/beach"},
        source_raw_data={"beach_kind": "일반"},
        marker_icon="beach",
        marker_color="P-07",
        source_providers=("python-khoa-api",),
        updated_at=_UPDATED,
    )


def _festival_row() -> public_views_repo.PublicFestivalRow:
    return public_views_repo.PublicFestivalRow(
        feature_id="f_festival_1",
        festival_name="미래 봄꽃 축제",
        lon=126.9239,
        lat=37.5263,
        sido_code="11",
        sigungu_code="11560",
        legal_dong_code="1156010100",
        address={"road": "서울특별시 영등포구 여의공원로 120", "legal": "서울 영등포구"},
        detail={
            "event_kind": "festival",
            "starts_on": "2099-05-02",
            "ends_on": "2099-05-05",
            "venue_name": "여의도공원",
            "tel": "02-000-0000",
            "payload": {"organizer_name": "영등포구청", "provider_org_name": "서울시"},
        },
        urls={"homepage": "https://example.test/festival"},
        source_raw_data={
            "fstvl_co": "축제 상세",
            "auspc_instt_nm": "주최기관",
            "suprt_instt_nm": "후원기관",
            "reference_date": "2099-04-01",
        },
        marker_icon="star",
        marker_color="P-11",
        source_providers=("data.go.kr-standard",),
        updated_at=_UPDATED,
    )


def test_public_view_routes_mounted_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/v1/public/beaches" in spec["paths"]
    assert "/v1/public/beaches/map-markers" in spec["paths"]
    assert "/v1/public/beaches/{feature_id}" in spec["paths"]
    assert "/v1/public/festivals/monthly" in spec["paths"]
    assert "/v1/public/festivals/map-markers" in spec["paths"]
    assert "/v1/public/festivals/{feature_id}" in spec["paths"]
    schemas = spec["components"]["schemas"]
    assert "BeachPublicView" in schemas
    assert "FestivalPublicView" in schemas
    assert "PublicFestivalMonthlyResponse" in schemas


def test_public_view_routes_disabled_with_features_gate() -> None:
    disabled = TestClient(create_app(AdminSettings(features_routes_enabled=False)))
    assert disabled.get("/v1/public/beaches").status_code == 404
    assert disabled.get("/v1/public/festivals/monthly").status_code == 404


def test_list_public_beaches_maps_page(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.admin.db import get_session
    from kortravelmap.admin.routers import public_views as public_views_mod

    async def _list(_session: Any, **kwargs: Any) -> public_views_repo.PublicBeachPage:
        assert kwargs["sido_code"] == "26"
        assert kwargs["page_size"] == 10
        return public_views_repo.PublicBeachPage(items=(_beach_row(),), next_cursor="n")

    monkeypatch.setattr(
        public_views_mod.public_views_repo,
        "list_public_beaches",
        _list,
    )
    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get(
            "/v1/public/beaches",
            params={"sido_code": "26", "page_size": 10, "include_forecast": "true"},
        )
        assert r.status_code == 200
        body = r.json()
        item = body["data"]["items"][0]
        assert item["feature_id"] == "f_beach_1"
        assert item["road_address"] == "부산광역시 수영구 광안해변로"
        assert item["beach_width_m"] == 25.0
        assert item["beach_length_m"] == 1400.0
        assert item["source_providers"] == ["python-khoa-api"]
        assert body["meta"]["page"] == {
            "page_size": 10,
            "next_cursor": "n",
            "total": None,
        }
    finally:
        client.app.dependency_overrides.clear()


def test_public_beach_markers_reject_partial_bbox(client: TestClient) -> None:
    r = client.get("/v1/public/beaches/map-markers", params={"min_lon": 126})
    assert r.status_code == 422
    assert "bbox" in r.json()["detail"]


def test_public_festival_monthly_maps_items_and_months(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.admin.db import get_session
    from kortravelmap.admin.routers import public_views as public_views_mod

    async def _monthly(
        _session: Any,
        **kwargs: Any,
    ) -> public_views_repo.PublicFestivalPage:
        assert kwargs["month_start"] == date(2099, 5, 1)
        assert kwargs["month_end"] == date(2099, 5, 31)
        assert kwargs["include_months"] is True
        return public_views_repo.PublicFestivalPage(
            items=(_festival_row(),),
            months=(
                public_views_repo.PublicFestivalMonthSummary(
                    year=2099, month=4, count=1
                ),
                public_views_repo.PublicFestivalMonthSummary(
                    year=2099, month=5, count=2
                ),
            ),
            next_cursor=None,
        )

    monkeypatch.setattr(
        public_views_mod.public_views_repo,
        "list_public_festivals_monthly",
        _monthly,
    )
    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get(
            "/v1/public/festivals/monthly",
            params={"year": 2099, "month": 5, "page_size": 12},
        )
        assert r.status_code == 200
        body = r.json()
        item = body["data"]["items"][0]
        assert item["festival_name"] == "미래 봄꽃 축제"
        assert item["event_status"] == "scheduled"
        assert item["festival_content"] == "축제 상세"
        assert item["organizer_name"] == "영등포구청"
        assert item["auspc_instt_name"] == "주최기관"
        assert item["reference_date"] == "2099-04-01"
        assert body["data"]["months"] == [
            {"year": 2099, "month": 4, "count": 1},
            {"year": 2099, "month": 5, "count": 2},
        ]
    finally:
        client.app.dependency_overrides.clear()


def test_get_public_festival_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.admin.db import get_session
    from kortravelmap.admin.routers import public_views as public_views_mod

    async def _missing(_session: Any, *, feature_id: str) -> None:
        assert feature_id == "missing"
        return

    monkeypatch.setattr(public_views_mod.public_views_repo, "get_public_festival", _missing)
    client.app.dependency_overrides[get_session] = _fake_session
    try:
        r = client.get("/v1/public/festivals/missing")
        assert r.status_code == 404
    finally:
        client.app.dependency_overrides.clear()
