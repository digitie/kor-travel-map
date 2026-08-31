"""봉인된 destination facet 계약이 revision 값을 다시 얼리지 못하게 한다.

## 무엇이 문제였나

`alembic/baseline/application-destination-alembic-version.sql`의 마지막 조건이
``alembic_version = ARRAY['300']``이었다.

이 SQL의 산출물은 **단일 boolean**이다 — 성공이면
``kor-travel-map.application-destination-alembic-version.v1``, 아니면 ``…mismatch``
한 줄. 기대 digest는 성공 sentinel 문자열의 sha256일 뿐이고, 스키마 상태를 담지 않는다.

그래서 revision 값을 이 안에 넣으면 두 가지가 동시에 일어났다.

1. migration을 하나 더하는 순간 이 facet은 **영원히 mismatch**가 된다. 옮겨갈 digest가
   존재하지 않는다 — sentinel은 성공/실패 두 값뿐이다.
2. 조건 스무 개 중 무엇이 거짓인지 구분되지 않는다. ACL이 틀렸는지 revision이 다른지
   같은 `mismatch` 하나로 나온다.

`301`을 얹자 fresh installer·finalize·final-permit 셋이 동시에 막혔고, 원인이 이것이었다.

## 무엇으로 대체했나

revision 동등성은 호출자가 **파생 head**로 대조한다 — 배포 executable 넷이 모두
``versions != (head,)``를 이미 강제하며, 얼린 리터럴보다 강하다(현재 graph에서 유도한
값과 비교한다). facet은 ACL/identity만 증명한다.

이 게이트는 그 분리를 되돌리지 못하게 한다.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "alembic" / "baseline"
DOCKER_DIR = REPO_ROOT / "docker"

_DESTINATION_FACET = BASELINE / "application-destination-alembic-version.sql"
_SOURCE_FACET = BASELINE / "application-source-alembic-version.sql"

_VERSION_PREDICATE = re.compile(
    r"alembic_version[^;]{0,200}?ARRAY\s*\[", re.IGNORECASE | re.DOTALL
)


def _statements(source: str) -> str:
    """`--` 주석 줄을 뺀 SQL 본문."""
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("--")
    )


def test_destination_facet_does_not_pin_a_revision_value() -> None:
    """**이 게이트의 본체.**

    destination facet은 head가 움직여도 살아 있어야 한다. revision 값을 넣으면 그
    순간 이 계약은 영원히 mismatch가 되고, 기대 digest는 sentinel 해시라 옮겨갈 곳이
    없다.
    """
    body = _statements(_DESTINATION_FACET.read_text(encoding="utf-8"))

    assert _VERSION_PREDICATE.search(body) is None, (
        "destination facet이 alembic_version 값을 술어에 넣었다 — 이 SQL은 단일 boolean "
        "sentinel이라 head가 움직이면 영원히 mismatch가 된다. revision 동등성은 배포 "
        "executable이 파생 head로 대조한다."
    )


def test_the_expected_digest_is_the_success_sentinel() -> None:
    """기대 digest가 상태가 아니라 sentinel의 해시임을 못 박는다.

    이 사실이 위 게이트의 근거다 — 조건을 하나 빼도 **기대 digest가 바뀌지 않는다**는
    것을 여기서 직접 보인다. 누군가 "digest를 다시 계산해야 하지 않나"라고 물을 때의
    답이기도 하다.
    """
    import hashlib

    sentinel = "kor-travel-map.application-destination-alembic-version.v1"
    digest = hashlib.sha256()
    digest.update(sentinel.encode("utf-8"))
    digest.update(b"\n")
    recorded = (BASELINE / "application-destination-alembic-version.sha256").read_text(
        encoding="utf-8"
    ).strip()

    assert recorded == digest.hexdigest()


def test_source_facet_may_still_pin_the_retired_revision() -> None:
    """source facet은 반대로 값을 고정하는 것이 **맞다.**

    그것은 `0236`이라는 retired source 상태를 서술하는 계약이고, 그 상태는 정의상
    움직이지 않는다. 두 파일을 같은 규칙으로 묶으면 안 된다.
    """
    body = _statements(_SOURCE_FACET.read_text(encoding="utf-8"))

    assert _VERSION_PREDICATE.search(body) is not None, (
        "source facet에서 revision 고정이 사라졌다 — retired `0236` 상태 서술이므로 "
        "값을 고정하는 것이 맞다"
    )


_HEAD_EQUALITY_CONSUMERS = (
    "application-schema-fresh-300.py",
    "application-schema-fresh-finalize.py",
    "application-schema-final-permit.py",
    "transition-application-schema-0236-to-300.py",
)


@pytest.mark.parametrize("name", _HEAD_EQUALITY_CONSUMERS)
def test_every_consumer_still_asserts_exact_revision_equality(name: str) -> None:
    """facet에서 뺀 성질이 **실제로 다른 곳에 있는지** 확인한다.

    "호출자가 이미 본다"는 주장이 사실이 아니면 이 변경은 순수한 약화다. 주장을
    코드로 고정한다.
    """
    source = (DOCKER_DIR / name).read_text(encoding="utf-8")

    assert re.search(r"versions\s*!=\s*\(_?\w*HEAD\w*,\)", source) or re.search(
        r"expected_head\s*=\s*_\w*HEAD", source
    ), (
        f"{name}이 raw revision 동등성을 대조하지 않는다 — facet에서 뺀 성질을 "
        "여기서 잃으면 순수한 약화다"
    )
