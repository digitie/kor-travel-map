"""B단계 검증기 — 회수한 검증 로직이 실제로 무엇을 잡는지 잰다.

각 테스트는 **손상을 심고 그것이 잡히는지** 본다. 정상 번들이 통과하는 것만 재면
검증기를 통째로 비워도 초록이다(이번 세션에서 반복해 겪은 공허한 게이트).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from kortravelmap.infra.evidence_verify import (
    EvidenceVerificationError,
    compute_acked_through,
    verify_bundle,
)

_EVIDENCE_DIR = "evidence"


def _event(sequence: int) -> dict[str, object]:
    return {
        "event_id": f"e{sequence}",
        "event_sequence": sequence,
        "event_sha256": f"{sequence:064d}",
    }


def _ack(sequence: int, principal: str) -> dict[str, object]:
    return {
        "event_id": f"e{sequence}",
        "principal_id": principal,
        "event_sha256": f"{sequence:064d}",
    }


def _subscription(principal: str, initial: int = 0) -> dict[str, object]:
    return {"principal_id": principal, "initial_event_sequence": initial}


def _write_bundle(
    root: Path,
    relations: dict[str, list[dict[str, object]]],
    *,
    corrupt: str | None = None,
) -> Path:
    """정상 번들을 쓰고, `corrupt`가 주어지면 그 relation의 파일만 손댄다."""

    (root / "meta").mkdir(parents=True, exist_ok=True)
    (root / _EVIDENCE_DIR).mkdir(parents=True, exist_ok=True)
    declared: dict[str, object] = {}
    for name, rows in relations.items():
        relative = f"{_EVIDENCE_DIR}/{name}.jsonl"
        payload = (
            ("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n").encode()
            if rows
            else b""
        )
        declared[name] = {
            "path": relative,
            "row_count": payload.count(b"\n"),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        if corrupt == name:
            # manifest는 그대로 두고 **파일만** 바꾼다 — 지문 대조가 잡아야 한다.
            payload += b'{"tampered": true}\n'
        (root / relative).write_bytes(payload)

    (root / "meta" / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "manual_feature_evidence": {
                    "schema_version": 4,
                    "recovery_status": "audit_only_no_restore",
                    "relations": declared,
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return root


def _healthy(principal: str = "service:pinvi") -> dict[str, list[dict[str, object]]]:
    return {
        "feature_reference_reconciliation_events": [_event(1), _event(2), _event(3)],
        "feature_reference_reconciliation_acks": [
            _ack(1, principal),
            _ack(2, principal),
        ],
        "feature_reference_reconciliation_subscriptions": [_subscription(principal)],
    }


def test_a_healthy_bundle_passes_and_reports_the_rebuilt_cursor(tmp_path: Path) -> None:
    result = verify_bundle(_write_bundle(tmp_path, _healthy()))
    assert result.ok, result.failures
    assert result.relations_checked == 3
    cursor = result.cursors[0]
    # 1·2가 ack됐고 3은 안 됐다 → 연속 prefix는 2까지다.
    assert cursor.acked_through_sequence == 2
    assert cursor.first_missing_sequence == 3


def test_a_tampered_relation_is_caught_by_the_digest(tmp_path: Path) -> None:
    """evidence root 재계산 — manifest는 그대로인데 파일이 바뀌면 잡아야 한다."""

    result = verify_bundle(
        _write_bundle(
            tmp_path, _healthy(), corrupt="feature_reference_reconciliation_events"
        )
    )
    assert not result.ok
    assert any("지문 불일치" in failure for failure in result.failures)
    assert any("행 수 불일치" in failure for failure in result.failures)


def test_a_non_prefix_ack_is_fail_loud(tmp_path: Path) -> None:
    """2를 건너뛰고 3을 ack했다 — 정상 이력에서는 나올 수 없는 모양이다.

    DB의 ack 프로시저가 `event_sequence > acked_through`의 **바로 다음 하나**만
    인정하므로 연속 prefix가 보장된다. 끊긴 곳이 있으면 그것 자체가 손상 신호다.
    """

    relations = _healthy()
    relations["feature_reference_reconciliation_acks"] = [
        _ack(1, "service:pinvi"),
        _ack(3, "service:pinvi"),
    ]
    result = verify_bundle(_write_bundle(tmp_path, relations))
    assert not result.ok
    assert any("연속 prefix가 아닌 ACK" in failure for failure in result.failures)


def test_an_ack_before_the_initial_cursor_is_fail_loud(tmp_path: Path) -> None:
    relations = _healthy()
    relations["feature_reference_reconciliation_subscriptions"] = [
        _subscription("service:pinvi", initial=2)
    ]
    result = verify_bundle(_write_bundle(tmp_path, relations))
    assert not result.ok
    assert any("initial cursor 이전" in failure for failure in result.failures)


def test_an_ack_event_hash_mismatch_is_caught(tmp_path: Path) -> None:
    """ACK가 든 지문이 event의 것과 달라지면 잡는다 — Postgres 없이 되는 축이다."""

    relations = _healthy()
    relations["feature_reference_reconciliation_acks"] = [
        {**_ack(1, "service:pinvi"), "event_sha256": "f" * 64},
        _ack(2, "service:pinvi"),
    ]
    result = verify_bundle(_write_bundle(tmp_path, relations))
    assert not result.ok
    assert any("ACK/event 해시 불일치" in failure for failure in result.failures)


def test_an_ack_pointing_at_a_missing_event_is_caught(tmp_path: Path) -> None:
    relations = _healthy()
    relations["feature_reference_reconciliation_acks"] = [
        _ack(1, "service:pinvi"),
        {"event_id": "e99", "principal_id": "service:pinvi", "event_sha256": "0" * 64},
    ]
    result = verify_bundle(_write_bundle(tmp_path, relations))
    assert not result.ok
    assert any("존재하지 않는 event" in failure for failure in result.failures)


def test_a_bundle_without_evidence_is_refused(tmp_path: Path) -> None:
    """evidence를 담지 않은 번들을 조용히 통과시키면 안 된다.

    n150의 backup이 정확히 그 상태였다 — 담을 것이 없는데 '검증 통과'가 나오면
    그것이 이 항목이 막으려는 실패다.
    """

    (tmp_path / "meta").mkdir(parents=True)
    (tmp_path / "meta" / "manifest.json").write_text(
        json.dumps({"schema_version": 1}), encoding="utf-8"
    )
    with pytest.raises(EvidenceVerificationError, match="evidence를 담지 않았다"):
        verify_bundle(tmp_path)


def test_the_result_says_what_it_did_not_verify(tmp_path: Path) -> None:
    """침묵을 통과로 읽으면 안 된다 — 안 본 것을 결과가 말한다."""

    result = verify_bundle(_write_bundle(tmp_path, _healthy()))
    joined = " ".join(result.not_verified)
    assert "ownership" in joined
    assert "extension" in joined
    assert "RustFS" in joined
    # payload 해시 **재계산**은 Postgres가 있어야 하므로 하지 않았다고 말한다.
    assert result.payload_hash_checked is False


def test_acked_through_is_the_contiguous_prefix_not_the_maximum() -> None:
    """끊긴 뒤의 ack는 cursor를 밀지 못한다 — 최댓값을 쓰면 데이터를 건너뛴다."""

    cursors = compute_acked_through(
        subscriptions=[_subscription("p")],
        events=[_event(1), _event(2), _event(3), _event(4)],
        acks=[_ack(1, "p"), _ack(3, "p"), _ack(4, "p")],
    )
    assert cursors[0].acked_through_sequence == 1
    assert cursors[0].first_missing_sequence == 2


def test_a_subscription_with_no_acks_keeps_its_initial_cursor() -> None:
    cursors = compute_acked_through(
        subscriptions=[_subscription("p", initial=7)],
        events=[_event(8), _event(9)],
        acks=[],
    )
    assert cursors[0].acked_through_sequence == 7
    assert cursors[0].first_missing_sequence == 8
