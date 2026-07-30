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
    filename: str = "approval.csv",
    metadata_values: tuple[str, ...] | None = None,
) -> Path:
    path = target / filename
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
        values = metadata_values or tuple("{}" for _ in feature_ids)
        for feature_id, metadata_json in zip(feature_ids, values, strict=True):
            writer.writerow(
                {
                    "collection_key": key[0],
                    "source_item_key": key[1],
                    "source_component_key": key[2],
                    "feature_id": feature_id,
                    "metadata_json": metadata_json,
                }
            )
    return path


def _write_manifest(target: Path, *csv_paths: Path) -> Path:
    manifest = target / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "files": [
                    {
                        "path": csv_path.name,
                        "sha256": hashlib.sha256(csv_path.read_bytes()).hexdigest(),
                        "rows": sum(
                            1
                            for _ in csv.DictReader(
                                csv_path.read_text(encoding="utf-8").splitlines()
                            )
                        ),
                    }
                    for csv_path in csv_paths
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


@pytest.mark.unit
def test_h25_apply_preflights_all_metadata_before_any_file_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    approvals = dict(list(h25.APPROVED.items())[:2])
    evidence = {key: h25.EVIDENCE[key] for key in approvals}
    monkeypatch.setattr(h25, "APPROVED", approvals)
    monkeypatch.setattr(h25, "EVIDENCE", evidence)
    (first_key, first_feature), (second_key, second_feature) = approvals.items()
    first = _write_approval_csv(
        tmp_path,
        key=first_key,
        feature_ids=("",),
        filename="a.csv",
    )
    second = _write_approval_csv(
        tmp_path,
        key=second_key,
        feature_ids=(second_feature,),
        filename="b.csv",
        metadata_values=("{broken",),
    )
    manifest = _write_manifest(tmp_path, first, second)
    before = {
        path: path.read_bytes()
        for path in (first, second, manifest)
    }

    with pytest.raises(RuntimeError, match="metadata_json이 올바르지 않음"):
        h25.apply_verified_links(tmp_path)

    assert {path: path.read_bytes() for path in before} == before
    assert first_feature


@pytest.mark.unit
def test_h25_apply_counts_changed_rows_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    key, expected = next(iter(h25.APPROVED.items()))
    monkeypatch.setattr(h25, "APPROVED", {key: expected})
    monkeypatch.setattr(h25, "EVIDENCE", {key: h25.EVIDENCE[key]})
    csv_path = _write_approval_csv(
        tmp_path,
        key=key,
        feature_ids=("",),
    )
    manifest = _write_manifest(tmp_path, csv_path)

    assert h25.apply_verified_links(tmp_path) == 1

    with csv_path.open(encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["feature_id"] == expected
    assert json.loads(row["metadata_json"])["feature_match_status"] == "linked"
    manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
    assert manifest_data["files"][0]["sha256"] == hashlib.sha256(
        csv_path.read_bytes()
    ).hexdigest()


@pytest.mark.unit
def test_h25_replace_outputs_rolls_back_on_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_bytes(b"old-a")
    second.write_bytes(b"old-b")
    real_replace = h25.os.replace
    replace_calls = 0

    def interrupt_second_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        if replace_calls == 2:
            raise KeyboardInterrupt
        real_replace(source, destination)

    monkeypatch.setattr(h25.os, "replace", interrupt_second_replace)

    with pytest.raises(KeyboardInterrupt):
        h25._replace_outputs({first: b"new-a", second: b"new-b"})

    assert first.read_bytes() == b"old-a"
    assert second.read_bytes() == b"old-b"
    assert list(tmp_path.glob(".*.tmp")) == []


@pytest.mark.unit
def test_h25_replace_outputs_rolls_back_after_rename_then_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "a.csv"
    second = tmp_path / "b.csv"
    first.write_bytes(b"old-a")
    second.write_bytes(b"old-b")
    real_replace = h25.os.replace
    replace_calls = 0

    def interrupt_after_first_replace(source: Path, destination: Path) -> None:
        nonlocal replace_calls
        replace_calls += 1
        real_replace(source, destination)
        if replace_calls == 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(h25.os, "replace", interrupt_after_first_replace)

    with pytest.raises(KeyboardInterrupt):
        h25._replace_outputs({first: b"new-a", second: b"new-b"})

    assert first.read_bytes() == b"old-a"
    assert second.read_bytes() == b"old-b"
    assert list(tmp_path.glob(".*.tmp")) == []


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
        sibling_feature_id: str | None | object = ...,
    ) -> None:
        self.rows = [
            {
                "curation_item_id": "item-id",
                "external_item_id": "item-key",
                "external_component_id": "primary",
                "place_name": "대상",
                "feature_id": feature_id,
                "metadata": {},
                "collection_key": "collection",
                "feature_name": "잘못된 대상",
                "feature_addr": "잘못된 주소",
            }
        ]
        if sibling_feature_id is not ...:
            self.rows.append(
                {
                    "curation_item_id": "sibling-id",
                    "external_item_id": "item-key",
                    "external_component_id": "component-02",
                    "place_name": "대상 형제",
                    "feature_id": sibling_feature_id,
                    "metadata": {},
                    "collection_key": "collection",
                    "feature_name": "형제 대상",
                    "feature_addr": "형제 주소",
                }
            )
        self.fail_finding_insert = fail_finding_insert
        self.findings: dict[str, dict[str, Any]] = (
            {"issue-id": {"status": "open"}} if existing_finding else {}
        )

    def transaction(self) -> _FakeTransaction:
        return _FakeTransaction(self)

    async def fetch(
        self,
        _sql: str,
        _collection: str,
        _item: str,
        component: str,
    ) -> list[dict[str, Any]]:
        return [
            row
            for row in self.rows
            if row["external_component_id"] == component
        ]

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
        {("collection", "item-key", "primary"): (expected, "지역 불일치")},
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
        {
            ("collection", "item-key", "primary"): (
                "feature:wrong",
                "지역 불일치",
            )
        },
    )
    conn = _FakeH33Connection(feature_id="feature:correct")

    await h33.run(conn, apply=True)

    assert conn.rows[0]["feature_id"] == "feature:correct"
    assert conn.findings == {}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_h33_already_unlinked_reconstructs_missing_resolved_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        h33,
        "MISLINKS",
        {
            ("collection", "item-key", "primary"): (
                "feature:wrong",
                "지역 불일치",
            )
        },
    )
    conn = _FakeH33Connection(feature_id=None)

    await h33.run(conn, apply=True)

    assert conn.rows[0]["feature_id"] is None
    assert conn.findings == {"new-issue": {"status": "resolved"}}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_h33_null_sibling_does_not_create_false_resolved_finding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        h33,
        "MISLINKS",
        {
            ("collection", "item-key", "primary"): (
                "feature:wrong",
                "지역 불일치",
            )
        },
    )
    conn = _FakeH33Connection(
        feature_id="feature:correct",
        sibling_feature_id=None,
    )

    await h33.run(conn, apply=True)

    assert conn.rows[0]["feature_id"] == "feature:correct"
    assert conn.rows[1]["feature_id"] is None
    assert conn.findings == {}


