"""T-VN-39 (2) — legacy TEXT ``feature_id``를 물리 제거하고 uuid로 재키한다.

Revision ID: 309_t39_feature_id_rekey
Revises: 308_t39_provider_identities

설계 근거는 ``docs/reports/t-vn-39-rekey-design-2026-09-09.md``와 ADR-098이 소유한다.
여기에는 **그 결정이 DDL에서 어떻게 순서가 되는지**만 적는다.

## 백필이 아니라 전제조건이다

``provider_sync.provider_feature_identities``의 축은
``(provider_dataset_id, feature_kind, natural_key)``인데 그 ``natural_key``가 **DB
어디에도 없다.** ``source_entities.source_entity_id``는 grain이 다르고(opinet은
entity id가 제품별, 자연키가 주유소별이다) ``feature_aliases.alias``의 ``f_*``는
단방향 sha1이라 역산할 수 없다. 자연키는 provider 변환기가 적재 시점에만 안다.

그래서 기존 행에 claim을 만들 방법이 없고, **백필 대신 전제조건**을 건다 —
``feature.features``가 0행이 아니면 이 마이그레이션은 이름을 대고 거부한다. 그 검사가
없으면 행이 있는 DB에서 재키가 **성공하고**, 다음 ETL이 그 Feature들을 통째로 다시
만든다. 그 시점에는 원인이 마이그레이션으로 보이지 않는다.

prod는 0행이고(2026-09-08 실측) 소유자가 재적재를 승인했다. CI는 마이그레이션이 데이터
삽입 **전에** 돌므로 항상 0행이다.

## `USING`은 서브쿼리를 못 받는다

alias로 풀어야 하는 21개 컬럼을 서브쿼리로 쓰면 ``ALTER COLUMN ... USING``이 거부한다.
함수로 감싸고 **매칭 실패를 조용한 NULL이 아니라 RAISE**로 만든다. 임시 컬럼
추가/UPDATE/DROP 방식이었다면 그 21개 컬럼의 인덱스·제약을 전부 다시 열거해야 했다 —
``ALTER COLUMN TYPE``은 그것들을 자동 재구축한다.

## 트리거가 조용히 사라진다

``trg_features_identity_fence``는 ``BEFORE UPDATE OF feature_id, feature_uuid``다.
PostgreSQL은 컬럼 목록의 **각 컬럼에** DEPENDENCY_AUTO를 기록하므로, 재키가 어느 쪽을
DROP하든 이 트리거가 **오류도 경고도 없이** 함께 삭제된다. 그래서 재생성을 재키
**뒤**에 놓는다 — 앞에 두면 새 트리거가 아직 text인 컬럼에 의존을 걸고 곧바로 다시
사라진다.

## 뷰의 `::text` 조인을 남기면 인덱스가 죽는다

``feature.public_features``의 subtype 조인 5곳이
``((place.feature_id)::text = (core.feature_id)::text)`` 형태다. 그대로 재생성하면
결과는 맞고 planner가 인덱스를 못 쓴다. ``feature.features``가 0행인 CI에서는
**관측되지 않고** prod에서만 느려진다.

슬롯 2는 ``CAST(core.feature_id AS text) AS feature_uuid``로 남긴다 — 26열의 이름과
순서가 소비자 계약이고 ``tvn34c-post-cutover-invariants-v1.sql``의 INV-34C-04가
그것을 고정한다.

## 루틴은 사이드카가 소유한다

23개 루틴의 본문은 ``_309_*.sql``에 있다. 소유자 롤이 7개로 갈리므로 ``SET ROLE``로
왕복한다(``302_m03_child_issuance``가 같은 규율이다). 시그니처가 바뀌는 13개는
DROP+CREATE라 명시 ACL이 사라지므로 사이드카가 REVOKE/GRANT/OWNER를 함께 낸다.
시그니처가 같은 8개는 ``CREATE OR REPLACE``라 ACL이 보존된다.

DDL은 문장 하나씩 실행한다(asyncpg prepared statement 제약).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from alembic import op

# ruff: noqa: E501

#: **32자 이하여야 한다** — `public.alembic_version.version_num`이 `varchar(32)`다.
revision: Final[str] = "309_t39_feature_id_rekey"
down_revision: Final[str] = "308_t39_provider_identities"
branch_labels: None = None
depends_on: None = None

_HERE: Final[Path] = Path(__file__).parent


def _sidecar(name: str) -> tuple[str, ...]:
    """사이드카를 **문장 단위로** 쪼갠다.

    asyncpg는 prepared statement 하나에 여러 명령을 넣지 못한다
    (`cannot insert multiple commands into a prepared statement`). 이 저장소의 기존
    사이드카는 파일당 한 문장이라 그 제약이 드러난 적이 없는데, T-VN-39의 사이드카는
    시그니처가 바뀌어 `DROP` + `CREATE` + `ALTER OWNER` + `REVOKE` + `GRANT`를 함께
    낸다. 2026-09-09 n150 첫 실행이 이것을 잡았다.

    달러 인용 안의 세미콜론은 세지 않는다 — 그것을 놓치면 plpgsql 본문이 중간에서
    잘리고, 그 실패는 "문법 오류"로 나타나 원인을 가리키지 않는다.

    **태그를 `$$`로 가정하면 안 된다.** head 덤프는 `$_$`도 쓴다(실측: `$$` 60회,
    `$_$` 8회). 첫 구현이 `$$`만 보다가 `unterminated dollar-quoted string`으로
    죽었다 — 여는 태그를 읽어 **같은 태그**로 닫는다.
    """

    body = (_HERE / name).read_text(encoding="utf-8")
    opener = re.compile(r"\$[A-Za-z_][A-Za-z_0-9]*\$|\$\$")
    statements: list[str] = []
    current: list[str] = []
    index = 0
    tag: str | None = None
    while index < len(body):
        if tag is None:
            match = opener.match(body, index)
            if match is not None:
                tag = match.group(0)
                current.append(tag)
                index = match.end()
                continue
            if body[index] == ";":
                statement = "".join(current).strip()
                if statement:
                    statements.append(statement)
                current = []
                index += 1
                continue
        elif body.startswith(tag, index):
            current.append(tag)
            index += len(tag)
            tag = None
            continue
        current.append(body[index])
        index += 1
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    if tag is not None:
        raise RuntimeError(f"사이드카의 달러 인용이 닫히지 않았다: {name} (태그 {tag})")
    if not statements:
        raise RuntimeError(f"사이드카에서 문장을 하나도 읽지 못했다: {name}")
    return tuple(statements)

# 재타입 선행 2 · 나머지 32 · shadow 13 · FK drop 40 · FK 재생성 34 · 영구삭제 6

#: features·aliases 먼저 — alias 조회의 원천이고 fence 함수가 중간 상태를 못 견딘다.
_RETYPE_IDENTITY: Final[tuple[str, ...]] = (
    "ALTER TABLE feature.feature_aliases ALTER COLUMN feature_id TYPE uuid USING feature_uuid",
    "ALTER TABLE feature.features ALTER COLUMN feature_id TYPE uuid USING feature_uuid",
)

#: shadow가 있으면 그 값을 승계하고, 없으면 alias로 푼다.
#:
#: **표 단위로 한 문장에 묶는다.** 같은 표의 두 컬럼을 따로 ALTER하면 그 둘을 함께
#: 보는 CHECK가 중간 상태에서 재검사되어 `uuid = text`로 죽는다 — 2026-09-09 n150
#: 실측: `theme_feature_candidate_transitions`의
#: `ck_candidate_transition_initial_shape`가 `from_feature_id IS DISTINCT FROM
#: to_feature_id`를 본다. `dedup_review_queue`(a/b) · `feature_merge_history`
#: (master/loser) · `feature_reference_reconciliation_events`(old/replacement) ·
#: `manual_provider_dedup_cases`(manual/provider)도 같은 모양이다.
_RETYPE_REST: Final[tuple[str, ...]] = (
    "ALTER TABLE feature.curation_items ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE feature.curation_link_decisions ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE feature.current_price_summary ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE feature.current_weather_summary ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE feature.feature_areas ALTER COLUMN feature_id TYPE uuid USING feature_uuid",
    "ALTER TABLE feature.feature_base_field_values ALTER COLUMN feature_id TYPE uuid USING feature_uuid",
    "ALTER TABLE feature.feature_events ALTER COLUMN feature_id TYPE uuid USING feature_uuid",
    "ALTER TABLE feature.feature_notices ALTER COLUMN feature_id TYPE uuid USING feature_uuid",
    "ALTER TABLE feature.feature_places ALTER COLUMN feature_id TYPE uuid USING feature_uuid",
    "ALTER TABLE feature.feature_price_values ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE feature.feature_routes ALTER COLUMN feature_id TYPE uuid USING feature_uuid",
    "ALTER TABLE feature.feature_state_transitions ALTER COLUMN feature_id TYPE uuid USING feature_uuid",
    "ALTER TABLE feature.feature_weather_values ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE feature.features ALTER COLUMN parent_feature_id TYPE uuid USING feature.t39_uuid_for_legacy(parent_feature_id)",
    "ALTER TABLE feature.theme_candidate_generation_observations ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE feature.theme_feature_candidate_transitions ALTER COLUMN from_feature_id TYPE uuid USING feature.t39_uuid_for_legacy(from_feature_id), ALTER COLUMN to_feature_id TYPE uuid USING feature.t39_uuid_for_legacy(to_feature_id)",
    "ALTER TABLE feature.theme_feature_candidates ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE ops.data_integrity_violations ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE ops.dedup_review_queue ALTER COLUMN feature_id_a TYPE uuid USING feature.t39_uuid_for_legacy(feature_id_a), ALTER COLUMN feature_id_b TYPE uuid USING feature.t39_uuid_for_legacy(feature_id_b)",
    "ALTER TABLE ops.enrichment_review_queue ALTER COLUMN target_feature_id TYPE uuid USING feature.t39_uuid_for_legacy(target_feature_id)",
    "ALTER TABLE ops.feature_merge_history ALTER COLUMN loser_feature_id TYPE uuid USING feature.t39_uuid_for_legacy(loser_feature_id), ALTER COLUMN master_feature_id TYPE uuid USING feature.t39_uuid_for_legacy(master_feature_id)",
    "ALTER TABLE ops.feature_overrides ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE ops.feature_reference_reconciliation_events ALTER COLUMN old_feature_id TYPE uuid USING old_feature_uuid, ALTER COLUMN replacement_feature_id TYPE uuid USING replacement_feature_uuid",
    "ALTER TABLE ops.import_job_events ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE ops.manual_provider_dedup_cases ALTER COLUMN manual_feature_id TYPE uuid USING manual_feature_uuid, ALTER COLUMN provider_feature_id TYPE uuid USING provider_feature_uuid",
    "ALTER TABLE ops.poi_cache_target_feature_links ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
    "ALTER TABLE provider_sync.source_links ALTER COLUMN feature_id TYPE uuid USING feature.t39_uuid_for_legacy(feature_id)",
)

_SHADOW_DROP: Final[tuple[str, ...]] = (
    "ALTER TABLE feature.feature_aliases DROP COLUMN feature_uuid",
    "ALTER TABLE feature.feature_areas DROP COLUMN feature_uuid",
    "ALTER TABLE feature.feature_base_field_values DROP COLUMN feature_uuid",
    "ALTER TABLE feature.feature_events DROP COLUMN feature_uuid",
    "ALTER TABLE feature.feature_notices DROP COLUMN feature_uuid",
    "ALTER TABLE feature.feature_places DROP COLUMN feature_uuid",
    "ALTER TABLE feature.feature_routes DROP COLUMN feature_uuid",
    "ALTER TABLE feature.feature_state_transitions DROP COLUMN feature_uuid",
    "ALTER TABLE feature.features DROP COLUMN feature_uuid",
    "ALTER TABLE ops.feature_reference_reconciliation_events DROP COLUMN old_feature_uuid",
    "ALTER TABLE ops.feature_reference_reconciliation_events DROP COLUMN replacement_feature_uuid",
    "ALTER TABLE ops.manual_provider_dedup_cases DROP COLUMN manual_feature_uuid",
    "ALTER TABLE ops.manual_provider_dedup_cases DROP COLUMN provider_feature_uuid",
)

#: features 참조 34 + 2차 파급 6. 크로스 표 타입 불일치 때문에 전부 선행 DROP.
_FK_DROP: Final[tuple[str, ...]] = (
    "ALTER TABLE feature.curation_items DROP CONSTRAINT curation_items_feature_id_fkey",
    "ALTER TABLE feature.curation_items DROP CONSTRAINT fk_curation_items_accepted_link_decision",
    "ALTER TABLE feature.current_price_summary DROP CONSTRAINT current_price_summary_feature_id_fkey",
    "ALTER TABLE feature.current_price_summary DROP CONSTRAINT fk_current_price_summary_fact",
    "ALTER TABLE feature.current_weather_summary DROP CONSTRAINT current_weather_summary_feature_id_fkey",
    "ALTER TABLE feature.current_weather_summary DROP CONSTRAINT fk_current_weather_summary_fact",
    "ALTER TABLE feature.feature_aliases DROP CONSTRAINT fk_feature_aliases_feature",
    "ALTER TABLE feature.feature_aliases DROP CONSTRAINT fk_feature_aliases_identity_pair",
    "ALTER TABLE feature.feature_areas DROP CONSTRAINT fk_feature_areas_feature_kind",
    "ALTER TABLE feature.feature_areas DROP CONSTRAINT fk_feature_areas_identity_pair",
    "ALTER TABLE feature.feature_base_field_values DROP CONSTRAINT fk_feature_base_field_values_feature_identity",
    "ALTER TABLE feature.feature_events DROP CONSTRAINT fk_feature_events_feature_kind",
    "ALTER TABLE feature.feature_events DROP CONSTRAINT fk_feature_events_identity_pair",
    "ALTER TABLE feature.feature_notices DROP CONSTRAINT fk_feature_notices_feature_kind",
    "ALTER TABLE feature.feature_notices DROP CONSTRAINT fk_feature_notices_identity_pair",
    "ALTER TABLE feature.feature_places DROP CONSTRAINT fk_feature_places_feature_kind",
    "ALTER TABLE feature.feature_places DROP CONSTRAINT fk_feature_places_identity_pair",
    "ALTER TABLE feature.feature_price_values DROP CONSTRAINT feature_price_values_feature_id_fkey",
    "ALTER TABLE feature.feature_routes DROP CONSTRAINT fk_feature_routes_feature_kind",
    "ALTER TABLE feature.feature_routes DROP CONSTRAINT fk_feature_routes_identity_pair",
    "ALTER TABLE feature.feature_weather_values DROP CONSTRAINT feature_weather_values_feature_id_fkey",
    "ALTER TABLE feature.features DROP CONSTRAINT fk_features_parent_feature_id_features",
    "ALTER TABLE feature.theme_feature_candidates DROP CONSTRAINT theme_feature_candidates_feature_id_fkey",
    "ALTER TABLE ops.data_integrity_violations DROP CONSTRAINT fk_data_integrity_violations_feature_id_features",
    "ALTER TABLE ops.dedup_review_queue DROP CONSTRAINT fk_dedup_review_queue_feature_id_a_features",
    "ALTER TABLE ops.dedup_review_queue DROP CONSTRAINT fk_dedup_review_queue_feature_id_b_features",
    "ALTER TABLE ops.enrichment_review_queue DROP CONSTRAINT fk_enrichment_review_queue_target_feature_id_features",
    "ALTER TABLE ops.feature_merge_history DROP CONSTRAINT fk_feature_merge_history_loser_feature_id_features",
    "ALTER TABLE ops.feature_merge_history DROP CONSTRAINT fk_feature_merge_history_master_feature_id_features",
    "ALTER TABLE ops.feature_overrides DROP CONSTRAINT fk_feature_overrides_feature_id_features",
    "ALTER TABLE ops.feature_reference_reconciliation_events DROP CONSTRAINT fk_feature_reference_reconciliation_events_old_identity",
    "ALTER TABLE ops.feature_reference_reconciliation_events DROP CONSTRAINT fk_feature_reference_reconciliation_events_replacement_identity",
    "ALTER TABLE ops.feature_requests DROP CONSTRAINT feature_requests_resolved_feature_id_fkey",
    "ALTER TABLE ops.manual_provider_dedup_cases DROP CONSTRAINT fk_manual_provider_dedup_cases_manual_claim",
    "ALTER TABLE ops.manual_provider_dedup_cases DROP CONSTRAINT fk_manual_provider_dedup_cases_manual_identity",
    "ALTER TABLE ops.manual_provider_dedup_cases DROP CONSTRAINT fk_manual_provider_dedup_cases_manual_origin",
    "ALTER TABLE ops.manual_provider_dedup_cases DROP CONSTRAINT fk_manual_provider_dedup_cases_provider_identity",
    "ALTER TABLE ops.manual_provider_dedup_cases DROP CONSTRAINT fk_manual_provider_dedup_cases_provider_link",
    "ALTER TABLE ops.poi_cache_target_feature_links DROP CONSTRAINT fk_poi_cache_target_feature_links_feature_id_features",
    "ALTER TABLE provider_sync.source_links DROP CONSTRAINT fk_source_links_feature_id_features",
)

#: composite 11 중 6은 기존 FK가 이미 덮으므로 영구 삭제한다.
_FK_RECREATE: Final[tuple[str, ...]] = (
    "ALTER TABLE feature.curation_items ADD CONSTRAINT curation_items_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE SET NULL",
    "ALTER TABLE feature.curation_items ADD CONSTRAINT fk_curation_items_accepted_link_decision FOREIGN KEY (accepted_link_decision_id, curation_item_id, feature_id) REFERENCES feature.curation_link_decisions (decision_id, curation_item_id, feature_id) ON DELETE RESTRICT DEFERRABLE INITIALLY DEFERRED",
    "ALTER TABLE feature.current_price_summary ADD CONSTRAINT current_price_summary_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE feature.current_price_summary ADD CONSTRAINT fk_current_price_summary_fact FOREIGN KEY (price_value_key, feature_id, provider_dataset_id, price_domain, product_key) REFERENCES feature.feature_price_values (price_value_key, feature_id, provider_dataset_id, price_domain, product_key) ON DELETE CASCADE",
    "ALTER TABLE feature.current_weather_summary ADD CONSTRAINT current_weather_summary_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE feature.current_weather_summary ADD CONSTRAINT fk_current_weather_summary_fact FOREIGN KEY (weather_value_key, feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key) REFERENCES feature.feature_weather_values (weather_value_key, feature_id, provider_dataset_id, weather_domain, forecast_style, metric_key) ON DELETE CASCADE",
    "ALTER TABLE feature.feature_aliases ADD CONSTRAINT fk_feature_aliases_feature FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE feature.feature_areas ADD CONSTRAINT fk_feature_areas_feature_kind FOREIGN KEY (feature_id, kind) REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE",
    "ALTER TABLE feature.feature_base_field_values ADD CONSTRAINT fk_feature_base_field_values_feature_identity FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE feature.feature_events ADD CONSTRAINT fk_feature_events_feature_kind FOREIGN KEY (feature_id, kind) REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE",
    "ALTER TABLE feature.feature_notices ADD CONSTRAINT fk_feature_notices_feature_kind FOREIGN KEY (feature_id, kind) REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE",
    "ALTER TABLE feature.feature_places ADD CONSTRAINT fk_feature_places_feature_kind FOREIGN KEY (feature_id, kind) REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE",
    "ALTER TABLE feature.feature_price_values ADD CONSTRAINT feature_price_values_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE feature.feature_routes ADD CONSTRAINT fk_feature_routes_feature_kind FOREIGN KEY (feature_id, kind) REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE",
    "ALTER TABLE feature.feature_weather_values ADD CONSTRAINT feature_weather_values_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE feature.features ADD CONSTRAINT fk_features_parent_feature_id_features FOREIGN KEY (parent_feature_id) REFERENCES feature.features (feature_id) ON DELETE SET NULL",
    "ALTER TABLE feature.theme_feature_candidates ADD CONSTRAINT theme_feature_candidates_feature_id_fkey FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE RESTRICT",
    "ALTER TABLE ops.data_integrity_violations ADD CONSTRAINT fk_data_integrity_violations_feature_id_features FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE SET NULL",
    "ALTER TABLE ops.dedup_review_queue ADD CONSTRAINT fk_dedup_review_queue_feature_id_a_features FOREIGN KEY (feature_id_a) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE ops.dedup_review_queue ADD CONSTRAINT fk_dedup_review_queue_feature_id_b_features FOREIGN KEY (feature_id_b) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE ops.enrichment_review_queue ADD CONSTRAINT fk_enrichment_review_queue_target_feature_id_features FOREIGN KEY (target_feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE ops.feature_merge_history ADD CONSTRAINT fk_feature_merge_history_loser_feature_id_features FOREIGN KEY (loser_feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE ops.feature_merge_history ADD CONSTRAINT fk_feature_merge_history_master_feature_id_features FOREIGN KEY (master_feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE ops.feature_overrides ADD CONSTRAINT fk_feature_overrides_feature_id_features FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE ops.feature_reference_reconciliation_events ADD CONSTRAINT fk_feature_reference_reconciliation_events_old_identity FOREIGN KEY (old_feature_id) REFERENCES feature.features (feature_id) ON DELETE RESTRICT",
    "ALTER TABLE ops.feature_reference_reconciliation_events ADD CONSTRAINT fk_feature_reference_reconciliation_events_replacement_identity FOREIGN KEY (replacement_feature_id) REFERENCES feature.features (feature_id) ON DELETE RESTRICT",
    "ALTER TABLE ops.feature_requests ADD CONSTRAINT feature_requests_resolved_feature_id_fkey FOREIGN KEY (resolved_feature_id) REFERENCES feature.features (feature_id)",
    "ALTER TABLE ops.manual_provider_dedup_cases ADD CONSTRAINT fk_manual_provider_dedup_cases_manual_claim FOREIGN KEY (manual_feature_id, manual_creation_command_id) REFERENCES feature.manual_feature_identity_claims (feature_id, claimed_by_command_id) ON DELETE RESTRICT",
    "ALTER TABLE ops.manual_provider_dedup_cases ADD CONSTRAINT fk_manual_provider_dedup_cases_manual_identity FOREIGN KEY (manual_feature_id) REFERENCES feature.features (feature_id) ON DELETE RESTRICT",
    "ALTER TABLE ops.manual_provider_dedup_cases ADD CONSTRAINT fk_manual_provider_dedup_cases_manual_origin FOREIGN KEY (manual_feature_id, manual_creation_command_id) REFERENCES feature.feature_creation_origins (feature_id, creation_command_id) ON DELETE RESTRICT",
    "ALTER TABLE ops.manual_provider_dedup_cases ADD CONSTRAINT fk_manual_provider_dedup_cases_provider_identity FOREIGN KEY (provider_feature_id) REFERENCES feature.features (feature_id) ON DELETE RESTRICT",
    "ALTER TABLE ops.manual_provider_dedup_cases ADD CONSTRAINT fk_manual_provider_dedup_cases_provider_link FOREIGN KEY (provider_feature_id, source_entity_key) REFERENCES provider_sync.source_links (feature_id, source_entity_key) ON DELETE RESTRICT",
    "ALTER TABLE ops.poi_cache_target_feature_links ADD CONSTRAINT fk_poi_cache_target_feature_links_feature_id_features FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
    "ALTER TABLE provider_sync.source_links ADD CONSTRAINT fk_source_links_feature_id_features FOREIGN KEY (feature_id) REFERENCES feature.features (feature_id) ON DELETE CASCADE",
)

# 영구 삭제되는 composite FK (같은 표의 다른 FK가 덮는다):
#   fk_feature_aliases_identity_pair                         ← fk_feature_aliases_feature
#   fk_feature_areas_identity_pair                           ← fk_feature_areas_feature_kind
#   fk_feature_events_identity_pair                          ← fk_feature_events_feature_kind
#   fk_feature_notices_identity_pair                         ← fk_feature_notices_feature_kind
#   fk_feature_places_identity_pair                          ← fk_feature_places_feature_kind
#   fk_feature_routes_identity_pair                          ← fk_feature_routes_feature_kind


#: 재키가 값을 옮길 수 없는 행이 있으면 **여기서 선다.**
_PRECONDITION: Final[str] = """
DO $$
DECLARE
    n bigint;
