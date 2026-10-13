"""Feature advisory fence가 lock table을 고갈시키지 않고 교착을 만들지 않는지 센다(ADR-111).

## 왜

2026-10-12 n150 공용 PostgreSQL에서 ``feature.finalize_provider_curation_root``가 dataset
하나(11,820 Feature)를 완결하려고 Feature마다 ``pg_advisory_xact_lock('feature-write:<id>')``를
잡다가 SQLSTATE 53200(``out of shared memory``)으로 죽었다. advisory lock은 트랜잭션이 끝날
때까지 **cluster 전체가 함께 쓰는** lock table의 칸을 차지한다(``max_locks_per_transaction``
×연결 수). 같은 패턴이 프로시저 여덟 곳에 더 있었다.

406이 그것을 전역 gate ``feature-write-all`` 하나로 바꿨다. 대량 writer는 배타로 한 번,
단건 writer는 Feature 잠금 앞에서 공유로 잡는다. 이 파일은 그 계약이 head에서 깨지지
않았는지를 두 축으로 본다.

1. **개수.** ``feature-write:<id>``는 스칼라 하나에만 건다 — 루프 안이나 관계(표)를 훑는
   ``PERFORM ... FROM``이면 잠금 수가 데이터 크기를 따라 자란다. 그리고 그 앞에서 반드시
   gate를 든다(공유든 배타든) — 안 들면 대량 writer와 서로를 막지 않는다.
2. **순서.** 한 트랜잭션이 잡는 전역 잠금은
   ``kortravelmap:curation-import`` → ``feature-curation-write`` → ``feature-write-all``
   → ``feature-write:<id>`` → ``curation-catalog-write`` 순서를 지킨다. 중첩 ``CALL``을
   펼쳐서 본다 — ``finalize_provider_curation_root``는 ``curation-catalog-write``를 잡은 뒤
   ``materialize_theme_candidate_generation``을 부르고, 그 안이 gate를 다시 잡는다(이미
   들고 있으므로 재진입, 위반 아님). 공유로 든 gate를 배타로 올리는 것도 위반이다 — 둘이
   동시에 그러면 서로를 기다린다.

Python은 ``feature-write``를 잡지 않는다(``feature_repo.lock_feature_curation_write``는
``feature-curation-write``만 잡는다). 그것도 여기서 센다 — Python이 잡기 시작하면 이
검사가 보는 세계 밖에서 순서가 정해진다.

## 하한

검사가 대상을 놓치면 항진명제가 된다. 그래서 본 루틴 수에 하한을 걸고, 위반을 일부러
심은 본문으로 탐지기 자신이 빨개지는지도 본다.
"""

from __future__ import annotations

import pathlib
import re
from dataclasses import dataclass
from typing import Final

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HEAD_SCHEMA = _ROOT / "alembic" / "head-schema.sql"

#: 루틴 하나의 머리. 본문은 이 머리에서 그 루틴의 ``ALTER ... OWNER TO``까지다 — pg_dump는
#: 루틴마다 그 둘을 붙여 쓴다. 따옴표 태그(``$$``·``$_$``)나 ``LANGUAGE sql`` 모양에 기대지 않는다.
_ROUTINE = re.compile(r"^CREATE (?:PROCEDURE|FUNCTION) (?P<name>[a-z_]+\.[a-z_0-9]+)\(", re.MULTILINE)
_ROUTINE_END = re.compile(r"^ALTER (?:PROCEDURE|FUNCTION) ", re.MULTILINE)
_LOCK = re.compile(
    r"pg_advisory_xact_lock(?P<shared>_shared)?\(\s*hashtextextended\(\s*'(?P<key>[^']*)'"
)
_CALL = re.compile(r"\b(?:CALL|PERFORM|:=|FROM)\s+(?P<name>feature\.[a-z_0-9]+)\(")

#: 전역 잠금의 순서. 표에 없는 키(collection·plan별 키, m05 등)는 이 순서와 무관하다.
_RANK: Final[dict[str, int]] = {
    "kortravelmap:curation-import": 0,
    "feature-curation-write": 1,
    "feature-write-all": 2,
    "feature-write:": 3,
    "curation-catalog-write": 4,
}
_GATE: Final[str] = "feature-write-all"
_PER_FEATURE: Final[str] = "feature-write:"


