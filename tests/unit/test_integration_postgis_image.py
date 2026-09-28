"""통합 테스트 PostGIS 이미지 override 계약 (ADR-103).

``KTM_TEST_POSTGIS_IMAGE``가 없으면 alpine 기본값, 있으면 digest 참조만 받는다.
빈 값이나 tag를 조용히 기본값으로 바꾸면 glibc lane이 alpine에서 돌면서 초록이 된다.
"""

from __future__ import annotations

import pytest

from tests.integration._postgis_image import (
    ALPINE_POSTGIS_IMAGE,
    POSTGIS_IMAGE_ENV,
    SHARED_GLIBC_POSTGIS_IMAGE,
    resolve_postgis_image,
)

pytestmark = pytest.mark.unit


def test_absent_override_picks_the_alpine_baseline_digest() -> None:
    assert resolve_postgis_image({}) == ALPINE_POSTGIS_IMAGE


@pytest.mark.parametrize("image", [ALPINE_POSTGIS_IMAGE, SHARED_GLIBC_POSTGIS_IMAGE])
def test_digest_override_is_used_as_given(image: str) -> None:
    assert resolve_postgis_image({POSTGIS_IMAGE_ENV: image}) == image


@pytest.mark.parametrize(
    "value",
    [
        "",
        "postgis/postgis:16-3.5",
        "postgis/postgis:16-3.5@sha256:" + "8b33190b" * 8,
        "postgis/postgis@sha256:" + "8B33190B" * 8,
        "postgis/postgis@sha256:" + "8b33190b" * 7,
        "docker.io/postgis/postgis@sha256:" + "8b33190b" * 8,
        "other/postgis@sha256:" + "8b33190b" * 8,
        SHARED_GLIBC_POSTGIS_IMAGE + "\n",
        " " + SHARED_GLIBC_POSTGIS_IMAGE,
    ],
)
def test_present_but_malformed_override_fails(value: str) -> None:
    """있는데 모양이 틀리면 기본값으로 떨어지지 않고 실패한다."""

    with pytest.raises(ValueError, match=POSTGIS_IMAGE_ENV):
        resolve_postgis_image({POSTGIS_IMAGE_ENV: value})


def test_the_two_lanes_are_distinct_digests() -> None:
    """두 lane이 같은 이미지를 가리키면 glibc lane은 판별력이 없다."""

    assert ALPINE_POSTGIS_IMAGE != SHARED_GLIBC_POSTGIS_IMAGE
