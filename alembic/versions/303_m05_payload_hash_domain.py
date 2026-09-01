"""T-VN-M05 — dedup case의 raw payload hash 도메인을 source_records와 정합.

Revision ID: 303_m05_payload_hash_domain
Revises: 302_m03_child_issuance

``ops.manual_provider_dedup_cases.source_record_raw_payload_hash``는
``feature.source_records.raw_payload_hash``의 **사본**인데, 원본 도메인은
``^[0-9a-f]{1,64}$``(``ck_source_records_payload_hash_canonical`` —
``make_payload_hash``의 기본 32-hex prefix 규약)이고 사본 제약만 정확히
64-hex를 강제했다. 그 결과 기본 규약으로 적재된 **모든** provider 레코드가
M05 dedup case 기록(``feature.record_manual_provider_dedup_candidate``)에서
``ck_manual_provider_dedup_cases_hashes`` 위반으로 깨진다 — 2026-09-01
isolated one-shot(e2e16)이 사상 처음 이 경로를 실주행해 적발했다.

사본 필드의 도메인을 원본과 동일하게 넓힌다. ``evidence_fingerprint``와
``scorer_input_sha256``는 이 계약 자체가 full SHA-256을 정의하므로 64-hex를
유지한다. 넓히는 방향이므로 기존 행은 전부 새 제약을 만족한다 —
``NOT VALID`` + ``VALIDATE``로 lock 창을 최소화한다(302 L7과 동일 규약).

DDL은 문장 하나씩 실행한다(asyncpg prepared statement 제약, `301`과 동일).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: Final[str] = "303_m05_payload_hash_domain"
down_revision: Final[str] = "302_m03_child_issuance"
branch_labels: Final[Sequence[str] | None] = None
depends_on: Final[Sequence[str] | None] = None

_HASHES_DROP: Final[str] = (
    "ALTER TABLE ops.manual_provider_dedup_cases "
    "DROP CONSTRAINT ck_manual_provider_dedup_cases_hashes"
)
_HASHES_ADD_WIDENED_NOT_VALID: Final[str] = (
    "ALTER TABLE ops.manual_provider_dedup_cases "
    "ADD CONSTRAINT ck_manual_provider_dedup_cases_hashes "
    "CHECK (evidence_fingerprint ~ '^[0-9a-f]{64}$' "
    "AND scorer_input_sha256 ~ '^[0-9a-f]{64}$' "
    "AND source_record_raw_payload_hash ~ '^[0-9a-f]{1,64}$') NOT VALID"
)
_HASHES_ADD_ORIGINAL_NOT_VALID: Final[str] = (
    "ALTER TABLE ops.manual_provider_dedup_cases "
    "ADD CONSTRAINT ck_manual_provider_dedup_cases_hashes "
    "CHECK (evidence_fingerprint ~ '^[0-9a-f]{64}$' "
    "AND scorer_input_sha256 ~ '^[0-9a-f]{64}$' "
    "AND source_record_raw_payload_hash ~ '^[0-9a-f]{64}$') NOT VALID"
)
_HASHES_VALIDATE: Final[str] = (
    "ALTER TABLE ops.manual_provider_dedup_cases "
    "VALIDATE CONSTRAINT ck_manual_provider_dedup_cases_hashes"
)


def upgrade() -> None:
    for statement in (
        _HASHES_DROP,
        _HASHES_ADD_WIDENED_NOT_VALID,
        _HASHES_VALIDATE,
    ):
        op.execute(statement)


def downgrade() -> None:
    # 좁히는 방향이라 32-hex 사본이 이미 기록됐다면 VALIDATE에서 fail-close
    # 한다 — 조용한 데이터 손실 대신 운영자가 결정한다(302 downgrade 규약).
    for statement in (
        _HASHES_DROP,
        _HASHES_ADD_ORIGINAL_NOT_VALID,
        _HASHES_VALIDATE,
    ):
        op.execute(statement)
