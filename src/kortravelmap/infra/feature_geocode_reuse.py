"""적재 전 geo 재사용 판정 — payload·좌표·스탬프가 그대로인 행의 저장 주소 열(ADR-116).

비-MOIS 적재는 run마다 모든 좌표를 역지오코딩했다. 그런데 ``load_bundle``은 payload가
같고(``became_current`` 거짓) 스탬프가 현재 토큰이면(stale 거짓) 주소 열을 쓰지 않는다 — 새 답은
버려진다. 이 모듈은 **변환 전에** "그런 행"과 그 저장 주소 열을 한 번에 읽는다.
호출자(``dagster/geo_reuse.py``)가 그 값을 역지오코더의 답으로 돌려줘 geo 왕복을 건너뛴다.

조건(ADR-116 결정 1)은 ``load_bundle``이 그 행을 쓰지 않을 조건과 같다:

- head의 현재 record가 bundle과 같은 payload hash다(``became_current``가 거짓인 조건),
- 스탬프가 ``called``이고 ``geo_data_token``이 run의 현재 토큰과 같다(ADR-109의 stale이 아니다),
- 저장 ``coord``의 경도·위도가 bundle 좌표와 정확히 같다 — SQL에서 float8로, 적재가 쓰는
  값(``float(coord.lon)``) 그대로 비교한다(``Decimal``과 float을 Python에서 비교하면 영영 같지
  않다),
- claim으로 풀린 Feature가 ``active``이고 주소 유도 열에 active override가 없다.

**읽기 전용이고 fence(``lock_feature_curation_write``)를 잡지 않는다** — ADR-113의 받기 단계(쓰기
transaction 밖)와 큐 경로의 결합 transaction 어디서 불러도 다른 writer를 막지 않는다. commit은
호출자 책임이다.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY, DOUBLE_PRECISION
from sqlalchemy.types import Text

from kortravelmap.infra.feature_geocode_load import ADDRESS_GEO_COLUMNS
from kortravelmap.infra.feature_repo import (
    _make_source_entity_key,
    resolve_active_provider_dataset_id,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto import FeatureBundle

__all__ = ["REUSE_READ_CHUNK", "read_reusable_geo_columns"]

#: 한 문장에 묻는 행 수 상한(unnest 배열 길이).
REUSE_READ_CHUNK: Final[int] = 1000

_FIELD_PATHS: Final[list[str]] = [f"core.{column}" for column in ADDRESS_GEO_COLUMNS]

_READ_REUSABLE_SQL: Final = text(
    """
WITH input AS (
    SELECT *
      FROM unnest(
          CAST(:feature_kinds AS text[]),
          CAST(:natural_keys AS text[]),
          CAST(:source_entity_keys AS text[]),
          CAST(:source_record_keys AS text[]),
          CAST(:raw_payload_hashes AS text[]),
          CAST(:lons AS double precision[]),
          CAST(:lats AS double precision[])
      ) AS input(
          feature_kind, natural_key, source_entity_key, source_record_key,
          raw_payload_hash, lon, lat
      )
), resolved AS (
    SELECT input.*,
           feature.resolve_provider_feature_id(
               CAST(:provider_dataset_id AS bigint), input.feature_kind, input.natural_key
           ) AS feature_id
      FROM input
)
SELECT resolved.source_record_key,
       feature.address, feature.legal_dong_code, feature.road_name_code,
       feature.road_address_management_no, feature.admin_dong_code,
       feature.sido_code, feature.sigungu_code
  FROM resolved
  JOIN feature.features AS feature
    ON feature.feature_id = resolved.feature_id
  JOIN provider_sync.source_entity_heads AS head
    ON head.source_entity_key = resolved.source_entity_key
  -- payload는 hash로 비교한다. load_bundle의 became_current는 DB가 확정한 canonical
  -- record key로 판정하고, conflict 경로의 DTO key는 그것과 다를 수 있다.
  JOIN provider_sync.source_records AS record
    ON record.source_record_key = head.current_source_record_key
   AND record.raw_payload_hash = resolved.raw_payload_hash
  JOIN feature.feature_geocode_stamps AS stamp
    ON stamp.feature_id = feature.feature_id
 WHERE feature.lifecycle_state = 'active'
   AND stamp.reverse_outcome = 'called'
   AND stamp.geo_data_token = CAST(:current_data_token AS text)
   AND feature.coord IS NOT NULL
   AND x_extension.ST_X(feature.coord) = resolved.lon
   AND x_extension.ST_Y(feature.coord) = resolved.lat
   AND NOT EXISTS (
       SELECT 1
         FROM ops.feature_overrides AS override
        WHERE override.feature_id = feature.feature_id
          AND override.status = 'active'
          AND override.field_path = ANY(CAST(:field_paths AS text[]))
   )