BEGIN
    SELECT count(*) INTO n FROM feature.features;
    IF n > 0 THEN
        RAISE EXCEPTION
            'T-VN-39: feature.features에 %행이 있다 — 이 행들은 provider identity '
            'claim을 얻을 수 없다. claim 축의 natural_key는 DB 어디에도 없고'
            '(source_entity_id는 grain이 다르고 f_* alias는 단방향 sha1이다) '
            'provider 변환기가 적재 시점에만 안다. 재적재가 전제다.', n
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_t39_rekey_requires_empty_features';
    END IF;
END
$$
"""

#: `ALTER COLUMN ... USING`은 서브쿼리를 못 받는다. 함수로 감싸고 매칭 실패를
#: **RAISE**로 만든다 — 조용한 NULL은 NOT NULL 컬럼에서 나중에, 엉뚱한 자리에서 터진다.
_LEGACY_LOOKUP: Final[str] = """
CREATE FUNCTION feature.t39_uuid_for_legacy(p_alias text) RETURNS uuid
    LANGUAGE plpgsql STABLE
    SET search_path TO 'pg_catalog'
    AS $$
DECLARE
    v uuid;
BEGIN
    IF p_alias IS NULL THEN
        RETURN NULL;
    END IF;
    SELECT a.feature_id INTO v
      FROM feature.feature_aliases AS a
     WHERE a.alias = p_alias;
    IF v IS NULL THEN
        RAISE EXCEPTION
            'T-VN-39 재키: legacy feature_id %에 대응하는 alias가 없다 — '
            '이 값은 uuid로 옮길 수 없다.', p_alias
            USING ERRCODE = '23502';
    END IF;
    RETURN v;
