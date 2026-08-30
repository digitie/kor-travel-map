"""provider ``Protocol`` ↔ 핀된 실모델 적합성 게이트.

## 왜 필요한가

Map은 ADR-006에 따라 provider wrapper를 만들지 않고 입력 shape을 structural
``Protocol``로만 선언한다. 런타임 결선은 ``importlib.import_module()`` +
``cast(Any, ...)``이므로 mypy도 import-linter도 이 결박을 보지 못한다. 게다가
provider 라이브러리는 ``[project.optional-dependencies] providers`` extra라
CI(``pip install -e ".[dev]"``)에 **설치조차 되지 않는다.**

그 결과 ``HeritageDetail.manager`` 삭제는 정적 검사·단위 테스트를 전부 green으로
통과한 채 live/Dagster 경로에서만 터졌다. 단위 테스트가 provider 실모델이 아니라
자체 fake dataclass를 쓰기 때문이다 — fake는 provider가 바뀌어도 같이 바뀌지 않는다.

## 무엇을 보는가

``_provider_surface.json``은 **핀된 exact SHA**의 provider 소스에서 뽑은 클래스별
공개 멤버 집합이다(``scripts/generate_provider_surface_manifest.py``). 따라서 이
게이트는 네트워크도 provider 설치도 없이 실제 provider 표면을 본다.

세 가지를 강제한다.

1. **manifest가 핀과 일치한다.** 핀만 올리고 manifest를 재생성하지 않으면 실패한다.
   manifest가 조용히 낡을 수 없다.
2. **모든 Protocol이 선언돼 있다.** ``providers/``의 ``Protocol`` 전수가
   ``PROVIDER_MODEL_BINDINGS`` 또는 ``PROTOCOLS_WITHOUT_PROVIDER_MODEL`` 중
   정확히 한쪽에만 있어야 한다. 새 Protocol이 선언 없이 끼어들 수 없다.
3. **결박된 Protocol의 모든 멤버가 실모델에 있다.** 이것이 본체다.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest

from kortravelmap.providers._source_models import (
    PROTOCOLS_WITHOUT_PROVIDER_MODEL,
    PROVIDER_MODEL_BINDINGS,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVIDERS_DIR = REPO_ROOT / "src" / "kortravelmap" / "providers"
MANIFEST_PATH = PROVIDERS_DIR / "_provider_surface.json"

_PIN_RE = re.compile(
    r'"(?P<dist>python-[a-z0-9-]+)\s*@\s*git\+https://github\.com/digitie/'
    r"(?P<repo>[a-z0-9-]+)\.git@(?P<sha>[0-9a-f]{40})\""
)


def _manifest() -> dict[str, object]:
    assert MANIFEST_PATH.exists(), (
        f"{MANIFEST_PATH.relative_to(REPO_ROOT)}가 없다 — "
        "`python scripts/generate_provider_surface_manifest.py`로 생성할 것"
    )
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _declared_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _PIN_RE.search(line)
        if match is not None:
            pins[match.group("dist")] = match.group("sha")
    return pins


def _protocol_members(node: ast.ClassDef) -> set[str]:
    """``Protocol``이 요구하는 공개 멤버 이름."""
    members: set[str] = set()
    for statement in node.body:
        target: str | None = None
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            target = statement.target.id
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            target = statement.name
        if target is not None and not target.startswith("_"):
            members.add(target)
    return members


def _base_names(node: ast.ClassDef) -> list[str]:
    """``class X(Protocol)`` / ``class X(typing.Protocol)`` / ``class X(Y)``의 base 이름."""
    names: list[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def _discover_protocols() -> dict[str, set[str]]:
    """``providers/`` 안의 모든 ``Protocol``을 reflection으로 찾는다.

    선언 표를 읽는 것이 아니라 소스를 훑는다 — 표에 빠진 Protocol이 있으면
    그 사실 자체가 드러나야 하기 때문이다.

    **상속을 편다.** ``OpinetStationDetailItem``은 ``OpinetStationItem``을 상속해
    ``prices`` 하나만 직접 선언하지만, 실모델은 상속분(``uni_id``/``name``/``lon`` …)도
    만족해야 한다. 직접 선언만 보면 그 7개가 결박 대상 클래스에서 검증되지 않은 채
    green이 된다(적대 리뷰).

    Protocol 판정도 ``Protocol``/``typing.Protocol``과 **다른 Protocol의 하위**까지
    본다 — 그러지 않으면 Protocol을 상속한 Protocol이 "선언 전수" 검사를 조용히
    빠져나간다.
    """
    declared: dict[str, tuple[set[str], list[str]]] = {}
    for path in sorted(PROVIDERS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                declared[node.name] = (_protocol_members(node), _base_names(node))

    def is_protocol(name: str, seen: frozenset[str] = frozenset()) -> bool:
        if name == "Protocol":
            return True
        if name in seen or name not in declared:
            return False
        return any(
            is_protocol(base, seen | {name}) for base in declared[name][1]
        )

    found: dict[str, set[str]] = {}
    for path in sorted(PROVIDERS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = _base_names(node)
            if not any(is_protocol(base) for base in bases):
                continue
            members = set(_protocol_members(node))
            pending = [b for b in bases if b != "Protocol"]
            seen_bases: set[str] = {node.name}
            while pending:
                base = pending.pop()
                if base in seen_bases or base not in declared:
                    continue
                seen_bases.add(base)
                members |= declared[base][0]
                pending.extend(declared[base][1])
            found[f"{path.stem}.{node.name}"] = members
    return found


def test_manifest_matches_declared_pins() -> None:
    """manifest의 provider 핀이 ``pyproject.toml`` 선언과 같아야 한다.

    이 검사가 없으면 핀만 올리고 manifest를 그대로 두어 게이트가 **낡은 표면을
    보면서 통과**할 수 있다. 그 상태의 green은 아무것도 관측하지 않은 green이다.
    """
    manifest = _manifest()
    providers = manifest["providers"]
    assert isinstance(providers, dict)
    declared = _declared_pins()

    stale: list[str] = []
    for dist, entry in sorted(providers.items()):
        assert isinstance(entry, dict)
        assert dist in declared, f"manifest에 있으나 pyproject 핀이 사라진 provider: {dist}"
        if entry["pinned_sha"] != declared[dist]:
            recorded = str(entry["pinned_sha"])[:8]
            stale.append(f"{dist}: manifest={recorded} pyproject={declared[dist][:8]}")

    assert not stale, (
        "provider 표면 manifest가 핀과 어긋난다 — "
        "`python scripts/generate_provider_surface_manifest.py`로 재생성할 것:\n  "
        + "\n  ".join(stale)
    )

    # 역방향도 본다. 이 검사가 없으면 새 provider를 핀하면서 표면 추출 대상에
    # 넣는 것을 잊어도 게이트가 아무 말도 하지 않는다 — 실제로 python-mcst-api가
    # 13개 핀 중 12개만 검사받는 상태였고, manifest만 훑는 검사는 그것을 볼 수 없었다.
    exempt = manifest.get("providers_without_protocols", {})
    assert isinstance(exempt, dict)
    uncovered = sorted(set(declared) - set(providers) - set(exempt))
    assert not uncovered, (
        "핀은 있으나 표면 대조도 면제 선언도 없는 provider다 — `Protocol` 결박이 "
        "있으면 PROVIDER_PACKAGES에, 없으면 사유와 함께 PROVIDERS_WITHOUT_PROTOCOLS에 "
        f"넣고 manifest를 재생성할 것: {uncovered}"
    )
    silent = sorted(name for name, reason in exempt.items() if not str(reason).strip())
    assert not silent, f"사유가 비어 있는 provider 면제: {silent}"


def test_every_protocol_is_declared_exactly_once() -> None:
    """``providers/``의 모든 Protocol이 두 표 중 정확히 한쪽에만 있어야 한다."""
    discovered = set(_discover_protocols())
    bound = set(PROVIDER_MODEL_BINDINGS)
    unbound = set(PROTOCOLS_WITHOUT_PROVIDER_MODEL)

    both = sorted(bound & unbound)
    assert not both, f"두 표에 동시에 선언된 Protocol: {both}"

    undeclared = sorted(discovered - bound - unbound)
    assert not undeclared, (
        "선언되지 않은 Protocol이 있다 — provider 실모델과 결박되면 "
        "PROVIDER_MODEL_BINDINGS에, 아니면 사유와 함께 "
        f"PROTOCOLS_WITHOUT_PROVIDER_MODEL에 넣을 것: {undeclared}"
    )

    phantom = sorted((bound | unbound) - discovered)
    assert not phantom, f"선언은 있으나 실제로 없는 Protocol(이름 변경/삭제?): {phantom}"


def test_unbound_protocols_carry_a_reason() -> None:
    """결박 면제에는 반드시 근거가 있어야 한다 — 빈 사유는 면제가 아니라 은폐다."""
    empty = sorted(k for k, v in PROTOCOLS_WITHOUT_PROVIDER_MODEL.items() if not v.strip())
    assert not empty, f"사유가 비어 있는 결박 면제: {empty}"


@pytest.mark.parametrize(
    "protocol_key",
    sorted(PROVIDER_MODEL_BINDINGS),
    ids=sorted(PROVIDER_MODEL_BINDINGS),
)
def test_bound_protocol_members_exist_on_pinned_model(protocol_key: str) -> None:
    """결박된 Protocol의 모든 멤버가 핀된 provider 실모델 표면에 있어야 한다.

    ``HeritageDetail.manager`` 삭제 같은 변경을 핀 상향 시점에 잡는 것이 목적이다.
    """
    model_path = PROVIDER_MODEL_BINDINGS[protocol_key]
    required = _discover_protocols()[protocol_key]
    assert required, f"{protocol_key}: 멤버가 없는 Protocol은 결박을 검증하지 못한다"

    manifest = _manifest()
    providers = manifest["providers"]
    assert isinstance(providers, dict)

    package = model_path.split(".", 1)[0]
    for entry in providers.values():
        assert isinstance(entry, dict)
        if entry["package"] != package:
            continue
        classes = entry["classes"]
        assert isinstance(classes, dict)
        assert model_path in classes, (
            f"{protocol_key}: 결박 대상 {model_path}가 핀된 provider 표면에 없다 "
            f"(이름 변경/삭제 여부를 확인할 것)"
        )
        surface = classes[model_path]
        assert isinstance(surface, dict)
        available = set(surface["members"])  # type: ignore[arg-type]
        missing = sorted(required - available)
        assert not missing, (
            f"{protocol_key} → {model_path}: 실모델에 없는 Protocol 멤버 {missing}. "
            f"provider가 필드를 지웠거나 이름을 바꿨다면 Protocol과 사용처를 "
            f"함께 재결박할 것. (평탄화하지 못한 외부 base: "
            f"{surface['external_bases']})"
        )
        return

    pytest.fail(f"{protocol_key}: manifest에 패키지 {package}가 없다")


def test_contract_table_pins_match_pyproject() -> None:
    """``provider-contract.md`` §12 표의 sha가 ``pyproject.toml`` 핀과 같아야 한다.

    표는 사람이 provider 상태를 확인하는 유일한 1장 정본인데, 두 번이나 실제 핀의
    **조상**을 가리킨 채 방치됐다(knps ``@5e88fb4``, airkorea ``@22996a4``).
    낡은 표는 없는 표보다 나쁘다 — 대조했다고 착각하게 만든다.

    표는 축약 sha를 쓰므로 접두사 일치로 본다.
    """
    contract = (REPO_ROOT / "docs" / "architecture" / "provider-contract.md").read_text(
        encoding="utf-8"
    )
    declared = _declared_pins()

    row_re = re.compile(
        r"^\| (?P<dist>python-[a-z0-9-]+) \| `@(?P<sha>[0-9a-f]{7,40})`",
        re.MULTILINE,
    )
    documented = {m.group("dist"): m.group("sha") for m in row_re.finditer(contract)}
    assert documented, "provider-contract.md §12에서 핀 행을 하나도 읽지 못했다"

    mismatched = [
        f"{dist}: 표=@{sha} pyproject=@{declared[dist][: len(sha)]}"
        for dist, sha in sorted(documented.items())
        if dist in declared and not declared[dist].startswith(sha)
    ]
    assert not mismatched, (
        "provider-contract.md §12 표와 pyproject.toml 핀이 어긋난다:\n  " + "\n  ".join(mismatched)
    )

    undocumented = sorted(set(declared) - set(documented))
    assert not undocumented, f"pyproject에 핀이 있으나 §12 표에 행이 없다: {undocumented}"
