"""Feature 대표 원천을 쓰기 시점에 유지하는 표 ``feature.feature_primary_sources`` — ADR-125.

Revision ID: 459_feature_primary_sources
Revises: 458_live_topic_commit_bump

왜 필요한가. 관리자 ``GET /v1/admin/features``의 ``sort=provider``와
``provider_dataset_id`` 필터, 공개 ``/features/nearby``의 ``primary_provider``·``providers``
필터, dedup 검토 목록이 Feature의 "대표 원천"을 읽을 때마다 원천 계보 다섯 표
(``source_links → source_entities → provider_datasets → source_entity_heads →
source_records``)에서 다시 골랐다. #1561 뒤에도 prod(44만 Feature)에서 ``sort=provider``
2.1 s·hash 노드 약 127 MB, 드문 dataset 필터 + 이름 정렬 약 3 s였다.

규칙(ADR-125). 대표 원천 = Feature의 ``source_role = 'primary'`` 연결 중 **가장 먼저 붙은 것**
(``source_links.created_at``, 동률이면 ``source_entity_key COLLATE "C"``). 종전 규칙("head가
가장 최근에 관측된 것")은 관측 시각이 적재마다 움직여 primary가 둘 이상인 Feature
817건(prod 2026-11-27, 전부 서로 다른 provider)의 대표가 적재 주기에 따라 바뀌었고, 쓰기
시점에 유지하려면 모든 head 관측 갱신(전량 적재마다 수십만 행)에 trigger를 걸어야 했다.
새 규칙은 ``source_links`` 행
(feature·entity·role·created_at)과 불변 식별(``source_entities.provider_dataset_id``·
``provider_datasets.provider``는 trigger가 갱신을 거부한다)에만 기댄다.

무엇을 만드는가.

- ``feature.feature_primary_source_rule`` — 규칙의 **유일한 정의**(view). trigger·backfill·정합성
  검사(F10)가 모두 이것을 읽는다. ``feature_id`` 술어는 ``DISTINCT ON`` 키라 view 안으로 내려가
  ``idx_source_links_primary``를 탄다.
- ``feature.feature_primary_sources`` — Feature 하나에 한 행(원천이 없으면 세 열이 NULL). 색인
  ``(COALESCE(provider, ''), feature_id)``가 provider 정렬 keyset을, ``(provider_dataset_id,
  feature_id)``가 dataset 필터를 받친다. FK는 두지 않는다(455와 같은 이유 — purge 증거 포획이
  ``features`` 자식을 훑는다). 행의 생성·삭제는 ``features`` 행 trigger가 한다.
- ``source_links`` 문장 trigger(INSERT·UPDATE·DELETE, transition table) — primary 연결이 바뀐
  Feature만 모아 ``feature.refresh_feature_primary_sources``를 부른다. 그 함수는 ① 행을
  보장하고 ② 그 행들을 ``feature_id`` 순서로 잠근 **뒤에** ③ 새 snapshot으로 규칙을 다시 계산한다
  — 같은 Feature의 서로 다른 연결을 두 transaction이 함께 바꿔도 뒤에 온 쪽이 앞의 commit을 본
  뒤에 계산한다(READ COMMITTED write skew 없음).
- trigger는 모두 ``ENABLE ALWAYS``다(파생 상태 — replica 역할로 쓰는 경로도 어긋나지 않게, 455와
  같다). 함수는 ``SECURITY DEFINER``이고 PUBLIC 실행권을 걷는다.

쓰기 경로를 코드마다 고치지 않고 trigger로 두는 이유는 ADR-125 §2 — ``source_links`` 쓰기는
Python repo·SQL procedure(소유자 넷)·FK cascade·migration에 흩어져 있고, 새 경로가 생겨도 정본이
어긋나지 않아야 한다.

잠금·시간 — 쓰기를 막는 창을 짧게 둔다.

1. 표·view·함수·색인을 만든다(뜨거운 표 잠금 없음).
2. trigger 없이 backfill — 5만 행 조각마다 규칙을 계산해 넣는다. ``features``·``source_links``는
   읽기만 하므로(``ACCESS SHARE``) 적재는 계속된다.
3. trigger를 만든다 — ``features``·``source_links``에 ``SHARE ROW EXCLUSIVE``(``lock_timeout`` 5초;
   진행 중인 적재가 있으면 실패하고 통째로 되돌아간다 — 다시 돌린다). 이때부터 commit까지
   두 표의 **쓰기만** 기다린다(읽기는 막지 않는다).
4. 따라잡기 — 2 동안 생긴 차이(새 Feature·지운 Feature·바뀐 연결)를 같은 조각 단위로 고친다.
   규칙 전체 재계산 한 번이다.

쓰기 대기 창은 3~4다. 실측·추정은 journal(2026-11-27)과 ADR-125 §6.

마지막 문장은 ``SET ROLE ktm_feature_schema_owner``다. forward-only.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from itertools import pairwise
from typing import Final

from sqlalchemy import text

from alembic import op

revision: str = "459_feature_primary_sources"
down_revision: str | Sequence[str] | None = "458_live_topic_commit_bump"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA_OWNER: Final[str] = "ktm_feature_schema_owner"

#: 대표 원천 규칙의 유일한 정의. 정렬의 마지막 키가 ``pk_source_links``의 둘째 열이라 Feature
#: 안에서 동률이 없다.
_RULE_VIEW_SQL: Final[str] = """
CREATE VIEW feature.feature_primary_source_rule AS
SELECT DISTINCT ON (sl.feature_id)
    sl.feature_id,
    sl.source_entity_key,
    se.provider_dataset_id,
    pd.provider
