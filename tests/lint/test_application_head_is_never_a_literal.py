"""application head 리터럴이 배포 자산 어디에도 남지 않게 한다 — 전수, 값 기준.

## 이 파일이 왜 따로 있는가

`test_application_schema_head_single_source.py`는 head **정본**이 하나임을 지킨다.
이 파일은 그 정본을 우회하는 리터럴이 **어디에도 없음**을 지킨다. 두 성질은 다르고,
후자를 종전 방식으로 지키려다 세 번 연속으로 뚫렸다.

## 무엇이 뚫렸는가

스캔을 `docker/` 넷 → 여섯 → `docker/`+`scripts/` 82개로 넓혔지만, 적대 리뷰가 **실행으로**
열네 가지를 우회했다. 뚫린 방식이 전부 같은 뿌리를 갖는다 — **열거**다.

| 우회 | 뿌리 |
|---|---|
| `scripts/lib/application-head-guard.sh` | `iterdir()`이 한 단계만 |
| `docker/api.Dockerfile`의 `ENV …EXPECTED_HEAD="300"` | 확장자 `.py`/`.sh`만 |
| `--expected-head "300"` (줄 시작이 `--`) | SQL 주석용 `startswith("--")` 스킵 |
| `EXPECTED_HEAD="300"` 뒤 `!= "$EXPECTED_HEAD"` | 비교 토큰 목록 |
| `SUPPORTED_HEADS = (\n "300",\n)` | 같은 줄에 비교가 없음 |

마지막 둘이 특히 중요하다. **리터럴과 비교를 다른 줄에 두는 것은 우회가 아니라 그냥
평범한 코드다.** 그러니 "비교에 쓰였나"를 묻는 규칙은 원리적으로 완결될 수 없다.

## 그래서 규칙을 바꾼다

묻는 것을 바꾼다 — **"리터럴이 비교에 쓰였나"가 아니라 "리터럴이 존재하나"**다.
존재만 보면 토큰 목록도, 줄 단위 문맥도, 포매터 reflow도 무관해진다.

훑는 대상도 바꾼다 — `rglob`으로 하위 디렉터리까지, 확장자 목록 대신 **텍스트로 읽히는
모든 파일**을. Dockerfile·compose·`.env*`·확장자 없는 실행 스크립트가 전부 들어온다.

정당한 baseline root 언급은 파일 단위로 **사유와 함께** 면제한다. 면제 목록에 죽은
항목이 있으면 실패한다 — 새 파일이 남의 면제를 물려받지 못한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kortravelmap.infra.application_schema_head import BASELINE_ROOT_REVISION

REPO_ROOT = Path(__file__).resolve().parents[2]

_SCANNED_TREES = ("docker", "scripts")

_SKIPPED_DIRECTORIES = frozenset({"__pycache__", "node_modules", ".venv", "dist", ".next"})

#: 텍스트가 아닌 것만 뺀다. 확장자 allowlist를 쓰면 그 목록이 다시 사각지대가 된다.
_BINARY_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".docx", ".xlsx", ".zip", ".gz", ".whl"}
)

#: 숫자 300이 다른 뜻으로 쓰이는 자리(초, 픽셀, HTTP 코드)와 구분하기 위해 **따옴표로
#: 감싼 형태**만 본다. head는 문자열이므로 코드에서는 반드시 따옴표를 두른다.
#: `.env`/Dockerfile의 `=300` 형태는 아래에서 따로 본다.
_QUOTED = re.compile(rf"""["']{re.escape(BASELINE_ROOT_REVISION)}["']""")
_ENV_ASSIGNMENT = re.compile(
    rf"KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD\s*[=:]\s*[\"']?{re.escape(BASELINE_ROOT_REVISION)}"
)

_EXEMPT: dict[str, str] = {
    "build-baseline.sh": (
        "baseline 제작기. 정의상 `300` baseline만 만든다 — 다른 head의 baseline은 "
        "재squash라는 별도 결정이다."
    ),
    "create-application-300-fresh-oracle.sh": (
        "`0236 → 300` baseline artifact 검증용 disposable oracle. 검증 대상이 baseline "
        "그 자체이므로 목적지가 baseline root다."
    ),
    "create-application-0236-source-oracle.sh": (
        "retired `0236` source oracle. baseline 재봉인 입력이며 head와 무관하다."
    ),
    "rehearse-application-300-handoff.sh": (
        "`0236 → 300` handoff 리허설. handoff의 목적지가 baseline root다."
    ),
    "build-application-300-paired-candidate.sh": (
        "paired candidate receipt의 `forbidden_application_raw_revision`은 'Dagster "
        "metadata DB는 application raw revision을 갖지 않는다'는 격리 선언이며 baseline "
        "root를 가리킨다 — head가 아니다."
    ),
    "build-application-300-candidate.sh": (
        "candidate 이미지 제작기. baseline root 산출물을 다룬다."
    ),
    "transition-application-schema-0236-to-300.py": (
        "handoff executable. stamp 목적지가 baseline root이며 "
        "`test_handoff_stamps_the_baseline_root_not_the_head`가 따로 고정한다."
    ),
    "application-schema-fresh-300.py": (
        "baseline root 도달 여부로 분기한다. 리터럴이 아니라 "
        "`BASELINE_ROOT_REVISION` 상수를 쓰지만, 봉인 실패 메시지에 `300`이 문자열로 "
        "들어간다."
    ),
    "dagster-storage-migrate.py": (
        "`_BASELINE_ROOT_REVISION` 선언 한 줄. Dagster metadata DB가 application raw "
        "revision을 갖지 않는다는 격리 판정에 쓰이며 head가 아니다."
    ),
}


def _scanned_files() -> list[Path]:
    """배포 자산 전체 — 하위 디렉터리 포함, 확장자 무관."""
    files: list[Path] = []
    for tree in _SCANNED_TREES:
        root = REPO_ROOT / tree
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if _SKIPPED_DIRECTORIES.intersection(path.relative_to(root).parts):
                continue
            if path.suffix.lower() in _BINARY_SUFFIXES:
                continue
            files.append(path)
    return files


def _text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def test_the_scan_actually_reaches_files() -> None:
    """스캔이 비어 있으면 아래 게이트는 조용히 무의미해진다.

    `iterdir()`을 `rglob()`으로 바꾸면서 경로를 한 번 잘못 쓰면 offenders가 항상 빈
    리스트가 되고, 모든 단언이 통과한다. 그 상태를 직접 막는다.
    """
    files = _scanned_files()

    assert len(files) > 50, f"배포 자산 스캔이 {len(files)}개만 찾았다 — 경로가 틀렸다"
    names = {path.name for path in files}
    # 하위 디렉터리가 실제로 들어오는지 이름으로 확인한다.
    assert any(path.parent.name == "lib" for path in files), (
        "`scripts/lib/`가 스캔에 없다 — 재귀가 동작하지 않는다"
    )
    assert "api.Dockerfile" in names, "Dockerfile이 스캔에 없다 — 확장자 필터가 남아 있다"
    assert "api-entrypoint.sh" in names


def test_no_deploy_asset_contains_the_head_literal() -> None:
    """**이 게이트의 본체.**

    비교인지 대입인지 묻지 않는다. 배포 자산에 `"300"` 문자열이 있으면 그 자체로
    실패다 — head는 파생값이어야 하고, 파생값을 쓰는 코드에는 이 리터럴이 나타날
    이유가 없다.
    """
    offenders: list[str] = []
    for path in _scanned_files():
        if path.name in _EXEMPT:
            continue
        source = _text(path)
        if source is None:
            continue
        for number, line in enumerate(source.splitlines(), 1):
            if _QUOTED.search(line) or _ENV_ASSIGNMENT.search(line):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT).as_posix()}:{number}: {line.strip()[:88]}"
                )

    assert not offenders, (
        "배포 자산에 application head 리터럴이 있다. head는 "
        "`kortravelmap.infra.application_schema_head.application_schema_head()`에서 "
        "파생해야 한다. baseline root를 가리키는 정당한 언급이라면 `_EXEMPT`에 **사유와 "
        "함께** 선언할 것:\n  " + "\n  ".join(offenders)
    )


