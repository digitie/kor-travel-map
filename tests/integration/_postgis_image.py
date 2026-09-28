"""통합 테스트 PostGIS 이미지의 단일 정본 (ADR-103).

기본은 immutable baseline을 만든 alpine(musl) digest다. n150 prod의 Map DB는
Manager 공용 instance로 옮겨 가고 그 instance는 glibc 이미지(default collation
``en_US.utf8``)를 쓴다. CI는 같은 suite를 그 digest에서도 돌리므로(``ci.yml``의
``integration`` matrix ``lane: glibc``), 이미지는 환경 변수
``KTM_TEST_POSTGIS_IMAGE``로 바꿀 수 있다.

**부재는 기본값을 고르는 것이다. 있는데 모양이 틀리면 실패다** — 빈 문자열이나
floating tag를 조용히 기본값으로 바꾸면 glibc lane이 alpine에서 돌면서 초록이 된다.
digest 참조만 받는다: tag는 같은 이름으로 다른 바이트를 가리킬 수 있다.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Final

#: 환경 변수 이름. CI matrix가 lane마다 이 값을 준다.
POSTGIS_IMAGE_ENV: Final = "KTM_TEST_POSTGIS_IMAGE"

#: 기본 lane(alpine, musl). immutable baseline이 이 이미지에서 만들어졌다.
ALPINE_POSTGIS_IMAGE: Final = (
    "postgis/postgis@sha256:dc17b064a946f64804d3b15e2ce90d01a444c02c9226a28a54764c083bd81a0c"
)

#: n150 공용 instance(``kor-travel-shared-postgres``)가 실제로 도는 glibc 이미지.
#: Manager가 이 digest를 고정한다(PG 16.9, PostGIS 3.5.2, ``en_US.utf8``). 공용
#: instance의 digest가 바뀌면 여기와 ``ci.yml``의 ``lane: glibc``를 함께 바꾼다
#: (``tests/unit/test_ci_workflows.py``가 두 값을 대조한다).
SHARED_GLIBC_POSTGIS_IMAGE: Final = (
    "postgis/postgis@sha256:8b33190b6486ab9905dea999171817c1ac461733a7078dd4c836091c6e6b5d40"
)

_DIGEST_REFERENCE: Final = re.compile(r"postgis/postgis@sha256:[0-9a-f]{64}")


def resolve_postgis_image(environ: Mapping[str, str] | None = None) -> str:
    """이번 실행의 PostGIS 이미지를 정한다.

    변수가 없으면 alpine 기본값, 있으면 ``postgis/postgis@sha256:<64 hex>``와
    완전히 일치해야 한다. 아니면 ``ValueError`` — 호출하는 fixture가 skip이 아니라
    실패로 드러낸다.
    """

    source = os.environ if environ is None else environ
    if POSTGIS_IMAGE_ENV not in source:
        return ALPINE_POSTGIS_IMAGE
    value = source[POSTGIS_IMAGE_ENV]
    if _DIGEST_REFERENCE.fullmatch(value) is None:
        raise ValueError(
            f"{POSTGIS_IMAGE_ENV}는 postgis/postgis@sha256:<64 hex> digest 참조여야 한다"
            f" (받은 값 {value!r})."
        )
    return value
