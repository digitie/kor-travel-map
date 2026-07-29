"""PR #890 사후 감사에서 확인한 운영 스크립트 회귀."""

from __future__ import annotations

import copy
import csv
import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import h25b_apply_verified_links as h25
from scripts import h33_unlink_mislinks as h33
from scripts import h33_verify_public_exposure as h33_verify


def _write_approval_csv(
    target: Path,
    *,
    key: h25.ApprovalKey,
    feature_ids: tuple[str, ...],
) -> Path:
    path = target / "approval.csv"
    fields = [
        "collection_key",
        "source_item_key",
        "source_component_key",
        "feature_id",
        "metadata_json",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for feature_id in feature_ids:
            writer.writerow(
                {
                    "collection_key": key[0],
                    "source_item_key": key[1],
                    "source_component_key": key[2],
                    "feature_id": feature_id,
                    "metadata_json": "{}",
                }
            )
    return path


def _write_manifest(target: Path, csv_path: Path) -> Path:
    manifest = target / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": csv_path.name,
                        "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                        "rows": 1,
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest


@pytest.mark.unit
def test_h25_apply_rejects_wrong_existing_link_before_manifest_write(
    tmp_path: Path,
) -> None:
    key, expected = next(iter(h25.APPROVED.items()))
    csv_path = _write_approval_csv(
        tmp_path,
        key=key,
        feature_ids=("feature:wrong",),
    )
    manifest = _write_manifest(tmp_path, csv_path)
    before = (csv_path.read_bytes(), manifest.read_bytes())

    with pytest.raises(RuntimeError, match="feature_id=.*expected"):
        h25.apply_verified_links(tmp_path)

    assert (csv_path.read_bytes(), manifest.read_bytes()) == before
    assert expected != "feature:wrong"


@pytest.mark.unit
def test_h25_apply_rejects_duplicate_approved_identity(tmp_path: Path) -> None:
    key, expected = next(iter(h25.APPROVED.items()))
    csv_path = _write_approval_csv(
        tmp_path,
        key=key,
        feature_ids=(expected, expected),
    )
    manifest = _write_manifest(tmp_path, csv_path)
    before = (csv_path.read_bytes(), manifest.read_bytes())

    with pytest.raises(RuntimeError, match="출현 2건"):
        h25.apply_verified_links(tmp_path)

    assert (csv_path.read_bytes(), manifest.read_bytes()) == before


class _FakeTransaction:
    def __init__(self, conn: _FakeH33Connection) -> None:
        self.conn = conn
        self.snapshot: tuple[list[dict[str, Any]], dict[str, dict[str, Any]]] | None = None

    async def __aenter__(self) -> None:
        self.snapshot = (copy.deepcopy(self.conn.rows), copy.deepcopy(self.conn.findings))

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: object,
    ) -> bool:
        if exc_type is not None:
            assert self.snapshot is not None
            self.conn.rows, self.conn.findings = self.snapshot
        return False


class _FakeH33Connection:
    def __init__(
        self,
        *,
        feature_id: str | None,
        fail_finding_insert: bool = False,
        existing_finding: bool = False,
    ) -> None:
        self.rows = [
            {
                "curation_item_id": "item-id",
                "external_item_id": "item-key",
                "place_name": "대상",
                "feature_id": feature_id,
                "metadata": {},
                "collection_key": "collection",
                "feature_name": "잘못된 대상",
                "feature_addr": "잘못된 주소",
            }
        ]
        self.fail_finding_insert = fail_finding_insert
        self.findings: dict[str, dict[str, Any]] = (
            {"issue-id": {"status": "open"}} if existing_finding else {}
        )

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    async def fetch(self, _sql: str, _collection: str, _item: str) -> list[dict[str, Any]]:
        return self.rows

    async def fetchval(self, sql: str, *args: object) -> object:
        if sql == "select current_database()":
            return "test"
        if sql == h33._UNLINK_SQL:
            item_id, _metadata, expected = args
            for row in self.rows:
                if row["curation_item_id"] == item_id and row["feature_id"] == expected:
                    row["feature_id"] = None
                    return item_id
            return None
        if sql == h33._LOCK_FINDING_SQL:
            return None
        if sql == h33._FIND_EXISTING_SQL:
            return next(iter(self.findings), None)
        if sql == h33._INSERT_FINDING_SQL:
            if self.fail_finding_insert:
                raise RuntimeError("finding insert failed")
            self.findings["new-issue"] = {"status": "resolved"}
            return "new-issue"
        if sql == h33._UPDATE_FINDING_SQL:
            issue_id = str(args[0])
            self.findings[issue_id] = {"status": "resolved"}
            return issue_id
        raise AssertionError(f"unexpected SQL: {sql}")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_h33_finding_failure_rolls_back_unlink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = "feature:wrong"
    monkeypatch.setattr(
        h33,
        "MISLINKS",
        {("collection", "item-key"): (expected, "지역 불일치")},
    )
    conn = _FakeH33Connection(feature_id=expected, fail_finding_insert=True)

    with pytest.raises(RuntimeError, match="finding insert failed"):
        await h33.run(conn, apply=True)

    assert conn.rows[0]["feature_id"] == expected
    assert conn.findings == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_h33_guarded_current_link_does_not_create_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        h33,
        "MISLINKS",
        {("collection", "item-key"): ("feature:wrong", "지역 불일치")},
    )
    conn = _FakeH33Connection(feature_id="feature:correct")

    await h33.run(conn, apply=True)

    assert conn.rows[0]["feature_id"] == "feature:correct"
    assert conn.findings == {}


@pytest.mark.unit
def test_h33_public_verifier_rejects_500_and_empty_positive_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collections = [
        {"collection_key": key, "collection_id": key, "item_count": len(item_keys)}
        for key, item_keys in h33_verify.TARGET_ITEMS.items()
    ]

    def fake_get(path: str) -> tuple[int, dict]:
        if h33_verify.BOGUS_FEATURE in path:
            return 404, {}
        if path.startswith("/v1/curations/features/"):
            return 500, {}
        if path == "/v1/curations/collections?page_size=500":
            return 200, {"data": collections}
        if path.startswith("/v1/curations/collections/"):
            key = path.rsplit("/", 1)[-1]
            return 200, {
                "data": {
                    "items": [
                        {"external_item_id": item_key, "feature_id": None}
                        for item_key in h33_verify.TARGET_ITEMS[key]
                    ]
                }
            }
        if path.startswith("/v1/curations?q="):
            return 500, {}
        raise AssertionError(path)

    monkeypatch.setattr(h33_verify, "get", fake_get)

    assert h33_verify.main() == 1
