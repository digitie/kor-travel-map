"""모든 provider fetcher가 요청을 **세거나, 왜 못 세는지 적거나** 하게 한다.

2026-09-13 적대 리뷰가 blocker를 잡았다. 분자 배선(:mod:`~.upstream_requests`)은
멀쩡했는데 **커버리지가 없었다** — 계수기는 asset 35개 전부에서 열리는데 세는 자리는
셋뿐이었다. 그래서 OpiNet처럼 수천 건을 쓰는 경로가 ``upstream_requests_min: 0``을
냈고, 하필 그것이 저장소가 유일하게 **한도 대비 run 예산을 코드에 박아 둔**
provider였다(``_OPINET_RUN_CALL_BUDGET`` vs 무료키 300/일, #545).

그때 이 저장소가 갖고 있던 구조 검사는 초록이었다. 그 검사는
``asset이 계수 범위 안에서 도는가``를 물었는데, wrapper가 **항상** 열므로
항진명제였다 — 같은 실패 형태를 그날 네 번째로 반복한 것이다.

**그래서 여기서는 asset이 아니라 fetcher를 센다.** 요청을 실제로 보내는 것은
fetcher이고, 그것이 계수 호출을 (직접이든 헬퍼를 통해서든) 갖는지는 소스에서
유도할 수 있다. 못 세는 것은 :data:`_UNCOUNTABLE`에 **이유와 함께** 적어야 한다 —
목록에 이름을 올리는 일 자체가 결정의 기록이다.

**KMA(기상청)·에어코리아는 이 게이트의 대상이 아니다**(2026-09-14 지시).
:data:`_EXCLUDED_FROM_EVALUATION`에 이유와 함께 적혀 있다 — 둘 다 자동 적재가 꺼져
있고 큐 경계가 그 결정을 강제하며, **날씨 관련 로직 자체를 걷어낼 예정**이다.
계수 호출은 코드에 그대로 있다(빼는 것은 평가이지 계측이 아니다).

**이 검사가 볼 수 없는 것**(2차 적대 리뷰가 실측으로 열거했다. 적어 두는 이유는
다음 사람이 초록을 과신하지 않게 하려는 것이다):

- **도달 가능성.** ``if False:`` 아래든, 죽은 중첩 함수 안이든, 루프 **밖** 1회든
  호출 노드가 있기만 하면 초록이다. 이 구멍은 정적으로 막기 어렵다 — 대신
  ``packages/kor-travel-map-dagster/tests/test_upstream_request_numerator.py``가
  **손으로 박은 자리마다 가짜 client로 N번 부르고 ``counter == N``을 결박한다.**
  거기가 효과를 보는 자리고, 여기는 "자리가 있는가"만 본다.
- **실행 모드.** 어떤 모드에서만 계수 경로를 타는 fetcher는 :data:`_PARTIALLY_COUNTED`에
  적는다 — 유도만으로는 구분되지 않는 거짓 양성이다.
- **attribute 호출의 receiver 타입.** ``x.spend()``는 어느 ``x``인지 모른다. 그래서
  폐쇄에 쓰는 키는 ``(모듈, qualname)``이고, 이름이 여러 정의로 갈리면
  :func:`test_counting_helper_names_are_unambiguous`가 빨개진다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_PKG = _ROOT / "packages" / "kor-travel-map-dagster" / "src" / "kortravelmap" / "dagster"
_NOTE = "note_upstream_request"

#: 이 층에서 요청 수를 셀 수 **없는** fetcher와 그 이유.
#:
#: 여기 있는 fetcher의 asset은 ``upstream_requests_min``을 내보내지 않는다 —
#: 0을 내보내지 않는다는 뜻이다. "세지 않았다"와 "0번 요청했다"는 다른 사실이고,
#: 틀린 0은 읽는 사람을 멈추게 하지 못한다.
#:
#: 2차 적대 리뷰가 이 목록을 두 칸 줄였다. 종전 사유 두 개가 **provider 소스와
#: 어긋났다** — ``file_data.iter_pages``는 public이었고, event 창은 14개월로 알 수
#: 있었다. 못 센다는 선언은 값싸고, 값싼 선언은 계측을 대체하기 시작한다.
_UNCOUNTABLE: dict[str, str] = {
    "fetch_krairport_airports": (
        "번들 정적 데이터 — credential 없이 동작하고 upstream 요청이 없다."
    ),
    "fetch_mois_license_records": "로컬 sqlite 파일을 읽는다 — upstream 요청이 없다.",
}


#: **부분 계측** — 어떤 실행 모드에서는 세고 어떤 모드에서는 못 세는 fetcher.
#:
#: 전이 폐쇄는 "이 fetcher가 세는 함수를 부르는가"만 본다. 그래서 모드에 따라
#: 계수 경로를 타지 않는 fetcher도 "센다"로 판정된다 — 거짓 양성이다. 그 사실을
#: 목록으로 남겨 다음 사람이 유도 결과를 과신하지 않게 한다.
#:
#: 여기 있는 fetcher는 계측된 모드에서는 값을 내고, 아닌 모드에서는 key 없이
#: 나간다(계약상 0으로 위장하지 않는다). 아래 하한은 이들을 **계측된 쪽으로
#: 세지 않는다** — 부분 계측으로 강등하는 것이 공짜면 그것이 값싼 도피로가 된다.
_PARTIALLY_COUNTED: dict[str, str] = {
    "fetch_opinet_stations": (
        "`low_top_area` 모드는 `_OpinetCallBudget.spend()`로 정확히 세지만, "
        "`bbox`/`poi_cache_target` 모드의 `iter_stations_in_bbox`는 provider가 "
        "bbox를 격자로 덮으며 셀마다 호출한다 — 셀 수 계산이 provider private이라 "
        "이 층에서는 셀 수 없다."
    ),
    "fetch_opinet_station_price_details": (
        "`low_top_area` 모드는 예산기가 정확히 센다(완전). `bbox`/`poi_cache_target` "
        "모드는 상세 조회(`get_station_detail`)가 uni_id마다 1건이라 그쪽은 세지만, "
        "그 uni_id를 찾아온 enumerate는 세지 못한다 — 즉 **key가 실리되 실제 사용량보다 "
        "작다.** 같은 모드의 `fetch_opinet_stations`가 값을 아예 안 내는 것과 다르다."
    ),
    "sync_mois_source_db": (
        "큐 runner 경로와 Phase A op 경로는 센다. **asset 경로는 못 센다** — "
        "`_sync_then_fetch_mois_license_records`가 Dagster resource init 시점에 "
        "`ensure_mois_source_db_fresh`를 부르는데, resource init은 compute보다 "
        "먼저 돌아 계수 범위 밖이다. generator로 미루면 범위 안으로 들어오지만 "
        "동기 다운로드가 async compute의 이벤트 루프를 막는다(#617이 그래서 "
        "`to_thread`로 보냈다)."
    ),
}


#: fetcher의 우주를 **이름으로 박는다**.
#:
#: 종전에는 ``fetch_`` 접두사로 유도했다. 그러면 개명 한 번으로 선언 없이 면제되고,
#: ``>= 30`` 가드는 그것을 보지 못한다(2차 리뷰). 명시 목록이면 추가·삭제·개명이
#: 전부 이 파일의 편집으로 나타나 리뷰에 보인다.
_EXPECTED_FETCHERS: frozenset[str] = frozenset(
    {
        "fetch_datagokr_cultural_festivals",
        "fetch_datagokr_file_data_records",
        "fetch_khoa_beaches",
        "fetch_knps_geometry_records",
        "fetch_knps_point_records",
        "fetch_kor_travel_concierge_youtube_features",
        "fetch_krairport_airports",
        "fetch_krex_rest_area_fuel_prices",
        "fetch_krex_rest_area_weather",
        "fetch_krex_rest_areas",
        "fetch_krex_traffic_notices",
        "fetch_krforest_arboretums",
        "fetch_krforest_dulle_trails",
        "fetch_krforest_landslide_forecast_issues",
        "fetch_krforest_mountain_trails",
        "fetch_krforest_mountain_weather",
        "fetch_krforest_recreation_forests",
        "fetch_krforest_wildfire_risk_forecast",
        "fetch_krheritage_events",
        "fetch_krheritage_items",
        "fetch_mcst_culture_records",
        "fetch_mois_license_records",
        "fetch_opinet_station_price_details",
        "fetch_opinet_stations",
        "fetch_seoul_open_data_bookstores",
        "fetch_standard_museums",
        "fetch_standard_parking_lots",
        "fetch_standard_special_streets",
        "fetch_standard_tourist_attractions",
        "fetch_visitkorea_festival_events",
        # fetcher 이름은 아니지만 **같은 종류의 upstream 다운로드**라 게이트 안에
        # 둔다. MOIS Phase A는 slug마다 LOCALDATA 파일을 받는다 — 접두사로 유도하면
        # 이것이 통째로 게이트 밖이었다(2·3차 리뷰).
        "sync_mois_source_db",
        # 이름에 밑줄이 앞서지만 upstream을 직접 부르는 자리다.
        "_fetch_krex_traffic_notice_snapshot",
    }
)

#: **쿼터 평가 대상이 아닌** 진입점과 그 이유.
#:
#: 2026-09-14 지시로 KMA(기상청)·에어코리아가 빠졌다. 둘 다 2026-09-09부터 자동
#: 적재가 꺼져 있고(`DISABLED_FEATURE_LOAD_SCHEDULES`), 큐 경계가 그 결정을 강제한다
#: (`DISABLED_FEATURE_LOAD_OPERATION_KEYS`). 그리고 **날씨 관련 로직 자체를 걷어낼
#: 예정**이라, 그때까지 이 게이트가 그 코드를 붙들고 있을 이유가 없다.
#:
#: 이름을 조용히 지우지 않고 목록으로 남기는 이유는 다른 목록과 같다 — **이름을
#: 올리는 일 자체가 결정의 기록**이고, 지우면 "왜 빠졌는지"가 diff 밖으로 사라진다.
#: 계수 호출은 코드에 그대로 있다(빼는 것은 평가이지 계측이 아니다).
_EXCLUDED_FROM_EVALUATION: dict[str, str] = {
    "fetch_kma_weather_alerts": "기상청 — 2026-09-14 지시로 쿼터 평가 대상에서 제외.",
    "fetch_airkorea_air_quality": "에어코리아 — 2026-09-14 지시로 평가 대상에서 제외.",
    "fetch_airkorea_stations": "에어코리아 — 2026-09-14 지시로 평가 대상에서 제외.",
    "_fetch_nowcast_rows": "기상청 격자 콜백 — 평가 대상 provider가 아니다.",
    "_fetch_short_forecast_rows": "기상청 격자 콜백 — 평가 대상 provider가 아니다.",
    "_fetch_ultra_short_forecast_rows": "기상청 격자 콜백 — 평가 대상 provider가 아니다.",
}

#: 접두사에는 걸리지만 **진입점이 아닌** 이름과 그 이유.
#:
#: 우주 유도를 접두사로 넓히면(`_fetch_` 등) 콜백·헬퍼까지 딸려 온다. 그것들을
#: 계측하라고 요구하면 **이중 계수**가 난다 — 부르는 쪽이 이미 세고 있기 때문이다.
#: 그래서 빼되, 빼는 이유를 적는다. 목록에 이름을 올리는 일 자체가 결정의 기록이다.
_NOT_AN_ENTRYPOINT: dict[str, str] = {}

#: 진입점 후보를 훑을 때 쓰는 이름 접두사.
#:
#: ``fetch_`` 하나만 훑으면 **fetcher가 아닌 진입점**(MOIS Phase A sync, KMA 격자
#: job)이 새로 생겨도 아무도 보지 못한다. 3차 리뷰가 그 구멍을 짚었다.
_ENTRYPOINT_PREFIXES: tuple[str, ...] = (
    "fetch_",
    "_fetch_",
    "sync_",
    "download_",
)

#: **완전 계측 수를 직접 박는다.**
#:
#: 종전 하한은 ``len(fetchers) - len(_UNCOUNTABLE) - len(_PARTIALLY_COUNTED)``였다.
#: 그것은 래칫이 아니라 **항등식**이다 — 면제를 하나 늘리면 좌변과 우변이 함께
#: 줄어 아무것도 빨개지지 않는다(3차 리뷰). 수를 따로 박으면 면제를 늘리는 편집이
#: 반드시 이 숫자를 낮추는 편집을 동반하고, 그 한 줄이 리뷰에 보인다.
_EXPECTED_FULLY_COUNTED: int = 26


def _module_trees() -> dict[str, ast.Module]:
    return {
        str(path.relative_to(_PKG)): ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(_PKG.rglob("*.py"))
    }


def _called_names(node: ast.AST) -> set[str]:
    """이 함수 본문이 부르는 이름. 중첩 함수의 호출은 세지 않는다.

    중첩 함수는 자기 키를 따로 갖는다 — 본문에 끌어넣으면 정의만 되고 호출되지
    않는 죽은 중첩 함수의 계수가 부모에게 흘러든다.
    """

    names: set[str] = set()
    stack: list[ast.AST] = list(ast.iter_child_nodes(node))
    while stack:
        child = stack.pop()
        if isinstance(child, ast.AsyncFunctionDef | ast.FunctionDef | ast.Lambda):
            continue
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
        stack.extend(ast.iter_child_nodes(child))
    return names


def _definitions() -> dict[tuple[str, str], set[str]]:
    """``(모듈, qualname) -> 부르는 이름``.

    키가 모듈+qualname인 이유는 bare name으로 뭉치면 **다른 모듈의 동명 함수**가
    서로의 계수를 물려받기 때문이다(2차 리뷰 실측: 486개 정의가 443개 키로 뭉쳤다).
    """

    definitions: dict[tuple[str, str], set[str]] = {}
    for module, tree in _module_trees().items():
        stack: list[tuple[ast.AST, str]] = [(tree, "")]
        while stack:
            node, prefix = stack.pop()
            for child in ast.iter_child_nodes(node):
                if isinstance(child, ast.AsyncFunctionDef | ast.FunctionDef):
                    qualname = f"{prefix}{child.name}"
                    definitions[(module, qualname)] = _called_names(child)
                    stack.append((child, f"{qualname}."))
                elif isinstance(child, ast.ClassDef):
                    stack.append((child, f"{prefix}{child.name}."))
                else:
                    stack.append((child, prefix))
    return definitions


def _leaf(qualname: str) -> str:
    return qualname.rsplit(".", 1)[-1]


def _definitions_per_leaf() -> dict[str, int]:
    """qualname의 **마지막 조각**별 정의 수. 호출측은 이 조각만 보인다."""

    counts: dict[str, int] = {}
    for _, qualname in _definitions():
        counts[_leaf(qualname)] = counts.get(_leaf(qualname), 0) + 1
    return counts


def _counting_definitions() -> set[tuple[str, str]]:
    """``note_upstream_request``를 **직접 또는 간접으로** 부르는 정의.

    전이 폐쇄를 도는 이유는 대부분의 fetcher가 헬퍼를 통해 세기 때문이다
    (``iter_paginated_items``·``_iter_krforest_records``·``_OpinetCallBudget.spend``).
    호출측에는 bare name밖에 없으므로 폐쇄는 leaf 이름으로 전파하되, 키는
    ``(모듈, qualname)``으로 유지해 어느 정의가 세는지를 구분한다.
    """

    definitions = _definitions()
    counting = {key for key, calls in definitions.items() if _NOTE in calls}
    changed = True
    while changed:
        changed = False
        leaves = {_leaf(qualname) for _, qualname in counting}
        for key, calls in definitions.items():
            if key not in counting and calls & leaves:
                counting.add(key)
                changed = True
    return counting


def _counting_leaf_names() -> set[str]:
    return {_leaf(qualname) for _, qualname in _counting_definitions()}


def _fetchers() -> list[str]:
    leaves = {_leaf(qualname) for _, qualname in _definitions()}
    return sorted(_EXPECTED_FETCHERS & leaves)


def test_the_declared_universe_matches_the_source() -> None:
    """개명·삭제·추가가 **이 파일의 편집**을 강제한다.

    접두사 유도로는 ``fetch_`` 를 떼는 것만으로 선언 없이 게이트 밖으로 나갈 수
    있었다(2차 리뷰). 명시 목록이면 그 이동이 diff에 남는다.
    """

    leaves = {_leaf(qualname) for _, qualname in _definitions()}
    missing = sorted(_EXPECTED_FETCHERS - leaves)
    assert missing == [], (
        f"선언된 fetcher가 소스에 없다: {missing}. 개명·삭제됐다면 "
        "`_EXPECTED_FETCHERS`를 함께 고쳐라 — 목록에서 조용히 빠지는 것이 "
        "이 게이트의 가장 값싼 도피로다."
    )
    extra = sorted(
        leaf
        for leaf in leaves
        if leaf.startswith(_ENTRYPOINT_PREFIXES)
        and leaf not in _EXPECTED_FETCHERS
        and leaf not in _NOT_AN_ENTRYPOINT
        and leaf not in _EXCLUDED_FROM_EVALUATION
    )
    assert extra == [], (
        f"목록에 없는 새 진입점이 있다: {extra}. `_EXPECTED_FETCHERS`에 올리고, "
        "세거나 못 세는 이유를 선언해라."
    )


def test_the_universe_cannot_shrink_without_editing_this_file() -> None:
    """목록에서 **조용히 빠지는** 것을 막는 래칫.

    ``extra`` 쪽 유도는 접두사에 걸려 있다. 그래서 접두사에 걸리지 않는 항목
    (``sync_mois_source_db`` 같은 것)은 목록에서 지워도 아무것도 빨개지지
    않았다 — 3차 리뷰가 잡은 구멍이다. 수 자체에 래칫을 걸면 줄이는 편집이
    반드시 이 줄을 고치게 된다.
    """

    assert len(_EXPECTED_FETCHERS) >= 31, (
        f"진입점 목록이 {len(_EXPECTED_FETCHERS)}개로 줄었다. 진짜로 사라진 "
        "진입점이면 이 하한도 함께 낮춰라 — 그 편집이 리뷰에 보여야 한다."
    )


def test_the_exclusion_lists_are_real_and_state_reasons() -> None:
    """제외 목록이 낡거나 이름만 올라가는 것을 막는다.

    제외는 값싸다 — 값싼 제외는 계측을 대체하기 시작한다. 그래서 이름이 실재하는지,
    이유가 적혀 있는지, 그리고 진입점 목록과 겹치지 않는지를 따로 결박한다.
    """

    leaves = {_leaf(qualname) for _, qualname in _definitions()}
    for label, table in (
        ("_NOT_AN_ENTRYPOINT", _NOT_AN_ENTRYPOINT),
        ("_EXCLUDED_FROM_EVALUATION", _EXCLUDED_FROM_EVALUATION),
    ):
        stale = sorted(set(table) - leaves)
        assert stale == [], f"{label}에 없는 이름이 적혀 있다: {stale}"
        thin = sorted(name for name, why in table.items() if len(why) < 25)
        assert thin == [], f"{label}의 이유가 너무 짧다: {thin}"
        overlap = sorted(set(table) & set(_EXPECTED_FETCHERS))
        assert overlap == [], f"{label}이 진입점 목록과 겹친다: {overlap}"


def test_the_derivation_actually_found_the_counting_sites() -> None:
    """항진명제 방지 — 유도가 비면 아래 파라미터가 0개가 된다."""

    assert len(_fetchers()) >= 31, "진입점 유도가 낡았다 — 거의 아무것도 찾지 못했다."
    assert _counting_definitions(), (
        f"`{_NOTE}`를 부르는 정의를 하나도 찾지 못했다 — 계측이 사라졌다."
    )


def test_counting_helper_names_are_unambiguous() -> None:
    """계수 헬퍼 이름이 다른 정의와 겹치면 폐쇄가 엉뚱한 함수를 초록으로 만든다.

    호출측에는 ``x.spend()``의 receiver 타입이 보이지 않는다. 그래서 계수하는 정의의
    leaf 이름이 **유일**하기를 요구한다 — 겹치면 여기서 빨개지고, 고치는 방법은
    계수 헬퍼 이름을 충돌 불가능하게 두는 것이다.
    """

    counts = _definitions_per_leaf()
    ambiguous = sorted(
        leaf
        for leaf in _counting_leaf_names()
        if counts.get(leaf, 0) > 1 and leaf != _NOTE
    )
    assert ambiguous == [], (
        f"계수 정의의 이름이 여러 정의로 갈린다: {ambiguous}. 전이 폐쇄가 "
        "동명의 다른 함수까지 '센다'로 판정한다 — 계수 헬퍼 이름을 "
        "`_note_<provider>_call`처럼 충돌 불가능하게 바꿔라."
    )


def test_the_partial_list_names_only_real_fetchers() -> None:
    """부분 계측 목록도 낡지 않게 한다."""

    stale = sorted(set(_PARTIALLY_COUNTED) - set(_fetchers()))
    assert stale == [], f"부분 계측 목록에 없는 fetcher가 적혀 있다: {stale}"
    thin = sorted(name for name, why in _PARTIALLY_COUNTED.items() if len(why) < 30)
    assert thin == [], f"이유가 너무 짧다: {thin}"


def test_partial_and_uncountable_do_not_overlap() -> None:
    """한 fetcher가 '못 센다'와 '부분적으로 센다'를 동시에 주장할 수 없다."""

    both = sorted(set(_PARTIALLY_COUNTED) & set(_UNCOUNTABLE))
    assert both == [], f"두 목록에 함께 있다: {both}"


def test_the_uncountable_list_names_only_real_fetchers() -> None:
    """선언 목록이 낡지 않게 한다 — 사라진 이름이 면제를 계속 사 주지 못한다."""

    stale = sorted(set(_UNCOUNTABLE) - set(_fetchers()))
    assert stale == [], (
        f"선언 목록에 없는 fetcher가 적혀 있다: {stale}. 이름이 바뀌었거나 "
        "사라졌다 — 목록을 갱신해라."
    )


def test_every_uncountable_entry_states_a_reason() -> None:
    """이름만 올리는 것은 면제가 아니다."""

    thin = sorted(name for name, why in _UNCOUNTABLE.items() if len(why) < 30)
    assert thin == [], (
        f"이유가 너무 짧다: {thin}. 왜 이 층에서 셀 수 없는지 적어라 — "
        "그 문장이 다음 사람이 다시 시도할지 판단하는 근거다."
    )


@pytest.mark.parametrize("fetcher", sorted(_EXPECTED_FETCHERS))
def test_every_fetcher_counts_its_upstream_requests(fetcher: str) -> None:
    """fetcher는 요청을 세거나, 왜 못 세는지 선언돼 있어야 한다."""

    if fetcher in _UNCOUNTABLE:
        pytest.skip(f"선언된 비계측: {_UNCOUNTABLE[fetcher]}")
    assert fetcher in _counting_leaf_names(), (
        f"`{fetcher}`가 upstream 요청을 세지 않는다. 그 asset의 "
        "`upstream_requests_min`이 metadata에 실리지 않아 "
        "**한도의 몇 %를 쓰는지 대답할 수 없다**. "
        f"`{_NOTE}()`를 호출 자리에 넣거나, 이 층에서 셀 수 없다면 "
        "`_UNCOUNTABLE`에 이유와 함께 적어라."
    )


#: feature asset이 사는 모듈 — 여기서는 metadata 초크포인트를 지나야 한다.
#:
#: 손으로 박은 목록이라 **조용히 줄일 수 있다.** 그래서 아래 두 검사가 이름의
#: 실재와 유도 결과의 비어 있지 않음을 따로 결박한다(4차 적대 리뷰).
_FEATURE_ASSET_MODULES: tuple[str, ...] = ("assets.py", "kma_weather.py", "mcst_features.py")


def test_the_feature_asset_module_list_is_real_and_nonempty() -> None:
    """목록이 낡거나 조용히 줄어드는 것을 막는다.

    아래 초크포인트 검사는 이 목록을 훑는다. 목록에서 모듈 하나를 빼면 그 모듈의
    우회가 보이지 않게 되고, 목록을 비우면 검사가 **항진명제**가 된다.
    """

    modules = set(_module_trees())
    missing = sorted(set(_FEATURE_ASSET_MODULES) - modules)
    assert missing == [], f"선언된 feature asset 모듈이 없다: {missing}"
    assert len(_FEATURE_ASSET_MODULES) >= 3, (
        f"feature asset 모듈 목록이 {len(_FEATURE_ASSET_MODULES)}개로 줄었다 — "
        "진짜로 사라졌으면 이 하한도 함께 낮춰라."
    )
    # 유도가 비면 초크포인트 검사가 아무 함수도 보지 않는다.
    scanned = [
        node.name
        for module, tree in _module_trees().items()
        if module in _FEATURE_ASSET_MODULES
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
        and "_add_output_metadata" in _called_names(node)
    ]
    assert len(scanned) >= 10, (
        f"초크포인트를 지나는 함수를 {len(scanned)}개만 찾았다 — 유도가 낡았다."
    )


def test_feature_assets_do_not_bypass_the_metadata_choke_point() -> None:
    """센 값을 들고 초크포인트를 지나지 않는 feature asset이 없어야 한다.

    분자는 ``etl._add_output_metadata``에서 합쳐진다. feature asset이
    ``context.add_output_metadata``를 직접 부르면 그 자리에서는 분자가 실리지
    않는다 — 실제로 visitkorea enrichment asset이 센 값을 그렇게 버리고 있었다
    (2026-09-13 3차 적대 리뷰).

    직접 호출 자체를 금지하지는 않는다. 같은 함수가 초크포인트도 지나면
    (추가 metadata를 덧붙이는 자리) 분자는 그쪽으로 실린다 — 여기서는 **둘 중
    하나도 안 지나는 함수**만 잡는다.
    """

    offenders: list[str] = []
    for module, tree in _module_trees().items():
        if module not in _FEATURE_ASSET_MODULES:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
                continue
            calls = _called_names(node)
            if "add_output_metadata" in calls and "_add_output_metadata" not in calls:
                offenders.append(f"{module}::{node.name}")
    assert offenders == [], (
        f"feature asset이 초크포인트를 지나지 않고 metadata를 싣는다: {offenders}. "
        "`_add_output_metadata(context, ...)`를 써라 — 그러지 않으면 그 asset이 "
        "센 upstream 요청 수가 버려진다."
    )


def test_the_exemption_floor_is_bound_to_what_is_declared() -> None:
    """면제가 조용히 늘어나는 것을 막는 하한 — **본 것**에 정확히 건다.

    종전 하한은 ``len(fetchers) - 6``이었는데 실제 면제는 4였다. 두 칸이 비어
    있으면 면제 둘이 아무 편집 없이 더 들어온다 — 래칫인 척하는 상수다
    (이 저장소가 이미 기록한 실패 형태: "검사기 하한은 '본 것'에 건다").

    부분 계측도 계측된 쪽으로 세지 않는다. 그렇지 않으면 완전 계측을 부분 계측으로
    강등하는 것이 공짜가 된다.
    """

    fetchers = _fetchers()
    counting = _counting_leaf_names()
    fully = [
        name
        for name in fetchers
        if name in counting
        and name not in _PARTIALLY_COUNTED
        and name not in _UNCOUNTABLE
    ]
    assert len(fully) == _EXPECTED_FULLY_COUNTED, (
        f"완전 계측이 {len(fully)}개인데 이 파일이 박아 둔 수는 "
        f"{_EXPECTED_FULLY_COUNTED}개다(전체 {len(fetchers)}, 비계측 "
        f"{len(_UNCOUNTABLE)}, 부분 {len(_PARTIALLY_COUNTED)}). 계측을 빼거나 "
        "강등했다면 `_EXPECTED_FULLY_COUNTED`도 함께 낮춰야 하고, 그 한 줄이 "
        "리뷰에 보여야 한다. 늘렸다면 올려라."
    )
    # 선언 목록과 어긋나지 않는지도 함께 본다 — 둘 다 손으로 관리되므로 서로를
    # 검산한다.
    derived = len(fetchers) - len(_UNCOUNTABLE) - len(_PARTIALLY_COUNTED)
    assert derived == _EXPECTED_FULLY_COUNTED, (
        f"선언에서 유도한 수({derived})와 박아 둔 수({_EXPECTED_FULLY_COUNTED})가 "
        "다르다 — 목록 하나를 고치고 다른 하나를 잊었다."
    )
