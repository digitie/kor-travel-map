"""T-VN-33 source lineage ORM mapping의 canonical storage identity 검증."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from kortravelmap.infra.models import (
    ProviderDatasetOperationRow,
    ProviderDatasetOperationScopeRow,
    ProviderDatasetRow,
    SourceEntityHeadRow,
    SourceEntityRow,
    SourceLinkRow,
    SourceRecordRow,
)

_ROOT = Path(__file__).resolve().parents[2]
_PRODUCTION_SOURCE_ROOTS = (
    _ROOT / "src" / "kortravelmap",
    _ROOT / "packages" / "kor-travel-map-api" / "src" / "kortravelmap" / "api",
    _ROOT
    / "packages"
    / "kor-travel-map-dagster"
    / "src"
    / "kortravelmap"
    / "dagster",
)
_FORBIDDEN_SOURCE_LINEAGE_COLUMNS = {
    "source_entities": frozenset(
        {"provider", "dataset_key", "current_source_record_key"}
    ),
    "source_records": frozenset(
        {
            "provider",
            "dataset_key",
            "source_entity_type",
            "source_entity_id",
            "source_version",
            "raw_name",
            "raw_address",
            "raw_longitude",
            "raw_latitude",
            "last_seen_at",
            "expires_at",
        }
    ),
    "source_links": frozenset({"is_primary_source"}),
}


def _production_source_lineage_sql_literals() -> list[tuple[Path, str]]:
    """정적 문자열 SQL만 검사해 DTO input 필드를 DB 열로 오인하지 않는다."""

    literals: list[tuple[Path, str]] = []
    table_markers = tuple(
        f"provider_sync.{table}" for table in _FORBIDDEN_SOURCE_LINEAGE_COLUMNS
    )
    sql_keyword = re.compile(r"\b(?:SELECT|INSERT|UPDATE|DELETE|JOIN|FROM|WITH)\b")
    for root in _PRODUCTION_SOURCE_ROOTS:
        for path in root.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                if any(marker in node.value for marker in table_markers) and sql_keyword.search(
                    node.value
                ):
                    literals.append((path, node.value))
    return literals


def _legacy_sql_column_references(sql: str) -> set[str]:
    """final 0090 뒤에는 실패해야 할 normal-reader/writer 열 참조를 찾는다."""

    found: set[str] = set()
    for table, columns in _FORBIDDEN_SOURCE_LINEAGE_COLUMNS.items():
        names = "|".join(sorted(columns))
        direct = rf"\bprovider_sync\.{table}\.(?:{names})\b"
        if re.search(direct, sql, flags=re.IGNORECASE):
            found.add(f"{table}:direct")

        aliases = re.findall(
            rf"\b(?:FROM|JOIN|UPDATE)\s+provider_sync\.{table}"
            r"(?:\s+AS)?\s+([A-Za-z_][A-Za-z0-9_]*)",
            sql,
            flags=re.IGNORECASE,
        )
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\.(?:{names})\b", sql):
                found.add(f"{table}:{alias}")

        inserted = re.search(
            rf"\bINSERT\s+INTO\s+provider_sync\.{table}\s*\((?P<columns>[^)]*)\)",
            sql,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if inserted is not None:
            inserted_columns = set(
                re.findall(r"\b[A-Za-z_][A-Za-z0-9_]*\b", inserted["columns"])
            )
            if inserted_columns & columns:
                found.add(f"{table}:insert")
    return found


def test_provider_dataset_and_operation_mappings_have_db_owned_identity() -> None:
    assert set(ProviderDatasetRow.__table__.primary_key.columns.keys()) == {
        "provider_dataset_id"
    }
    assert set(ProviderDatasetOperationRow.__table__.primary_key.columns.keys()) == {
        "provider_dataset_id",
        "operation_key",
    }
    assert set(ProviderDatasetOperationScopeRow.__table__.primary_key.columns.keys()) == {
        "provider_dataset_id",
        "sync_scope",
    }


def test_source_lineage_mappings_keep_mutable_observation_out_of_raw_record() -> None:
    entity_columns = set(SourceEntityRow.__table__.columns.keys())
    record_columns = set(SourceRecordRow.__table__.columns.keys())
    head_columns = set(SourceEntityHeadRow.__table__.columns.keys())
    link_columns = set(SourceLinkRow.__table__.columns.keys())

    assert "provider_dataset_id" in entity_columns
    assert {"provider", "dataset_key", "current_source_record_key"}.isdisjoint(
        entity_columns
    )
    assert record_columns == {
        "source_record_key",
        "source_entity_key",
        "raw_data",
        "raw_payload_hash",
        "fetched_at",
        "imported_at",
    }
    assert head_columns == {
        "source_entity_key",
        "current_source_record_key",
        "observed_at",
        "expires_at",
        "updated_at",
    }
    assert "is_primary_source" not in link_columns
    assert any(
        str(index.dialect_options["postgresql"].get("where"))
        == "source_role = 'primary'"
        for index in SourceLinkRow.__table__.indexes
        if index.name == "idx_source_links_primary"
    )


def test_final_cutover_migration_statically_drops_source_lineage_legacy_columns() -> None:
    """0090 DDL이 manifest의 shadow ownership 열을 다시 남기지 않는다."""

    ddl = (
        _ROOT / "alembic" / "versions" / "0091_tvn33_cutover_fence.py"
    ).read_text(encoding="utf-8")
    for table, columns in _FORBIDDEN_SOURCE_LINEAGE_COLUMNS.items():
        statements = re.findall(
            rf"ALTER TABLE provider_sync\.{table}(?P<body>.*?);",
            ddl,
            flags=re.DOTALL,
        )
        assert statements, table
        body = "\n".join(statements)
        for column in columns:
            assert f"DROP COLUMN {column}" in body, f"{table}.{column}"


def test_production_source_lineage_sql_has_no_final0090_legacy_column_reference() -> None:
    """normal path는 final schema에서 물리 삭제한 source-lineage 열을 읽거나 쓰지 않는다."""

    failures = {
        str(path.relative_to(_ROOT)): sorted(_legacy_sql_column_references(sql))
        for path, sql in _production_source_lineage_sql_literals()
        if _legacy_sql_column_references(sql)
    }

    assert failures == {}
