"""PinVi 전용 canonical curation snapshot service read."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from kortravelmap.core.curation_snapshot import (
    canonical_curation_snapshot_value,
    curation_snapshot_sha256,
)
from kortravelmap.infra import curation_repo
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.api.auth import require_curation_snapshot_service_principal
from kortravelmap.api.db import get_session

__all__ = ["service_router"]

_SNAPSHOT_SCOPE = "pinvi:curation-snapshot:read"
_REVISION_PATTERN = r"^[1-9][0-9]*$"
_BODY_ETAG_PATTERN = r"^sha256:[0-9a-f]{64}$"
_DIGEST_PATTERN = r"^[0-9a-f]{64}$"
_HTTP_ETAG_PATTERN = r'^"sha256:[0-9a-f]{64}"$'
_ITEM_SET_HASH_VERSION = "ktm-db-item-set-v1"
_ETAG_HEADER = {
    "ETag": {
        "description": "canonicalization v1 snapshot의 strong ETag.",
        "schema": {"type": "string", "pattern": _HTTP_ETAG_PATTERN},
    }
}

service_router = APIRouter(
    prefix="/service",
    tags=["service-curation-snapshots"],
    dependencies=[Depends(require_curation_snapshot_service_principal)],
)


class CurationSnapshotCollection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    theme_slug: Annotated[str, Field(min_length=1, max_length=128)]
    theme_name: Annotated[str, Field(min_length=1, max_length=200)]
    title: Annotated[str, Field(min_length=1, max_length=300)]
    edition_key: Annotated[str, Field(max_length=100)]


class CurationSnapshotItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: UUID
    relation: str
    sort_order: int
    title: str | None
    summary: str | None


class CurationSnapshotFeature(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feature_id: UUID
    name: str
    category: str
    kind: str
    lon: float | None
    lat: float | None
    address: dict[str, Any]
    detail: dict[str, Any]
    source_record_key: str | None


class CurationItemDetailSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    curation_item_id: UUID
    collection_id: UUID
    row_revision: Annotated[str, Field(pattern=_REVISION_PATTERN)]
    etag: Annotated[str, Field(pattern=_BODY_ETAG_PATTERN)]
    updated_at: datetime
    collection: CurationSnapshotCollection
    item: CurationSnapshotItem
    feature: CurationSnapshotFeature


class CurationCollectionDetailSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection_id: UUID
    row_revision: Annotated[str, Field(pattern=_REVISION_PATTERN)]
    etag: Annotated[str, Field(pattern=_BODY_ETAG_PATTERN)]
    updated_at: datetime
    collection: CurationSnapshotCollection
    item_count: Annotated[
        int,
        Field(ge=0, le=curation_repo.CURATION_SERVICE_COLLECTION_MAX_ITEMS),
    ]
    item_set_hash_version: Literal["ktm-db-item-set-v1"]
    item_set_hash: Annotated[str, Field(pattern=_DIGEST_PATTERN)]
    items: Annotated[list[CurationItemDetailSnapshot], Field(max_length=200)]
    next_cursor: str | None
    complete: bool


def _rfc3339(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _item_payload(row: curation_repo.CurationServiceItemSnapshot) -> dict[str, object]:
    return {
        "curation_item_id": row.curation_item_id,
        "collection_id": row.collection_id,
        "row_revision": str(row.row_revision),
        "updated_at": _rfc3339(row.updated_at),
        "collection": {
            "theme_slug": row.theme_slug,
            "theme_name": row.theme_name,
            "title": row.collection_title,
            "edition_key": row.edition_key,
        },
        "item": {
            "feature_id": row.feature_uuid,
            "relation": row.relation,
            "sort_order": row.sort_order,
            "title": row.item_title,
            "summary": row.item_summary,
        },
        "feature": {
            "feature_id": row.feature_uuid,
            "name": row.feature_name,
            "category": row.feature_category,
            "kind": row.feature_kind,
            "lon": row.lon,
            "lat": row.lat,
            "address": row.address,
            "detail": row.detail,
            "source_record_key": row.source_record_key,
        },
    }


def _item_view(
    row: curation_repo.CurationServiceItemSnapshot,
) -> CurationItemDetailSnapshot:
    payload = canonical_curation_snapshot_value(_item_payload(row))
    if not isinstance(payload, dict):  # pragma: no cover - closed builder invariant
        raise TypeError("curation item snapshot payload must be an object")
    return CurationItemDetailSnapshot.model_validate(
        {**payload, "etag": f"sha256:{curation_snapshot_sha256(payload)}"}
    )


def _collection_identity_payload(
    snapshot: curation_repo.CurationServiceCollectionSnapshot,
) -> dict[str, object]:
    return {
        "collection_id": snapshot.collection_id,
        "row_revision": str(snapshot.row_revision),
        "updated_at": _rfc3339(snapshot.updated_at),
        "collection": {
            "theme_slug": snapshot.theme_slug,
            "theme_name": snapshot.theme_name,
            "title": snapshot.title,
            "edition_key": snapshot.edition_key,
        },
        "item_count": snapshot.item_count,
        "item_set_hash_version": _ITEM_SET_HASH_VERSION,
        "item_set_hash": snapshot.item_set_hash,
    }


def _encode_cursor(payload: dict[str, object], *, key: bytes) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(key, raw, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(raw + signature).decode("ascii").rstrip("=")


def _decode_cursor(raw: str, *, key: bytes) -> dict[str, object]:
    try:
        padded = raw + "=" * (-len(raw) % 4)
        signed = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload_bytes, signature = signed[:-32], signed[-32:]
        if len(signature) != 32 or not hmac.compare_digest(
            signature,
            hmac.new(key, payload_bytes, hashlib.sha256).digest(),
        ):
            raise ValueError
        payload = json.loads(payload_bytes)
        if not isinstance(payload, dict) or set(payload) != {
            "v",
            "collection_id",
            "collection_revision",
            "item_set_hash_version",
            "item_set_hash",
            "last_item_id",
        }:
            raise ValueError
        if payload["v"] != 1:
            raise ValueError
        if payload["item_set_hash_version"] != _ITEM_SET_HASH_VERSION:
            raise ValueError
        UUID(str(payload["collection_id"]))
        UUID(str(payload["last_item_id"]))
        if not str(payload["collection_revision"]).isdigit():
            raise ValueError
        if len(str(payload["item_set_hash"])) != 64:
            raise ValueError
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=422, detail="invalid curation snapshot cursor") from exc
    return payload


@service_router.get(
    "/curation-items/{curation_item_id}/detail-snapshot",
    response_model=CurationItemDetailSnapshot,
    responses={
        200: {"headers": _ETAG_HEADER},
        304: {"description": "ETag 일치", "headers": _ETAG_HEADER},
    },
    openapi_extra={"x-required-service-scope": _SNAPSHOT_SCOPE},
)
async def get_curation_item_detail_snapshot(
    curation_item_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    if_none_match: Annotated[
        str | None,
        Header(alias="If-None-Match", pattern=_HTTP_ETAG_PATTERN),
    ] = None,
) -> CurationItemDetailSnapshot | Response:
    row = await curation_repo.get_curation_service_item_snapshot(
        session,
        curation_item_id=str(curation_item_id),
    )
    if row is None:
        raise HTTPException(status_code=404, detail="curation item snapshot 없음")
    view = _item_view(row)
    strong_etag = f'"{view.etag}"'
    if if_none_match == strong_etag:
        return Response(status_code=304, headers={"ETag": strong_etag})
    response.headers["ETag"] = strong_etag
    return view


@service_router.get(
    "/curation-collections/{collection_id}/detail-snapshot",
    response_model=CurationCollectionDetailSnapshot,
    responses={
        200: {"headers": _ETAG_HEADER},
        304: {
            "description": "첫 page collection ETag 일치",
            "headers": _ETAG_HEADER,
        },
        409: {"description": "cursor 이후 collection/item set 변경 — 첫 page부터 재시작"},
        413: {
            "description": (
                "collection public item 수가 service snapshot 상한을 넘음 — "
                "collection을 분할해야 함"
            )
        },
    },
    openapi_extra={"x-required-service-scope": _SNAPSHOT_SCOPE},
)
async def get_curation_collection_detail_snapshot(
    request: Request,
    collection_id: UUID,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    page_size: Annotated[int, Query(ge=1, le=200)] = 100,
    cursor: Annotated[str | None, Query(min_length=1, max_length=4096)] = None,
    if_none_match: Annotated[
        str | None,
        Header(alias="If-None-Match", pattern=_HTTP_ETAG_PATTERN),
    ] = None,
) -> CurationCollectionDetailSnapshot | Response:
    key = request.app.state.settings.cursor_signing_key
    cursor_payload = _decode_cursor(cursor, key=key) if cursor is not None else None
    after_curation_item_id = (
        str(cursor_payload["last_item_id"])
        if cursor_payload is not None
        else None
    )
    snapshot = await curation_repo.get_curation_service_collection_snapshot(
        session,
        collection_id=str(collection_id),
        after_curation_item_id=after_curation_item_id,
        page_limit=page_size + 1,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="curation collection snapshot 없음")
    if snapshot.item_count > curation_repo.CURATION_SERVICE_COLLECTION_MAX_ITEMS:
        raise HTTPException(
            status_code=413,
            detail=(
                "curation collection snapshot item limit exceeded: "
                f"max={curation_repo.CURATION_SERVICE_COLLECTION_MAX_ITEMS}"
            ),
        )

    identity_payload = _collection_identity_payload(snapshot)
    if cursor_payload is not None and (
        str(cursor_payload["collection_id"]) != snapshot.collection_id
        or str(cursor_payload["collection_revision"]) != str(snapshot.row_revision)
        or str(cursor_payload["item_set_hash_version"]) != _ITEM_SET_HASH_VERSION
        or str(cursor_payload["item_set_hash"]) != snapshot.item_set_hash
    ):
        raise HTTPException(
            status_code=409,
            detail="curation collection snapshot changed; restart from first page",
        )

    page = snapshot.items[:page_size]
    complete = len(snapshot.items) <= page_size
    next_cursor = None
    if not complete and page:
        next_cursor = _encode_cursor(
            {
                "v": 1,
                "collection_id": snapshot.collection_id,
                "collection_revision": str(snapshot.row_revision),
                "item_set_hash_version": _ITEM_SET_HASH_VERSION,
                "item_set_hash": snapshot.item_set_hash,
                "last_item_id": page[-1].curation_item_id,
            },
            key=key,
        )
    payload_without_etag = canonical_curation_snapshot_value(
        {
            **identity_payload,
            "items": [
                _item_view(item).model_dump(mode="json")
                for item in page
            ],
            "next_cursor": next_cursor,
            "complete": complete,
        }
    )
    if not isinstance(payload_without_etag, dict):  # pragma: no cover
        raise TypeError("curation collection snapshot payload must be an object")
    collection_etag = f"sha256:{curation_snapshot_sha256(payload_without_etag)}"
    strong_etag = f'"{collection_etag}"'
    if cursor_payload is None and if_none_match == strong_etag:
        return Response(status_code=304, headers={"ETag": strong_etag})
    response.headers["ETag"] = strong_etag
    response_payload = {**payload_without_etag, "etag": collection_etag}
    return CurationCollectionDetailSnapshot.model_validate(response_payload)
