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


def test_geo_admin_proxy_secret_stays_masked() -> None:
    secret = "geo-proxy-secret"
    settings = KorTravelMapSettings(
        kor_travel_geo_admin_proxy_secret=SecretStr(secret),
    )

    assert settings.kor_travel_geo_admin_proxy_secret is not None
    assert settings.kor_travel_geo_admin_proxy_secret.get_secret_value() == secret
    assert secret not in repr(settings)


def test_opinet_run_budget_preserves_daily_quota_for_two_datasets() -> None:
    assert KorTravelMapSettings(opinet_run_call_budget=700).opinet_run_call_budget == 700
    with pytest.raises(ValidationError):
        KorTravelMapSettings(opinet_run_call_budget=701)
