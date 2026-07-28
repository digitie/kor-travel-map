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

import sys
from pathlib import Path
from typing import Any

import pytest

from kortravelmap.api.app import create_app
from kortravelmap.api.routers.curated import (
    CuratedFeatureDetailContentView,
    CuratedFeatureDetailSnapshotView,
    CuratedFeatureDetailSourceView,
    CuratedFeatureDetailThemeView,
    _snapshot_view,
)
from kortravelmap.api.route_policy import _iter_flattened_routes, _resolve_route
from kortravelmap.api.settings import ApiSettings

# 저장소 루트의 `tests/unit/test_curated_repo.py` fixture(_FakeSession/_feature_row)를 재사용해
# 실제 생성 payload로 view 정합을 검증한다(같은 생성부를 두 번 구현하지 않는다).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.unit.test_curated_repo import (  # noqa: E402
    _CURATED_ID,
    _FakeSession,
    _feature_row,
)

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
        "curation_status": {"type": "string", "required": True, "nullable": False},
        "reuse_policy": {"type": "string", "required": True, "nullable": False},
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
        "relation": {"type": "string", "required": True, "nullable": False},
        "sort_order": {"type": "integer", "required": True, "nullable": False},
        "day_index": {"type": "integer", "required": False, "nullable": True},
        "memo": {"type": "string", "required": False, "nullable": True},
        # 소비자가 통째로 저장만 하고 내부를 읽지 않으므로 opaque object로 유지한다.
        "feature_snapshot": {"type": "object", "required": True, "nullable": False},
        "source_record_key": {"type": "string", "required": False, "nullable": True},
    },
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


def test_admin_detail_snapshot_schemas_pin_required_types_and_nullability() -> None:
    """PinVi가 소비하는 admin snapshot payload를 필드 단위로 고정한다."""
    spec = _full_spec()
    for schema_name, fields in _SCHEMA_CONTRACTS.items():
        schema = spec["components"]["schemas"][schema_name]
        assert schema.get("additionalProperties") is False, schema_name
        # exact property 집합 — producer 쪽이므로 무단 노출·삭제를 모두 막는다.
        assert set(schema["properties"]) == set(fields), (
            schema_name,
            set(schema["properties"]) ^ set(fields),
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
    assert set(schema["properties"]) == (
        set(_SNAPSHOT_SCALARS) | set(_SNAPSHOT_REFS) | {"items"}
    )
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


def test_pinvi_compatibility_alias_route_stays_registered() -> None:
    """PinVi가 호출하는 alias 경로를 라우트 등록 수준에서 고정한다.

    alias는 `include_in_schema=False`라 OpenAPI에 나타나지 않는다. 스펙 기반 검사만으로는
    alias가 삭제돼도 잡히지 않고, 삭제되면 PinVi curated import가 404로 죽는다.
    """
    app = create_app(ApiSettings())
    # FastAPI 0.136+는 include_router 결과를 lazy `_IncludedRouter`로 감싸 `app.routes`에
    # 구체 route가 바로 보이지 않는다. route_policy가 쓰는 것과 같은 해석 helper를 재사용한다.
    paths = {
        _resolve_route(entry)[0] for entry in _iter_flattened_routes(app)
    }
    assert _SNAPSHOT_PATH in paths, "문서화된 detail-snapshot 경로가 사라졌다"
    assert _PINVI_ALIAS_PATH in paths, (
        "PinVi 호환 alias 경로가 사라졌다 — PinVi curated import가 404가 된다"
    )
    spec = _full_spec()
    assert _SNAPSHOT_PATH in spec["paths"]
    # alias는 의도적으로 스펙에서 감춘다(문서 표면 이중화를 피한다).
    assert _PINVI_ALIAS_PATH not in spec["paths"]


@pytest.mark.asyncio
async def test_snapshot_view_accepts_repository_payload() -> None:
    """생성부가 만든 실제 payload가 typed view를 그대로 통과하는지 확인한다.

    typed view는 `extra="forbid"`라 생성부가 key를 바꾸면 응답이 500으로 죽는다. 실제 생성
    경로(`curated_repo.get_curated_feature_detail_snapshot`)의 결과를 그대로 통과시켜
    생성부↔view drift를 fail-closed 이전에 잡는다.
    """
    from kortravelmap.infra import curated_repo

    snapshot = await curated_repo.get_curated_feature_detail_snapshot(
        _FakeSession([_feature_row()]),
        curated_feature_id=_CURATED_ID,
    )
    assert snapshot is not None

    view = _snapshot_view(snapshot)

    assert isinstance(view, CuratedFeatureDetailSnapshotView)
    assert isinstance(view.theme, CuratedFeatureDetailThemeView)
    assert isinstance(view.content, CuratedFeatureDetailContentView)
    assert isinstance(view.source, CuratedFeatureDetailSourceView)
    # 생성부 dict key 집합 == view 필드 집합 (한쪽만 늘어나면 실패)
    assert set(snapshot.theme) == set(CuratedFeatureDetailThemeView.model_fields)
    assert set(snapshot.content) == set(CuratedFeatureDetailContentView.model_fields)
    assert set(snapshot.source) == set(CuratedFeatureDetailSourceView.model_fields)