FROM provider_sync.source_links AS sl
JOIN provider_sync.source_entities AS se
  ON se.source_entity_key = sl.source_entity_key
JOIN provider_sync.provider_datasets AS pd
  ON pd.provider_dataset_id = se.provider_dataset_id
WHERE sl.source_role = 'primary'
ORDER BY sl.feature_id, sl.created_at, sl.source_entity_key COLLATE "C"
"""

_CREATE_TABLE_SQL: Final[str] = """
CREATE TABLE feature.feature_primary_sources (
    feature_id uuid NOT NULL,
    source_entity_key text,
    provider_dataset_id bigint,
    provider text,
    CONSTRAINT pk_feature_primary_sources PRIMARY KEY (feature_id),
    CONSTRAINT ck_feature_primary_sources_shape CHECK (
        (source_entity_key IS NULL) = (provider_dataset_id IS NULL)
        AND (provider_dataset_id IS NULL) = (provider IS NULL)
    )
)
"""

#: 정렬·필터 색인. 식은 ``admin_feature_repo``의 정렬 키·필터 술어와 글자 그대로 같아야 한다.
_INDEX_SQL: Final[tuple[str, ...]] = (
    "CREATE INDEX idx_feature_primary_sources_provider_keyset "
    "ON feature.feature_primary_sources ((COALESCE(provider, ''::text)), feature_id)",
    "CREATE INDEX idx_feature_primary_sources_dataset "
    "ON feature.feature_primary_sources (provider_dataset_id, feature_id)",
)

#: 주어진 Feature들의 행을 규칙에 맞춘다 — 모든 trigger가 이 하나를 부른다.
#: ① 살아 있는 Feature의 행을 보장한다(잠금 자리). ② 그 행들을 ``feature_id`` 순서로 잠근다.
#: ③ 사라진 Feature의 행을 지운다. ④ **새 문장(새 snapshot)**에서 규칙을 다시 계산해 다른 값만
#: 고친다. ②가 ④ 앞에 있어서, 같은 Feature의 연결을 함께 바꾼 다른 transaction이 있으면 그
#: commit을 기다린 뒤에 계산한다. 규칙 view는 ``feature_id = ANY(...)``를 안으로 내려 받는다
#: (조인 조건으로 두면 view 전체를 계산한다 — 그래서 바깥 조인이 아니라 부분 질의에 술어를 둔다).
_REFRESH_FUNCTION_SQL: Final[str] = """
CREATE FUNCTION feature.refresh_feature_primary_sources(p_feature_ids uuid[]) RETURNS void
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF p_feature_ids IS NULL OR cardinality(p_feature_ids) = 0 THEN
        RETURN;
    END IF;
    INSERT INTO feature.feature_primary_sources AS ps (feature_id)
    SELECT f.feature_id
      FROM feature.features AS f
     WHERE f.feature_id = ANY(p_feature_ids)
     ORDER BY f.feature_id
    ON CONFLICT (feature_id) DO NOTHING;
    PERFORM 1
       FROM feature.feature_primary_sources AS ps
      WHERE ps.feature_id = ANY(p_feature_ids)
      ORDER BY ps.feature_id
        FOR UPDATE;
    DELETE FROM feature.feature_primary_sources AS ps
     WHERE ps.feature_id = ANY(p_feature_ids)
       AND NOT EXISTS (
           SELECT 1 FROM feature.features AS f WHERE f.feature_id = ps.feature_id
       );
    UPDATE feature.feature_primary_sources AS ps
       SET source_entity_key = picked.source_entity_key,
           provider_dataset_id = picked.provider_dataset_id,
           provider = picked.provider
      FROM (
          SELECT ids.feature_id, rule.source_entity_key, rule.provider_dataset_id, rule.provider
            FROM (SELECT DISTINCT unnest(p_feature_ids) AS feature_id) AS ids
            LEFT JOIN (
                SELECT r.feature_id, r.source_entity_key, r.provider_dataset_id, r.provider
                  FROM feature.feature_primary_source_rule AS r
                 WHERE r.feature_id = ANY(p_feature_ids)
            ) AS rule
              ON rule.feature_id = ids.feature_id
      ) AS picked
     WHERE ps.feature_id = picked.feature_id
       AND (ps.source_entity_key, ps.provider_dataset_id, ps.provider)
           IS DISTINCT FROM
           (picked.source_entity_key, picked.provider_dataset_id, picked.provider);
