"""route geometry가 보조 relation으로 간 뒤에도 잃으면 안 되는 것들 (ADR-099 2단계).

ADR-086/`0087_route_area_subtypes`가 geometry를 subtype으로 옮긴 이유는 성능이
아니라 **불변식**이었다 — "geometry가 필수인 kind와 없어야 하는 kind가 술어가
아니라 테이블 구조로 갈린다". `feature_routes.geom NOT NULL`이 그 구조였다.

312가 geometry를 밖으로 빼면서 그 컬럼이 사라진다. 대체 fence는
`fk_feature_routes_geometry`(DEFERRABLE INITIALLY DEFERRED)이고, **이 파일의
첫 세 검사가 그것이 실제로 서 있는지를 센다.**

## 왜 COMMIT까지 가야 하는가

deferred 제약은 문장 직후에 발화하지 않는다. `INSERT` 다음 줄에서 assert하면
**FK가 아예 없어도 통과한다** — 검사가 자기 대상을 한 번도 안 보는 부류다.
그래서 여기서는 문장이 아니라 **트랜잭션**을 단위로 본다.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_ROUTE_WKT = "MULTILINESTRING((126.97 37.56, 126.98 37.57))"
_OTHER_WKT = "MULTILINESTRING((127.10 37.60, 127.11 37.61))"

_INSERT_FEATURE = text(
    """
    INSERT INTO feature.features (
        feature_id, kind, name, category, lifecycle_state,
        publication_state, quality_state
    ) VALUES (
        CAST(:feature_id AS uuid), 'route', :name, '99000000',
        'active', 'published', 'valid'
    )
    """
)

_INSERT_ROUTE = text(
    """
    INSERT INTO feature.feature_routes (feature_id, kind, route_type)
    VALUES (CAST(:feature_id AS uuid), 'route', 'trail')
    """
)

_INSERT_GEOMETRY = text(
    """
    INSERT INTO feature.feature_route_geometries (feature_id, kind, geom)
    VALUES (
        CAST(:feature_id AS uuid), 'route',
        CAST(x_extension.ST_Multi(x_extension.ST_SetSRID(
            x_extension.ST_GeomFromText(CAST(:wkt AS text)), 4326))
        AS x_extension.geometry(MultiLineString, 4326))
    )
    """
)


def _fresh_id() -> str:
    return str(uuid.uuid4())


async def test_a_route_without_geometry_cannot_commit(
    migrated_engine: AsyncEngine,
) -> None:
    """**핵심.** geometry 없는 route는 COMMIT에서 거절된다.

    ADR-086의 `geom NOT NULL`을 대체하는 장치다. 문장 직후가 아니라 COMMIT에서
    판정되므로, 이 검사가 트랜잭션을 끝까지 가져가지 않으면 FK가 없어도 통과한다.
    """

    feature_id = _fresh_id()

    async def _route_without_geometry() -> None:
        async with migrated_engine.begin() as conn:
            await conn.execute(
                _INSERT_FEATURE, {"feature_id": feature_id, "name": "no-geom"}
            )
            await conn.execute(_INSERT_ROUTE, {"feature_id": feature_id})
            # geometry를 넣지 않는다 — 여기서는 아직 아무 일도 일어나지 않는다.
            # 판정은 이 블록을 **빠져나가는 COMMIT**에서 난다.

    with pytest.raises(IntegrityError) as raised:
        await _route_without_geometry()
    assert "23503" in str(raised.value) or "foreign key" in str(raised.value).lower(), (
        f"geometry 없는 route가 COMMIT됐거나 다른 이유로 죽었다: {raised.value}"
    )


async def test_removing_the_geometry_cannot_commit(
    migrated_engine: AsyncEngine,
) -> None:
    """이미 있는 route의 geometry만 지우는 것도 막힌다."""

    feature_id = _fresh_id()
    async with migrated_engine.begin() as conn:
        await conn.execute(_INSERT_FEATURE, {"feature_id": feature_id, "name": "with-geom"})
        await conn.execute(_INSERT_ROUTE, {"feature_id": feature_id})
        await conn.execute(_INSERT_GEOMETRY, {"feature_id": feature_id, "wkt": _ROUTE_WKT})

    with pytest.raises(IntegrityError):
        async with migrated_engine.begin() as conn:
            await conn.execute(
                text(
                    "DELETE FROM feature.feature_route_geometries"
                    " WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": feature_id},
            )


async def test_either_insertion_order_commits(
    migrated_engine: AsyncEngine,
) -> None:
    """**늘 거절하는 fence는 fence가 아니다.** geometry를 먼저 넣어도 통과한다.

    DEFERRABLE이어야 하는 이유가 여기 있다 — 한 트랜잭션 안의 순서를 강제하면
    재적재·purge CASCADE가 중간 상태에서 죽는다.
    """

    feature_id = _fresh_id()
    async with migrated_engine.begin() as conn:
        await conn.execute(_INSERT_FEATURE, {"feature_id": feature_id, "name": "geom-first"})
        await conn.execute(_INSERT_GEOMETRY, {"feature_id": feature_id, "wkt": _ROUTE_WKT})
        await conn.execute(_INSERT_ROUTE, {"feature_id": feature_id})

    async with migrated_engine.connect() as conn:
        found = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM feature.feature_routes"
                    " WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": feature_id},
            )
        ).scalar_one()
    assert found == 1, "geometry를 먼저 넣은 정상 트랜잭션이 거절됐다."


async def test_geom_digest_follows_the_geometry(
    migrated_engine: AsyncEngine,
) -> None:
    """생성 컬럼이므로 **어떤 쓰기 경로로 바꿔도** 지문이 따라간다.

    봉인은 geometry 자체가 아니라 이 지문을 본다. 지문이 따라가지 않으면
    "geometry만 바뀐 재적재"가 같은 해시를 내고, 기존 검사는 전부 초록이다.
    """

    feature_id = _fresh_id()
    async with migrated_engine.begin() as conn:
        await conn.execute(_INSERT_FEATURE, {"feature_id": feature_id, "name": "digest"})
        await conn.execute(_INSERT_GEOMETRY, {"feature_id": feature_id, "wkt": _ROUTE_WKT})
        await conn.execute(_INSERT_ROUTE, {"feature_id": feature_id})

    async def _digest() -> str:
        async with migrated_engine.connect() as conn:
            return str(
                (
                    await conn.execute(
                        text(
                            "SELECT geom_digest FROM feature.feature_route_geometries"
                            " WHERE feature_id = CAST(:feature_id AS uuid)"
                        ),
                        {"feature_id": feature_id},
                    )
                ).scalar_one()
            )

    before = await _digest()
    assert len(before) == 64, f"지문이 64자 hex가 아니다: {before!r}"

    # **프로시저를 우회한 직접 UPDATE.** 이 경로가 덮이는 것이 생성 컬럼을 고른
    # 이유다 — 트리거였다면 `UPDATE OF geom_digest`가 발화하지 않는다.
    async with migrated_engine.begin() as conn:
        await conn.execute(
            text(
                "UPDATE feature.feature_route_geometries"
                " SET geom = CAST(x_extension.ST_Multi(x_extension.ST_SetSRID("
                "   x_extension.ST_GeomFromText(CAST(:wkt AS text)), 4326))"
                " AS x_extension.geometry(MultiLineString, 4326))"
                " WHERE feature_id = CAST(:feature_id AS uuid)"
            ),
            {"feature_id": feature_id, "wkt": _OTHER_WKT},
        )

    after = await _digest()
    assert after != before, (
        "geometry를 직접 UPDATE했는데 지문이 그대로다 — 봉인이 그 변경을 못 본다."
    )


async def test_identical_geometry_reload_does_not_rewrite_the_row(
    migrated_engine: AsyncEngine,
) -> None:
    """같은 geometry를 다시 써도 행을 건드리지 않는다.

    geometry는 큰 컬럼이고 GiST 인덱스가 달려 있다 — 동일 재적재가 57,060행을
    다시 쓰면 인덱스가 그만큼 더럽혀진다. 판정은 `xmin`으로 한다(행이 실제로
    새로 쓰였는가).
    """

    feature_id = _fresh_id()
    async with migrated_engine.begin() as conn:
        await conn.execute(_INSERT_FEATURE, {"feature_id": feature_id, "name": "quiet"})
        await conn.execute(_INSERT_GEOMETRY, {"feature_id": feature_id, "wkt": _ROUTE_WKT})
        await conn.execute(_INSERT_ROUTE, {"feature_id": feature_id})

    async def _xmin() -> str:
        async with migrated_engine.connect() as conn:
            return str(
                (
                    await conn.execute(
                        text(
                            "SELECT xmin::text FROM feature.feature_route_geometries"
                            " WHERE feature_id = CAST(:feature_id AS uuid)"
                        ),
                        {"feature_id": feature_id},
                    )
                ).scalar_one()
            )

    from kortravelmap.infra.feature_subtype import geometry_upsert_sql

    statement = geometry_upsert_sql("route")
    assert statement is not None, "route geometry upsert 문장이 없다."

    before = await _xmin()
    async with migrated_engine.begin() as conn:
        await conn.execute(
            text(statement),
            {"feature_id": feature_id, "kind": "route", "geom_wkt": _ROUTE_WKT},
        )
    assert await _xmin() == before, "같은 geometry 재적재가 행을 다시 썼다."

    async with migrated_engine.begin() as conn:
        await conn.execute(
            text(statement),
            {"feature_id": feature_id, "kind": "route", "geom_wkt": _OTHER_WKT},
        )
    assert await _xmin() != before, (
        "**바뀐** geometry가 행을 다시 쓰지 않았다 — 쓰기-조용 조건이 너무 넓다."
    )


async def test_new_geometry_rows_become_public_ready(
    migrated_engine: AsyncEngine,
) -> None:
    """**핵심.** 새 geometry 행의 `public_ready`가 INSERT 시점에 채워진다.

    2026-09-19 적대 리뷰가 잡은 blocker다. provider가 넣는 feature는 DTO 기본값이
    active/published/valid라 **core 3축을 바꾸는 UPDATE가 일어나지 않고**, 그래서
    AFTER UPDATE 트리거는 영원히 발화하지 않는다. 값을 채우는 것은 INSERT 시점의
    BEFORE 트리거다. 그것이 없으면 `public_ready`가 false로 남고 공개 bbox가
    route를 **한 건도** 못 고른다 — 오류 없이 결과만 0건이라 조용하다.
    """

    feature_id = _fresh_id()
    async with migrated_engine.begin() as conn:
        await conn.execute(_INSERT_FEATURE, {"feature_id": feature_id, "name": "ready"})
        await conn.execute(_INSERT_GEOMETRY, {"feature_id": feature_id, "wkt": _ROUTE_WKT})
        await conn.execute(_INSERT_ROUTE, {"feature_id": feature_id})

    async with migrated_engine.connect() as conn:
        ready = (
            await conn.execute(
                text(
                    "SELECT public_ready FROM feature.feature_route_geometries"
                    " WHERE feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": feature_id},
            )
        ).scalar_one()
    assert ready is True, (
        "published/active/valid feature의 geometry 행이 public_ready=false다 — "
        "파생 트리거가 없어 공개 bbox에서 route가 영원히 0건이 된다."
    )


async def test_the_public_bbox_predicate_actually_returns_the_route(
    migrated_engine: AsyncEngine,
) -> None:
    """술어를 **행이 있는 상태로** 태운다.

    EXPLAIN만 보는 검사는 빈 표에서도 초록이다 — 자기 대상을 한 번도 안 본다.
    여기서는 실제로 bbox 안에 route를 넣고 그것이 후보로 **나오는지**를 센다.
    """

    feature_id = _fresh_id()
    async with migrated_engine.begin() as conn:
        await conn.execute(_INSERT_FEATURE, {"feature_id": feature_id, "name": "bbox"})
        await conn.execute(_INSERT_GEOMETRY, {"feature_id": feature_id, "wkt": _ROUTE_WKT})
        await conn.execute(_INSERT_ROUTE, {"feature_id": feature_id})

    async with migrated_engine.connect() as conn:
        hits = (
            await conn.execute(
                text(
                    "SELECT count(*) FROM feature.feature_route_geometries AS hit"
                    " WHERE hit.public_ready"
                    "   AND hit.geom OPERATOR(x_extension.&&)"
                    "       x_extension.ST_MakeEnvelope(126.9, 37.5, 127.0, 37.6, 4326)"
                    "   AND x_extension.ST_Intersects(hit.geom,"
                    "       x_extension.ST_MakeEnvelope(126.9, 37.5, 127.0, 37.6, 4326))"
                    "   AND hit.feature_id = CAST(:feature_id AS uuid)"
                ),
                {"feature_id": feature_id},
            )
        ).scalar_one()
    assert hits == 1, (
        "bbox 안의 published route가 공개 후보 술어에 잡히지 않는다 — "
        "공개 지도에서 route가 통째로 사라진다."
    )


async def test_the_public_bbox_predicate_still_uses_the_partial_gist(
    migrated_engine: AsyncEngine,
) -> None:
    """공개 bbox가 **조인 없이** partial GiST를 그대로 탄다.

    `public_ready`를 보조 relation에 복제한 이유가 이것이다. 복제하지 않으면 이
    술어가 `feature_routes`와 조인해야 하고, ADR-086이 EXPLAIN으로 실측한
    "술어가 subtype GiST를 직접 탄다"는 성질을 잃는다.
    """

    async with migrated_engine.connect() as conn:
        await conn.execute(text("SET enable_seqscan = off"))
        plan = "\n".join(
            str(row[0])
            for row in (
                await conn.execute(
                    text(
                        "EXPLAIN SELECT feature_id"
                        " FROM feature.feature_route_geometries"
                        " WHERE public_ready"
                        "   AND geom OPERATOR(x_extension.&&)"
                        "       x_extension.ST_MakeEnvelope(126.9, 37.5, 127.0, 37.6, 4326)"
                    )
                )
            ).all()
        )
    assert "idx_feature_route_geometries_geom_gist" in plan, (
        f"bbox 술어가 보조 relation의 partial GiST를 타지 않는다:\n{plan}"
    )


async def test_feature_routes_no_longer_carries_geometry(
    migrated_engine: AsyncEngine,
) -> None:
    """이전이 실제로 끝났는지 카탈로그로 본다 — 마이그레이션 파일이 아니라 DB를."""

    async with migrated_engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    "SELECT attname FROM pg_attribute"
                    " WHERE attrelid = 'feature.feature_routes'::regclass"
                    "   AND attnum > 0 AND NOT attisdropped"
                )
            )
        ).scalars().all()
    assert "geom" not in rows, "feature_routes에 geom이 아직 있다 — 이전이 끝나지 않았다."
    assert "route_type" in rows, "비-공간 컬럼까지 사라졌다 — 이전 범위가 넘쳤다."
