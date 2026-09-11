"""디스크에 있는 migration 사이드카가 실제로 실행되는지 검사한다.

## 왜

큰 재키는 루틴 본문을 `.py` 안에 두지 못한다 — 수백 줄 plpgsql이 리뷰를 삼킨다.
그래서 `alembic/versions/_<rev>_<루틴이름>.sql` 사이드카로 쪼개고 `.py`가
`_sidecar("...")`로 끌어다 쓴다. 이 분리에는 조용한 구멍이 하나 있다:

**파일을 쓰고 배선을 잊어도 아무것도 빨개지지 않는다.**

마이그레이션은 초록으로 통과하고, 사이드카는 리뷰에 올라오고, diff에도 보인다.
그런데 그 루틴은 DB에서 옛 정의 그대로다. 2026-09-09 T-VN-39에서 정확히 이 일이
났다 — 2차 스코프에서 발견한 11개 루틴의 사이드카를 다 써 놓고 `_ROUTINE_STATEMENTS`에
넣지 않았다. `alembic upgrade head`는 성공했을 것이고, 시그니처 린트는 사이드카
파일을 원천으로 읽으므로 **그것도 초록이었을 것이다.** 첫 실패는 한참 뒤 런타임에서
났을 것이다.

탐지기가 대상을 안 보는데 초록인 부류라, 여기서 본다.

## 어떻게 보는가 — 이름이 아니라 읽기를 센다

배선을 정규식으로 찾으면 이 검사 자신이 같은 함정에 빠진다. 실제로 306은 이름을
`_sidecar(f"_306_{name}_{suffix}.sql")`로 **조립**해서 읽는다 — 리터럴을 찾는 눈에는
"배선 안 됨"으로 보이고, 그건 거짓 양성이다. 반대 방향의 거짓 음성도 똑같이 쉽다.

그래서 이름을 읽지 않고 `pathlib.Path.read_text`를 계측한 채 각 마이그레이션 모듈을
import해서 **실제로 열린 파일을 센다.** 사이드카는 모듈 상수를 만들 때 읽히므로
import만으로 잡힌다. 조립하든 리터럴이든 상관없다.

`upgrade()` 안에서 늦게 읽는 마이그레이션이 나오면 import는 그것을 못 본다. 그런
경우를 위해 리터럴 참조도 함께 인정한다(합집합) — 둘 중 하나면 배선된 것이다.

## 예외를 두는 법

판정이 "무변경"인 루틴도 사이드카로 둔다 — 왜 손대지 않는지가 리뷰의 대상이기
때문이다. 그런 파일은 실행되면 **안 된다.** 파일 머리에 판정을 적어 구분한다:

    -- 판정: 유지(무변경)

이 표식은 주석이 아니라 계약이다. 배선하지 않겠다는 선언을 파일 자신이 들고 있어야
"잊었다"와 "일부러 뺐다"가 구분된다.
"""

from __future__ import annotations

import importlib.util
import pathlib
import re
from collections.abc import Iterator
from contextlib import contextmanager

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_VERSIONS = _ROOT / "alembic" / "versions"

#: 사이드카 이름 규약: `_<revision 접두>_<루틴이름>.sql`.
_SIDECAR = re.compile(r"^_(?P<rev>[0-9]+)_(?P<name>[a-z_0-9]+)\.sql$")
#: 이름을 조립하지 않고 그대로 쓴 참조. 늦게 읽는 마이그레이션을 위한 보조 통로다.
_LITERAL_REFERENCE = re.compile(r'"(?P<file>_[0-9]+_[a-z_0-9]+\.sql)"')
#: 실행하지 않겠다는 선언. 판정 문구는 자유롭되 "무변경"이 들어가야 한다.
_UNCHANGED = re.compile(r"판정:\s*[^\n]*무변경")


