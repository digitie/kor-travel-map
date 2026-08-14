"""KHOA 해수욕장 category 01020300→01050100 re-key 후 구 feature 1회성 정리.

Revision ID: 0027_khoa_recategorize_cleanup
Revises: 0026_curated_copy_snapshots
Create Date: 2026-06-17

DA-D-07(2026-06-16, commit f189a45)에서 KHOA 해수욕장 ``BEACH_CATEGORY``를
``01020300``(COAST_ISLAND, 오분류)에서 전용 ``01050100``(TOURISM_NATURE_BEACH)로
정밀화했다. ``category``는 ``make_feature_id`` 해시 입력(``core/ids.py``)이라 이
변경은 모든 해수욕장 feature를 **재import 시 새 feature_id로 re-key**한다.

그런데 KHOA 적재 경로는 snapshot prune(``soft_delete_features_not_in_snapshot``)을
호출하지 않고(MOIS 전용), 설령 호출하더라도 prune은 ``source_entity_id`` 기준이라
re-key를 못 본다(자연키 ``name::sido::gugun``은 불변). 결과적으로 재import 후
구 ``01020300`` feature가 ``active``로 남아 신 ``01050100`` feature와 **중복**된다
(issue #452 / #445 — review-followup).

본 migration은 그 구 feature를 1회성으로 ``status='inactive'``(+``deleted_at``)
처리한다(ADR-017 — place는 무기한 보존, status만 inactive). 안전장치:

- KHOA 해수욕장 **primary source**로 적재된 feature 중 category가 아직 구
  ``01020300``인 것만 대상(범위를 source_records join으로 KHOA-해수욕장에 한정 —
  타 provider의 정당한 ``01020300`` 해안/섬 feature는 건드리지 않는다).
- **동일 source_record에 신 ``01050100`` primary feature가 이미 존재**할 때만
  비활성화한다(재import 미완료 시 가용성 공백 방지 — re-key 전이면 no-op).
- ``data_origin='user_request'`` 사용자 생성분 제외.
- ``deleted_at IS NULL`` 가드로 멱등(여러 번 실행해도 안전).

본 SQL은 ``KHOA_RECATEGORIZE_CLEANUP_SQL`` 상수로 노출해 회귀 테스트
(``tests/integration/test_khoa_recategorize_cleanup.py``)가 동일 SQL을 검증한다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0027_khoa_recategorize_cleanup"
down_revision: str | Sequence[str] | None = "0026_curated_copy_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: 구 ``01020300`` KHOA 해수욕장 primary feature를 inactive로 전환하는 1회성 SQL.
#: 신 ``01050100`` primary sibling이 같은 source_record에 존재할 때만 동작(멱등).
KHOA_RECATEGORIZE_CLEANUP_SQL: str = """
UPDATE feature.features AS f
SET status = 'inactive', deleted_at = now(), updated_at = now()
WHERE f.deleted_at IS NULL
  AND f.category = '01020300'
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'
  AND EXISTS (
    SELECT 1
    FROM provider_sync.source_links AS old_sl
    JOIN provider_sync.source_records AS sr
      ON sr.source_record_key = old_sl.source_record_key
    JOIN provider_sync.source_links AS new_sl
      ON new_sl.source_record_key = old_sl.source_record_key
     AND new_sl.is_primary_source
    JOIN feature.features AS nf
      ON nf.feature_id = new_sl.feature_id
    WHERE old_sl.feature_id = f.feature_id
      AND old_sl.is_primary_source
      AND sr.provider = 'python-khoa-api'
      AND sr.dataset_key = 'khoa_beaches'
      AND sr.source_entity_type = 'beach'
      AND nf.category = '01050100'
      AND nf.deleted_at IS NULL
      AND nf.feature_id <> f.feature_id
  )
"""


def upgrade() -> None:
    op.execute(KHOA_RECATEGORIZE_CLEANUP_SQL)


def downgrade() -> None:
    # 비활성화는 되돌리지 않는다 — 구 feature_id는 re-key 산물이며 신
    # ``01050100`` feature가 정본이다. status를 되살리면 중복이 복원된다.
    pass