@pytest.mark.unit
def test_h33_public_verifier_rejects_500_and_empty_positive_control(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collections = [
        {
            "collection_key": key,
            "collection_id": key,
            "item_count": len(item_identities),
        }
        for key, item_identities in h33_verify.TARGET_ITEMS.items()
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
                        {
                            "external_item_id": item_key,
                            "external_component_id": component_key,
                            "feature_id": None,
                        }
                        for item_key, component_key in h33_verify.TARGET_ITEMS[key]
                    ]
                }
            }
        if path.startswith("/v1/curations?q="):
            return 500, {}
        raise AssertionError(path)

    monkeypatch.setattr(h33_verify, "get", fake_get)

    assert h33_verify.main() == 1


@pytest.mark.unit
def test_h33_public_verifier_requires_target_feature_id_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collections = [
        {
            "collection_key": key,
            "collection_id": key,
            "item_count": len(item_identities),
        }
        for key, item_identities in h33_verify.TARGET_ITEMS.items()
    ]

    def fake_get(path: str) -> tuple[int, dict]:
        if path.startswith("/v1/curations/features/"):
            return 404, {}
        if path == "/v1/curations/collections?page_size=500":
            return 200, {"data": collections}
        if path.startswith("/v1/curations/collections/"):
            key = path.rsplit("/", 1)[-1]
            return 200, {
                "data": {
                    "items": [
                        {
                            "external_item_id": item_key,
                            "external_component_id": component_key,
                        }
                        for item_key, component_key in h33_verify.TARGET_ITEMS[key]
                    ]
                }
            }
        if path.startswith("/v1/curations?q="):
            return 200, {
                "data": [
                    {"feature": {"feature_id": "feature:unrelated"}},
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(h33_verify, "get", fake_get)

    assert h33_verify.main() == 1


@pytest.mark.unit
def test_h33_public_verifier_rejects_target_replaced_by_null_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing_identity = ("kt100-2025-2026-024", "primary")
    collections = [
        {
            "collection_key": key,
            "collection_id": key,
            "item_count": len(item_identities),
        }
        for key, item_identities in h33_verify.TARGET_ITEMS.items()
    ]

    def fake_get(path: str) -> tuple[int, dict]:
        if path.startswith("/v1/curations/features/"):
            return 404, {}
        if path == "/v1/curations/collections?page_size=500":
            return 200, {"data": collections}
        if path.startswith("/v1/curations/collections/"):
            key = path.rsplit("/", 1)[-1]
            items = [
                {
                    "external_item_id": item_key,
                    "external_component_id": component_key,
                    "feature_id": None,
                }
                for item_key, component_key in h33_verify.TARGET_ITEMS[key]
                if (item_key, component_key) != missing_identity
            ]
            if key == "korean-tourism-100:2025-2026":
                items.append(
                    {
                        "external_item_id": missing_identity[0],
                        "external_component_id": "component-02",
                        "feature_id": None,
                    }
                )
            return 200, {"data": {"items": items}}
        if path.startswith("/v1/curations?q="):
            return 200, {
                "data": [
                    {"feature": {"feature_id": "feature:unrelated"}},
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(h33_verify, "get", fake_get)

    assert h33_verify.main() == 1


@pytest.mark.unit
def test_h33_public_verifier_ignores_legitimate_linked_sibling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sibling_item = "kt100-2025-2026-024"
    collections = [
        {
            "collection_key": key,
            "collection_id": key,
            "item_count": len(item_identities),
        }
        for key, item_identities in h33_verify.TARGET_ITEMS.items()
    ]

    def fake_get(path: str) -> tuple[int, dict]:
        if path.startswith("/v1/curations/features/"):
            return 404, {}
        if path == "/v1/curations/collections?page_size=500":
            return 200, {"data": collections}
        if path.startswith("/v1/curations/collections/"):
            key = path.rsplit("/", 1)[-1]
            items = [
                {
                    "external_item_id": item_key,
                    "external_component_id": component_key,
                    "feature_id": None,
                }
                for item_key, component_key in h33_verify.TARGET_ITEMS[key]
            ]
            if key == "korean-tourism-100:2025-2026":
                items.append(
                    {
                        "external_item_id": sibling_item,
                        "external_component_id": "component-02",
                        "feature_id": "feature:legitimate",
                    }
                )
            return 200, {"data": {"items": items}}
        if path.startswith("/v1/curations?q="):
            return 200, {
                "data": [
                    {"feature": {"feature_id": "feature:unrelated"}},
                ]
            }
        raise AssertionError(path)

    monkeypatch.setattr(h33_verify, "get", fake_get)

    assert h33_verify.main() == 0
