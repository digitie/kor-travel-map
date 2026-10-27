"""Feature advisory fence가 lock table을 고갈시키지 않고 교착을 만들지 않는지 센다(ADR-111·115).

## 왜

2026-10-12 n150 공용 PostgreSQL에서 ``feature.finalize_provider_curation_root``가 dataset
하나(11,820 Feature)를 완결하려고 Feature마다 ``pg_advisory_xact_lock('feature-write:<id>')``를
잡다가 SQLSTATE 53200(``out of shared memory``)으로 죽었다. advisory lock은 트랜잭션이 끝날
때까지 **cluster 전체가 함께 쓰는** lock table의 칸을 차지한다(``max_locks_per_transaction``
×연결 수). 같은 패턴이 프로시저 여덟 곳에 더 있었다.

406이 그것을 전역 gate ``feature-write-all`` 하나로 바꿨다. 대량 writer는 배타로 한 번,
단건 writer는 Feature 잠금 앞에서 공유로 잡는다. 이 파일은 그 계약이 head에서 깨지지
않았는지를 세 축으로 본다.

1. **개수.** ``feature-write:<id>``는 스칼라 하나에만 건다 — 루프 안이나 관계(표)를 훑는
   ``PERFORM ... FROM``이면 잠금 수가 데이터 크기를 따라 자란다. 그리고 그 앞에서 반드시
   gate를 든다(공유든 배타든) — 안 들면 대량 writer와 서로를 막지 않는다.
2. **순서.** 한 트랜잭션이 잡는 전역 잠금은
   ``P`` → ``L`` → ``kortravelmap:curation-import`` → ``feature-curation-write`` →
   ``feature-write-all`` → ``feature-write:<id>`` → ``curation-catalog-write`` 순서를 지킨다.
   ``P``는 공통 protocol gate(``ops.lock_scoped_feature_write_protocol``, ADR-115)이고
   ``L``은 provider tracking lineage다(``ops.lock_provider_feature_tracking_protocol``: 인자가
   ``true``면 P EX 다음 L, ``false``면 L만. 433 WI-1부터 큐레이션을 확정하는 쓰기만 ``true``다).
   중첩 ``CALL``과 행 쓰기의 trigger 함수까지 펼쳐서 본다 — ``finalize_provider_curation_root``는
   ``curation-catalog-write``를 잡은 뒤 ``materialize_theme_candidate_generation``을 부르고, 그
   안이 gate를 다시 잡는다(이미 들고 있으므로 재진입, 위반 아님). 공유로 든 gate·P를 배타로
   올리는 것도 위반이다 — 둘이 동시에 그러면 서로를 기다린다.
3. **P는 맨 앞.** P를 처음 잡는 자리 앞에 ranked advisory, L, Feature 도메인(``feature``·
   ``provider_sync``) 행의 ``FOR UPDATE/SHARE``가 있으면 위반이다(433 WI-4). 명령·job·취소
   원장 행은 각자의 키로 순서가 정해지므로 세지 않는다. 단건·관리 writer의 regime 진입
   (``ops.lock_single_feature_writer_protocol``, 433 DC-1)은 epoch에 따라 P를 잡거나 잡지
   않으므로 **두 세계**(epoch=0: 진입이 아무것도 잡지 않음, epoch>0: P EX)를 모두 걷는다.
   epoch=0 세계에서는 P 없이 적재 fence(``curation-import``·``feature-curation-write``)를 행
   잠금 뒤에 잡는 것도 위반이다 — 적재는 P EX→fence→행 순서로 쥐고 있다.

Python은 ``feature-write``를 잡지 않는다(``feature_repo.lock_feature_curation_write``는
``feature-curation-write``만 잡는다). 그것도 여기서 센다 — Python이 잡기 시작하면 이
검사가 보는 세계 밖에서 순서가 정해진다. Python infra/API의 P·L helper 호출 순서도
같은 규칙(L 뒤 P, 행 잠금 뒤 P, 공유 뒤 배타 금지)으로 센다 — 같은 모듈 안의 호출만 펼친다.

## 하한

검사가 대상을 놓치면 항진명제가 된다. 그래서 본 루틴 수에 하한을 걸고, 위반을 일부러
심은 본문으로 탐지기 자신이 빨개지는지도 본다.
"""

from __future__ import annotations

import ast
import pathlib
import re
from dataclasses import dataclass
from typing import Final

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_HEAD_SCHEMA = _ROOT / "alembic" / "head-schema.sql"

#: 루틴 하나의 머리. 본문은 이 머리에서 그 루틴의 ``ALTER ... OWNER TO``까지다 — pg_dump는
#: 루틴마다 그 둘을 붙여 쓴다. 따옴표 태그(``$$``·``$_$``)나 ``LANGUAGE sql`` 모양에 기대지 않는다.
_ROUTINE = re.compile(
    r"^CREATE (?:PROCEDURE|FUNCTION) (?P<name>[a-z_]+\.[a-z_0-9]+)\(", re.MULTILINE
)
_ROUTINE_END = re.compile(r"^ALTER (?:PROCEDURE|FUNCTION) ", re.MULTILINE)
_LOCK = re.compile(
    r"pg_(?:try_)?advisory_xact_lock(?P<shared>_shared)?\(\s*hashtextextended\(\s*'(?P<key>[^']*)'"
)
_SCHEMAS = r"(?:feature|ops|provider_sync)"
#: 다른 루틴 호출. 스키마 셋 전부를 본다 — ``ops.transition_provider_cancellation_job_command``가
#: root 완결을 부르듯 다른 스키마에서 들어오는 경로가 있다.
_CALL = re.compile(rf"\b(?:CALL|PERFORM|:=|FROM|SELECT)\s+(?P<name>{_SCHEMAS}\.[a-z_0-9]+)\(")
#: 행 쓰기. 그 표의 trigger 함수가 같은 트랜잭션에서 돈다.
_WRITE = re.compile(
    rf"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?P<table>{_SCHEMAS}\.[a-z_0-9]+)\b"
)
_TRIGGER = re.compile(
    r"^CREATE (?:CONSTRAINT )?TRIGGER \S+ .*? ON (?P<table>[a-z_]+\.[a-z_0-9]+) .*?"
    r"EXECUTE FUNCTION (?P<function>[a-z_]+\.[a-z_0-9]+)\(",
    re.MULTILINE,
)

