"""T-VN-34C/T-VN-36D가 소유한 Feature reader의 legacy 컬럼 정적 차단선.

금지 목록은 0097(3축 cutover)과 0104(final field-override fence)의 실제
``DROP COLUMN`` SQL에서 읽는다 — 손으로 적지 않는다.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
# 손으로 적은 목록은 반드시 뒤처진다 — 실제로 뒤처졌다. `status_repo.py`가 이 목록에
# 없어서 `feature.features`를 `deleted_at`으로 세는 코드가 0097 이후에도 남았고,
# 정적 게이트는 green인 채 통합 테스트에서만 터졌다. 그래서 목록을 박지 않고
# **Feature relation을 실제로 언급하는 모듈을 매번 찾는다.** 새 모듈이 생겨도
# 자동으로 이 차단선 안에 들어온다.
_SOURCE_ROOTS = (
    _ROOT / "src/kortravelmap",
    _ROOT / "packages/kor-travel-map-api/src",
    _ROOT / "packages/kor-travel-map-dagster/src",
)
_FEATURE_RELATION_MENTION = re.compile(r"feature\.(?:features|public_features)")


def _owned_feature_readers() -> tuple[Path, ...]:
    found: list[Path] = []
    for root in _SOURCE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            if _FEATURE_RELATION_MENTION.search(path.read_text(encoding="utf-8")):
                found.append(path)
    assert found, "Feature relation을 읽는 모듈을 하나도 찾지 못했다 — 탐색 경로가 틀렸다"
    return tuple(found)


_OWNED_FEATURE_READERS = _owned_feature_readers()
_FEATURE_RELATIONS = r"feature\.(?:features|public_features)"
# 파괴적 cutover가 물리 삭제한 컬럼 전부. 손으로 적으면 뒤처진다 — 실제로
# `user_deleted_by`가 빠져 있었다. 그래서 마이그레이션 SQL에서 **직접 읽어** 목록을
# 만든다. 세대가 늘면 여기에 파일을 더한다: 0097(T-VN-34C 3축 cutover)이 legacy
# status/delete/user-change 계열 8개를, 0104(T-VN-36D final fence)가 whole-row freeze
# 잔재인 `data_origin`/`data_version`을 지운다. 뒷 세대를 더하지 않으면 차단선은
# **직전 세대만** 보게 되고, 새로 지운 컬럼은 정적으로 무방비가 된다.
_CUTOVER_MIGRATIONS = (
    _ROOT / "alembic/versions/0097_tvn34c_final_state_cutover.py",
    _ROOT / "alembic/versions/0104_tvn36_final_fence.py",
)
_DROPPED_COLUMNS = tuple(
    sorted(
        {
            column
            for migration in _CUTOVER_MIGRATIONS
            for column in re.findall(
                r"ALTER TABLE feature\.features DROP COLUMN ([a-z_]+)",
                migration.read_text(encoding="utf-8"),
            )
        }
    )
)
assert len(_DROPPED_COLUMNS) >= 10, f"cutover DROP COLUMN 목록을 읽지 못했다: {_DROPPED_COLUMNS}"
assert {"data_origin", "data_version"} <= set(_DROPPED_COLUMNS), _DROPPED_COLUMNS
_LEGACY_COLUMNS = "(?:" + "|".join(re.escape(c) for c in _DROPPED_COLUMNS) + ")"


# f-string 보간 자리를 대신하는 식별자. **식별자로 유효한 형태**여야 alias 바인딩
# (`FROM feature.features AS {alias}`)과 컬럼 참조(`{alias}.status`)가 같은 토큰으로
# 이어져 탐지된다. 서로 다른 보간이 한 토큰으로 합쳐지므로 판정은 과탐 쪽으로 기운다 —
# 차단선에서는 그쪽이 옳다.
_FSTRING_EXPR_TOKEN = "ktm_fstring_expr"


def _joined_str_text(node: ast.JoinedStr) -> str:
    """f-string을 하나의 SQL 문자열로 재조립한다.

    이 저장소의 SQL은 상당수가 f-string이다(`_lineage_sql(...)` 같은 조각을
    보간한다). f-string은 보간마다 ``ast.Constant``가 쪼개지므로, Constant만
    모으면 alias 바인딩과 컬럼 참조가 **서로 다른 조각**에 놓여 차단선이 통째로
    무반응이 된다 — 이 가드가 지키려는 대상 파일에서 Feature relation alias
    바인딩의 상당수가 정확히 그 형태였다(2026-08-12 적대 리뷰 실측).
    """

    parts: list[str] = []
    for value in node.values:
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            parts.append(value.value)
        elif isinstance(value, ast.JoinedStr):
            parts.append(_joined_str_text(value))
        else:
            parts.append(_FSTRING_EXPR_TOKEN)
    return "".join(parts)


# 0079 세대 표면을 **바이트 그대로** 재생하는 H35 복원 리허설 전용 함수들. 그 세대에
# `lifecycle_state`가 없었으므로 legacy 컬럼이 남아 있는 것이 정상이고, 3축으로 고쳐
# 쓰면 리허설이 재생하려던 표면이 아니게 된다. 차단선의 대상은 **현행** reader이므로
# 이 함수 본문만 제외한다 — 파일 전체나 alias 이름으로 제외하면 같은 파일의 현행
# 코드까지 함께 눈감게 된다.
_FROZEN_REHEARSAL_FUNCTION_PREFIX = "_frozen_h35_"
# 면제는 **모듈까지 지정해서만** 성립한다. 이름 접두어만으로 트리 전역을 면제하면
# 어느 모듈에서든 함수 이름만 그렇게 붙여 차단선을 통과할 수 있다.
#
# `curation_repo._active_feature_state_sql`은 접두어 규약을 쓰지 않지만 같은 부류다 —
# `frozen_h35_schema=True` 분기가 0063~0079 세대의 정본 컬럼으로 같은 규칙을 적는다.
# 그 세대에는 3축 컬럼이 아예 없으므로 여기를 3축으로 고치면 리허설이 재생하려던
# 표면이 아니게 된다. 이름을 하나씩 적는 이유는, 파일 전체를 빼면 같은 파일의 현행
# 코드까지 함께 눈감기 때문이다.
_FROZEN_REHEARSAL_FUNCTIONS: dict[str, frozenset[str]] = {
    "curation_repo.py": frozenset({"_active_feature_state_sql"}),
}
_FROZEN_REHEARSAL_MODULES = frozenset({"feature_repo.py"})


def _is_frozen_rehearsal_function(node: ast.AST, path: Path) -> bool:
    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    if node.name in _FROZEN_REHEARSAL_FUNCTIONS.get(path.name, frozenset()):
        return True
    if path.name not in _FROZEN_REHEARSAL_MODULES:
        return False
    return node.name.startswith(_FROZEN_REHEARSAL_FUNCTION_PREFIX)


def _sql_literals(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    frozen: set[int] = set()
    for node in ast.walk(tree):
        if _is_frozen_rehearsal_function(node, path):
            for inner in ast.walk(node):
                frozen.add(id(inner))
    literals: list[str] = []
    for node in ast.walk(tree):
        if id(node) in frozen:
            continue
        if isinstance(node, ast.JoinedStr):
            literals.append(_joined_str_text(node))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append(node.value)
    return tuple(literals)


def _legacy_feature_reads(sql: str) -> set[str]:
    """core/public Feature alias에 묶인 금지 열만 찾는다.

    ops queue 같은 독립 ``status``는 이 경계의 대상이 아니다. 반면 alias가
    Feature relation에서 파생되면 어떤 상태든 C final의 3축으로 명시해야 한다.
    """

    found: set[str] = set()
    if re.search(r"\bfeature\.features_detailed\b", sql, flags=re.IGNORECASE):
        found.add("features_detailed")
    aliases = re.findall(
        rf"\b(?:FROM|JOIN|UPDATE)\s+{_FEATURE_RELATIONS}"
        r"(?:\s+AS)?\s+([A-Za-z_][A-Za-z0-9_]*)",
        sql,
        flags=re.IGNORECASE,
    )
    for alias in aliases:
        if re.search(rf"\b{re.escape(alias)}\.{_LEGACY_COLUMNS}\b", sql, re.IGNORECASE):
            found.add(alias)
    if re.search(
        rf"\b{_FEATURE_RELATIONS}\.{_LEGACY_COLUMNS}\b",
        sql,
        flags=re.IGNORECASE,
    ):
        found.add("qualified")
    # 보간 alias에 묶인 legacy 컬럼. 이 저장소의 지배적 형태는 술어를 **헬퍼가 반환해**
    # 보간하는 것이라(`_active_feature_state_sql(alias)` 등), alias 바인딩(`FROM ... AS f`)은
    # A 리터럴에 있고 컬럼 참조(`{alias}.deleted_at`)는 B 함수의 리터럴에 있다. 그러면
    # 위 alias 규칙 어디에도 걸리지 않는다 — 헬퍼 쪽만 보면 relation 이름이 아예 없다.
    # 그래서 **보간 자리 토큰에 붙은** legacy 컬럼은 relation 문맥 없이도 위반으로 본다.
    if re.search(rf"{_FSTRING_EXPR_TOKEN}\.{_LEGACY_COLUMNS}", sql, re.IGNORECASE):
        found.add("interpolated-alias")
    # alias도 relation 접두어도 없는 **맨 컬럼**. `status_repo`의
    # `SELECT count(*) FILTER (WHERE deleted_at IS NULL) FROM feature.features`가
    # 정확히 이 형태였고, alias 규칙만으로는 통째로 통과했다.
    #
    # 오탐을 막기 위해 **참조하는 relation이 전부 Feature relation일 때만** 본다.
    # 다른 테이블이 섞이면 그 테이블의 동명 컬럼일 수 있어 판정할 수 없다.
    relations = re.findall(
        r"\b(?:FROM|JOIN|UPDATE)\s+([a-z_]+\.[a-z_]+)", sql, flags=re.IGNORECASE
    )
    if (
        relations
        and all(
            re.fullmatch(_FEATURE_RELATIONS, relation, flags=re.IGNORECASE)
            for relation in relations
        )
        and re.search(rf"(?<![.\w]){_LEGACY_COLUMNS}\b", sql, flags=re.IGNORECASE)
    ):
        found.add("unqualified")
    return found


def test_tvn34c_owned_feature_readers_do_not_restore_legacy_state() -> None:
    violations = {
        str(path.relative_to(_ROOT)): sorted(
            {
                violation
                for sql in _sql_literals(path)
                for violation in _legacy_feature_reads(sql)
            }
        )
        for path in _OWNED_FEATURE_READERS
    }
    assert {path: found for path, found in violations.items() if found} == {}


# ── 스크립트 축 ──────────────────────────────────────────────────────────────
# 위 차단선은 AST 기반이라 `.py`만 본다. 그런데 이 저장소의 **live 인수 러너**는 sh이고
# 그 안에서 `feature.features`를 직접 질의한다. 실제로 T-VN-34C가 `user_change_reason`을
# 물리 삭제한 뒤에도 `run-admin-feature-clone-live-acceptance.sh`가 그 컬럼을 계속 조회해
# **live E2E 경로가 통째로 깨진 채** 모든 게이트가 green이었다(2026-08-13 실측). 러너에는
# 정적 문자열 계약만 있고 실행 게이트가 없어 아무도 잡지 못했다.
_SCRIPT_ROOTS = (_ROOT / "scripts",)


def _feature_relation_scripts() -> tuple[Path, ...]:
    found: list[Path] = []
    for root in _SCRIPT_ROOTS:
        for path in sorted(root.rglob("*.sh")):
            if _FEATURE_RELATION_MENTION.search(path.read_text(encoding="utf-8")):
                found.append(path)
    return tuple(found)


def test_tvn34c_scripts_do_not_query_dropped_feature_columns() -> None:
    """sh 러너가 0097이 지운 컬럼을 조회하지 않는지 본다.

    판정은 단순하다 — `feature.features`를 언급하는 스크립트에서 삭제된 컬럼 이름이
    **SQL로** 나타나면 위반이다. 주석에 이름을 적는 것(왜 지웠는지 설명)은 허용한다.
    """

    violations: dict[str, list[str]] = {}
    for path in _feature_relation_scripts():
        hits: set[str] = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#"):
                continue
            # `feature.features`를 **읽는 문맥**만 본다. 이 스크립트들에는
            # (a) "그 컬럼이 더 이상 없어야 한다"는 부정 단언
            #     (`information_schema.columns ... column_name = ANY(...)`)과
            # (b) HTTP `response.status`·쉘 `local status=$?` 같은 동명이인이 섞여 있다.
            # 둘 다 위반이 아니므로, 같은 줄에서 `feature.features`와 함께 나오는
            # 참조만 센다.
            if "information_schema" in line:
                continue
            if "feature.features" not in line:
                continue
            for column in _DROPPED_COLUMNS:
                # alias 한정(`f.user_change_reason`)이 **바로 위반이다.** py 쪽
                # "맨 컬럼" 규칙의 lookbehind를 그대로 쓰면 점 뒤 참조가 제외돼
                # 정작 잡아야 할 형태를 놓친다(그렇게 짰다가 변이가 통과했다).
                if re.search(rf"\b{re.escape(column)}\b", line):
                    hits.add(column)
        if hits:
            violations[str(path.relative_to(_ROOT))] = sorted(hits)
    assert violations == {}, (
        "스크립트가 0097이 삭제한 컬럼을 조회한다 — live 경로가 런타임에만 터진다"
    )
