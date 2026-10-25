"""427 인덱스의 정본 metadata와 migration DDL 대응을 검증한다."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from sqlalchemy import Index, MetaData, Table, Text, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from kortravelmap.infra.models import Base

# PG16의 실제 pg_get_indexdef 반사값. comparator를 바꾸지 않고 이 경계를 검증한다.
_REFLECTED = {
    "ix_source_entity_heads_bounded_evidence_key": (
        "(\n"
        "CASE\n"
        "    WHEN octet_length(source_entity_key) <= 256 "
        "THEN source_entity_key\n"
        "    ELSE NULL::text\n"
        "END)"
    ),
    "ix_source_links_bounded_evidence_key": (
        "(\n"
        "CASE\n"
        "    WHEN octet_length(source_entity_key) <= 256 "
        "THEN source_entity_key\n"
        "    ELSE NULL::text\n"
        "END)"
    ),
    "ix_source_records_bounded_evidence_key": (
        "(\n"
        "CASE\n"
        "    WHEN octet_length(source_record_key::text) <= 256 "
        "THEN source_record_key::text\n"
        "    ELSE NULL::text\n"
        "END)"
    ),
}


@pytest.mark.parametrize(
    ("table_name", "index_name"),
    [
        ("source_entity_heads", "ix_source_entity_heads_bounded_evidence_key"),
        ("source_records", "ix_source_records_bounded_evidence_key"),
        ("source_links", "ix_source_links_bounded_evidence_key"),
    ],
)
def test_airport_bounded_index_metadata_matches_reflection_and_migration(
    table_name: str, index_name: str
) -> None:
    spec = spec_from_file_location(
        "_airport_index_metadata_migration",
        Path(__file__).resolve().parents[2] / "alembic/versions/427_transport_airport_reader.py",
    )
    assert spec is not None
    assert spec.loader is not None
    migration = module_from_spec(spec)
    spec.loader.exec_module(migration)
    statements = [
        sql
        for sql in migration._UPGRADE_STATEMENTS
        if sql.startswith(f"CREATE INDEX {index_name} ON ")
    ]
    assert len(statements) == 1
    table = Base.metadata.tables[f"provider_sync.{table_name}"]
    indexes = [index for index in table.indexes if index.name == index_name]
    assert len(indexes) == 1
    actual = str(CreateIndex(indexes[0]).compile(dialect=postgresql.dialect()))
    reflected_table = Table(
        table_name,
        MetaData(),
        Index(index_name, text(_REFLECTED[index_name])),
        schema="provider_sync",
    )
    reflected_index = next(iter(reflected_table.indexes))
    impl = MigrationContext.configure(dialect=postgresql.dialect()).impl
    comparison = impl.compare_indexes(indexes[0], reflected_index)
    assert comparison.is_equal, comparison.message
    assert not comparison.is_skip

    # 실제 migration DDL은 pg_catalog를 명시한다. 반사 canonical 표현은 builtin
    # qualifier와 text 열의 무의미한 text cast만 없애며 CASE/256/NULL/컬럼은 같다.
    original = statements[0].replace("pg_catalog.octet_length", "octet_length")
    key = "source_record_key" if table_name == "source_records" else "source_entity_key"
    if isinstance(table.c[key].type, Text):
        original = original.replace(f"{key}::text", key)
    assert "".join(actual.split()) == "".join(original.split())
