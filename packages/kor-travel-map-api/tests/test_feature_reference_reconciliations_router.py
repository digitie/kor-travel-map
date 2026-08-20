"""M05 Feature reference reconciliation service-route contract tests."""

from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import Request, Response
from kortravelmap.infra.feature_reference_reconciliation_repo import (
    FeatureReferenceReconciliationPreflight,
)

from kortravelmap.api.app import create_app
from kortravelmap.api.auth import FeatureReferenceReconciliationServiceContext
from kortravelmap.api.routers import feature_reference_reconciliations as router
from kortravelmap.api.settings import ApiSettings

_EVENT_ID = UUID("95000000-0000-4000-8000-000000000001")
_WORKER_ID = UUID("95000000-0000-4000-8000-000000000002")
_COMMAND_KEY = UUID("95000000-0000-4000-8000-000000000003")


class _Transaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, *args: object) -> None:
        return None


class _Session:
    def __init__(self) -> None:
        self.execute = AsyncMock()

    def begin(self) -> _Transaction:
        return _Transaction()


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/m05", "headers": []})


@pytest.mark.unit
def test_reconciliation_service_routes_are_mounted_in_openapi() -> None:
    spec = create_app(ApiSettings(public_api_key_required=False)).openapi()
    assert "/v1/service/feature-reference-reconciliations" in spec["paths"]
    ack = spec["paths"]["/v1/service/feature-reference-reconciliations/{event_id}/acks"]["post"]
    assert ack["responses"]["409"]
    assert ack["security"] == [{"ServiceToken": []}]


@pytest.mark.asyncio
async def test_semantic_ack_replay_preflights_before_domain_command_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preflight = AsyncMock(
        return_value=FeatureReferenceReconciliationPreflight(
            outcome="replayed", acked_through_sequence=11
        )
    )
    claim = AsyncMock(side_effect=AssertionError("new domain command must not be claimed"))
    monkeypatch.setattr(
        router.reconciliation_repo,
        "preflight_feature_reference_reconciliation_ack",
        preflight,
    )
    monkeypatch.setattr(router, "begin_domain_command", claim)
    session = _Session()
    response = Response()

    result = await router.ack_feature_reference_reconciliation_event_route(
        event_id=_EVENT_ID,
        body=router.FeatureReferenceReconciliationAckInput(
            worker_id=_WORKER_ID,
            lease_epoch=1,
            event_sha256="a" * 64,
            local_receipt_sha256="b" * 64,
        ),
        request=_request(),
        response=response,
        idempotency_key=_COMMAND_KEY,
        context=FeatureReferenceReconciliationServiceContext(
            actor="service:feature-reference-reconciliation",
            principal_id="service:feature-reference-reconciliation",
        ),
        session=session,  # type: ignore[arg-type]
    )

    assert isinstance(result, router.FeatureReferenceReconciliationAckResponse)
    assert result.data.outcome == "replayed"
    assert result.data.acked_through_sequence == 11
    assert response.headers["Idempotency-Replayed"] == "true"
    preflight.assert_awaited_once()
    claim.assert_not_awaited()
