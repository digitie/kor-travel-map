"""#668: PATCH의 필드 존재 여부를 보존하는 명령 지문."""

from __future__ import annotations

from inspect import signature

import pytest
from fastapi import Request, Response

from kortravelmap.api.auth import AdminProxyContext
from kortravelmap.api.domain_command_service import _route_payload
from kortravelmap.api.routers.admin_features import AdminFeaturePatchRequest, patch_feature_route


@pytest.mark.asyncio
async def test_patch_fingerprint_distinguishes_omitted_coordinate_from_explicit_null():
    request = Request({"type": "http", "headers": [(b"if-match", b'"1"')]})
    original = patch_feature_route.__wrapped__
    common = dict(
        feature_id="test-feature",
        request=request,
        response=Response(),
        context=AdminProxyContext(actor="admin:test"),
        session=None,
    )
    first = await _route_payload(
        signature(original),
        (),
        {**common, "body": AdminFeaturePatchRequest(name="new", reason="same reason")},
        fingerprint_headers=("If-Match",),
    )
    second = await _route_payload(
        signature(original),
        (),
        {**common, "body": AdminFeaturePatchRequest(name="new", coord=None, reason="same reason")},
        fingerprint_headers=("If-Match",),
    )
    assert first != second
