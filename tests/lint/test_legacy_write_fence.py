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


@pytest.mark.parametrize(
    "relation",
    [
        "curated_features",
        # legacy read 캐시 — 읽는 코드도 쓰는 코드도 없다(fence 리뷰 P2). 40C까지 SELECT만.
        "curated_feature_detail_snapshots",
    ],
)
def test_acl_layer_grants_no_write_on_legacy_relations(relation: str) -> None:
    """ACL 층 — legacy 관계에 write 권한이 부여되지 않는다.

    `reconcile_runtime_privileges`는 REVOKE ALL 뒤 이 표대로만 GRANT한다. 표에 write가
    있으면 DB에 write가 생긴다. 이 한 줄이 DB 층 fence의 전부다.
    """
    privileges = runtime_privileges._FEATURE_TABLE_PRIVILEGES  # noqa: SLF001
    assert relation in privileges, "표에서 아예 빠지면 SELECT도 못 한다"
    granted = set(privileges[relation])
    assert granted == {"SELECT"}, (
        f"{relation}에 write 권한이 부여된다: {sorted(granted - {'SELECT'})}. "
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


# ── infra 전체 inventory ────────────────────────────────────────────────────
#
# 위 검사는 `curated_repo.py`의 이름 규칙(`create_/update_/set_/archive_curated_feature*`)만
# 본다. 적대 리뷰 P2: 다른 infra 모듈이 raw SQL로 legacy를 쓰면 그 규칙 밖이다. 그래서
# `src/kortravelmap/infra/*.py` 전부를 SQL 문자열 수준에서 훑는다 — 모듈 상수든 함수 안
# 인라인이든 `curated_features`에 write/lock하는 문장을 모두 찾아 **감싸는 함수**로 되돌린
# 뒤, 그 함수가 fence를 부르거나 아래 allowlist에 있어야 한다.

_INFRA_DIR = _ROOT / "src/kortravelmap/infra"
# write DML(ONLY/MERGE/TRUNCATE 포함) 또는 row lock. PostgreSQL은 FOR UPDATE / FOR NO KEY
# UPDATE / FOR SHARE / FOR KEY SHARE **넷 다** UPDATE 권한을 요구한다(SELECT 문서) — SHARE도
# 잡는다. lock 절은 `OF alias`가 있든 없든, alias에 `AS`가 있든 없든 매칭한다: 같은 문자열
# 안에 `feature.curated_features`가 등장하고 뒤에 locking clause가 오면 write로 본다.
_LEGACY_WRITE_SQL = re.compile(
    r"\b(?:UPDATE|INSERT\s+INTO|DELETE\s+FROM|MERGE\s+INTO|TRUNCATE)\s+(?:ONLY\s+)?"
    r"feature\.curated_features\b"
    r"|feature\.curated_features\b[\s\S]*?\bFOR\s+(?:NO\s+KEY\s+UPDATE|UPDATE|KEY\s+SHARE|SHARE)\b",
    re.I,
)
# 0214 이전의 Python canonical writer들. runtime은 같은 이름의 SECURITY DEFINER procedure
# (`*_command`)를 CALL하고, 이 Python 함수들은 **어떤 runtime 진입점에도 연결돼 있지 않다**
# (아래 `test_superseded_python_writers_are_not_reachable_from_runtime`가 그것을 고정한다).
# superuser 통합 테스트의 seeding 경로로만 남아 있고 40C에서 legacy와 함께 사라진다.
_SUPERSEDED_TEST_ONLY_WRITERS: frozenset[str] = frozenset(
    {"update_curation_item", "_lock_legacy_projections_for_item"}
)


def _legacy_writing_functions(path: Path) -> dict[str, bool]:
    """모듈에서 legacy write SQL을 품거나 그런 상수를 쓰는 top-level 함수 → fence 호출 여부."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    write_consts: set[str] = set()
    for node in tree.body:
        target = None
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target = node.target.id
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            target = t.id if isinstance(t, ast.Name) else None
        value = getattr(node, "value", None)
        if (
            target
            and isinstance(value, ast.Constant)
            and isinstance(value.value, str)
            and _LEGACY_WRITE_SQL.search(value.value)
        ):
            write_consts.add(target)

    out: dict[str, bool] = {}
    for fn in tree.body:
        if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        writes = False
        calls_fence = False
        for n in ast.walk(fn):
            if isinstance(n, ast.Constant) and isinstance(n.value, str):
                if _LEGACY_WRITE_SQL.search(n.value):
                    writes = True
            elif isinstance(n, ast.Name) and n.id in write_consts:
                writes = True
            elif (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "assert_legacy_write_allowed"
            ):
                calls_fence = True
        if writes:
            out[fn.name] = calls_fence
    return out


def test_every_infra_legacy_write_is_fenced_or_superseded() -> None:
    """infra 전체에서 `curated_features`에 write/lock하는 함수는 fence를 부르거나 allowlist다."""
    found: dict[str, dict[str, bool]] = {}
    for path in sorted(_INFRA_DIR.glob("*.py")):
        fns = _legacy_writing_functions(path)
        if fns:
            found[path.name] = fns
    assert found, "legacy write SQL을 하나도 못 찾았다 — 정규식이나 경로가 틀렸다"
    # 검사기가 살아 있다는 증거: 알려진 fenced writer와 알려진 superseded writer가 둘 다 잡힌다.
    assert found.get("curated_repo.py", {}).get("create_curated_feature") is True
    assert "update_curation_item" in found.get("curation_repo.py", {})

    unfenced = sorted(
        f"{module}:{name}"
        for module, fns in found.items()
        for name, fenced in fns.items()
        if not fenced and name not in _SUPERSEDED_TEST_ONLY_WRITERS
    )
    assert not unfenced, (
        f"fence 없이 legacy를 쓰는 함수: {unfenced}. SECURITY DEFINER procedure CALL로 옮기거나 "
        "fence를 부르거나, superseded 테스트 전용이면 allowlist에 근거와 함께 추가한다."
    )


def test_superseded_python_writers_are_not_reachable_from_runtime() -> None:
    """allowlist의 Python writer가 라우터·CLI·dagster 어디에서도 참조되지 않는다.

    allowlist는 "runtime에서 안 부른다"는 전제 위에 있다. 누가 다시 연결하면 그 경로는
    runtime role에서 42501이다 — 여기서 먼저 잡는다.
    """
    # 진입점 + "진입점이 부를 수 있는 모든 것". curation_repo.py 자신만 제외한다 —
    # infra의 다른 모듈이 부르면 그 모듈이 runtime-reachable bridge가 된다(리뷰 P2).
    entrypoint_dirs = (
        _ROOT / "packages/kor-travel-map-api/src",
        _ROOT / "packages/kor-travel-map-dagster/src",
        _ROOT / "src/kortravelmap",
        _ROOT / "scripts",
    )
    excluded = {_ROOT / "src/kortravelmap/infra/curation_repo.py"}
    # `_lock_legacy_projections_for_item`은 private이라 `update_curation_item`을 통해서만
    # 닿는다. public 이름과 그 wrapper(`archive_curation_item`은 update_curation_item을 감싼다).
    names = sorted(
        {n for n in _SUPERSEDED_TEST_ONLY_WRITERS if not n.startswith("_")}
        | {"archive_curation_item"}
    )
    pattern = re.compile(r"\b(" + "|".join(map(re.escape, names)) + r")\b(?!_command)")
    hits: list[str] = []
    for base in entrypoint_dirs:
        assert base.is_dir(), f"진입점 디렉터리가 없다: {base}"
        for path in base.rglob("*.py"):
            if path in excluded:
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    hits.append(f"{path.relative_to(_ROOT)}:{i}: {line.strip()}")
    assert not hits, "superseded Python legacy writer가 runtime 진입점에서 참조된다:\n" + "\n".join(
        hits
    )


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


def test_legacy_write_regex_catches_every_locking_clause_and_dml_form() -> None:
    """검사기 자기검증 — 회피 형태가 실제로 잡히는지(리뷰 P2에서 나온 목록)."""
    caught = (
        "UPDATE ONLY feature.curated_features SET x = 1",
        "MERGE INTO feature.curated_features AS t USING s ON true WHEN MATCHED THEN DELETE",
        "TRUNCATE feature.curated_features",
        "SELECT 1 FROM feature.curated_features cf WHERE true FOR UPDATE OF cf",
        "SELECT 1 FROM feature.curated_features WHERE true FOR NO KEY UPDATE",
        "SELECT 1 FROM feature.curated_features AS legacy FOR SHARE",
        "SELECT 1 FROM feature.curated_features FOR KEY SHARE",
        "select 1 from feature.curated_features for update",
    )
    for sql in caught:
        assert _LEGACY_WRITE_SQL.search(sql), sql
    passed = (
        "SELECT count(*) FROM feature.curated_features",
        "SELECT 1 FROM feature.curated_features_history FOR UPDATE",
        "UPDATE feature.curation_items SET x = 1",
    )
    for sql in passed:
        assert not _LEGACY_WRITE_SQL.search(sql), sql


def test_no_orm_write_path_to_curated_features_outside_models() -> None:
    """ORM 우회 — `CuratedFeatureRow`(models.py)를 통한 add()/update()는 SQL 문자열이 없어
    위 정규식이 못 본다. 그래서 그 row 클래스가 models·infra/__init__ 재수출 밖 어디에서도
    참조되지 않음을 고정한다. 참조가 생기면 여기서 red — 그때 fence 층을 그 경로에도 놓는다.
    """
    allowed = {
        _ROOT / "src/kortravelmap/infra/models.py",
        _ROOT / "src/kortravelmap/infra/__init__.py",
    }
    bases = (
        _ROOT / "src",
        _ROOT / "packages/kor-travel-map-api/src",
        _ROOT / "packages/kor-travel-map-dagster/src",
        _ROOT / "scripts",
    )
    hits: list[str] = []
    for base in bases:
        for path in base.rglob("*.py"):
            if path in allowed:
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r"\bCuratedFeatureRow\b", line):
                    hits.append(f"{path.relative_to(_ROOT)}:{i}: {line.strip()}")
    assert not hits, "CuratedFeatureRow(ORM legacy write 우회 가능)가 참조된다:\n" + "\n".join(
        hits
    )

