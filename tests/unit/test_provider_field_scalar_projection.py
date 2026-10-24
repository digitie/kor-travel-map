"""scoped opt-in은 정책/manifest 경계를 명시하고 기존 OFF를 보존한다."""

from __future__ import annotations

from typing import Any

import pytest

from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.infra.provider_field_candidates import (
    arm_provider_field_shadow,
    capture_provider_field_candidates,
    recompute_provider_field_candidates,
)


class _Result:
    def mappings(self) -> _Result:
        return self

    def one(self) -> dict[str, int]:
        return {"o_field_count": 1, "o_unresolved_count": 0}


class _Session:
    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any]) -> _Result:
        self.calls.append((str(statement), params))
        return _Result()


async def test_explicit_scoped_capture_cannot_silently_fall_back_to_off() -> None:
    session = _Session()
    with pytest.raises(ValueError, match="정책"):
        await capture_provider_field_candidates(
            session,
            feature_id="unused",
            dataset_id=1,
            entity_key="e",
            record_key="r",
            values="not JSON",
            geometry_wkt="not JSON",
            presence=None,
            attempt_id="applying",
        )
    assert session.calls == []


async def test_scoped_capture_keeps_presence_and_manifest_identity() -> None:
    session = _Session()
    arm_provider_field_shadow(session, 3)
    result = await capture_provider_field_candidates(
        session,
        feature_id="feature",
        dataset_id=1,
        entity_key="source",
        record_key="r2",
        values='{"core.name":"new","place.phones":null}',
        geometry_wkt="{}",
        presence=ProviderFieldPresence(
            normalizer_revision="explicit-v1", supplied_fields={"core.name"}
        ),
        attempt_id="applying",
    )
    statement, params = session.calls[0]
    assert "record_scoped_provider_field_candidates" in statement
    assert params["attempt_id"] == "applying"
    assert params["policy_revision"] == 3
    assert params["values"] == '{"core.name": "new"}'
    assert params["presence_proven"] is True
    assert result is not None
    assert result.unresolved_count == 0


@pytest.mark.parametrize("revision", [True, 0, -1])
async def test_invalid_projection_revision_has_no_database_effect(revision: Any) -> None:
    session = _Session()
    with pytest.raises(ValueError, match="revision"):
        await recompute_provider_field_candidates(
            session,
            attempt_id="attempt",
            feature_id="feature",
            policy_revision=revision,
        )
    assert session.calls == []