#: 전역 잠금의 순서. 표에 없는 키(collection·plan별 키, m05 등)는 이 순서와 무관하다.
#: ``P``(protocol gate)와 ``L``(tracking lineage)은 advisory 키가 아니라 아래 함수 호출로 센다.
_P: Final[str] = "P"
_L: Final[str] = "L"
_RANK: Final[dict[str, int]] = {
    _P: -2,
    _L: -1,
    "kortravelmap:curation-import": 0,
    "feature-curation-write": 1,
    "feature-write-all": 2,
    "feature-write:": 3,
    "curation-catalog-write": 4,
}
_GATE: Final[str] = "feature-write-all"
_PER_FEATURE: Final[str] = "feature-write:"
#: 적재(대량 writer)가 P EX 뒤 transaction 내내 쥐는 fence. P 없이 행 잠금 뒤에 잡으면 역순이다.
_LOAD_FENCES: Final[frozenset[str]] = frozenset(
    {"kortravelmap:curation-import", "feature-curation-write"}
)

#: P·L을 잡는 SQL 진입. 본문을 펼치지 않고 인자로 모드를 정한다 — tracking 진입 본문의
#: ``IF p_finalizing`` 분기를 정적으로 펼치면 leaf까지 P EX를 쥔 것으로 읽혀 위반을 놓친다.
_PROTOCOL_FUNCTION: Final[str] = "ops.lock_scoped_feature_write_protocol"
_TRACKING_FUNCTION: Final[str] = "ops.lock_provider_feature_tracking_protocol"
_REGIME_FUNCTION: Final[str] = "ops.lock_single_feature_writer_protocol"
_ENTRY_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {_PROTOCOL_FUNCTION, _TRACKING_FUNCTION, _REGIME_FUNCTION}
)
_ENTRY_CALL = re.compile(
    r"\b(?P<name>ops\.lock_scoped_feature_write_protocol"
    r"|ops\.lock_provider_feature_tracking_protocol"
    r"|ops\.lock_single_feature_writer_protocol)\((?P<args>[^)]*)\)"
)
#: L을 직접 잡는 bigint 키(``advisory_lock_key('kortravelmap:pipeline-lineage:mutation')``).
_LINEAGE_DIRECT = re.compile(r"pg_advisory_xact_lock\(\s*6832465333779826081\b")
_ROW_LOCK = re.compile(r"\bFOR\s+(?:NO\s+KEY\s+UPDATE|KEY\s+SHARE|UPDATE|SHARE)\b")
#: P보다 앞서면 안 되는 행 잠금은 Feature 도메인(source → link → Feature) 행이다. 명령·job·
#: 취소·검토 큐 같은 원장 행은 각자 키(domain command·L·검토 행)로 순서가 정해진다.
_DOMAIN_RELATION = re.compile(r"\b(?:FROM|JOIN)\s+(?:feature|provider_sync)\.[a-z_0-9]+")


def _domain_row_locks(sql: str) -> list[int]:
    """Feature 도메인 표를 읽는 문장의 ``FOR UPDATE/SHARE`` 위치."""
    offsets: list[int] = []
    for match in _ROW_LOCK.finditer(sql):
        start = sql.rfind(";", 0, match.start()) + 1
        if _DOMAIN_RELATION.search(sql, start, match.start()):
            offsets.append(match.start())
    return offsets
#: epoch=0(진입이 P를 잡지 않음)과 epoch>0(P EX) 두 세계.
_WORLDS: Final[tuple[str, ...]] = ("epoch0", "regime")


@dataclass(frozen=True)
class _Lock:
    key: str
    shared: bool
    offset: int


@dataclass(frozen=True)
class _Protocol:
    """P 진입. ``mode``는 ``EX``·``SH``·``?``(변수 인자)·``REGIME``(단건 regime 진입)."""

    mode: str
    offset: int


@dataclass(frozen=True)
class _Lineage:
    """L 획득. tracking 진입의 finalizing 인자는 앞에 P EX 사건을 따로 낸다.

    ``leaf``는 tracking 진입의 ``false``(장부 쓰기)다 — 진입 자신이 P를 쥔 채 오면
    ``ck_provider_tracking_prefix``로 거부한다(P EX와 L을 이미 쥔 재진입만 통과).
    """

    offset: int
    leaf: bool = False


@dataclass(frozen=True)
class _Row:
    offset: int


def _entry_events(name: str, args: str, offset: int) -> list[object]:
    argument = " ".join(args.split()).lower()
    if name == _REGIME_FUNCTION:
        return [_Protocol("REGIME", offset)]
    if name == _PROTOCOL_FUNCTION:
        mode = {"true": "EX", "false": "SH"}.get(argument, "?")
        return [_Protocol(mode, offset)]
    if argument == "false":
        return [_Lineage(offset, leaf=True)]
    # true, 또는 변수/식(``p_authoritative_snapshot_complete``·SUCCESS 완결 식)은 확정 쪽으로
    # 센다 — 앞의 조건(L·행 잠금 없음)이 가장 엄격하고, 같은 분기 안의 root 완결 CALL이
    # 재진입으로 읽힌다.
    return [_Protocol("EX", offset), _Lineage(offset)]


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
        # 어떤 FROM이든 집합이다 — 스키마 없는 표 이름(`FROM source_links`)이나 부분 질의도.
        if re.search(r"\bFROM\b", statement, re.IGNORECASE):
            violations.append(f"{name}: per-Feature lock over a relation scan")
        if _loop_depth(body, match.start()) > 0:
            violations.append(f"{name}: per-Feature lock inside a loop")
        if gate_seen_at is None:
            violations.append(f"{name}: per-Feature lock without the feature-write-all gate first")
    return violations


def _triggers(schema: str) -> dict[str, list[str]]:
    by_table: dict[str, list[str]] = {}
    for match in _TRIGGER.finditer(schema):
        by_table.setdefault(match["table"], []).append(match["function"])
    return by_table


