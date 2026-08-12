"""T-VN-34C가 소유한 Feature reader의 legacy state 정적 차단선."""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_OWNED_FEATURE_READERS = (
    _ROOT / "src/kortravelmap/infra/feature_repo.py",
    _ROOT / "src/kortravelmap/infra/admin_feature_repo.py",
    _ROOT / "src/kortravelmap/infra/curated_repo.py",
    _ROOT / "src/kortravelmap/infra/curation_repo.py",
    _ROOT / "src/kortravelmap/infra/scope_repo.py",
    _ROOT / "src/kortravelmap/infra/dedup_refresh_repo.py",
    _ROOT / "src/kortravelmap/infra/weather_repo.py",
    _ROOT / "src/kortravelmap/infra/consistency.py",
    _ROOT / "src/kortravelmap/infra/merge_repo.py",
    _ROOT / "src/kortravelmap/infra/feature_address_repo.py",
)
_FEATURE_RELATIONS = r"feature\.(?:features|public_features)"
_LEGACY_COLUMNS = r"(?:status|deleted_at|user_deleted_at|user_change_[a-z_]+)"


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


def _is_frozen_rehearsal_function(node: ast.AST) -> bool:
    return isinstance(
        node, (ast.FunctionDef, ast.AsyncFunctionDef)
    ) and node.name.startswith(_FROZEN_REHEARSAL_FUNCTION_PREFIX)


def _sql_literals(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    frozen: set[int] = set()
    for node in ast.walk(tree):
        if _is_frozen_rehearsal_function(node):
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
