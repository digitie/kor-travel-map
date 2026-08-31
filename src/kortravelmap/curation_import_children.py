"""T-VN-M03 — import child command identity의 결정적 유도.

import 부모 command(``admin.curation.import``)는 batch lifecycle을 소유하고, 실제 manual
Feature 생성은 plan row마다 private child command로 분리한다. 그 child의 idempotency
identity를 **무엇에서 유도하는가**가 이 모듈의 전부다.

## 무엇을 쓰지 않는가

설계 §6.2가 두 가지를 명시적으로 배제한다.

- ``parent_command_id`` — retry마다 새로 생긴다. 이것을 쓰면 같은 plan을 재시도할 때
  같은 행이 매번 다른 child가 되어, 부모가 재시도될 때마다 Feature가 중복 생성된다.
- ``import_row_id`` — commit **결과**다. child를 만들기 전에는 존재하지 않으므로
  입력이 될 수 없다.

그래서 이 함수의 시그니처에는 둘 다 없다. 넣을 자리가 없는 것이 계약이다.

## 무엇을 쓰는가

잠긴 부모의 identity(``actor`` + ``operation`` + ``Idempotency-Key`` +
``request_fingerprint``)와 immutable plan의 좌표(``import_plan_id`` + ``plan_sha256`` +
``plan_row_number`` + typed manual payload SHA-256)다. 앞의 넷은 "누가 어떤 요청으로"를,
뒤의 넷은 "그 요청 안의 어느 행을"을 고정한다.

plan이 재해소되면 ``plan_sha256``이 달라지므로 child도 달라진다 — 다른 내용의 plan에
같은 child가 붙는 것을 막는다.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final
from uuid import UUID, uuid5

CHILD_OPERATION: Final = "admin.curation-import.manual-feature-row.create-v1"
"""child command의 operation. 외부 HTTP가 이 operation을 직접 부르는 route는 없다."""

CHILD_IDEMPOTENCY_NAMESPACE: Final = UUID("2d3e71ea-3144-5fe1-a4e3-99c2c3ef7bfc")
"""child idempotency key의 UUIDv5 namespace.

``uuid5(NAMESPACE_URL,
"https://github.com/digitie/kor-travel-map/t-vn-m03/child-command")``로 한 번 유도해
상수로 굳혔다. 값이 바뀌면 과거 child identity가 전부 달라지므로 바꾸지 않는다.
"""

_PREIMAGE_VERSION: Final = 1


@dataclass(frozen=True, slots=True)
class ParentCommandIdentity:
    """child 유도에 쓰는 **잠긴 부모**의 identity.

    ``command_id``를 일부러 담지 않는다 — retry마다 달라지는 값이 identity에 섞이면
    같은 행이 재시도마다 다른 child가 된다.
    """

    actor: str
    operation: str
    idempotency_key: str
    request_fingerprint: str


@dataclass(frozen=True, slots=True)
class ChildCommandIdentity:
    """한 plan row가 만들 child command의 결정적 identity."""

    operation: str
    idempotency_key: UUID
    request_fingerprint: str


def child_command_preimage(
    *,
    parent: ParentCommandIdentity,
    import_plan_id: str,
    plan_sha256: str,
    plan_row_number: int,
    manual_payload_sha256: str,
) -> str:
    """child identity의 canonical preimage.

    key 정렬·공백 없음·비ASCII 그대로 — 직렬화가 결정적이어야 같은 입력이 같은 child를
    낸다. 테스트가 이 문자열을 직접 보게 해 두어, 입력이 하나라도 빠지면 드러나게 한다.
    """
    return json.dumps(
        {
            "version": _PREIMAGE_VERSION,
            "child_operation": CHILD_OPERATION,
            "parent": {
                "actor": parent.actor,
                "operation": parent.operation,
                "idempotency_key": parent.idempotency_key,
                "request_fingerprint": parent.request_fingerprint,
            },
            "plan": {
                "import_plan_id": import_plan_id,
                "plan_sha256": plan_sha256,
                "plan_row_number": plan_row_number,
                "manual_payload_sha256": manual_payload_sha256,
            },
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def derive_child_command_identity(
    *,
    parent: ParentCommandIdentity,
    import_plan_id: str,
    plan_sha256: str,
    plan_row_number: int,
    manual_payload_sha256: str,
) -> ChildCommandIdentity:
    """plan row 하나의 child command identity를 결정적으로 유도한다.

    같은 (부모 요청, plan 내용, 행 번호, typed payload)이면 언제 몇 번을 유도해도 같은
    값이다. 넷 중 하나라도 다르면 다른 child다.
    """
    preimage = child_command_preimage(
        parent=parent,
        import_plan_id=import_plan_id,
        plan_sha256=plan_sha256,
        plan_row_number=plan_row_number,
        manual_payload_sha256=manual_payload_sha256,
    )
    return ChildCommandIdentity(
        operation=CHILD_OPERATION,
        idempotency_key=uuid5(CHILD_IDEMPOTENCY_NAMESPACE, preimage),
        request_fingerprint=hashlib.sha256(preimage.encode()).hexdigest(),
    )
