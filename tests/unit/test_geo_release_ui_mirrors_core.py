"""admin 화면 `/admin/ops/geo-releases`가 core·센서와 같은 값을 쓰는지 (T-GR-06, #1334 리뷰 S1).

화면은 API 사유 값(`replay_not_launchable_before_t_gr_08`) 하나로는 MOIS(센서 수동)와 replay
미지원을 가르지 못해 operation key 집합을 따로 들고 있다 — OpenAPI enum을 바꾸지 않으려는 것
(PinVi 재vendor 회피). 그 집합과 data_token 없음 경보 문구가 core·센서와 어긋나면 운영자는
틀린 안내를 본다. 그래서 TS 원문에서 값을 뽑아 정본과 대조한다
(`test_dagster_code_location_is_one_name.py`와 같은 꼴).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from kortravelmap.core.feature_operation import SENSOR_MANUAL_OPERATION_KEYS

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_FRONTEND = _ROOT / "packages" / "kor-travel-map-admin" / "frontend" / "src"
_API_TS = _FRONTEND / "api" / "geoReleases.ts"
_CLIENT_TSX = _FRONTEND / "app" / "admin" / "ops" / "geo-releases" / "geo-releases-client.tsx"
_SENSOR = (
    _ROOT
    / "packages"
    / "kor-travel-map-dagster"
    / "src"
    / "kortravelmap"
    / "dagster"
    / "geo_release_sensor.py"
)


def _ts_string_set(text: str, name: str) -> frozenset[str]:
    match = re.search(
        rf"export const {name}\b[^=]*=\s*new Set\(\[(?P<body>[^\]]*)\]\)", text, re.DOTALL
    )
    assert match is not None, f"{name} = new Set([...])를 찾지 못했다"
    values = re.findall(r'"([^"\\]*)"', match["body"])
    # 문자열이 아닌 원소(변수·spread)가 섞이면 이 검사가 보지 못한다 — 그 자체를 실패로 둔다.
    leftover = re.sub(r'"[^"\\]*"|[\s,]', "", match["body"])
    assert leftover == "", f"{name}에 문자열 literal이 아닌 원소가 있다: {leftover!r}"
    return frozenset(values)


def _ts_string_const(path: Path, name: str) -> str:
    match = re.search(rf'^const {name} = "([^"\\]*)";$', path.read_text(encoding="utf-8"), re.M)
    assert match is not None, f"{path.name}: const {name} = \"...\"를 찾지 못했다"
    return match[1]


def _python_constant(path: Path, name: str) -> object:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{path.name}: {name}이 없다")


def test_manual_operation_keys_are_the_core_set() -> None:
    keys = _ts_string_set(_API_TS.read_text(encoding="utf-8"), "MANUAL_OPERATION_KEYS")
    assert keys == SENSOR_MANUAL_OPERATION_KEYS
    assert SENSOR_MANUAL_OPERATION_KEYS  # 빈 집합끼리 같아 초록이 되지 않게


def test_missing_data_token_alert_is_the_sensor_skip_reason() -> None:
    sensor = _python_constant(_SENSOR, "NO_DATA_TOKEN_SKIP_REASON")
    assert isinstance(sensor, str)
    assert sensor
    assert _ts_string_const(_CLIENT_TSX, "MISSING_FINGERPRINT_TEXT") == sensor
    # 센서가 실제로 그 상수로 Skip한다(상수만 두고 다른 문장을 내면 위 대조가 무의미하다).
    assert 'SkipReason(f"{NO_DATA_TOKEN_SKIP_REASON}' in _SENSOR.read_text(encoding="utf-8")


_SAMPLE = (
    "export const MANUAL_OPERATION_KEYS: ReadonlySet<string> = new Set([\n"
    '  "a_job",\n'
    "]);"
)


def test_the_parser_sees_a_drift() -> None:
    """대조군 — 파서가 원소를 실제로 읽고, literal이 아닌 원소는 거부한다."""
    assert _ts_string_set(_SAMPLE, "MANUAL_OPERATION_KEYS") == frozenset({"a_job"})
    two = _SAMPLE.replace('"a_job"', '"a_job", "b_job"')
    assert _ts_string_set(two, "MANUAL_OPERATION_KEYS") == frozenset({"a_job", "b_job"})
    with pytest.raises(AssertionError, match="literal이 아닌"):
        _ts_string_set(_SAMPLE.replace('"a_job"', "...OTHER"), "MANUAL_OPERATION_KEYS")
