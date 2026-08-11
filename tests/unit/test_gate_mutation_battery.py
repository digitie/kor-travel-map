"""감사기가 **실제로 무엇을 잡는지** 변이로 확인한다(게이트에 걸린 판).

`scripts/audit-mutation-battery.py`는 지금까지 사람이 손으로 돌리는 도구였다.
9라운드 적대 리뷰가 그 대가를 실증했다 — 하네스가 깨져 통제군이 실패하는 상태로
"32/32 검출"이 출력됐고, 그 숫자가 머지 근거로 인용됐다. 아무도 안 돌리는 도구의
출력은 검증이 아니다.

그래서 여기에 건다. CI unit job이 곧 이 배터리를 돌린다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_BATTERY = Path(__file__).resolve().parents[2] / "scripts" / "audit-mutation-battery.py"


def _load_battery() -> object:
    spec = importlib.util.spec_from_file_location("ktm_audit_battery", _BATTERY)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_control_group_passes_without_any_mutation() -> None:
    """변이 없는 사본에서 감사기가 통과해야 한다.

    이게 깨지면 ``caught = returncode != 0``이 **항상 참**이 되어 검출률이
    감사기와 무관한 상수가 된다 — 실제로 그 상태였다.
    """

    battery = _load_battery()
    assert battery._control_group_is_clean(), (  # type: ignore[attr-defined]
        "하네스가 깨졌다 — 변이 없이도 감사기가 실패한다. 이 상태의 검출률은 근거가 "
        "되지 못한다."
    )


def test_every_mutation_is_detected() -> None:
    """설계한 변이가 **전부** 잡혀야 한다. 하나라도 생존하면 그 부류는 무방비다."""

    battery = _load_battery()
    survivors = [
        label
        for label, spec in battery.MUTATIONS.items()  # type: ignore[attr-defined]
        if not battery._run(label, *spec, quiet=True)  # type: ignore[attr-defined]
    ]
    assert survivors == [], "감사기를 통과하는 변이가 있다:\n" + "\n".join(survivors)