def _events(body: str, triggers: dict[str, list[str]]) -> list[tuple[int, object]]:
    events: list[tuple[int, object]] = []
    for match in _WRITE.finditer(body):
        for function in triggers.get(match["table"], ()):
            events.append((match.start(), function))
    for match in _LOCK.finditer(body):
        key = match["key"]
        rank_key = _PER_FEATURE if key.startswith(_PER_FEATURE) else key
        if rank_key in _RANK:
            events.append((match.start(), _Lock(rank_key, bool(match["shared"]), match.start())))
    for match in _ENTRY_CALL.finditer(body):
        for event in _entry_events(match["name"], match["args"], match.start()):
            events.append((match.start(), event))
    for match in _LINEAGE_DIRECT.finditer(body):
        events.append((match.start(), _Lineage(match.start())))
    for offset in _domain_row_locks(body):
        events.append((offset, _Row(offset)))
    for match in _CALL.finditer(body):
        if match["name"] not in _ENTRY_FUNCTIONS:
            events.append((match.start(), match["name"]))
    # 같은 자리의 P와 L(확정 tracking 진입)은 넣은 순서(P 다음 L)를 지킨다 — 정렬은 안정적이다.
    return sorted(events, key=lambda event: event[0])


@dataclass
class _Held:
    """한 transaction이 지금까지 쥔 것 — 키별 모드(``EX``·``SH``·``?``)와 행 잠금 여부."""

    modes: dict[str, str]
    rows: bool = False


def _acquire(
    held: _Held, key: str, mode: str, *, origin: str, path: str, world: str
) -> list[str]:
    """``key``를 ``mode``로 잡을 때의 위반. 이미 쥐었으면 재진입이고 승격만 본다."""
    if key in held.modes:
        if key in (_GATE, _P) and held.modes[key] == "SH" and mode == "EX":
            return [f"{origin}: shared→exclusive {key} upgrade at {path} [{world}]"]
        return []
    violations: list[str] = []
    top = max((_RANK[name] for name in held.modes), default=-3)
    if _RANK[key] < top:
        above = sorted(name for name in held.modes if _RANK[name] > _RANK[key])
        violations.append(f"{origin}: {key} after {above} at {path} [{world}]")
    if key == _P and held.rows:
        violations.append(f"{origin}: P after a row lock at {path} [{world}]")
    if key in _LOAD_FENCES and held.rows and held.modes.get(_P) != "EX":
        violations.append(f"{origin}: {key} after a row lock without P EX at {path} [{world}]")
    held.modes[key] = mode
    return violations


def _leaf_violations(held: _Held, *, origin: str, path: str, world: str) -> list[str]:
    """tracking leaf 진입의 실행 시 거부(``ck_provider_tracking_prefix``)를 미리 본다.

    leaf는 P를 쥔 transaction에서 부르면 23514다. 확정 진입(P EX→L) 뒤의 재진입만 통과한다.
    433이 장부 쓰기를 leaf로 좁혔으므로, 같은 transaction에서 적재 fence(P EX)를 쥔 뒤
    장부를 쓰는 경로가 생기면 여기서 먼저 빨개진다.
    """
    protocol = held.modes.get(_P)
    if protocol is None or (protocol == "EX" and _L in held.modes):
        return []
    return [f"{origin}: leaf tracking L after P {protocol} without L at {path} [{world}]"]


def _order_violations(
    routines: dict[str, str], triggers: dict[str, list[str]] | None = None
) -> list[str]:
    """중첩 호출을 펼친 잠금 열이 전역 순서·P 맨 앞·승격 금지를 두 epoch 세계에서 지키는가."""

    violations: list[str] = []

    def walk(
        name: str,
        held: _Held,
        stack: tuple[str, ...],
        origin: str,
        world: str,
    ) -> None:
        if name in stack or name not in routines or name in _ENTRY_FUNCTIONS:
            return
        for _offset, event in _events(routines[name], triggers or {}):
            if isinstance(event, str):
                walk(event, held, (*stack, name), origin, world)
                continue
            path = " → ".join((*stack, name))
            context = {"origin": origin, "path": path, "world": world}
            if isinstance(event, _Row):
                held.rows = True
            elif isinstance(event, _Protocol):
                if event.mode == "REGIME" and world == "epoch0":
                    continue
                mode = "EX" if event.mode == "REGIME" else event.mode
                violations.extend(_acquire(held, _P, mode, **context))
            elif isinstance(event, _Lineage):
                if event.leaf:
                    violations.extend(_leaf_violations(held, **context))
                violations.extend(_acquire(held, _L, "EX", **context))
            else:
                assert isinstance(event, _Lock)
                mode = "SH" if event.shared else "EX"
                violations.extend(_acquire(held, event.key, mode, **context))

    for world in _WORLDS:
        for name in sorted(routines):
            walk(name, _Held({}), (), name, world)
    return violations


_GATE_BUSY_MESSAGE = "feature-write-all gate is busy"
"""root 완결이 gate를 잡지 못했을 때 procedure가 내는 오류 문구의 머리(ADR-112 결정 5).

reconcile 분류가 이 문구를 표지로 읽는다 — 잠금을 잡는 코드가 아니므로 이름 검사에서 뺀다."""


def _python_feature_write_takers() -> list[str]:
    takers: list[str] = []
    for base in (_ROOT / "src", _ROOT / "packages"):
        for path in sorted(base.rglob("*.py")):
            if "tests" in path.parts:
                continue
            source = path.read_text(encoding="utf-8").replace(_GATE_BUSY_MESSAGE, "")
            if "feature-write:" in source or "feature-write-all" in source:
                takers.append(str(path.relative_to(_ROOT)))
    return takers


# ── Python helper 순서(433 WI-4) ────────────────────────────────────────────────
#
# 같은 모듈 안의 함수 호출만 펼친다(다른 모듈의 repo 함수는 그 모듈을 볼 때 센다). 분기
# (``if``/``else``)는 각자 같은 시작 상태에서 걷고 합친다 — ``if finalizing: P EX else: L``이
# 순서 위반으로 읽히지 않게 한다. SQL 문자열 상수는 P·L 진입과 ``FOR UPDATE/SHARE``만 본다.

