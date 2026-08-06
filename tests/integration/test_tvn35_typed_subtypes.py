"""T-VN-35 / ADR-084 — kind별 typed subtype 계약 통합 테스트 (testcontainers).

alembic 0084~0086이 만든 배타 arc와 "subtype이 kind별 값의 유일한 정본"이라는
계약을 **DB 수준에서** 고정한다. 여기서 검증하는 축은 다섯이다:

1. **배타 arc** — subtype 행이 있는 동안 core ``kind``가 못 바뀌고, 한 feature는
   최대 하나의 subtype에만 있으며, 고아 subtype과 identity 사본 불일치가
   FK로 막힌다. 코드 규율이 아니라 DB 계약이라는 것이 요점이다.
2. **upsert 왕복** — writer가 subtype에만 쓰고, ``feature.features_detailed``가
   조립한 ``detail``이 DTO 왕복과 동등하다(응답 shape 무변경).
3. **geometry 필수 kind** — geometry 없는 route/area는 write 시점에 거부되고
   core 행도 남지 않는다(``feature_routes``/``feature_areas``의 ``geom``이
   NOT NULL이므로 사후 보정이 아니라 fail-close).
4. **notice lifecycle** — supersede/purge가 typed ``timestamptz`` 컬럼을 갱신하고
   공개 read 필터가 그 typed 비교로 감산한다(``detail->>`` 문자열 파싱 소멸).
5. **merge cross-kind 거부** — kind가 subtype 소속을 결정하므로 이종 병합은
   무결성을 직접 깬다(``MergeConflictError``).

추가로 0086 ``downgrade``/``upgrade`` 왕복이 ``detail`` 역조립을 무손실로
수행하는지 소량 시드 md5 대조로 고정한다(ADR-084 근거절의 731k행 전수 대조를
회귀 가드 크기로 축소한 것).
"""

from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

import pytest
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from alembic import command
from kortravelmap.core.ids import make_payload_hash, make_source_record_key
from kortravelmap.dto import (
    Address,
    AreaDetail,
    Coordinate,
    EventDetail,
    Feature,
    FeatureBundle,
    FeatureKind,
    NoticeDetail,
    PlaceDetail,
    RouteDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.infra import feature_repo, merge_repo
from kortravelmap.infra.db import make_async_engine, normalize_async_dsn
from kortravelmap.infra.feature_subtype import (
    SUBTYPE_TABLES,
    count_subtype_drift,
    subtype_params,
    subtype_upsert_sql,
)
from kortravelmap.infra.merge_repo import MergeConflictError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 8, 6, 12, 0, tzinfo=_KST)

_ROUTE_WKT = "MULTILINESTRING((127.0 37.5, 127.01 37.51, 127.02 37.52))"
_AREA_WKT = (
    "MULTIPOLYGON(((127.0 37.5, 127.1 37.5, 127.1 37.6, 127.0 37.6, 127.0 37.5)))"
)


# ---------------------------------------------------------------------------
# 시드 헬퍼 — core는 raw SQL, subtype은 **프로덕션 매핑 정본**을 그대로 쓴다.
# (테스트가 매핑 규칙을 복제하면 계약이 두 벌이 된다.)
# ---------------------------------------------------------------------------


async def _insert_core(
    session: AsyncSession,
    *,
    feature_id: str,
    kind: str,
    name: str = "타입드 서브타입 검증",
    category: str = "01070100",
    lon: float | None = 127.0,
    lat: float | None = 37.5,
    status: str = "active",
) -> str:
    """core 행만 INSERT하고 저장된 ``feature_uuid``를 돌려준다."""
    stored_uuid = (
        await session.execute(
            text(
                """
                INSERT INTO feature.features (
                    feature_id, kind, name, category, coord, status, updated_at
                )
                VALUES (
                    :feature_id, :kind, :name, :category,
                    CASE WHEN CAST(:lon AS double precision) IS NULL THEN NULL
                         ELSE x_extension.ST_SetSRID(
                             x_extension.ST_MakePoint(
                                 CAST(:lon AS double precision),
                                 CAST(:lat AS double precision)
                             ), 4326) END,
                    :status, CAST(:updated_at AS timestamptz)
                )
                RETURNING CAST(feature_uuid AS text)
                """
            ),
            {
                "feature_id": feature_id,
                "kind": kind,
                "name": name,
                "category": category,
                "lon": lon,
                "lat": lat,
                "status": status,
                "updated_at": _NOW,
            },
        )
    ).scalar_one()
    await session.flush()
    return str(stored_uuid)


async def _insert_subtype(
    session: AsyncSession,
    *,
    feature_id: str,
    feature_uuid: str,
    kind: str,
    detail: dict[str, Any],
    geom_wkt: str | None = None,
) -> None:
    sql = subtype_upsert_sql(kind)
    assert sql is not None, f"kind {kind!r} has no subtype table"
    params = subtype_params(
        feature_id=feature_id,
        feature_uuid=feature_uuid,
        kind=kind,
        detail=detail,
    )
    assert params is not None
    if geom_wkt is not None:
        params["geom_wkt"] = geom_wkt
    await session.execute(text(sql), params)
    await session.flush()


async def _seed_place(
    session: AsyncSession, feature_id: str, *, place_kind: str = "cafe"
) -> str:
    feature_uuid = await _insert_core(session, feature_id=feature_id, kind="place")
    await _insert_subtype(
        session,
        feature_id=feature_id,
        feature_uuid=feature_uuid,
        kind="place",
        detail={"place_kind": place_kind},
    )
    return feature_uuid


def _bundle(
    feature: Feature,
    *,
    source_entity_id: str,
    provider: str = "python-krex-api",
    dataset_key: str = "krex_traffic_notices",
    source_entity_type: str = "traffic_notice",
    raw_data: dict[str, Any] | None = None,
    fetched_at: datetime | None = None,
) -> FeatureBundle:
    """``feature_repo.load_bundle``이 받는 최소 bundle."""
    payload = raw_data if raw_data is not None else {"natural_key": source_entity_id}
    payload_hash = make_payload_hash(payload)
    source_record_key = make_source_record_key(
        provider=provider,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
    )
    return FeatureBundle(
        feature=feature,
        source_record=SourceRecord(
            provider=provider,
            dataset_key=dataset_key,
            source_entity_type=source_entity_type,
            source_entity_id=source_entity_id,
            raw_payload_hash=payload_hash,
            raw_name=feature.name,
            raw_data=payload,
            fetched_at=fetched_at or _NOW,
            source_record_key=source_record_key,
        ),
        source_link=SourceLink(
            feature_id=feature.feature_id,
            source_record_key=source_record_key,
            source_role=SourceRole.PRIMARY,
            match_method="natural_key",
            confidence=100,
            is_primary_source=True,
        ),
    )


