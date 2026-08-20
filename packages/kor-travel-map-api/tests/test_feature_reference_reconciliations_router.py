"""M05 Feature reference reconciliation service-route contract tests."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi import Request, Response
from kortravelmap.infra.feature_reference_reconciliation_repo import (
    FeatureReferenceReconciliationPreflight,
    FeatureReferenceReconciliationSubscriptionProvision,
    ManualProviderDedupCase,
    ManualProviderDedupCaseResolution,
)

from kortravelmap.api.app import create_app
from kortravelmap.api.auth import FeatureReferenceReconciliationServiceContext
from kortravelmap.api.domain_command_service import DomainCommandHandle
from kortravelmap.api.routers import feature_reference_reconciliations as router
from kortravelmap.api.settings import ApiSettings

_EVENT_ID = UUID("95000000-0000-4000-8000-000000000001")
_WORKER_ID = UUID("95000000-0000-4000-8000-000000000002")
_COMMAND_KEY = UUID("95000000-0000-4000-8000-000000000003")
_CASE_ID = UUID("95000000-0000-4000-8000-000000000004")
_RESOLUTION_ID = UUID("95000000-0000-4000-8000-000000000005")


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


def _admin_context() -> router.AdminProxyContext:
    return router.AdminProxyContext(actor="admin:reviewer")


def _case(case_id: UUID = _CASE_ID) -> ManualProviderDedupCase:
    return ManualProviderDedupCase(
        case_id=case_id,
        status="pending",
        created_at=datetime(2026, 8, 21, 12, tzinfo=UTC),
        evidence_fingerprint="c" * 64,
        manual_feature={
            "feature_id": "manual-1",
            "feature_uuid": str(_EVENT_ID),
            "row_revision": 3,
            "snapshot": {},
        },
        provider_feature={
            "feature_id": "provider-1",
            "feature_uuid": str(_WORKER_ID),
            "row_revision": 4,
            "snapshot": {},
        },
        scores={
            "scorer_id": "m05",
            "scorer_input_sha256": "d" * 64,
            "name_score": 1.0,
            "spatial_score": 1.0,
            "category_score": 1.0,
            "total_score": 1.0,
            "distance_meters": 0.0,
        },
    )


@pytest.mark.unit
def test_reconciliation_service_routes_are_mounted_in_openapi() -> None:
    spec = create_app(ApiSettings(public_api_key_required=False)).openapi()
    assert "/v1/service/feature-reference-reconciliations" in spec["paths"]
    ack = spec["paths"]["/v1/service/feature-reference-reconciliations/{event_id}/acks"]["post"]
    assert ack["responses"]["409"]
    assert ack["security"] == [{"ServiceToken": []}]
    activation = spec["paths"]["/v1/admin/feature-reference-reconciliation-subscriptions"]
    assert "post" in activation


@pytest.mark.asyncio
async def test_semantic_ack_replay_preflights_before_domain_command_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def key_preflight(*_args: object, **_kwargs: object) -> None:
        calls.append("idempotency-key")

    async def receipt_preflight(
        *_args: object, **_kwargs: object
    ) -> FeatureReferenceReconciliationPreflight:
        assert calls == ["idempotency-key"]
        calls.append("receipt")
        return FeatureReferenceReconciliationPreflight(
            outcome="replayed", acked_through_sequence=11
        )

    preflight = AsyncMock(side_effect=receipt_preflight)
    claim = AsyncMock(side_effect=AssertionError("new domain command must not be claimed"))
    monkeypatch.setattr(
        router.reconciliation_repo,
        "preflight_feature_reference_reconciliation_ack",
        preflight,
    )
    monkeypatch.setattr(router, "begin_domain_command", claim)
    monkeypatch.setattr(router, "preflight_domain_command_claim", key_preflight)
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
    assert calls == ["idempotency-key", "receipt"]
    claim.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscription_provision_is_durable_admin_domain_command(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = DomainCommandHandle(
        command_id=92,
        actor="admin:reviewer",
        operation="admin.feature-reference-reconciliation-subscription.provision.v1",
        idempotency_key=str(_COMMAND_KEY),
        request_fingerprint="e" * 64,
    )
    provision = AsyncMock(
        return_value=FeatureReferenceReconciliationSubscriptionProvision(
            outcome="provisioned", initial_event_sequence=7
        )
    )
    complete = AsyncMock()
    monkeypatch.setattr(router, "begin_domain_command", AsyncMock(return_value=command))
    monkeypatch.setattr(
        router.reconciliation_repo,
        "provision_feature_reference_reconciliation_subscription",
        provision,
    )
    monkeypatch.setattr(router, "complete_domain_command", complete)

    result = await router.provision_feature_reference_reconciliation_subscription_route(
        body=router.FeatureReferenceReconciliationSubscriptionProvisionInput(
            initial_event_sequence=7
        ),
        request=_request(),
        idempotency_key=_COMMAND_KEY,
        context=_admin_context(),
        session=_Session(),  # type: ignore[arg-type]
    )

    assert isinstance(
        result, router.FeatureReferenceReconciliationSubscriptionProvisionResponse
    )
    assert result.data.initial_event_sequence == 7
    provision.assert_awaited_once()
    complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_case_list_returns_keyset_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    second = _case(UUID("95000000-0000-4000-8000-000000000006"))
    list_cases = AsyncMock(return_value=(_case(), second))
    monkeypatch.setattr(router.reconciliation_repo, "list_manual_provider_dedup_cases", list_cases)

    result = await router.list_manual_provider_dedup_cases_route(
        request=_request(),
        context=_admin_context(),
        session=_Session(),  # type: ignore[arg-type]
        status_filter="pending",
        after_created_at=None,
        after_case_id=None,
        limit=50,
    )

    assert [item.case_id for item in result.data.items] == [_CASE_ID, second.case_id]
    assert result.data.next_after_created_at == second.created_at
    assert result.data.next_after_case_id == second.case_id
    list_cases.assert_awaited_once()


@pytest.mark.asyncio
async def test_admin_stale_decision_persists_terminal_409_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = DomainCommandHandle(
        command_id=91,
        actor="admin:reviewer",
        operation="admin.manual-provider-dedup-case.resolve.v1",
        idempotency_key=str(_COMMAND_KEY),
        request_fingerprint="e" * 64,
    )
    begin = AsyncMock(return_value=command)
    resolve = AsyncMock(
        return_value=ManualProviderDedupCaseResolution(
            outcome="stale",
            resolution_id=None,
            event_id=None,
            manual_feature_id=None,
            manual_feature_row_revision=None,
        )
    )
    complete = AsyncMock()
    monkeypatch.setattr(router, "begin_domain_command", begin)
    monkeypatch.setattr(router.reconciliation_repo, "resolve_manual_provider_dedup_case", resolve)
    monkeypatch.setattr(router, "complete_domain_command", complete)

    result = await router.resolve_manual_provider_dedup_case_route(
        case_id=_CASE_ID,
        body=router.ManualProviderDedupCaseDecisionInput(
            decision="kept",
            expected_case_fingerprint="f" * 64,
            expected_manual_row_revision=3,
            expected_provider_row_revision=4,
            reason="증적 보존",
        ),
        request=_request(),
        idempotency_key=_COMMAND_KEY,
        context=_admin_context(),
        session=_Session(),  # type: ignore[arg-type]
    )

    assert isinstance(result, router.JSONResponse)
    assert result.status_code == 409
    complete.assert_awaited_once()
    assert complete.await_args.kwargs["status_code"] == 409