#: (폴더, 그 폴더의 dotted 이름). Dagster 코드는 client 인스턴스 메서드를 부르므로 정적으로
#: 펼 수 없다 — 그 아래 client·infra 함수는 여기서 직접 센다.
_API_SRC: Final[pathlib.Path] = _ROOT / "packages" / "kor-travel-map-api" / "src"
_PY_ROOTS: Final[tuple[tuple[pathlib.Path, str], ...]] = (
    (_ROOT / "src" / "kortravelmap", "kortravelmap"),
    (_API_SRC / "kortravelmap" / "api", "kortravelmap.api"),
)
#: tracking leaf 진입(``lock_provider_feature_tracking_protocol(false)``)의 L.
_PY_LEAF: Final[str] = "L:LEAF"
#: 이름만으로 모드가 정해지는 helper.
_PY_FIXED_HELPERS: Final[dict[str, tuple[str, ...]]] = {
    "lock_feature_curation_write": ("P:EX",),
    "lock_provider_feature_finalization": ("P:EX", "L"),
    "lock_provider_feature_tracking_leaf": (_PY_LEAF,),
    "lock_pipeline_lineage_mutation": ("L",),
    "lock_single_feature_writer_protocol": ("P:REGIME",),
}
#: keyword 인자로 모드가 정해지는 helper — (keyword, 참일 때, 거짓일 때). 변수면 참으로 센다.
_PY_KEYWORD_HELPERS: Final[dict[str, tuple[str, tuple[str, ...], tuple[str, ...]]]] = {
    "lock_feature_write_protocol": ("exclusive", ("P:EX",), ("P:SH",)),
    "lock_scoped_feature_write_protocol": ("exclusive", ("P:EX",), ("P:SH",)),
    "lock_provider_feature_tracking": ("finalizing", ("P:EX", "L"), (_PY_LEAF,)),
}
_PY_MAX_DEPTH: Final[int] = 6


def _py_callee(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _py_string(node: ast.AST | None, constants: dict[str, str]) -> str:
    """SQL로 쓰인 식의 상수 문자열(모듈 상수·리터럴·f-string 조각·``text()``)을 모은다."""
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id, "")
    if isinstance(node, ast.JoinedStr):
        return "".join(_py_string(value, constants) for value in node.values)
    if isinstance(node, ast.FormattedValue):
        return ""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _py_string(node.left, constants) + _py_string(node.right, constants)
    if isinstance(node, ast.Call) and _py_callee(node) == "text" and node.args:
        return _py_string(node.args[0], constants)
    return ""


def _py_sql_events(sql: str) -> list[str]:
    events: list[tuple[int, str]] = []
    for match in _ENTRY_CALL.finditer(sql):
        for event in _entry_events(match["name"], match["args"], match.start()):
            if isinstance(event, _Protocol):
                events.append((match.start(), "P:" + event.mode))
            else:
                assert isinstance(event, _Lineage)
                events.append((match.start(), _PY_LEAF if event.leaf else "L"))
    for match in _LINEAGE_DIRECT.finditer(sql):
        events.append((match.start(), "L"))
    for offset in _domain_row_locks(sql):
        events.append((offset, "ROW"))
    return [event for _offset, event in sorted(events, key=lambda item: item[0])]


@dataclass(frozen=True)
class _PyEvent:
    """``kind``는 ``P:EX``·``P:SH``·``P:REGIME``·``L``·``L:LEAF``·``ROW``다."""

    kind: str
    where: str


@dataclass(frozen=True)
class _PyBranch:
    """``if``의 두 갈래. 같은 시작 상태에서 따로 걷는다."""

    body: tuple[_PyEvent | _PyBranch | _PyTransaction, ...]
    orelse: tuple[_PyEvent | _PyBranch | _PyTransaction, ...]


@dataclass(frozen=True)
class _PyTransaction:
    """``async with ....begin():`` 블록 — 새 transaction이므로 빈 상태에서 걷는다."""

    body: tuple[_PyEvent | _PyBranch | _PyTransaction, ...]


_PyItems = tuple[_PyEvent | _PyBranch | _PyTransaction, ...]
#: ``session.commit()``·``rollback()`` 뒤에는 잠금이 풀린다.
_PY_RESET: Final[str] = "RESET"


@dataclass
class _PyModule:
    name: str
    constants: dict[str, str]
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef]
    memo: dict[tuple[str, _Bindings], _PyItems]
    #: 지역 이름 → (모듈 dotted 경로, 원래 이름). ``from x import f as g``.
    imported: dict[str, tuple[str, str]]
    #: 지역 별칭 → 모듈 dotted 경로. ``from kortravelmap.infra import feature_repo as repo``.
    aliases: dict[str, str]


_PY_CACHE: dict[str, _PyModule | None] = {}


def _py_module_path(dotted: str) -> pathlib.Path | None:
    parts = dotted.split(".")
    if parts[0] != "kortravelmap":
        return None
    if len(parts) > 1 and parts[1] == "api":
        base = _ROOT / "packages" / "kor-travel-map-api" / "src"
    elif len(parts) > 1 and parts[1] == "dagster":
        return None
    else:
        base = _ROOT / "src"
    candidate = base.joinpath(*parts)
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    if (candidate / "__init__.py").is_file():
        return candidate / "__init__.py"
    return None


def _py_load(dotted: str) -> _PyModule | None:
    if dotted not in _PY_CACHE:
        path = _py_module_path(dotted)
        _PY_CACHE[dotted] = _py_module(path, dotted=dotted) if path is not None else None
    return _PY_CACHE[dotted]