def test_every_exemption_is_alive_and_reasoned() -> None:
    """면제는 실재하는 파일에만, 사유와 함께.

    죽은 항목이 남으면 새 파일이 그 이름을 물려받아 조용히 면제된다.
    """
    names = {path.name for path in _scanned_files()}
    dead = sorted(set(_EXEMPT) - names)
    empty = sorted(name for name, reason in _EXEMPT.items() if len(reason.strip()) < 20)

    assert not dead, f"면제 목록에 존재하지 않는 파일: {dead}"
    assert not empty, f"사유가 없거나 부실한 면제: {empty}"


def test_every_exemption_actually_needs_it() -> None:
    """면제됐지만 리터럴이 없는 파일은 목록에서 빼야 한다.

    쓸모없는 면제가 쌓이면 목록이 검토 대상이 아니라 배경 소음이 된다.
    """
    unnecessary: list[str] = []
    for path in _scanned_files():
        if path.name not in _EXEMPT:
            continue
        source = _text(path)
        if source is None:
            continue
        if not _QUOTED.search(source) and not _ENV_ASSIGNMENT.search(source):
            unnecessary.append(path.name)

    assert not unnecessary, (
        f"리터럴이 없는데 면제된 파일 — 목록에서 뺄 것: {sorted(unnecessary)}"
    )


@pytest.mark.parametrize(
    ("shape", "line", "previous"),
    [
        ("CLI 장옵션", '    --expected-head "300" \\', "    verify \\"),
        ("변수 대입", 'EXPECTED_HEAD="300"', ""),
        ("Dockerfile ENV", 'ENV KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD="300"', ""),
        ("멤버십 튜플", '    "300",', "SUPPORTED_HEADS = ("),
        ("SQL IN", "    CHECK (head IN ('300'))", ""),
        ("compose env", "      KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD: 300", ""),
        ("dotenv", "KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD=300", ""),
    ],
)
def test_the_rule_catches_every_shape_that_bypassed_the_old_one(
    shape: str, line: str, previous: str
) -> None:
    """적대 리뷰가 뚫은 형태를 하나씩 되짚는다.

    게이트를 고쳤다는 주장은 "고친 코드가 통과한다"가 아니라 "뚫렸던 형태가 이제
    걸린다"로 증명해야 한다. `previous`는 종전 규칙이 앞 줄 문맥에 의존했음을 남겨 둔
    것이며, 새 규칙은 그것을 보지 않는다 — 그 무관함 자체가 요점이다.
    """
    del previous, shape

    assert _QUOTED.search(line) or _ENV_ASSIGNMENT.search(line)
