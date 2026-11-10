"""``venue_candidates_repo`` — 장소 이름으로 좌표가 있는 공개 장소 Feature 후보를 읽는다(#1468 D).

국가유산 행사 장소 이름("진주성", "밀양향교")을 같은 시군구의 장소 Feature에 연결할 때 쓰는 후보
읽기다. 고르는 규칙은 순수 함수 :func:`kortravelmap.core.venue_match.match_venue`가 갖는다 — 이
모듈은 이름으로 넓게 읽기만 한다.

술어는 ``idx_features_name_trgm``(활성·공개·유효 부분 GIN trigram)을 타도록 같은 상태 술어를
쓰고 ``name ILIKE``로 거른다. 지역 비교는 표기가 섞여 있어(``전라남도``/``전남광주통합특별시``)
SQL이 아니라 호출자가 한다. 좌표는 ``coord``(4326)를 그대로 읽는다 — 술어에 좌표 변환이 없다
(ADR-012). raw SQL은 이 모듈의 상수다(ADR-004). 읽기 전용이다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

from kortravelmap.core.venue_match import VenueCandidate, venue_name_key
from kortravelmap.dto import Coordinate

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["VENUE_CANDIDATE_LIMIT", "find_venue_candidates", "venue_name_pattern"]

VENUE_CANDIDATE_LIMIT: Final[int] = 200
"""이름 하나당 읽는 후보 상한 — 지역 비교 전이라 넉넉히 읽는다."""

_FIND_SQL: Final = """
SELECT
    CAST(f.feature_id AS text) AS feature_id,
    f.name,
    x_extension.ST_X(f.coord) AS lon,
    x_extension.ST_Y(f.coord) AS lat,
    f.address ->> 'sido_name' AS sido_name,
    f.address ->> 'sigungu_name' AS sigungu_name,
    (
        SELECT dataset.dataset_key
        FROM provider_sync.source_links AS link
        JOIN provider_sync.source_entities AS entity
          ON entity.source_entity_key = link.source_entity_key
        JOIN provider_sync.provider_datasets AS dataset
          ON dataset.provider_dataset_id = entity.provider_dataset_id
        WHERE link.feature_id = f.feature_id
          AND link.source_role = 'primary'
        ORDER BY dataset.dataset_key
        LIMIT 1
    ) AS dataset_key
FROM feature.features AS f
WHERE f.lifecycle_state = 'active'
  AND f.publication_state = 'published'
  AND f.quality_state = 'valid'
  AND f.kind IN ('place', 'area')
  AND f.coord IS NOT NULL
  AND f.name ILIKE :pattern ESCAPE '\\'
ORDER BY f.feature_id
LIMIT :limit
"""


def venue_name_pattern(name: str) -> str | None:
    """이름 조각 → ``ILIKE`` 패턴(낱말 사이는 아무 글자나, LIKE 특수문자는 escape).

    비교 글자가 3자 미만이면 None — trigram 색인이 쓸 낱말이 없고 너무 넓다.
    """
    if len(venue_name_key(name)) < 3:
        return None
    words = [
        word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        for word in name.split()
    ]
    return "%" + "%".join(words) + "%"


async def find_venue_candidates(
    session: AsyncSession, *, name: str, limit: int = VENUE_CANDIDATE_LIMIT
) -> list[VenueCandidate]:
    """이름에 ``name``의 낱말이 차례로 든 활성·공개·유효 장소/면 Feature(좌표 있음)."""
    pattern = venue_name_pattern(name)
    if pattern is None:
        return []
    rows = (
        await session.execute(text(_FIND_SQL), {"pattern": pattern, "limit": limit})
    ).mappings()
    candidates: list[VenueCandidate] = []
    for row in rows:
        try:
            coord = Coordinate(lon=Decimal(str(row["lon"])), lat=Decimal(str(row["lat"])))
        except (ValueError, ArithmeticError):
            continue
        candidates.append(
            VenueCandidate(
                feature_id=str(row["feature_id"]),
                name=str(row["name"]),
                coord=coord,
                sido_name=row["sido_name"],
                sigungu_name=row["sigungu_name"],
                dataset_key=row["dataset_key"],
            )
        )
    return candidates