def _py_module(
    path: pathlib.Path, source: str | None = None, *, dotted: str | None = None
) -> _PyModule:
    tree = ast.parse(source if source is not None else path.read_text(encoding="utf-8"))
    package = dotted
    if dotted is not None and path.name != "__init__.py":
        package = dotted.rsplit(".", 1)[0]
    constants: dict[str, str] = {}
    functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    imported: dict[str, tuple[str, str]] = {}
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for target in targets:
                if isinstance(target, ast.Name) and value is not None:
                    text_value = _py_string(value, constants)
                    if text_value:
                        constants[target.id] = text_value
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions[node.name] = node
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            source_module = node.module
            if node.level and package:
                anchor = package.split(".")
                source_module = ".".join(anchor[: len(anchor) - node.level + 1] + [node.module])
            for alias in node.names:
                local = alias.asname or alias.name
                if _py_module_path(f"{source_module}.{alias.name}") is not None:
                    aliases[local] = f"{source_module}.{alias.name}"
                else:
                    imported[local] = (source_module, alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    aliases[alias.asname] = alias.name
    name = str(path.relative_to(_ROOT)) if path.is_absolute() else str(path)
    return _PyModule(name, constants, functions, {}, imported, aliases)


def _py_resolve(module: _PyModule, name: str, depth: int = 0) -> tuple[_PyModule, str] | None:
    """``name``이 가리키는 함수 정의(모듈, 이름). package 재수출은 몇 단계 따라간다."""
    if name in module.functions:
        return module, name
    if depth > 4 or name not in module.imported:
        return None
    source, original = module.imported[name]
    target = _py_load(source)
    if target is None:
        return None
    return _py_resolve(target, original, depth + 1)


#: 호출 지점에서 상수로 정해진 인자(이름 → 값). 정렬된 tuple이라 기억 키가 된다.
_Bindings = tuple[tuple[str, object], ...]
_PY_SIMPLE: Final[tuple[type, ...]] = (bool, int, str, type(None))


def _py_function_events(module: _PyModule, name: str, bindings: _Bindings = ()) -> _PyItems:
    """함수의 사건 열(인자 상수별 기억). 재귀는 빈 열로 끊는다."""
    key = (name, bindings)
    if key in module.memo:
        return module.memo[key]
    module.memo[key] = ()
    items = _py_block_items(module.functions[name].body, module, name, dict(bindings))
    module.memo[key] = items
    return items


_PyItem = _PyEvent | _PyBranch | _PyTransaction


def _py_value(node: ast.AST, bindings: dict[str, object]) -> tuple[bool, object]:
    """(알 수 있나, 값) — 상수 또는 상수로 묶인 이름만 안다."""
    if isinstance(node, ast.Constant) and isinstance(node.value, _PY_SIMPLE):
        return True, node.value
    if isinstance(node, ast.Name) and node.id in bindings:
        return True, bindings[node.id]
    return False, None


def _py_static_truth(test: ast.expr, bindings: dict[str, object]) -> bool | None:
    """``if`` 조건을 상수 인자로 정할 수 있으면 참/거짓, 아니면 ``None``."""
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _py_static_truth(test.operand, bindings)
        return None if inner is None else not inner
    if isinstance(test, ast.Compare) and len(test.ops) == 1:
        known_left, left = _py_value(test.left, bindings)
        known_right, right = _py_value(test.comparators[0], bindings)
        if not (known_left and known_right):
            return None
        op = test.ops[0]
        if isinstance(op, ast.Is):
            return left is right
        if isinstance(op, ast.IsNot):
            return left is not right
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        return None
    if isinstance(test, ast.BoolOp):
        values = [_py_static_truth(value, bindings) for value in test.values]
        if isinstance(test.op, ast.And):
            return False if False in values else (True if all(v is True for v in values) else None)
        return True if True in values else (False if all(v is False for v in values) else None)
    known, value = _py_value(test, bindings)
    return bool(value) if known else None


def _py_call_bindings(
    node: ast.Call, function: ast.FunctionDef | ast.AsyncFunctionDef, bindings: dict[str, object]
) -> _Bindings:
    """호출 인자와 기본값 중 상수로 정해지는 매개변수."""
    arguments = function.args
    positional = [*arguments.posonlyargs, *arguments.args]
    bound: dict[str, object] = {}
    with_default = positional[len(positional) - len(arguments.defaults) :]
    defaults = list(zip(with_default, arguments.defaults, strict=True))
    defaults += [
        (parameter, default)
        for parameter, default in zip(arguments.kwonlyargs, arguments.kw_defaults, strict=True)
        if default is not None
    ]
    for parameter, default in defaults:
        known, value = _py_value(default, {})
        if known:
            bound[parameter.arg] = value
    for parameter, argument in zip(positional, node.args, strict=False):
        known, value = _py_value(argument, bindings)
        if known:
            bound[parameter.arg] = value
        else:
            bound.pop(parameter.arg, None)
    for keyword in node.keywords:
        if keyword.arg is None:
            continue
        known, value = _py_value(keyword.value, bindings)
        if known:
            bound[keyword.arg] = value
        else:
            bound.pop(keyword.arg, None)
    return tuple(sorted(bound.items(), key=lambda item: item[0]))


def _py_call_items(
    node: ast.Call, module: _PyModule, where: str, bindings: dict[str, object]
) -> list[_PyItem]:
    callee = _py_callee(node)
    label = f"{where} → {callee or '?'}"
    if callee in ("commit", "rollback") and isinstance(node.func, ast.Attribute):
        return [_PyEvent(_PY_RESET, label)]
    if callee in _PY_FIXED_HELPERS:
        return [_PyEvent(kind, label) for kind in _PY_FIXED_HELPERS[callee]]
    if callee in _PY_KEYWORD_HELPERS:
        keyword, when_true, when_false = _PY_KEYWORD_HELPERS[callee]
        chosen = when_true
        for item in node.keywords:
            known, value = _py_value(item.value, bindings)
            if item.arg == keyword and known:
                chosen = when_true if value is True else when_false
        return [_PyEvent(kind, label) for kind in chosen]
    target: tuple[_PyModule, str] | None = None
    if isinstance(node.func, ast.Name):
        target = _py_resolve(module, node.func.id)
    elif (
        isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in module.aliases
    ):
        other = _py_load(module.aliases[node.func.value.id])
        if other is not None:
            target = _py_resolve(other, node.func.attr)
    if target is not None:
        owner, function = target
        call_bindings = _py_call_bindings(node, owner.functions[function], bindings)
        expanded: list[_PyItem] = []
        for item in _py_function_events(owner, function, call_bindings):
            if isinstance(item, _PyEvent):
                expanded.append(_PyEvent(item.kind, f"{where} → {item.where}"))
            else:
                expanded.append(item)
        return expanded
    return [
        _PyEvent(kind, label)
        for argument in node.args
        for kind in _py_sql_events(_py_string(argument, module.constants))
    ]


def _py_expression_items(
    node: ast.AST, module: _PyModule, where: str, bindings: dict[str, object]
) -> list[_PyItem]:
    """식 하나 안의 호출을 **안쪽 먼저**(인자 평가 순서) 센다."""
    if isinstance(node, ast.Lambda | ast.FunctionDef | ast.AsyncFunctionDef):
        return []
    items: list[_PyItem] = []
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Attribute):
            items.extend(_py_expression_items(node.func.value, module, where, bindings))
        for argument in [*node.args, *(item.value for item in node.keywords)]:
            if not isinstance(argument, ast.Call) or _py_callee(argument) != "text":
                items.extend(_py_expression_items(argument, module, where, bindings))
        items.extend(_py_call_items(node, module, where, bindings))
        return items
    for child in ast.iter_child_nodes(node):
        items.extend(_py_expression_items(child, module, where, bindings))
    return items


def _py_begins_transaction(statement: ast.stmt) -> bool:
    """``async with ....begin():``(savepoint ``begin_nested`` 제외)인가."""
    if not isinstance(statement, ast.With | ast.AsyncWith):
        return False
    return any(
        isinstance(item.context_expr, ast.Call) and _py_callee(item.context_expr) == "begin"
        for item in statement.items
    )


