"""0214 이전 Python canonical writer가 runtime 진입점에서 닿지 않는지.

runtime은 같은 이름의 SECURITY DEFINER procedure(`*_command`)를 CALL한다. 아래 Python
writer는 superuser 통합 테스트의 seeding 경로로만 남아 있고, 어떤 runtime 진입점에도
연결돼 있지 않다 — 누가 다시 연결하면 그 경로는 runtime role에서 42501이다.

T-VN-40C가 `tests/lint/test_legacy_write_fence.py`를 legacy `curated_features` fence와
함께 지웠는데, 이 검사만은 fence와 무관하게(=writer가 canonical 표를 쓴다) 계속
유효하므로 여기로 옮겼다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]

# `_lock_legacy_projections_for_item`은 40C가 legacy projection과 함께 지웠다.
# `update_curation_item`은 canonical 표를 쓰므로 남았고, 그래서 검사도 남는다.
_SUPERSEDED_TEST_ONLY_WRITERS: frozenset[str] = frozenset({"update_curation_item"})


def test_superseded_writer_set_is_not_empty_and_still_exists() -> None:
    """빈 집합이거나 이름이 사라졌으면 아래 검사가 자명하게 통과한다."""
    assert _SUPERSEDED_TEST_ONLY_WRITERS, "검사 대상이 비어 있다"
    source = (_ROOT / "src/kortravelmap/infra/curation_repo.py").read_text(encoding="utf-8")
    for name in _SUPERSEDED_TEST_ONLY_WRITERS:
        assert re.search(rf"^async def {re.escape(name)}\(", source, re.M), (
            f"{name}이 curation_repo.py에 없다 — 지워졌다면 이 검사도 함께 정리한다"
        )


def test_superseded_python_writers_are_not_reachable_from_runtime() -> None:
    """superseded Python writer가 라우터·CLI·dagster 어디에서도 참조되지 않는다."""
    # 진입점 + "진입점이 부를 수 있는 모든 것". curation_repo.py 자신만 제외한다 —
    # infra의 다른 모듈이 부르면 그 모듈이 runtime-reachable bridge가 된다.
    entrypoint_dirs = (
        _ROOT / "packages/kor-travel-map-api/src",
        _ROOT / "packages/kor-travel-map-dagster/src",
        _ROOT / "src/kortravelmap",
        _ROOT / "scripts",
    )
    excluded = {_ROOT / "src/kortravelmap/infra/curation_repo.py"}
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
    assert not hits, (
        "superseded Python writer가 runtime 경로에서 참조된다 — "
        "`*_command` procedure CALL로 바꾼다:\n" + "\n".join(hits)
    )
