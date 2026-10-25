"""427 인덱스의 정본 metadata와 migration DDL 대응을 검증한다."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex

from kortravelmap.infra.models import Base


@pytest.mark.parametrize(
    ("table_name", "index_name"),
    [
        ("source_entity_heads", "ix_source_entity_heads_bounded_evidence_key"),
        ("source_records", "ix_source_records_bounded_evidence_key"),
        ("source_links", "ix_source_links_bounded_evidence_key"),
    ],
)
def test_airport_bounded_index_metadata_matches_migration(
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
        sql for sql in migration._UPGRADE_STATEMENTS
        if sql.startswith(f"CREATE INDEX {index_name} ON ")
    ]
    assert len(statements) == 1
    table = Base.metadata.tables[f"provider_sync.{table_name}"]
    indexes = [index for index in table.indexes if index.name == index_name]
    assert len(indexes) == 1
    actual = str(CreateIndex(indexes[0]).compile(dialect=postgresql.dialect()))
    assert actual == statements[0]
