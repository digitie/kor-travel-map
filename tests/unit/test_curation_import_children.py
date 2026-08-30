"""T-VN-M03 — child command identity 유도 규칙.

이 identity가 틀리면 두 가지 중 하나가 벌어진다.

- 재시도마다 달라지면 → 같은 행이 매번 새 Feature를 만든다(중복 생성)
- 서로 다른 행이 같아지면 → `UNIQUE(child_command_id)`에 걸려 batch 전체가 죽는다

그래서 "같은 것은 같고 다른 것은 다르다"를 입력 축마다 하나씩 고정한다.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from kortravelmap.curation_import_children import (
    CHILD_IDEMPOTENCY_NAMESPACE,
    CHILD_OPERATION,
    ParentCommandIdentity,
    child_command_preimage,
    derive_child_command_identity,
)

pytestmark = pytest.mark.unit

_PARENT = ParentCommandIdentity(
    actor="admin-ui-bff",
    operation="admin.curation.import",
    idempotency_key="7f1a1d0e-3d5a-4a4f-9a1a-1b2c3d4e5f60",
    request_fingerprint="a" * 64,
)
_BASE: dict[str, object] = {
    "import_plan_id": "0f2f3a4b-5c6d-4e7f-8a9b-0c1d2e3f4a5b",
    "plan_sha256": "b" * 64,
    "plan_row_number": 2,
    "manual_payload_sha256": "c" * 64,
}


def _derive(**overrides: object):
    kwargs = {**_BASE, **overrides}
    return derive_child_command_identity(parent=_PARENT, **kwargs)  # type: ignore[arg-type]


def test_identity_is_deterministic() -> None:
    assert _derive() == _derive()


def test_identity_uses_the_declared_child_operation() -> None:
    identity = _derive()

    assert identity.operation == CHILD_OPERATION
    assert identity.operation == "admin.curation-import.manual-feature-row.create-v1"


@pytest.mark.parametrize(
    "override",
    [
        {"plan_row_number": 3},
        {"plan_sha256": "d" * 64},
        {"manual_payload_sha256": "e" * 64},
        {"import_plan_id": "11111111-2222-4333-8444-555555555555"},
    ],
    ids=["row", "plan_sha", "payload_sha", "plan_id"],
)
def test_each_plan_axis_changes_the_identity(override: dict[str, object]) -> None:
    """행·plan 내용·payload·plan이 다르면 다른 child다."""
    assert _derive(**override).idempotency_key != _derive().idempotency_key


@pytest.mark.parametrize(
    "field",
    ["actor", "operation", "idempotency_key", "request_fingerprint"],
)
def test_each_parent_axis_changes_the_identity(field: str) -> None:
    """부모 요청이 다르면 다른 child다 — 다른 사람의 같은 파일이 섞이지 않는다."""
    changed = replace(_PARENT, **{field: getattr(_PARENT, field) + "-x"})

    other = derive_child_command_identity(parent=changed, **_BASE)  # type: ignore[arg-type]

    assert other.idempotency_key != _derive().idempotency_key


def test_preimage_carries_every_declared_input() -> None:
    """§6.2가 지정한 여덟 입력이 preimage에 실제로 들어 있어야 한다.

    하나라도 빠지면 그 축이 달라져도 같은 child가 된다 — 위 파라미터 테스트가 잡지만,
    여기서는 **왜** 잡히는지를 문서화한다.
    """
    payload = json.loads(child_command_preimage(parent=_PARENT, **_BASE))  # type: ignore[arg-type]

    assert payload["parent"] == {
        "actor": _PARENT.actor,
        "operation": _PARENT.operation,
        "idempotency_key": _PARENT.idempotency_key,
        "request_fingerprint": _PARENT.request_fingerprint,
    }
    assert payload["plan"] == _BASE
    assert payload["child_operation"] == CHILD_OPERATION


def test_preimage_excludes_parent_command_id_and_import_row_id() -> None:
    """설계 §6.2가 배제한 두 값이 identity에 섞이지 않아야 한다.

    ``parent_command_id``는 retry마다 새로 생기고 ``import_row_id``는 commit 결과다.
    둘 중 하나라도 들어가면 재시도가 중복 Feature를 만든다.
    """
    preimage = child_command_preimage(parent=_PARENT, **_BASE)  # type: ignore[arg-type]

    assert "command_id" not in preimage
    assert "import_row_id" not in preimage


def test_namespace_is_pinned() -> None:
    """namespace가 바뀌면 과거 child identity가 전부 달라진다 — 상수로 고정한다."""
    assert str(CHILD_IDEMPOTENCY_NAMESPACE) == "2d3e71ea-3144-5fe1-a4e3-99c2c3ef7bfc"


def test_fingerprint_is_sha256_hex() -> None:
    identity = _derive()

    assert len(identity.request_fingerprint) == 64
    assert set(identity.request_fingerprint) <= set("0123456789abcdef")
