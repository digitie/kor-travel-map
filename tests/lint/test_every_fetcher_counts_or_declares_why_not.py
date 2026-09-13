"""모든 provider fetcher가 요청을 **세거나, 왜 못 세는지 적거나** 하게 한다.

2026-09-13 적대 리뷰가 blocker를 잡았다. 분자 배선(:mod:`~.upstream_requests`)은
멀쩡했는데 **커버리지가 없었다** — 계수기는 asset 35개 전부에서 열리는데 세는 자리는
셋뿐이었다. 그래서 OpiNet처럼 수천 건을 쓰는 경로가 ``upstream_requests_min: 0``을
냈고, 하필 그것이 **분모를 실측한 유일한 provider**였다.

그때 이 저장소가 갖고 있던 구조 검사는 초록이었다. 그 검사는
``asset이 계수 범위 안에서 도는가``를 물었는데, wrapper가 **항상** 열므로
항진명제였다 — 같은 실패 형태를 그날 네 번째로 반복한 것이다.

**그래서 여기서는 asset이 아니라 fetcher를 센다.** 요청을 실제로 보내는 것은
fetcher이고, 그것이 계수 호출을 (직접이든 헬퍼를 통해서든) 갖는지는 소스에서
유도할 수 있다. 못 세는 것은 :data:`_UNCOUNTABLE`에 **이유와 함께** 적어야 한다 —
목록에 이름을 올리는 일 자체가 결정의 기록이다.
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
_UNCOUNTABLE: dict[str, str] = {
    "fetch_krairport_airports": (
        "번들 정적 데이터 — credential 없이 동작하고 upstream 요청이 없다."
    ),
    "fetch_mois_license_records": (
        "로컬 sqlite 파일을 읽는다 — upstream 요청이 없다."
    ),
    "fetch_datagokr_file_data_records": (
        "`client.file_data.iter_all()`이 provider 안에서 페이지네이션한다. "
        "이 층은 페이지 수를 볼 수 없고, 1로 세면 0만큼이나 오도한다."
    ),
    "fetch_krheritage_events": (
        "`client.event.iter_months()`가 provider 안에서 월별로 순회한다. "
        "같은 이유로 이 층에서는 요청 수를 알 수 없다."
    ),
}


def _module_trees() -> dict[str, ast.Module]:
    return {
        path.name: ast.parse(path.read_text(encoding="utf-8"))
        for path in sorted(_PKG.glob("*.py"))
    }


def _called_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return names


def _functions() -> dict[str, set[str]]:
    return {
        node.name: _called_names(node)
        for tree in _module_trees().values()
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef)
    }


def _counting_functions() -> set[str]:
    """``note_upstream_request``를 **직접 또는 간접으로** 부르는 함수.

    전이 폐쇄를 도는 이유는 대부분의 fetcher가 헬퍼를 통해 세기 때문이다
    (``iter_paginated_items``·``_iter_krforest_records``·``_OpinetCallBudget.spend``).
    """

    functions = _functions()
    counting = {name for name, calls in functions.items() if _NOTE in calls}
    changed = True
    while changed:
        changed = False
        for name, calls in functions.items():
            if name not in counting and calls & counting:
                counting.add(name)
                changed = True
    return counting


def _fetchers() -> list[str]:
    return sorted(name for name in _functions() if name.startswith("fetch_"))


def test_the_derivation_actually_found_the_fetchers() -> None:
    """항진명제 방지 — 유도가 비면 아래 파라미터가 0개가 된다."""

    fetchers = _fetchers()
    assert len(fetchers) >= 30, (
        f"provider fetcher를 {len(fetchers)}개만 찾았다 — 유도가 낡았다."
    )
    assert _NOTE in str(_functions().values()) or _counting_functions(), (
        f"`{_NOTE}`를 부르는 함수를 하나도 찾지 못했다 — 계측이 사라졌다."
    )


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


@pytest.mark.parametrize("fetcher", _fetchers())
def test_every_fetcher_counts_its_upstream_requests(fetcher: str) -> None:
    """fetcher는 요청을 세거나, 왜 못 세는지 선언돼 있어야 한다."""

    if fetcher in _UNCOUNTABLE:
        pytest.skip(f"선언된 비계측: {_UNCOUNTABLE[fetcher]}")
    assert fetcher in _counting_functions(), (
        f"`{fetcher}`가 upstream 요청을 세지 않는다. 그 asset의 "
        "`upstream_requests_min`이 metadata에 실리지 않아 "
        "**한도의 몇 %를 쓰는지 대답할 수 없다**. "
        f"`{_NOTE}()`를 호출 자리에 넣거나, 이 층에서 셀 수 없다면 "
        "`_UNCOUNTABLE`에 이유와 함께 적어라."
    )


def test_most_fetchers_are_actually_counted() -> None:
    """면제가 조용히 늘어나는 것을 막는 하한.

    선언이 값싸면 다음 사람이 계측 대신 면제를 고른다. 실측(2026-09-13)은
    32개 중 28개가 센다 — 그 비율이 무너지면 여기서 빨개진다.
    """

    fetchers = _fetchers()
    counted = [name for name in fetchers if name in _counting_functions()]
    assert len(counted) >= len(fetchers) - 6, (
        f"계측되지 않은 fetcher가 {len(fetchers) - len(counted)}개다"
        f"(전체 {len(fetchers)}). 면제가 늘고 있다 — 분자를 세는 것이 원칙이고 "
        "선언은 예외다."
    )
