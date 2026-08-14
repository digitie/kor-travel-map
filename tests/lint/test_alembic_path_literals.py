"""소스가 적은 alembic 파일 경로가 실제로 존재하는지 검사한다.

squash(`0200`)로 체인 109개가 `alembic/versions/` -> `alembic/legacy_versions/`로
옮겨갔다. 그 경로를 **문자열로** 들고 있던 코드는 import 시점에야 죽는데, 그게 통합
테스트 setup이면 수백 건이 한꺼번에 error가 되고 원인은 로그 끝에서야 보인다 —
실제로 그렇게 4건이 마지막까지 남았다(`test_khoa_*`가 migration 모듈을
`spec_from_file_location`으로 직접 로드한다).

alembic이 해석하는 revision id는 `test_migration_forward_only`와 `_archived_revisions`가
본다. 여기서 보는 것은 **파일 경로 리터럴**이다 — 그쪽 가드가 잡지 못하는 축이다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_SCANNED_ROOTS = (
    _ROOT / "src",
    _ROOT / "tests",
    _ROOT / "scripts",
    _ROOT / "packages",
    _ROOT / "alembic",
    _ROOT / "docker",
)
#: 두 표기를 본다: Path 연산자로 이어 붙인 형태와 슬래시로 붙인 문자열 형태.
#: 전자는 줄바꿈을 넘나들 수 있어 공백을 먼저 뭉갠다.
#:
#: 예시는 **적지 않는다.** 이 파일 자신이 스캔 대상이라, 예시로 적은 경로가 실재하지
#: 않으면 가드가 자기 자신을 위반으로 잡는다 — 첫 판이 정확히 그랬다.
#: (`test_no_control_characters_in_source`가 금지 문자를 `chr()`로 적는 것과 같은 이유다.)
_PATH_STYLE = re.compile(r'"alembic"\s*/\s*"(versions|legacy_versions)"\s*/\s*"([^"]+\.py)"')
_STRING_STYLE = re.compile(r'"alembic/(versions|legacy_versions)/([^"]+\.py)"')


def _sources() -> list[Path]:
    found: list[Path] = []
    for root in _SCANNED_ROOTS:
        if root.exists():
            found.extend(sorted(root.rglob("*.py")))
    assert found, "스캔 대상을 하나도 찾지 못했다 — 경로가 틀렸다"
    return found


def test_alembic_file_path_literals_resolve() -> None:
    missing: dict[str, list[str]] = {}
    checked = 0
    for path in _sources():
        collapsed = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
        for directory, name in _PATH_STYLE.findall(collapsed) + _STRING_STYLE.findall(collapsed):
            checked += 1
            if not (_ROOT / "alembic" / directory / name).exists():
                missing.setdefault(str(path.relative_to(_ROOT)), []).append(
                    f"alembic/{directory}/{name}"
                )
    assert checked, (
        "alembic 경로 리터럴을 하나도 찾지 못했다 — 표기가 바뀌었다면 이 가드도 함께"
        " 고쳐라(찾지 못한 채 통과시키지 마라)"
    )
    assert not missing, "존재하지 않는 alembic 파일을 가리킨다:\n" + "\n".join(
        f"  {source}: {', '.join(names)}" for source, names in sorted(missing.items())
    )
