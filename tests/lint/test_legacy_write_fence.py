"""T-VN-40A legacy write fence — 세 층이 같은 것을 막고 있는지.

fence는 ACL(`runtime_privileges`) · static(`legacy_write_fence` + repo 호출) · route(410)
세 층이다. **하나만 두면 그 하나가 조용히 풀렸을 때 아무도 모른다.** 이 테스트는 세 층이
서로 어긋나지 않는지를 본다 — 층 하나가 fence 대상을 빼먹으면 여기서 red다.

이 저장소에서 반복 관찰된 실패 모드가 "검사기가 검사한다고 주장하는 것을 실제로는 안
본다"이므로, 각 검사가 **빈 집합끼리 비교해 통과하지 않는지**도 함께 단언한다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from kortravelmap.infra import legacy_write_fence, runtime_privileges

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_REPO = _ROOT / "src/kortravelmap/infra/curated_repo.py"
_ROUTER = (
    _ROOT / "packages/kor-travel-map-api/src/kortravelmap/api/routers/curated.py"
)


def test_fence_target_set_is_not_empty() -> None:
    """빈 집합이면 아래 검사가 전부 자명하게 통과한다."""
    assert legacy_write_fence.LEGACY_CURATED_RELATIONS, "fence 대상이 비어 있다"
    assert "curated_features" in legacy_write_fence.LEGACY_CURATED_RELATIONS


def test_acl_layer_grants_no_write_on_curated_features() -> None:
    """ACL 층 — `curated_features`에 write 권한이 부여되지 않는다.

    `reconcile_runtime_privileges`는 REVOKE ALL 뒤 이 표대로만 GRANT한다. 표에 write가
    있으면 DB에 write가 생긴다. 이 한 줄이 DB 층 fence의 전부다.
    """
    privileges = runtime_privileges._FEATURE_TABLE_PRIVILEGES  # noqa: SLF001
    assert "curated_features" in privileges, "표에서 아예 빠지면 SELECT도 못 한다"
    granted = set(privileges["curated_features"])
    assert granted == {"SELECT"}, (
        f"curated_features에 write 권한이 부여된다: {sorted(granted - {'SELECT'})}. "
        "T-VN-40A fence를 되돌린 것이다."
    )


def test_static_layer_every_repo_write_function_calls_the_fence() -> None:
    """static 층 — legacy repo의 모든 write 함수가 fence를 부른다.

    `create_`/`update_`/`set_`/`archive_`로 시작하는 async 함수 각각의 본문에
    `assert_legacy_write_allowed(...)` 호출이 있어야 한다. 새 write 함수를 추가하면서 fence를
    빠뜨리면 여기서 잡힌다.
    """
    tree = ast.parse(_REPO.read_text(encoding="utf-8"))
    # `curated_feature`(단수)로 시작하는 것만 — `curated_theme_command` 등은 T-VN-40의
    # 살아 있는 catalog라 fence 대상이 아니다(plan:28). 이름이 `curated_`로 시작한다고
    # 전부 legacy가 아니다.
    write_fns = [
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef)
        and re.match(r"^(create|update|set|archive)_curated_feature(_|$)", node.name)
    ]
    assert write_fns, "write 함수를 하나도 못 찾았다 — 이름 규칙이 바뀌었나"

    missing: list[str] = []
    for fn in write_fns:
        calls = {
            n.func.id
            for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        }
        if "assert_legacy_write_allowed" not in calls:
            missing.append(fn.name)
    assert not missing, f"fence를 안 부르는 legacy write 함수: {missing}"


def test_static_layer_fence_relations_match_the_declared_set() -> None:
    """static 층이 부르는 relation 이름이 선언된 집합 안에 있다.

    오타(`curated_feature`)로 부르면 fence가 그 호출을 통과시킨다 — 집합 밖 이름은
    조용히 허용되기 때문이다. 그래서 호출부의 문자열을 모아 집합과 대조한다.
    """
    src = _REPO.read_text(encoding="utf-8")
    called = set(re.findall(r'assert_legacy_write_allowed\("([a-z_]+)"', src))
    assert called, "호출부에서 relation 이름을 하나도 못 뽑았다"
    unknown = called - legacy_write_fence.LEGACY_CURATED_RELATIONS
    assert not unknown, (
        f"fence 집합에 없는 relation을 부른다(오타면 fence가 통과시킨다): {sorted(unknown)}"
    )


def test_route_layer_admin_router_has_the_fence_dependency() -> None:
    """route 층 — legacy admin router에 write fence dependency가 걸려 있다."""
    src = _ROUTER.read_text(encoding="utf-8")
    assert "_fence_legacy_curated_writes" in src
    # router 정의에 실제로 걸려 있는지 (함수만 있고 안 걸면 무의미)
    m = re.search(
        r"admin_router\s*=\s*APIRouter\((.*?)\)\n", src, re.S
    )
    assert m, "admin_router 정의를 못 찾음"
    assert "_fence_legacy_curated_writes" in m.group(1), (
        "fence 함수는 있는데 admin_router dependencies에 안 걸려 있다"
    )


def test_fence_refuses_every_declared_relation() -> None:
    """함수 자체가 선언된 모든 relation을 거부하는지."""
    for relation in legacy_write_fence.LEGACY_CURATED_RELATIONS:
        with pytest.raises(legacy_write_fence.LegacyWriteFenceError):
            legacy_write_fence.assert_legacy_write_allowed(relation, operation="test")


def test_fence_ignores_relations_outside_the_set() -> None:
    """집합 밖은 통과한다 — 이 fence의 관심사가 아니다.

    (그래서 위 `..._match_the_declared_set`이 필요하다: 오타는 여기로 빠져나간다.)
    """
    legacy_write_fence.assert_legacy_write_allowed("curation_items", operation="test")
