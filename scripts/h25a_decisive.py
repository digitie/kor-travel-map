"""T-VN-H25A 현재 membership 증거를 단일 read-only snapshot에서 생성한다.

과거 membership은 current snapshot으로 추론하지 않는다. 이 스크립트가 보증하는 범위는
입력 CSV와 현재 DB의 stable row identity 대조, 현재 Feature usable 상태, schema 삭제
계약뿐이다.
"""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import asyncpg

CSV_DIR = Path(os.environ.get("CSV_DIR", "/workspace/resources/curations"))
DSN = os.environ.get("DSN", "").replace("+asyncpg", "")
OUT = Path(
    os.environ.get(
        "OUT",
        "docs/reports/curation-membership-evidence-2026-07-29.json",
    )
)
INPUT_COMMIT = os.environ.get("EVIDENCE_INPUT_COMMIT", "")

_EXPECTED_INPUT_FILES = {
    "arboretum-garden-stamp-tour-2026.csv",
    "heritage-visit-campaign.csv",
    "korean-tourism-100-2023-2024.csv",
    "korean-tourism-100-2025-2026.csv",
    "lighthouse-stamp-tour.csv",
}
_REQUIRED_CSV_COLUMNS = {
    "collection_key",
    "feature_id",
    "place_name",
    "source_component_key",
    "source_item_key",
}
_EXPECTED_COUNTS = {
    "csv_rows": 486,
    "csv_linked": 217,
    "csv_unresolved": 269,
    "csv_unique_feature_ids": 158,
    "db_rows": 486,
    "db_linked": 225,
    "db_unresolved": 261,
    "csv_unlinked_db_linked": 8,
    "csv_linked_db_unlinked": 0,
    "linked_target_mismatch": 0,
}
_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")

CsvIdentity = tuple[str, str, str]
LegacyIdentity = tuple[str, str, str]


def _digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(payload).hexdigest()


def _required_text(row: dict[str, str | None], field: str, location: str) -> str:
    value = (row.get(field) or "").strip()
    if not value:
        raise ValueError(f"{location}: {field}가 비어 있음")
    return value


def load_csv_snapshot() -> tuple[list[dict[str, Any]], dict[str, str]]:
    """입력 CSV를 stable identity와 file hash로 결속한다."""

    paths = sorted(
        path
        for path in CSV_DIR.glob("*.csv")
        if path.name != "template.csv"
    )
    names = {path.name for path in paths}
    if names != _EXPECTED_INPUT_FILES:
        raise RuntimeError(
            "curation evidence 입력 파일 집합 불일치: "
            f"missing={sorted(_EXPECTED_INPUT_FILES - names)}, "
            f"extra={sorted(names - _EXPECTED_INPUT_FILES)}"
        )

    rows: list[dict[str, Any]] = []
    file_hashes: dict[str, str] = {}
    seen: set[CsvIdentity] = set()
    for path in paths:
        raw = path.read_bytes()
        file_hashes[path.name] = hashlib.sha256(raw).hexdigest()
        with path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or ())
            missing = _REQUIRED_CSV_COLUMNS - fields
            if missing:
                raise RuntimeError(
                    f"{path.name}: 필수 열 누락 {sorted(missing)}"
                )
            for line_number, source in enumerate(reader, start=2):
                location = f"{path.name}:{line_number}"
                collection_key = _required_text(
                    source, "collection_key", location
                )
                source_item_key = _required_text(
                    source, "source_item_key", location
                )
                source_component_key = _required_text(
                    source, "source_component_key", location
                )
                csv_identity = (
                    collection_key,
                    source_item_key,
                    source_component_key,
                )
                if csv_identity in seen:
                    raise RuntimeError(
                        f"{location}: CSV stable identity 중복 {csv_identity!r}"
                    )
                seen.add(csv_identity)
                rows.append(
                    {
                        "collection_key": collection_key,
                        "source_item_key": source_item_key,
                        "source_component_key": source_component_key,
                        "place_name": _required_text(
                            source, "place_name", location
                        ),
                        "feature_id": (source.get("feature_id") or "").strip()
                        or None,
                        "csv_file": path.name,
                        "csv_line": line_number,
                        "csv_sha256": file_hashes[path.name],
                    }
                )
    return rows, file_hashes