END;
$$
"""

#: ``source_links`` 문장 trigger — primary 연결이 바뀐 Feature만 모은다. UPDATE는 규칙이 보는 열
#: (feature·entity·role·created_at)이 실제로 바뀐 행만 센다(같은 값 upsert는 지나간다). 쓰지
#: 않는 갈래의 transition table 이름은 plpgsql이 그 문장을 처음 실행할 때만 해석하므로 문제없다.
_LINKS_SYNC_FUNCTION_SQL: Final[str] = """
CREATE FUNCTION feature.sync_feature_primary_source_links() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v_feature_ids uuid[];
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT array_agg(DISTINCT n.feature_id ORDER BY n.feature_id) INTO v_feature_ids
          FROM new_links AS n
         WHERE n.source_role = 'primary';
    ELSIF TG_OP = 'DELETE' THEN
        SELECT array_agg(DISTINCT o.feature_id ORDER BY o.feature_id) INTO v_feature_ids
          FROM old_links AS o
         WHERE o.source_role = 'primary';
    ELSE
        SELECT array_agg(DISTINCT changed.feature_id ORDER BY changed.feature_id)
          INTO v_feature_ids
          FROM (
              (SELECT o.feature_id, o.source_entity_key, o.source_role, o.created_at
                 FROM old_links AS o
               EXCEPT ALL
               SELECT n.feature_id, n.source_entity_key, n.source_role, n.created_at
                 FROM new_links AS n)
              UNION ALL
              (SELECT n.feature_id, n.source_entity_key, n.source_role, n.created_at
                 FROM new_links AS n
               EXCEPT ALL
               SELECT o.feature_id, o.source_entity_key, o.source_role, o.created_at
                 FROM old_links AS o)
          ) AS changed
         WHERE changed.source_role = 'primary';
    END IF;
    IF v_feature_ids IS NOT NULL THEN
        PERFORM feature.refresh_feature_primary_sources(v_feature_ids);
    END IF;
    RETURN NULL;