def _py_block_items(
    body: list[ast.stmt], module: _PyModule, where: str, bindings: dict[str, object]
) -> _PyItems:
    items: list[_PyItem] = []
    for statement in body:
        if isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            continue
        if _py_begins_transaction(statement):
            assert isinstance(statement, ast.With | ast.AsyncWith)
            items.append(
                _PyTransaction(_py_block_items(statement.body, module, where, bindings))
            )
            continue
        if isinstance(statement, ast.If):
            items.extend(_py_expression_items(statement.test, module, where, bindings))
            truth = _py_static_truth(statement.test, bindings)
            if truth is True:
                items.extend(_py_block_items(statement.body, module, where, bindings))
            elif truth is False:
                items.extend(_py_block_items(statement.orelse, module, where, bindings))
            else:
                items.append(
                    _PyBranch(
                        _py_block_items(statement.body, module, where, bindings),
                        _py_block_items(statement.orelse, module, where, bindings),
                    )
                )
            continue
        for child in ast.iter_child_nodes(statement):
            if not isinstance(child, ast.stmt | ast.ExceptHandler):
                items.extend(_py_expression_items(child, module, where, bindings))
        for field in ("body", "orelse", "handlers", "finalbody"):
            nested = getattr(statement, field, None)
            if not isinstance(nested, list):
                continue
            for element in nested:
                block = element.body if isinstance(element, ast.ExceptHandler) else [element]
                statements = [part for part in block if isinstance(part, ast.stmt)]
                items.extend(_py_block_items(statements, module, where, bindings))
    return tuple(items)


def _py_walk(
    items: _PyItems, held: _Held, origin: str, world: str
) -> tuple[list[str], list[_Held]]:
    """사건 열을 걷고 (위반, 끝 상태들)을 돌려준다. 분기마다 상태를 나눈다."""
    violations: list[str] = []
    states = [held]
    for item in items:
        if isinstance(item, _PyTransaction):
            # 새 transaction은 빈 상태에서 시작하고 바깥 상태를 바꾸지 않는다.
            found, _ends = _py_walk(item.body, _Held({}), origin, world)
            violations.extend(found)
            continue
        if isinstance(item, _PyBranch):
            next_states: list[_Held] = []
            for state in states:
                for branch in (item.body, item.orelse):
                    found, ends = _py_walk(
                        branch, _Held(dict(state.modes), state.rows), origin, world
                    )
                    violations.extend(found)
                    next_states.extend(ends)
            # 같은 상태는 합쳐 갈래 수가 폭증하지 않게 한다.
            unique = {(tuple(sorted(s.modes.items())), s.rows): s for s in next_states}
            states = list(unique.values())
            continue
        for state in states:
            context = {"origin": origin, "path": item.where, "world": world}
            if item.kind == _PY_RESET:
                state.modes.clear()
                state.rows = False
            elif item.kind == "ROW":
                state.rows = True
            elif item.kind.startswith("P:"):
                mode = item.kind[2:]
                if mode == "REGIME":
                    if world == "epoch0":
                        continue
                    mode = "EX"
                violations.extend(_acquire(state, _P, mode, **context))
            else:
                if item.kind == _PY_LEAF:
                    violations.extend(_leaf_violations(state, **context))
                violations.extend(_acquire(state, _L, "EX", **context))
    return violations, states


def _py_root_modules() -> list[_PyModule]:
    modules: list[_PyModule] = []
    for root, package in _PY_ROOTS:
        for path in sorted(root.rglob("*.py")):
            parts = list(path.relative_to(root).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            module = _py_load(".".join([package, *parts]))
            if module is not None:
                modules.append(module)
    return modules


def _python_order_violations(
    modules: list[_PyModule] | None = None,
) -> tuple[list[str], int]:
    """(위반, P/L helper를 부르는 함수 수)."""
    violations: list[str] = []
    takers = 0
    targets = modules if modules is not None else _py_root_modules()
    for module in targets:
        for name in sorted(module.functions):
            items = _py_function_events(module, name)
            if _py_has_entry(items):
                takers += 1
            origin = f"{module.name}::{name}"
            for world in _WORLDS:
                found, _ends = _py_walk(items, _Held({}), origin, world)
                violations.extend(found)
    return violations, takers


def _py_has_entry(items: _PyItems) -> bool:
    for item in items:
        if isinstance(item, _PyBranch):
            if _py_has_entry(item.body) or _py_has_entry(item.orelse):
                return True
        elif isinstance(item, _PyTransaction):
            if _py_has_entry(item.body):
                return True
        elif item.kind not in ("ROW", _PY_RESET):
            return True
    return False


def test_the_scan_sees_the_feature_write_takers() -> None:
    """하한을 '본 것'에 건다 — 루틴 추출이 깨지면 아래 검사들이 조용히 초록이 된다."""
    schema = _HEAD_SCHEMA.read_text(encoding="utf-8")
    routines = _routines(schema)
    textual = len(re.findall(r"^CREATE (?:PROCEDURE|FUNCTION) ", schema, re.MULTILINE))
    assert len(routines) == textual, "루틴 추출이 head의 CREATE 문 전부를 보지 못한다"
    per_feature = [name for name, body in routines.items() if "'feature-write:'" in body]
    gated = [name for name, body in routines.items() if f"'{_GATE}'" in body]
    assert len(per_feature) >= 6, per_feature
    assert len(gated) >= len(per_feature) + 8, gated
    triggers = _triggers(schema)
    assert sum(len(functions) for functions in triggers.values()) >= 100, "trigger 추출이 깨졌다"
    assert "feature.sync_concierge_catalog_after_observation" in triggers.get(
        "ops.curation_source_observation_receipts", []
    )
    # P·L 진입을 실제로 본다(433 WI-4). 433 head 기준 P 직접 진입 루틴 21개, tracking 진입 9개,
    # regime 진입 14개다 — 정규식이 낡으면 이 하한이 먼저 무너진다.
    entries = {
        name: {match["name"] for match in _ENTRY_CALL.finditer(body)}
        for name, body in routines.items()
        if name not in _ENTRY_FUNCTIONS
    }
    protocol = [name for name, seen in entries.items() if _PROTOCOL_FUNCTION in seen]
    tracking = [name for name, seen in entries.items() if _TRACKING_FUNCTION in seen]
    regime = [name for name, seen in entries.items() if _REGIME_FUNCTION in seen]
    assert len(protocol) >= 20, protocol
    assert len(tracking) >= 9, tracking
    assert len(regime) >= 14, regime
    _violations, python_takers = _python_order_violations()
    assert python_takers >= 20, python_takers


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
        "한 번, 단건 writer는 Feature 잠금 앞에 "
        "`pg_advisory_xact_lock_shared(...'feature-write-all'...)`(ADR-111)."
    )


