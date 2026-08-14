"""provider entity identity와 immutable payload observation을 분리한다.

Revision ID: 0044_source_entities
Revises: 0043_weather_history_idx
Create Date: 2026-07-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0044_source_entities"
down_revision: str | Sequence[str] | None = "0043_weather_history_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ENTITY_KEY_SQL = """
'se_' || encode(
    x_extension.digest(
        provider || '|' || dataset_key || '|' ||
        source_entity_type || '|' || source_entity_id,
        'sha256'
    ),
    'hex'
)
"""


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE provider_sync.source_entities (
            source_entity_key text PRIMARY KEY,
            provider text NOT NULL,
            dataset_key text NOT NULL,
            source_entity_type text NOT NULL,
            source_entity_id text NOT NULL,
            current_source_record_key text,
            first_seen_at timestamptz NOT NULL,
            last_seen_at timestamptz NOT NULL,
            CONSTRAINT uq_source_entities_identity UNIQUE (
                provider, dataset_key, source_entity_type, source_entity_id
            ),
            CONSTRAINT ck_source_entities_seen_order
                CHECK (first_seen_at <= last_seen_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX idx_source_entities_current_record "
        "ON provider_sync.source_entities (current_source_record_key) "
        "WHERE current_source_record_key IS NOT NULL"
    )

    op.execute("ALTER TABLE provider_sync.source_records ADD COLUMN source_entity_key text")
    op.execute(
        f"""
        UPDATE provider_sync.source_records
        SET source_entity_key = {_ENTITY_KEY_SQL}
        """
    )
    op.execute(
        f"""
        INSERT INTO provider_sync.source_entities (
            source_entity_key,
            provider,
            dataset_key,
            source_entity_type,
            source_entity_id,
            first_seen_at,
            last_seen_at
        )
        SELECT
            {_ENTITY_KEY_SQL},
            provider,
            dataset_key,
            source_entity_type,
            source_entity_id,
            min(least(fetched_at, last_seen_at, imported_at)),
            max(greatest(fetched_at, last_seen_at, imported_at))
        FROM provider_sync.source_records
        GROUP BY provider, dataset_key, source_entity_type, source_entity_id
        """
    )
    op.execute(
        "ALTER TABLE provider_sync.source_records ALTER COLUMN source_entity_key SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE provider_sync.source_records "
        "ADD CONSTRAINT fk_source_records_source_entity_key_source_entities "
        "FOREIGN KEY (source_entity_key) "
        "REFERENCES provider_sync.source_entities (source_entity_key) "
        "ON DELETE RESTRICT"
    )
    op.execute(
        "ALTER TABLE provider_sync.source_records "
        "ADD CONSTRAINT uq_source_records_entity_record "
        "UNIQUE (source_entity_key, source_record_key)"
    )
    op.execute(
        "CREATE INDEX idx_source_records_entity_history "
        "ON provider_sync.source_records ("
        "source_entity_key, last_seen_at DESC, fetched_at DESC, "
        "imported_at DESC, source_record_key DESC)"
    )

    op.execute(
        """
        WITH ranked AS (
            SELECT DISTINCT ON (source_entity_key)
                source_entity_key,
                source_record_key
            FROM provider_sync.source_records
            ORDER BY
                source_entity_key,
                last_seen_at DESC,
                fetched_at DESC,
                imported_at DESC,
                source_record_key DESC
        )
        UPDATE provider_sync.source_entities AS se
        SET current_source_record_key = ranked.source_record_key
        FROM ranked
        WHERE ranked.source_entity_key = se.source_entity_key
        """
    )
    op.execute(
        "ALTER TABLE provider_sync.source_entities "
        "ADD CONSTRAINT fk_source_entities_current_record "
        "FOREIGN KEY (source_entity_key, current_source_record_key) "
        "REFERENCES provider_sync.source_records "
        "(source_entity_key, source_record_key) "
        "ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED"
    )

    # record-version link를 entity link로 접는다. 같은 entity의 여러 payload link는
    # current record link를 우선하고, 없으면 current 결정 순서와 같은 최신 link를
    # 남겨 Feature↔entity membership을 하나도 잃지 않는다.
    op.execute("ALTER TABLE provider_sync.source_links ADD COLUMN source_entity_key text")
    op.execute(
        """
        UPDATE provider_sync.source_links AS sl
        SET source_entity_key = sr.source_entity_key
        FROM provider_sync.source_records AS sr
        WHERE sr.source_record_key = sl.source_record_key
        """
    )
    op.execute(
        """
        WITH duplicate_links AS (
            SELECT
                sl.ctid,
                row_number() OVER (
                    PARTITION BY sl.feature_id, sl.source_entity_key
                    ORDER BY
                        (sr.source_record_key = se.current_source_record_key) DESC,
                        sr.last_seen_at DESC,
                        sr.fetched_at DESC,
                        sr.imported_at DESC,
                        sr.source_record_key DESC,
                        sl.created_at DESC,
                        sl.ctid DESC
                ) AS rank
            FROM provider_sync.source_links AS sl
            JOIN provider_sync.source_records AS sr
              ON sr.source_record_key = sl.source_record_key
            JOIN provider_sync.source_entities AS se
              ON se.source_entity_key = sl.source_entity_key
        )
        DELETE FROM provider_sync.source_links AS sl
        USING duplicate_links AS duplicate
        WHERE sl.ctid = duplicate.ctid
          AND duplicate.rank > 1
        """
    )
    op.execute("DROP INDEX IF EXISTS provider_sync.idx_source_links_record")
    op.execute("ALTER TABLE provider_sync.source_links DROP CONSTRAINT IF EXISTS pk_source_links")
    op.execute(
        "ALTER TABLE provider_sync.source_links "
        "DROP CONSTRAINT IF EXISTS "
        "fk_source_links_source_record_key_source_records"
    )
    op.execute("ALTER TABLE provider_sync.source_links DROP COLUMN source_record_key")
    op.execute("ALTER TABLE provider_sync.source_links ALTER COLUMN source_entity_key SET NOT NULL")
    op.execute(
        "ALTER TABLE provider_sync.source_links "
        "ADD CONSTRAINT pk_source_links "
        "PRIMARY KEY (feature_id, source_entity_key)"
    )
    op.execute(
        "ALTER TABLE provider_sync.source_links "
        "ADD CONSTRAINT fk_source_links_source_entity_key_source_entities "
        "FOREIGN KEY (source_entity_key) "
        "REFERENCES provider_sync.source_entities (source_entity_key) "
        "ON DELETE RESTRICT"
    )
    op.execute(
        "CREATE INDEX idx_source_links_entity ON provider_sync.source_links (source_entity_key)"
    )


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM provider_sync.source_links AS sl
                JOIN provider_sync.source_records AS sr
                  ON sr.source_entity_key = sl.source_entity_key
                GROUP BY sl.feature_id, sl.source_entity_key
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION USING
                    ERRCODE = 'P0001',
                    MESSAGE = (
                        '0044 downgrade refused: linked source entity has '
                        'multiple immutable records; export or explicitly '
                        'remove history before downgrade'
                    );
            END IF;
        END
        $$
        """
    )
    op.execute("ALTER TABLE provider_sync.source_links ADD COLUMN source_record_key text")
    op.execute(
        """
        UPDATE provider_sync.source_links AS sl
        SET source_record_key = se.current_source_record_key
        FROM provider_sync.source_entities AS se
        WHERE se.source_entity_key = sl.source_entity_key
        """
    )
    op.execute("DROP INDEX IF EXISTS provider_sync.idx_source_links_entity")
    op.execute("ALTER TABLE provider_sync.source_links DROP CONSTRAINT IF EXISTS pk_source_links")
    op.execute(
        "ALTER TABLE provider_sync.source_links "
        "DROP CONSTRAINT IF EXISTS "
        "fk_source_links_source_entity_key_source_entities"
    )
    op.execute("ALTER TABLE provider_sync.source_links DROP COLUMN source_entity_key")
    op.execute("ALTER TABLE provider_sync.source_links ALTER COLUMN source_record_key SET NOT NULL")
    op.execute(
        "ALTER TABLE provider_sync.source_links "
        "ADD CONSTRAINT pk_source_links "
        "PRIMARY KEY (feature_id, source_record_key)"
    )
    op.execute(
        "ALTER TABLE provider_sync.source_links "
        "ADD CONSTRAINT fk_source_links_source_record_key_source_records "
        "FOREIGN KEY (source_record_key) "
        "REFERENCES provider_sync.source_records (source_record_key) "
        "ON DELETE RESTRICT"
    )
    op.execute(
        "CREATE INDEX idx_source_links_record ON provider_sync.source_links (source_record_key)"
    )

    op.execute(
        "ALTER TABLE provider_sync.source_entities "
        "DROP CONSTRAINT IF EXISTS fk_source_entities_current_record"
    )
    op.execute("DROP INDEX IF EXISTS provider_sync.idx_source_records_entity_history")
    op.execute(
        "ALTER TABLE provider_sync.source_records "
        "DROP CONSTRAINT IF EXISTS uq_source_records_entity_record"
    )
    op.execute(
        "ALTER TABLE provider_sync.source_records "
        "DROP CONSTRAINT IF EXISTS "
        "fk_source_records_source_entity_key_source_entities"
    )
    op.execute("ALTER TABLE provider_sync.source_records DROP COLUMN source_entity_key")
    op.execute("DROP TABLE provider_sync.source_entities")