"""
).bindparams(
    bindparam("feature_kinds", type_=ARRAY(Text)),
    bindparam("natural_keys", type_=ARRAY(Text)),
    bindparam("source_entity_keys", type_=ARRAY(Text)),
    bindparam("source_record_keys", type_=ARRAY(Text)),
    bindparam("raw_payload_hashes", type_=ARRAY(Text)),
    bindparam("lons", type_=ARRAY(DOUBLE_PRECISION)),
    bindparam("lats", type_=ARRAY(DOUBLE_PRECISION)),
    bindparam("field_paths", type_=ARRAY(Text)),
)


_Probe = tuple[str, str, str, str, str, float, float]


def _probe(bundle: FeatureBundle) -> _Probe | None:
    feature = bundle.feature
    coord = feature.coord
    if coord is None or not feature.provider_natural_key:
        return None
    record = bundle.source_record
    return (
        feature.kind.value,
        str(feature.provider_natural_key),
        _make_source_entity_key(
            provider=record.provider,
            dataset_key=record.dataset_key,
            source_entity_type=record.source_entity_type,
            source_entity_id=record.source_entity_id,
        ),
        record.source_record_key,
        record.raw_payload_hash,
        float(coord.lon),
        float(coord.lat),
    )


async def read_reusable_geo_columns(
    session: AsyncSession,
    bundles: Sequence[FeatureBundle],
    *,
    current_data_token: str,
) -> dict[str, Mapping[str, Any]]:
    """재사용 조건을 만족하는 행의 ``source_record_key → 저장 주소 유도 열``(ADR-116 결정 1).

    값은 ``ADDRESS_GEO_COLUMNS``(``address`` jsonb + 코드 6개)를 키로 갖는다 —
    ``address_column_values``와 같은 모양이라 호출자가 그대로 비교한다. 좌표·natural key가 없는
    bundle, 활성 dataset이 아닌 pair의 bundle은 묻지 않는다(결과에 없다 — 호출자는 geo를 부른다).
    """
    groups: dict[tuple[str, str], list[_Probe]] = defaultdict(list)
    for bundle in bundles:
        probe = _probe(bundle)
        if probe is not None:
            groups[(bundle.source_record.provider, bundle.source_record.dataset_key)].append(probe)
    found: dict[str, Mapping[str, Any]] = {}
    for (provider, dataset_key), probes in groups.items():
        try:
            provider_dataset_id = await resolve_active_provider_dataset_id(
                session, provider=provider, dataset_key=dataset_key
            )
        except LookupError:
            continue
        for start in range(0, len(probes), REUSE_READ_CHUNK):
            chunk = probes[start : start + REUSE_READ_CHUNK]
            rows = (
                await session.execute(
                    _READ_REUSABLE_SQL,
                    {
                        "provider_dataset_id": provider_dataset_id,
                        "current_data_token": current_data_token,
                        "feature_kinds": [probe[0] for probe in chunk],
                        "natural_keys": [probe[1] for probe in chunk],
                        "source_entity_keys": [probe[2] for probe in chunk],
                        "source_record_keys": [probe[3] for probe in chunk],
                        "raw_payload_hashes": [probe[4] for probe in chunk],
                        "lons": [probe[5] for probe in chunk],
                        "lats": [probe[6] for probe in chunk],
                        "field_paths": _FIELD_PATHS,
                    },
                )
            ).mappings().all()
            for row in rows:
                values = {column: row[column] for column in ADDRESS_GEO_COLUMNS}
                if isinstance(values["address"], str):
                    values["address"] = json.loads(values["address"])
                found[str(row["source_record_key"])] = values
    return found
