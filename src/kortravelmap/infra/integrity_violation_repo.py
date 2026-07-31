"""``ops.data_integrity_violations`` repository (ADR-045 T-205c).

정합성 위반/주소 매칭 이슈/미디어 실패 같은 운영 검토 항목을 "이슈 1건 = 1행"으로
저장한다. 배치 집계 테이블인 ``feature_consistency_reports``와 달리, 이 테이블은
admin UI에서 acknowledge/resolve/ignore할 수 있는 큐다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "DataIntegrityViolation",
    "DataIntegrityViolationStateConflict",
    "IntegrityObservationRun",
    "IntegrityObservationReceipt",
    "close_stale_integrity_findings",
    "create_data_integrity_violation",
    "ensure_integrity_observation_run",
    "finalize_integrity_observation_run",
    "get_data_integrity_violation",
    "list_data_integrity_violations",
    "purge_resolved_integrity_findings",
    "set_data_integrity_violation_status",
    "sync_integrity_findings",
]

_SEVERITIES: Final[frozenset[str]] = frozenset(
    {"info", "warning", "error", "critical"}
)
_STATUSES: Final[frozenset[str]] = frozenset(
    {"open", "acknowledged", "resolved", "ignored"}
)
_RESOLVED_STATUSES: Final[frozenset[str]] = frozenset({"resolved", "ignored"})
_MAX_LIST_LIMIT: Final[int] = 500

_RETURN_COLUMNS: Final[str] = (
    "issue_id, provider, dataset_key, source_record_key, feature_id, "
    "violation_type, severity, message, payload, status, detected_at, "
    "last_seen_at, resolved_at"
)
_RETURN_COLUMNS_V: Final[str] = (
    "v.issue_id, v.provider, v.dataset_key, v.source_record_key, v.feature_id, "
    "v.violation_type, v.severity, v.message, v.payload, v.status, v.detected_at, "
    "v.last_seen_at, v.resolved_at"
)


@dataclass(frozen=True)
class DataIntegrityViolation:
    """``ops.data_integrity_violations`` row."""

    issue_id: str
    provider: str | None
    dataset_key: str | None
    source_record_key: str | None
    feature_id: str | None
    violation_type: str
    severity: str
    message: str
    payload: dict[str, Any]
    status: str
    detected_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None


class DataIntegrityViolationStateConflict(ValueError):
    """data integrity issue가 요청한 상태 전이를 허용하지 않을 때 발생."""

    def __init__(
        self,
        *,
        issue_id: str,
        current_status: str,
        target_status: str,
    ) -> None:
        self.issue_id = issue_id
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            "data integrity violation "
            f"{issue_id!r}는 {target_status!r} 전이를 허용하지 않음: "
            f"status={current_status!r}"
        )


@dataclass(frozen=True)
class IntegrityObservationRun:
    """provider/dataset scope에서 external run에 배정한 불변 generation."""

    observation_run_id: int
    provider: str
    dataset_key: str
    generation: int
    external_run_id: str
    status: str


@dataclass(frozen=True)
class IntegrityObservationReceipt:
    """authoritative close를 허용하는 source/finding 전량 관측 증명."""

    authoritative_snapshot_complete: bool
    source_observations: int
    findings_observed: int
    findings_unique: int
    findings_upserted: int
    finding_persistence_complete: bool

    def __post_init__(self) -> None:
        counts = (
            self.source_observations,
            self.findings_observed,
            self.findings_unique,
            self.findings_upserted,
        )
        if any(count < 0 for count in counts):
            raise ValueError("observation receipt count는 음수일 수 없다.")
        if self.findings_unique > self.findings_observed:
            raise ValueError("unique finding 수는 observed finding 수를 넘을 수 없다.")
        if self.findings_upserted > self.findings_unique:
            raise ValueError("upserted finding 수는 unique finding 수를 넘을 수 없다.")

    @property
    def permits_stale_close(self) -> bool:
        return (
            self.authoritative_snapshot_complete
            and self.source_observations > 0
            and self.finding_persistence_complete
            and self.findings_upserted == self.findings_unique
        )


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        value = json.loads(value)
    return dict(value) if value else {}


def _row_to_violation(row: Any) -> DataIntegrityViolation:
    return DataIntegrityViolation(
        issue_id=str(row.issue_id),
        provider=row.provider,
        dataset_key=row.dataset_key,
        source_record_key=row.source_record_key,
        feature_id=row.feature_id,
        violation_type=str(row.violation_type),
        severity=str(row.severity),
        message=str(row.message),
        payload=_json_dict(row.payload),
        status=str(row.status),
        detected_at=row.detected_at,
        last_seen_at=row.last_seen_at,
        resolved_at=row.resolved_at,
    )


def _validate_violation(
    *,
    violation_type: str,
    severity: str,
    message: str,
) -> None:
    if not violation_type:
        raise ValueError("violation_type must be non-empty")
    if severity not in _SEVERITIES:
        raise ValueError(f"severity must be one of {sorted(_SEVERITIES)}")
    if not message:
        raise ValueError("message must be non-empty")


_INSERT_SQL: Final[str] = f"""
INSERT INTO ops.data_integrity_violations (
    provider, dataset_key, source_record_key, feature_id, violation_type,
    severity, message, payload
) VALUES (
    :provider, :dataset_key, :source_record_key, :feature_id, :violation_type,
    :severity, :message, CAST(:payload AS jsonb)
)
RETURNING {_RETURN_COLUMNS}
"""

_GET_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.data_integrity_violations
WHERE issue_id = :issue_id
"""

