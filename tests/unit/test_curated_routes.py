"""curated REST 라우터 app mount 단위 테스트."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, NoReturn
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from kortravelmap.api.app import create_app
from kortravelmap.api.curated_public_schema import (
    PublicCuratedAreaFeatureView,
    PublicCuratedEventFeatureView,
    PublicCuratedNoticeFeatureView,
    PublicCuratedPlaceFeatureView,
    PublicCuratedPriceFeatureView,
    PublicCuratedRouteFeatureView,
    PublicCuratedWeatherFeatureView,
)
from kortravelmap.api.db import get_session
from kortravelmap.api.routers import curated
from kortravelmap.api.settings import ApiSettings
from pydantic import SecretStr

from kortravelmap.infra.curated_repo import (
    CuratedFeature,
    CuratedFeaturePage,
    CuratedSourceRule,
)
from kortravelmap.settings import KorTravelMapSettings

pytestmark = pytest.mark.unit

_FEATURE_UUID = "99999999-9999-4999-8999-999999999999"


def _raw_curated_feature() -> CuratedFeature:
    now = datetime(2026, 7, 19, tzinfo=UTC)
    return CuratedFeature(
        curated_feature_id="11111111-1111-4111-8111-111111111111",
        theme_id="22222222-2222-4222-8222-222222222222",
        theme_slug="public-raw-boundary",
        theme_name="공개 raw 경계",
        theme_group="test",
        feature_id="feature:public-curated",
        feature_uuid=_FEATURE_UUID,
        feature_name="공개 큐레이션 장소",
        feature_category="01070100",
        feature_kind="place",
        lon=126.978,
        lat=37.566,
        sido_code="11",
        sigungu_code="11110",
        legal_dong_code="1111010100",
        address={
            "road": "서울특별시 공개로 1",
            "legal": "서울특별시 공개동 1",
            "zipcode": "03172",
            "sido_name": "서울특별시",
            "bjd_code": "1111010100",
            "road_address_management_no": "RAW_ADDRESS_MANAGEMENT_NO",
            "unknown_address": "RAW_ADDRESS_SENTINEL",
        },
        detail={
            "feature_id": "feature:public-curated",
            "place_kind": "museum",
            "phones": [
                "02-0000-0000",
                {"raw": "RAW_PHONE_OBJECT"},
                "RAW_PHONE_SENTINEL",
            ],
            "reviews_link": {
                "naver": "https://map.naver.com/example",
                "raw_provider": "https://raw.example.test/review",
            },
            "business_hours": {
                "timezone": "Asia/Seoul",
                "open_now": True,
                "periods": [
                    {
                        "open": {"day": 1, "time": "0900", "raw": "RAW_OPEN"},
                        "close": {"day": 1, "time": "1800"},
                        "raw": "RAW_PERIOD",
                    }
                ],
                "weekday_text": ["RAW_WEEKDAY_TEXT"],
                "raw": "RAW_BUSINESS_HOURS",
            },
            "facility_info": {
                "wheelchair": True,
                "description": "공개 장소 설명",
                "gemini_enriched_description": "검수된 공개 설명",
                "category_label": "박물관",
                "youtube_video_id": "video-raw-1",
                "youtube_video_url": "https://youtube.example.test/raw",
                "youtube_video_title": "RAW_VIDEO_TITLE",
                "youtube_channel_id": "RAW_CHANNEL_ID",
                "youtube_channel_title": "RAW_CHANNEL_TITLE",
                "youtube_playlist_id": "RAW_PLAYLIST_ID",
                "youtube_playlist_title": "RAW_PLAYLIST_TITLE",
                "youtube_source_type": "RAW_SOURCE_TYPE",
                "youtube_source_value": "RAW_SOURCE_VALUE",
                "youtube_source_title": "RAW_SOURCE_TITLE",
                "youtube_source_search_query": "RAW_SEARCH_QUERY",
                "youtube_corrected_search_query": "RAW_CORRECTED_QUERY",
                "timestamp_start": "00:03:12",
                "timestamp_end": "00:03:41",
                "transcript_excerpt": "RAW_TRANSCRIPT_EXCERPT",
                "gemini_url_evidence": "RAW_GEMINI_EVIDENCE",
                "confidence_score": 86,
                "source_record_key": "RAW_FACILITY_SOURCE_KEY",
                "unknown_nested": {"sentinel": "RAW_FACILITY_SENTINEL"},
            },
            "payload": {
                "sentinel": "RAW_DETAIL_PAYLOAD",
                "source_record_key": "RAW_NESTED_SOURCE_RECORD_KEY",
                "raw_payload_hash": "RAW_NESTED_HASH",
            },
            "raw_data": {"sentinel": "RAW_DETAIL_ROOT"},
        },
        source_id="33333333-3333-4333-8333-333333333333",
        provider_dataset_id=101,
        provider="raw-provider-internal",
        dataset_key="raw-dataset-internal",
        source_name="공개 출처명",
        source_url="https://example.test/source",
        source_record_key="RAW_TOP_LEVEL_SOURCE_RECORD_KEY",
        curation_status="curated",
        selection_origin="source_rule",
        selected_by="RAW_ADMIN_ACTOR",
        selected_at=now,
        rejected_by=None,
        rejected_at=None,
        rejection_reason=None,
        rank_score=99.0,
        display_title="공개 제목",
        display_summary="공개 요약",
        curation_relation="nearby_option",
        reuse_policy="allowed",
        content_version=3,
        metadata={"raw_external_id": "RAW_METADATA_ID"},
        created_at=now,
        updated_at=now,
        archived_at=None,
    )


def _nested_keys(value: object) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            nested_key
            for nested_value in value.values()
            for nested_key in _nested_keys(nested_value)
        }
    if isinstance(value, list):
        return {
            nested_key
            for nested_value in value
            for nested_key in _nested_keys(nested_value)
        }
    return set()


def test_curated_routes_are_in_openapi() -> None:
    paths = create_app().openapi()["paths"]

    assert "/v1/curated-themes" in paths
    assert "/v1/curated-sources" in paths
    assert "/v1/curated-features" in paths
    assert "/v1/curated-features/{curated_feature_id}" in paths
    assert "/v1/curated-features/{curated_feature_id}/detail-snapshot" not in paths
    assert "/v1/admin/features/curated/{curated_feature_id}/detail-snapshot" in paths
    assert "/v1/admin/features/curated/{curated_feature_id}/select" in paths
    assert "/v1/admin/curated-features" not in paths
    assert "/v1/admin/curated-features/{curated_feature_id}/select" not in paths
    assert "/v1/admin/curated-source-rules/{rule_id}/apply" in paths
    assert {"get", "patch", "delete"}.issubset(
        paths["/v1/admin/curated-source-rules/{rule_id}"]
    )


class _ForbiddenSession:
    """건드리면 실패하는 세션 stub — keyless 거부가 DB에 닿지 않음을 강제한다.

    ``require_public_api_key``는 ``get_session``을 sub-dependency로 받지만,
    헤더가 없는 요청은 활성 key hash 조회 이전에 401로 끊긴다. T-VN-34가
    ``KorTravelMapSettings.pg_dsn`` 기본값을 없앤 뒤로는 세션을 override하지
    않으면 dependency 해석이 ``KOR_TRAVEL_MAP_PG_DSN``을 요구하다 RuntimeError
    로 끝나 401 대신 500이 났다. 여기서 stub을 주입해 (1) DSN 없이도 게이트를
    검증하고 (2) 거부 경로가 세션을 쓰기 시작하면 즉시 드러나게 한다.
    """

    def __getattr__(self, name: str) -> NoReturn:
        raise AssertionError(f"keyless 거부 경로가 DB 세션을 사용했다: session.{name}")


async def _forbidden_session() -> AsyncIterator[_ForbiddenSession]:
    yield _ForbiddenSession()


@pytest.mark.parametrize(
    "path",
    [
        "/v1/curated-features",
        "/v1/curated-features/11111111-1111-4111-8111-111111111111",
        "/v1/curated-sources",
        "/v1/curated-themes",
    ],
)
def test_public_curated_routes_reject_keyless_requests(path: str) -> None:
    app = create_app(
        ApiSettings(
            _env_file=None,
            public_api_key_required=True,
            vworld_api_key=SecretStr("public-key-for-curated-route-test"),
        )
    )
    app.dependency_overrides[get_session] = _forbidden_session
    response = TestClient(app).get(path)
    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["code"] == "UNAUTHORIZED"


def test_curated_source_rule_view_accepts_detail_selector() -> None:
    now = datetime(2026, 7, 12, tzinfo=UTC)
    row = CuratedSourceRule(
        rule_id="11111111-1111-1111-1111-111111111111",
        theme_id="22222222-2222-2222-2222-222222222222",
        theme_slug="youtube-food",
        source_id="33333333-3333-3333-3333-333333333333",
        provider_dataset_id=101,
        provider="kor-travel-concierge-youtube",
        dataset_key="youtube_place_candidates",
        place_kind="youtube_place_candidate",
        category=None,
        region_scope={},
        detail_selector={"path": ["payload", "channel_id"], "value": "channel-A"},
        default_action="curated",
        priority=10,
        enabled=True,
        metadata={},
        created_at=now,
        updated_at=now,
    )

    view = curated._rule_view(row)

    assert view.detail_selector == {
        "path": ["payload", "channel_id"],
        "value": "channel-A",
    }
    assert view.row_revision == "1"


class _RuleApiSession:
    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield

    async def execute(self, statement: object) -> None:
        assert str(statement) == "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"


def _rule_api_row(*, revision: int, archived: bool = False) -> CuratedSourceRule:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    return CuratedSourceRule(
        rule_id="11111111-1111-4111-8111-111111111111",
        theme_id="22222222-2222-4222-8222-222222222222",
        theme_slug="rule-api",
        source_id="33333333-3333-4333-8333-333333333333",
        provider_dataset_id=101,
        provider="rule-api-provider",
        dataset_key="rule-api-dataset",
        place_kind=None,
        category=None,
        region_scope={},
        detail_selector=None,
        default_action="candidate",
        priority=0,
        enabled=not archived,
        metadata={},
        created_at=now,
        updated_at=now,
        row_revision=revision,
        archived_at=now if archived else None,
    )


def test_retained_rule_http_commands_use_strong_etag_and_typed_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service

    rows = {
        3: _rule_api_row(revision=3),
        4: _rule_api_row(revision=4),
        5: _rule_api_row(revision=5, archived=True),
    }
    get_rule = AsyncMock(return_value=rows[3])
    create_rule = AsyncMock(return_value=rows[3])
    patch_rule = AsyncMock(return_value=rows[4])
    archive_rule = AsyncMock(return_value=rows[5])
    monkeypatch.setattr(curated.curated_repo, "get_curated_source_rule", get_rule)
    monkeypatch.setattr(
        curated.curated_repo, "create_curated_source_rule_command", create_rule
    )
    monkeypatch.setattr(
        curated.curated_repo, "patch_curated_source_rule_command", patch_rule
    )
    monkeypatch.setattr(
        curated.curated_repo, "archive_curated_source_rule_command", archive_rule
    )

    async def _begin_command(
        _session: object,
        *,
        actor: str,
        operation: str,
        idempotency_key: object,
        payload: object,
    ) -> domain_command_service.DomainCommandHandle:
        del payload
        return domain_command_service.DomainCommandHandle(
            command_id=701,
            actor=actor,
            operation=operation,
            idempotency_key=str(idempotency_key),
            request_fingerprint="a" * 64,
        )

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _begin_command)
    monkeypatch.setattr(
        domain_command_service, "complete_domain_command", AsyncMock()
    )
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )

    async def _session() -> AsyncIterator[_RuleApiSession]:
        yield _RuleApiSession()

    app.dependency_overrides[get_session] = _session
    client = TestClient(app)
    rule_id = rows[3].rule_id
    key_prefix = "95000000-0000-4000-8000-00000000000"

    fetched = client.get(f"/v1/admin/curated-source-rules/{rule_id}")
    created = client.post(
        "/v1/admin/curated-source-rules",
        json={"theme_id": rows[3].theme_id, "source_id": rows[3].source_id},
        headers={"Idempotency-Key": f"{key_prefix}1"},
    )
    missing = client.patch(
        f"/v1/admin/curated-source-rules/{rule_id}",
        json={"priority": 9},
        headers={"Idempotency-Key": f"{key_prefix}2"},
    )
    patched = client.patch(
        f"/v1/admin/curated-source-rules/{rule_id}",
        json={"priority": 9},
        headers={
            "Idempotency-Key": f"{key_prefix}3",
            "If-Match": '"3"',
        },
    )
    archived = client.request(
        "DELETE",
        f"/v1/admin/curated-source-rules/{rule_id}",
        json={"reason_code": "operator_retired"},
        headers={
            "Idempotency-Key": f"{key_prefix}4",
            "If-Match": '"4"',
        },
    )

    assert (fetched.status_code, fetched.headers["etag"]) == (200, '"3"')
    assert fetched.json()["data"]["row_revision"] == "3"
    assert (created.status_code, created.headers["etag"]) == (201, '"3"')
    assert missing.status_code == 428
    assert (patched.status_code, patched.headers["etag"]) == (200, '"4"')
    assert (archived.status_code, archived.headers["etag"]) == (200, '"5"')
    assert archived.json()["data"]["archived_at"] is not None
    assert create_rule.await_args.kwargs["command_id"] == 701
    assert create_rule.await_args.kwargs["principal"] == "local-dev"
    assert patch_rule.await_args.kwargs["expected_revision"] == 3
    assert patch_rule.await_args.kwargs["updates"] == {"priority": 9}
    assert patch_rule.await_count == 1
    assert archive_rule.await_args.kwargs["expected_revision"] == 4
    assert archive_rule.await_args.kwargs["reason_code"] == "operator_retired"


@pytest.mark.parametrize(
    ("path", "method", "payload"),
    [
        (
            "/v1/admin/curated-source-rules/not-a-uuid",
            "GET",
            None,
        ),
        (
            "/v1/admin/curated-source-rules/11111111-1111-4111-8111-111111111111",
            "PATCH",
            {"priority": None},
        ),
        (
            "/v1/admin/curated-source-rules/11111111-1111-4111-8111-111111111111",
            "PATCH",
            {"enabled": None},
        ),
    ],
)
def test_retained_rule_http_rejects_malformed_identifiers_and_nulls(
    path: str,
    method: str,
    payload: dict[str, object] | None,
) -> None:
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )
    client = TestClient(app)
    headers = {
        "Idempotency-Key": "96000000-0000-4000-8000-000000000001",
        "If-Match": '"1"',
    }
    response = client.request(method, path, json=payload, headers=headers)
    assert response.status_code == 422


def test_public_curated_list_and_detail_strip_raw_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """#765: 공개 list/detail은 같은 fail-closed allowlist를 사용한다."""

    row = _raw_curated_feature()

    async def _list(_session: object, **kwargs: Any) -> CuratedFeaturePage:
        assert kwargs["public_only"] is True
        assert {"theme_id", "source_id", "provider", "dataset_key"}.isdisjoint(kwargs)
        return CuratedFeaturePage(items=(row,), next_cursor=None)

    async def _get(_session: object, **kwargs: Any) -> CuratedFeature:
        assert kwargs["public_only"] is True
        return row

    monkeypatch.setattr(curated.curated_repo, "list_curated_features", _list)
    monkeypatch.setattr(curated.curated_repo, "get_curated_feature", _get)

    app = create_app(
        ApiSettings(public_api_key_required=False, vworld_api_key=None)
    )

    async def _session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = _session
    client = TestClient(app)

    listed = client.get("/v1/curated-features")
    detailed = client.get(f"/v1/curated-features/{row.curated_feature_id}")

    assert listed.status_code == 200
    assert detailed.status_code == 200
    list_item = listed.json()["data"]["items"][0]
    detail_item = detailed.json()["data"]
    assert list_item == detail_item
    assert detail_item["feature_kind"] == "place"
    # T-VN-32C PR-2 — 공개 응답의 feature 참조 값은 UUID 정본이다.
    assert detail_item["feature_id"] == _FEATURE_UUID
    assert detail_item["address"] == {
        "road": "서울특별시 공개로 1",
        "legal": "서울특별시 공개동 1",
        "zipcode": "03172",
        "sido_name": "서울특별시",
    }
    assert detail_item["detail"] == {
        "feature_id": _FEATURE_UUID,
        "place_kind": "museum",
        "phones": ["02-0000-0000"],
        "reviews_link": {"naver": "https://map.naver.com/example"},
        "business_hours": {
            "timezone": "Asia/Seoul",
            "open_now": True,
            "periods": [
                {
                    "open": {"day": 1, "time": "0900"},
                    "close": {"day": 1, "time": "1800"},
                }
            ],
            "special_days": [],
        },
        "facility_info": {
            "description": "공개 장소 설명",
            "gemini_enriched_description": "검수된 공개 설명",
            "category_label": "박물관",
            "wheelchair": True,
        },
    }
    assert {
        "payload",
        "raw",
        "raw_data",
        "raw_provider",
        "raw_payload_hash",
        "source_record_key",
        "source_id",
        "metadata",
        "selected_by",
        "road_address_management_no",
        "unknown_address",
        "unknown_nested",
        "weekday_text",
        "youtube_video_id",
        "youtube_video_url",
        "youtube_video_title",
        "youtube_channel_id",
        "youtube_channel_title",
        "youtube_playlist_id",
        "youtube_playlist_title",
        "youtube_source_type",
        "youtube_source_value",
        "youtube_source_title",
        "youtube_source_search_query",
        "youtube_corrected_search_query",
        "timestamp_start",
        "timestamp_end",
        "transcript_excerpt",
        "gemini_url_evidence",
        "confidence_score",
    }.isdisjoint(_nested_keys(detail_item))
    serialized = json.dumps(detail_item, ensure_ascii=False)
    for raw_value in (
        "RAW_PHONE_OBJECT",
        "RAW_PHONE_SENTINEL",
        "RAW_ADDRESS_SENTINEL",
        "RAW_BUSINESS_HOURS",
        "video-raw-1",
        "RAW_VIDEO_TITLE",
        "RAW_CHANNEL_ID",
        "RAW_PLAYLIST_ID",
        "RAW_TRANSCRIPT_EXCERPT",
        "RAW_GEMINI_EVIDENCE",
        "RAW_FACILITY_SENTINEL",
    ):
        assert raw_value not in serialized

    # 같은 repository row의 admin/operator projection은 감사 원문을 그대로 유지한다.
    admin_item = curated._feature_view(row).model_dump(mode="json")
    assert admin_item["source_record_key"] == "RAW_TOP_LEVEL_SOURCE_RECORD_KEY"
    assert admin_item["detail"]["payload"]["sentinel"] == "RAW_DETAIL_PAYLOAD"
    assert admin_item["detail"]["facility_info"]["youtube_video_id"] == "video-raw-1"
    assert admin_item["metadata"]["raw_external_id"] == "RAW_METADATA_ID"


