"""alembic revision id가 `alembic_version.version_num`에 들어가는지 검사한다.

## 왜

`public.alembic_version.version_num`은 `varchar(32)`다. 그보다 긴 revision id를 쓰면
migration DDL은 **전부 성공한 뒤** 마지막 stamp에서 죽는다:

    StringDataRightTruncationError: value too long for type character varying(32)
    [SQL: UPDATE alembic_version SET version_num='308_t39_provider_feature_identities' ...]

2026-09-09에 35자 이름으로 통합 전량이 **setup error로 뒤덮였다**. 그 진단은
revision 이름이 길다는 말을 하지 않는다 — SQL 문에 값이 실려 있을 뿐이고, 읽는 사람은
"내가 만든 표의 어떤 컬럼이 32자를 넘었나"를 먼저 의심한다.

DB에 닿기 전에 잡는다.

## 32가 어디서 오는가

`alembic_version` 표는 alembic이 만들고, 이 저장소는 handoff 경로에서 그것을 직접
`CREATE TABLE`한다 — 그 DDL의 `varchar(32)`가 정본이다. 그래서 상수를 박지 않고
**그 DDL에서 읽는다.** 폭이 바뀌면 이 검사가 따라간다.
"""

from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[2]
_VERSIONS = _ROOT / "alembic" / "versions"

#: `alembic_version.version_num`의 폭을 선언하는 **정본**. alembic이 version table을
#: 만드는 자리이고, 저장소의 어떤 파일도 그 사본일 뿐이다. 사본을 읽으면 사본이 낡는
#: 날 이 검사가 조용히 낡은 폭을 지킨다.
def _alembic_impl_source() -> pathlib.Path:
    import alembic.ddl.impl

    return pathlib.Path(alembic.ddl.impl.__file__)


_WIDTH_SOURCES = (_alembic_impl_source(),)

#: 두 형태를 모두 받는다 — alembic의 `Column("version_num", String(32), ...)`와
#: 그것을 SQL로 적은 `version_num varchar(32)`.
_WIDTH_PATTERN = re.compile(
    r"""version_num["']?[\s,]+(?:String\(|varchar\()(\d+)\)""",
    re.IGNORECASE,
)
#: 선언 형태가 두 가지다 — `revision: str = ...`(300~302)와
#: `revision: Final[str] = ...`(303~). `Final[str]`만 보면 앞 셋을 놓치고, 그러면
#: 이 검사는 **조용히 절반만** 본다(2026-09-09 첫 구현에서 실제로 그랬다).
#: 그래서 주석(annotation)을 통째로 흘려보낸다.
_REVISION_PATTERN = re.compile(r'^revision\s*:[^=]*=\s*"([^"]+)"', re.MULTILINE)
_DOWN_PATTERN = re.compile(r'^down_revision\s*:[^=]*=\s*"([^"]+)"', re.MULTILINE)


def _declared_width() -> int | None:
    for source in _WIDTH_SOURCES:
        if not source.is_file():
            continue
        found = _WIDTH_PATTERN.search(source.read_text(encoding="utf-8"))
        if found:
            return int(found.group(1))
    return None


def _revisions() -> dict[str, tuple[str, str | None]]:
    """`{파일명: (revision, down_revision)}`."""

    found: dict[str, tuple[str, str | None]] = {}
    for path in sorted(_VERSIONS.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        revision = _REVISION_PATTERN.search(text)
        if revision is None:
            continue
        down = _DOWN_PATTERN.search(text)
        found[path.name] = (revision.group(1), down.group(1) if down else None)
    return found


_WIDTH = _declared_width()
_REVISIONS = _revisions()


def test_the_width_is_read_from_a_live_declaration() -> None:
    """폭을 상수로 박지 않는다 — 선언에서 읽는다."""

    assert _WIDTH is not None, (
        "`version_num` 폭 선언을 찾지 못했다 — alembic이 version table을 만드는 "
        f"자리가 옮겨졌거나 형태가 바뀌었다: {[str(source) for source in _WIDTH_SOURCES]}"
    )
    assert _WIDTH == 32, f"폭이 {_WIDTH}로 바뀌었다 — 이 검사의 전제를 갱신하라"


def test_the_versions_directory_is_live() -> None:
    """파일 수와 파싱된 revision 수가 **같아야** 한다.

    "8개 이상"으로 재면 파서가 절반만 봐도 통과한다. 디렉터리의 실제 파일 수와
    대조해야 파서가 눈을 감는 순간이 빨개진다.
    """

    modules = sorted(
        path.name for path in _VERSIONS.glob("*.py") if path.name != "__init__.py"
    )
    assert modules, "alembic/versions에 migration이 없다 — 경로가 옮겨졌다"
    unparsed = sorted(set(modules) - set(_REVISIONS))
    assert unparsed == [], (
        f"이 파일들에서 revision 선언을 읽지 못했다 — 파서가 선언 형태를 못 본다: {unparsed}"
    )


def test_every_revision_id_fits_the_version_column() -> None:
    width = _WIDTH or 32
    too_long = {
        name: (revision, len(revision))
        for name, (revision, _) in _REVISIONS.items()
        if len(revision) > width
    }
    assert too_long == {}, (
        f"revision id가 `alembic_version.version_num varchar({width})`를 넘는다. "
        "migration은 DDL을 전부 성공시킨 뒤 마지막 stamp에서 "
        "`StringDataRightTruncationError`로 죽고, 그 진단은 revision 이름을 가리키지 "
        f"않는다(2026-09-09 실측).\n{too_long}"
    )


def test_every_down_revision_points_at_a_declared_revision() -> None:
    """길이를 고치느라 이름을 바꿀 때 `down_revision`을 빠뜨리면 체인이 끊긴다."""

    declared = {revision for revision, _ in _REVISIONS.values()}
    dangling = {
        name: down
        for name, (_, down) in _REVISIONS.items()
        if down is not None and down not in declared
    }
    assert dangling == {}, f"down_revision이 존재하지 않는 revision을 가리킨다: {dangling}"
