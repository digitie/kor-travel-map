"""pg_prewarm 부팅 후 warm-up 헬퍼 (T-102).

배포/재기동 직후 hot read path relation(테이블·인덱스)을 `pg_prewarm`으로 shared_buffers/
OS page cache에 끌어올려 첫 쿼리의 cold-start latency를 줄인다. 명시적 호출 경로이고,
autoprewarm background worker(서버 `shared_preload_libraries='pg_prewarm'` config)와는 별개다.

설계 노트:
- `x_extension.pg_prewarm(regclass)`를 쓴다(확장은 `x_extension` 스키마, ADR-008 / migration
  `0022_pg_prewarm_extension`).
- **opt-in / best-effort**: 확장이 없으면(`pg_prewarm` 미설치) no-op으로 `{}`를 돌려준다.
  존재하지 않는 relation은 `to_regclass`로 미리 걸러 조용히 건너뛴다(이름 drift에 견고).
- T-102는 도입 조건(명시적 P99 SLO + shared_buffers가 hot 데이터 fit)이 충족될 때 켠다
  (`docs/performance.md §9.5`). 본 헬퍼는 그 조건에서 부팅 훅/CLI/Dagster가 호출한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# hot read path (T-212d keyset 인덱스 + 공간 인덱스 + feature.features 본체).
# 존재하지 않는 이름은 ``to_regclass``로 자동 skip되므로 인덱스 rename에 견고.
DEFAULT_HOT_RELATIONS: tuple[str, ...] = (
    "feature.features",
    "feature.idx_features_coord_gist",
    "feature.idx_features_coord_5179_gist",
    "feature.idx_features_updated_keyset",
    "feature.idx_features_status_updated",
    "feature.idx_features_name_trgm",
    "provider_sync.source_records",
    "provider_sync.source_links",
)


async def prewarm_extension_available(session: AsyncSession) -> bool:
    """`pg_prewarm` 확장 설치 여부."""
    return (
        await session.execute(
            text("SELECT 1 FROM pg_extension WHERE extname = 'pg_prewarm'")
        )
    ).scalar_one_or_none() is not None


async def prewarm_relations(
    session: AsyncSession,
    relations: Sequence[str] = DEFAULT_HOT_RELATIONS,
) -> dict[str, int]:
    """주어진 relation을 `pg_prewarm`으로 buffer에 끌어올린다.

    반환: ``{relation: warmed_block_count}``. 확장 미설치면 빈 dict(no-op). 존재하지 않는
    relation은 결과에서 제외한다.
    """
    if not await prewarm_extension_available(session):
        return {}
    existing = (
        await session.execute(
            text(
                "SELECT rel FROM unnest(CAST(:rels AS text[])) AS rel "
                "WHERE to_regclass(rel) IS NOT NULL"
            ),
            {"rels": list(relations)},
        )
    ).scalars().all()
    warmed: dict[str, int] = {}
    for rel in existing:
        blocks = (
            await session.execute(
                text("SELECT x_extension.pg_prewarm(CAST(:rel AS regclass))"),
                {"rel": rel},
            )
        ).scalar_one()
        warmed[str(rel)] = int(blocks)
    return warmed
