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


def _sql_literals(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return tuple(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    )


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
