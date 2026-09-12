"""prod 이미지에 구워지는 Python 스크립트가 전부 `mypy --strict` 아래인지 결박한다.

이 스크립트들은 프로덕션 컨테이너 안에서 돌며 **모든 rebuild를 게이트한다** — schema
head 계약, 최종 permit, fresh bootstrap, Dagster storage migration. 그런데 2026-09-13
까지 CI mypy는 `kortravelmap` 세 패키지와 D2 lane만 봤다.

같은 날 그중 하나(`dagster-storage-migrate.py`)가 prod 스택을 두 번 내렸다. 두 번 다
타입이 아니라 계약 문제였다 — 봉인된 key 집합이 config와 어긋난 것, 그리고 그 봉인이
자기 config를 거부한 것. 타입 검사가 그 둘을 잡지는 못했을 것이다. **그럼에도 이
경계를 옮기는 이유는 그 사건이 이 파일들이 얼마나 결정적인지를 보여 줬기 때문이고,
D2 lane을 편입한 것과 정확히 같은 논리다**(그쪽도 프로덕션 DB에 직접 쓴다는 이유였다).

목록을 손으로 적지 않고 **Dockerfile의 COPY에서 유도한다.** 이미지에 들어가는 것이
곧 프로덕션에서 도는 것이다. 스크립트가 늘면 이 게이트가 mypy 스텝도 함께 늘라고
말한다(AGENTS.md DO NOT 15: 유도 → 결박 → 탐지).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / ".github" / "workflows" / "lint.yml"

#: `COPY --chown=root:root docker/dagster-storage-migrate.py /usr/local/bin/...`
_COPIED = re.compile(
    r"^COPY\s+(?:--\S+\s+)*(?P<path>docker/[\w.-]+\.py)\s", re.MULTILINE
)


def _baked_scripts() -> list[str]:
    """prod Dockerfile이 이미지에 넣는 Python 스크립트를 소스에서 유도한다."""
    found: set[str] = set()
    for dockerfile in sorted((_ROOT / "docker").glob("*.Dockerfile")):
        text = dockerfile.read_text(encoding="utf-8")
        found |= {match.group("path") for match in _COPIED.finditer(text)}
    return sorted(found)


def test_the_dockerfiles_bake_at_least_one_python_script() -> None:
    """유도의 전제. 하나도 못 찾으면 아래 검사가 조용히 항진명제가 된다."""
    assert _baked_scripts(), (
        "`docker/*.Dockerfile`에서 COPY되는 Python 스크립트를 찾지 못했다 — "
        "COPY 구문이 바뀌었거나 이 게이트의 파서가 낡았다. 어느 쪽이든 아래 검사가 "
        "아무것도 재지 않는 상태다."
    )


def test_every_baked_script_is_type_checked_in_ci() -> None:
    """이미지에 들어가는 것은 전부 mypy 스텝에 있다."""
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    missing = [script for script in _baked_scripts() if script not in workflow]
    assert not missing, (
        f"prod 이미지에 구워지는데 CI mypy 스텝에 없는 스크립트: {missing}. "
        "이 파일들은 프로덕션 컨테이너 안에서 돌며 rebuild를 게이트한다 — "
        "`.github/workflows/lint.yml`의 mypy 스텝에 더해라."
    )


def test_the_mypy_step_does_not_name_scripts_that_are_not_baked() -> None:
    """반대 방향도 본다 — 목록이 낡아 없는 파일을 가리키면 스텝이 즉시 실패한다.

    그러면 CI가 빨개져 누군가 고치겠지만, 그 빨강은 "타입 오류"로 읽힌다. 여기서
    잡으면 "목록이 낡았다"로 읽힌다 — 같은 결함을 다른 이름으로 말하는 검사가
    다음 사람을 잘못된 곳으로 보낸다.
    """
    workflow = _WORKFLOW.read_text(encoding="utf-8")
    named = set(re.findall(r"(docker/[\w.-]+\.py)", workflow))
    baked = set(_baked_scripts())
    stale = sorted(named - baked)
    assert not stale, (
        f"CI mypy 스텝이 이미지에 없는 스크립트를 가리킨다: {stale}. "
        "파일이 옮겨졌거나 지워졌다."
    )
