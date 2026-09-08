"""evidence exporter가 backup 스크립트와 **같은 규약**을 쓰는지 결박한다.

두 곳이 어긋나면 `docker-backup.sh`가 만든 artifact와 이 exporter가 만든 artifact를
같은 검증기로 볼 수 없다 — 그러면 검증기가 조용히 한쪽만 보게 된다. 이번 세션에서
반복해 겪은 실패 양상(정본과 사본이 갈렸는데 아무도 안 잡는다)과 같은 것이라
**값이 아니라 두 구현을 대조한다.**
"""

from __future__ import annotations

import pathlib
import re
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from kortravelmap.infra.evidence_export import (
    EVIDENCE_RELATIONS,
    canonical_jsonl,
    export_evidence,
    manifest_bytes,
    manifest_fragment,
    relation_digest,
)

pytestmark = [pytest.mark.integration]

_BACKUP_SCRIPT = (
    pathlib.Path(__file__).resolve().parents[2] / "scripts" / "docker-backup.sh"
)


def _script_relations() -> list[tuple[str, str]]:
    """`docker-backup.sh`의 `capture_evidence_jsonl` 호출을 파싱한다."""

    source = _BACKUP_SCRIPT.read_text(encoding="utf-8")
    pattern = re.compile(
        r'capture_evidence_jsonl\s*\\\s*\n\s*(\w+)\s*\\\s*\n\s*"([^"]+)"',
        re.MULTILINE,
    )
    return [(m.group(1), m.group(2)) for m in pattern.finditer(source)]


def test_evidence_export_matches_the_backup_script_contract() -> None:
    """relation 이름·순서·SELECT가 **문자 그대로** 같아야 한다.

    정렬이 규약의 일부다 — `ORDER BY`가 다르면 같은 내용이 다른 SHA-256을 낸다.
    그래서 SELECT 전체를 대조하지, 이름만 대조하지 않는다.
    """

    script = _script_relations()
    assert script, "backup 스크립트에서 evidence 호출을 파싱하지 못했다"

    exporter = [(relation.name, relation.select_sql) for relation in EVIDENCE_RELATIONS]
    def normalise(sql: str) -> str:
        return " ".join(sql.split())

    assert [(name, normalise(sql)) for name, sql in exporter] == [
        (name, normalise(sql)) for name, sql in script
    ]


def test_canonical_jsonl_matches_the_psql_output_shape() -> None:
    """빈 relation은 **빈 바이트열**이고, 행마다 개행 하나다.

    `psql -A -t`가 그렇게 낸다. 여기서 빈 relation에 개행 하나를 내면 행 수가
    0이 아니라 1로 세어져 manifest가 어긋난다.
    """

    assert canonical_jsonl([]) == b""
    assert relation_digest("x", canonical_jsonl([])).row_count == 0

    payload = canonical_jsonl(['{"a": 1}', '{"a": 2}'])
    assert payload == b'{"a": 1}\n{"a": 2}\n'
    assert relation_digest("x", payload).row_count == 2


def test_manifest_carries_what_it_does_not_verify() -> None:
    """산출물이 *복원 가능하다*를 증명하지 않는다는 사실을 manifest가 싣는다.

    이것이 빠지면 receipt가 "검증 통과"로 읽히고, 그것이 이 정책이 애초에 피하려던
    실패다(검증되지 않은 복구 경로를 믿는 것).
    """

    fragment = manifest_fragment(
        {"x": relation_digest("x", b"")},
        alembic_revision="305_m05_relitigation_fence",
        server_version="17.0",
    )
    not_verified = fragment["not_verified"]
    assert isinstance(not_verified, list)
    assert any("ownership" in str(item) for item in not_verified)
    assert any("extension" in str(item) for item in not_verified)
    # manifest 자신도 해시 대상이 되게 바이트로 낼 수 있어야 한다.
    assert manifest_bytes(fragment).endswith(b"\n")


async def test_export_reads_every_relation_in_one_snapshot(
    migrated_engine: AsyncEngine,
) -> None:
    """열 relation을 실제 DB에서 뽑고, 행 수·지문이 손계산과 맞는지 본다."""

    async with migrated_engine.begin() as connection:
        await connection.execute(
            text(
                "INSERT INTO ops.domain_commands "
                "(actor, operation, idempotency_key, request_fingerprint) "
                "VALUES (:actor, :operation, x_extension.gen_random_uuid(), repeat('d', 64))"
            ),
            {
                "actor": f"admin:evidence-{uuid4().hex[:8]}",
                "operation": "admin.evidence-export.test-v1",
            },
        )

    async with migrated_engine.connect() as connection:
        await connection.execute(
            text("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
        )
        exported = await export_evidence(connection)

    assert set(exported) == {relation.name for relation in EVIDENCE_RELATIONS}

    payload, digest = exported["domain_commands"]
    assert digest.row_count >= 1
    assert digest.row_count == payload.count(b"\n")
    assert relation_digest("domain_commands", payload).sha256 == digest.sha256
    # 각 행이 온전한 JSON 객체여야 한다 — canonical JSONL의 요지다.
    for line in payload.splitlines():
        assert line.startswith(b"{")
        assert line.endswith(b"}")


async def test_lease_is_deliberately_absent_from_the_evidence_root(
    migrated_engine: AsyncEngine,
) -> None:
    """`lease`는 담지 않는다 — 담으면 fencing token이 되살아난다.

    `ops.feature_reference_reconciliation_leases`는 mutable projection이고, 불변
    ACK/event의 연속 prefix에서 **다시 만들어야** 하는 값이다. 옛 restore 검증기가
    그 이유를 적어 뒀다("dump 시점의 worker fencing token은 반드시 무효화한다").
    담아 두면 복원 뒤 두 holder가 생긴다.
    """

    names = {relation.name for relation in EVIDENCE_RELATIONS}
    assert "feature_reference_reconciliation_leases" not in names
    # 그런데 그 relation은 **실재해야** 한다 — 없으면 이 단언이 공허하다.
    async with migrated_engine.connect() as connection:
        assert (
            await connection.scalar(
                text(
                    "SELECT to_regclass("
                    "'ops.feature_reference_reconciliation_leases') IS NOT NULL"
                )
            )
            is True
        )
