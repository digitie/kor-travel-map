"""기본 OFF는 원문 JSON 변환·DB 접근 없이 끝나며 supplied/null을 구별한다."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from kortravelmap.dto.provider_field_presence import ProviderFieldPresence
from kortravelmap.infra.provider_field_candidates import (
    arm_provider_field_shadow,
    capture_provider_field_candidates,
)


class _Result:
    def mappings(self) -> _Result:
        return self

    def one(self) -> dict[str, int]:
        return {"o_field_count": 2, "o_unresolved_count": 1}


class _Session:
    def __init__(self) -> None:
        self.info: dict[str, Any] = {}
        self.calls: list[dict[str, Any]] = []

    async def execute(self, _statement: Any, params: dict[str, Any]) -> _Result:
        self.calls.append(params)
        return _Result()


async def test_off_does_not_even_parse_json_or_call_database() -> None:
    session = _Session()
    result = await capture_provider_field_candidates(
        session,
        feature_id="unused",
        dataset_id=1,
        entity_key="e",
        record_key="r",
        values="not JSON",
        geometry_wkt="not JSON",
        presence=None,
    )
    assert result is None
    assert session.calls == []


async def test_unsupplied_dto_null_is_not_sent_as_explicit_null() -> None:
    session = _Session()
    arm_provider_field_shadow(session, 1)
    result = await capture_provider_field_candidates(
        session,
        feature_id="unused",
        dataset_id=1,
        entity_key="e",
        record_key="r",
        values='{"core.name":"name","place.biz_number":null}',
        geometry_wkt="{}",
        presence=ProviderFieldPresence(normalizer_revision="v1", supplied_fields={"core.name"}),
    )
    assert json.loads(session.calls[0]["values"]) == {"core.name": "name"}
    assert session.calls[0]["presence_proven"] is True
    assert result.unresolved_count == 1


@pytest.mark.parametrize("revision", [0, -1, True])
def test_invalid_shadow_revision_is_not_armed(revision: Any) -> None:
    with pytest.raises(ValueError, match="revision"):
        arm_provider_field_shadow(_Session(), revision)


@pytest.mark.parametrize("paths", [{""}, {" core.name"}, {"name"}])
def test_presence_requires_canonical_registry_paths(paths: set[str]) -> None:
    with pytest.raises(ValidationError):
        ProviderFieldPresence(normalizer_revision="v1", supplied_fields=paths)
