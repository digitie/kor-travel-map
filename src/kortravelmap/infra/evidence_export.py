"""재생성 불가능한 evidence를 canonical JSONL로 뽑는다 (T-VN-M05-2 A단계).

## 왜 필요한가

지배적 손실은 사고가 아니라 **계획된 재구축**이다. `ktdctl pinvi-pair rebuild-pinned`가
Map revision이 바뀔 때마다 application DB를 `dropdb --force` 후 `template0`에서 다시
만든다 — `.env` 값 하나가 바뀌어도 그 경로를 탄다. 2026-09-07 03:23 UTC의 rebuild가
만든 빈 DB가 지금 n150의 `kor_travel_map`이다.

재적재가 되살리는 것은 provider 파생분뿐이다. 아래 열 relation은 **되살아나지 않는다**:

- `feature.feature_creation_origins` — 어느 Feature가 admin/curation/request 산인지.
  provider에 그 장소가 아예 없다.
- `feature.manual_feature_identity_claims` — exact identity 예약.
- `ops.domain_commands`·`domain_command_results` — 위 둘의 FK 대상. 잃으면 origin과
  claim이 orphan이 되어 append-only 불변 자체가 깨진다.
- `ops.feature_requests` — PinVi가 올린 **사용자 제출**. 외부 입력이라 재생성 불가.
- `ops.manual_provider_dedup_cases`·`_resolutions` — admin의 판정 이력.
- `ops.feature_reference_reconciliation_{events,acks,subscriptions}` — PinVi와의 합의.

**manual-feature writer는 2026-09-05T20:27:59Z에 prod에서 켜졌다.** 그때부터 위
데이터가 쌓이는데 그것을 담은 backup이 n150에서 한 번도 만들어진 적이 없다.

## 이 모듈이 하는 일과 하지 않는 일

**하는 일**: 하나의 exported snapshot에 결박된 REPEATABLE READ READ ONLY 트랜잭션에서
열 relation을 PK 순서 canonical JSONL로 뽑고, relation별 행 수와 SHA-256을 낸다.
규약은 `scripts/docker-backup.sh`(§evidence)와 **바이트 단위로 같아야 한다** — 다르면
그 스크립트가 만든 artifact와 이 모듈이 만든 artifact를 같은 검증기로 볼 수 없다.
`test_evidence_export_matches_the_backup_script_contract`가 둘을 결박한다.

**하지 않는 일**: 쓰기. 복원. 판정. 이 모듈은 읽기 전용이고, 산출물은 *복원 가능하다*를
증명하지 않는다 — ownership·ACL·extension 인벤토리·dump TOC 적용 가능성 중 어느 것도
보지 않는다. 그 한계를 manifest fragment에 명시해 실어, 나중에 receipt를 읽는 사람이
"검증 통과"로 오해하지 않게 한다.

`lease`는 일부러 넣지 않는다. `ops.feature_reference_reconciliation_leases`는 mutable
projection이고, 불변 ACK/event의 연속 prefix에서 다시 만들어야 하는 값이다 — 담아 두면
dump 시점의 worker fencing token이 되살아나 두 holder가 생긴다.

ADR 참조: ADR-002 async-only · ADR-004 raw SQL `text()` · ADR-097 §후속 1
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncConnection

__all__ = [
    "EVIDENCE_RELATIONS",
    "EVIDENCE_SCHEMA_VERSION",
    "EvidenceRelation",
    "RelationDigest",
    "canonical_jsonl",
    "export_evidence",
    "relation_digest",
]

#: manifest fragment의 형식 버전. 옛 `schema_version in {1,2,3}` 고정 게이트가 코드
#: 부패의 정체였으므로(2026-09-08 조사), 검증기는 이 값을 **manifest에서 읽어** 분기하고
#: 상수로 박지 않는다.
EVIDENCE_SCHEMA_VERSION: Final[int] = 1


@dataclass(frozen=True)
class EvidenceRelation:
    """한 relation의 canonical 추출 규약."""

    name: str
    #: `to_jsonb(row)::text`를 PK 순서로 내는 SELECT. **정렬이 규약의 일부다** —
    #: 순서가 다르면 같은 내용이 다른 SHA-256을 낸다.
    select_sql: str


#: `scripts/docker-backup.sh`가 담는 것과 **같은 열 relation, 같은 순서**다.
#: 이 목록은 Map에 남는다 — Manager는 범용 hook만 갖고 이 목록을 알지 않는다
#: (사용자의 "Manager 범용성 유지" 지시).
EVIDENCE_RELATIONS: Final[tuple[EvidenceRelation, ...]] = (
    EvidenceRelation(
        "manual_feature_identity_claims",
        "SELECT to_jsonb(claim)::text FROM feature.manual_feature_identity_claims"
        " AS claim ORDER BY claim.feature_id",
    ),
    EvidenceRelation(
        "feature_creation_origins",
        "SELECT to_jsonb(origin)::text FROM feature.feature_creation_origins"
        " AS origin ORDER BY origin.feature_id",
    ),
    EvidenceRelation(
        "domain_commands",
        "SELECT to_jsonb(command)::text FROM ops.domain_commands"
        " AS command ORDER BY command.command_id",
    ),
    EvidenceRelation(
        "domain_command_results",
        "SELECT to_jsonb(result)::text FROM ops.domain_command_results"
        " AS result ORDER BY result.command_id",
    ),
    EvidenceRelation(
        "feature_requests",
        "SELECT to_jsonb(request)::text FROM ops.feature_requests"
        " AS request ORDER BY request.request_id",
    ),
    EvidenceRelation(
        "manual_provider_dedup_cases",
        "SELECT to_jsonb(dedup_case)::text FROM ops.manual_provider_dedup_cases"
        " AS dedup_case ORDER BY dedup_case.case_id",
    ),
    EvidenceRelation(
        "manual_provider_dedup_resolutions",
        "SELECT to_jsonb(resolution)::text FROM ops.manual_provider_dedup_resolutions"
        " AS resolution ORDER BY resolution.resolution_id",
    ),
    EvidenceRelation(
        "feature_reference_reconciliation_events",
        "SELECT to_jsonb(event)::text FROM ops.feature_reference_reconciliation_events"
        " AS event ORDER BY event.event_sequence",
    ),
    EvidenceRelation(
        "feature_reference_reconciliation_acks",
        "SELECT to_jsonb(ack)::text FROM ops.feature_reference_reconciliation_acks"
        " AS ack ORDER BY ack.event_id, ack.principal_id",
    ),
    EvidenceRelation(
        "feature_reference_reconciliation_subscriptions",
        "SELECT to_jsonb(subscription)::text FROM"
        " ops.feature_reference_reconciliation_subscriptions"
        " AS subscription ORDER BY subscription.principal_id",
    ),
)


@dataclass(frozen=True)
class RelationDigest:
    """한 relation의 행 수와 지문."""

    name: str
    row_count: int
    sha256: str


def canonical_jsonl(rows: Sequence[str]) -> bytes:
    """행마다 개행 하나. 빈 relation은 **빈 바이트열**이다.

    `psql -A -t`의 출력 규약과 같다 — 그래야 `docker-backup.sh`가 만든 파일과
    이 모듈이 만든 파일의 SHA-256이 같아진다.
    """

    if not rows:
        return b""
    return ("\n".join(rows) + "\n").encode("utf-8")


def relation_digest(name: str, payload: bytes) -> RelationDigest:
    """행 수는 개행 수다 — `wc -l`과 같은 셈이라야 manifest가 호환된다."""

    return RelationDigest(
        name=name,
        row_count=payload.count(b"\n"),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


async def export_evidence(
    connection: AsyncConnection,
    *,
    snapshot_id: str | None = None,
) -> dict[str, tuple[bytes, RelationDigest]]:
    """열 relation을 **하나의 스냅숏에서** 뽑는다.

    `snapshot_id`를 주면 `SET TRANSACTION SNAPSHOT`으로 그 스냅숏에 결박한다 —
    `pg_dump --snapshot`과 같은 시점을 보게 하려는 것이다. 주지 않으면 호출자가 연
    트랜잭션의 스냅숏을 그대로 쓴다.

    **relation 사이에 시점이 갈리면 안 된다.** 예를 들어 `domain_commands`를 읽은 뒤
    `feature_creation_origins`를 다른 시점에서 읽으면 origin이 가리키는 command가 없는
    artifact가 나오고, 그것은 append-only 불변을 어긴 것처럼 보인다.
    """

    if snapshot_id is not None:
        await connection.execute(
            text("SET TRANSACTION SNAPSHOT :snapshot_id").bindparams(
                snapshot_id=snapshot_id
            )
        )

    exported: dict[str, tuple[bytes, RelationDigest]] = {}
    for relation in EVIDENCE_RELATIONS:
        result = await connection.execute(text(relation.select_sql))
        rows = [str(row[0]) for row in result]
        payload = canonical_jsonl(rows)
        exported[relation.name] = (payload, relation_digest(relation.name, payload))
    return exported


def manifest_fragment(
    digests: Mapping[str, RelationDigest],
    *,
    alembic_revision: str,
    server_version: str,
) -> dict[str, object]:
    """검증기가 읽을 manifest 조각.

    **한계를 함께 싣는다.** 이 산출물은 artifact 무결성만 증명하고 *복원 가능하다*를
    증명하지 않는다 — receipt를 "검증 통과"로 읽으면 정확히 이 정책이 피하려던 실패로
    되돌아간다. 그래서 `not_verified`를 값으로 적어 둔다.
    """

    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "alembic_revision": alembic_revision,
        "server_version": server_version,
        "relations": {
            name: {"row_count": digest.row_count, "sha256": digest.sha256}
            for name, digest in sorted(digests.items())
        },
        "not_verified": [
            "database ownership and ACL",
            "extension inventory",
            "pg_restore TOC applicability",
            "RustFS object payloads",
            "relations outside this evidence root",
        ],
    }


def manifest_bytes(fragment: Mapping[str, object]) -> bytes:
    """manifest도 해시 대상이다 — 옛 artifact는 manifest가 `SHA256SUMS`에 없었다."""

    return (
        json.dumps(dict(fragment), ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")