def test_global_lock_order_holds_through_nested_calls() -> None:
    schema = _HEAD_SCHEMA.read_text(encoding="utf-8")
    violations = sorted(set(_order_violations(_routines(schema), _triggers(schema))))
    assert not violations, (
        "전역 잠금 순서(P → L → import → feature-curation-write → feature-write-all → "
        "feature-write:<id> → curation-catalog-write, P는 행 잠금보다 먼저)를 어긴다:\n  "
        + "\n  ".join(violations)
    )


def test_python_protocol_helpers_keep_the_same_order() -> None:
    violations, _takers = _python_order_violations()
    assert not violations, (
        "Python infra/API가 P·L helper를 순서에 어긋나게 부른다(L 뒤 P, 행 잠금 뒤 P, 공유 뒤 "
        "배타):\n  " + "\n  ".join(sorted(set(violations)))
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
_PLANTED_UNQUALIFIED_SCAN = """
  PERFORM pg_advisory_xact_lock_shared(hashtextextended('feature-write-all', 0));
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || l.feature_id, 0))
  FROM source_links AS l;
"""
_PLANTED_UNGATED = """
  PERFORM pg_advisory_xact_lock(hashtextextended('feature-write:' || p_feature_id, 0));
"""


def test_the_detectors_turn_red_on_planted_violations() -> None:
    """탐지기 자신이 빨개지는지 — 일부러 어긴 본문을 먹인다."""
    assert any("loop" in v for v in _per_feature_violations("planted", _PLANTED_LOOP))
    assert any("relation" in v for v in _per_feature_violations("planted", _PLANTED_SCAN))
    assert any(
        "relation" in v for v in _per_feature_violations("planted", _PLANTED_UNQUALIFIED_SCAN)
    )
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

    # trigger 경유: 표에 쓰면 그 trigger 함수의 잠금이 같은 트랜잭션에서 잡힌다.
    via_trigger = {
        "feature.catalog_then_observe": (
            "  PERFORM pg_advisory_xact_lock(hashtextextended('curation-catalog-write', 0));\n"
            "  INSERT INTO ops.observations (x) VALUES (1);\n"
        ),
        "feature.on_observation": (
            "  IF NOT pg_try_advisory_xact_lock(hashtextextended('feature-write-all', 0)) THEN\n"
        ),
    }
    trigger_schema = (
        "CREATE TRIGGER trg_obs AFTER INSERT ON ops.observations FOR EACH ROW "
        "EXECUTE FUNCTION feature.on_observation();\n"
    )
    found = _order_violations(via_trigger, _triggers(trigger_schema))
    assert any(v.startswith("feature.catalog_then_observe:") for v in found), found
    assert not any(
        v.startswith("feature.catalog_then_observe:") for v in _order_violations(via_trigger)
    )


#: 433 WI-4가 일부러 심는 P·L 위반 본문. 하나라도 초록이면 탐지기가 눈을 감은 것이다.
_PLANTED_PROTOCOL = {
    "feature.import_then_protocol": (
        "  PERFORM pg_advisory_xact_lock(hashtextextended('kortravelmap:curation-import', 0));\n"
        "  PERFORM ops.lock_scoped_feature_write_protocol(true);\n"
    ),
    "feature.lineage_then_protocol": (
        "  PERFORM ops.lock_provider_feature_tracking_protocol(false);\n"
        "  PERFORM ops.lock_scoped_feature_write_protocol(true);\n"
    ),
    "feature.leaf_then_finalizing": (
        "  PERFORM ops.lock_provider_feature_tracking_protocol(false);\n"
        "  PERFORM ops.lock_provider_feature_tracking_protocol(true);\n"
    ),
    "feature.shared_then_exclusive": (
        "  PERFORM ops.lock_scoped_feature_write_protocol(false);\n"
        "  PERFORM ops.lock_scoped_feature_write_protocol(true);\n"
    ),
    "feature.row_then_protocol": (
        "  PERFORM 1 FROM feature.features WHERE feature_id=p_id FOR UPDATE;\n"
        "  CALL feature.protocol_first(p_id);\n"
    ),
    "feature.protocol_first": "  PERFORM ops.lock_scoped_feature_write_protocol(true);\n",
    # regime 진입은 epoch>0에서 P EX다 — 행 잠금 뒤의 진입은 그 세계에서 위반이다.
    "feature.row_then_regime": (
        "  PERFORM 1 FROM feature.features WHERE feature_id=p_id FOR UPDATE;\n"
        "  PERFORM ops.lock_single_feature_writer_protocol();\n"
    ),
    # epoch=0에서는 regime 진입이 P를 잡지 않는다 — 행 잠금 뒤 적재 fence는 적재와 역순이다.
    "feature.regime_then_fence_after_rows": (
        "  PERFORM ops.lock_single_feature_writer_protocol();\n"
        "  PERFORM 1 FROM feature.features WHERE feature_id=p_id FOR UPDATE;\n"
        "  PERFORM pg_advisory_xact_lock(hashtextextended('feature-curation-write', 0));\n"
    ),
    # leaf 진입은 P를 쥔 채 오면 실행 시 23514다(``ck_provider_tracking_prefix``).
    "feature.fence_then_leaf": (
        "  PERFORM ops.lock_scoped_feature_write_protocol(true);\n"
        "  PERFORM ops.lock_provider_feature_tracking_protocol(false);\n"
    ),
    "feature.shared_lineage_then_leaf": (
        "  PERFORM ops.lock_scoped_feature_write_protocol(false);\n"
        "  PERFORM pg_advisory_xact_lock(6832465333779826081::bigint);\n"
        "  PERFORM ops.lock_provider_feature_tracking_protocol(false);\n"
    ),
    "feature.regime_then_leaf": (
        "  PERFORM ops.lock_single_feature_writer_protocol();\n"
        "  PERFORM ops.lock_provider_feature_tracking_protocol(false);\n"
    ),
    # 정상: 확정 진입(P EX→L) 뒤의 leaf·같은 진입 재진입·regime 진입 뒤 행 잠금.
    "feature.finalizing_then_leaf": (
        "  PERFORM ops.lock_provider_feature_tracking_protocol(true);\n"
        "  PERFORM ops.lock_provider_feature_tracking_protocol(false);\n"
        "  PERFORM 1 FROM ops.import_jobs WHERE job_id=p_id FOR UPDATE;\n"
    ),
    "feature.regime_then_rows": (
        "  PERFORM ops.lock_single_feature_writer_protocol();\n"
        "  PERFORM 1 FROM feature.features WHERE feature_id=p_id FOR UPDATE;\n"
        "  CALL feature.nested_regime(p_id);\n"
    ),
    "feature.nested_regime": "  PERFORM ops.lock_single_feature_writer_protocol();\n",
}


def test_the_protocol_detectors_turn_red_on_planted_violations() -> None:
    found = _order_violations(_PLANTED_PROTOCOL)

    def hits(origin: str) -> list[str]:
        return [v for v in found if v.startswith(origin + ":")]

    assert any("P after" in v for v in hits("feature.import_then_protocol")), found
    assert any("P after ['L']" in v for v in hits("feature.lineage_then_protocol")), found
    assert any("P after ['L']" in v for v in hits("feature.leaf_then_finalizing")), found
    assert any("upgrade" in v for v in hits("feature.shared_then_exclusive")), found
    assert any("row lock" in v for v in hits("feature.row_then_protocol")), found
    regime_rows = hits("feature.row_then_regime")
    assert regime_rows, found
    assert all(v.endswith("[regime]") for v in regime_rows), regime_rows
    fence = hits("feature.regime_then_fence_after_rows")
    assert any("without P EX" in v and v.endswith("[epoch0]") for v in fence), found
    assert not any(v.endswith("[regime]") for v in fence), fence
    assert any("leaf tracking L after P EX" in v for v in hits("feature.fence_then_leaf")), found
    assert any(
        "leaf tracking L after P SH" in v for v in hits("feature.shared_lineage_then_leaf")
    ), found
    regime_leaf = hits("feature.regime_then_leaf")
    assert regime_leaf, found
    assert all(v.endswith("[regime]") for v in regime_leaf), regime_leaf
    for fine in ("feature.finalizing_then_leaf", "feature.regime_then_rows"):
        assert not hits(fine), hits(fine)


_PLANTED_PYTHON = '''
_LOCK_ROW_SQL = "SELECT 1 FROM feature.features WHERE feature_id = :id FOR UPDATE"


async def leaf_then_finalizing(session):
    await lock_provider_feature_tracking_leaf(session)
    await lock_provider_feature_finalization(session)


async def row_then_fence(session):
    await session.execute(text(_LOCK_ROW_SQL), {"id": 1})
    await lock_feature_curation_write(session)


async def shared_then_exclusive(session):
    await lock_scoped_feature_write_protocol(session, exclusive=False)
    await lock_feature_write_protocol(session, exclusive=True)


async def _nested_finalizing(session):
    await lock_provider_feature_tracking(session, finalizing=True)


async def lineage_then_nested(session):
    await lock_pipeline_lineage_mutation(session)
    await _nested_finalizing(session)


async def branch_is_not_an_order(session, finalizing):
    if finalizing:
        await lock_provider_feature_finalization(session)
    else:
        await lock_provider_feature_tracking_leaf(session)
    await session.execute(text(_LOCK_ROW_SQL), {"id": 1})


async def regime_then_rows(session):
    await lock_single_feature_writer_protocol(session)
    await session.execute(text(_LOCK_ROW_SQL), {"id": 1})


async def separate_transactions(session):
    async with session.begin():
        await lock_provider_feature_tracking_leaf(session)
    async with session.begin():
        await lock_provider_feature_finalization(session)


async def after_commit(session):
    await lock_provider_feature_tracking_leaf(session)
    await session.commit()
    await lock_provider_feature_finalization(session)


async def inside_one_transaction(session):
    async with session.begin():
        await lock_provider_feature_tracking_leaf(session)
        await lock_provider_feature_finalization(session)


async def regime_then_row_then_fence(session):
    # epoch=0에서 regime 진입은 P를 잡지 않는다 — 뒤의 fence(P EX)는 행 잠금 뒤가 된다.
    await lock_single_feature_writer_protocol(session)
    await session.execute(text(_LOCK_ROW_SQL), {"id": 1})
    await lock_feature_curation_write(session)


async def _maybe_fence(session, exclusive=False):
    if exclusive:
        await lock_feature_curation_write(session)
    else:
        await lock_scoped_feature_write_protocol(session, exclusive=False)


async def shared_then_literal_shared_branch(session):
    await lock_scoped_feature_write_protocol(session, exclusive=False)
    await _maybe_fence(session, exclusive=False)


async def fence_then_ledger(session):
    await lock_feature_curation_write(session)
    await lock_provider_feature_tracking(session, finalizing=False)


async def finalization_then_ledger(session):
    await lock_provider_feature_finalization(session)
    await lock_provider_feature_tracking_leaf(session)
'''


def test_the_python_detector_turns_red_on_planted_violations() -> None:
    module = _py_module(pathlib.Path("planted.py"), _PLANTED_PYTHON)
    found, takers = _python_order_violations([module])
    assert takers >= 6, takers

    def hits(name: str) -> list[str]:
        return [v for v in found if v.startswith(f"planted.py::{name}:")]

    assert any("P after ['L']" in v for v in hits("leaf_then_finalizing")), found
    assert any("row lock" in v for v in hits("row_then_fence")), found
    assert any("upgrade" in v for v in hits("shared_then_exclusive")), found
    assert any("P after ['L']" in v for v in hits("lineage_then_nested")), found
    assert any("P after ['L']" in v for v in hits("inside_one_transaction")), found
    fence = hits("regime_then_row_then_fence")
    assert any("row lock" in v and v.endswith("[epoch0]") for v in fence), found
    assert not any(v.endswith("[regime]") for v in fence), fence
    assert any("leaf tracking L after P EX" in v for v in hits("fence_then_ledger")), found
    for fine in (
        "finalization_then_ledger",
        "branch_is_not_an_order",
        "regime_then_rows",
        "separate_transactions",
        "after_commit",
        # 상수 인자(exclusive=False)로 정해지는 분기는 배타 갈래를 걷지 않는다.
        "shared_then_literal_shared_branch",
    ):
        assert not hits(fine), (fine, found)