def compare_membership_rows(
    csv_rows: list[dict[str, Any]],
    db_rows: list[dict[str, Any]],
) -> tuple[dict[str, int], list[dict[str, Any]]]:
    """stable identity별 CSV/DB link 상태를 대조하고 drift 8행을 반환한다."""

    def group(
        rows: list[dict[str, Any]],
    ) -> dict[LegacyIdentity, list[dict[str, Any]]]:
        result: dict[LegacyIdentity, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            legacy_identity = (
                str(row["collection_key"]),
                str(row["source_item_key"]),
                str(row["place_name"]),
            )
            result[legacy_identity].append(row)
        return dict(result)

    csv_by_identity = group(csv_rows)
    db_by_identity = group(db_rows)
    csv_identities = set(csv_by_identity)
    db_identities = set(db_by_identity)
    if csv_identities != db_identities:
        raise RuntimeError(
            "CSV/DB stable identity 집합 불일치: "
            f"csv_only={len(csv_identities - db_identities)}, "
            f"db_only={len(db_identities - csv_identities)}"
        )

    counts: Counter[str] = Counter()
    drift: list[dict[str, Any]] = []
    for identity in sorted(csv_identities):
        csv_group = csv_by_identity[identity]
        db_group = db_by_identity[identity]
        if len(csv_group) != len(db_group):
            raise RuntimeError(
                f"legacy identity multiplicity 불일치: {identity!r}, "
                f"csv={len(csv_group)}, db={len(db_group)}"
            )
        csv_links = Counter(
            str(row["feature_id"]) for row in csv_group if row["feature_id"]
        )
        db_links = Counter(
            str(row["feature_id"]) for row in db_group if row["feature_id"]
        )
        common = csv_links & db_links
        counts["both_linked"] += common.total()
        csv_only = (csv_links - common).total()
        db_only = (db_links - common).total()
        target_mismatch = min(csv_only, db_only)
        counts["linked_target_mismatch"] += target_mismatch
        csv_only -= target_mismatch
        db_only -= target_mismatch
        counts["csv_linked_db_unlinked"] += csv_only
        counts["csv_unlinked_db_linked"] += db_only
        counts["both_unlinked"] += (
            len(csv_group) - common.total() - csv_only - target_mismatch
        )
        if db_only:
            if len(csv_group) != 1 or len(db_group) != 1 or db_only != 1:
                raise RuntimeError(
                    f"DB-only link manifest identity가 모호함: {identity!r}"
                )
            csv_row = csv_group[0]
            db_row = db_group[0]
            drift.append(
                {
                    "collection_key": identity[0],
                    "source_item_key": identity[1],
                    "source_component_key": csv_row["source_component_key"],
                    "place_name": csv_row["place_name"],
                    "db_feature_id": db_row["feature_id"],
                    "db_status": db_row["status"],
                    "csv_file": csv_row["csv_file"],
                    "csv_line": csv_row["csv_line"],
                    "csv_sha256": csv_row["csv_sha256"],
                    "csv_legacy_identity_multiplicity": len(csv_group),
                    "db_legacy_identity_multiplicity": len(db_group),
                }
            )

    summary = {
        "csv_rows": len(csv_rows),
        "csv_linked": sum(bool(row["feature_id"]) for row in csv_rows),
        "csv_unresolved": sum(not row["feature_id"] for row in csv_rows),
        "csv_unique_feature_ids": len(
            {row["feature_id"] for row in csv_rows if row["feature_id"]}
        ),
        "db_rows": len(db_rows),
        "db_linked": sum(bool(row["feature_id"]) for row in db_rows),
        "db_unresolved": sum(not row["feature_id"] for row in db_rows),
        "csv_unlinked_db_linked": counts["csv_unlinked_db_linked"],
        "csv_linked_db_unlinked": counts["csv_linked_db_unlinked"],
        "linked_target_mismatch": counts["linked_target_mismatch"],
    }
    if summary != _EXPECTED_COUNTS:
        raise RuntimeError(
            f"curation evidence count invariant 불일치: {summary!r}"
        )
    return summary, drift


async def _schema_contract(conn: asyncpg.Connection) -> dict[str, Any]:
    columns = {
        row["column_name"]
        for row in await conn.fetch(
            """
            select column_name
            from information_schema.columns
            where table_schema = 'feature' and table_name = 'curation_items'
            """
        )
    }
    required = {
        "external_item_id",
        "feature_id",
        "place_name",
        "source_record_key",
        "status",
    }
    if not required <= columns:
        raise RuntimeError(
            f"curation_items schema 불일치: missing={sorted(required - columns)}"
        )

    item_constraints = {
        row["conname"]: row["definition"]
        for row in await conn.fetch(
            """
            select conname, pg_get_constraintdef(oid) as definition
            from pg_constraint
            where conrelid = 'feature.curation_items'::regclass
            order by conname
            """
        )
    }
    feature_fk = item_constraints.get("curation_items_feature_id_fkey", "")
    if "ON DELETE SET NULL" not in feature_fk:
        raise RuntimeError("curation_items feature FK 삭제 계약 불일치")
    indexes = {
        row["indexname"]: row["indexdef"]
        for row in await conn.fetch(
            """
            select indexname, indexdef
            from pg_indexes
            where schemaname = 'feature' and tablename = 'curation_items'
            order by indexname
            """
        )
    }
    legacy_identity_index = indexes.get("uq_curation_items_active_identity", "")
    if (
        "(collection_id, external_item_id, feature_id) NULLS NOT DISTINCT"
        not in legacy_identity_index
    ):
        raise RuntimeError("curation_items legacy identity index 계약 불일치")

    merge_constraints = {
        row["conname"]: row["definition"]
        for row in await conn.fetch(
            """
            select conname, pg_get_constraintdef(oid) as definition
            from pg_constraint
            where conrelid = 'ops.feature_merge_history'::regclass
              and contype = 'f'
            order by conname
            """
        )
    }
    feature_merge_fks = [
        definition
        for definition in merge_constraints.values()
        if "feature.features(feature_id)" in definition
    ]
    if (
        len(feature_merge_fks) != 2
        or any("ON DELETE CASCADE" not in value for value in feature_merge_fks)
    ):
        raise RuntimeError("feature_merge_history FK 삭제 계약 불일치")
    return {
        "curation_feature_fk": feature_fk,
        "curation_identity_strategy": (
            "legacy snapshot exact group: "
            "collection_key + external_item_id + place_name"
        ),
        "curation_legacy_identity_index": legacy_identity_index,
        "merge_feature_fks": sorted(feature_merge_fks),
    }


async def collect_evidence() -> dict[str, Any]:
    if not _COMMIT_PATTERN.fullmatch(INPUT_COMMIT):
        raise RuntimeError("EVIDENCE_INPUT_COMMIT은 exact 40자 SHA여야 함")
    if not DSN:
        raise RuntimeError("DSN이 필요함")
    csv_rows, file_hashes = load_csv_snapshot()
    collection_keys = sorted(
        {str(row["collection_key"]) for row in csv_rows}
    )
    feature_ids = sorted(
        {str(row["feature_id"]) for row in csv_rows if row["feature_id"]}
    )

    conn = await asyncpg.connect(DSN)
    try:
        async with conn.transaction(
            isolation="repeatable_read",
            readonly=True,
            deferrable=True,
        ):
            alembic_head = await conn.fetchval(
                "select version_num from alembic_version limit 1"
            )
            if alembic_head != "0063_pipeline_root_id":
                raise RuntimeError(
                    f"alembic head 불일치: {alembic_head!r}"
                )
            schema = await _schema_contract(conn)

            feature_rows = [
                dict(row)
                for row in await conn.fetch(
                    """
                    select feature_id, status, created_at, deleted_at
                    from feature.features
                    where feature_id = any($1::text[])
                    order by feature_id
                    """,
                    feature_ids,
                )
            ]
            usable = [
                row
                for row in feature_rows
                if row["status"] not in {"deleted", "hidden"}
                and row["deleted_at"] is None
            ]
            if len(feature_rows) != 158 or len(usable) != 158:
                raise RuntimeError(
                    "현재 CSV Feature usable invariant 불일치: "
                    f"found={len(feature_rows)}, usable={len(usable)}"
                )

            db_rows = [
                dict(row)
                for row in await conn.fetch(
                    """
                    select c.collection_key,
                           i.external_item_id as source_item_key,
                           i.place_name,
                           i.feature_id,
                           i.status,
                           i.source_record_key
                    from feature.curation_items i
                    join feature.curation_collections c
                      on c.collection_id = i.collection_id
                    where c.collection_key = any($1::text[])
                    order by c.collection_key,
                             i.external_item_id,
                             i.place_name,
                             i.curation_item_id
                    """,
                    collection_keys,
                )
            ]
            summary, drift = compare_membership_rows(csv_rows, db_rows)
            if len(drift) != 8:
                raise RuntimeError(
                    f"exact drift manifest invariant 불일치: {len(drift)}"
                )

            source_record_counts = {
                "linked": sum(
                    bool(row["source_record_key"])
                    for row in db_rows
                    if row["feature_id"]
                ),
                "unresolved": sum(
                    bool(row["source_record_key"])
                    for row in db_rows
                    if not row["feature_id"]
                ),
            }
            if source_record_counts != {"linked": 0, "unresolved": 0}:
                raise RuntimeError(
                    "source_record_key evidence invariant 불일치: "
                    f"{source_record_counts!r}"
                )
            merge_history_rows = await conn.fetchval(
                "select count(*) from ops.feature_merge_history"
            )

            feature_snapshot = [
                {
                    "feature_id": row["feature_id"],
                    "status": row["status"],
                    "created_at": row["created_at"].isoformat(),
                    "deleted_at": (
                        row["deleted_at"].isoformat()
                        if row["deleted_at"] is not None
                        else None
                    ),
                }
                for row in feature_rows
            ]
            db_membership_snapshot = [
                {
                    key: row[key]
                    for key in (
                        "collection_key",
                        "source_item_key",
                        "place_name",
                        "feature_id",
                        "status",
                        "source_record_key",
                    )
                }
                for row in db_rows
            ]
    finally:
        await conn.close()

    return {
        "version": 2,
        "scope": "current_snapshot_only",
        "historical_membership_inference": "unsupported",
        "input_commit": INPUT_COMMIT,
        "csv_file_sha256": file_hashes,
        "alembic_head": alembic_head,
        "schema_contract": schema,
        "summary": summary,
        "current_feature_snapshot_sha256": _digest(feature_snapshot),
        "current_membership_snapshot_sha256": _digest(
            db_membership_snapshot
        ),
        "source_record_key_nonnull": source_record_counts,
        "current_merge_history_rows": merge_history_rows,
        "csv_unlinked_db_linked": drift,
    }


def main() -> None:
    evidence = asyncio.run(collect_evidence())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        "H25A current-snapshot evidence complete: "
        f"rows={evidence['summary']['db_rows']}, "
        f"drift={len(evidence['csv_unlinked_db_linked'])}, out={OUT}"
    )


if __name__ == "__main__":
    main()