@dataclass(frozen=True)
class _Lock:
    key: str
    shared: bool
    offset: int


def _routines(schema: str) -> dict[str, str]:
    routines: dict[str, str] = {}
    for match in _ROUTINE.finditer(schema):
        end = _ROUTINE_END.search(schema, match.end())
        assert end is not None, match["name"]
        assert match["name"] not in routines, f"duplicate routine {match['name']}"
        routines[match["name"]] = schema[match.end() : end.start()]
    return routines


def _statement(body: str, offset: int) -> str:
    end = body.find(";", offset)
    return body[offset : end if end != -1 else len(body)]


def _loop_depth(body: str, offset: int) -> int:
    prefix = body[:offset]
    opened = len(re.findall(r"(?<!END )\bLOOP\b", prefix))
    closed = len(re.findall(r"\bEND LOOP\b", prefix))
    return opened - closed


def _per_feature_violations(name: str, body: str) -> list[str]:
    """``feature-write:<id>`` 한 문장이 잠그는 개수가 데이터 크기를 따라 자라는가."""
    violations: list[str] = []
    gate_seen_at: int | None = None
    for match in _LOCK.finditer(body):
        key = match["key"]
        if key == _GATE and gate_seen_at is None:
            gate_seen_at = match.start()
        if key != _PER_FEATURE:
            continue
        statement = _statement(body, match.start())
        if re.search(r"\b(?:feature|provider_sync|ops)\.[a-z_]+", statement):
            violations.append(f"{name}: per-Feature lock over a relation scan")
        if _loop_depth(body, match.start()) > 0:
            violations.append(f"{name}: per-Feature lock inside a loop")
        if gate_seen_at is None:
            violations.append(f"{name}: per-Feature lock without the feature-write-all gate first")
    return violations


def _events(body: str) -> list[tuple[int, object]]:
    events: list[tuple[int, object]] = []
    for match in _LOCK.finditer(body):
        key = match["key"]
        rank_key = _PER_FEATURE if key.startswith(_PER_FEATURE) else key
        if rank_key in _RANK:
            events.append((match.start(), _Lock(rank_key, bool(match["shared"]), match.start())))
    for match in _CALL.finditer(body):
        events.append((match.start(), match["name"]))
    return sorted(events, key=lambda event: event[0])


def _order_violations(routines: dict[str, str]) -> list[str]:
    """중첩 호출을 펼친 잠금 열이 전역 순서와 공유→배타 승격 금지를 지키는가."""

    violations: list[str] = []

    def walk(
        name: str,
        held: dict[str, bool],
        stack: tuple[str, ...],
        origin: str,
    ) -> None:
        if name in stack or name not in routines:
            return
        for _offset, event in _events(routines[name]):
            if isinstance(event, str):
                walk(event, held, (*stack, name), origin)
                continue
            assert isinstance(event, _Lock)
            path = " → ".join((*stack, name))
            if event.key in held:
                if held[event.key] and not event.shared and event.key == _GATE:
                    violations.append(f"{origin}: shared→exclusive gate upgrade at {path}")
                continue
            top = max((_RANK[key] for key in held), default=-1)
            if _RANK[event.key] < top:
                above = sorted(key for key in held if _RANK[key] > _RANK[event.key])
                violations.append(f"{origin}: {event.key} after {above} at {path}")
            held[event.key] = event.shared

    for name in sorted(routines):
        walk(name, {}, (), name)
    return violations


def _python_feature_write_takers() -> list[str]:
    takers: list[str] = []
    for base in (_ROOT / "src", _ROOT / "packages"):
        for path in sorted(base.rglob("*.py")):
            if "tests" in path.parts:
                continue
            if "feature-write:" in path.read_text(encoding="utf-8") or (
                "feature-write-all" in path.read_text(encoding="utf-8")
            ):
                takers.append(str(path.relative_to(_ROOT)))
    return takers