_SET_STATUS_SQL: Final[str] = f"""
WITH locked AS (
    SELECT issue_id, status
    FROM ops.data_integrity_violations
    WHERE issue_id = :issue_id
    FOR UPDATE
),
updated AS (
    UPDATE ops.data_integrity_violations AS v
    SET status = :status,
        resolved_at = CASE
            WHEN locked.status = :status THEN v.resolved_at
            WHEN :status = ANY(CAST(:resolved_statuses AS text[])) THEN now()
            ELSE NULL
        END,
        payload = CASE
            WHEN CAST(:resolution_payload AS jsonb) = '{{}}'::jsonb THEN v.payload
            ELSE v.payload || jsonb_build_object(
                'resolution',
                CAST(:resolution_payload AS jsonb)
            )
        END
    FROM locked
    WHERE v.issue_id = locked.issue_id
      AND (
        locked.status = :status
        OR locked.status <> ALL(CAST(:resolved_statuses AS text[]))
      )
    RETURNING {_RETURN_COLUMNS_V}
)
SELECT {_RETURN_COLUMNS}
FROM updated
"""

_LIST_SQL: Final[str] = f"""
SELECT {_RETURN_COLUMNS}
FROM ops.data_integrity_violations
WHERE (CAST(:status AS text) IS NULL OR status = CAST(:status AS text))
  AND (CAST(:severity AS text) IS NULL OR severity = CAST(:severity AS text))
  AND (CAST(:violation_type AS text) IS NULL
       OR violation_type = CAST(:violation_type AS text))
  AND (CAST(:feature_id AS text) IS NULL OR feature_id = CAST(:feature_id AS text))
  AND (CAST(:provider AS text) IS NULL OR provider = CAST(:provider AS text))
  AND (CAST(:dataset_key AS text) IS NULL OR dataset_key = CAST(:dataset_key AS text))
ORDER BY last_seen_at DESC, issue_id DESC
LIMIT :limit
"""