@pytest.mark.parametrize(
    ("feature_kind", "view_type"),
    [
        ("place", PublicCuratedPlaceFeatureView),
        ("event", PublicCuratedEventFeatureView),
        ("notice", PublicCuratedNoticeFeatureView),
        ("area", PublicCuratedAreaFeatureView),
        ("route", PublicCuratedRouteFeatureView),
        ("price", PublicCuratedPriceFeatureView),
        ("weather", PublicCuratedWeatherFeatureView),
    ],
)
def test_public_curated_projection_uses_feature_kind_discriminator(
    feature_kind: str,
    view_type: type[object],
) -> None:
    row = replace(_raw_curated_feature(), feature_kind=feature_kind)

    view = curated._public_feature_view(row)

    assert view is not None
    assert isinstance(view.root, view_type)
    assert view.root.feature_kind == feature_kind
    assert view.root.feature_id == _FEATURE_UUID


def test_public_curated_projection_rejects_unknown_kind() -> None:
    row = replace(_raw_curated_feature(), feature_kind="internal-experiment")

    assert curated._public_feature_view(row) is None


def test_public_curated_routes_hide_unknown_kind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = replace(_raw_curated_feature(), feature_kind="internal-experiment")

    async def _list(_session: object, **_kwargs: Any) -> CuratedFeaturePage:
        return CuratedFeaturePage(items=(row,), next_cursor=None)

    async def _get(_session: object, **_kwargs: Any) -> CuratedFeature:
        return row

    monkeypatch.setattr(curated.curated_repo, "list_curated_features", _list)
    monkeypatch.setattr(curated.curated_repo, "get_curated_feature", _get)
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))

    async def _session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = _session
    client = TestClient(app)

    listed = client.get("/v1/curated-features")
    detailed = client.get(f"/v1/curated-features/{row.curated_feature_id}")

    assert listed.status_code == 200
    assert listed.json()["data"]["items"] == []
    assert detailed.status_code == 404


