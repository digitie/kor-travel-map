"""KHOA 해수욕장 re-key 정리 hardening — stable-identity join + stale primary link 강등.

Revision ID: 0030_khoa_rekey_hardening
Revises: 0029_weather_metric_feature_idx
Create Date: 2026-06-23

issue #509 회귀. 0027(``0027_khoa_recategorize_cleanup``)은 구 ``01020300`` 해수욕장
feature와 신 ``01050100`` feature를 **동일 ``source_record_key``** 로 매칭한다. 그러나
``source_record_key``는 ``raw_payload_hash``를 포함한다(``core/ids.make_source_record_key``;
``uq_source_records``가 ``(provider, dataset_key, source_entity_type, source_entity_id,
raw_payload_hash)``로 키잉 — alembic 0002). 재수집 payload가 조금이라도 달라지면 **같은
안정 식별자(stable identity)** 인데도 새 ``source_record_key``가 발급되고, old/new가 서로
다른 source_record에 매달려 0027의 ``source_record_key`` equality join이 깨진다 → 구
feature가 ``active``로 남아 신 feature와 중복(issue #509 Problem A).

또한 0027은 비활성화된 구 feature의 ``provider_sync.source_links.is_primary_source=true``를
그대로 둔다. ``get_primary_source_detail`` / ``_GET_PRIMARY_SOURCE_DETAIL_SQL``
(``infra/feature_repo.py``)이 ``deleted_at IS NULL`` / status 필터 / 결정적 ORDER BY 없이
``LIMIT 1`` 하면 비활성 구 feature를 반환할 수 있다(issue #509 Problem B — 본 migration은
stale primary link를 강등해 두 번째 방어선을 만든다).

본 migration:

1. **stable identity로 재정리** — old/new를 ``source_record_key`` 대신
   ``source_records``의 안정 식별자 ``(provider, dataset_key, source_entity_type,
   source_entity_id)``로 join하여(``provider='python-khoa-api'``, ``dataset_key=
   'khoa_beaches'``, ``source_entity_type='beach'`` 한정), ``raw_payload_hash`` drift를
   견디고 구 ``01020300`` primary feature를 ``status='inactive'``(+``deleted_at``)
   처리한다. 신 ``01050100`` primary sibling이 같은 안정 식별자에 ``active``(``deleted_at
   IS NULL``)로 존재할 때만 동작(재import 미완료 시 no-op — 가용성 공백 방지).
   ``data_origin='user_request'`` 사용자 생성분 제외. ``deleted_at IS NULL`` 가드로 멱등.

2. **stale primary link 강등** — 위에서 비활성화된 구 feature_id들의
   ``provider_sync.source_links.is_primary_source``를 ``false``로 내린다(KHOA 해수욕장
   source_record에 매달린 primary link만 대상). ``get_primary_source_detail``의 1차
   방어이자 정합성 정리.

0027은 이미 prod에 적용됐을 수 있으므로 **in-place 수정하지 않고** 후속 migration으로 둔다.

본 SQL은 ``KHOA_REKEY_CLEANUP_SQL`` / ``KHOA_REKEY_DEMOTE_PRIMARY_SQL`` 상수로 노출해
회귀 테스트(``tests/integration/test_khoa_rekey_hardening.py``)가 동일 SQL을 검증한다.

MIGRATION ORDERING(해소됨) — admin auth(``0028_admin_auth_keys``, #520) →
weather(``0029_weather_metric_feature_idx``, #518) 머지 후, 본 migration을 그 뒤로
rebase하여 ``down_revision='0029_weather_metric_feature_idx'``로 단일 head(``0030``)를 유지한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0030_khoa_rekey_hardening"
down_revision: str | Sequence[str] | None = "0029_weather_metric_feature_idx"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: 구 ``01020300`` KHOA 해수욕장 primary feature를 inactive로 전환 — old/new를
#: source_record의 **안정 식별자**(provider/dataset/entity_type/entity_id)로 join하여
#: ``raw_payload_hash`` drift를 견딘다. 신 ``01050100`` primary sibling이 같은 안정
#: 식별자에 ``active``로 존재할 때만 동작(멱등 — ``deleted_at IS NULL`` 가드).
KHOA_REKEY_CLEANUP_SQL: str = """
UPDATE feature.features AS f
SET status = 'inactive', deleted_at = now(), updated_at = now()
WHERE f.deleted_at IS NULL
  AND f.category = '01020300'
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'
  AND EXISTS (
    SELECT 1
    FROM provider_sync.source_links AS old_sl
    JOIN provider_sync.source_records AS old_sr
      ON old_sr.source_record_key = old_sl.source_record_key
    JOIN provider_sync.source_records AS new_sr
      ON new_sr.provider = old_sr.provider
     AND new_sr.dataset_key = old_sr.dataset_key
     AND new_sr.source_entity_type = old_sr.source_entity_type
     AND new_sr.source_entity_id = old_sr.source_entity_id
    JOIN provider_sync.source_links AS new_sl
      ON new_sl.source_record_key = new_sr.source_record_key
     AND new_sl.is_primary_source
    JOIN feature.features AS nf
      ON nf.feature_id = new_sl.feature_id
    WHERE old_sl.feature_id = f.feature_id
      AND old_sl.is_primary_source
      AND old_sr.provider = 'python-khoa-api'
      AND old_sr.dataset_key = 'khoa_beaches'
      AND old_sr.source_entity_type = 'beach'
      AND nf.category = '01050100'
      AND nf.status = 'active'
      AND nf.deleted_at IS NULL
      AND nf.feature_id <> f.feature_id
  )
"""

#: 비활성화된 구 KHOA 해수욕장 feature에 남은 stale primary link 강등 —
#: ``get_primary_source_detail``의 1차 방어. ``KHOA_REKEY_CLEANUP_SQL`` 이후 실행.
#: KHOA 해수욕장 source_record에 매달린, inactive+deleted_at 구 feature의 primary
#: link만 ``false``로 내린다(멱등 — 이미 false면 0 row).
KHOA_REKEY_DEMOTE_PRIMARY_SQL: str = """
UPDATE provider_sync.source_links AS sl
SET is_primary_source = false
FROM provider_sync.source_records AS sr,
     feature.features AS f
WHERE sl.source_record_key = sr.source_record_key
  AND sl.feature_id = f.feature_id
  AND sl.is_primary_source
  AND sr.provider = 'python-khoa-api'
  AND sr.dataset_key = 'khoa_beaches'
  AND sr.source_entity_type = 'beach'
  AND f.category = '01020300'
  AND f.status = 'inactive'
  AND f.deleted_at IS NOT NULL
"""


def upgrade() -> None:
    # 순서 중요: 먼저 구 feature를 inactive 처리한 뒤, 그 feature의 stale primary
    # link를 강등한다(demote가 inactive+deleted_at 상태에 의존).
    op.execute(KHOA_REKEY_CLEANUP_SQL)
    op.execute(KHOA_REKEY_DEMOTE_PRIMARY_SQL)


def downgrade() -> None:
    # 비활성화/강등은 되돌리지 않는다 — 구 feature_id는 re-key 산물이며 신
    # ``01050100`` feature가 정본이다. status/primary를 되살리면 중복이 복원된다.
    pass
