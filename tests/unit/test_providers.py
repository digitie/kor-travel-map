"""``test_providers`` — provider name canonical 정규화 (PR#29, ADR-024/028)."""

from __future__ import annotations

import pytest

from kortravelmap.core.providers import (
    CANONICAL_PROVIDER_NAMES,
    PROVIDER_ALIASES,
    is_known_provider,
    normalize_provider_name,
)


@pytest.mark.unit
def test_canonical_names_include_core_providers() -> None:
    """필수 provider canonical name이 카탈로그에 박혀 있다."""
    required = {
        "python-visitkorea-api",
        "python-kma-api",
        "python-knps-api",
        "python-mois-api",  # ADR-024
        "python-opinet-api",
        "python-krex-api",
        "python-krheritage-api",
        "data.go.kr-standard",
    }
    assert required <= set(CANONICAL_PROVIDER_NAMES)


@pytest.mark.unit
def test_aliases_map_to_known_canonical() -> None:
    """모든 alias 값은 ``CANONICAL_PROVIDER_NAMES``에 있어야 한다."""
    canonical_set = set(CANONICAL_PROVIDER_NAMES)
    for alias, canonical in PROVIDER_ALIASES.items():
        assert canonical in canonical_set, (
            f"alias {alias!r} → {canonical!r}, but canonical 목록에 없음"
        )


@pytest.mark.unit
def test_normalize_canonical_passthrough() -> None:
    """canonical name은 그대로 반환."""
    assert normalize_provider_name("python-knps-api") == "python-knps-api"
    assert normalize_provider_name("data.go.kr-standard") == "data.go.kr-standard"


@pytest.mark.unit
def test_normalize_alias_resolves() -> None:
    """alias → canonical 매핑."""
    assert normalize_provider_name("knps") == "python-knps-api"
    assert normalize_provider_name("visitkorea") == "python-visitkorea-api"
    assert normalize_provider_name("kma") == "python-kma-api"
    # ADR-024 — krmois는 mois로 정정됨.
    assert normalize_provider_name("krmois") == "python-mois-api"
    assert normalize_provider_name("mois") == "python-mois-api"
    assert normalize_provider_name("python-krmois-api") == "python-mois-api"


@pytest.mark.unit
def test_normalize_rejects_unknown() -> None:
    """미지원 name은 ValueError (silent fallback 금지)."""
    with pytest.raises(ValueError, match="알 수 없는 provider"):
        normalize_provider_name("python-unknown-api")


@pytest.mark.unit
def test_normalize_rejects_empty() -> None:
    """빈 문자열 거부."""
    with pytest.raises(ValueError, match="비어"):
        normalize_provider_name("")


@pytest.mark.unit
def test_is_known_provider_lenient() -> None:
    """``is_known_provider``는 raise 없이 bool 반환."""
    assert is_known_provider("python-knps-api") is True
    assert is_known_provider("knps") is True  # alias
    assert is_known_provider("python-unknown-api") is False
    assert is_known_provider("") is False