def test_public_curated_routes_fail_closed_on_malformed_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _raw_curated_feature()
    malformed_detail = {
        **base.detail,
        "reviews_link": {
            "naver": "https://example.test:99999/review",
        },
        "facility_info": {
            "description": "URL 오류와 무관한 공개 설명",
            "homepage_url": "https://example.test:99999/home",
            "image_url": "https://[malformed-ipv6",
        },
    }
    row = replace(
        base,
        source_url="https://[malformed-ipv6",
        detail=malformed_detail,
    )

    async def _list(_session: object, **_kwargs: Any) -> CuratedFeaturePage:
        return CuratedFeaturePage(items=(row,), next_cursor=None)

    async def _get(_session: object, **_kwargs: Any) -> CuratedFeature:
        return row

    monkeypatch.setattr(curated.curated_repo, "list_curated_features", _list)
    monkeypatch.setattr(curated.curated_repo, "get_curated_feature", _get)
    app = create_app(ApiSettings(public_api_key_required=False, vworld_api_key=None))

    async def _session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = _session
    client = TestClient(app)

    listed = client.get("/v1/curated-features")
    detailed = client.get(f"/v1/curated-features/{row.curated_feature_id}")

    assert listed.status_code == 200
    assert detailed.status_code == 200
    list_item = listed.json()["data"]["items"][0]
    detail_item = detailed.json()["data"]
    assert list_item == detail_item
    assert "source_url" not in detail_item
    assert detail_item["detail"]["reviews_link"] == {}
    assert detail_item["detail"]["facility_info"] == {
        "description": "URL 오류와 무관한 공개 설명"
    }


