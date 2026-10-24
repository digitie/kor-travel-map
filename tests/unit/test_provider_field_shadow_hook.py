"""실제 원천 이름만 presence로 선언하며 native hook는 명시 scope/default OFF다."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from kortravelmap.providers.mcst import file_rows_to_bundles
from kortravelmap.settings import KorTravelMapSettings
from tests.unit.test_providers_mcst import _NOW, _world_restaurant_row


async def test_mcst_presence_does_not_invent_dto_defaults_or_geo_provenance() -> None:
    bundles = await file_rows_to_bundles(
        [_world_restaurant_row(), _world_restaurant_row(TITLE="다른 이름")],
        slug="world_restaurants_csv",
        fetched_at=_NOW,
    )
    assert bundles[0].provider_field_presence is bundles[1].provider_field_presence
    assert bundles[0].provider_field_presence.supplied_fields == frozenset({"core.name"})
    assert bundles[0].provider_field_presence.normalizer_revision == "mcst-name-v1"
    assert bundles[0].source_record.raw_data["TITLE"] == "과카몰레"


def test_shadow_settings_are_off_without_explicit_revision_and_scope() -> None:
    settings = KorTravelMapSettings(_env_file=None)
    assert settings.provider_field_shadow_policy_revision is None
    assert not settings.provider_field_shadow_scopes


@pytest.mark.parametrize("revision", [True, False, 0, -1])
def test_invalid_shadow_revision_is_rejected(revision: object) -> None:
    with pytest.raises(ValidationError):
        KorTravelMapSettings(provider_field_shadow_policy_revision=revision, _env_file=None)


@pytest.mark.parametrize("scopes", [[(" p", "dataset")], [("p", "")], [("p", "x" * 129)]])
def test_shadow_scopes_are_exact_canonical_pairs(scopes: object) -> None:
    with pytest.raises(ValidationError):
        KorTravelMapSettings(provider_field_shadow_scopes=scopes, _env_file=None)
