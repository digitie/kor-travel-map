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
    }
)

UNCOMPARED_INDEXES = frozenset(
    {
        ("feature", "idx_features_dedup_refresh_keyset"),
    }
)

__all__ = ["UNCOMPARED_INDEXES", "UNMAPPED_APP_TABLES"]