class _FakePlaceSearchClient:
    calls: list[tuple[str, str, dict[str, Any]]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> _FakePlaceSearchClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append(("GET", url, kwargs))
        request = httpx.Request("GET", url)
        if url == curated.KAKAO_LOCAL_KEYWORD_URL:
            return httpx.Response(
                200,
                json={
                    "documents": [
                        {
                            "place_name": "카카오 장소",
                            "address_name": "서울 종로구 세종로",
                            "road_address_name": "서울 종로구 사직로 161",
                            "x": "126.976896",
                            "y": "37.579553",
                            "category_name": "여행 > 관광명소",
                        }
                    ]
                },
                request=request,
            )
        if url == curated.NAVER_LOCAL_SEARCH_URL:
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "title": "<b>네이버 장소</b>",
                            "address": "서울 종로구 세종로",
                            "roadAddress": "서울 종로구 사직로 161",
                            "mapx": "1269768960",
                            "mapy": "375795530",
                            "category": "여행>관광명소",
                        }
                    ]
                },
                request=request,
            )
        raise AssertionError(f"unexpected GET {url}")

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append(("POST", url, kwargs))
        request = httpx.Request("POST", url)
        if url == curated.GOOGLE_PLACES_TEXT_SEARCH_URL:
            return httpx.Response(
                200,
                json={
                    "places": [
                        {
                            "displayName": {"text": "구글 장소"},
                            "formattedAddress": "서울 종로구 사직로 161",
                            "location": {
                                "latitude": 37.579553,
                                "longitude": 126.976896,
                            },
                            "primaryTypeDisplayName": {"text": "관광명소"},
                        }
                    ]
                },
                request=request,
            )
        raise AssertionError(f"unexpected POST {url}")


