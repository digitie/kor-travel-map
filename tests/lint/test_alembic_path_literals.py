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
    _ROOT / ".github",
)
#: `.py`만 보면 `scripts/h35/*.sh` 같은 쉘 러너가 밖에 남는다 — 그것도 같은 경로를
#: 문자열로 들고 있고, 깨지면 배포 시점에야 드러난다.
_SCANNED_SUFFIXES = ("*.py", "*.sh")
#: 두 표기를 본다: Path 연산자로 이어 붙인 형태와 슬래시로 붙인 문자열 형태.
#: 전자는 줄바꿈을 넘나들 수 있어 공백을 먼저 뭉갠다.
#:
#: 예시는 **적지 않는다.** 이 파일 자신이 스캔 대상이라, 예시로 적은 경로가 실재하지
#: 않으면 가드가 자기 자신을 위반으로 잡는다 — 첫 판이 정확히 그랬다.
#: (`test_no_control_characters_in_source`가 금지 문자를 `chr()`로 적는 것과 같은 이유다.)
#: 작은따옴표도 받는다. 이 저장소는 `ruff` select에 `Q`가 없고 `ruff format --check`가
#: `if: false`라 두 표기가 모두 합법이다 — 큰따옴표만 보면 가장 그럴듯한 우회가
#: 그대로 열린다(적대 리뷰 실증).
_QUOTE = "[\"']"
#: `baseline`도 본다 — `alembic/baseline/{schema,seed}.sql`은 **모든 fresh DB에서 실제로
#: 실행되는** 764KB다. 지금은 `0200`이 디렉터리와 파일명을 나눠 들고 있어 리터럴이
#: 없지만(그래서 이 가드가 세는 것도 0건이다), 누가 경로를 한 줄로 적는 순간 대상이 된다.
_DIRECTORY = "(versions|legacy_versions|retired_versions/0200-0236|baseline)"
_LEAF = r"([^\"']+\.(?:py|sql))"
_PATH_STYLE = re.compile(
    rf"{_QUOTE}alembic{_QUOTE}\s*/\s*{_QUOTE}{_DIRECTORY}{_QUOTE}\s*/\s*{_QUOTE}{_LEAF}{_QUOTE}"
)
_STRING_STYLE = re.compile(rf"{_QUOTE}alembic/{_DIRECTORY}/{_LEAF}{_QUOTE}")
#: 따옴표 **없이** 나오는 경로. 쉘 인자·워크플로 명령·docstring에서 가장 흔한 형태이고,
#: 앞의 두 표기만 보던 판은 이 축을 통째로 놓쳤다. 세어 보니 저장소에 9건 있었고 그중
#: 하나가 squash로 옮겨간 파일을 그대로 가리키고 있었다(2026-08-15 실측) — 가드가 잡으라고
#: 만들어진 바로 그 종류다.
#:
#: 앞에 `"`/`'`/`/`/단어문자가 오면 제외한다. 그래야 위 두 표기와 중복해 세지 않고,
#: `docs/alembic/versions/...` 같은 다른 경로의 꼬리를 잘못 물지 않는다.
_BARE_STYLE = re.compile(rf"(?<![\"'/\w])alembic/{_DIRECTORY}/([\w.\-*]+\.(?:py|sql))")


def _sources() -> list[Path]:
    found: list[Path] = []
    for root in _SCANNED_ROOTS:
        if root.exists():
            for pattern in _SCANNED_SUFFIXES:
                found.extend(sorted(root.rglob(pattern)))
    assert found, "스캔 대상을 하나도 찾지 못했다 — 경로가 틀렸다"
    return found


def test_alembic_file_path_literals_resolve() -> None:
    missing: dict[str, list[str]] = {}
    checked = 0
    for path in _sources():
        collapsed = re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))
        found = (
            _PATH_STYLE.findall(collapsed)
            + _STRING_STYLE.findall(collapsed)
            + _BARE_STYLE.findall(collapsed)
        )
        for directory, name in found:
            # f-string 보간(`{stem}`)은 정적으로 풀 수 없다. 검사하지 않는다 —
            # 억지로 판정하면 정상 코드에 빨간불이 뜨고, 사람은 가드를 끄는 쪽으로 움직인다.
            if "{" in name:
                continue
            # glob 패턴(`*_schema_baseline.py`, `*.sql`)은 파일 하나를 가리키지 않는다.
            # 존재 여부로 판정하면 정상 코드가 빨개진다.
            if "*" in name:
                continue
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
