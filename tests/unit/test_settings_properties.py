"""``KorTravelMapSettings`` 호환 alias/파생 속성 단위 테스트."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

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


def test_geo_api_key_value_strips_and_returns_none_for_blank() -> None:
    assert (
        KorTravelMapSettings(
            kor_travel_geo_api_key=SecretStr("  vkey  ")
        ).kor_travel_geo_api_key_value
        == "vkey"
    )
    assert (
        KorTravelMapSettings(kor_travel_geo_api_key=SecretStr("   ")).kor_travel_geo_api_key_value
        is None
    )
    assert KorTravelMapSettings(kor_travel_geo_api_key=None).kor_travel_geo_api_key_value is None