async def _detail_from_view(session: AsyncSession, feature_id: str) -> dict[str, Any]:
    """``features_detailed``가 subtype에서 조립한 ``detail``(응답 정본)."""
    raw = (
        await session.execute(
            text(
                "SELECT detail FROM feature.features_detailed "
                "WHERE feature_id = :feature_id"
            ),
            {"feature_id": feature_id},
        )
    ).scalar_one()
    return json.loads(raw) if isinstance(raw, str) else dict(raw)


async def _subtype_row(
    session: AsyncSession, table: str, feature_id: str
) -> dict[str, Any] | None:
    row = (
        await session.execute(
            text(f"SELECT * FROM feature.{table} WHERE feature_id = :feature_id"),
            {"feature_id": feature_id},
        )
    ).mappings().first()
    return dict(row) if row is not None else None


# ---------------------------------------------------------------------------
# ① 배타 arc — kind 불변 / 단일 subtype / 고아 금지 / identity 사본 일치
# ---------------------------------------------------------------------------


async def test_core_kind_change_is_blocked_while_subtype_row_exists(
    migrated_session: AsyncSession,
) -> None:
    """subtype 행이 있는 동안 core ``kind`` 변경이 **FK 위반**으로 막힌다.

    ADR-084 컨텍스트 1의 구멍(provider upsert의 ``kind = EXCLUDED.kind``가 kind를
    조용히 교체할 수 있던 것)을 코드 규율이 아니라 DB 계약으로 닫은 것이 이
    단언의 대상이다. 참조 대상은 0084의 ``uq_features_identity_kind``.
    """
    await _seed_place(migrated_session, "tvn35:arc:kind")

    with pytest.raises(IntegrityError) as excinfo:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "UPDATE feature.features SET kind = 'event' "
                    "WHERE feature_id = :feature_id"
                ),
                {"feature_id": "tvn35:arc:kind"},
            )
    assert "fk_feature_places_feature_kind" in str(excinfo.value)

    # subtype이 없는 kind(price)는 arc 밖이라 종전대로 자유롭다 — 배타 arc가
    # "subtype이 있는 동안"에만 kind를 묶는다는 것을 반대 방향으로 고정한다.
    await _insert_core(
        migrated_session, feature_id="tvn35:arc:price", kind="price", category="06020000"
    )
    await migrated_session.execute(
        text("UPDATE feature.features SET kind = 'weather' WHERE feature_id = :feature_id"),
        {"feature_id": "tvn35:arc:price"},
    )
    await migrated_session.flush()


async def test_second_subtype_insert_is_blocked_for_same_feature(
    migrated_session: AsyncSession,
) -> None:
    """한 feature는 최대 한 subtype에만 존재한다 — 이중 삽입은 FK 위반이다.

    core ``kind``가 단일 값이므로 다른 kind 상수를 요구하는 subtype의
    ``(feature_id, kind)`` 복합 FK가 구조적으로 실패한다.
    """
    feature_uuid = await _seed_place(migrated_session, "tvn35:arc:double")

    with pytest.raises(IntegrityError) as excinfo:
        async with migrated_session.begin_nested():
            await _insert_subtype(
                migrated_session,
                feature_id="tvn35:arc:double",
                feature_uuid=feature_uuid,
                kind="event",
                detail={"event_kind": "festival"},
            )
    assert "fk_feature_events_feature_kind" in str(excinfo.value)

    # 같은 subtype 재삽입(중복 PK)도 막힌다 — upsert 경로만이 갱신 수단이다.
    with pytest.raises(IntegrityError) as excinfo:
        async with migrated_session.begin_nested():
            await migrated_session.execute(
                text(
                    "INSERT INTO feature.feature_places "
                    "(feature_id, feature_uuid, kind, place_kind) "
                    "VALUES (:feature_id, CAST(:feature_uuid AS uuid), 'place', 'cafe')"
                ),
                {"feature_id": "tvn35:arc:double", "feature_uuid": feature_uuid},
            )
    assert "pk_feature_places" in str(excinfo.value)


async def test_orphan_subtype_and_identity_mismatch_are_blocked(
    migrated_session: AsyncSession,
) -> None:
    """core 행 없는 subtype과 identity 사본 불일치가 각각 FK로 막힌다."""
    with pytest.raises(IntegrityError) as excinfo:
        async with migrated_session.begin_nested():
            await _insert_subtype(
                migrated_session,
                feature_id="tvn35:arc:ghost",
                feature_uuid=str(uuid4()),
                kind="place",
                detail={"place_kind": "cafe"},
            )
    assert "fk_feature_places_feature_kind" in str(excinfo.value)

    # core는 있지만 feature_uuid 사본이 다르면 identity 쌍 FK가 막는다(0083 선례).
    await _insert_core(migrated_session, feature_id="tvn35:arc:identity", kind="place")
    with pytest.raises(IntegrityError) as excinfo:
        async with migrated_session.begin_nested():
            await _insert_subtype(
                migrated_session,
                feature_id="tvn35:arc:identity",
                feature_uuid=str(uuid4()),
                kind="place",
                detail={"place_kind": "cafe"},
            )
    assert "fk_feature_places_identity_pair" in str(excinfo.value)


async def test_core_delete_cascades_to_subtype(migrated_session: AsyncSession) -> None:
    """core 행 삭제는 subtype을 CASCADE로 데려간다(0083 ``feature_aliases`` 규약)."""
    await _seed_place(migrated_session, "tvn35:arc:cascade")
    await migrated_session.execute(
        text("DELETE FROM feature.features WHERE feature_id = :feature_id"),
        {"feature_id": "tvn35:arc:cascade"},
    )
    await migrated_session.flush()
    assert await _subtype_row(migrated_session, "feature_places", "tvn35:arc:cascade") is None