END;
$$
"""

#: ``features`` 행 trigger — 행의 생성·삭제만 한다. 새 Feature는 아직 연결이 없다(연결은 FK라
#: 뒤에 온다). 같은 문장(data-modifying CTE)에서 연결까지 넣었다면 두 trigger 중 무엇이 먼저 돌든
#: 끝 상태가 같다 — 연결 trigger의 refresh가 값을 채우고, 여기는 ``DO NOTHING``이다.
_CORE_SYNC_FUNCTION_SQL: Final[str] = """
CREATE FUNCTION feature.sync_feature_primary_source_core() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        DELETE FROM feature.feature_primary_sources WHERE feature_id = OLD.feature_id;
    ELSE
        INSERT INTO feature.feature_primary_sources (feature_id)
        VALUES (NEW.feature_id)
        ON CONFLICT (feature_id) DO NOTHING;
    END IF;
    RETURN NULL;
END;
$$
"""

#: TRUNCATE는 행 trigger를 부르지 않는다. ``features``는 운영에서 TRUNCATE fence(307)가 막지만,
#: fence를 끈 정리 경로(통합 시험)도 표를 어긋나게 두지 않는다(455와 같다).
_TRUNCATE_SYNC_FUNCTION_SQL: Final[str] = """
CREATE FUNCTION feature.truncate_feature_primary_sources() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    SET search_path TO 'pg_catalog'
    AS $$
BEGIN
    IF TG_TABLE_NAME = 'features' THEN
        TRUNCATE feature.feature_primary_sources;
    ELSE
        UPDATE feature.feature_primary_sources
           SET source_entity_key = NULL,
               provider_dataset_id = NULL,
               provider = NULL
         WHERE source_entity_key IS NOT NULL;
    END IF;
    RETURN NULL;
END;
$$
"""

#: trigger 함수는 실행 권한 없이도 발화한다 — 런타임 login이 직접 부를 수 없게 PUBLIC 실행권을
#: 걷는다(런타임 preflight가 예상 밖 SECURITY DEFINER 실행권을 거부한다).
_REVOKE_FUNCTION_SQL: Final[tuple[str, ...]] = (
    "REVOKE ALL ON FUNCTION feature.refresh_feature_primary_sources(uuid[]) FROM PUBLIC",
    "REVOKE ALL ON FUNCTION feature.sync_feature_primary_source_links() FROM PUBLIC",
    "REVOKE ALL ON FUNCTION feature.sync_feature_primary_source_core() FROM PUBLIC",
    "REVOKE ALL ON FUNCTION feature.truncate_feature_primary_sources() FROM PUBLIC",
)

#: transition table을 쓰는 trigger는 사건 하나에 하나씩 만든다.
_TRIGGER_SQL: Final[tuple[str, ...]] = (
    "CREATE TRIGGER trg_source_links_primary_source_insert "
    "AFTER INSERT ON provider_sync.source_links "
    "REFERENCING NEW TABLE AS new_links FOR EACH STATEMENT "
    "EXECUTE FUNCTION feature.sync_feature_primary_source_links()",
    "CREATE TRIGGER trg_source_links_primary_source_update "
    "AFTER UPDATE ON provider_sync.source_links "
    "REFERENCING OLD TABLE AS old_links NEW TABLE AS new_links FOR EACH STATEMENT "
    "EXECUTE FUNCTION feature.sync_feature_primary_source_links()",
    "CREATE TRIGGER trg_source_links_primary_source_delete "
    "AFTER DELETE ON provider_sync.source_links "
    "REFERENCING OLD TABLE AS old_links FOR EACH STATEMENT "
    "EXECUTE FUNCTION feature.sync_feature_primary_source_links()",
    "CREATE TRIGGER trg_source_links_primary_source_truncate "
    "AFTER TRUNCATE ON provider_sync.source_links "
    "FOR EACH STATEMENT EXECUTE FUNCTION feature.truncate_feature_primary_sources()",
    "CREATE TRIGGER trg_features_zz_primary_source "
    "AFTER INSERT OR DELETE ON feature.features "
    "FOR EACH ROW EXECUTE FUNCTION feature.sync_feature_primary_source_core()",
    "CREATE TRIGGER trg_features_zz_primary_source_truncate "
    "AFTER TRUNCATE ON feature.features "
    "FOR EACH STATEMENT EXECUTE FUNCTION feature.truncate_feature_primary_sources()",
)

_ENABLE_ALWAYS_SQL: Final[tuple[str, ...]] = (
    "ALTER TABLE provider_sync.source_links "
    "ENABLE ALWAYS TRIGGER trg_source_links_primary_source_insert",
    "ALTER TABLE provider_sync.source_links "
    "ENABLE ALWAYS TRIGGER trg_source_links_primary_source_update",
    "ALTER TABLE provider_sync.source_links "
    "ENABLE ALWAYS TRIGGER trg_source_links_primary_source_delete",
    "ALTER TABLE provider_sync.source_links "
    "ENABLE ALWAYS TRIGGER trg_source_links_primary_source_truncate",
    "ALTER TABLE feature.features ENABLE ALWAYS TRIGGER trg_features_zz_primary_source",
    "ALTER TABLE feature.features ENABLE ALWAYS TRIGGER trg_features_zz_primary_source_truncate",
)

#: backfill·따라잡기 조각 크기(Feature 행 수). 조각마다 규칙 계산이 그 범위로 좁혀져 문장 하나의
#: 메모리(규칙 전체를 한 번에 고르면 hash 약 127 MB)와 시간이 묶인다.
_SLICE_ROWS: Final[int] = 50000

#: 조각 경계 — ``feature_id`` 순서로 ``_SLICE_ROWS``마다 하나. 첫 조각은 아래로, 마지막 조각은
#: 위로 열려 있어 경계를 잰 뒤에 생긴 Feature도 어느 조각에든 든다.
_SLICE_BOUNDS_SQL: Final[str] = """
SELECT b.feature_id
  FROM (
      SELECT f.feature_id, row_number() OVER (ORDER BY f.feature_id) AS rn
        FROM feature.features AS f
  ) AS b
 WHERE mod(b.rn, CAST(:slice_rows AS bigint)) = 1
   AND b.rn > 1
 ORDER BY b.feature_id
