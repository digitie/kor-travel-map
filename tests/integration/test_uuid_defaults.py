"""UUID default schema qualification regression tests (T-RV-13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = pytest.mark.integration

_EXPECTED_DEFAULTS = {
    ("feature_consistency_reports", "report_id"): "x_extension.gen_random_uuid()",
    ("dedup_review_queue", "review_key"): "x_extension.gen_random_uuid()",
    ("import_jobs", "job_id"): "x_extension.gen_random_uuid()",
    ("feature_merge_history", "merge_id"): "x_extension.gen_random_uuid()",
    ("feature_update_requests", "request_id"): "x_extension.gen_random_uuid()",
    ("offline_uploads", "upload_id"): "x_extension.gen_random_uuid()",
    ("feature_overrides", "override_key"): "x_extension.gen_random_uuid()",
    ("data_integrity_violations", "violation_key"): "x_extension.gen_random_uuid()",
    ("poi_cache_targets", "target_id"): "x_extension.gen_random_uuid()",
}


async def test_ops_uuid_defaults_are_schema_qualified(
    migrated_session: AsyncSession,
) -> None:
    rows = (
        await migrated_session.execute(
            text(
                """
                SELECT
                    c.relname AS table_name,
                    a.attname AS column_name,
                    pg_get_expr(d.adbin, d.adrelid) AS default_expr
                FROM pg_attribute AS a
                JOIN pg_class AS c ON c.oid = a.attrelid
                JOIN pg_namespace AS n ON n.oid = c.relnamespace
                JOIN pg_attrdef AS d
                  ON d.adrelid = a.attrelid
                 AND d.adnum = a.attnum
                WHERE n.nspname = 'ops'
                """
            )
        )
    ).mappings().all()

    defaults = {
        (str(row["table_name"]), str(row["column_name"])): str(row["default_expr"])
        for row in rows
        if (str(row["table_name"]), str(row["column_name"])) in _EXPECTED_DEFAULTS
    }
    assert defaults == _EXPECTED_DEFAULTS
