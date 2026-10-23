"""역지오코딩 asset은 저장값 재사용 helper를 거친다(ADR-116).

payload·좌표·geo 토큰이 그대로인 행의 geo 왕복을 건너뛰는 자리는 ``_transform_reusing_geo`` 한
곳이다. asset이 변환을 그 helper 없이 ``reverse_geocoder=``로 직접 부르면 그 dataset은 run마다 모든
좌표를 다시 역지오코딩한다 — 기능은 그대로라 아무 검사도 빨개지지 않는다. 그래서 여기서 막는다.

예외는 이유가 있는 둘뿐이다 — MOIS(ADR-108의 자기 재개형 경로)와 concierge(변환이 격리 목록을 채우는
부수효과가 있고 ``observe()``의 후보 시군구를 admin evidence로 싣는다 — 두 번 돌릴 수도, 저장값으로
재현할 수도 없다).
"""

from __future__ import annotations

import ast
import pathlib
from typing import Final

_DAGSTER_PKG: Final = (
    pathlib.Path(__file__).resolve().parents[2]
    / "packages"
    / "kor-travel-map-dagster"
    / "src"
    / "kortravelmap"
    / "dagster"
)
#: dagster 패키지의 모든 모듈을 본다 — 새 모듈에서 helper 없이 부르는 것도 잡는다.
_MODULES: Final = tuple(sorted(path.name for path in _DAGSTER_PKG.glob("*.py")))
_HELPER: Final = "_transform_reusing_geo"
_ALLOWED: Final[dict[str, str]] = {
    "run_feature_place_mois_licenses": "ADR-108 재개형 chunk 적재가 자기 선조회·건너뛰기를 갖는다",
    "run_feature_place_kor_travel_concierge_youtube": (
        "격리 목록 부수효과 + observe() 후보 증거 — 두 번 변환할 수 없다"
    ),
    "load_mois_license_records_chunked": "ADR-108 MOIS 재개형 chunk 적재(자기 선조회)",
    "load_offline_upload_op": "사람이 올린 일회성 파일 — 이전 적재가 없다",
}


def _passes_live_geocoder(call: ast.Call) -> bool:
    return any(
        keyword.arg == "reverse_geocoder"
        and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is None)
        for keyword in call.keywords
    )


def _offenders(tree: ast.Module) -> list[str]:
    found: list[str] = []
    for function in tree.body:
        if not isinstance(function, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if function.name == _HELPER or function.name in _ALLOWED:
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Call) or not _passes_live_geocoder(node):
                continue
            if isinstance(node.func, ast.Name) and node.func.id == _HELPER:
                continue
            found.append(f"{function.name}: {ast.unparse(node.func)}(…)")
    return found


def test_every_reverse_geocoding_transform_goes_through_the_reuse_helper() -> None:
    offenders: list[str] = []
    seen_helper_calls = 0
    for name in _MODULES:
        tree = ast.parse((_DAGSTER_PKG / name).read_text(encoding="utf-8"))
        offenders += [f"{name} {entry}" for entry in _offenders(tree)]
        seen_helper_calls += sum(
            1
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == _HELPER
        )
    assert not offenders, (
        "역지오코딩 변환을 저장값 재사용 helper 없이 부른다(ADR-116) — "
        f"`{_HELPER}(context, transform, records, …)`로 감쌀 것: {offenders}"
    )
    # 항진명제 방지 — helper 호출이 사라지면 위 검사는 아무것도 보지 않는다.
    assert seen_helper_calls >= 18, seen_helper_calls


def test_the_allowlist_still_names_real_run_functions() -> None:
    names = {
        node.name
        for name in _MODULES
        for node in ast.parse((_DAGSTER_PKG / name).read_text(encoding="utf-8")).body
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }
    assert set(_ALLOWED) <= names, sorted(set(_ALLOWED) - names)


def test_a_direct_call_is_caught() -> None:
    """의도적 빨강 — helper를 빼고 직접 부르는 asset을 잡는다."""
    sample = ast.parse(
        "async def run_feature_x(context):\n"
        "    return await convert(rows, reverse_geocoder=_reverse_geocoder(context))\n"
        "async def run_feature_y(context):\n"
        "    return await _transform_reusing_geo(\n"
        "        context, convert, rows, reverse_geocoder=_reverse_geocoder(context)\n"
        "    )\n"
        "async def run_feature_z(context):\n"
        "    return await convert(rows, reverse_geocoder=None)\n"
    )
    assert _offenders(sample) == ["run_feature_x: convert(…)"]