async def create_data_integrity_violation(
    session: AsyncSession,
    *,
    violation_type: str,
    severity: str,
    message: str,
    provider: str | None = None,
    dataset_key: str | None = None,
    source_record_key: str | None = None,
    feature_id: str | None = None,
    payload: Mapping[str, Any] | None = None,
) -> DataIntegrityViolation:
    """정합성/운영 이슈 1건을 생성한다. commit은 호출자 책임."""
    _validate_violation(
        violation_type=violation_type,
        severity=severity,
        message=message,
    )
    row = (
        await session.execute(
            text(_INSERT_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "source_record_key": source_record_key,
                "feature_id": feature_id,
                "violation_type": violation_type,
                "severity": severity,
                "message": message,
                "payload": json.dumps(
                    dict(payload) if payload else {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        )
    ).one()
    return _row_to_violation(row)


async def get_data_integrity_violation(
    session: AsyncSession,
    issue_id: str,
) -> DataIntegrityViolation | None:
    """violation key로 이슈 1건 조회."""
    row = (
        await session.execute(
            text(_GET_SQL),
            {"issue_id": issue_id},
        )
    ).one_or_none()
    return _row_to_violation(row) if row is not None else None


async def set_data_integrity_violation_status(
    session: AsyncSession,
    issue_id: str,
    *,
    status: str,
    resolution_payload: Mapping[str, Any] | None = None,
) -> DataIntegrityViolation | None:
    """이슈 상태를 변경한다. ``resolved``/``ignored``는 ``resolved_at``을 찍는다."""
    if status not in _STATUSES:
        raise ValueError(f"status must be one of {sorted(_STATUSES)}")
    row = (
        await session.execute(
            text(_SET_STATUS_SQL),
            {
                "issue_id": issue_id,
                "status": status,
                "resolved_statuses": list(_RESOLVED_STATUSES),
                "resolution_payload": json.dumps(
                    dict(resolution_payload) if resolution_payload else {},
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        )
    ).one_or_none()
    if row is not None:
        return _row_to_violation(row)
    existing = await get_data_integrity_violation(session, issue_id)
    if existing is None:
        return None
    raise DataIntegrityViolationStateConflict(
        issue_id=existing.issue_id,
        current_status=existing.status,
        target_status=status,
    )


async def list_data_integrity_violations(
    session: AsyncSession,
    *,
    status: str | None = None,
    severity: str | None = None,
    violation_type: str | None = None,
    feature_id: str | None = None,
    provider: str | None = None,
    dataset_key: str | None = None,
    limit: int = 200,
) -> tuple[DataIntegrityViolation, ...]:
    """운영 이슈 목록 조회."""
    rows = (
        await session.execute(
            text(_LIST_SQL),
            {
                "status": status,
                "severity": severity,
                "violation_type": violation_type,
                "feature_id": feature_id,
                "provider": provider,
                "dataset_key": dataset_key,
                "limit": max(1, min(limit, _MAX_LIST_LIMIT)),
            },
        )
    ).all()
    return tuple(_row_to_violation(row) for row in rows)


_UPSERT_FINDINGS_BATCH_SQL: Final[str] = """
INSERT INTO ops.data_integrity_violations (
    provider, dataset_key, source_record_key, feature_id, violation_type,
    severity, message, payload, last_seen_at
)
SELECT finding.*, statement_timestamp()
FROM unnest(
        CAST(:providers AS text[]),
        CAST(:datasets AS text[]),
        CAST(:source_record_keys AS text[]),
        CAST(:feature_ids AS text[]),
        CAST(:violation_types AS text[]),
        CAST(:severities AS text[]),
        CAST(:messages AS text[]),
        CAST(:payloads AS jsonb[])
    ) AS finding(
        provider, dataset_key, source_record_key, feature_id, violation_type,
        severity, message, payload
    )
ON CONFLICT ((payload ->> 'dedupe_key'))
WHERE status IN ('open', 'acknowledged') AND payload ? 'dedupe_key'
DO UPDATE SET
    source_record_key = CASE
        WHEN EXCLUDED.last_seen_at >= ops.data_integrity_violations.last_seen_at
        THEN EXCLUDED.source_record_key
        ELSE ops.data_integrity_violations.source_record_key
    END,
    feature_id = CASE
        WHEN EXCLUDED.last_seen_at >= ops.data_integrity_violations.last_seen_at
        THEN EXCLUDED.feature_id
        ELSE ops.data_integrity_violations.feature_id
    END,
    message = CASE
        WHEN EXCLUDED.last_seen_at >= ops.data_integrity_violations.last_seen_at
        THEN EXCLUDED.message
        ELSE ops.data_integrity_violations.message
    END,
    severity = CASE
        WHEN EXCLUDED.last_seen_at >= ops.data_integrity_violations.last_seen_at
        THEN EXCLUDED.severity
        ELSE ops.data_integrity_violations.severity
    END,
    last_seen_at = GREATEST(
        ops.data_integrity_violations.last_seen_at,
        EXCLUDED.last_seen_at
    ),
    payload = (
        CASE
            WHEN EXCLUDED.last_seen_at >= ops.data_integrity_violations.last_seen_at
            THEN ops.data_integrity_violations.payload
                || jsonb_strip_nulls(EXCLUDED.payload)
            ELSE ops.data_integrity_violations.payload
        END
    )
        || jsonb_build_object(
            'occurrence_count',
            COALESCE(
                (ops.data_integrity_violations.payload ->> 'occurrence_count')::bigint,
                1
            ) + 1
        )
RETURNING issue_id
"""

_INSERT_OBSERVATION_SCOPE_SQL: Final[str] = """
INSERT INTO ops.integrity_observation_scopes (provider, dataset_key)
VALUES (:provider, :dataset_key)
ON CONFLICT (provider, dataset_key) DO NOTHING
"""

_LOCK_OBSERVATION_SCOPE_SQL: Final[str] = """
SELECT latest_generation, latest_authoritative_generation
FROM ops.integrity_observation_scopes
WHERE provider = :provider
  AND dataset_key = :dataset_key
FOR UPDATE
"""

_GET_OBSERVATION_RUN_SQL: Final[str] = """
SELECT observation_run_id, provider, dataset_key, generation, external_run_id, status
FROM ops.integrity_observation_runs
WHERE provider = :provider
  AND dataset_key = :dataset_key
  AND external_run_id = :external_run_id
"""

_GET_OBSERVATION_RUN_FOR_UPDATE_SQL: Final[str] = (
    _GET_OBSERVATION_RUN_SQL + "\nFOR UPDATE"
)

_ALLOCATE_OBSERVATION_GENERATION_SQL: Final[str] = """
UPDATE ops.integrity_observation_scopes
SET latest_generation = latest_generation + 1,
    updated_at = now()
WHERE provider = :provider
  AND dataset_key = :dataset_key
RETURNING latest_generation
"""

_INSERT_OBSERVATION_RUN_SQL: Final[str] = """
INSERT INTO ops.integrity_observation_runs (
    provider, dataset_key, generation, external_run_id
) VALUES (
    :provider, :dataset_key, :generation, :external_run_id
)
RETURNING observation_run_id, provider, dataset_key, generation, external_run_id, status
"""

_INSERT_FINDING_OBSERVATIONS_SQL: Final[str] = """
INSERT INTO ops.integrity_finding_observations (
    observation_run_id, dedupe_key
)
SELECT :observation_run_id, observed.dedupe_key
FROM unnest(CAST(:dedupe_keys AS text[])) AS observed(dedupe_key)
ON CONFLICT (observation_run_id, dedupe_key) DO NOTHING
"""


def _observation_run(row: Any) -> IntegrityObservationRun:
    return IntegrityObservationRun(
        observation_run_id=int(row.observation_run_id),
        provider=str(row.provider),
        dataset_key=str(row.dataset_key),
        generation=int(row.generation),
        external_run_id=str(row.external_run_id),
        status=str(row.status),
    )


async def ensure_integrity_observation_run(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    external_run_id: str,
) -> IntegrityObservationRun:
    """scope row lock 아래에서 external run에 단조 generation을 한 번만 배정한다."""

    if not provider or not dataset_key:
        raise ValueError("provider/dataset_key는 observation scope에 필수다.")
    if not external_run_id.strip():
        raise ValueError("external_run_id는 비어 있을 수 없다.")
    await session.execute(
        text(_INSERT_OBSERVATION_SCOPE_SQL),
        {"provider": provider, "dataset_key": dataset_key},
    )
    scope = (
        await session.execute(
            text(_LOCK_OBSERVATION_SCOPE_SQL),
            {"provider": provider, "dataset_key": dataset_key},
        )
    ).one()
    del scope
    params = {
        "provider": provider,
        "dataset_key": dataset_key,
        "external_run_id": external_run_id,
    }
    existing = (
        await session.execute(text(_GET_OBSERVATION_RUN_SQL), params)
    ).one_or_none()
    if existing is not None:
        return _observation_run(existing)

    generation = int(
        (
            await session.execute(
                text(_ALLOCATE_OBSERVATION_GENERATION_SQL),
                {"provider": provider, "dataset_key": dataset_key},
            )
        ).scalar_one()
    )
    inserted = (
        await session.execute(
            text(_INSERT_OBSERVATION_RUN_SQL),
            {**params, "generation": generation},
        )
    ).one()
    return _observation_run(inserted)



async def sync_integrity_findings(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    findings: Sequence[Mapping[str, Any]],
    external_run_id: str | None = None,
) -> int:
    """finding 집합을 **단일 statement로** 기록한다 (T-VN-H30A). commit은 호출자 책임.

    반환: upsert한 건수.

    왜 batch인가 — ``ops.data_integrity_violations``에는 statement 단위 트리거
    (``trg_data_integrity_violations_ops_live_revision``)가 걸려 있어 statement마다
    ``ops_live`` revision 단일 행을 갱신한다. finding 하나당 INSERT를 돌리면 그 hot row에
    배타 락을 N번 잡고 트랜잭션 끝까지 쥐게 되어, ``/admin/issues`` 쓰기를 막고 동시 run을
    직렬화하며 admin PATCH와 데드락까지 만든다. 전체를 한 statement로 접으면 트리거는
    1회만 발화한다.

    이 함수는 finding을 닫지 않는다. ``external_run_id``가 있으면 같은 transaction에서
    immutable generation을 확보하고 run별 dedupe-key observation set을 기록한다.
    provider 전체 snapshot이 끝난 뒤 authoritative typed receipt를 가진 호출자가
    ``finalize_integrity_observation_run``으로 scope fence 아래에서 한 번만 sweep한다.
    따라서 배치 경계나 빈 제어-flow sentinel은 absence 증거가 되지 않는다(T-VN-H32R).
    """
    ordered_findings = sorted(
        findings,
        key=lambda finding: str(finding["payload"]["dedupe_key"]),
    )
    for finding in ordered_findings:
        dedupe_key = str(finding["payload"]["dedupe_key"])
        if (
            len(dedupe_key) != 68
            or not dedupe_key.startswith("av2_")
            or any(char not in "0123456789abcdef" for char in dedupe_key[4:])
        ):
            raise ValueError("finding dedupe_key는 av2_<sha256> 형식이어야 한다.")
        if finding.get("provider") != provider:
            raise ValueError("finding provider가 sync 범위와 다르다.")
        if finding.get("dataset_key") != dataset_key:
            raise ValueError("finding dataset_key가 sync 범위와 다르다.")
        # batch 경로에도 같은 검증을 건다. 없으면 잘못된 severity가 DB CHECK까지 가서
        # unnest statement 전체를 실패시키고, 상위의 광범위 except가 삼켜
        # **그 run의 finding 전부**를 잃는다.
        _validate_violation(
            violation_type=str(finding["violation_type"]),
            severity=str(finding["severity"]),
            message=str(finding["message"]),
        )

    observation_run: IntegrityObservationRun | None = None
    if external_run_id is not None:
        observation_run = await ensure_integrity_observation_run(
            session,
            provider=provider,
            dataset_key=dataset_key,
            external_run_id=external_run_id,
        )

    upserted = 0
    if ordered_findings:
        result = await session.execute(
            text(_UPSERT_FINDINGS_BATCH_SQL),
            {
                "providers": [f.get("provider") for f in ordered_findings],
                "datasets": [f.get("dataset_key") for f in ordered_findings],
                "source_record_keys": [
                    f.get("source_record_key") for f in ordered_findings
                ],
                "feature_ids": [f.get("feature_id") for f in ordered_findings],
                "violation_types": [f["violation_type"] for f in ordered_findings],
                "severities": [f["severity"] for f in ordered_findings],
                "messages": [f["message"] for f in ordered_findings],
                "payloads": [
                    json.dumps(f["payload"], ensure_ascii=False)
                    for f in ordered_findings
                ],
            },
        )
        upserted = len(result.scalars().all())
        if observation_run is not None:
            await session.execute(
                text(_INSERT_FINDING_OBSERVATIONS_SQL),
                {
                    "observation_run_id": observation_run.observation_run_id,
                    "dedupe_keys": [
                        str(finding["payload"]["dedupe_key"])
                        for finding in ordered_findings
                    ],
                },
            )

    return upserted


# T-VN-H32R — immutable observation generation 기반 close.
#
# **왜 한 statement인가.** 이 테이블에는 statement 단위 트리거
# ``trg_data_integrity_violations_ops_live_revision``이 걸려 있어 statement마다 ``ops_live``
# revision 단일 행을 갱신한다. finding마다 UPDATE를 돌리면 그 hot row에 배타 락을 N번 잡고
# 트랜잭션 끝까지 쥐게 되어 ``/admin/issues`` 쓰기를 막고 데드락까지 만든다
# (``sync_integrity_findings``가 batch upsert인 이유와 같다).
#
# **술어 하나하나가 기각된 설계를 피한다.**
#
# - ``status = 'open'`` — ``acknowledged``는 사람이 인지한 표시라 **불가침**이다.
#   기계가 닫지 않는다.
# - 현재 run의 immutable observation set에 있는 dedupe key는 닫지 않는다.
# - 더 새 generation의 partial run이 이미 관측한 key도 닫지 않는다. 그 run이 실패해
#   authoritative가 되지 못해도 새 증거를 과거 snapshot이 파괴할 수 없다.
# - scope row ``FOR UPDATE``와 ``latest_authoritative_generation`` fence로 오래된 run이
#   새 authoritative run 뒤에서 sweep하는 것을 막는다.
# - ``provider``/``dataset_key`` — provider 경계를 넘지 않는다.
# - ``payload ->> 'dedupe_key' LIKE 'av2\_%'`` — ``sync_integrity_findings``가 만든 계열만
#   닫는다. 같은 provider/dataset에 다른 subsystem이 남긴 finding(예: curation mislink)을
#   쓸어버리지 않기 위한 경계다.
_CLOSE_STALE_FINDINGS_SQL: Final[str] = r"""
UPDATE ops.data_integrity_violations AS v
   SET status = 'resolved',
       resolved_at = now(),
       payload = v.payload || jsonb_build_object('resolution', CAST(:resolution AS jsonb))
 WHERE v.provider = :provider
   AND v.dataset_key = :dataset_key
   AND v.status = 'open'
   AND v.payload ? 'dedupe_key'
   AND v.payload ->> 'dedupe_key' LIKE 'av2\_%'
   AND NOT EXISTS (
       SELECT 1
       FROM ops.integrity_finding_observations AS current_observation
       WHERE current_observation.observation_run_id = :observation_run_id
         AND current_observation.dedupe_key = v.payload ->> 'dedupe_key'
   )
   AND NOT EXISTS (
       SELECT 1
       FROM ops.integrity_observation_runs AS newer_run
       JOIN ops.integrity_finding_observations AS newer_observation
         ON newer_observation.observation_run_id = newer_run.observation_run_id
       WHERE newer_run.provider = :provider
         AND newer_run.dataset_key = :dataset_key
         AND newer_run.generation > :generation
         AND newer_observation.dedupe_key = v.payload ->> 'dedupe_key'
   )
RETURNING v.issue_id
"""

_FINALIZE_OBSERVATION_RUN_SQL: Final[str] = """
UPDATE ops.integrity_observation_runs
SET status = :status,
    source_observations = :source_observations,
    findings_observed = :findings_observed,
    findings_unique = :findings_unique,
    findings_upserted = :findings_upserted,
    completed_at = now()
WHERE observation_run_id = :observation_run_id
  AND status = 'collecting'
"""

_ADVANCE_AUTHORITATIVE_GENERATION_SQL: Final[str] = """
UPDATE ops.integrity_observation_scopes
SET latest_authoritative_generation = :generation,
    updated_at = now()
WHERE provider = :provider
  AND dataset_key = :dataset_key
"""

# resolved 보존 기간이 지난 행을 **삭제**한다 (T-VN-H32R).
#
# ``acknowledged``는 어떤 경우에도 지우지 않는다 — close 대상도, 삭제 대상도 아니다.
# ``feature_repo.purge_expired_notices``와 같은 retention 문자열 패턴을 쓴다.
_PURGE_RESOLVED_FINDINGS_SQL: Final[str] = """
DELETE FROM ops.data_integrity_violations AS v
 WHERE v.status = 'resolved'
   AND v.resolved_at IS NOT NULL
   -- asyncpg가 파라미터 타입을 interval로 추론하면 str을 거부한다.
   -- feature_repo.purge_expired_notices와 같은 이중 캐스팅을 쓴다.
   AND v.resolved_at < now() - CAST(CAST(:retention AS text) AS interval)
RETURNING v.issue_id
"""


async def close_stale_integrity_findings(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    run_id: str,
    receipt: IntegrityObservationReceipt,
) -> int:
    """최신 authoritative generation에서만 stale finding을 닫는다."""

    if not provider or not dataset_key:
        raise ValueError("provider/dataset_key는 close 범위에 필수다.")
    if not run_id:
        raise ValueError("run_id는 비어 있을 수 없다 — 빈 값은 큐 전체를 닫는다.")
    if not receipt.permits_stale_close:
        raise ValueError("authoritative observation receipt가 close를 허용하지 않는다.")

    await session.execute(
        text(_INSERT_OBSERVATION_SCOPE_SQL),
        {"provider": provider, "dataset_key": dataset_key},
    )
    scope = (
        (
            await session.execute(
                text(_LOCK_OBSERVATION_SCOPE_SQL),
                {"provider": provider, "dataset_key": dataset_key},
            )
        )
        .mappings()
        .one()
    )
    row = (
        await session.execute(
            text(_GET_OBSERVATION_RUN_FOR_UPDATE_SQL),
            {
                "provider": provider,
                "dataset_key": dataset_key,
                "external_run_id": run_id,
            },
        )
    ).one_or_none()
    if row is None:
        raise LookupError("finding observation run이 durable하게 시작되지 않았다.")
    observation_run = _observation_run(row)
    if observation_run.status != "collecting":
        return 0

    latest_authoritative = int(scope["latest_authoritative_generation"])
    status = (
        "superseded"
        if observation_run.generation <= latest_authoritative
        else "authoritative"
    )
    finalize_params = {
        "status": status,
        "source_observations": receipt.source_observations,
        "findings_observed": receipt.findings_observed,
        "findings_unique": receipt.findings_unique,
        "findings_upserted": receipt.findings_upserted,
        "observation_run_id": observation_run.observation_run_id,
    }
    await session.execute(text(_FINALIZE_OBSERVATION_RUN_SQL), finalize_params)
    if status == "superseded":
        return 0

    await session.execute(
        text(_ADVANCE_AUTHORITATIVE_GENERATION_SQL),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "generation": observation_run.generation,
        },
    )
    resolution = {
        "closed_by": "observation_generation_sweep",
        "task": "T-VN-H32R",
        "run_id": run_id,
        "generation": observation_run.generation,
        "reason": "이 run이 같은 dedupe_key를 다시 관측하지 않았다",
    }
    result = await session.execute(
        text(_CLOSE_STALE_FINDINGS_SQL),
        {
            "provider": provider,
            "dataset_key": dataset_key,
            "observation_run_id": observation_run.observation_run_id,
            "generation": observation_run.generation,
            "resolution": json.dumps(resolution, ensure_ascii=False),
        },
    )
    return len(result.fetchall())


async def finalize_integrity_observation_run(
    session: AsyncSession,
    *,
    provider: str,
    dataset_key: str,
    external_run_id: str,
    receipt: IntegrityObservationReceipt,
) -> int:
    """명시 이름으로 generation을 authoritative finalize하고 stale을 닫는다."""

    return await close_stale_integrity_findings(
        session,
        provider=provider,
        dataset_key=dataset_key,
        run_id=external_run_id,
        receipt=receipt,
    )


async def purge_resolved_integrity_findings(
    session: AsyncSession,
    *,
    retention: str = "90 days",
) -> int:
    """보존 기간이 지난 ``resolved`` finding을 삭제한다 (T-VN-H32R). commit은 호출자 책임.

    ``acknowledged``는 사람이 인지한 표시라 **지우지 않는다**. ``open``도 당연히 대상이 아니다.

    기본 90일 — ``feature_repo.purge_expired_notices``(1년)와 같은 패턴이지만 finding은
    notice와 달리 **운영 신호**라 분기 회고에 필요한 만큼만 둔다.

    반환: 삭제한 행 수.
    """
    if not retention.strip():
        raise ValueError("retention은 비어 있을 수 없다.")
    result = await session.execute(
        text(_PURGE_RESOLVED_FINDINGS_SQL), {"retention": retention}
    )
    return len(result.fetchall())