"""


def _slice_predicate(column: str, lower: bool, upper: bool) -> str:
    parts = []
    if lower:
        parts.append(f"{column} >= CAST(:lo AS uuid)")
    if upper:
        parts.append(f"{column} < CAST(:hi AS uuid)")
    return " AND ".join(parts) if parts else "TRUE"


def _backfill_sql(lower: bool, upper: bool) -> str:
    """빈 행만 규칙 값으로 넣는다(이미 있는 행은 따라잡기가 맞춘다)."""

    return f"""
INSERT INTO feature.feature_primary_sources (
    feature_id, source_entity_key, provider_dataset_id, provider
)
SELECT f.feature_id, rule.source_entity_key, rule.provider_dataset_id, rule.provider
  FROM feature.features AS f
  LEFT JOIN (
      SELECT r.feature_id, r.source_entity_key, r.provider_dataset_id, r.provider
        FROM feature.feature_primary_source_rule AS r
       WHERE {_slice_predicate("r.feature_id", lower, upper)}
  ) AS rule
    ON rule.feature_id = f.feature_id
 WHERE {_slice_predicate("f.feature_id", lower, upper)}
ON CONFLICT (feature_id) DO NOTHING
"""


def _backfill_statements(lower: bool, upper: bool) -> tuple[str, ...]:
    return (_backfill_sql(lower, upper),)


def _catch_up_sql(lower: bool, upper: bool) -> tuple[str, ...]:
    """trigger 잠금 아래에서 backfill 뒤 생긴 차이를 고친다(넣기·고치기·지우기)."""

    return (
        _backfill_sql(lower, upper),
        f"""
UPDATE feature.feature_primary_sources AS ps
   SET source_entity_key = picked.source_entity_key,
       provider_dataset_id = picked.provider_dataset_id,
       provider = picked.provider
  FROM (
      SELECT cur.feature_id, rule.source_entity_key, rule.provider_dataset_id, rule.provider
        FROM feature.feature_primary_sources AS cur
        LEFT JOIN (
            SELECT r.feature_id, r.source_entity_key, r.provider_dataset_id, r.provider
              FROM feature.feature_primary_source_rule AS r
             WHERE {_slice_predicate("r.feature_id", lower, upper)}
        ) AS rule
          ON rule.feature_id = cur.feature_id
       WHERE {_slice_predicate("cur.feature_id", lower, upper)}
  ) AS picked
 WHERE ps.feature_id = picked.feature_id
   AND (ps.source_entity_key, ps.provider_dataset_id, ps.provider)
       IS DISTINCT FROM
       (picked.source_entity_key, picked.provider_dataset_id, picked.provider)
