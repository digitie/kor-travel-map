"""``KorTravelMapSettings`` 호환 alias/파생 속성 단위 테스트."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from kortravelmap.settings import KorTravelMapSettings

pytestmark = pytest.mark.unit


def test_object_store_key_aliases_track_canonical_fields() -> None:
    settings = KorTravelMapSettings(
        object_store_access_key_id=SecretStr("ak"),
        object_store_secret_access_key=SecretStr("sk"),
    )
    assert settings.object_store_access_key is not None
    assert settings.object_store_access_key.get_secret_value() == "ak"
    assert settings.object_store_secret_key is not None
    assert settings.object_store_secret_key.get_secret_value() == "sk"


def test_object_store_key_aliases_none_when_unset() -> None:
    settings = KorTravelMapSettings(
        object_store_access_key_id=None,
        object_store_secret_access_key=None,
    )
    assert settings.object_store_access_key is None
    assert settings.object_store_secret_key is None


def test_geo_public_api_key_stays_masked() -> None:
    secret = "geo-public-key"
    settings = KorTravelMapSettings(
        kor_travel_geo_api_key=SecretStr(secret),
    )

    assert settings.kor_travel_geo_api_key is not None
    assert settings.kor_travel_geo_api_key.get_secret_value() == secret
    assert secret not in repr(settings)


@pytest.mark.parametrize(
    ("unsafe_url", "secret_marker"),
    [
        ("http://alice:password@geo.example", "password"),
        ("https://geo.example/private-token", "private-token"),
        ("https://geo.example?token=query-secret", "query-secret"),
        ("https://geo.example#fragment-secret", "fragment-secret"),
        ("http://geo.example:SUPER-SECRET-PORT", "SUPER-SECRET-PORT"),
    ],
)
def test_geo_base_url_accepts_only_secret_free_origin(
    unsafe_url: str,
    secret_marker: str,
) -> None:
    with pytest.raises(ValidationError, match="HTTP\\(S\\) origin") as excinfo:
        KorTravelMapSettings(kor_travel_geo_base_url=unsafe_url)
    rendered = f"{excinfo.value}{excinfo.value!r}"
    assert unsafe_url not in rendered
    assert secret_marker not in rendered

    settings = KorTravelMapSettings(
        kor_travel_geo_base_url="https://geo.example/",
    )
    assert settings.kor_travel_geo_base_url is not None
    assert (
        settings.kor_travel_geo_base_url.get_secret_value()
        == "https://geo.example"
    )


def test_opinet_run_budget_preserves_daily_quota_for_two_datasets() -> None:
    """run 예산 상한이 **하루 전체**를 넘지 못한다.

    종전에는 700까지 허용했다 — 무료키 한도를 1,500으로 알고 있었기 때문이다.
    실제 한도는 **300/일**이고(2026-09-14 포털 확인, 1,500은 유료 프리미엄 값)
    한 run이 하루보다 많이 쓰게 설정할 수 있으면 안 된다. 산수 자체는
    `tests/lint/test_opinet_budget_fits_the_daily_limit.py`가 결박한다.
    """

    assert KorTravelMapSettings(opinet_run_call_budget=300).opinet_run_call_budget == 300
    with pytest.raises(ValidationError):
        KorTravelMapSettings(opinet_run_call_budget=301)


def test_provider_retry_budget_settings_are_bounded() -> None:
    settings = KorTravelMapSettings(
        provider_upstream_retry_budget_percent=7,
        provider_upstream_retry_budget_minimum=12,
    )
    assert settings.provider_upstream_retry_budget_percent == 7
    assert settings.provider_upstream_retry_budget_minimum == 12

    with pytest.raises(ValidationError):
        KorTravelMapSettings(provider_upstream_retry_budget_percent=-1)
    with pytest.raises(ValidationError):
        KorTravelMapSettings(provider_upstream_retry_budget_minimum=33)
