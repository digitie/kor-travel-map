"""``test_infra_feature_repo`` — ``feature_repo`` param 빌더 + 결과 집계 (DB 무관).

DB 적재 경로는 ``tests/integration/test_feature_repo_load.py``(testcontainers).
본 모듈은 ``Feature``/``SourceRecord``/``SourceLink`` DTO → bind params 변환과
``FeatureLoadResult`` 기본값만 단위 검증 (coord None / detail None 분기 포함).

T-VN-35(ADR-086) 이후 계약
--------------------------

core ``feature.features``에는 ``detail`` JSONB도 ``geom``도 없다(alembic 0086).
따라서 ``_feature_params``는 core 컬럼 바인딩만 만들고, kind별 값은
``feature_subtype.subtype_params``가 typed subtype 컬럼으로 매핑한다. notice
효력 종료 감산도 ``detail ->> 'valid_end_time'`` 문자열 파싱(+ 오염 방어용
``pg_input_is_valid`` cast)이 아니라 ``feature_notices.valid_end_time``
timestamptz 비교다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy.exc import DBAPIError

from kortravelmap.core.exceptions import (
    FeatureSearchCursorInvalidError,
    FeatureSearchCursorQueryMismatchError,
    FeatureSearchCursorTamperedError,
    FeatureSearchCursorVersionUnsupportedError,
)
from kortravelmap.dto import (
    Coordinate,
    Feature,
    PlaceDetail,
    SourceLink,
    SourceRecord,
)
from kortravelmap.dto._enums import (
    FeatureKind,
    FeatureLifecycleState,
    FeaturePublicationState,
    FeatureQualityState,
    SourceRole,
)
from kortravelmap.infra import feature_repo
from kortravelmap.infra.feature_repo import (
    FeatureLoadResult,
    FeatureSearchRow,
    NearbyFeatureRow,
    _feature_params,
    _provider_feature_payload,
    _source_link_params,
    _source_record_params,
)
from kortravelmap.infra.feature_subtype import subtype_params

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 5, 29, 9, 0, tzinfo=_KST)
_SEARCH_CURSOR_KEY = b"unit-test-feature-search-cursor-signing-key-0001"


def _place(coord: Coordinate | None, detail: PlaceDetail | None) -> Feature:
    return Feature(
        feature_id="place:abc123",
        kind=FeatureKind.PLACE,
        name="홍대 카페",
        category="02020101",
        coord=coord,
        marker_icon="cafe",
        marker_color="P-03",
        detail=detail,
        created_at=_NOW,
        updated_at=_NOW,
    )


def _provider_membership(
    *,
    entity_key: str = "entity:17",
    record_key: str = "record:17",
) -> feature_repo._ProviderSourceMembership:
    return feature_repo._ProviderSourceMembership(
        source_entity_key=entity_key,
        source_record_key=record_key,
    )


def test_feature_params_with_coord_and_detail() -> None:
    feature = _place(
        Coordinate(lon=Decimal("126.92"), lat=Decimal("37.55")),
        PlaceDetail(feature_id="place:abc123", place_kind="cafe"),
    )
    params = _feature_params(feature)

    assert params["feature_id"] == "place:abc123"
    assert params["kind"] == "place"
    assert params["lon"] == 126.92
    assert params["lat"] == 37.55
    # address/urls/raw_refs는 JSON 문자열 (CAST AS jsonb)
    assert isinstance(params["address"], str)
    assert json.loads(params["raw_refs"]) == []
    assert "lifecycle_state" not in params
    assert "publication_state" not in params
    assert "quality_state" not in params
    # T-VN-35: core에 detail 컬럼이 없으므로 core bind에도 없다.
    assert "detail" not in params


@pytest.mark.parametrize(
    ("lifecycle_state", "publication_state", "quality_state"),
    [
        (
            FeatureLifecycleState.ACTIVE,
            FeaturePublicationState.PUBLISHED,
            FeatureQualityState.VALID,
        ),
        (
            FeatureLifecycleState.ACTIVE,
            FeaturePublicationState.DRAFT,
            FeatureQualityState.QUARANTINED,
        ),
        (
            FeatureLifecycleState.RETIRED,
            FeaturePublicationState.SUPPRESSED,
            FeatureQualityState.VALID,
        ),
    ],
)
def test_provider_state_is_passed_once_to_tvn34_axes(
    lifecycle_state: FeatureLifecycleState,
    publication_state: FeaturePublicationState,
    quality_state: FeatureQualityState,
) -> None:
    """Provider conversion이 만든 3축은 repository에서 재해석하지 않는다."""
    feature = _place(None, None).model_copy(
        update={
            "lifecycle_state": lifecycle_state,
            "publication_state": publication_state,
            "quality_state": quality_state,
        }
    )

    actual = feature_repo._provider_feature_state(feature)

    assert (
        actual.lifecycle_state,
        actual.publication_state,
        actual.quality_state,
    ) == (lifecycle_state, publication_state, quality_state)


def test_provider_procedure_payload_excludes_legacy_state_columns() -> None:
    params = _feature_params(_place(None, None))

    payload = json.loads(_provider_feature_payload(params))

    assert "status" not in payload
    assert "deleted_at" not in payload
    assert "geom_wkt" not in payload
    assert "data_origin" not in payload
    assert "data_version" not in payload
    assert "created_at" not in payload
    assert "updated_at" not in payload
    assert payload["feature_id"] == "place:abc123"
    assert payload["address"] == json.loads(params["address"])
    assert payload["urls"] == json.loads(params["urls"])
    assert payload["raw_refs"] == []


def test_provider_state_context_is_dataset_derived_and_never_sends_principal() -> None:
    context = json.loads(
        feature_repo._provider_state_context(
            provider_dataset_id=17,
            reason_code="provider_reingest",
            source_membership=_provider_membership(),
        )
    )

    assert context == {
        "transition_kind": "provider_sync",
        "reason_code": "provider_reingest",
        "provider_dataset_id": 17,
        "source_entity_key": "entity:17",
        "source_record_key": "record:17",
    }


@pytest.mark.asyncio
async def test_provider_create_uses_procedure_and_omits_legacy_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Mappings:
        def __init__(self, row: dict[str, Any]) -> None:
            self._row = row

        def one(self) -> dict[str, Any]:
            return self._row

    class _Result:
        def __init__(self, row: dict[str, Any] | None = None) -> None:
            self._row = row

        def mappings(self) -> _Mappings:
            assert self._row is not None
            return _Mappings(self._row)

    class _Session:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []

        async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
            sql = str(statement)
            self.calls.append((sql, params))
            if "create_feature_with_initial_state" in sql:
                payload = json.loads(params["feature_payload"])
                assert "status" not in payload
                assert "deleted_at" not in payload
                assert json.loads(params["state_context"]) == {
                    "transition_kind": "provider_sync",
                    "reason_code": "provider_initial",
                    "provider_dataset_id": 17,
                    "source_entity_key": "entity:17",
                    "source_record_key": "record:17",
                }
                return _Result(
                    {
                        "o_inserted": True,
                        "o_feature_uuid": payload["feature_uuid"],
                    }
                )
            return _Result()

    async def _no_subtype(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(feature_repo, "_upsert_feature_subtype", _no_subtype)
    session = _Session()

    inserted = await feature_repo.upsert_feature(
        session,  # type: ignore[arg-type]
        _place(None, None),
        provider_dataset_id=17,
        source_membership=_provider_membership(),
    )

    assert inserted is True
    assert "CALL feature.create_feature_with_initial_state" in session.calls[0][0]


@pytest.mark.asyncio
async def test_existing_provider_refresh_uses_typed_field_patch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """whole-row user fence 대신 named provider field patch만 호출한다."""

    class _Mappings:
        def __init__(self, row: dict[str, Any] | None) -> None:
            self._row = row

        def one(self) -> dict[str, Any]:
            assert self._row is not None
            return self._row

        def one_or_none(self) -> dict[str, Any] | None:
            return self._row

    class _Result:
        def __init__(self, row: dict[str, Any] | None) -> None:
            self._row = row

        def mappings(self) -> _Mappings:
            return _Mappings(self._row)

    class _Session:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.feature_uuid: str | None = None

        async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
            sql = str(statement)
            self.calls.append(sql)
            if "create_feature_with_initial_state" in sql:
                self.feature_uuid = json.loads(params["feature_payload"])["feature_uuid"]
                return _Result(
                    {
                        "o_inserted": False,
                        "o_feature_uuid": self.feature_uuid,
                        "o_row_revision": 7,
                    }
                )
            if "apply_provider_feature_field_patch" in sql:
                return _Result(
                    {
                        "o_feature_id": feature.feature_id,
                        "o_row_revision": 8,
                        "o_applied_field_count": 25,
                    }
                )
            raise AssertionError(f"unexpected SQL: {sql}")

    async def _no_subtype(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("existing refresh must use the typed patch procedure")

    feature = _place(None, None)
    monkeypatch.setattr(feature_repo, "_upsert_feature_subtype", _no_subtype)
    session = _Session()

    inserted = await feature_repo.upsert_feature(
        session,  # type: ignore[arg-type]
        feature,
        provider_dataset_id=17,
        source_membership=_provider_membership(),
    )

    assert inserted is False
    assert any("apply_provider_feature_field_patch" in call for call in session.calls)
    assert not any("UPDATE feature.features AS f" in call for call in session.calls)
    assert not any("materialize_provider_feature_version" in call for call in session.calls)


@pytest.mark.asyncio
async def test_provider_reactivation_skips_preexisting_lifecycle_override() -> None:
    class _Session:
        async def execute(self, *_args: Any, **_kwargs: Any) -> None:
            raise AssertionError("override fence must skip the procedure call")

    changed = await feature_repo._transition_provider_lifecycle_from_state(
        _Session(),  # type: ignore[arg-type]
        feature_id="place:override",
        desired_state=feature_repo.ProviderFeatureState(
            lifecycle_state="active",
            publication_state="published",
            quality_state="valid",
        ),
        provider_dataset_id=17,
        source_membership=_provider_membership(),
        current=feature_repo._FeatureLoadState(
            exists=True,
            lifecycle_state="retired",
            publication_state="suppressed",
            quality_state="valid",
            row_revision=3,
            has_provider_reactivation_override=True,
        ),
        retry_on_serialization=True,
    )

    assert changed is False


@pytest.mark.asyncio
async def test_provider_reactivation_fence_sqlstate_is_a_noop() -> None:
    class _Nested:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: Any) -> bool:
            return False

    class _DriverError(Exception):
        sqlstate = "23514"

    class _Session:
        def __init__(self) -> None:
            self.transition_calls = 0

        def begin_nested(self) -> _Nested:
            return _Nested()

        async def execute(self, *_args: Any, **_kwargs: Any) -> None:
            self.transition_calls += 1
            raise DBAPIError.instance(
                "CALL feature.transition_feature_state", {},
                _DriverError("provider reactivation is fenced by lifecycle override"),
                _DriverError,
            )

    session = _Session()
    changed = await feature_repo._transition_provider_lifecycle_from_state(
        session,  # type: ignore[arg-type]
        feature_id="place:race-fence",
        desired_state=feature_repo.ProviderFeatureState(
            lifecycle_state="active",
            publication_state="published",
            quality_state="valid",
        ),
        provider_dataset_id=17,
        source_membership=_provider_membership(),
        current=feature_repo._FeatureLoadState(
            exists=True,
            lifecycle_state="retired",
            publication_state="suppressed",
            quality_state="valid",
            row_revision=4,
            has_provider_reactivation_override=False,
        ),
        retry_on_serialization=True,
    )

    assert changed is False
    assert session.transition_calls == 1


@pytest.mark.asyncio
async def test_provider_reactivation_conflict_rereads_without_second_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Nested:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: Any) -> bool:
            return False

    class _DriverError(Exception):
        sqlstate = "40001"

    class _Session:
        def __init__(self) -> None:
            self.transition_calls = 0

        def begin_nested(self) -> _Nested:
            return _Nested()

        async def execute(self, *_args: Any, **_kwargs: Any) -> None:
            self.transition_calls += 1
            raise DBAPIError.instance(
                "CALL feature.transition_feature_state", {}, _DriverError("changed"), _DriverError
            )

    async def _already_advanced(*_args: Any, **_kwargs: Any) -> feature_repo._FeatureLoadState:
        return feature_repo._FeatureLoadState(
            exists=True,
            lifecycle_state="active",
            publication_state="published",
            quality_state="valid",
            row_revision=5,
            has_provider_reactivation_override=False,
        )

    monkeypatch.setattr(feature_repo, "_feature_load_state", _already_advanced)
    session = _Session()
    changed = await feature_repo._transition_provider_lifecycle_from_state(
        session,  # type: ignore[arg-type]
        feature_id="place:concurrent",
        desired_state=feature_repo.ProviderFeatureState(
            lifecycle_state="active",
            publication_state="published",
            quality_state="valid",
        ),
        provider_dataset_id=17,
        source_membership=_provider_membership(),
        current=feature_repo._FeatureLoadState(
            exists=True,
            lifecycle_state="retired",
            publication_state="suppressed",
            quality_state="valid",
            row_revision=4,
            has_provider_reactivation_override=False,
        ),
        retry_on_serialization=True,
    )

    assert changed is False
    assert session.transition_calls == 1


@pytest.mark.asyncio
async def test_provider_reactivation_conflict_retries_once_when_still_retired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Nested:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *_args: Any) -> bool:
            return False

    class _DriverError(Exception):
        sqlstate = "40001"

    class _Session:
        def __init__(self) -> None:
            self.transition_calls = 0

        def begin_nested(self) -> _Nested:
            return _Nested()

        async def execute(self, *_args: Any, **_kwargs: Any) -> None:
            self.transition_calls += 1
            if self.transition_calls == 1:
                raise DBAPIError.instance(
                    "CALL feature.transition_feature_state",
                    {},
                    _DriverError("changed"),
                    _DriverError,
                )

    async def _still_retired(*_args: Any, **_kwargs: Any) -> feature_repo._FeatureLoadState:
        return feature_repo._FeatureLoadState(
            exists=True,
            lifecycle_state="retired",
            publication_state="suppressed",
            quality_state="valid",
            row_revision=5,
            has_provider_reactivation_override=False,
        )

    monkeypatch.setattr(feature_repo, "_feature_load_state", _still_retired)
    session = _Session()
    changed = await feature_repo._transition_provider_lifecycle_from_state(
        session,  # type: ignore[arg-type]
        feature_id="place:retry",
        desired_state=feature_repo.ProviderFeatureState(
            lifecycle_state="active",
            publication_state="published",
            quality_state="valid",
        ),
        provider_dataset_id=17,
        source_membership=_provider_membership(),
        current=feature_repo._FeatureLoadState(
            exists=True,
            lifecycle_state="retired",
            publication_state="suppressed",
            quality_state="valid",
            row_revision=4,
            has_provider_reactivation_override=False,
        ),
        retry_on_serialization=True,
    )

    assert changed is True
    assert session.transition_calls == 2


def test_feature_params_carry_geom_wkt_for_subtype_only() -> None:
    """``geom_wkt``은 core 컬럼이 아니라 route/area subtype 전용 바인딩이다.

    ``upsert_feature``가 core 실행 전에 ``pop``하므로 core INSERT 파라미터에는
    남지 않는다 — 여기서는 빌더가 그 키를 만든다는 것만 고정한다.
    """
    params = _feature_params(_place(None, None))
    assert "geom_wkt" in params
    assert params["geom_wkt"] is None


def test_feature_detail_maps_to_typed_subtype_params() -> None:
    """kind별 값의 정본은 subtype이다 — DTO detail이 typed 컬럼으로 간다."""
    feature = _place(
        Coordinate(lon=Decimal("126.92"), lat=Decimal("37.55")),
        PlaceDetail(feature_id="place:abc123", place_kind="cafe", phones=["02-1234-5678"]),
    )
    params = subtype_params(
        feature_id=feature.feature_id,
        feature_uuid="00000000-0000-4000-8000-000000000001",
        kind=feature.kind.value,
        detail=feature.detail,
    )
    assert params is not None
    assert params["place_kind"] == "cafe"
    assert params["phones"] == ["02-1234-5678"]
    # jsonb 컬럼만 JSON 문자열로 직렬화된다(raw text() 경로 바인딩).
    assert json.loads(params["payload"]) == {}


def test_feature_params_without_coord_is_none() -> None:
    feature = _place(None, None)
    params = _feature_params(feature)

    assert params["lon"] is None
    assert params["lat"] is None
    # core bind에 detail은 애초에 없다 — 값 정본은 subtype이다.
    assert "detail" not in params
    # detail 미지정이어도 subtype 파라미터는 kind DTO 기본값으로 채워진다.
    subtype = subtype_params(
        feature_id=feature.feature_id,
        feature_uuid="00000000-0000-4000-8000-000000000001",
        kind=feature.kind.value,
        detail=feature.detail,
    )
    assert subtype is not None
    assert subtype["place_kind"] == PlaceDetail(feature_id="x").place_kind


def test_source_record_params_serializes_raw_data() -> None:
    record = SourceRecord(
        source_record_key="sr_key1",
        provider="python-datagokr-api",
        dataset_key="cultural_festivals",
        source_entity_type="festival",
        source_entity_id="E001",
        raw_payload_hash="hash1",
        raw_data={"a": 1, "b": "값"},
        fetched_at=_NOW,
    )
    params = _source_record_params(record, provider_dataset_id=7)

    assert params["source_record_key"] == "sr_key1"
    assert params["provider"] == "python-datagokr-api"
    assert params["provider_dataset_id"] == 7
    loaded = json.loads(params["raw_data"])
    assert loaded == {"a": 1, "b": "값"}


def test_source_link_params_maps_enum_value() -> None:
    link = SourceLink(
        feature_id="place:abc123",
        source_record_key="sr_key1",
        source_role=SourceRole.PRIMARY,
        match_method="natural_key",
        confidence=100,
        created_at=_NOW,
    )
    params = _source_link_params(link)

    assert params["source_role"] == "primary"
    assert params["confidence"] == 100
    # ``is_primary_source``는 T-VN-33에서 ``source_role``로 흡수됐다 —
    # 같은 사실을 두 컬럼에 적으면 서로 어긋날 수 있어 파생 컬럼을 없앴다.
    assert "is_primary_source" not in params


def test_feature_load_result_defaults_zero() -> None:
    result = FeatureLoadResult()
    assert result.bundles_total == 0
    assert result.features_inserted == 0
    assert result.source_links_updated == 0


def test_module_exports_load_helpers() -> None:
    for name in (
        "load_bundle",
        "load_bundles",
        "upsert_feature",
        "get_feature_row",
        "features_nearby_poi_cache_target",
    ):
        assert hasattr(feature_repo, name)


@pytest.mark.parametrize("close_missing", [False, True])
def test_notice_reconcile_reranks_only_out_of_scope_feature_lineages(
    close_missing: bool,
) -> None:
    """동일 scope는 ``ranked``를 재사용해 lineage 수의 제곱 비용을 피한다."""
    sql = feature_repo._supersede_stale_notice_sql(close_missing)
    out_of_scope = sql.split("out_of_scope_feature_lineages AS MATERIALIZED (", 1)[
        1
    ].split("),\nglobal_feature_wins AS MATERIALIZED (", 1)[0]
    normalized = " ".join(out_of_scope.split())

    assert (
        "dataset.provider <> :provider OR dataset.dataset_key <> :dataset_key OR "
        "se.source_entity_type <> :source_entity_type"
    ) in normalized
    assert "FROM out_of_scope_feature_lineages AS current_notice" in sql
    assert "FROM global_feature_lineages AS current_notice" not in sql


@pytest.mark.parametrize("close_missing", [False, True])
def test_notice_reconcile_materializes_lineage_ctes(close_missing: bool) -> None:
    """계보 승패 CTE는 질의당 1회만 계산돼야 한다 (ADR-087).

    ``MATERIALIZED``가 없으면 Postgres가 이 CTE를 갱신 대상 feature마다 다시
    실행한다 — 3,045 notice 규모에서 124.8초 대 0.58초다.
    """
    sql = feature_repo._supersede_stale_notice_sql(close_missing)

    assert "out_of_scope_feature_lineages AS MATERIALIZED (" in sql
    assert "global_feature_wins AS MATERIALIZED (" in sql


#: ``public_active_notice_filter_sql(..., frozen_h35_schema=True)``의 고정값
#: (2026-08-07 기준 = ``origin/main``의 필터와 byte-identical).
#:
#: H35 리허설의 존재 이유가 "0079 당시 표면을 그대로 재생한다"이므로, 이 SQL은
#: 동등해 보이는 재작성조차 두지 않는다. 리허설 자체는 **컬럼 참조 오류만** 잡지
#: 의미가 같은 재작성은 못 잡으므로(그 세대 스키마에서 실행만 되면 통과한다)
#: 여기서 바이트로 못박는다. 값이 바뀌면 리허설이 재생하는 표면이 달라진 것이다.
_FROZEN_H35_NOTICE_FILTER_SHA256: Final[str] = (
    "e934cdb89f1e390bb054447d572ba103a1c74442138d1d8567a938c560db46a7"
)


def test_frozen_h35_notice_filter_is_byte_stable() -> None:
    frozen = feature_repo.public_active_notice_filter_sql("f", frozen_h35_schema=True)

    assert len(frozen) == 15672
    assert (
        hashlib.sha256(frozen.encode()).hexdigest()
        == _FROZEN_H35_NOTICE_FILTER_SHA256
    )


def test_frozen_h35_notice_filter_does_not_touch_the_stored_column() -> None:
    """0079 세대에는 ``lineage_key`` 컬럼도 파생 함수도 없다 (ADR-087)."""
    frozen = feature_repo.public_active_notice_filter_sql("f", frozen_h35_schema=True)

    assert "sr.lineage_key" not in frozen
    assert "source_record_lineage_key" not in frozen
    # 남는 두 토큰은 파생 테이블 alias뿐이다.
    assert "AS lineage_key" in frozen
    assert "current_notice.lineage_key" in frozen


def test_current_notice_filter_reads_the_stored_lineage_column() -> None:
    """현행 필터는 계보를 **재계산하지 않는다** (ADR-087).

    재계산이 남으면 인덱스가 붙을 수 없고 경쟁자 탐색이 notice 전수 스캔으로
    되돌아간다 — 3,045 notice에서 0.17초 대 21.2초다.
    """
    current = feature_repo.public_active_notice_filter_sql("f")

    # T-VN-33에서 계보는 ``source_records``에서 ``source_entity_heads``로 옮겼다.
    # ``COALESCE(head.lineage_key, entity.source_entity_id)``는 **두 테이블에**
    # 걸쳐 있어 어떤 인덱스도 못 태운다(EXPLAIN에서 index 노드 0개). 그래서
    # head에 완전 물화하고 필터는 컬럼을 그대로 읽는다.
    assert "other_head.lineage_key = current_notice.lineage_key" in current
    assert "cur_head.lineage_key AS lineage_key" in current
    assert "COALESCE(" not in current
    assert "raw_data" not in current
    assert "concat_ws" not in current


def test_current_notice_filter_keeps_the_ordering_test_indexable() -> None:
    """순서 조건이 **행 비교 하나**여야 Index Cond로 밀린다 (ADR-087).

    한 술어 안에 ``OR``로 묶으면 Postgres가 Filter로 남겨 계보의 payload 이력
    전체를 훑는다 — 50,001 record 계보에서 ``Rows Removed by Filter: 50000``.
    그래서 "확실히 나은 행"과 "동률"을 **두 EXISTS로 나눈다**.
    """
    current = feature_repo.public_active_notice_filter_sql("f")

    normalized = " ".join(current.split())

    assert (
        "(other_head.observed_at, other_sr.source_record_key)"
        " > (current_notice.seen_at, current_notice.source_record_key)"
    ) in normalized
    assert current.count("HAVING bool_and(") == 1
    # 죽은 COALESCE가 남으면 인덱스 열과 맞지 않는다 — last_seen_at은 NOT NULL이다.
    assert "COALESCE(cur_sr.last_seen_at" not in current
    assert "COALESCE(other_sr.last_seen_at" not in current
    # 동률 분기는 별도 EXISTS여야 한다. 하나로 합치면 OR가 생겨 순서 조건이
    # Index Cond에서 Filter로 떨어진다.
    assert normalized.count("LIMIT 1 )") >= 2 or current.count("LIMIT 1") >= 2


def test_nearby_feature_sql_guards_required_lon_lat_contract() -> None:
    sql = feature_repo._NEARBY_TARGET_CTE_SQL

    assert "x_extension.ST_X(f.coord) AS lon" in sql
    assert "x_extension.ST_Y(f.coord) AS lat" in sql
    assert "f.coord IS NOT NULL" in sql
    assert "f.coord_5179 IS NOT NULL" in sql


#: T-VN-35(ADR-086) 이후의 종료 notice 감산 술어 — free-form jsonb 문자열
#: 파싱이 아니라 ``feature_notices.valid_end_time`` typed 비교다.
_TYPED_ENDED_NOTICE_FRAGMENTS: tuple[str, ...] = (
    "FROM feature.feature_notices AS ended_notice",
    "ended_notice.valid_end_time IS NOT NULL",
    "ended_notice.valid_end_time <= now()",
)

#: 되살아나면 안 되는 종전 형태 — 오염된 한 행이 공개 read 전체를 500으로
#: 만들 수 있던 문자열 파싱과 그 방어용 cast 가드(T-VN-06/F-9). typed 컬럼이
#: 그 실패 모드를 구조적으로 없앴으므로 재도입은 회귀다.
_STRING_PARSE_RELICS: tuple[str, ...] = (
    "pg_input_is_valid",
    "detail ->> 'valid_end_time'",
    "detail->>'valid_end_time'",
)


def _assert_typed_notice_filter(sql: str, alias: str, *, label: str) -> None:
    assert f"{alias}.kind <> 'notice'" in sql, f"{label} lost the kind short-circuit"
    for fragment in _TYPED_ENDED_NOTICE_FRAGMENTS:
        assert fragment in sql, f"{label} dropped typed valid_end_time comparison"
    assert f"ended_notice.feature_id = {alias}.feature_id" in sql, (
        f"{label} does not correlate on the caller alias"
    )
    for relic in _STRING_PARSE_RELICS:
        assert relic not in sql, f"{label} reintroduced free-form detail parsing"


def test_shared_notice_filter_function_compares_typed_valid_end_time() -> None:
    """중앙화된 notice 종료 감산 함수가 typed timestamptz 비교여야 한다.

    #745가 이 감산 SQL을 ``_ended_notice_hidden_sql(alias)`` /
    ``public_active_notice_filter_sql(alias)`` 함수로 중앙화하고 curation/curated
    표면까지 정본으로 확산시켰다 — 그 단일 함수가 곧 전 표면의 계약이다.
    T-VN-35(ADR-086)가 ``detail`` 문자열 파싱과 ``pg_input_is_valid`` 방어 cast를
    ``feature_notices.valid_end_time`` 비교로 대체했다(T-VN-06/F-9의 실패 모드
    자체가 소멸). alias를 그대로 반영하는지도 함께 고정한다.
    """
    for alias in ("f", "pf", "public_count_pf"):
        _assert_typed_notice_filter(
            feature_repo._ended_notice_hidden_sql(alias),
            alias,
            label=f"_ended_notice_hidden_sql({alias!r})",
        )
        _assert_typed_notice_filter(
            feature_repo.public_active_notice_filter_sql(alias),
            alias,
            label=f"public_active_notice_filter_sql({alias!r})",
        )
    # 기존 정적 상수(alias 'f')도 같은 계약을 담는다.
    _assert_typed_notice_filter(
        feature_repo._PUBLIC_ACTIVE_NOTICE_FILTER_SQL,
        "f",
        label="_PUBLIC_ACTIVE_NOTICE_FILTER_SQL",
    )


def test_every_composed_public_read_sql_embeds_typed_notice_filter() -> None:
    """_PUBLIC_ACTIVE_NOTICE_FILTER_SQL을 합성한 모든 공개 read 상수가 계약을 포함.

    미래에 특정 표면이 이 필터를 fork하며 감산을 빠뜨리거나(F-9 재발) 문자열
    파싱을 되살리면 fast-fail한다.
    """
    scalar_sql = {
        # T-VN-32B: identities SQL이 ids SQL을 대체(legacy id·UUID 쌍 반환).
        "_PUBLIC_ACTIVE_NOTICE_IDENTITIES_SQL": (
            feature_repo._PUBLIC_ACTIVE_NOTICE_IDENTITIES_SQL
        ),
        "_FEATURES_IN_BBOX_SQL": feature_repo._FEATURES_IN_BBOX_SQL,
        "_FEATURES_IN_BBOX_WITH_GEOMETRY_SQL": (
            feature_repo._FEATURES_IN_BBOX_WITH_GEOMETRY_SQL
        ),
        "_FEATURE_SEARCH_CTE_SQL": feature_repo._FEATURE_SEARCH_CTE_SQL,
        "_FEATURE_SEARCH_SCORE_CTE_SQL": feature_repo._FEATURE_SEARCH_SCORE_CTE_SQL,
        "_NEARBY_TARGET_CTE_SQL": feature_repo._NEARBY_TARGET_CTE_SQL,
        "_NEARBY_COORD_CTE_SQL": feature_repo._NEARBY_COORD_CTE_SQL,
        "_FEATURES_CONTAINED_IN_AREA_SQL": feature_repo._FEATURES_CONTAINED_IN_AREA_SQL,
        "_CATEGORY_FEATURE_COUNTS_SQL": feature_repo._CATEGORY_FEATURE_COUNTS_SQL,
    }
    for name, sql in scalar_sql.items():
        _assert_typed_notice_filter(sql, "f", label=name)
    # cluster는 unit별 3종을 dict로 조립 — 각 변형이 같은 계약을 담아야 한다.
    for unit, sql in feature_repo._CLUSTER_BBOX_SQL_BY_UNIT.items():
        _assert_typed_notice_filter(sql, "f", label=f"cluster SQL[{unit}]")


def test_curation_and_curated_route_through_shared_notice_filter() -> None:
    """#745가 확산한 curation/curated 공개 표면이 중앙 함수를 경유해 계약을 상속.

    각 repo의 합성 SQL 상수가 자신의 alias로 만든 typed 감산을 담고 있어야 한다 —
    naked cast를 다시 인라인하면 여기서 fast-fail한다.
    """
    from kortravelmap.infra import curated_repo, curation_repo

    # curation collection count(count_pf / public_count_pf)·item 필터(pf).
    _assert_typed_notice_filter(
        curation_repo._COLLECTION_COUNT_NOTICE_FILTER_SQL,
        "count_pf",
        label="_COLLECTION_COUNT_NOTICE_FILTER_SQL",
    )
    _assert_typed_notice_filter(
        curation_repo._COLLECTION_PUBLIC_COUNT_NOTICE_FILTER_SQL,
        "public_count_pf",
        label="_COLLECTION_PUBLIC_COUNT_NOTICE_FILTER_SQL",
    )
    _assert_typed_notice_filter(
        curation_repo._ITEM_PUBLIC_NOTICE_FILTER_SQL,
        "pf",
        label="_ITEM_PUBLIC_NOTICE_FILTER_SQL",
    )
    # curated feature 목록 공개 필터(f 별칭).
    _assert_typed_notice_filter(
        curated_repo._PUBLIC_FEATURE_FILTERS_SQL,
        "f",
        label="_PUBLIC_FEATURE_FILTERS_SQL",
    )


def test_nearby_cursor_round_trips_distance_name_and_updated_at() -> None:
    row = NearbyFeatureRow(
        feature_id="feature-1",
        kind="place",
        name="A first",
        category="06020000",
        lon=126.978,
        lat=37.5665,
        distance_m=12.5,
        primary_provider="python-opinet-api",
        primary_dataset_key="opinet_stations",
        last_updated_at=_NOW,
    )

    distance = feature_repo._encode_nearby_cursor(row, sort="distance")
    assert feature_repo._nearby_cursor_params(distance, sort="distance") == {
        "cursor_distance_m": 12.5,
        "cursor_name": None,
        "cursor_last_updated_at": None,
        "cursor_feature_id": "feature-1",
    }

    name = feature_repo._encode_nearby_cursor(row, sort="name")
    assert feature_repo._nearby_cursor_params(name, sort="name")[
        "cursor_name"
    ] == "A first"

    updated = feature_repo._encode_nearby_cursor(row, sort="last_updated_at")
    assert feature_repo._nearby_cursor_params(updated, sort="last_updated_at")[
        "cursor_last_updated_at"
    ] == _NOW


def test_nearby_cursor_rejects_malformed_or_wrong_sort() -> None:
    row = NearbyFeatureRow(
        feature_id="feature-1",
        kind="place",
        name="A first",
        category="06020000",
        lon=126.978,
        lat=37.5665,
        distance_m=12.5,
        primary_provider=None,
        primary_dataset_key=None,
        last_updated_at=_NOW,
    )
    cursor = feature_repo._encode_nearby_cursor(row, sort="distance")

    with pytest.raises(ValueError, match="invalid nearby cursor"):
        feature_repo._nearby_cursor_params("not-base64", sort="distance")
    with pytest.raises(ValueError, match="invalid nearby cursor"):
        feature_repo._nearby_cursor_params(cursor, sort="name")


def test_feature_search_cursor_round_trips_score_and_id_modes() -> None:
    row = FeatureSearchRow(
        feature_id="feature-1",
        kind="place",
        name="경복궁",
        category="01070100",
        lon=126.977,
        lat=37.5796,
        marker_icon="monument",
        marker_color="P-01",
        score=0.95,
        score_cursor="0.9500000476837158",
    )

    score_contract = feature_repo._feature_search_contract(
        q=" 경복궁 ",
        bbox=None,
        kinds=["place", "place"],
        categories=None,
        page_size=20,
        include_total=False,
    )
    score_cursor = feature_repo._encode_search_cursor(
        row,
        contract=score_contract,
        signing_key=_SEARCH_CURSOR_KEY,
    )
    assert feature_repo._search_cursor_params(
        score_cursor,
        contract=score_contract,
        signing_key=_SEARCH_CURSOR_KEY,
    ) == {
        "cursor_score": "0.9500000476837158",
        "cursor_feature_id": "feature-1",
    }

    id_contract = feature_repo._feature_search_contract(
        q=None,
        bbox=(126.0, 37.0, 128.0, 38.0),
        kinds=None,
        categories=["01070100"],
        page_size=20,
        include_total=False,
    )
    id_cursor = feature_repo._encode_search_cursor(
        row,
        contract=id_contract,
        signing_key=_SEARCH_CURSOR_KEY,
    )
    assert feature_repo._search_cursor_params(
        id_cursor,
        contract=id_contract,
        signing_key=_SEARCH_CURSOR_KEY,
    ) == {
        "cursor_score": None,
        "cursor_feature_id": "feature-1",
    }

    with pytest.raises(FeatureSearchCursorQueryMismatchError):
        feature_repo._search_cursor_params(
            score_cursor,
            contract=id_contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )


def test_feature_search_cursor_fingerprint_uses_normalized_repository_contract() -> None:
    first = feature_repo._feature_search_contract(
        q="  경복궁  ",
        bbox=(126.0, 37.0, 128.0, 38.0),
        kinds=["event", "place", "event"],
        categories=["01070100", " 01070100 "],
        page_size=50,
        include_total=True,
    )
    second = feature_repo._feature_search_contract(
        q="경복궁",
        bbox=(126, 37, 128, 38),
        kinds=["place", "event"],
        categories=["01070100"],
        page_size=50,
        include_total=True,
    )
    assert first == second
    assert first.fingerprint == second.fingerprint
    cursor = feature_repo._encode_search_cursor(
        FeatureSearchRow(
            feature_id="feature-1",
            kind="place",
            name="경복궁",
            category="01070100",
            lon=126.977,
            lat=37.5796,
            marker_icon="monument",
            marker_color="P-01",
            score=0.95,
            score_cursor="0.9500000476837158",
        ),
        contract=first,
        signing_key=_SEARCH_CURSOR_KEY,
    )
    assert feature_repo._search_cursor_params(
        cursor,
        contract=second,
        signing_key=_SEARCH_CURSOR_KEY,
    )["cursor_feature_id"] == "feature-1"


def test_feature_search_cursor_rejects_tamper_unknown_version_and_query_reuse() -> None:
    contract = feature_repo._feature_search_contract(
        q="경복궁",
        bbox=None,
        kinds=["place"],
        categories=None,
        page_size=10,
        include_total=False,
    )
    row = FeatureSearchRow(
        feature_id="feature-1",
        kind="place",
        name="경복궁",
        category="01070100",
        lon=126.977,
        lat=37.5796,
        marker_icon="monument",
        marker_color="P-01",
        score=0.95,
        score_cursor="0.9500000476837158",
    )
    cursor = feature_repo._encode_search_cursor(
        row,
        contract=contract,
        signing_key=_SEARCH_CURSOR_KEY,
    )
    payload, signature = cursor.split(".")
    tampered_payload = ("A" if payload[0] != "A" else "B") + payload[1:]
    with pytest.raises(FeatureSearchCursorTamperedError):
        feature_repo._search_cursor_params(
            f"{tampered_payload}.{signature}",
            contract=contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )
    tampered_signature = ("A" if signature[0] != "A" else "B") + signature[1:]
    with pytest.raises(FeatureSearchCursorTamperedError):
        feature_repo._search_cursor_params(
            f"{payload}.{tampered_signature}",
            contract=contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )
    with pytest.raises(FeatureSearchCursorInvalidError):
        feature_repo._search_cursor_params(
            f"{payload}.{signature[:-2]}",
            contract=contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )

    unknown_version = feature_repo._encode_search_cursor_payload(
        {
            "v": 999,
            "kind": "feature_search",
            "query": contract.fingerprint,
            "keyset": {
                "feature_id": "feature-1",
                "score": "0.9500000476837158",
            },
        },
        signing_key=_SEARCH_CURSOR_KEY,
    )
    with pytest.raises(FeatureSearchCursorVersionUnsupportedError):
        feature_repo._search_cursor_params(
            unknown_version,
            contract=contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )

    changed_query = feature_repo._feature_search_contract(
        q="창덕궁",
        bbox=None,
        kinds=["place"],
        categories=None,
        page_size=10,
        include_total=False,
    )
    with pytest.raises(FeatureSearchCursorQueryMismatchError):
        feature_repo._search_cursor_params(
            cursor,
            contract=changed_query,
            signing_key=_SEARCH_CURSOR_KEY,
        )

    for invalid_payload in (
        {
            "v": 1,
            "kind": "other",
            "query": contract.fingerprint,
            "keyset": {
                "feature_id": "feature-1",
                "score": "0.9500000476837158",
            },
        },
        {
            "v": 1,
            "kind": "feature_search",
            "query": contract.fingerprint,
            "keyset": {"feature_id": "feature-1", "score": "NaN"},
        },
    ):
        invalid_cursor = feature_repo._encode_search_cursor_payload(
            invalid_payload,
            signing_key=_SEARCH_CURSOR_KEY,
        )
        with pytest.raises(FeatureSearchCursorInvalidError):
            feature_repo._search_cursor_params(
                invalid_cursor,
                contract=contract,
                signing_key=_SEARCH_CURSOR_KEY,
            )


@pytest.mark.parametrize(
    "cursor",
    [
        "not-a-token",
        "payload=.signature",
        "a" * 2049,
    ],
)
def test_feature_search_cursor_rejects_malformed_tokens(cursor: str) -> None:
    contract = feature_repo._feature_search_contract(
        q=None,
        bbox=(126.0, 37.0, 128.0, 38.0),
        kinds=None,
        categories=None,
        page_size=50,
        include_total=False,
    )
    with pytest.raises(FeatureSearchCursorInvalidError):
        feature_repo._search_cursor_params(
            cursor,
            contract=contract,
            signing_key=_SEARCH_CURSOR_KEY,
        )


@pytest.mark.asyncio
async def test_features_nearby_target_validates_before_db_call() -> None:
    class _Session:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("validation should happen before DB execute")

    with pytest.raises(ValueError, match="sort must be one of"):
        await feature_repo.features_nearby_poi_cache_target(
            _Session(),  # type: ignore[arg-type]
            target_id="target-1",
            sort="bad",
        )
    with pytest.raises(ValueError, match="radius_km must be greater than 0"):
        await feature_repo.features_nearby_poi_cache_target(
            _Session(),  # type: ignore[arg-type]
            target_id="target-1",
            radius_km=0,
        )
    with pytest.raises(ValueError, match="limit must be greater than 0"):
        await feature_repo.features_nearby_poi_cache_target(
            _Session(),  # type: ignore[arg-type]
            target_id="target-1",
            limit=0,
        )


@pytest.mark.asyncio
async def test_search_features_validates_before_db_call() -> None:
    class _Session:
        async def execute(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("validation should happen before DB execute")

    with pytest.raises(ValueError, match="q 또는 bbox"):
        await feature_repo.search_features(  # type: ignore[arg-type]
            _Session(),
            cursor_signing_key=_SEARCH_CURSOR_KEY,
        )
    with pytest.raises(ValueError, match="signing key must be at least 32 bytes"):
        await feature_repo.search_features(  # type: ignore[arg-type]
            _Session(),
            q="경복궁",
            cursor_signing_key=b"short",
        )
    with pytest.raises(ValueError, match="page_size must be greater than 0"):
        await feature_repo.search_features(
            _Session(),  # type: ignore[arg-type]
            q="경복궁",
            page_size=0,
            cursor_signing_key=_SEARCH_CURSOR_KEY,
        )
    with pytest.raises(ValueError, match="invalid bbox"):
        await feature_repo.search_features(
            _Session(),  # type: ignore[arg-type]
            bbox=(127, 37, 126, 38),
            cursor_signing_key=_SEARCH_CURSOR_KEY,
        )
    contract = feature_repo._feature_search_contract(
        q="경복궁",
        bbox=None,
        kinds=None,
        categories=None,
        page_size=50,
        include_total=False,
    )
    cursor = feature_repo._encode_search_cursor(
        FeatureSearchRow(
            feature_id="feature-1",
            kind="place",
            name="경복궁",
            category="01070100",
            lon=126.977,
            lat=37.5796,
            marker_icon="monument",
            marker_color="P-01",
            score=0.95,
            score_cursor="0.9500000476837158",
        ),
        contract=contract,
        signing_key=_SEARCH_CURSOR_KEY,
    )
    with pytest.raises(FeatureSearchCursorQueryMismatchError):
        await feature_repo.search_features(  # type: ignore[arg-type]
            _Session(),
            q="창덕궁",
            cursor=cursor,
            cursor_signing_key=_SEARCH_CURSOR_KEY,
        )


@pytest.mark.asyncio
async def test_search_features_include_total_false_never_executes_count() -> None:
    class _Result:
        def mappings(self) -> _Result:
            return self

        def all(self) -> list[dict[str, object]]:
            return []

        def scalar_one(self) -> int:
            return 7

    class _Session:
        def __init__(self) -> None:
            self.statements: list[str] = []

        async def execute(self, statement: object, *_args: object, **_kwargs: object) -> _Result:
            self.statements.append(" ".join(str(statement).lower().split()))
            return _Result()

    without_total = _Session()
    page = await feature_repo.search_features(  # type: ignore[arg-type]
        without_total,
        bbox=(126.0, 37.0, 128.0, 38.0),
        include_total=False,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert page.total_count is None
    assert not any("count(*)" in statement for statement in without_total.statements)

    with_total = _Session()
    counted_page = await feature_repo.search_features(  # type: ignore[arg-type]
        with_total,
        bbox=(126.0, 37.0, 128.0, 38.0),
        include_total=True,
        cursor_signing_key=_SEARCH_CURSOR_KEY,
    )
    assert counted_page.total_count == 7
    assert sum("count(*)" in statement for statement in with_total.statements) == 1


def _load_state(
    *, publication: str, reason_code: str | None, from_state: str | None
) -> feature_repo._FeatureLoadState:
    return feature_repo._FeatureLoadState(
        exists=True,
        lifecycle_state="retired",
        publication_state=publication,
        quality_state="valid",
        row_revision=1,
        has_provider_reactivation_override=False,
        last_publication_reason_code=reason_code,
        last_publication_from_state=from_state,
    )


_DESIRED = feature_repo.ProviderFeatureState(
    lifecycle_state="active", publication_state="published", quality_state="valid"
)


def test_provider_reingest_restores_the_value_the_retire_recorded() -> None:
    state = _load_state(
        publication="suppressed", reason_code="provider_retire", from_state="draft"
    )
    assert feature_repo._provider_reingest_publication(state, _DESIRED) == "draft"


def test_provider_reingest_recovers_rows_the_0095_backfill_handed_over() -> None:
    """0095가 넘겨온 세대도 공개 표면으로 돌아와야 한다.

    backfill은 legacy row마다 ``reason_code='legacy_provider_retire'``(또는
    ``legacy_status_retire``) / ``from_publication_state=NULL``인 전이 하나만 남긴다.
    되돌릴 값이 기록돼 있지 않다고 해서 복구를 포기하면, **마이그레이션이 스스로
    만들어낸 행 전량**이 ``feature.public_features``에서 영구히 사라진다 — prod는
    0087 + 실데이터라 그 집합이 크다. 이 축이 없으면 그 소멸이 조용히 남는다.
    """

    for reason_code in ("legacy_provider_retire", "legacy_status_retire"):
        state = _load_state(
            publication="suppressed", reason_code=reason_code, from_state=None
        )
        assert (
            feature_repo._provider_reingest_publication(state, _DESIRED) == "published"
        ), reason_code


def test_provider_reingest_leaves_a_newer_non_provider_decision_alone() -> None:
    """provider는 **자기가 내린 것만** 되돌린다."""

    state = _load_state(
        publication="suppressed", reason_code="operator_suppress", from_state="published"
    )
    assert feature_repo._provider_reingest_publication(state, _DESIRED) == "suppressed"


def test_legacy_retire_reason_codes_exist_in_the_0095_backfill() -> None:
    """복구가 보는 reason code가 실제로 0095가 쓰는 이름인지 대조한다.

    이름이 갈리면 복구는 조용히 무효가 된다 — 위 테스트들은 여전히 통과하면서
    실제 backfill 행만 복구되지 않는다.
    """

    backfill_sql = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        # squash(`0200`) 이후 체인은 아카이브다 — `alembic/legacy_versions/README.md`.
        / "legacy_versions"
        / "0095_feature_orthogonal_state_spine.py"
    ).read_text(encoding="utf-8")
    for reason_code in feature_repo._LEGACY_PROVIDER_RETIRE_REASON_CODES:
        assert f"'{reason_code}'" in backfill_sql, reason_code