""",
        f"""
DELETE FROM feature.feature_primary_sources AS ps
 WHERE {_slice_predicate("ps.feature_id", lower, upper)}
   AND NOT EXISTS (SELECT 1 FROM feature.features AS f WHERE f.feature_id = ps.feature_id)
""",
    )


_RECEIPT_HEAD_CHECK_SQL: Final[str] = """
ALTER TABLE ops.application_schema_operation_receipts
    DROP CONSTRAINT ck_application_schema_operation_receipts_head,
    ADD CONSTRAINT ck_application_schema_operation_receipts_head CHECK(destination_head IN (
        '300',
        '301_m03_import_children',
        '302_m03_child_issuance',
        '303_m05_payload_hash_domain',
        '304_m05_detector_manuals',
        '305_m05_relitigation_fence',
        '306_m02_manual_feature_purge',
        '307_m02_truncate_fence',
        '308_t39_provider_identities',
        '309_t39_feature_id_rekey',
        '310_seoul_source_move',
        '311_seal_member_digest',
        '312_route_geometry_sidecar',
        '313_single_service_role',
        '400',
        '401_retire_map_kma_refresh',
        '402_remove_map_weather_data',
        '403_drop_kma_notice_lineage',
        '404_transport_provider_identity',
        '405_mois_freshness_sla',
        '406_feature_write_gate',
        '407_feature_geocode_stamps',
        '408_kor_travel_geo_releases',
        '409_geo_release_item_reasons',
        '410_provider_field_shadow',
        '411_scoped_feature_write_kernel',
        '412_provider_scalar_projection',
        '413_legacy_sql_protocol_entry',
        '414_manual_dedup_protocol',
        '415_state_lifecycle_protocol',
        '416_field_override_protocol',
        '417_protocol_ex_reentry',
        '418_creation_protocol',
        '419_retire_pg_transport_values',
        '420_exclusive_provider_refresh',
        '421_stamp_writer_boundary',
        '422_heritage_evidence_reader',
        '423_exclusive_context_select',
        '424_tracking_protocol_prefix',
        '425_provider_base_update_first',
        '426_provider_patch_protocol',
        '427_transport_airport_reader',
        '428_bounded_curation_capture',
        '429_strict_sh_data_guards',
        '430_provider_snapshot_recovery',
        '431_transport_rest_reader',
        '432_rest_snapshot_atomic',
        '433_snapshot_ready_plan_reset',
        '434_protocol_entry_narrowing',
        '435_retire_sh_snapshot_path',
        '436_feature_search_aliases',
        '437_feature_command_fingerprints',
        '438_transport_reference_places',
        '439_traditional_market_dataset',
        '441_tourapi_attraction_dataset',
        '442_mois_brand_search_aliases',
        '444_trip_search_aliases',
        '446_mcst_place_attributes',
        '447_admin_search_trgm_indexes',
        '448_mcst_theme_transition',
        '449_tourapi_festivals_primary',
        '450_incheon_airport_search_alias',
        '451_feature_search_prominence',
        '452_lotte_hotel_search_alias',
        '453_features_autovacuum',
        '454_route_cluster_markers',
        '455_feature_cluster_points',
        '456_feature_update_retry',
        '457_event_clock_slots',
        '458_live_topic_commit_bump',
        '459_feature_primary_sources'
    ))
