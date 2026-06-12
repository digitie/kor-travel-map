"""``AreaDetail`` — Feature.kind='area'의 detail (MULTIPOLYGON).

ADR 참조
--------
- ADR-018 — ``Feature.detail``은 자유 dict 금지, AreaDetail로만 적재
- ADR-027 — ``area_kind`` Literal에 ``"hazard_zone"`` 추가 (위험지역 =
  지역 area, ``payload.hazard_type`` + ``payload.domain``으로 구체)
- ADR-028 amendment — KNPS ``protected_areas``는 ``"protected_area"``로 구체
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["AreaDetail", "AREA_KINDS"]


AreaKind = Literal[
    "area",
    "national_park",
    "provincial_park",
    "recreation_forest",
    "tourism_district",
    "beach",
    "campsite",
    "heritage_area",
    "natural_heritage_area",
    "buried_heritage_area",
    "hazard_zone",  # ADR-027
    "protected_area",  # ADR-028 amendment (KNPS protected areas)
    "other",
]

AREA_KINDS: Final[tuple[str, ...]] = (
    "area",
    "national_park",
    "provincial_park",
    "recreation_forest",
    "tourism_district",
    "beach",
    "campsite",
    "heritage_area",
    "natural_heritage_area",
    "buried_heritage_area",
    "hazard_zone",  # ADR-027
    "protected_area",  # ADR-028 amendment (KNPS protected areas)
    "other",
)


class AreaDetail(BaseModel):
    """Feature.kind='area'의 detail. geometry는 ``features.geom``
    (MULTIPOLYGON) 컬럼에 저장; 본 모델은 메타만.

    ADR-027: ``hazard_zone``일 때 ``payload.hazard_type`` (예: ``rockfall``,
    ``flash_flood``, ``wildlife``) + ``payload.domain`` (``forest``,
    ``coastal``, ...). ADR-028 amendment: ``protected_area``일 때
    ``payload.protection_type`` 보존.
    """

    model_config = ConfigDict(extra="forbid")

    feature_id: str
    area_kind: AreaKind = "area"
    boundary_source: str | None = Field(
        default=None,
        description="boundary 출처 (예: ``'gis_3070426'``, ``'gis_spca'``, ``'krforest'``).",
    )
    area_square_meters: Decimal | None = Field(default=None, ge=0)
    regulation_scope: str | None = None
    administrative_office: str | None = None
    description: str | None = None
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "ADR-027: ``hazard_zone``일 때 "
            "``{'hazard_type': 'rockfall|flash_flood|wildlife|...', "
            "'domain': 'forest|coastal|urban|...'}``. ADR-028 amendment: "
            "``protected_area``일 때 ``{'protection_type': 'special|...'}``."
        ),
    )