END
$$
"""

_LEGACY_LOOKUP_DROP: Final[str] = "DROP FUNCTION feature.t39_uuid_for_legacy(text)"

#: 저장소 유일 뷰. `ALTER COLUMN TYPE`의 절대 선행 조건이다(뷰 의존이 있으면 2BP01).
_VIEW_DROP: Final[str] = "DROP VIEW feature.public_features"

#: 본문이 `feature_uuid`를 참조하는 features·aliases 트리거. plpgsql은 의존성을
#: 추적하지 않으므로 **같은 트랜잭션**에서 내려야 한다.
#: `trg_features_row_revision`과 `trg_features_manual_feature_truncate_fence`는
#: 두 컬럼을 한 번도 참조하지 않는다(실측) — 내리지 않는다.
_TRIGGER_DROP: Final[tuple[str, ...]] = (
    "DROP TRIGGER trg_features_feature_uuid_fill ON feature.features",
    "DROP TRIGGER trg_features_identity_fence ON feature.features",
    "DROP TRIGGER trg_features_legacy_alias ON feature.features",
    "DROP TRIGGER trg_feature_aliases_delete_fence ON feature.feature_aliases",
    "DROP TRIGGER trg_feature_aliases_update_fence ON feature.feature_aliases",
    "DROP TRIGGER trg_feature_aliases_no_truncate ON feature.feature_aliases",
)

#: `alias = feature_id`. text와 uuid 사이에는 `=` 연산자가 없으므로 재부착이 영구히
#: 불가능하다. 되살려서도 안 된다 — legacy 키가 업무키가 아니라는 것이 재키의 요지다.
_ALIAS_IDENTITY_CHECK_DROP: Final[str] = (
    "ALTER TABLE feature.feature_aliases"
    " DROP CONSTRAINT ck_feature_aliases_legacy_identity"
)

#: legacy 문자열을 **증거로** 남기는 표. uuid로 옮기면 증거가 파괴된다. 이름만
#: 정직하게 바꾼다 — `feature_id`로 남기면 다음 사람이 uuid로 착각한다.
_EVIDENCE_RENAME: Final[tuple[str, ...]] = (
    "ALTER TABLE feature.manual_feature_purge_records"
    " RENAME COLUMN feature_id TO legacy_feature_id",
    "ALTER TABLE feature.manual_feature_purge_records"
    " RENAME COLUMN feature_uuid TO feature_id",
    # RENAME은 NOT NULL을 보존한다. 재키 뒤 태어난 Feature는 legacy 주소를 애초에
    # 갖지 않으므로(ADR-098 결정 6) 이 열의 NULL은 결손이 아니라 참이다 —
    # `_309_purge_manual_feature.sql`이 스스로 적어 둔 계약 선결조건의 이행이다.
    "ALTER TABLE feature.manual_feature_purge_records"
    " ALTER COLUMN legacy_feature_id DROP NOT NULL",
    "ALTER TABLE ops.tvn36_legacy_freeze_preflight_manifest"
    " RENAME COLUMN feature_id TO legacy_feature_id",
    # 텍스트 짝이 없다 — 이 표의 진짜 identity다. 삭제가 아니라 개명.
    "ALTER TABLE ops.curation_import_manual_feature_children"
    " RENAME COLUMN feature_uuid TO feature_id",
)

#: `DROP COLUMN`이 **조용히 함께 지우는** 것. 미리 열거하고 뒤에서 재생성한다.
_COLLATERAL_RECREATE: Final[tuple[str, ...]] = (
    "ALTER TABLE ops.feature_reference_reconciliation_events"
    " ADD CONSTRAINT ck_feature_reference_reconciliation_events_replacement"
    " CHECK (((action = 'rebind'::text) AND (replacement_feature_id IS NOT NULL)"
    " AND (replacement_feature_row_revision IS NOT NULL))"
    " OR ((action = 'detach'::text) AND (replacement_feature_id IS NULL)"
    " AND (replacement_feature_row_revision IS NULL)))",
    "CREATE INDEX idx_manual_provider_dedup_cases_decision_fence"
    " ON ops.manual_provider_dedup_cases"
    " USING btree (manual_feature_id, provider_feature_id, decision_fingerprint)",
    # `ck_feature_aliases_legacy_identity`(alias = feature_id)는 uuid = text가 되어
    # 되살릴 수 없다. 그 자리를 값 관계가 아니라 **형태**로 받는다 — legacy alias는
    # `make_feature_id` 산출물(`f_{bjd|global}_{kind[0]}_{sha1[:16]}`)만 담고,
    # uuid 표기는 이 형태에 걸리지 않으므로 "정본 키를 alias로 되풀이하지 않는다"가
    # DB 층에서 강제된다(새 INV-068-01의 착지점, ADR-098 결정 6).
    #
    # bjd 자리를 `.+`로 두는 이유: `make_feature_id`는 `bjd_code`를 검증하지 않아
    # (`core/ids.py:150-155`가 kind/category/source_type/natural_key만 본다) 밑줄이
    # 섞인 값이 원리적으로 가능하다. 더 좁은 `[^_]+`로 조이면 그런 provider 하나가
    # 전량 23514로 멎는다 — 형태 검사가 적재를 막는 것은 이 CHECK의 목적이 아니다.
    "ALTER TABLE feature.feature_aliases"
    " ADD CONSTRAINT ck_feature_aliases_legacy_alias_shape"
    " CHECK (alias_kind <> 'legacy_feature_id'"
    "        OR alias ~ '^f_.+_[a-z]_[0-9a-f]{16}$')",
    # `ALTER COLUMN TYPE`은 살아남은 CHECK의 식을 **다시 쓴다** — text 시절의
    # `feature_id_a < feature_id_b`가 uuid 재타입 뒤 `(feature_id_a)::text <
    # (feature_id_b)::text`로 catalog에 남는다. 값의 순서는 canonical uuid 표기에서
    # 바이트 순서와 같아 바뀌지 않지만, ORM 선언(`models.py`의
    # `CheckConstraint("feature_id_a < feature_id_b")`)과 catalog가 달라져
    # `test_fresh_300_upgrade_is_metadata_clean`이 drift로 잡는다. 식을 uuid 축으로
    # 되돌린다 — 캐스트가 남으면 인덱스도 못 쓴다.
    "ALTER TABLE ops.dedup_review_queue"
    " DROP CONSTRAINT ck_dedup_review_queue_ck_dedup_pair_order",
    "ALTER TABLE ops.dedup_review_queue"
    " ADD CONSTRAINT ck_dedup_review_queue_ck_dedup_pair_order"
    " CHECK (feature_id_a < feature_id_b)",
)

_UNIQUE_RENAME: Final[str] = (
    "ALTER TABLE feature.features"
    " RENAME CONSTRAINT uq_features_identity_kind TO uq_features_id_kind"
)

#: 재키 **뒤**에 만든다. 앞에 두면 새 트리거가 아직 text인 컬럼에 DEPENDENCY_AUTO를
#: 걸고 그 컬럼이 사라질 때 함께 삭제된다 — 고치려던 침묵 소멸이 그대로 재현된다.
_TRIGGER_RECREATE: Final[tuple[str, ...]] = (
    "CREATE TRIGGER trg_features_identity_fence"
    " BEFORE UPDATE OF feature_id ON feature.features"
    " FOR EACH ROW EXECUTE FUNCTION feature.fence_features_identity_update()",
    "CREATE TRIGGER trg_feature_aliases_delete_fence"
    " BEFORE DELETE ON feature.feature_aliases"
    " FOR EACH ROW EXECUTE FUNCTION feature.fence_feature_aliases_write()",
    "CREATE TRIGGER trg_feature_aliases_update_fence"
    " BEFORE UPDATE ON feature.feature_aliases"
    " FOR EACH ROW EXECUTE FUNCTION feature.fence_feature_aliases_write()",
    "CREATE TRIGGER trg_feature_aliases_no_truncate"
    " BEFORE TRUNCATE ON feature.feature_aliases"
    " FOR EACH STATEMENT EXECUTE FUNCTION feature.fence_feature_aliases_write()",
)

_VIEW_RECREATE: Final[str] = """
CREATE VIEW feature.public_features AS
 SELECT core.feature_id,
    CAST(core.feature_id AS text) AS feature_uuid,
    core.kind,
    core.name,
    core.category,
    core.coord,
    core.coord_5179,
    core.coord_precision_digits,
    core.address,
    core.legal_dong_code,
    core.road_name_code,
    core.road_address_management_no,
    core.admin_dong_code,
    core.sido_code,
    core.sigungu_code,
    core.urls,
    core.marker_icon,
    core.marker_color,
    core.parent_feature_id,
    core.sibling_group_id,
    core.raw_refs,
    core.created_at,
    core.updated_at,
    core.row_revision,
    COALESCE(route.geom, area.geom) AS geom,
    COALESCE(
        CASE core.kind
            WHEN 'place'::text THEN
            CASE
                WHEN (place.feature_id IS NULL) THEN NULL::jsonb
                ELSE jsonb_build_object('feature_id', core.feature_id, 'place_kind', place.place_kind, 'phones', to_jsonb(place.phones), 'biz_number', place.biz_number, 'license_date', to_jsonb(place.license_date), 'business_hours', place.business_hours, 'facility_info', place.facility_info, 'reviews_link', place.reviews_link, 'payload', place.payload)
            END
            WHEN 'event'::text THEN
            CASE
                WHEN (event.feature_id IS NULL) THEN NULL::jsonb
                ELSE jsonb_build_object('feature_id', core.feature_id, 'event_kind', event.event_kind, 'starts_on', to_jsonb(event.starts_on), 'ends_on', to_jsonb(event.ends_on), 'timezone', event.timezone, 'opening_hours', event.opening_hours, 'venue_name', event.venue_name, 'tel', event.tel, 'content_id', event.content_id, 'content_type_id', event.content_type_id, 'area_code', event.area_code, 'sigungu_code', event.sigungu_code, 'payload', event.payload)
            END
            WHEN 'notice'::text THEN
            CASE
                WHEN (notice.feature_id IS NULL) THEN NULL::jsonb
                ELSE jsonb_build_object('feature_id', core.feature_id, 'notice_type', notice.notice_type, 'severity', notice.severity, 'valid_start_time', to_jsonb(to_char((notice.valid_start_time AT TIME ZONE 'Asia/Seoul'::text),
                CASE
                    WHEN (((EXTRACT(microsecond FROM notice.valid_start_time))::bigint % (1000000)::bigint) = 0) THEN 'YYYY-MM-DD"T"HH24:MI:SS"+09:00"'::text
                    ELSE 'YYYY-MM-DD"T"HH24:MI:SS.US"+09:00"'::text
                END)), 'valid_end_time', to_jsonb(to_char((notice.valid_end_time AT TIME ZONE 'Asia/Seoul'::text),
                CASE
                    WHEN (((EXTRACT(microsecond FROM notice.valid_end_time))::bigint % (1000000)::bigint) = 0) THEN 'YYYY-MM-DD"T"HH24:MI:SS"+09:00"'::text
                    ELSE 'YYYY-MM-DD"T"HH24:MI:SS.US"+09:00"'::text
                END)), 'source_agency', notice.source_agency, 'officer_name', notice.officer_name, 'payload', notice.payload)
            END
            WHEN 'route'::text THEN
            CASE
                WHEN (route.feature_id IS NULL) THEN NULL::jsonb
                ELSE jsonb_build_object('feature_id', core.feature_id, 'route_type', route.route_type, 'geometry_source', route.geometry_source, 'geometry_status', route.geometry_status, 'total_distance_meters', to_jsonb((route.total_distance_meters)::text), 'expected_duration_minutes', route.expected_duration_minutes, 'difficulty', route.difficulty, 'begin_name', route.begin_name, 'begin_address', route.begin_address, 'end_name', route.end_name, 'end_address', route.end_address, 'payload', route.payload)
            END
            WHEN 'area'::text THEN
            CASE
                WHEN (area.feature_id IS NULL) THEN NULL::jsonb
                ELSE jsonb_build_object('feature_id', core.feature_id, 'area_kind', area.area_kind, 'boundary_source', area.boundary_source, 'area_square_meters', to_jsonb((area.area_square_meters)::text), 'regulation_scope', area.regulation_scope, 'administrative_office', area.administrative_office, 'description', area.description, 'payload', area.payload)
            END
            ELSE NULL::jsonb
        END, '{}'::jsonb) AS detail
   FROM (((((feature.features core
     LEFT JOIN feature.feature_places place ON (place.feature_id = core.feature_id))
     LEFT JOIN feature.feature_events event ON (event.feature_id = core.feature_id))
     LEFT JOIN feature.feature_notices notice ON (notice.feature_id = core.feature_id))
     LEFT JOIN feature.feature_routes route ON (route.feature_id = core.feature_id))
     LEFT JOIN feature.feature_areas area ON (area.feature_id = core.feature_id))
  WHERE ((core.lifecycle_state = 'active'::text) AND (core.publication_state = 'published'::text) AND (core.quality_state = 'valid'::text))