@contextmanager
def _recording_sidecar_reads() -> Iterator[set[str]]:
    """`alembic/versions/*.sql`을 여는 모든 읽기를 기록한다."""
    opened: set[str] = set()
    original = pathlib.Path.read_text

    def spy(self: pathlib.Path, *args: object, **kwargs: object) -> str:
        resolved = self if self.is_absolute() else (pathlib.Path.cwd() / self)
        if resolved.parent == _VERSIONS and resolved.suffix == ".sql":
            opened.add(resolved.name)
        return original(self, *args, **kwargs)  # type: ignore[arg-type]

    pathlib.Path.read_text = spy  # type: ignore[method-assign]
    try:
        yield opened
    finally:
        pathlib.Path.read_text = original  # type: ignore[method-assign]


def _wired_sidecars() -> set[str]:
    """import 시점에 실제로 읽힌 사이드카 ∪ 소스에 리터럴로 적힌 사이드카."""
    with _recording_sidecar_reads() as opened:
        for path in sorted(_VERSIONS.glob("*.py")):
            spec = importlib.util.spec_from_file_location(f"_lint_{path.stem}", path)
            assert spec is not None, path
            assert spec.loader is not None, path
            spec.loader.exec_module(importlib.util.module_from_spec(spec))

    literal: set[str] = set()
    for path in sorted(_VERSIONS.glob("*.py")):
        literal.update(_LITERAL_REFERENCE.findall(path.read_text(encoding="utf-8")))
    return opened | literal


def _is_unchanged(path: pathlib.Path) -> bool:
    return _UNCHANGED.search(path.read_text(encoding="utf-8")) is not None


def test_every_sidecar_is_either_wired_or_declared_unchanged() -> None:
    wired = _wired_sidecars()
    unwired: list[str] = []
    for path in sorted(_VERSIONS.glob("_*.sql")):
        assert _SIDECAR.match(path.name) is not None, (
            f"{path.name}은 사이드카 이름 규약 `_<rev>_<루틴이름>.sql`을 벗어난다. "
            "규약을 벗어나면 어느 마이그레이션의 것인지 알 수 없어 이 검사가 눈을 감는다."
        )
        if path.name not in wired and not _is_unchanged(path):
            unwired.append(path.name)

    assert not unwired, (
        "사이드카가 디스크에만 있고 마이그레이션이 읽지 않는다:\n  "
        + "\n  ".join(unwired)
        + "\n\n`_sidecar(...)`로 배선하거나, 손대지 않는 것이 판정이라면 파일 머리에 "
        "`-- 판정: 유지(무변경)`과 그 근거를 적어라. 배선 없이 놓아두면 마이그레이션은 "
        "초록인데 DB의 루틴은 옛 정의 그대로다."
    )


def test_unchanged_sidecars_are_never_wired() -> None:
    """무변경 선언과 배선이 동시에 있으면 둘 중 하나가 거짓말이다."""
    wired = _wired_sidecars()
    contradictions = [
        path.name
        for path in sorted(_VERSIONS.glob("_*.sql"))
        if _is_unchanged(path) and path.name in wired
    ]

    assert not contradictions, (
        "`판정: 유지(무변경)`인데 마이그레이션이 읽는다:\n  "
        + "\n  ".join(contradictions)
        + "\n\n무변경 사이드카는 head 원문의 거울이라 DDL로 발행할 물건이 아니다. "
        "실제로 바꿀 생각이면 판정 헤더부터 고쳐라."
    )


def test_every_sidecar_belongs_to_an_existing_migration() -> None:
    orphans = [
        path.name
        for path in sorted(_VERSIONS.glob("_*.sql"))
        if (match := _SIDECAR.match(path.name)) is not None
        and not list(_VERSIONS.glob(f"{match.group('rev')}_*.py"))
    ]

    assert not orphans, (
        "대응하는 마이그레이션 `.py`가 없는 사이드카:\n  "
        + "\n  ".join(orphans)
        + "\n\n마이그레이션이 사라졌거나 revision 접두가 어긋났다. 어느 쪽이든 이 파일은 "
        "영원히 실행되지 않는다."
    )
