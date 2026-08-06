"""notice 계보 key를 저장하는 scope의 단일 정본 (ADR-087).

``provider_sync.source_records.lineage_key``는 **notice scope record에만** 채운다.
notice가 아닌 record에 "notice 계보"를 저장하는 것은 의미가 없고, 그 값은 어떤
질의도 읽지 않는다(read 필터가 이미 ``kind='notice'``로 좁힌다). 제한하지 않으면
계보 CASE의 ELSE 분기가 **모든 provider의 모든 record**(73만+)에
``source_entity_id`` 사본을 남긴다.

writer(``_UPSERT_SOURCE_RECORD_SQL``)와 backfill(alembic 0088)이 **같은 집합**을
써야 기존 행과 신규 행이 어긋나지 않는다. 그래서 여기 한 곳에 둔다.

여기 없는 provider가 notice를 내보내면 ``lineage_key``는 NULL이고 read는
재계산으로 물러난다 — 정확성은 유지되고 최적화만 적용되지 않는다.
"""

from __future__ import annotations

from typing import Final

__all__ = ["NOTICE_LINEAGE_SCOPES", "notice_lineage_scope_sql"]

#: (provider, dataset_key, source_entity_type) — ``_notice_lineage_sql``이 전용
#: 계보 규칙을 갖는 scope와 같다.
NOTICE_LINEAGE_SCOPES: Final[tuple[tuple[str, str, str], ...]] = (
    ("python-krex-api", "krex_traffic_notices", "traffic_notice"),
    ("python-kma-api", "kma_weather_alerts", "weather_alert"),
)


def notice_lineage_scope_sql(
    provider: str, dataset_key: str, source_entity_type: str
) -> str:
    """세 식이 notice scope에 속하는지 판정하는 SQL 술어 (여러 줄)."""
    rows = ",\n        ".join(
        f"('{provider_name}', '{dataset}', '{entity_type}')"
        for provider_name, dataset, entity_type in NOTICE_LINEAGE_SCOPES
    )
    return (
        f"(({provider}, {dataset_key}, {source_entity_type}) IN (\n"
        f"        {rows}\n"
        "    ))"
    )