@pytest.mark.asyncio
async def test_curated_place_search_calls_external_providers_directly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakePlaceSearchClient.calls = []
    monkeypatch.setattr(curated.httpx, "AsyncClient", _FakePlaceSearchClient)
    monkeypatch.setattr(
        curated,
        "KorTravelMapSettings",
        lambda: KorTravelMapSettings(
            _env_file=None,
            kakao_local_rest_api_key=SecretStr("kakao-key"),
            naver_search_client_id=SecretStr("naver-id"),
            naver_search_client_secret=SecretStr("naver-secret"),
            google_places_api_key=SecretStr("google-key"),
        ),
    )

    data = await curated._direct_place_search("경복궁")

    assert data.errors == {}
    assert data.kakao[0].name == "카카오 장소"
    assert data.naver[0].name == "네이버 장소"
    assert data.naver[0].longitude == pytest.approx(126.976896)
    assert data.naver[0].latitude == pytest.approx(37.579553)
    assert data.google[0].name == "구글 장소"
    assert data.google[0].category == "관광명소"

    call_urls = {url for _, url, _ in _FakePlaceSearchClient.calls}
    assert call_urls == {
        curated.KAKAO_LOCAL_KEYWORD_URL,
        curated.NAVER_LOCAL_SEARCH_URL,
        curated.GOOGLE_PLACES_TEXT_SEARCH_URL,
    }
    assert any(
        call_kwargs.get("headers", {}).get("Authorization") == "KakaoAK kakao-key"
        for _, _, call_kwargs in _FakePlaceSearchClient.calls
    )
    assert any(
        call_kwargs.get("headers", {}).get("X-Goog-Api-Key") == "google-key"
        for _, _, call_kwargs in _FakePlaceSearchClient.calls
    )


@pytest.mark.asyncio
async def test_curated_place_search_reports_missing_provider_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        curated,
        "KorTravelMapSettings",
        lambda: KorTravelMapSettings(_env_file=None),
    )

    data = await curated._direct_place_search("경복궁")

    assert data.google == []
    assert data.kakao == []
    assert data.naver == []
    assert set(data.errors) == {"google", "kakao", "naver"}
