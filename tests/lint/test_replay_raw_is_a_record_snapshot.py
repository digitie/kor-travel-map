"""replay 변환기는 저장된 ``raw_data``에 있는 필드만 읽는다 — 구조 golden (ADR-109 결정 7, T-GR-08).

replay는 ``source_records.raw_data``를 provider 모델로 되살려 **같은 변환기**에 넣는다. 그것이
fetch와 같은 bundle을 내려면 변환기가 record에서 읽는 필드가 전부 ``raw_data``에 들어 있어야
한다. 실모델 golden(``packages/kor-travel-map-dagster/tests/test_source_replay.py``)은 provider
라이브러리가 있어야 도는데 CI에는 ``providers`` extra가 없다 — 이 lint가 같은 성질을 provider
설치 없이 본다.

검사(표준데이터 replay 변환기마다):

1. 변환기 본문이 record 인자를 **속성 접근으로만** 쓴다 — 통째로 다른 함수에 넘기면 그 안에서 읽는
   필드를 이 검사가 볼 수 없으니 실패한다(보지 못한 것을 초록으로 세지 않는다).
2. 읽는 속성 ⊆ ``raw_data`` dict literal의 키.
3. ``raw_data`` 키 ⊆ 핀된 provider 모델의 필드(``_provider_surface.json``) —
   ``model_validate(raw)``가 그 키를 받는다.

대조군: 같은 검사를 MOIS 변환기에 대면 실패한다(record를 ``_build_address``·``_facility_info``에
통째로 넘기고, raw에 없는 필드를 읽는다) — MOIS가 replay 목록에 없는 이유다.

보지 못하는 것: 값의 **타입 왕복**(``str(float)`` → float 등)은 provider pydantic 동작이다 — 실모델
golden과, 런타임에 hash가 다르면 적재 전에 실패하는 ``apply_replay_provenance``가 맡는다.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from kortravelmap.core.feature_operation import REPLAY_RECORDS_RESOURCES

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVIDERS = REPO_ROOT / "src" / "kortravelmap" / "providers"


@dataclass(frozen=True)
class _Converter:
    module: str
    function: str
    record_param: str
    provider_model: str


#: 표준데이터 replay resource → 변환기(record 한 건을 bundle로)와 핀된 provider 모델.
#: fileData(``datagokr_file_data_records``)는 ``raw_data`` = 원본 row 전체라 이 검사가 필요 없다.
_CONVERTERS: dict[str, _Converter] = {
    "datagokr_cultural_festivals": _Converter(
        "standard_data", "_item_to_bundle", "item", "datagokr.models.PublicCulturalFestival"
    ),
    "standard_museums": _Converter(
        "standard_data", "_museum_to_bundle", "item", "datagokr.models.PublicMuseumArtGallery"
    ),
    "standard_tourist_attractions": _Converter(
        "standard_data", "_tourist_to_bundle", "item", "datagokr.models.PublicTouristAttraction"
    ),
    "standard_parking_lots": _Converter(
        "standard_data", "_parking_to_bundle", "item", "datagokr.models.PublicParkingLot"
    ),
    "standard_special_streets": _Converter(
        "standard_data", "_special_street_to_bundle", "item", "datagokr.models.PublicSpecialStreet"
    ),
}
_RAW_ROW_RESOURCES = frozenset({"datagokr_file_data_records"})

_MOIS = _Converter("mois", "license_record_to_bundle", "record", "mois.db.PlaceRecord")


def _function(converter: _Converter) -> ast.AsyncFunctionDef | ast.FunctionDef:
    tree = ast.parse((PROVIDERS / f"{converter.module}.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            and node.name == converter.function
        ):
            return node
    raise AssertionError(f"{converter.module}.{converter.function} 없음")


def _raw_keys(fn: ast.AST) -> set[str]:
    keys: set[str] = set()
    for node in ast.walk(fn):
        target = None
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        if (
            isinstance(target, ast.Name)
            and target.id == "raw_data"
            and isinstance(value, ast.Dict)
        ):
            keys |= {k.value for k in value.keys if isinstance(k, ast.Constant)}
    return keys


def _record_uses(fn: ast.AST, param: str) -> tuple[set[str], int]:
    """(속성으로 읽은 이름, 속성 접근이 아닌 사용 횟수)."""
    attributes: set[str] = set()
    parents = {child: parent for parent in ast.walk(fn) for child in ast.iter_child_nodes(parent)}
    bare = 0
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and node.id == param and isinstance(node.ctx, ast.Load):
            parent = parents.get(node)
            if isinstance(parent, ast.Attribute) and parent.value is node:
                attributes.add(parent.attr)
            else:
                bare += 1
    return attributes, bare


def _model_fields(model: str) -> set[str]:
    manifest = json.loads((PROVIDERS / "_provider_surface.json").read_text(encoding="utf-8"))
    for provider in manifest["providers"].values():
        classes = provider["classes"]
        if model in classes:
            return set(classes[model]["members"])
    raise AssertionError(f"provider surface에 {model} 없음")


def _violations(converter: _Converter) -> list[str]:
    fn = _function(converter)
    raw = _raw_keys(fn)
    read, bare = _record_uses(fn, converter.record_param)
    problems: list[str] = []
    if not raw:
        problems.append("raw_data dict literal 없음")
    if not read:
        problems.append("record 속성 읽기 0건 — 검사가 아무것도 보지 못했다")
    if bare:
        problems.append(f"record를 속성 접근 밖에서 {bare}회 쓴다(다른 함수에 통째로 넘김)")
    if missing := read - raw:
        problems.append(f"raw_data에 없는 필드를 읽는다: {sorted(missing)}")
    if converter.provider_model.startswith("datagokr.") and (
        unknown := raw - _model_fields(converter.provider_model)
    ):
        problems.append(f"provider 모델에 없는 raw 키: {sorted(unknown)}")
    return problems


def test_every_replay_resource_is_covered() -> None:
    assert set(_CONVERTERS) | _RAW_ROW_RESOURCES == set(REPLAY_RECORDS_RESOURCES.values())


@pytest.mark.parametrize("resource", sorted(_CONVERTERS))
def test_replay_converter_reads_only_what_raw_data_keeps(resource: str) -> None:
    assert _violations(_CONVERTERS[resource]) == []


def test_mois_converter_fails_the_same_check() -> None:
    """대조군 — MOIS가 replay 목록에 없는 이유를 같은 검사로 보인다."""
    problems = _violations(_MOIS)
    assert any("통째로" in problem for problem in problems), problems
    assert "feature_place_mois_licenses_job" not in REPLAY_RECORDS_RESOURCES
