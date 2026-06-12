"""smoke 테스트 — `kortravelmap` import + `KorTravelMapSettings` 기본값.

Sprint 1 PR#17 scaffolding 검증. 후속 PR (#18~)에서 더 자세한 테스트 추가.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_kor_travel_map_import() -> None:
    """`import kortravelmap`이 성공하고 public 진입점이 노출된다."""
    import kortravelmap
    from kortravelmap.client import AsyncKorTravelMapClient

    assert hasattr(kortravelmap, "__version__")
    assert isinstance(kortravelmap.__version__, str)
    assert kortravelmap.__version__  # not empty
    assert kortravelmap.AsyncKorTravelMapClient is AsyncKorTravelMapClient
    assert "AsyncKorTravelMapClient" in kortravelmap.__all__


@pytest.mark.unit
def test_kor_travel_map_subpackages_importable() -> None:
    """6개 layer subpackage가 모두 `kortravelmap` 아래에서 import된다."""
    import kortravelmap.category  # noqa: F401
    import kortravelmap.client  # noqa: F401
    import kortravelmap.core  # noqa: F401
    import kortravelmap.dto  # noqa: F401
    import kortravelmap.infra  # noqa: F401
    import kortravelmap.providers  # noqa: F401


@pytest.mark.unit
def test_settings_default_values() -> None:
    """`KorTravelMapSettings()` 환경변수 없이 기본값으로 생성."""
    from kortravelmap.settings import KorTravelMapSettings

    settings = KorTravelMapSettings()

    # PostgreSQL DSN 기본값
    assert settings.pg_dsn.get_secret_value().startswith(
        "postgresql+asyncpg://"
    )
    # 객체 저장소 기본 bucket
    assert settings.object_store_bucket == "kor-travel-map"
    assert settings.offline_upload_max_bytes == 100 * 1024 * 1024
    # 로깅
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"
    # 옵션
    assert settings.log_api_calls is False


@pytest.mark.unit
def test_settings_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """``KOR_TRAVEL_MAP_*`` 환경변수가 우선 적용된다."""
    from kortravelmap.settings import KorTravelMapSettings

    monkeypatch.setenv("KOR_TRAVEL_MAP_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("KOR_TRAVEL_MAP_OBJECT_STORE_BUCKET", "custom-bucket")
    monkeypatch.setenv("KOR_TRAVEL_MAP_OFFLINE_UPLOAD_MAX_BYTES", "2048")
    monkeypatch.setenv("KOR_TRAVEL_MAP_LOG_API_CALLS", "true")

    settings = KorTravelMapSettings()

    assert settings.log_level == "DEBUG"
    assert settings.object_store_bucket == "custom-bucket"
    assert settings.offline_upload_max_bytes == 2048
    assert settings.log_api_calls is True


@pytest.mark.unit
def test_settings_secrets_are_secretstr() -> None:
    """secret 필드는 ``SecretStr``로 wrap되어 repr 노출 방지."""
    from pydantic import SecretStr

    from kortravelmap.settings import KorTravelMapSettings

    settings = KorTravelMapSettings()

    assert isinstance(settings.pg_dsn, SecretStr)
    # repr는 `**********` 형태로 마스킹
    assert "changeme" not in repr(settings.pg_dsn)
