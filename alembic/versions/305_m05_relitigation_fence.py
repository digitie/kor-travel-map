"""T-VN-M05-RELITIGATION — admin이 판정한 쌍이 다시 올라오지 않게 한다.

Revision ID: 305_m05_relitigation_fence
Revises: 304_m05_detector_manuals

`feature.record_manual_provider_dedup_candidate`의 멱등성은 `evidence_fingerprint`가
같고 **그 case가 아직 미해결일 때만** 성립한다(baseline `schema.sql` 8180~8186행:
`LEFT JOIN ... resolutions` + `WHERE resolution.case_id IS NULL`). 그래서 admin이
`kept`로 판정한 쌍을 탐지기가 다시 보면 지문이 같아도 **새 case가 만들어진다.**
#1189의 탐지 job에 스케줄을 못 단 이유가 이것이다 — 주기 실행이 곧 admin 큐의
쳇바퀴가 된다.

## 차단 키가 `evidence_fingerprint`이면 안 되는 이유

그 지문의 입력에는 두 Feature의 `row_revision`과 `source_head_observed_at`이 들어
있다. 그래서 **score와 무관한 필드 patch 하나**(예: `urls` 수정)로 `row_revision`이
올라가면 지문이 달라지고 차단이 무력해진다. 반대로 지문이 아니라 snapshot 전체를
비교하면 같은 문제가 그대로 남는다.

## 그래서 `decision_fingerprint`를 따로 둔다

판정을 실제로 좌우하는 것만 넣는다:

- 두 snapshot에서 `row_revision`을 뺀 것 — `kind`·`name`·`category`·`lon`·`lat`와 식별자
- provider의 **현재 source 내용** — `source_record_key` + `source_record_raw_payload_hash`
- `scorer_id`

넣지 **않는** 것과 그 이유:

- `source_head_observed_at` — 내용이 그대로인데 head 관측 시각만 갱신되는 경로가
  실재한다(`_UPSERT_SOURCE_ENTITY_HEAD_SQL`이 더 새 `observed_at`에 갱신한다).
  넣으면 그 갱신마다 차단이 풀린다.
- 점수 **값** — 부동소수 잡음이 차단을 흔들면 안 된다. scorer가 바뀌면 `scorer_id`가
  바뀌어 다시 올라온다.

## 두 방향 모두 게이트가 필요하다

이 항목은 어느 방향으로도 틀릴 수 있다. 너무 세게 막으면 증거가 **실제로 바뀌었는데도**
새 후보가 안 올라오는 영구 침묵이 되고, 너무 약하면 supersede 폭풍이 난다. 둘 다
조용히 실패한다. 그래서 R1(차단)과 R2(해제)를 각각 결박한다.

`superseded` resolution은 차단 근거가 아니다 — 그것은 탐지기가 만든 것이라 admin
판정이 아니고, 그것으로 차단하면 탐지기가 자기 자신을 영구히 침묵시킨다.

## 기존 행 backfill

`decision_fingerprint`는 저장된 snapshot과 source 컬럼에서 **정확히 재계산할 수 있다**
— 그래서 backfill이 근사가 아니다. 재계산이 불가능한 행이 있으면 `SET NOT NULL`이
실패하고 그게 맞다.

프로시저 본문은 baseline에서 기계 파생한 sidecar로 둔다(302·303과 같은 규약).
DDL은 문장 하나씩 실행한다(asyncpg prepared statement 제약).
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from alembic import op

# ruff: noqa: E501

revision: Final[str] = "305_m05_relitigation_fence"
down_revision: Final[str] = "304_m05_detector_manuals"
branch_labels: None = None
depends_on: None = None

_HERE: Final = Path(__file__).resolve().parent


def _sidecar(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


_COLUMN_ADD: Final[str] = (
    "ALTER TABLE ops.manual_provider_dedup_cases ADD COLUMN decision_fingerprint text"
)

#: 저장된 snapshot·source 컬럼에서 프로시저와 **같은 식**으로 재계산한다.
#: `jsonb::text`는 키 순서를 정규화하므로 결정적이다.
_COLUMN_BACKFILL: Final[str] = """
UPDATE ops.manual_provider_dedup_cases
SET decision_fingerprint = encode(
    x_extension.digest(
        convert_to(
            jsonb_build_object(
                'manual', manual_feature_snapshot - 'row_revision',
                'provider', provider_feature_snapshot - 'row_revision',
                'source_record_key', source_record_key,
                'source_record_raw_payload_hash', source_record_raw_payload_hash,
                'scorer_id', scorer_id
            )::text,
            'UTF8'
        ),
        'sha256'
    ),
    'hex'
)
WHERE decision_fingerprint IS NULL
"""

_COLUMN_NOT_NULL: Final[str] = (
    "ALTER TABLE ops.manual_provider_dedup_cases"
    " ALTER COLUMN decision_fingerprint SET NOT NULL"
)

_COLUMN_CHECK: Final[str] = (
    "ALTER TABLE ops.manual_provider_dedup_cases"
    " ADD CONSTRAINT ck_manual_provider_dedup_cases_decision_fingerprint"
    " CHECK (decision_fingerprint ~ '^[0-9a-f]{64}$')"
)

#: 차단 조회가 (manual, provider, decision_fingerprint)로 들어간다. 이 인덱스가
#: 없으면 case가 쌓일수록 후보 하나마다 전체 스캔이 된다.
_INDEX_ADD: Final[str] = (
    "CREATE INDEX idx_manual_provider_dedup_cases_decision_fence"
    " ON ops.manual_provider_dedup_cases"
    " (manual_feature_uuid, provider_feature_uuid, decision_fingerprint)"
)

_INDEX_DROP: Final[str] = (
    "DROP INDEX ops.idx_manual_provider_dedup_cases_decision_fence"
)

_COLUMN_DROP: Final[str] = (
    "ALTER TABLE ops.manual_provider_dedup_cases DROP COLUMN decision_fingerprint"
)

_RECEIPT_HEAD_WIDEN: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals', '305_m05_relitigation_fence'))"
)

_RECEIPT_HEAD_NARROW: Final[str] = (
    # 되돌린 뒤 305 head receipt가 남아 있으면 실패한다 — 그게 맞다(301과 동일 원칙).
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals'))"
)


def upgrade() -> None:
    for statement in (
        _COLUMN_ADD,
        _COLUMN_BACKFILL,
        _COLUMN_NOT_NULL,
        _COLUMN_CHECK,
        _INDEX_ADD,
        _sidecar("_305_candidate_upgraded.sql"),
        _RECEIPT_HEAD_WIDEN,
    ):
        op.execute(statement)


def downgrade() -> None:
    for statement in (
        _RECEIPT_HEAD_NARROW,
        _sidecar("_305_candidate_original.sql"),
        _INDEX_DROP,
        _COLUMN_DROP,
    ):
        op.execute(statement)