"""

#: 실행 순서대로의 정적 문장. 창은 소유자 롤로 열고 같은 롤로 끝난다(455와 같다). 조각 단위 DML
#: 두 단계(backfill은 준비 뒤·trigger 앞, 따라잡기는 trigger 뒤·마무리 앞)는 ``upgrade``가 끼워
#: 넣는다 — 둘 다 롤을 바꾸지 않는다.
_SETUP_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE " + _SCHEMA_OWNER,
    _RULE_VIEW_SQL,
    _CREATE_TABLE_SQL,
    *_INDEX_SQL,
    _REFRESH_FUNCTION_SQL,
    _LINKS_SYNC_FUNCTION_SQL,
    _CORE_SYNC_FUNCTION_SQL,
    _TRUNCATE_SYNC_FUNCTION_SQL,
    *_REVOKE_FUNCTION_SQL,
)
_TRIGGER_STATEMENTS: Final[tuple[str, ...]] = (*_TRIGGER_SQL, *_ENABLE_ALWAYS_SQL)
_FINISH_STATEMENTS: Final[tuple[str, ...]] = (
    "ANALYZE feature.feature_primary_sources",
    _RECEIPT_HEAD_CHECK_SQL,
    "SET ROLE " + _SCHEMA_OWNER,
)
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    *_SETUP_STATEMENTS,
    *_TRIGGER_STATEMENTS,
    *_FINISH_STATEMENTS,
)
_LOCK_TIMEOUT_MS: Final[int] = 1000
#: 두 뜨거운 표의 trigger 생성(``SHARE ROW EXCLUSIVE``) — 진행 중인 쓰기 transaction을 이만큼만
#: 기다린다. 넘으면 migration 전체가 되돌아간다(재시도 가능).
_TRIGGER_LOCK_TIMEOUT_MS: Final[int] = 5000
_STATEMENT_TIMEOUT_CAP_MS: Final[int] = 300000


def upgrade() -> None:
    """대표 원천 표·규칙 view·trigger를 만들고 조각 단위로 채운다."""
    bind = op.get_bind()
    settings = {
        str(name): str(value)
        for name, value in bind.execute(
            text(
                "SELECT name,setting FROM pg_settings "
                "WHERE name IN ('lock_timeout','statement_timeout')"
            )
        ).all()
    }

    def cap(name: str, limit: int) -> None:
        prior = int(settings[name])
        bind.execute(
            text("SELECT set_config(:name,:value,true)"),
            {"name": name, "value": str(min(prior, limit) if prior else limit)},
        )

    def run_slices(builder: Callable[[bool, bool], tuple[str, ...]]) -> None:
        bounds = [
            str(value)
            for value in bind.execute(
                text(_SLICE_BOUNDS_SQL), {"slice_rows": _SLICE_ROWS}
            ).scalars()
        ]
        edges: list[str | None] = [None, *bounds, None]
        for lo, hi in pairwise(edges):
            for statement in builder(lo is not None, hi is not None):
                bind.execute(text(statement), {"lo": lo, "hi": hi})

    cap("statement_timeout", _STATEMENT_TIMEOUT_CAP_MS)
    cap("lock_timeout", _LOCK_TIMEOUT_MS)
    # 1. 뜨거운 표 잠금 없이 만든다.
    for statement in _SETUP_STATEMENTS:
        bind.execute(text(statement))
    # 2. trigger 없이 채운다 — 적재는 계속된다.
    run_slices(_backfill_statements)
    # 3. trigger — 이때부터 commit까지 두 표의 쓰기가 기다린다.
    cap("lock_timeout", _TRIGGER_LOCK_TIMEOUT_MS)
    for statement in _TRIGGER_STATEMENTS:
        bind.execute(text(statement))
    cap("lock_timeout", _LOCK_TIMEOUT_MS)
    # 4. 2 동안 생긴 차이를 고친다.
    run_slices(_catch_up_sql)
    for statement in _FINISH_STATEMENTS:
        bind.execute(text(statement))
    for name, value in settings.items():
        bind.execute(text("SELECT set_config(:name,:value,true)"), {"name": name, "value": value})
    bind.execute(text("SET ROLE " + _SCHEMA_OWNER))


def downgrade() -> None:
    """되돌리지 않는다 — 표·trigger는 forward revision으로만 걷는다."""
    raise RuntimeError(
        "459_feature_primary_sources is forward-only: 표·trigger는 forward revision으로만 걷는다."
    )
