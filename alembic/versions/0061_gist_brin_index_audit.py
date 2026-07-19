"""자동 full GiST 제거 + weather source-record 지원 index (F-8 / D-12-3, T-VN-18).

Revision ID: 0061_gist_brin_index_audit
Revises: 0060_weather_integrity
Create Date: 2026-07-19

배경 (F-8: GiST 6개 = 자동 full 3 + 수동 partial 3, write ~1.6×)
----------------------------------------------------------------
``feature.features``의 geometry 컬럼(coord/coord_5179/geom)이 geoalchemy2 기본
``spatial_index=True`` 라 0002의 ``op.create_table`` 시점에 **full GiST**가
자동 생성됐다(idx_features_coord / idx_features_coord_5179 / idx_features_geom,
WHERE 절 없음). 0002는 이와 별도로 공개 술어 **partial GiST** 3개를 명시 생성한다
(idx_features_coord_gist / idx_features_coord_5179_gist / idx_features_geom_gist,
``WHERE deleted_at IS NULL`` [``AND geom IS NOT NULL``]).

공개 조회(bbox/nearby/in-area/T-VN-04 ``feature.public_features`` view)는 모두
``deleted_at IS NULL`` 술어를 포함하므로 partial GiST로 충분하다(planner가 partial을
선택하는 EXPLAIN 회귀는 ``tests/integration/test_gist_brin_index_audit.py``). full
GiST는 삭제 행까지 색인해 write 비용만 늘린다(insert/update마다 index 6개 유지).
따라서 models.py에서 ``spatial_index=False``로 자동 색인을 끄고(metadata gate
정합), 여기서 DB의 자동 full 3개를 **CONCURRENTLY** 제거한다.

write-cost 실측(§8.3 필수 — 실제 수치는 journal/PR 참조): point insert 워크로드는
coord + coord_5179 축을 색인한다. full 제거 전(4 GiST: coord/coord_5179 각 full+partial)
대비 제거 후(2 GiST: partial만) INSERT 처리량을 testcontainers에서 실측하며,
``test_gist_brin_index_audit.py::test_dropping_full_gist_reduces_write_cost``가 이를
재현한다(partial-only가 더 빠름을 단언 + 비율 출력).

BRIN 감사 (D-12-3: 기존 감사 후 누락 hot path만 보강)
-----------------------------------------------------
기존 시간축 BRIN: weather ``brin_weather_values_valid_at``(0017)·
``brin_weather_values_collected_at``(0043), price ``idx_price_values_observed_at_brin``
(0034), source_records imported_at/fetched_at(0002)/last_seen_at(0038). weather
card/history 조회는 항상 feature-scoped(``WHERE feature_id = ...``)라 0043의 복합
B-tree(feature_id+issued_at / feature_id+valid_at)를 쓰고, cross-feature append-time
스캔축(valid_at/collected_at/observed_at)은 이미 BRIN이 있다. 새로 추가할 **누락된
hot 시간축이 없어 BRIN은 추가하지 않는다**(speculative 추가 금지). 감사 근거는
journal에 첨부.

source-record FK 지원 index (T-VN-17 이월)
------------------------------------------
0060의 ``fk_weather_value_source_record``(ON DELETE SET NULL)는 source_record 삭제
시 참조행을 찾아야 하는데 지원 index가 없어 ~30M행 seq-scan이 난다. price의
``idx_price_values_source_record``를 미러링해
``idx_weather_values_source_record``(partial, ``WHERE source_record_key IS NOT NULL``)를
**CONCURRENTLY** 추가한다.

DDL 안전 (ADR-075 D-12, ~30M행)
-------------------------------
DROP/CREATE 모두 ``CONCURRENTLY``(autocommit_block)라 ACCESS EXCLUSIVE 없이 write를
막지 않는다. CREATE는 재실행 안전을 위해 leftover INVALID index를 먼저 CONCURRENTLY
drop한다. INVALID index 탐지·제거는 ``docs/runbooks/docker-app.md`` §8.1의 일반
concurrent DDL 절차를 따른다. downgrade는 자동
full GiST 3개를 복원하고 weather 지원 index를 제거한다(둘 다 CONCURRENTLY).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0061_gist_brin_index_audit"
down_revision: str | Sequence[str] | None = "0060_weather_integrity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        # 1) 자동 full GiST 3개 제거 — 공개 술어 partial GiST만 남긴다.
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS feature.idx_features_coord")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS feature.idx_features_coord_5179")
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS feature.idx_features_geom")

        # 2) weather source-record FK 지원 index (T-VN-17 이월, price 미러).
        #    재실행 안전: leftover INVALID index를 먼저 제거.
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS "
            "feature.idx_weather_values_source_record"
        )
        op.execute(
            """
            CREATE INDEX CONCURRENTLY idx_weather_values_source_record
            ON feature.feature_weather_values (source_record_key)
            WHERE source_record_key IS NOT NULL
            """
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS "
            "feature.idx_weather_values_source_record"
        )
        # 자동 full GiST 복원 (geoalchemy2 기본 이름·WHERE 없음).
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_features_coord "
            "ON feature.features USING GIST (coord)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_features_coord_5179 "
            "ON feature.features USING GIST (coord_5179)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_features_geom "
            "ON feature.features USING GIST (geom)"
        )