"""

_RECEIPT_HEAD_WIDEN: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals', '305_m05_relitigation_fence',"
    " '306_m02_manual_feature_purge', '307_m02_truncate_fence',"
    " '308_t39_provider_identities', '309_t39_feature_id_rekey'))"
)


#: 루틴 사이드카. **순서에 의미가 없다** — 각 파일이 자기 `SET ROLE` 창을 열고 닫는다.
#:
#: 처음에는 소유자 롤별로 바깥에서 묶었다. 그 형태는 조용히 깨진다: 자기 창을 이미
#: 가진 사이드카(pg_dump가 그렇게 뱉는다)가 끝에서 `SET ROLE ktm_feature_schema_owner`로
#: 되돌리면, 뒤따르는 파일은 바깥 그룹이 지정한 롤이 아니라 스키마 소유자로 실행된다.
#: 2026-09-09 n150 실행이 `must be owner of function derive_subtype_public_ready`로
#: 그것을 잡았다. 파일 하나를 목록에서 옮기는 것만으로 다른 파일이 깨지는 배치는
#: 계약이 아니라 함정이다.
#:
#: `SET ROLE`이 필요한 이유는 `CREATE OR REPLACE`와 `DROP`이 **소유자만** 할 수 있고
#: 이 롤들이 NOINHERIT이기 때문이다. schema owner가 멤버십을 갖는다
#: (`302_m03_child_issuance.py:310-311`). `feature` 스키마는 소유자 롤 전부가 `ALL`을
#: 가지므로 창 안에서 CREATE도 성립한다(`alembic/head-schema.sql:24731-24737`).
#:
#: 예외는 `ops.record_curation_import_manual_feature_child` 하나다. `ops`에서
#: `ktm_curation_command_owner`는 USAGE만 갖고(`head-schema.sql:24749`) CREATE가 없어
#: 창을 열 수 없다. 그 파일은 스키마 소유자로 돌고 소유권만 이전한다 — 실측으로 통한다.
_ROUTINE_STATEMENTS: Final[tuple[str, ...]] = (
    *_sidecar("_309_append_theme_feature_candidate_transition.sql"),
    *_sidecar("_309_apply_provider_feature_field_patch.sql"),
    *_sidecar("_309_archive_curated_source_command.sql"),
    *_sidecar("_309_claim_curation_import_plan_command.sql"),
    *_sidecar("_309_apply_curation_import_items_command.sql"),
    *_sidecar("_309_create_curation_item_command.sql"),
    *_sidecar("_309_create_curation_rule_reconcile_receipt.sql"),
    *_sidecar("_309_create_manual_curation_item_with_feature_command.sql"),
    *_sidecar("_309_current_theme_candidate_snapshot.sql"),
    *_sidecar("_309_patch_curation_item_command.sql"),
    *_sidecar("_309_record_curation_import_manual_feature_child.sql"),
    *_sidecar("_309_write_feature_state_transition.sql"),
    *_sidecar("_309_approve_feature_request_with_initial_state.sql"),
    *_sidecar("_309_ensure_features_legacy_alias.sql"),
    *_sidecar("_309_fence_features_identity_update.sql"),
    *_sidecar("_309_fill_features_feature_uuid.sql"),
    *_sidecar("_309_purge_manual_feature.sql"),
    *_sidecar("_309_author_feature_field_overrides.sql"),
    *_sidecar("_309_author_lifecycle_override.sql"),
    *_sidecar("_309_create_feature_with_initial_state.sql"),
    *_sidecar("_309_derive_subtype_public_ready.sql"),
    *_sidecar("_309_has_active_feature_override.sql"),
    *_sidecar("_309_lock_current_provider_feature_source_evidence.sql"),
    *_sidecar("_309_materialize_theme_candidate_generation.sql"),
    *_sidecar("_309_merge_lock_curation_collections.sql"),
    *_sidecar("_309_reactivate_admin_feature_state.sql"),
    *_sidecar("_309_resolve_provider_feature_id.sql"),
    *_sidecar("_309_revoke_feature_field_overrides.sql"),
    *_sidecar("_309_revoke_lifecycle_override.sql"),
    *_sidecar("_309_transition_admin_feature_state.sql"),
    *_sidecar("_309_transition_feature_state.sql"),
    *_sidecar("_309_validate_feature_base_field_value.sql"),
    # ADR-098의 착지처. core 프로시저가 재작성된 **뒤**여야 한다 — 이 wrapper가
    # 그것을 CALL하고, plpgsql은 CREATE 시점에 의존을 검사하지 않지만 첫 호출에서
    # 시그니처가 맞아야 한다.
    *_sidecar("_309_create_provider_feature_with_initial_state.sql"),
    *_sidecar("_309_create_admin_manual_feature_with_initial_state.sql"),
    *_sidecar("_309_read_admin_manual_feature_provenance.sql"),
    *_sidecar("_309_reject_manual_feature_hard_purge.sql"),
    *_sidecar("_309_list_manual_provider_dedup_cases.sql"),
    *_sidecar("_309_list_manual_provider_dedup_detector_manuals.sql"),
    *_sidecar("_309_read_manual_provider_dedup_case.sql"),
    *_sidecar("_309_record_manual_provider_dedup_candidate.sql"),
    *_sidecar("_309_resolve_manual_provider_dedup_case.sql"),
    *_sidecar("_309_resolve_manual_provider_dedup_case_v2.sql"),
)


#: 순서가 곧 설계다. 각 단계의 근거는 이 모듈 docstring이 소유한다.
_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    # A. 옮길 수 없는 행이 있으면 여기서 선다.
    _PRECONDITION,
    # B. alias 조회 헬퍼 — `USING`이 서브쿼리를 못 받는다.
    _LEGACY_LOOKUP,
    # C. 뷰 — `ALTER COLUMN TYPE`의 절대 선행 조건(2BP01).
    _VIEW_DROP,
    # D. 트리거 — plpgsql은 의존성을 추적하지 않는다.
    *_TRIGGER_DROP,
    # E. FK 40 — 크로스 표 타입 불일치 때문에 전부 선행 DROP.
    *_FK_DROP,
    # F. `alias = feature_id` — text와 uuid 사이에 `=`가 없다.
    _ALIAS_IDENTITY_CHECK_DROP,
    # G. 증거 표 개명 — legacy 문자열을 값이 아니라 이름으로 보존한다.
    *_EVIDENCE_RENAME,
    # H. features·aliases 먼저 — 나머지 재타입이 alias를 원천으로 쓴다.
    *_RETYPE_IDENTITY,
    # I. 나머지 32.
    *_RETYPE_REST,
    # J. shadow 13 — `DROP COLUMN`이 조용히 지우는 것은 K가 되살린다.
    *_SHADOW_DROP,
    # K. J가 함께 지운 CHECK·인덱스.
    *_COLLATERAL_RECREATE,
    # L. 자식 composite FK의 참조 대상 이름.
    _UNIQUE_RENAME,
    # M. FK 34 재생성 (composite 11 중 6은 기존 FK가 덮으므로 영구 삭제).
    *_FK_RECREATE,
    # N. 루틴 34 — 소유자 롤별 `SET ROLE` 왕복.
    *_ROUTINE_STATEMENTS,
    # O. 트리거 재생성 — **재키 뒤여야 한다.** 앞에 두면 새 트리거가 아직
    #    text인 컬럼에 DEPENDENCY_AUTO를 걸고 곧바로 다시 사라진다.
    *_TRIGGER_RECREATE,
    # P. 뷰 재생성 — `::text` 조인 제거, 슬롯 2는 `CAST(... AS text)`.
    _VIEW_RECREATE,
    # Q. 헬퍼 회수.
    _LEGACY_LOOKUP_DROP,
    _RECEIPT_HEAD_WIDEN,
)


def upgrade() -> None:
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    raise RuntimeError(
        "T-VN-39 재키는 forward-only다 — legacy 문자열 키는 alias로만 남고 "
        "features의 text 컬럼은 되살릴 원본이 없다. 되돌리려면 PITR/스냅샷 복원이다 "
        "(선례: alembic/legacy_versions/0094_drop_weather_metric_series.py)."
    )
