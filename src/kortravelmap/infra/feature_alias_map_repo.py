"""``kortravelmap.infra.feature_alias_map_repo`` — alias-map 이관 표면 조회 (T-VN-32C).

consumer-rollout-v1 T-VN-32 "32C: PinVi를 UUID+alias contract로 선전환(검증된
alias map DB-to-DB 이관)"의 Map 측 read 표면이다. ``feature.feature_aliases``
전체를 canonical 순서(alias NFC UTF-8 byte 오름차순 — ``COLLATE "C"``)로
keyset 페이지 조회하고, 저장소 전체 checksum(merkle root)을
``core.feature_alias_map`` 순수 계약으로 계산한다.

fail-close 규율
---------------
- 조회된 모든 행은 core canonical 검증(NFC/trim/uuid canonical form/kind 닫힌
  집합)과 legacy 파생 검증(uuid5)을 통과해야 한다. 하나라도 어긋나면 DB 층
  보장(0079/0080/0081)이 뚫린 것이므로 페이지/checksum을 반환하는 대신
  :class:`FeatureAliasMapIntegrityError`로 즉시 실패한다.
- checksum은 단일 문(단일 snapshot) 조회 위에서 계산한다. 페이지 pull과
  checksum 대조 사이의 write drift는 소비자(PinVi)가 root 불일치로 감지하고
  재시도한다 — 이관·검증 window 동안 write fence를 유지하는 운영 규율은
  rollout artifact가 소유한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

from kortravelmap.core.feature_alias_map import (
    FeatureAliasMapRowV1,
    feature_alias_map_merkle_root,
    verify_legacy_alias_derivation,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FEATURE_ALIAS_MAP_PAGE_MAX_LIMIT",
    "FeatureAliasMapChecksum",
    "FeatureAliasMapIntegrityError",
    "FeatureAliasMapPage",
    "compute_feature_alias_map_checksum",
    "fetch_feature_alias_map_page",
]

FEATURE_ALIAS_MAP_PAGE_MAX_LIMIT: Final[int] = 1000
"""페이지당 최대 row 수 — 이관 소비자는 keyset(`after_alias`)으로 전체를 순회한다."""


class FeatureAliasMapIntegrityError(RuntimeError):
    """alias-map 행이 canonical/파생 계약을 위반 — DB 층 보장 붕괴 (fail-close)."""


@dataclass(frozen=True)
class FeatureAliasMapPage:
    """canonical 순서 페이지 — ``has_more``면 마지막 alias가 다음 keyset."""

    rows: tuple[FeatureAliasMapRowV1, ...]
    has_more: bool


@dataclass(frozen=True)
class FeatureAliasMapChecksum:
    """저장소 전체 alias-map checksum."""

    alias_count: int
    merkle_root: str


# COLLATE "C" — UTF-8 byte 순서. core 계약의 정렬 축(alias NFC UTF-8 byte
# 오름차순)과 동일하다 (저장 alias는 NFC 검증을 통과해야 하므로 byte 순서가
# 곧 canonical 순서다). 0081이 같은 collation의 keyset index를 만든다.
_PAGE_SQL: Final[str] = """
SELECT alias, CAST(feature_uuid AS text) AS feature_uuid, alias_kind
FROM feature.feature_aliases
WHERE CAST(:after_alias AS text) IS NULL
   OR alias COLLATE "C" > CAST(:after_alias AS text) COLLATE "C"
ORDER BY alias COLLATE "C"
LIMIT :limit
"""

_ALL_ROWS_SQL: Final[str] = """
SELECT alias, CAST(feature_uuid AS text) AS feature_uuid, alias_kind
FROM feature.feature_aliases
"""


def _canonical_row(alias: object, feature_uuid: object, alias_kind: object) -> FeatureAliasMapRowV1:
    try:
        row = FeatureAliasMapRowV1(
            alias=str(alias),
            feature_uuid=str(feature_uuid),
            alias_kind=str(alias_kind),
        )
        verify_legacy_alias_derivation(row)
    except ValueError as exc:
        raise FeatureAliasMapIntegrityError(
            "alias-map 행이 canonical/파생 계약을 위반했습니다 — DB 층 보장 "
            f"(0079/0080/0081)이 뚫린 상태이므로 이관을 중단합니다: {exc}"
        ) from exc
    return row


async def fetch_feature_alias_map_page(
    session: AsyncSession,
    *,
    after_alias: str | None,
    limit: int,
) -> FeatureAliasMapPage:
    """canonical 순서 keyset 페이지 — ``limit``은 1~``PAGE_MAX_LIMIT``."""
    if not 1 <= limit <= FEATURE_ALIAS_MAP_PAGE_MAX_LIMIT:
        raise ValueError(
            f"limit은 1~{FEATURE_ALIAS_MAP_PAGE_MAX_LIMIT} 범위여야 합니다 (got {limit})."
        )
    records = (
        (
            await session.execute(
                text(_PAGE_SQL),
                {"after_alias": after_alias, "limit": limit + 1},
            )
        )
        .mappings()
        .all()
    )
    rows = tuple(
        _canonical_row(record["alias"], record["feature_uuid"], record["alias_kind"])
        for record in records[:limit]
    )
    return FeatureAliasMapPage(rows=rows, has_more=len(records) > limit)


async def compute_feature_alias_map_checksum(
    session: AsyncSession,
) -> FeatureAliasMapChecksum:
    """저장소 전체 alias-map merkle root — 단일 문 snapshot 위에서 계산.

    전량을 메모리에 올린다(행당 수십 byte — 현재 ~1만 행, MOIS bulk 이후
    수십만 행에서도 수십 MB 수준). 이관 cutover 전용 표면이라 hot path가
    아니다.
    """
    records = (await session.execute(text(_ALL_ROWS_SQL))).mappings().all()
    rows = [
        _canonical_row(record["alias"], record["feature_uuid"], record["alias_kind"])
        for record in records
    ]
    return FeatureAliasMapChecksum(
        alias_count=len(rows),
        merkle_root=feature_alias_map_merkle_root(rows),
    )
