"""H35 canonical CSV5 bundle 검증, import와 idempotency 확인."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final, cast

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from kortravelmap.cli._h35_contract import (
    H35IdentityError,
    H35Request,
    JsonValue,
    Receipt,
    Status,
    all_pass,
    bind_database_identity,
    canonical_json_bytes,
    check,
    receipt,
    strict_hex,
)
from kortravelmap.cli._h35_schema_version import FORWARD_BOUNDARY, TARGET_SCHEMA
from kortravelmap.curation_import import CurationImportRow, parse_curation_csv
from kortravelmap.curation_provenance import (
    LIGHTHOUSE_DATASET_PREFIX,
    parse_curation_provenance,
    provenance_row_payload,
    requires_lighthouse_provenance,
)
from kortravelmap.infra import curation_repo
from kortravelmap.infra.curation_link_basis import trusted_basis_sql
from kortravelmap.infra.db import make_async_engine

EXPECTED_POST_PUBLIC: Final = 3_265
EXPECTED_CSV_FILES: Final = 5
EXPECTED_CSV_ROWS: Final = 486
EXPECTED_CSV_ACCEPTED: Final = 222
EXPECTED_CSV_REJECTED: Final = 0
_CSV_ACTOR: Final = "system:h35-csv5"
_RESOURCE_ROOT: Final = Path("resources/curations")
_MANIFEST_PATH: Final = _RESOURCE_ROOT / "manifest.json"


@dataclass(frozen=True)
class Csv5Bundle:
    manifest_sha256: str
    bundle_sha256: str
    entries: tuple[dict[str, JsonValue], ...]


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _dsn() -> str:
    value = os.environ.get("KOR_TRAVEL_MAP_PG_DSN")
    if not value:
        raise RuntimeError("database_configuration_missing")
    return value


def _engine() -> AsyncEngine:
    return make_async_engine(
        _dsn(),
        pool_size=1,
        max_overflow=0,
        server_settings={
            "application_name": "kor-travel-map-h35-helper",
            "lock_timeout": "5s",
        },
    )


def _image_revision_check(request: H35Request) -> dict[str, JsonValue]:
    return check(
        "candidate_image_source_revision",
        expected=request.source_revision,
        observed=os.environ.get("KOR_TRAVEL_MAP_IMAGE_REVISION", ""),
    )


async def _bind_live_database_identity(
    session: AsyncSession,
    request: H35Request,
) -> tuple[H35Request, dict[str, JsonValue]]:
    row = (
        (
            await session.execute(
                text(
                    "SELECT current_database() AS database_name, "
                    "(pg_control_system()).system_identifier::text AS system_identifier, "
                    "(SELECT count(*) FROM alembic_version) AS alembic_rows"
                )
            )
        )
        .mappings()
        .one()
    )
    if int(row["alembic_rows"]) != 1:
        raise H35IdentityError("alembic_version_cardinality_invalid")
    return bind_database_identity(
        request,
        database=str(row["database_name"]),
        system_identifier=str(row["system_identifier"]),
    )


def _required_int(entry: Mapping[str, JsonValue], key: str) -> int:
    value = entry[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimeError("csv5_manifest_invalid")
    return value


def load_csv5_bundle() -> Csv5Bundle:
    """고정 resource root의 canonical manifest와 다섯 asset을 검증한다."""
    manifest_bytes = _MANIFEST_PATH.read_bytes()
    raw = json.loads(manifest_bytes)
    if not isinstance(raw, dict) or raw.get("schema_version") != 3:
        raise RuntimeError("csv5_manifest_invalid")
    files = raw.get("files")
    if not isinstance(files, list):
        raise RuntimeError("csv5_manifest_invalid")
    entries: list[dict[str, JsonValue]] = []
    for value in files:
        if not isinstance(value, dict) or value.get("kind") != "official_seed":
            continue
        entry = cast("dict[str, object]", value)
        path_value = entry.get("path")
        expected_rows = entry.get("expected_rows")
        linked_rows = entry.get("linked_rows")
        unresolved_rows = entry.get("unresolved_rows")
        if (
            not isinstance(path_value, str)
            or Path(path_value).name != path_value
            or isinstance(expected_rows, bool)
            or not isinstance(expected_rows, int)
            or isinstance(linked_rows, bool)
            or not isinstance(linked_rows, int)
            or isinstance(unresolved_rows, bool)
            or not isinstance(unresolved_rows, int)
        ):
            raise RuntimeError("csv5_manifest_invalid")
        expected_sha = strict_hex(entry.get("sha256"), length=64, field="csv sha256")
        if _sha256((_RESOURCE_ROOT / path_value).read_bytes()) != expected_sha:
            raise RuntimeError("csv5_asset_digest_mismatch")
        entries.append(
            {
                "path": path_value,
                "sha256": expected_sha,
                "expected_rows": expected_rows,
                "linked_rows": linked_rows,
                "unresolved_rows": unresolved_rows,
                "provenance_path": cast("JsonValue", entry.get("provenance_path")),
                "provenance_sha256": cast("JsonValue", entry.get("provenance_sha256")),
            }
        )
    entries.sort(key=lambda item: str(item["path"]))
    if (
        len(entries) != EXPECTED_CSV_FILES
        or sum(_required_int(entry, "expected_rows") for entry in entries) != EXPECTED_CSV_ROWS
        or sum(_required_int(entry, "linked_rows") for entry in entries) != EXPECTED_CSV_ACCEPTED
        or sum(_required_int(entry, "unresolved_rows") for entry in entries)
        != EXPECTED_CSV_ROWS - EXPECTED_CSV_ACCEPTED
    ):
        raise RuntimeError("csv5_manifest_counts_mismatch")
    return Csv5Bundle(
        manifest_sha256=_sha256(manifest_bytes),
        bundle_sha256=_sha256(canonical_json_bytes(entries)),
        entries=tuple(entries),
    )


def _metadata(row: CurationImportRow) -> dict[str, Any]:
    metadata = dict(row.metadata_json)
    if row.subcourse:
        metadata["subcourse"] = row.subcourse
    if row.official_ordinal is not None:
        metadata["official_ordinal"] = row.official_ordinal
    if row.place_name:
        metadata["official_place_name"] = row.place_name
    if row.address_hint:
        metadata["address_hint"] = row.address_hint
    return metadata


def _frozen_h35_lighthouse_dataset_pairs(
    rows: tuple[CurationImportRow, ...],
) -> frozenset[tuple[str, str]]:
    """등대 seed pair를 CSV 자연키만으로 판정한다 (질의 없음).

    이 CLI는 0063~0079 고정 세대에서만 돈다 — dataset catalog
    ``provider_sync.provider_datasets``는 0089가 만들므로 조회할 대상이 없다.
    당시 판정은 ``dataset_key`` prefix 하나였고, 그 술어를 그대로 보존한다
    (역사 표면 보존, ADR-075).
    """

    return frozenset(
        (row.provider, row.dataset_key)
        for row in rows
        if row.dataset_key.startswith(LIGHTHOUSE_DATASET_PREFIX)
    )


async def _resolved_rows(
    session: AsyncSession,
    *,
    entry: Mapping[str, JsonValue],
) -> tuple[tuple[curation_repo.ResolvedCurationImportRow, ...], int, int]:
    content = (_RESOURCE_ROOT / str(entry["path"])).read_bytes()
    preview = parse_curation_csv(content)
    if preview.has_errors or preview.rows_total != _required_int(entry, "expected_rows"):
        raise RuntimeError("csv5_parse_rejected")
    provenance_by_row: dict[int, dict[str, Any]] = {}
    provenance_path = entry.get("provenance_path")
    if provenance_path is not None:
        if not isinstance(provenance_path, str) or Path(provenance_path).name != provenance_path:
            raise RuntimeError("csv5_provenance_manifest_invalid")
        provenance_content = (_RESOURCE_ROOT / provenance_path).read_bytes()
        expected_sha = strict_hex(
            entry.get("provenance_sha256"), length=64, field="provenance_sha256"
        )
        if _sha256(provenance_content) != expected_sha:
            raise RuntimeError("csv5_provenance_digest_mismatch")
        provenance = parse_curation_provenance(
            csv_content=content,
            provenance_content=provenance_content,
        )
        provenance_by_row = {
            csv_row.row_number: provenance_row_payload(provenance, row)
            for csv_row, row in zip(preview.rows, provenance.rows, strict=True)
        }
    elif requires_lighthouse_provenance(
        preview.rows,
        lighthouse_dataset_pairs=_frozen_h35_lighthouse_dataset_pairs(preview.rows),
    ):
        raise RuntimeError("csv5_provenance_missing")

    requests = tuple(
        curation_repo.FeatureMatchRequest(
            row_number=row.row_number,
            feature_id=row.feature_id or None,
            place_name=row.place_name or None,
            address_hint=row.address_hint or None,
        )
        for row in preview.rows
    )
    # h35 cutover는 0063~0079 고정 세대에서 돈다 — matcher의 frozen 변형을
    # 사용한다 (T-VN-32C PR-2, 역사 표면 보존).
    matches = await curation_repo.resolve_feature_matches(
        session, requests=requests, frozen_h35_schema=True
    )
    accepted = rejected = 0
    resolved: list[curation_repo.ResolvedCurationImportRow] = []
    for row in preview.rows:
        candidates = matches.get(row.row_number, ())
        adopted = candidates[0] if row.feature_id.strip() and len(candidates) == 1 else None
        if row.feature_id.strip():
            accepted += adopted is not None
            rejected += adopted is None
        resolved.append(
            curation_repo.ResolvedCurationImportRow(
                row_number=row.row_number,
                collection_key=row.collection_key,
                theme_slug=row.theme_slug,
                theme_name=row.theme_name,
                theme_group=row.theme_group,
                title=row.title,
                edition_key=row.edition_key,
                # 0063~0079 고정 세대 — ``feature.curated_sources``의 identity는
                # 자연키이고 surrogate 열도 catalog도 없다(둘 다 0089/0090 산물).
                provider_dataset_id=None,
                frozen_h35_dataset=(row.provider, row.dataset_key),
                source_name=row.source_name,
                source_url=row.source_url or None,
                source_item_key=row.source_item_key,
                source_component_key=row.source_component_key,
                feature_id=adopted.feature_id if adopted is not None else None,
                place_name=row.place_name
                or (adopted.name if adopted is not None else row.feature_id),
                address_hint=row.address_hint or None,
                sort_order=(
                    row.sort_order
                    if row.sort_order is not None
                    else (
                        row.official_ordinal
                        if row.official_ordinal is not None
                        else row.row_number - 1
                    )
                ),
                item_title=row.item_title or None,
                item_summary=row.item_summary or None,
                metadata=_metadata(row),
                provenance=provenance_by_row.get(row.row_number),
            )
        )
    return tuple(resolved), accepted, rejected


async def csv5_existing_state(session: AsyncSession, bundle: Csv5Bundle) -> dict[str, int]:
    hashes = [str(entry["sha256"]) for entry in bundle.entries]
    row = (
        (
            await session.execute(
                text(
                    "SELECT count(DISTINCT batch.import_batch_id)::bigint AS batches, "
                    "count(row.import_row_id)::bigint AS rows, "
                    "count(*) FILTER (WHERE decision.decision_kind='accepted' "
                    "AND decision.match_basis='csv_explicit_feature_id')::bigint AS accepted "
                    "FROM feature.curation_import_batches AS batch "
                    "LEFT JOIN feature.curation_import_rows AS row "
                    "ON row.import_batch_id=batch.import_batch_id "
                    "LEFT JOIN feature.curation_items AS item "
                    "ON item.current_import_row_id=row.import_row_id "
                    "LEFT JOIN feature.curation_link_decisions AS decision "
                    "ON decision.decision_id=item.accepted_link_decision_id "
                    "AND decision.import_row_id=row.import_row_id "
                    "WHERE batch.actor=:actor AND batch.batch_kind='csv_upload' "
                    "AND batch.content_sha256=ANY(CAST(:hashes AS text[]))"
                ),
                {"actor": _CSV_ACTOR, "hashes": hashes},
            )
        )
        .mappings()
        .one()
    )
    return {key: int(row[key] or 0) for key in ("batches", "rows", "accepted")}


def _public_count_sql() -> str:
    return f"""
        SELECT count(*)::bigint FROM feature.curation_items AS item
        JOIN feature.curation_collections AS collection
          ON collection.collection_id=item.collection_id
        JOIN feature.curated_themes AS theme ON theme.theme_id=collection.theme_id
        WHERE item.archived_at IS NULL AND collection.archived_at IS NULL
          AND item.source_present
          AND item.status='included' AND collection.status='published'
          AND collection.visibility='public' AND theme.visibility='public'
          AND EXISTS (SELECT 1 FROM feature.curation_link_decisions AS decision
            WHERE decision.decision_id=item.accepted_link_decision_id
              AND decision.curation_item_id=item.curation_item_id
              AND decision.feature_id=item.feature_id
              AND decision.decision_kind='accepted'
              AND {trusted_basis_sql("decision.match_basis")})
    """


async def run_csv5(request: H35Request) -> Receipt:
    bundle = load_csv5_bundle()
    engine = _engine()
    accepted = rejected = imported_rows = 0
    status: Status = "failed"
    schema = "unknown"
    final_state = {"batches": 0, "rows": 0, "accepted": 0}
    public = 0
    checks: list[dict[str, JsonValue]] = []
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            live_request, identity_check = await _bind_live_database_identity(session, request)
            schema = str(await session.scalar(text("SELECT version_num FROM alembic_version")))
            before = await csv5_existing_state(session, bundle)
            empty = before == {"batches": 0, "rows": 0, "accepted": 0}
            complete = before == {
                "batches": EXPECTED_CSV_FILES,
                "rows": EXPECTED_CSV_ROWS,
                "accepted": EXPECTED_CSV_ACCEPTED,
            }
            checks = [
                identity_check,
                _image_revision_check(request),
                check("schema_before_csv5", expected=TARGET_SCHEMA, observed=schema),
                check("csv5_prior_state_known", expected=True, observed=empty or complete),
                check(
                    "csv5_manifest_files", expected=EXPECTED_CSV_FILES, observed=len(bundle.entries)
                ),
            ]
            if not all_pass(checks):
                await session.rollback()
                return receipt(
                    live_request,
                    status="rejected",
                    schema_before=schema,
                    schema_after=schema,
                    forward_boundary=FORWARD_BOUNDARY if schema == TARGET_SCHEMA else "not_crossed",
                    row_counts={**before, "accepted": 0, "rejected": 0},
                    checks=checks,
                )
            if empty:
                for entry in bundle.entries:
                    rows, file_accepted, file_rejected = await _resolved_rows(session, entry=entry)
                    accepted += file_accepted
                    rejected += file_rejected
                    imported_rows += len(rows)
                    if file_rejected:
                        raise RuntimeError("csv5_explicit_feature_rejected")
                    await curation_repo.import_curation_rows(
                        session,
                        rows=rows,
                        actor=_CSV_ACTOR,
                        source_content_sha256=str(entry["sha256"]),
                        batch_kind="csv_upload",
                        # 0063~0079 고정 세대 — removal projection의 feature_uuid는
                        # NULL (T-VN-32C PR-2, 역사 표면 보존).
                        frozen_h35_schema=True,
                    )
                if (accepted, rejected, imported_rows) != (
                    EXPECTED_CSV_ACCEPTED,
                    EXPECTED_CSV_REJECTED,
                    EXPECTED_CSV_ROWS,
                ):
                    raise RuntimeError("csv5_result_counts_mismatch")
                await session.flush()
            else:
                accepted, imported_rows = EXPECTED_CSV_ACCEPTED, EXPECTED_CSV_ROWS
            final_state = await csv5_existing_state(session, bundle)
            public = int((await session.scalar(text(_public_count_sql()))) or 0)
            checks.extend(
                (
                    check(
                        "csv5_batches", expected=EXPECTED_CSV_FILES, observed=final_state["batches"]
                    ),
                    check("csv5_rows", expected=EXPECTED_CSV_ROWS, observed=final_state["rows"]),
                    check(
                        "csv5_accepted",
                        expected=EXPECTED_CSV_ACCEPTED,
                        observed=final_state["accepted"],
                    ),
                    check("csv5_rejected", expected=EXPECTED_CSV_REJECTED, observed=rejected),
                    check(
                        "public_items_after_csv5", expected=EXPECTED_POST_PUBLIC, observed=public
                    ),
                    check(
                        "csv5_manifest_sha256",
                        expected=bundle.manifest_sha256,
                        observed=_sha256(_MANIFEST_PATH.read_bytes()),
                    ),
                    check(
                        "csv5_bundle_sha256",
                        expected=bundle.bundle_sha256,
                        observed=_sha256(canonical_json_bytes(bundle.entries)),
                    ),
                )
            )
            status = "accepted" if all_pass(checks) else "rejected"
            if status == "accepted":
                await session.commit()
            else:
                await session.rollback()
    finally:
        await engine.dispose()
    return receipt(
        live_request,
        status=status,
        schema_before=schema,
        schema_after=schema,
        forward_boundary=FORWARD_BOUNDARY if schema == TARGET_SCHEMA else "not_crossed",
        row_counts={
            "accepted": accepted,
            "batches": final_state["batches"],
            "csv_files": EXPECTED_CSV_FILES,
            "imported_rows": imported_rows,
            "public_items": public,
            "rejected": rejected,
        },
        checks=checks,
    )


async def collect_csv5_verify_state(
    request: H35Request,
) -> tuple[H35Request, dict[str, JsonValue], dict[str, int], int]:
    bundle = load_csv5_bundle()
    engine = _engine()
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            live_request, identity_check = await _bind_live_database_identity(session, request)
            return (
                live_request,
                identity_check,
                await csv5_existing_state(session, bundle),
                int((await session.scalar(text(_public_count_sql()))) or 0),
            )
    finally:
        await engine.dispose()


__all__ = [
    "EXPECTED_CSV_ACCEPTED",
    "EXPECTED_CSV_FILES",
    "EXPECTED_CSV_ROWS",
    "EXPECTED_POST_PUBLIC",
    "Csv5Bundle",
    "collect_csv5_verify_state",
    "csv5_existing_state",
    "load_csv5_bundle",
    "run_csv5",
]
