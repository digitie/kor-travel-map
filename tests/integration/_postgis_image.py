"""통합 테스트 PostGIS 이미지의 단일 정본 (ADR-118, ADR-103).

통합 suite는 n150 공용 instance(``kor-travel-shared-postgres``)가 실제로 도는 이미지 하나에서
돈다 — PostgreSQL 18 + PostGIS 3.6, glibc(default collation ``en_US.utf8``). 2026-10-27
공용 PG가 16→18로 올랐고(Manager #562), ADR-118이 PG16 alpine·glibc 두 lane을 이 하나로
바꿨다. 이미지는 환경 변수 ``KTM_TEST_POSTGIS_IMAGE``로 바꿀 수 있다(다음 major 이행 lane용).

**부재는 기본값을 고르는 것이다. 있는데 모양이 틀리면 실패다** — 빈 문자열이나
floating tag를 조용히 기본값으로 바꾸면 이행 lane이 기본 이미지에서 돌면서 초록이 된다.
digest 참조만 받는다: tag는 같은 이름으로 다른 바이트를 가리킬 수 있다.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Final

#: 환경 변수 이름. CI matrix가 lane마다 이 값을 준다.
POSTGIS_IMAGE_ENV: Final = "KTM_TEST_POSTGIS_IMAGE"

#: n150 공용 instance(``kor-travel-shared-postgres``)가 실제로 도는 glibc 이미지이자 통합
#: suite의 기본값. 이 값은 Manager ``docker-compose.yml``의 공용 instance ``image:`` 기본값
#: (``postgis/postgis:18-3.6@sha256:…``)의 **사본**이고, 두 저장소 사이에는 drift 검출기가 없다.
#: 공용 이미지를 올릴 때는 한 변경 묶음으로 Manager 핀과 이 값, ``ci.yml``·``postgis-only.yml``의
#: matrix를 함께 바꾼다(``tests/unit/test_ci_workflows.py``가 workflow 쪽을 대조한다).
#: 2026-10-28 기준 PG 18.6, PostGIS 3.6.4, ``en_US.utf8``. 이 index에는 amd64만 있다.
SHARED_GLIBC_POSTGIS_IMAGE: Final = (
    "postgis/postgis@sha256:4a43e3c3e5d55b9208240fc71db543b79c638766280c625a425bd0a2390989c4"
)

_DIGEST_REFERENCE: Final = re.compile(r"postgis/postgis@sha256:[0-9a-f]{64}")


def resolve_postgis_image(environ: Mapping[str, str] | None = None) -> str:
    """이번 실행의 PostGIS 이미지를 정한다.

    변수가 없으면 공용 instance 기본값, 있으면 ``postgis/postgis@sha256:<64 hex>``와
    완전히 일치해야 한다. 아니면 ``ValueError`` — 호출하는 fixture가 skip이 아니라
    실패로 드러낸다.
    """

    source = os.environ if environ is None else environ
    if POSTGIS_IMAGE_ENV not in source:
        return SHARED_GLIBC_POSTGIS_IMAGE
    value = source[POSTGIS_IMAGE_ENV]
    if _DIGEST_REFERENCE.fullmatch(value) is None:
        raise ValueError(
            f"{POSTGIS_IMAGE_ENV}는 postgis/postgis@sha256:<64 hex> digest 참조여야 한다"
            f" (받은 값 {value!r})."
        )
    return value
