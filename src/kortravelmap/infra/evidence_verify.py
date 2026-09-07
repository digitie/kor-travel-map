"""backup artifact만으로 M05 evidence를 검증한다 (T-VN-M05-2 B단계).

## 무엇을 회수했나

이 검증 로직은 새로 지은 것이 아니다. 커밋 `b2543d68`("refactor: establish
application 300 baseline boundary") 직전의 `scripts/docker-restore-verify.sh`(416줄)에
거의 조문 그대로 있었고 그 커밋이 지웠다. 여기서 회수하되 **live DB에 쓰지 않는
형태**로 옮긴다 — 옛 버전은 복원된 DB에 lease를 다시 써 넣었지만, 이 모듈은 계산만
하고 결과를 돌려준다.

## Postgres에 의존하는 축과 아닌 축을 나눈다

`event_sha256`은 `x_extension.digest(convert_to(event_payload::text, 'UTF8'), 'sha256')`
이고, `event_payload::text`는 **Postgres의 jsonb 렌더링**이다. 그것을 Python으로
재구현하면 정본이 둘이 되고 Postgres major 버전이 렌더링을 바꾸는 순간 조용히
갈라진다 — 이 저장소가 반복해 겪은 실패 양상이다. 그래서:

- **구조·순서 축**(evidence root 재계산, ACK 연속 prefix, `acked_through` 계산,
  initial cursor 이전 ACK)은 순수 Python으로 한다. 이것이 M05-2의 대부분이다.
- **payload 해시·envelope 축**은 Postgres가 있어야 하므로 별도 단계로 두고,
  **건너뛰었으면 건너뛰었다고 보고한다.** 침묵을 통과로 읽으면 안 된다.

## 무엇을 증명하지 않는가

artifact 무결성만 본다. ownership·ACL·extension 인벤토리·`pg_restore` TOC 적용
가능성·RustFS 실물은 **보지 않는다.** 결과에 그 목록을 실어, receipt를 읽는 사람이
"복원 가능하다"로 오해하지 않게 한다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Final

__all__ = [
    "EvidenceVerificationError",
    "SubscriptionCursor",
    "VerificationResult",
    "compute_acked_through",
    "verify_bundle",
]

#: 이 검증기가 **보지 않는** 것. 결과에 그대로 실린다.
NOT_VERIFIED: Final[tuple[str, ...]] = (
    "database ownership and ACL",
    "extension inventory",
    "pg_restore TOC applicability",
    "RustFS object payloads",
    "relations outside this evidence root",
)


class EvidenceVerificationError(RuntimeError):
    """artifact가 자기 manifest와 어긋난다."""


@dataclass(frozen=True)
class SubscriptionCursor:
    """한 principal의 재구축된 cursor."""

    principal_id: str
    initial_event_sequence: int
    acked_through_sequence: int
    #: 연속 prefix가 끊긴 첫 event sequence. `None`이면 끊긴 곳이 없다.
    first_missing_sequence: int | None


@dataclass
class VerificationResult:
    """검증 결과. **실패도 담는다** — 통과만 담으면 침묵이 통과로 읽힌다."""

    relations_checked: int = 0
    failures: list[str] = field(default_factory=list)
    cursors: list[SubscriptionCursor] = field(default_factory=list)
    payload_hash_checked: bool = False
    not_verified: tuple[str, ...] = NOT_VERIFIED

    @property
    def ok(self) -> bool:
        return not self.failures


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise EvidenceVerificationError(f"evidence 파일이 없다: {path}")
    raw = path.read_bytes()
    if not raw:
        return []
    return [json.loads(line) for line in raw.splitlines()]


def _digest(path: Path) -> tuple[int, str]:
    raw = path.read_bytes()
    return raw.count(b"\n"), hashlib.sha256(raw).hexdigest()


def compute_acked_through(
    *,
    subscriptions: list[dict[str, Any]],
    events: list[dict[str, Any]],
    acks: list[dict[str, Any]],
) -> list[SubscriptionCursor]:
    """불변 ACK/event의 **연속 prefix**에서 cursor를 다시 만든다.

    옛 검증기의 LATERAL 두 개를 그대로 옮긴 것이다:

    1. `initial_event_sequence` 뒤로 ACK가 **없는** 첫 event sequence를 찾는다.
    2. 그보다 **작은** event만으로 `max(event_sequence)`를 취한다. 없으면
       `initial_event_sequence` 그대로다.

    이것이 근사가 아닌 이유는 DB가 보증한다 — ack 프로시저가
    `event_sequence > acked_through`의 **바로 다음 하나**만 인정하므로 정상 이력은
    항상 연속 prefix다. 끊긴 곳이 있으면 그것 자체가 손상 신호다.
    """

    sequence_by_event: dict[str, int] = {
        str(event["event_id"]): int(event["event_sequence"]) for event in events
    }
    acked_sequences: dict[str, set[int]] = {}
    for ack in acks:
        principal = str(ack["principal_id"])
        sequence = sequence_by_event.get(str(ack["event_id"]))
        if sequence is not None:
            acked_sequences.setdefault(principal, set()).add(sequence)

    ordered = sorted(sequence_by_event.values())
    cursors: list[SubscriptionCursor] = []
    for subscription in sorted(
        subscriptions, key=lambda row: str(row["principal_id"])
    ):
        principal = str(subscription["principal_id"])
        initial = int(subscription["initial_event_sequence"])
        seen = acked_sequences.get(principal, set())
        candidates = [sequence for sequence in ordered if sequence > initial]

        first_missing = next(
            (sequence for sequence in candidates if sequence not in seen), None
        )
        prefix = [
            sequence
            for sequence in candidates
            if first_missing is None or sequence < first_missing
        ]
        cursors.append(
            SubscriptionCursor(
                principal_id=principal,
                initial_event_sequence=initial,
                acked_through_sequence=max(prefix) if prefix else initial,
                first_missing_sequence=first_missing,
            )
        )
    return cursors


def _check_ack_continuity(
    result: VerificationResult,
    *,
    subscriptions: list[dict[str, Any]],
    events: list[dict[str, Any]],
    acks: list[dict[str, Any]],
) -> None:
    """불연속 ACK와 initial cursor 이전 ACK는 fail-loud다."""

    sequence_by_event = {
        str(event["event_id"]): int(event["event_sequence"]) for event in events
    }
    initial_by_principal = {
        str(row["principal_id"]): int(row["initial_event_sequence"])
        for row in subscriptions
    }

    for ack in acks:
        principal = str(ack["principal_id"])
        sequence = sequence_by_event.get(str(ack["event_id"]))
        if sequence is None:
            result.failures.append(
                f"ACK가 존재하지 않는 event를 가리킨다: {ack['event_id']}"
            )
            continue
        initial = initial_by_principal.get(principal)
        if initial is not None and sequence <= initial:
            result.failures.append(
                f"ACK가 initial cursor 이전이다: {principal} seq={sequence}"
                f" initial={initial}"
            )

    for cursor in result.cursors:
        if cursor.first_missing_sequence is None:
            continue
        later = [
            sequence_by_event[str(ack["event_id"])]
            for ack in acks
            if str(ack["principal_id"]) == cursor.principal_id
            and str(ack["event_id"]) in sequence_by_event
        ]
        if any(sequence > cursor.first_missing_sequence for sequence in later):
            result.failures.append(
                f"연속 prefix가 아닌 ACK: {cursor.principal_id}"
                f" first_missing={cursor.first_missing_sequence}"
            )


def _check_ack_event_hash(
    result: VerificationResult,
    *,
    events: list[dict[str, Any]],
    acks: list[dict[str, Any]],
) -> None:
    """ACK가 든 `event_sha256`이 그 event의 것과 같아야 한다.

    이 축은 **Postgres 없이 된다** — 양쪽 다 이미 저장된 값이라 다시 렌더링할 필요가
    없다. payload에서 해시를 **재계산**하는 축만 Postgres가 필요하다.
    """

    hash_by_event = {
        str(event["event_id"]): str(event["event_sha256"]) for event in events
    }
    for ack in acks:
        event_id = str(ack["event_id"])
        expected = hash_by_event.get(event_id)
        if expected is None:
            continue
        if str(ack.get("event_sha256")) != expected:
            result.failures.append(f"ACK/event 해시 불일치: event={event_id}")


def verify_bundle(bundle: Path) -> VerificationResult:
    """backup 번들 하나를 검증한다.

    `meta/manifest.json`의 `manual_feature_evidence.relations`를 **읽어서** 대상을
    정한다 — relation 목록을 여기에 박으면 옛 `schema_version in {1,2,3}` 고정
    게이트와 같은 부패를 다시 심는다(그 게이트가 정확히 코드 부패의 정체였다).
    """

    result = VerificationResult()
    manifest_path = bundle / "meta" / "manifest.json"
    if not manifest_path.exists():
        raise EvidenceVerificationError(f"manifest가 없다: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    evidence = manifest.get("manual_feature_evidence")
    if not isinstance(evidence, dict):
        raise EvidenceVerificationError(
            "manifest에 manual_feature_evidence가 없다 — 이 번들은 evidence를 담지 않았다"
        )
    relations = evidence.get("relations")
    if not isinstance(relations, dict) or not relations:
        raise EvidenceVerificationError("manifest의 relations가 비어 있다")

    loaded: dict[str, list[dict[str, Any]]] = {}
    for name, declared in sorted(relations.items()):
        path = bundle / str(declared["path"])
        try:
            row_count, sha256 = _digest(path)
        except OSError as error:
            result.failures.append(f"{name}: 읽지 못했다 ({error})")
            continue
        result.relations_checked += 1
        if row_count != int(declared["row_count"]):
            result.failures.append(
                f"{name}: 행 수 불일치 manifest={declared['row_count']} 실제={row_count}"
            )
        if sha256 != str(declared["sha256"]):
            result.failures.append(
                f"{name}: 지문 불일치 manifest={declared['sha256']} 실제={sha256}"
            )
        try:
            loaded[name] = _read_jsonl(path)
        except (EvidenceVerificationError, json.JSONDecodeError) as error:
            result.failures.append(f"{name}: JSONL을 읽지 못했다 ({error})")

    events = loaded.get("feature_reference_reconciliation_events", [])
    acks = loaded.get("feature_reference_reconciliation_acks", [])
    subscriptions = loaded.get(
        "feature_reference_reconciliation_subscriptions", []
    )

    result.cursors = compute_acked_through(
        subscriptions=subscriptions, events=events, acks=acks
    )
    _check_ack_continuity(
        result, subscriptions=subscriptions, events=events, acks=acks
    )
    _check_ack_event_hash(result, events=events, acks=acks)
    return result
