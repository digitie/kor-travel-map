"""smoke 테스트 — `krtour.map` import + `KrtourMapSettings` 기본값.

Sprint 1 PR#17 scaffolding 검증. 후속 PR (#18~)에서 더 자세한 테스트 추가.
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
def test_krtour_map_import() -> None:
    """`import krtour.map`이 성공하고 public 진입점이 노출된다."""
    import krtour.map
    from krtour.map.client import AsyncKrtourMapClient

    assert hasattr(krtour.map, "__version__")
    assert isinstance(krtour.map.__version__, str)
    assert krtour.map.__version__  # not empty
    assert krtour.map.AsyncKrtourMapClient is AsyncKrtourMapClient
    assert "AsyncKrtourMapClient" in krtour.map.__all__


@pytest.mark.unit
def test_krtour_map_subpackages_importable() -> None:
    """6개 layer subpackage가 모두 PEP 420 namespace로 import된다."""
    import krtour.map.category  # noqa: F401
    import krtour.map.client  # noqa: F401
    import krtour.map.core  # noqa: F401
    import krtour.map.dto  # noqa: F401
    import krtour.map.infra  # noqa: F401
    import krtour.map.providers  # noqa: F401


@pytest.mark.unit
def test_settings_default_values() -> None:
    """`KrtourMapSettings()` 환경변수 없이 기본값으로 생성."""
    from krtour.map.settings import KrtourMapSettings

    settings = KrtourMapSettings()

    # PostgreSQL DSN 기본값
    assert settings.pg_dsn.get_secret_value().startswith(
        "postgresql+asyncpg://"
    )
    # 객체 저장소 기본 bucket
    assert settings.object_store_bucket == "krtour-map"
    # 로깅
    assert settings.log_level == "INFO"
    assert settings.log_format == "json"
    # 옵션
    assert settings.log_api_calls is False


@pytest.mark.unit
def test_settings_env_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """``KRTOUR_MAP_*`` 환경변수가 우선 적용된다."""
    from krtour.map.settings import KrtourMapSettings

    monkeypatch.setenv("KRTOUR_MAP_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("KRTOUR_MAP_OBJECT_STORE_BUCKET", "custom-bucket")
    monkeypatch.setenv("KRTOUR_MAP_LOG_API_CALLS", "true")

    settings = KrtourMapSettings()

    assert settings.log_level == "DEBUG"
    assert settings.object_store_bucket == "custom-bucket"
    assert settings.log_api_calls is True


@pytest.mark.unit
def test_settings_secrets_are_secretstr() -> None:
    """secret 필드는 ``SecretStr``로 wrap되어 repr 노출 방지."""
    from pydantic import SecretStr

    from krtour.map.settings import KrtourMapSettings

    settings = KrtourMapSettings()

    assert isinstance(settings.pg_dsn, SecretStr)
    # repr는 `**********` 형태로 마스킹
    assert "changeme" not in repr(settings.pg_dsn)
