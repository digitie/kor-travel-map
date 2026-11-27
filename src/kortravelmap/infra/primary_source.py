"""Feature 대표 원천 읽기 조각 — ADR-125 (migration 459).

대표 원천은 Feature의 ``source_role = 'primary'`` 연결 중 **가장 먼저 붙은 것**
(``source_links.created_at``, 동률이면 ``source_entity_key COLLATE "C"``)이다. 규칙의 정의는 DB
view ``feature.feature_primary_source_rule`` 하나이고, ``feature.feature_primary_sources``는 그
결과를 ``source_links``·``features`` trigger가 쓰기와 같은 transaction에서 유지한 사본이다(Feature
하나에 한 행, 원천이 없으면 세 열이 NULL).

읽는 쪽은 규칙을 다시 계산하지 않고 이 사본만 읽는다 — 관리자 목록의 ``provider`` 정렬·
``provider_dataset_id`` 필터·표시, 공개 nearby의 ``primary_provider``·``providers`` 필터, dedup 검토
목록. 정합성 검사 F10(``infra.consistency``)이 사본과 규칙 view를 전수 대조한다.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "PRIMARY_SOURCE_DRIFT_SQL",
    "PRIMARY_SOURCE_SORT_KEY_SQL",
    "primary_source_display_join_sql",
]

#: ``provider`` 정렬 키. ``idx_feature_primary_sources_provider_keyset``의 식
#: ``COALESCE(provider, ''::text)``와 같아야 keyset이 그 색인을 탄다. 원천이 없는 Feature는 ''다.
PRIMARY_SOURCE_SORT_KEY_SQL: Final[str] = "COALESCE(ps.provider, '')"


def primary_source_display_join_sql(
    feature_alias: str, *, row_alias: str, dataset_alias: str
) -> str:
    """Feature 행에 대표 원천(``{dataset_alias}.provider``·``dataset_key``)을 붙이는 LEFT JOIN 둘.

    표시 값은 정본 ``provider_datasets``에서 읽는다(``provider``는 사본과 같다 — 식별 불변).
    """

    for alias in (feature_alias, row_alias, dataset_alias):
        if not alias.isidentifier():
            raise ValueError("SQL alias must be an identifier")
    return f"""
    LEFT JOIN feature.feature_primary_sources AS {row_alias}
      ON {row_alias}.feature_id = {feature_alias}.feature_id
    LEFT JOIN provider_sync.provider_datasets AS {dataset_alias}
      ON {dataset_alias}.provider_dataset_id = {row_alias}.provider_dataset_id"""


#: 정합성 검사 F10 — 사본이 규칙과 어긋난 Feature(행이 없거나, 고아 행이거나, 값이 다름).
PRIMARY_SOURCE_DRIFT_SQL: Final[str] = (
    "SELECT COALESCE(f.feature_id, ps.feature_id) AS id "
    "FROM feature.features AS f "
    "FULL JOIN feature.feature_primary_sources AS ps "
    "  ON ps.feature_id = f.feature_id "
    "LEFT JOIN feature.feature_primary_source_rule AS rule "
    "  ON rule.feature_id = f.feature_id "
    "WHERE f.feature_id IS NULL "
    "   OR ps.feature_id IS NULL "
    "   OR (ps.source_entity_key, ps.provider_dataset_id, ps.provider) "
    "      IS DISTINCT FROM "
    "      (rule.source_entity_key, rule.provider_dataset_id, rule.provider)"
)
