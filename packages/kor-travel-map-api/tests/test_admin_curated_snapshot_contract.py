"""admin curated detail-snapshot 계약 게이트 (T-VN-H07D, #815).

PinVi 런타임(`apps/api/app/services/notice_plan.py` curated import)이 실제로 소비하는 표면은
공개 curated 표면이 아니라 admin `GET /v1/admin/curated-features/{id}/detail-snapshot`이다.
이 파일은 그 표면의 **세 가지 계약**을 고정한다.

1. **필드 계약** — `theme`/`content`/`source`는 과거 free-form ``dict[str, Any]``이라 OpenAPI에
   `{"type": "object"}`로만 노출됐다. typed view 전환 후 required/type/nullable을 생성 스펙
   기준으로 고정한다(소비자 PinVi가 읽는 plan-level 필드가 여기 들어 있다).
2. **PinVi 호환 alias 경로** — PinVi가 호출하는 경로는 `include_in_schema=False`라 스펙에
   나타나지 않는다. 스펙 기반 검사로는 alias가 사라져도 잡히지 않으므로 **라우트 등록 자체**를
   고정한다.
3. **생성부↔view 정합** — typed view는 `extra="forbid"`이므로 생성부가 key를 하나라도 바꾸면
   응답이 500이 된다. 실제 생성 payload를 view에 통과시켜 fail-closed 회귀를 막는다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

# 저장소 루트의 `tests/unit/test_curated_repo.py` fixture(_FakeSession/_feature_row)를 재사용해
# 실제 생성 payload로 view 정합을 검증한다(같은 생성부를 두 번 구현하지 않는다).
# 루트 `pyproject.toml`의 `pythonpath = ["."]`가 이미 저장소 루트를 올려주므로 별도
# `sys.path` 조작은 필요 없다. 이 세 심볼은 API 패키지 suite도 함께 쓰는 공유 fixture다.
from tests.unit.test_curated_repo import (
    _CURATED_ID,
    _FakeSession,
    _feature_row,
)

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.route_policy import _iter_flattened_routes, _resolve_route
from kortravelmap.api.routers.curated import (
    CuratedFeatureDetailContentView,
    CuratedFeatureDetailSnapshotView,
    CuratedFeatureDetailSourceView,
    CuratedFeatureDetailThemeView,
    _snapshot_view,
)
from kortravelmap.api.settings import ApiSettings

pytestmark = pytest.mark.unit

_SNAPSHOT_PATH = "/v1/admin/features/curated/{curated_feature_id}/detail-snapshot"
# PinVi `clients/kor_travel_map_admin.py::get_curated_detail_snapshot`가 호출하는 실제 경로.
_PINVI_ALIAS_PATH = "/v1/admin/curated-features/{curated_feature_id}/detail-snapshot"

# 소비자(PinVi)가 읽는 필드 → `services/notice_plan.py`
#   content: title/category/summary/destination_name/region_code
#   source : source_name/provider
#   theme  : theme_slug
#   item   : curated_feature_item_id/day_index/sort_order/feature_id/memo/feature_snapshot
_SCHEMA_CONTRACTS: dict[str, dict[str, dict[str, Any]]] = {
    "CuratedFeatureDetailThemeView": {
        "theme_slug": {"type": "string", "required": True, "nullable": False},
        "theme_name": {"type": "string", "required": True, "nullable": False},
    },
    "CuratedFeatureDetailContentView": {
        "title": {"type": "string", "required": True, "nullable": False},
        "summary": {"type": "string", "required": True, "nullable": True},
        "destination_name": {"type": "string", "required": True, "nullable": True},
        "region_code": {"type": "string", "required": True, "nullable": True},
        "category": {"type": "string", "required": True, "nullable": False},
        "curation_status": {
            "type": "string",
            "required": True,
            "nullable": False,
            "enum": ["candidate", "curated", "rejected", "archived"],
        },
        "reuse_policy": {
            "type": "string",
            "required": True,
            "nullable": False,
            "enum": ["allowed", "blocked", "manual_review"],
        },
    },
    "CuratedFeatureDetailSourceView": {
        "provider": {"type": "string", "required": True, "nullable": False},
        "dataset_key": {"type": "string", "required": True, "nullable": False},
        "source_name": {"type": "string", "required": True, "nullable": False},
        "source_url": {"type": "string", "required": True, "nullable": True},
    },
    "CuratedFeatureDetailItemView": {
        "curated_feature_item_id": {"type": "string", "required": True, "nullable": False},
        "feature_id": {"type": "string", "required": True, "nullable": False},
        "relation": {
            "type": "string",
            "required": True,
            "nullable": False,
            "enum": [
                "primary_stop",
                "food_stop",
                "cafe_stop",
                "bookstore_stop",
                "nearby_option",
                "accessibility_support",
                "pet_support",
                "family_support",
                "theme_area_anchor",
            ],
        },
        "sort_order": {"type": "integer", "required": True, "nullable": False},
        "day_index": {"type": "integer", "required": True, "nullable": True},
        "memo": {"type": "string", "required": True, "nullable": True},
        "source_record_key": {"type": "string", "required": True, "nullable": True},
        # feature_snapshot은 `$ref`라 아래 _ITEM_REFS가 대상 view를 고정한다.
    },
    # PinVi가 name/lon/lat/address를 직접 읽는다(admin_pois 추출기 + search.py SQL 술어).
    "CuratedFeatureDetailFeatureSnapshotView": {
        "feature_id": {"type": "string", "required": True, "nullable": False},
        "name": {"type": "string", "required": True, "nullable": False},
        "category": {"type": "string", "required": True, "nullable": False},
        "kind": {"type": "string", "required": True, "nullable": False},
        "lon": {"type": "number", "required": True, "nullable": True},
        "lat": {"type": "number", "required": True, "nullable": True},
        "sido_code": {"type": "string", "required": True, "nullable": True},
        "sigungu_code": {"type": "string", "required": True, "nullable": True},
        "legal_dong_code": {"type": "string", "required": True, "nullable": True},
        # provider 원본 투영이라 free-form을 유지한다.
        "address": {"type": "object", "required": True, "nullable": False},
        "detail": {"type": "object", "required": True, "nullable": False},
    },
}

_ITEM_REFS: dict[str, str] = {
    "feature_snapshot": "CuratedFeatureDetailFeatureSnapshotView",
}

# 생성부(`curated_repo._feature_detail_snapshot`)가 만드는 key 집합 — view 정의와 독립적으로
# 고정해 "생성부가 바뀌었는데 view도 같이 바뀌어 통과"하는 경로를 막는다.
_PRODUCER_KEYS: dict[str, set[str]] = {
    "theme": {"theme_slug", "theme_name"},
    "content": {
        "title",
        "summary",
        "destination_name",
        "region_code",
        "category",
        "curation_status",
        "reuse_policy",
    },
    "source": {"provider", "dataset_key", "source_name", "source_url"},
}

# snapshot 컨테이너: 스칼라 + 하위 view `$ref` 결합까지 고정한다.
_SNAPSHOT_SCALARS: dict[str, dict[str, Any]] = {
    "curated_feature_id": {"type": "string", "required": True, "nullable": False},
    "version": {"type": "integer", "required": True, "nullable": False},
    "etag": {"type": "string", "required": True, "nullable": False},
    "updated_at": {"type": "string", "format": "date-time", "required": True, "nullable": False},
}
_SNAPSHOT_REFS: dict[str, str] = {
    "theme": "CuratedFeatureDetailThemeView",
    "content": "CuratedFeatureDetailContentView",
    "source": "CuratedFeatureDetailSourceView",
}


def _full_spec() -> dict[str, Any]:
    return create_app(ApiSettings()).openapi()


def _resolve(prop: dict[str, Any], where: str) -> tuple[dict[str, Any], bool]:
    """nullable wrapper(list-form type / anyOf)를 벗겨 ``(schema, nullable)``."""
    declared = prop.get("type")
    if isinstance(declared, list):
        non_null = [t for t in declared if t != "null"]
        assert len(non_null) == 1, f"{where}: type이 union으로 넓어짐 — {declared!r}"
        return {**prop, "type": non_null[0]}, "null" in declared
    branches = prop.get("anyOf")
    if isinstance(branches, list):
        non_null = [b for b in branches if isinstance(b, dict) and b.get("type") != "null"]
        nullable = any(isinstance(b, dict) and b.get("type") == "null" for b in branches)
        assert len(non_null) == 1, f"{where}: anyOf가 union으로 넓어짐 — {prop!r}"
        return non_null[0], nullable
    return prop, False


def _assert_field(
    spec: dict[str, Any], schema_name: str, field: str, expected: dict[str, Any]
) -> None:
    schema = spec["components"]["schemas"][schema_name]
    where = f"{schema_name}.{field}"
    properties = schema["properties"]
    assert field in properties, f"{where}: 스펙에 없음"
    resolved, nullable = _resolve(properties[field], where)
    assert resolved.get("type") == expected["type"], (where, "type", resolved.get("type"))
    assert nullable is expected["nullable"], (where, "nullable", nullable)
    is_required = field in set(schema.get("required", []))
    assert is_required is expected["required"], (where, "required", is_required)
    if "format" in expected:
        assert resolved.get("format") == expected["format"], (
            where,
            "format",
            resolved.get("format"),
        )
    if "enum" in expected:
        assert resolved.get("enum") == expected["enum"], (
            where,
            "enum",
            resolved.get("enum"),
        )


def test_admin_detail_snapshot_schemas_pin_required_types_and_nullability() -> None:
    """PinVi가 소비하는 admin snapshot payload를 필드 단위로 고정한다."""
    spec = _full_spec()
    for schema_name, fields in _SCHEMA_CONTRACTS.items():
        schema = spec["components"]["schemas"][schema_name]
        assert schema.get("additionalProperties") is False, schema_name
        # exact property 집합 — producer 쪽이므로 무단 노출·삭제를 모두 막는다.
        # `$ref` property(item의 feature_snapshot)는 아래 컨테이너 테스트가 대상까지 고정한다.
        expected_properties = set(fields) | (
            set(_ITEM_REFS) if schema_name == "CuratedFeatureDetailItemView" else set()
        )
        assert set(schema["properties"]) == expected_properties, (
            schema_name,
            set(schema["properties"]) ^ expected_properties,
        )
        for field, expected in fields.items():
            _assert_field(spec, schema_name, field, expected)


def test_admin_detail_snapshot_container_binds_typed_payload_views() -> None:
    """snapshot 컨테이너가 typed view를 `$ref`로 물고 있는지 고정한다.

    `theme`/`content`/`source`가 다시 free-form object로 되돌아가면(=계약 소실) 여기서 깨진다.
    """
    spec = _full_spec()
    schema = spec["components"]["schemas"]["CuratedFeatureDetailSnapshotView"]
    assert schema.get("additionalProperties") is False
    assert set(schema["properties"]) == (set(_SNAPSHOT_SCALARS) | set(_SNAPSHOT_REFS) | {"items"})
    for field, expected in _SNAPSHOT_SCALARS.items():
        _assert_field(spec, "CuratedFeatureDetailSnapshotView", field, expected)
    for field, target in _SNAPSHOT_REFS.items():
        resolved, nullable = _resolve(
            schema["properties"][field], f"CuratedFeatureDetailSnapshotView.{field}"
        )
        assert str(resolved.get("$ref", "")).rsplit("/", 1)[-1] == target, (field, target)
        assert nullable is False, field
    items = schema["properties"]["items"]
    assert items.get("type") == "array"
    assert str(items["items"].get("$ref", "")).rsplit("/", 1)[-1] == "CuratedFeatureDetailItemView"

    # item → feature_snapshot 도 typed view로 물려 있어야 한다(다시 free-form이 되면 실패).
    item_schema = spec["components"]["schemas"]["CuratedFeatureDetailItemView"]
    assert set(item_schema["properties"]) == (
        set(_SCHEMA_CONTRACTS["CuratedFeatureDetailItemView"]) | set(_ITEM_REFS)
    )
    for field, target in _ITEM_REFS.items():
        resolved, nullable = _resolve(
            item_schema["properties"][field], f"CuratedFeatureDetailItemView.{field}"
        )
        assert str(resolved.get("$ref", "")).rsplit("/", 1)[-1] == target, (field, target)
        assert nullable is False, field
        assert field in set(item_schema.get("required", [])), field


def test_pinvi_compatibility_alias_route_stays_registered() -> None:
    """PinVi가 호출하는 alias 경로를 라우트 등록 수준에서 고정한다.

    alias는 `include_in_schema=False`라 OpenAPI에 나타나지 않는다. 스펙 기반 검사만으로는
    alias가 삭제돼도 잡히지 않고, 삭제되면 PinVi curated import가 404로 죽는다.
    """
    app = create_app(ApiSettings())
    # FastAPI 0.136+는 include_router 결과를 lazy `_IncludedRouter`로 감싸 `app.routes`에
    # 구체 route가 바로 보이지 않는다. route_policy가 쓰는 것과 같은 해석 helper를 재사용한다.
    paths = {_resolve_route(entry)[0] for entry in _iter_flattened_routes(app)}
    assert _SNAPSHOT_PATH in paths, "문서화된 detail-snapshot 경로가 사라졌다"
    assert _PINVI_ALIAS_PATH in paths, (
        "PinVi 호환 alias 경로가 사라졌다 — PinVi curated import가 404가 된다"
    )
    spec = _full_spec()
    assert _SNAPSHOT_PATH in spec["paths"]
    # alias는 의도적으로 스펙에서 감춘다(문서 표면 이중화를 피한다).
    assert _PINVI_ALIAS_PATH not in spec["paths"]


# nullable 분기를 모두 태우는 override — 기본 fixture는 모든 nullable 필드가 채워져 있어
# `summary`/`destination_name`/`region_code`/`source_url`/좌표 None 경로가 검증되지 않는다.
_ALL_NULL_OVERRIDES: dict[str, Any] = {
    "display_title": None,
    "display_summary": None,
    "metadata": {},
    "source_url": None,
    "sido_code": None,
    "sigungu_code": None,
    "legal_dong_code": None,
    "lon": None,
    "lat": None,
    "address": {},
}


@pytest.mark.asyncio
@pytest.mark.parametrize("overrides", [{}, _ALL_NULL_OVERRIDES], ids=["populated", "all-null"])
async def test_snapshot_view_accepts_repository_payload(overrides: dict[str, Any]) -> None:
    """생성부가 만든 실제 payload가 typed view를 그대로 통과하는지 확인한다.

    typed view는 `extra="forbid"`라 생성부가 key를 바꾸면 응답이 500으로 죽는다. 실제 생성
    경로(`curated_repo.get_curated_feature_detail_snapshot`)의 결과를 그대로 통과시켜
    생성부↔view drift를 fail-closed 이전에 잡는다. nullable 분기까지 태워, non-null로 잘못
    좁힌 필드가 운영 500이 되기 전에 잡는다.
    """
    from kortravelmap.infra import curated_repo

    snapshot = await curated_repo.get_curated_feature_detail_snapshot(
        _FakeSession([_feature_row(**overrides)]),
        curated_feature_id=_CURATED_ID,
    )
    assert snapshot is not None

    view = _snapshot_view(snapshot)

    assert isinstance(view, CuratedFeatureDetailSnapshotView)
    assert isinstance(view.theme, CuratedFeatureDetailThemeView)
    assert isinstance(view.content, CuratedFeatureDetailContentView)
    assert isinstance(view.source, CuratedFeatureDetailSourceView)
    # 생성부 key 집합을 **view와 독립적인 리터럴**로 고정한다. view와 비교하면
    # `_snapshot_view()` 호출이 이미 같은 것을 보장해 항상 참인 검사가 된다.
    assert set(snapshot.theme) == _PRODUCER_KEYS["theme"]
    assert set(snapshot.content) == _PRODUCER_KEYS["content"]
    assert set(snapshot.source) == _PRODUCER_KEYS["source"]


@pytest.mark.parametrize("path", [_SNAPSHOT_PATH, _PINVI_ALIAS_PATH], ids=["documented", "alias"])
@pytest.mark.parametrize("overrides", [{}, _ALL_NULL_OVERRIDES], ids=["populated", "all-null"])
def test_detail_snapshot_endpoint_serves_typed_payload(
    path: str, overrides: dict[str, Any]
) -> None:
    """실제 endpoint를 태워 응답 직렬화까지 검증한다(문서 경로 + PinVi alias 둘 다).

    스키마 핀과 생성부 정합만으로는 FastAPI `response_model` 재검증·envelope 직렬화 경로가
    검증되지 않는다. 이 PR이 바로 그 response model을 바꿨으므로 HTTP 수준에서 고정한다.
    """
    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )

    async def _session() -> AsyncIterator[object]:
        yield _FakeSession([_feature_row(**overrides)])

    app.dependency_overrides[get_session] = _session
    client = TestClient(app)

    response = client.get(path.replace("{curated_feature_id}", _CURATED_ID))

    assert response.status_code == 200, response.text
    body = response.json()
    data = body["data"]
    assert set(data["theme"]) == _PRODUCER_KEYS["theme"]
    assert set(data["content"]) == _PRODUCER_KEYS["content"]
    assert set(data["source"]) == _PRODUCER_KEYS["source"]
    assert set(data) == (set(_SNAPSHOT_SCALARS) | set(_SNAPSHOT_REFS) | {"items"})
    assert set(data["items"][0]) == (
        set(_SCHEMA_CONTRACTS["CuratedFeatureDetailItemView"]) | set(_ITEM_REFS)
    )
    assert set(data["items"][0]["feature_snapshot"]) == set(
        _SCHEMA_CONTRACTS["CuratedFeatureDetailFeatureSnapshotView"]
    )
    assert "meta" in body