# ---------------------------------------------------------------------------
# ② upsert 왕복 — subtype이 정본, 뷰가 응답 detail을 조립
# ---------------------------------------------------------------------------


def _place_feature(feature_id: str, *, place_kind: str, phones: list[str]) -> Feature:
    return Feature(
        feature_id=feature_id,
        kind=FeatureKind.PLACE,
        name="왕복 검증 카페",
        category="01070100",
        marker_icon="cafe",
        marker_color="P-03",
        coord=Coordinate(lon=127.0, lat=37.5),
        address=Address(),
        detail=PlaceDetail(
            feature_id=feature_id,
            place_kind=place_kind,
            phones=phones,
            biz_number="123-45-67890",
            license_date=date(2024, 3, 1),
            facility_info={"seats": 40, "wifi": None},
            payload={"origin": "tvn35"},
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _event_feature(feature_id: str, *, ends_on: date) -> Feature:
    return Feature(
        feature_id=feature_id,
        kind=FeatureKind.EVENT,
        name="왕복 검증 축제",
        category="01010100",
        marker_icon="festival",
        marker_color="P-05",
        coord=Coordinate(lon=127.01, lat=37.51),
        address=Address(),
        detail=EventDetail(
            feature_id=feature_id,
            event_kind="festival",
            starts_on=date(2026, 8, 1),
            ends_on=ends_on,
            venue_name="여의도공원",
            tel="02-000-0000",
            content_id="C-1",
            content_type_id="15",
            area_code="1",
            payload={"origin": "tvn35"},
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )


def _notice_feature(
    feature_id: str,
    *,
    valid_end_time: datetime | None,
    valid_start_time: datetime | None = None,
) -> Feature:
    return Feature(
        feature_id=feature_id,
        kind=FeatureKind.NOTICE,
        name="왕복 검증 공지",
        category="99000000",
        marker_icon="danger",
        marker_color="P-15",
        coord=Coordinate(lon=127.02, lat=37.52),
        address=Address(),
        detail=NoticeDetail(
            feature_id=feature_id,
            notice_type="traffic",
            severity=2,
            valid_start_time=valid_start_time or _NOW - timedelta(days=1),
            valid_end_time=valid_end_time,
            source_agency="한국도로공사",
            payload={"domain": "highway"},
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )


async def test_place_bundle_upsert_round_trips_through_subtype(
    migrated_session: AsyncSession,
) -> None:
    """place bundle 적재 → subtype 행 생성 · identity 쌍 일치 · 뷰 detail 동등."""
    feature = _place_feature(
        "tvn35:rt:place", place_kind="cafe", phones=["02-1234-5678"]
    )
    await feature_repo.load_bundle(migrated_session, _bundle(feature, source_entity_id="P-1"))
    await migrated_session.flush()

    row = await _subtype_row(migrated_session, "feature_places", "tvn35:rt:place")
    assert row is not None
    assert row["kind"] == "place"
    assert row["place_kind"] == "cafe"
    assert row["phones"] == ["02-1234-5678"]
    assert row["license_date"] == date(2024, 3, 1)
    core_uuid = (
        await migrated_session.execute(
            text(
                "SELECT CAST(feature_uuid AS text) FROM feature.features "
                "WHERE feature_id = :feature_id"
            ),
            {"feature_id": "tvn35:rt:place"},
        )
    ).scalar_one()
    assert str(row["feature_uuid"]) == str(core_uuid)

    # 뷰가 조립한 detail이 DTO 왕복과 동등하다(응답 shape 무변경).
    assembled = await _detail_from_view(migrated_session, "tvn35:rt:place")
    assert PlaceDetail.model_validate(assembled) == feature.detail

    # 재upsert가 subtype을 **갱신**한다(행 증식 없음).
    updated = _place_feature(
        "tvn35:rt:place", place_kind="restaurant", phones=["02-9999-0000"]
    )
    await feature_repo.load_bundle(
        migrated_session, _bundle(updated, source_entity_id="P-1", raw_data={"v": 2})
    )
    await migrated_session.flush()
    reread = await _subtype_row(migrated_session, "feature_places", "tvn35:rt:place")
    assert reread is not None
    assert reread["place_kind"] == "restaurant"
    assert reread["phones"] == ["02-9999-0000"]
    assert (
        await migrated_session.execute(
            text("SELECT count(*) FROM feature.feature_places WHERE feature_id = :fid"),
            {"fid": "tvn35:rt:place"},
        )
    ).scalar_one() == 1
    assert await count_subtype_drift(migrated_session) == (0, 0, 0)


async def test_event_and_notice_bundles_round_trip_through_subtype(
    migrated_session: AsyncSession,
) -> None:
    """event/notice도 같은 계약 — typed date/timestamptz가 DTO 왕복과 동등하다."""
    event = _event_feature("tvn35:rt:event", ends_on=date(2026, 8, 10))
    notice = _notice_feature(
        "tvn35:rt:notice", valid_end_time=_NOW + timedelta(days=3)
    )
    await feature_repo.load_bundle(migrated_session, _bundle(event, source_entity_id="E-1"))
    await feature_repo.load_bundle(migrated_session, _bundle(notice, source_entity_id="N-1"))
    await migrated_session.flush()

    event_row = await _subtype_row(migrated_session, "feature_events", "tvn35:rt:event")
    assert event_row is not None
    assert event_row["starts_on"] == date(2026, 8, 1)
    assert event_row["ends_on"] == date(2026, 8, 10)
    assert event_row["timezone"] == "Asia/Seoul"

    notice_row = await _subtype_row(migrated_session, "feature_notices", "tvn35:rt:notice")
    assert notice_row is not None
    # 종전 ``detail->>`` 문자열이 아니라 typed timestamptz다.
    assert isinstance(notice_row["valid_end_time"], datetime)
    assert notice_row["valid_end_time"] == notice.detail.valid_end_time  # type: ignore[union-attr]
    assert notice_row["severity"] == 2

    assembled_event = await _detail_from_view(migrated_session, "tvn35:rt:event")
    assert EventDetail.model_validate(assembled_event) == event.detail
    assembled_notice = await _detail_from_view(migrated_session, "tvn35:rt:notice")
    assert NoticeDetail.model_validate(assembled_notice) == notice.detail

    # 재upsert로 종료 시각이 typed 컬럼에서 갱신된다.
    reopened = _notice_feature("tvn35:rt:notice", valid_end_time=None)
    await feature_repo.load_bundle(
        migrated_session, _bundle(reopened, source_entity_id="N-1", raw_data={"v": 2})
    )
    await migrated_session.flush()
    reread = await _subtype_row(migrated_session, "feature_notices", "tvn35:rt:notice")
    assert reread is not None
    assert reread["valid_end_time"] is None


async def test_assembled_notice_times_do_not_depend_on_session_timezone(
    migrated_session: AsyncSession,
) -> None:
    """조립된 시각 문자열이 세션 ``TimeZone`` GUC에 의존하면 안 된다.

    ``to_jsonb(timestamptz)``는 세션 TimeZone으로 렌더한다 — 그대로 두면 서버
    설정이 다른 인스턴스가 **같은 공지에 다른 문자열**을 돌려준다(실측: 같은
    행이 Asia/Seoul에서 ``+09:00``, UTC에서 ``+00:00``, America/New_York에서
    ``-04:00``). 뷰가 KST 고정 렌더를 쓰므로 세 세션에서 모두 같아야 한다.

    덧붙여 마이크로초가 0이면 생략해 Python ``datetime.isoformat()``과 표기가
    같다 — 기존 prod ``valid_start_time`` 145행이 그대로 유지되는 근거다.
    """
    feature_id = "tvn35:tz:notice"
    # 마이크로초 0(생략 분기)과 non-zero(``.US`` 분기)를 함께 태운다.
    start = datetime(2026, 8, 5, 17, 35, 24, tzinfo=_KST)
    end = datetime(2026, 8, 6, 1, 2, 3, 823154, tzinfo=_KST)
    notice = _notice_feature(feature_id, valid_start_time=start, valid_end_time=end)
    await feature_repo.load_bundle(
        migrated_session, _bundle(notice, source_entity_id="N-TZ")
    )
    await migrated_session.flush()

    rendered: list[tuple[str, str]] = []
    for zone in ("Asia/Seoul", "UTC", "America/New_York"):
        await migrated_session.execute(text(f"SET LOCAL TIME ZONE '{zone}'"))
        assembled = await _detail_from_view(migrated_session, feature_id)
        rendered.append(
            (assembled["valid_start_time"], assembled["valid_end_time"])
        )
    await migrated_session.execute(text("SET LOCAL TIME ZONE 'UTC'"))

    assert len(set(rendered)) == 1, f"세션 TimeZone에 따라 달라졌다: {rendered}"
    assert rendered[0] == (
        "2026-08-05T17:35:24+09:00",
        "2026-08-06T01:02:03.823154+09:00",
    )
    # 같은 순간을 가리키는지도 확인한다(표기만 고정한 것이지 값이 아니다).
    assembled = await _detail_from_view(migrated_session, feature_id)
    assert NoticeDetail.model_validate(assembled).valid_start_time == start
    assert NoticeDetail.model_validate(assembled).valid_end_time == end


async def test_event_sigungu_code_survives_subtype_round_trip(
    migrated_session: AsyncSession,
) -> None:
    """``EventDetail.sigungu_code``도 다른 필드와 같이 왕복해야 한다."""
    feature_id = "tvn35:rt:event-sigungu"
    feature = Feature(
        feature_id=feature_id,
        kind=FeatureKind.EVENT,
        name="시군구 코드 축제",
        category="01010100",
        marker_icon="festival",
        marker_color="P-05",
        coord=Coordinate(lon=127.03, lat=37.53),
        address=Address(),
        detail=EventDetail(
            feature_id=feature_id,
            event_kind="festival",
            starts_on=date(2026, 8, 1),
            ends_on=date(2026, 8, 3),
            area_code="1",
            sigungu_code="11140",
        ),
        created_at=_NOW,
        updated_at=_NOW,
    )
    await feature_repo.load_bundle(
        migrated_session, _bundle(feature, source_entity_id="E-SIGUNGU")
    )
    await migrated_session.flush()

    assembled = await _detail_from_view(migrated_session, feature_id)
    assert EventDetail.model_validate(assembled) == feature.detail


async def test_user_request_fence_skips_subtype_write(
    migrated_session: AsyncSession,
) -> None:
    """core가 fence로 갱신되지 않으면 subtype도 갱신되지 않는다(상세/core 정합).

    fence 판정은 core RETURNING이 남긴 실제 상태(``user_fenced``)라 파생 계산이
    아니다 — 여기서는 그 결과가 subtype까지 일관되게 미치는지만 본다.
    """
    feature = _place_feature("tvn35:fence", place_kind="cafe", phones=["02-1111-2222"])
    await feature_repo.load_bundle(migrated_session, _bundle(feature, source_entity_id="F-1"))
    await migrated_session.flush()
    await migrated_session.execute(
        text(
            "UPDATE feature.features SET data_origin = 'user_request', data_version = 1 "
            "WHERE feature_id = :feature_id"
        ),
        {"feature_id": "tvn35:fence"},
    )
    await migrated_session.flush()

    provider_retry = _place_feature(
        "tvn35:fence", place_kind="restaurant", phones=["02-3333-4444"]
    )
    await feature_repo.upsert_feature(migrated_session, provider_retry)
    await migrated_session.flush()

    row = await _subtype_row(migrated_session, "feature_places", "tvn35:fence")
    assert row is not None
    assert row["place_kind"] == "cafe"
    assert row["phones"] == ["02-1111-2222"]


# ---------------------------------------------------------------------------
# ③ geometry 필수 kind — write 시점 fail-close
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kind", "detail_factory"),
    [
        (FeatureKind.ROUTE, lambda fid: RouteDetail(feature_id=fid, route_type="trail")),
        (FeatureKind.AREA, lambda fid: AreaDetail(feature_id=fid, area_kind="area")),
    ],
)
async def test_geometryless_route_and_area_are_rejected_at_construction(
    migrated_session: AsyncSession,
    kind: FeatureKind,
    detail_factory: Any,
) -> None:
    """geometry 없는 route/area는 ``Feature`` 구성 시점에 거부된다.

    종전에는 적재 후 ``inactivate_geometryless_area_features_by_source``가 보정하던
    상태다. subtype ``geom``이 NOT NULL이 되면서 그 보정이 DTO 계약으로 앞당겨졌다
    (ADR-084 결정 5) — write까지 갈 것도 없다. 반대 방향(route/area가 아닌 kind의
    geometry)도 같은 validator가 막는다: 담을 곳이 없으므로 조용히 버려지느니
    거부한다.
    """
    feature_id = f"tvn35:geom:{kind.value}"
    with pytest.raises(ValueError, match="geom이 필수"):
        Feature(
            feature_id=feature_id,
            kind=kind,
            name="지오메트리 없는 경로/구역",
            category="03000000",
            marker_icon="park",
            marker_color="P-06",
            coord=Coordinate(lon=127.0, lat=37.5),
            address=Address(),
            geom=None,
            detail=detail_factory(feature_id),
            created_at=_NOW,
            updated_at=_NOW,
        )

    assert (
        await migrated_session.execute(
            text("SELECT count(*) FROM feature.features WHERE feature_id = :feature_id"),
            {"feature_id": feature_id},
        )
    ).scalar_one() == 0


async def test_geometry_on_non_route_area_kind_is_rejected() -> None:
    """place/event에 geometry를 실으면 담을 곳이 없다 — 구성 시점에 거부한다."""
    with pytest.raises(ValueError, match="geom을 가질 수 없다"):
        Feature(
            feature_id="tvn35:geom:place",
            kind=FeatureKind.PLACE,
            name="선을 가진 장소",
            category="01070100",
            marker_icon="place",
            marker_color="P-01",
            coord=Coordinate(lon=127.0, lat=37.5),
            address=Address(),
            geom=_ROUTE_WKT,
            detail=PlaceDetail(feature_id="tvn35:geom:place", place_kind="cafe"),
            created_at=_NOW,
            updated_at=_NOW,
        )


@pytest.mark.parametrize(
    ("kind", "wkt", "table", "detail_factory"),
    [
        (
            FeatureKind.ROUTE,
            _ROUTE_WKT,
            "feature_routes",
            lambda fid: RouteDetail(
                feature_id=fid, route_type="trail", geometry_source="knps"
            ),
        ),
        (
            FeatureKind.AREA,
            _AREA_WKT,
            "feature_areas",
            lambda fid: AreaDetail(
                feature_id=fid, area_kind="protected_area", boundary_source="gis_spca"
            ),
        ),
    ],
)
async def test_route_and_area_with_geometry_land_in_subtype(
    migrated_session: AsyncSession,
    kind: FeatureKind,
    wkt: str,
    table: str,
    detail_factory: Any,
) -> None:
    """geometry가 있으면 subtype에 Multi* 타입으로 승격 저장되고 뷰가 되돌려준다."""
    feature_id = f"tvn35:geom-ok:{kind.value}"
    feature = Feature(
        feature_id=feature_id,
        kind=kind,
        name="지오메트리 있는 경로/구역",
        category="03000000",
        marker_icon="park",
        marker_color="P-06",
        address=Address(),
        geom=wkt,
        detail=detail_factory(feature_id),
        created_at=_NOW,
        updated_at=_NOW,
    )
    await feature_repo.upsert_feature(migrated_session, feature)
    await migrated_session.flush()

    geometry_type = (
        await migrated_session.execute(
            text(
                f"SELECT x_extension.ST_GeometryType(geom) FROM feature.{table} "
                "WHERE feature_id = :feature_id"
            ),
            {"feature_id": feature_id},
        )
    ).scalar_one()
    assert geometry_type == (
        "ST_MultiLineString" if kind is FeatureKind.ROUTE else "ST_MultiPolygon"
    )

    assembled = await _detail_from_view(migrated_session, feature_id)
    model = RouteDetail if kind is FeatureKind.ROUTE else AreaDetail
    assert model.model_validate(assembled) == feature.detail

    # core에는 geometry가 없다 — 뷰가 subtype에서 제공한다.
    view_geom = (
        await migrated_session.execute(
            text(
                "SELECT x_extension.ST_GeometryType(geom) "
                "FROM feature.features_detailed WHERE feature_id = :feature_id"
            ),
            {"feature_id": feature_id},
        )
    ).scalar_one()
    assert view_geom == geometry_type


# ---------------------------------------------------------------------------
# ④ notice lifecycle — typed 컬럼 갱신 + typed 비교 read 필터
# ---------------------------------------------------------------------------


async def test_supersede_writes_typed_valid_end_time_and_read_filter_hides_it(
    migrated_session: AsyncSession,
) -> None:
    """feed 소멸 supersede가 typed ``valid_end_time``을 쓰고 공개 read가 감산한다."""
    feature = _notice_feature("tvn35:lifecycle:notice", valid_end_time=None)
    await feature_repo.load_bundle(
        migrated_session,
        _bundle(
            feature,
            source_entity_id="LC-1",
            raw_data={
                "occurred_date": "2026.08.06",
                "occurred_time": "07:25:43",
                "route_no": "0550",
                "direction": "부산방향",
                "point_name": "남제천(272.5k)",
                "incident_type_code": "03",
            },
        ),
    )
    await migrated_session.flush()

    visible = await feature_repo.public_active_notice_feature_identities(
        migrated_session, ["tvn35:lifecycle:notice"]
    )
    assert set(visible) == {"tvn35:lifecycle:notice"}

    # supersede 판정은 DB ``now()``와 비교되므로 실시계 기준 과거 시각을 쓴다.
    closed_at = datetime.now(_KST) - timedelta(hours=1)
    await feature_repo.supersede_stale_notice_features(
        migrated_session,
        provider="python-krex-api",
        dataset_key="krex_traffic_notices",
        source_entity_type="traffic_notice",
        active_lineage_keys=[],
        closed_at=closed_at,
    )
    await migrated_session.flush()

    row = await _subtype_row(
        migrated_session, "feature_notices", "tvn35:lifecycle:notice"
    )
    assert row is not None
    assert row["valid_end_time"] == closed_at

    # 조립 뷰의 detail도 같은 값을 돌려준다(조립 규칙이 한 곳이라 갈라지지 않는다).
    assembled = await _detail_from_view(migrated_session, "tvn35:lifecycle:notice")
    assert NoticeDetail.model_validate(assembled).valid_end_time == closed_at

    # typed 비교 read 필터가 종료된 notice를 감산한다.
    assert (
        await feature_repo.public_active_notice_feature_identities(
            migrated_session, ["tvn35:lifecycle:notice"]
        )
        == {}
    )


async def test_purge_expired_notices_reads_typed_columns(
    migrated_session: AsyncSession,
) -> None:
    """purge가 typed ``valid_end_time``/``valid_start_time``으로 보존 기간을 판정한다."""
    expired_id = "tvn35:purge:expired"
    fresh_id = "tvn35:purge:fresh"
    start_only_id = "tvn35:purge:start-only"

    for feature_id, end_time, start_time in (
        (expired_id, _NOW - timedelta(days=800), _NOW - timedelta(days=810)),
        (fresh_id, _NOW - timedelta(days=1), _NOW - timedelta(days=2)),
        (start_only_id, None, _NOW - timedelta(days=800)),
    ):
        feature_uuid = await _insert_core(
            migrated_session, feature_id=feature_id, kind="notice", category="99000000"
        )
        await _insert_subtype(
            migrated_session,
            feature_id=feature_id,
            feature_uuid=feature_uuid,
            kind="notice",
            detail={
                "notice_type": "traffic",
                "valid_start_time": start_time.isoformat(),
                "valid_end_time": end_time.isoformat() if end_time else None,
            },
        )

    purged = await feature_repo.purge_expired_notices(migrated_session)
    await migrated_session.flush()
    assert purged == 2

    statuses = dict(
        (
            await migrated_session.execute(
                text(
                    "SELECT feature_id, status FROM feature.features "
                    "WHERE feature_id = ANY(CAST(:ids AS text[]))"
                ),
                {"ids": [expired_id, fresh_id, start_only_id]},
            )
        ).all()
    )
    assert statuses[expired_id] == "inactive"
    assert statuses[start_only_id] == "inactive"
    assert statuses[fresh_id] == "active"


# ---------------------------------------------------------------------------
# ⑤ merge — cross-kind 거부 / same-kind 정상
# ---------------------------------------------------------------------------


async def test_cross_kind_merge_is_rejected(migrated_session: AsyncSession) -> None:
    """kind가 다른 두 feature 병합은 ``MergeConflictError``로 fail-close한다.

    kind가 어느 subtype에 값이 사는지를 결정하므로 이종 병합은 "provider 정체성만
    옮기고 typed 값은 남기는" 상태가 되어 무결성을 직접 깬다(ADR-084 결과절).
    """
    await _seed_place(migrated_session, "tvn35:merge:place")
    event_uuid = await _insert_core(
        migrated_session, feature_id="tvn35:merge:event", kind="event", category="01010100"
    )
    await _insert_subtype(
        migrated_session,
        feature_id="tvn35:merge:event",
        feature_uuid=event_uuid,
        kind="event",
        detail={"event_kind": "festival"},
    )

    with pytest.raises(MergeConflictError, match="kind가 다른"):
        await merge_repo.apply_feature_merge(
            migrated_session,
            master_id="tvn35:merge:place",
            loser_id="tvn35:merge:event",
            merged_by="tvn35-test",
        )


async def test_same_kind_merge_keeps_master_subtype_and_preserves_loser(
    migrated_session: AsyncSession,
) -> None:
    """같은 kind 병합은 정상 동작하고, loser subtype은 ADR-017대로 남는다."""
    await _seed_place(migrated_session, "tvn35:merge:master", place_kind="cafe")
    await _seed_place(migrated_session, "tvn35:merge:loser", place_kind="restaurant")

    await merge_repo.apply_feature_merge(
        migrated_session,
        master_id="tvn35:merge:master",
        loser_id="tvn35:merge:loser",
        merged_by="tvn35-test",
    )
    await migrated_session.flush()

    loser_status = (
        await migrated_session.execute(
            text("SELECT status FROM feature.features WHERE feature_id = :feature_id"),
            {"feature_id": "tvn35:merge:loser"},
        )
    ).scalar_one()
    assert loser_status == "deleted"
    # soft-delete는 core-only라 CASCADE가 발동하지 않는다 — typed 값이 보존된다.
    assert (
        await _subtype_row(migrated_session, "feature_places", "tvn35:merge:loser")
    ) is not None
    master_row = await _subtype_row(
        migrated_session, "feature_places", "tvn35:merge:master"
    )
    assert master_row is not None
    assert master_row["place_kind"] == "cafe"


# ---------------------------------------------------------------------------
# ⑥ migration 왕복 — downgrade 0083 → upgrade head 무손실 (md5 대조)
# ---------------------------------------------------------------------------

_ROUNDTRIP_PRE_REVISION = "0083_nonderived_uuid_generator"

_ROUNDTRIP_SEED_SQL = """
INSERT INTO feature.features (feature_id, kind, name, category, status, updated_at)
VALUES
    ('tvn35:mig:place', 'place', '왕복 장소', '01070100', 'active', now()),
    ('tvn35:mig:event', 'event', '왕복 축제', '01010100', 'active', now()),
    ('tvn35:mig:notice', 'notice', '왕복 공지', '99000000', 'active', now()),
    ('tvn35:mig:route', 'route', '왕복 경로', '03000000', 'active', now()),
    ('tvn35:mig:area', 'area', '왕복 구역', '03000000', 'active', now())
"""

# 조립 detail의 정본 대조값 — feature_id 순 md5. core 컬럼(0083 이하)과 뷰
# (0086 이상) 어느 쪽에서 읽어도 같아야 무손실이다.
_DETAIL_DIGEST_SQL = """
SELECT feature_id, md5(detail::text) AS digest
FROM {relation}
WHERE feature_id LIKE 'tvn35:mig:%'
ORDER BY feature_id
"""


def _run_alembic(dsn: str, revision: str, *, downgrade: bool = False) -> None:
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", dsn)
    if downgrade:
        command.downgrade(config, revision)
    else:
        command.upgrade(config, revision)


async def _fresh_database(pg_container: Any) -> str:
    admin_dsn = normalize_async_dsn(pg_container.get_connection_url())
    database = f"tvn35_subtypes_{uuid4().hex}"
    admin_engine = make_async_engine(admin_dsn)
    try:
        async with admin_engine.connect() as connection:
            autocommit = await connection.execution_options(isolation_level="AUTOCOMMIT")
            await autocommit.execute(text(f'CREATE DATABASE "{database}"'))
    finally:
        await admin_engine.dispose()
    return make_url(admin_dsn).set(database=database).render_as_string(hide_password=False)


async def _seed_subtypes_at_head(dsn: str) -> None:
    """head 상태에서 core + subtype 5종을 심는다(값 정본은 subtype)."""
    engine = make_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET search_path = public, x_extension"))
            await conn.execute(text(_ROUNDTRIP_SEED_SQL))
            uuids = dict(
                (
                    await conn.execute(
                        text(
                            "SELECT feature_id, CAST(feature_uuid AS text) "
                            "FROM feature.features WHERE feature_id LIKE 'tvn35:mig:%'"
                        )
                    )
                ).all()
            )
            seeds: tuple[tuple[str, str, dict[str, Any], str | None], ...] = (
                (
                    "tvn35:mig:place",
                    "place",
                    {
                        "place_kind": "cafe",
                        "phones": ["02-1234-5678"],
                        "biz_number": "123-45-67890",
                        "license_date": "2024-03-01",
                        "facility_info": {"seats": 40, "wifi": None},
                        "payload": {"origin": "tvn35"},
                    },
                    None,
                ),
                (
                    "tvn35:mig:event",
                    "event",
                    {
                        "event_kind": "festival",
                        "starts_on": "2026-08-01",
                        "ends_on": "2026-08-10",
                        "venue_name": "여의도공원",
                        "payload": {"origin": "tvn35"},
                    },
                    None,
                ),
                (
                    "tvn35:mig:notice",
                    "notice",
                    {
                        "notice_type": "traffic",
                        "severity": 2,
                        "valid_start_time": "2026-08-05T10:00:00+09:00",
                        "valid_end_time": "2026-08-09T10:00:00+09:00",
                        "payload": {"domain": "highway"},
                    },
                    None,
                ),
                (
                    "tvn35:mig:route",
                    "route",
                    {"route_type": "trail", "geometry_source": "knps", "payload": {}},
                    _ROUTE_WKT,
                ),
                (
                    "tvn35:mig:area",
                    "area",
                    {"area_kind": "protected_area", "payload": {}},
                    _AREA_WKT,
                ),
            )
            for feature_id, kind, detail, geom_wkt in seeds:
                sql = subtype_upsert_sql(kind)
                assert sql is not None
                params = subtype_params(
                    feature_id=feature_id,
                    feature_uuid=str(uuids[feature_id]),
                    kind=kind,
                    detail=detail,
                )
                assert params is not None
                if geom_wkt is not None:
                    params["geom_wkt"] = geom_wkt
                await conn.execute(text(sql), params)
    finally:
        await engine.dispose()


async def _detail_digests(dsn: str, relation: str) -> dict[str, str]:
    engine = make_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET search_path = public, x_extension"))
            rows = (
                await conn.execute(text(_DETAIL_DIGEST_SQL.format(relation=relation)))
            ).all()
    finally:
        await engine.dispose()
    return {str(feature_id): str(digest) for feature_id, digest in rows}


async def test_subtype_migration_round_trip_is_lossless(pg_container: Any) -> None:
    """``head`` → ``0083`` → ``head`` 왕복에서 조립 detail이 md5까지 동일하다.

    0086 downgrade는 뷰와 **같은 식**으로 core ``detail``/``geom``을 역조립한다.
    무손실이 아니면 롤백 가능성이 사라지므로, ADR-084 근거절의 731k행 전수 대조를
    회귀 가드 크기로 축소해 상시 고정한다.
    """
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, "head")
    await _seed_subtypes_at_head(dsn)

    at_head = await _detail_digests(dsn, "feature.features_detailed")
    assert set(at_head) == {
        "tvn35:mig:area",
        "tvn35:mig:event",
        "tvn35:mig:notice",
        "tvn35:mig:place",
        "tvn35:mig:route",
    }

    # downgrade — core detail/geom 역조립.
    await asyncio.to_thread(_run_alembic, dsn, _ROUNDTRIP_PRE_REVISION, downgrade=True)
    at_pre = await _detail_digests(dsn, "feature.features")
    assert at_pre == at_head

    geometry_kinds = await _geometry_types_on_core(dsn)
    assert geometry_kinds == {
        "tvn35:mig:route": "ST_MultiLineString",
        "tvn35:mig:area": "ST_MultiPolygon",
    }

    # 다시 head로 — backfill이 같은 값을 typed 컬럼으로 되돌린다.
    await asyncio.to_thread(_run_alembic, dsn, "head")
    assert await _detail_digests(dsn, "feature.features_detailed") == at_head


#: 0084 이전 세대가 실제로 저장하던 detail — ``Feature.detail.model_dump(mode="json")``
#: 그대로다. 값은 DTO에서 만들어 "옛 writer가 쓴 바이트"와 어긋날 수 없게 한다.
def _legacy_detail_seeds() -> dict[str, tuple[str, dict[str, Any], str | None]]:
    return {
        "tvn35:legacy:place": (
            "place",
            PlaceDetail(
                feature_id="tvn35:legacy:place",
                place_kind="cafe",
                phones=["02-1234-5678", "02-2222-3333"],
                biz_number="123-45-67890",
                license_date=date(2024, 3, 1),
                # 중첩 null은 provider 원문의 일부다 — 조립이 지우면 안 된다
                # (``jsonb_strip_nulls`` 결함이 여기서 잡혔다).
                facility_info={"seats": 40, "wifi": None, "nested": {"a": None}},
                reviews_link={"naver": "https://map.naver.com/v5/entry/place/1"},
                payload={"origin": "legacy", "raw": {"memo": None}},
            ).model_dump(mode="json"),
            None,
        ),
        "tvn35:legacy:event": (
            "event",
            EventDetail(
                feature_id="tvn35:legacy:event",
                event_kind="cultural_festival",
                starts_on=date(2026, 8, 1),
                ends_on=date(2026, 8, 10),
                venue_name="여의도공원",
                area_code="1",
                # 이 필드가 subtype 컬럼에서 빠져 있던 것이 전수 대조로 드러났다.
                sigungu_code="11140",
                payload={"origin": "legacy"},
            ).model_dump(mode="json"),
            None,
        ),
        "tvn35:legacy:notice": (
            "notice",
            NoticeDetail(
                feature_id="tvn35:legacy:notice",
                notice_type="traffic",
                severity=3,
                valid_start_time=datetime(2026, 8, 5, 17, 35, 24, tzinfo=_KST),
                valid_end_time=datetime(2026, 8, 9, 10, 0, tzinfo=_KST),
                source_agency="한국도로공사",
                payload={"domain": "highway", "krex_grade": None},
            ).model_dump(mode="json"),
            None,
        ),
        "tvn35:legacy:route": (
            "route",
            RouteDetail(
                feature_id="tvn35:legacy:route",
                route_type="trail",
                geometry_source="knps",
                total_distance_meters=Decimal("1234.567"),
                expected_duration_minutes=90,
                payload={"origin": "legacy"},
            ).model_dump(mode="json"),
            _ROUTE_WKT,
        ),
        "tvn35:legacy:area": (
            "area",
            AreaDetail(
                feature_id="tvn35:legacy:area",
                area_kind="protected_area",
                area_square_meters=Decimal("98765.43"),
                administrative_office="국립공원공단",
                payload={"origin": "legacy"},
            ).model_dump(mode="json"),
            _AREA_WKT,
        ),
    }


async def _seed_legacy_detail_at_pre_revision(dsn: str) -> None:
    """0083 세대의 core ``detail``/``geom``에 옛 writer가 쓰던 그대로 심는다."""
    engine = make_async_engine(dsn)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("SET search_path = public, x_extension"))
            for index, (feature_id, (kind, detail, wkt)) in enumerate(
                sorted(_legacy_detail_seeds().items())
            ):
                await conn.execute(
                    text(
                        "INSERT INTO feature.features ("
                        " feature_id, kind, name, category, status, updated_at,"
                        " detail, geom) VALUES ("
                        " :feature_id, :kind, :name, :category, 'active', now(),"
                        " CAST(:detail AS jsonb),"
                        " CASE WHEN :wkt IS NULL THEN NULL"
                        "      ELSE x_extension.ST_GeomFromText(:wkt, 4326) END)"
                    ),
                    {
                        "feature_id": feature_id,
                        "kind": kind,
                        "name": f"legacy fixture {index}",
                        "category": "01070100" if kind != "notice" else "99000000",
                        "detail": json.dumps(detail, ensure_ascii=False),
                        "wkt": wkt,
                    },
                )
    finally:
        await engine.dispose()


async def test_legacy_detail_survives_forward_migration_byte_for_byte(
    pg_container: Any,
) -> None:
    """0083의 실제 ``detail`` JSONB가 조립 결과와 **바이트까지** 같아야 한다.

    ``test_subtype_migration_round_trip_is_lossless``는 head에서 심어 head로
    돌아오는 닫힌 고리라, "옛 detail엔 있는데 subtype 컬럼과 뷰 **양쪽에** 없는
    필드"를 원리상 볼 수 없다 — ``EventDetail.sigungu_code`` 결함이 정확히 그
    모양이었다. 이 테스트는 반대 방향, 즉 마이그레이션이 실제로 통과시켜야 하는
    입력에서 출발한다.

    notice 시각만 예외다: 종전 저장 표기가 writer마다 갈렸고(ADR-084 결정 4)
    KST 고정 렌더로 통일했다. 그래도 Python ``isoformat()`` 표기와는 같으므로
    DTO가 만든 위 시드는 바이트까지 보존된다.
    """
    dsn = await _fresh_database(pg_container)
    await asyncio.to_thread(_run_alembic, dsn, _ROUNDTRIP_PRE_REVISION)
    await _seed_legacy_detail_at_pre_revision(dsn)

    before = await _detail_json(dsn, "feature.features", "tvn35:legacy:%")
    await asyncio.to_thread(_run_alembic, dsn, "head")
    after = await _detail_json(dsn, "feature.features_detailed", "tvn35:legacy:%")

    assert set(after) == set(_legacy_detail_seeds())
    for feature_id, expected in sorted(before.items()):
        assert after[feature_id] == expected, feature_id


async def _detail_json(dsn: str, relation: str, pattern: str) -> dict[str, Any]:
    engine = make_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET search_path = public, x_extension"))
            rows = (
                await conn.execute(
                    text(
                        f"SELECT feature_id, detail::text FROM {relation} "
                        "WHERE feature_id LIKE :pattern ORDER BY feature_id"
                    ),
                    {"pattern": pattern},
                )
            ).all()
    finally:
        await engine.dispose()
    return {str(feature_id): json.loads(detail) for feature_id, detail in rows}


async def _geometry_types_on_core(dsn: str) -> dict[str, str]:
    engine = make_async_engine(dsn)
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SET search_path = public, x_extension"))
            rows = (
                await conn.execute(
                    text(
                        "SELECT feature_id, x_extension.ST_GeometryType(geom) "
                        "FROM feature.features "
                        "WHERE feature_id LIKE 'tvn35:mig:%' AND geom IS NOT NULL"
                    )
                )
            ).all()
    finally:
        await engine.dispose()
    return {str(feature_id): str(geometry_type) for feature_id, geometry_type in rows}


def test_subtype_table_map_covers_every_geometry_and_detail_kind() -> None:
    """subtype 대상 kind 집합은 5종 고정 — price/weather는 값 정본이 따로 있다."""
    assert set(SUBTYPE_TABLES) == {"place", "event", "notice", "route", "area"}
    assert subtype_upsert_sql("price") is None
    assert subtype_upsert_sql("weather") is None
