"""Alembic metadata 비교 제외 객체의 단일 ledger (T-VN-19).

모든 app-owned 제외 객체는 integration 구조 계약을 가져야 한다. ``env.py``와
계약 테스트가 이 집합을 함께 import해, 검증 없는 새 제외 항목을 막는다.
"""

from __future__ import annotations

UNMAPPED_APP_TABLES = frozenset(
    {
        ("feature", "feature_weather_values"),
        ("feature", "feature_price_values"),
        ("feature", "current_weather_summary"),
        ("feature", "current_price_summary"),
        ("ops", "current_summary_runs"),
        ("ops", "system_log"),
        ("ops", "api_call_log"),
        ("ops", "public_api_keys"),
        ("ops", "admin_auth_events"),
        ("ops", "ops_live_ticket_claims"),
        ("ops", "ops_live_topic_revisions"),
        # 0103이 legacy whole-row freeze replay의 fail-closed preflight 결과를
        # 남기는 감사 전용 표다 — 애플리케이션 코드가 읽지 않으므로 ORM에
        # 매핑하지 않는다. 구조 계약은 0103 통합 테스트가 가진다.
        ("ops", "tvn36_legacy_freeze_preflight_manifest"),
        # T-VN-40 receipt/effect 관계는 의도적으로 raw SQL 전용이다. 애플리케이션
        # entity가 아니라 immutable command evidence이므로 ORM에 매핑하지 않고,
        # exact column/constraint/index는
        # ``test_alembic_unmapped_tables_keep_structural_contract``가 고정한다.
        ("feature", "curation_import_plans"),
        ("feature", "curation_import_plan_rows"),
        ("feature", "curation_import_plan_revisions"),
        ("ops", "curation_catalog_command_effects"),
        ("ops", "curation_concierge_legacy_owner_manifest"),
        ("ops", "curation_import_collection_effects"),
        ("ops", "curation_import_collection_touches"),
        ("ops", "curation_import_plan_claims"),
        ("ops", "curation_import_plan_commits"),
        ("ops", "curation_provider_root_receipts"),
        ("ops", "curation_provider_snapshot_receipts"),
        ("ops", "curation_source_observation_receipts"),
    }
)

# T-VN-34(0096/0097): 마지막 항목이던 ``idx_features_dedup_refresh_keyset``이
# 사라졌다. 0096이 ``idx_features_updated_keyset``을 같은 정렬축 + 3축 술어
# partial index로 다시 만들어 이 index의 역할을 흡수했고, 그 후속 index는
# ORM이 선언하므로 비교 대상이다 — 제외할 app-owned index가 더는 없다.
# 비어 있어도 ledger는 유지한다: env.py와 계약 테스트가 이 집합을 함께 읽어
# "계약 없는 새 제외 항목"을 계속 막는다.
UNCOMPARED_INDEXES: frozenset[tuple[str, str]] = frozenset()

__all__ = ["UNCOMPARED_INDEXES", "UNMAPPED_APP_TABLES"]
