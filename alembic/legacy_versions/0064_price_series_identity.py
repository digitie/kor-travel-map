"""price current/history 인덱스를 full series identity에 맞춘다.

Revision ID: 0064_price_series_identity
Revises: 0063_pipeline_root_id
Create Date: 2026-07-27

PriceValue natural identity는 feature_id + provider + price_domain + product_key +
observed_at이다. current는 앞 네 축별 최신값, history는 feature별 최신 관측순으로
읽으므로 두 access path를 각각 지원하고 provider를 누락한 기존 current index를 제거한다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0064_price_series_identity"
down_revision: str | Sequence[str] | None = "0063_pipeline_root_id"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE_SCHEMA = "feature"
_TABLE_NAME = "feature_price_values"
_OLD_INDEX = "idx_price_values_feature_product_observed"
_HISTORY_INDEX = "idx_price_values_feature_observed_identity"
_OLD_COLUMNS = (
    "feature_id",
    "price_domain",
    "product_key",
    "observed_at",
)
_OLD_OPTIONS = (0, 0, 0, 3)
_HISTORY_COLUMNS = (
    "feature_id",
    "observed_at",
    "provider",
    "price_domain",
    "product_key",
)
_HISTORY_OPTIONS = (0, 3, 0, 0, 0)


def _index_state(
    index_name: str,
    expected_columns: tuple[str, ...],
    expected_options: tuple[int, ...],
) -> tuple[bool, bool]:
    """인덱스 존재 여부와 이 revision의 유효한 정본 정의 여부를 반환한다."""
    row = (
        op.get_bind()
        .execute(
            sa.text(
                """
                SELECT
                    index_state.indisvalid,
                    index_state.indisready,
                    index_state.indislive,
                    index_state.indisunique,
                    index_state.indnatts,
                    index_state.access_method,
                    index_state.indoption::smallint[] AS key_options,
                    index_state.predicate,
                    ARRAY(
                        SELECT pg_get_indexdef(
                            index_state.indexrelid,
                            ordinal,
                            true
                        )
                        FROM generate_series(
                            1,
                            index_state.indnkeyatts
                        ) AS ordinal
                        ORDER BY ordinal
                    ) AS key_expressions
                FROM (
                    SELECT
                        pg_index.indexrelid,
                        pg_index.indrelid,
                        pg_index.indisvalid,
                        pg_index.indisready,
                        pg_index.indislive,
                        pg_index.indisunique,
                        pg_index.indnatts,
                        pg_index.indnkeyatts,
                        pg_index.indoption,
                        pg_am.amname AS access_method,
                        pg_get_expr(pg_index.indpred, pg_index.indrelid) AS predicate
                    FROM pg_index
                    JOIN pg_class AS index_class
                      ON index_class.oid = pg_index.indexrelid
                    JOIN pg_namespace AS index_namespace
                      ON index_namespace.oid = index_class.relnamespace
                    JOIN pg_class AS table_class
                      ON table_class.oid = pg_index.indrelid
                    JOIN pg_namespace AS table_namespace
                      ON table_namespace.oid = table_class.relnamespace
                    JOIN pg_am ON pg_am.oid = index_class.relam
                    WHERE index_namespace.nspname = :schema_name
                      AND index_class.relname = :index_name
                      AND table_namespace.nspname = :schema_name
                      AND table_class.relname = :table_name
                ) AS index_state
                """
            ),
            {
                "schema_name": _TABLE_SCHEMA,
                "table_name": _TABLE_NAME,
                "index_name": index_name,
            },
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return False, False
    canonical = (
        bool(row["indisvalid"])
        and bool(row["indisready"])
        and bool(row["indislive"])
        and not bool(row["indisunique"])
        and row["indnatts"] == len(expected_columns)
        and row["access_method"] == "btree"
        and row["predicate"] is None
        and tuple(row["key_expressions"]) == expected_columns
        and tuple(row["key_options"]) == expected_options
    )
    return True, canonical


def _execute_concurrently(sql: str) -> None:
    with op.get_context().autocommit_block():
        op.execute(sql)


def _ensure_index(
    *,
    desired_name: str,
    desired_columns: tuple[str, ...],
    desired_options: tuple[int, ...],
    peer_name: str,
    peer_columns: tuple[str, ...],
    peer_options: tuple[int, ...],
    create_sql: str,
) -> None:
    """부분 적용 재실행에서도 유효한 access path 하나를 보존한다."""
    desired_exists, desired_canonical = _index_state(
        desired_name,
        desired_columns,
        desired_options,
    )
    if desired_canonical:
        return

    if desired_exists:
        _, peer_canonical = _index_state(peer_name, peer_columns, peer_options)
        if not peer_canonical:
            raise RuntimeError(
                f"cannot replace non-canonical index {desired_name!r} without "
                f"valid peer {peer_name!r}"
            )
        _execute_concurrently(f"DROP INDEX CONCURRENTLY {_TABLE_SCHEMA}.{desired_name}")

    _execute_concurrently(create_sql)
    _, created_canonical = _index_state(desired_name, desired_columns, desired_options)
    if not created_canonical:
        raise RuntimeError(f"created index {desired_name!r} is not canonical")


def _drop_peer_after_cutover(
    *,
    desired_name: str,
    desired_columns: tuple[str, ...],
    desired_options: tuple[int, ...],
    peer_name: str,
) -> None:
    _, desired_canonical = _index_state(desired_name, desired_columns, desired_options)
    if not desired_canonical:
        raise RuntimeError(f"refusing to drop peer {peer_name!r} before {desired_name!r} is valid")
    peer_exists, _ = _index_state(peer_name, (), ())
    if peer_exists:
        _execute_concurrently(f"DROP INDEX CONCURRENTLY {_TABLE_SCHEMA}.{peer_name}")


def upgrade() -> None:
    # current는 기존 uq_price_value_identity를 역방향 스캔한다. 별도 current
    # index를 만들면 동일한 선두 컬럼을 중복 저장해 write amplification만 늘어난다.
    # history access path만 바꾸되 새 index가 유효해지기 전까지 기존 index를 보존한다.
    _ensure_index(
        desired_name=_HISTORY_INDEX,
        desired_columns=_HISTORY_COLUMNS,
        peer_name=_OLD_INDEX,
        desired_options=_HISTORY_OPTIONS,
        peer_columns=_OLD_COLUMNS,
        peer_options=_OLD_OPTIONS,
        create_sql="""
            CREATE INDEX CONCURRENTLY idx_price_values_feature_observed_identity
            ON feature.feature_price_values
                (feature_id, observed_at DESC, provider, price_domain, product_key)
        """,
    )
    _drop_peer_after_cutover(
        desired_name=_HISTORY_INDEX,
        desired_columns=_HISTORY_COLUMNS,
        peer_name=_OLD_INDEX,
        desired_options=_HISTORY_OPTIONS,
    )


def downgrade() -> None:
    _ensure_index(
        desired_name=_OLD_INDEX,
        desired_columns=_OLD_COLUMNS,
        peer_name=_HISTORY_INDEX,
        desired_options=_OLD_OPTIONS,
        peer_columns=_HISTORY_COLUMNS,
        peer_options=_HISTORY_OPTIONS,
        create_sql="""
            CREATE INDEX CONCURRENTLY idx_price_values_feature_product_observed
            ON feature.feature_price_values
                (feature_id, price_domain, product_key, observed_at DESC)
        """,
    )
    _drop_peer_after_cutover(
        desired_name=_OLD_INDEX,
        desired_columns=_OLD_COLUMNS,
        peer_name=_HISTORY_INDEX,
        desired_options=_OLD_OPTIONS,
    )