def test_the_scan_sees_the_feature_write_takers() -> None:
    """하한을 '본 것'에 건다 — 루틴 추출이 깨지면 아래 검사들이 조용히 초록이 된다."""
    schema = _HEAD_SCHEMA.read_text(encoding="utf-8")
    routines = _routines(schema)
    textual = len(re.findall(r"^CREATE (?:PROCEDURE|FUNCTION) ", schema, re.MULTILINE))
    assert len(routines) == textual, "루틴 추출이 head의 CREATE 문 전부를 보지 못한다"
    per_feature = [name for name, body in routines.items() if "'feature-write:'" in body]
    gated = [name for name, body in routines.items() if f"'{_GATE}'" in body]
    assert len(per_feature) >= 6, per_feature
    assert len(gated) >= len(per_feature) + 9, gated


def test_per_feature_locks_are_scalar_and_gated() -> None:
    routines = _routines(_HEAD_SCHEMA.read_text(encoding="utf-8"))
    violations = [
        violation
        for name, body in sorted(routines.items())
        for violation in _per_feature_violations(name, body)
    ]
    assert not violations, (
        "Feature advisory 잠금 수가 데이터 크기를 따라 자란다(53200 lock table 고갈):\n  "
        + "\n  ".join(violations)
        + "\n\n대량 writer는 `pg_advisory_xact_lock(hashtextextended('feature-write-all', 0))` "
        "한 번, 단건 writer는 Feature 잠금 앞에 `pg_advisory_xact_lock_shared(...'feature-write-all'...)`(ADR-111)."
    )


def test_global_lock_order_holds_through_nested_calls() -> None:
    routines = _routines(_HEAD_SCHEMA.read_text(encoding="utf-8"))
    violations = sorted(set(_order_violations(routines)))
    assert not violations, (
        "전역 advisory 잠금 순서(import → feature-curation-write → feature-write-all → "
        "feature-write:<id> → curation-catalog-write)를 어긴다:\n  " + "\n  ".join(violations)
    )


def test_python_takes_no_feature_write_lock() -> None:
    assert _python_feature_write_takers() == [], (
        "Python이 Feature advisory 잠금을 잡기 시작했다. 이 검사는 SQL 루틴만 순서를 본다 — "
        "Python 쪽 잠금을 더하려면 그 트랜잭션의 전역 잠금 순서를 여기에 함께 실어라."
    )


_PLANTED_LOOP = """
  FOR v_feature_id IN SELECT link.feature_id FROM provider_sync.source_links AS link
  LOOP
    PERFORM pg_advisory_xact_lock_shared(hashtextextended('feature-write-all', 0));
    PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || v_feature_id, 0));
  END LOOP;
"""
_PLANTED_SCAN = """
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write-all', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || link.feature_id, 0))
  FROM provider_sync.source_links AS link ORDER BY link.feature_id;
"""
_PLANTED_UNGATED = """
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || p_feature_id, 0));
"""


def test_the_detectors_turn_red_on_planted_violations() -> None:
    """탐지기 자신이 빨개지는지 — 일부러 어긴 본문을 먹인다."""
    assert any("loop" in v for v in _per_feature_violations("planted", _PLANTED_LOOP))
    assert any("relation" in v for v in _per_feature_violations("planted", _PLANTED_SCAN))
    assert any("gate" in v for v in _per_feature_violations("planted", _PLANTED_UNGATED))
    assert _per_feature_violations(
        "fine",
        "  PERFORM pg_advisory_xact_lock_shared(hashtextextended('feature-write-all', 0));\n"
        "  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || p_feature_id, 0));\n",
    ) == []

    inverted = {
        "feature.catalog_then_gate": (
            "  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));\n"
            "  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write-all', 0));\n"
        ),
        "feature.shared_then_bulk": (
            "  PERFORM pg_advisory_xact_lock_shared(hashtextextended('feature-write-all', 0));\n"
            "  CALL feature.bulk(1);\n"
        ),
        "feature.bulk": (
            "  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write-all', 0));\n"
        ),
        "feature.reentrant": (
            "  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write-all', 0));\n"
            "  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));\n"
            "  CALL feature.bulk(1);\n"
        ),
    }
    found = _order_violations(inverted)
    assert any(v.startswith("feature.catalog_then_gate:") for v in found), found
    assert any(v.startswith("feature.shared_then_bulk:") and "upgrade" in v for v in found)
    assert not any(v.startswith("feature.reentrant:") for v in found), found
