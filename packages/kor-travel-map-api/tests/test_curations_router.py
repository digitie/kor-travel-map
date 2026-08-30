"""큐레이션 collection/group/template REST 계약."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from collections.abc import AsyncIterator, Iterator, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from kortravelmap.curation_import import CURATION_CSV_HEADERS, parse_curation_csv
from kortravelmap.infra.curation_candidate_repo import (
    ThemeCandidatePage,
    ThemeCandidateRecord,
    ThemeCandidateTransitionPage,
    ThemeCandidateTransitionRecord,
)
from kortravelmap.infra.curation_repo import (
    CurationCollection,
    CurationImportBatch,
    CurationImportPlan,
    CurationImportResult,
    CurationImportRowReceipt,
    CurationItem,
    CurationLinkAudit,
    CurationQuarantineCollection,
    CurationQuarantineItem,
    CurationQuarantineItemsPreview,
    CurationQuarantineMoveConflict,
    CurationQuarantineMoveConflictError,
    CurationQuarantineOriginalCollection,
    CurationQuarantineSourceRef,
    CurationQuarantineThemeRef,
    FeatureCurationGroup,
    FeatureMatch,
)
from kortravelmap.infra.domain_command_repo import DomainCommandRecord

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings

COLLECTION_ID = "11111111-1111-4111-8111-111111111111"
ITEM_ID = "22222222-2222-4222-8222-222222222222"
CANDIDATE_ID = "33333333-3333-4333-8333-333333333333"


def _uuid(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, label))


def _theme_candidate() -> ThemeCandidateRecord:
    now = datetime(2026, 8, 13, tzinfo=UTC)
    return ThemeCandidateRecord(
        candidate_id=CANDIDATE_ID,
        rule_id=_uuid("rule"),
        theme_id=_uuid("theme"),
        theme_slug="coastal-cafes",
        theme_name="해안 카페",
        source_id=_uuid("source"),
        source_name="provider source",
        provider_dataset_id=101,
        source_entity_key="entity-1",
        feature_id="feature:one",
        feature_uuid=_uuid("feature:one"),
        feature_name="바다 카페",
        feature_kind="place",
        feature_category="01070100",
        feature_detail={"place_type": "cafe"},
        lifecycle_state="active",
        publication_state="published",
        quality_state="valid",
        source_record_key="record-1",
        source_record_hash="a" * 64,
        rule_row_revision=4,
        rule_input_hash="b" * 64,
        candidate_input_hash="c" * 64,
        review_state="open",
        eligibility_present=True,
        disposition="active",
        rank_score="0.750000",
        proposal_title="바다 카페",
        proposal_summary=None,
        match_evidence={"selector": "category"},
        row_revision=7,
        feature_row_revision=9,
        created_at=now,
        updated_at=now,
    )


class _FakeCatalogRow:
    """``provider_datasets`` 한 행 — 자연키와 canonical id."""

    def __init__(self, provider: str, dataset_key: str, provider_dataset_id: int) -> None:
        self.provider = provider
        self.dataset_key = dataset_key
        self.provider_dataset_id = provider_dataset_id


_CATALOG_ROWS: tuple[_FakeCatalogRow, ...] = (
    # 101은 **등대가 아닌** dataset이다 — 등대면 provenance가 필수라
    # 일반 import 경로를 검증할 수 없다. 102만 공식 등대다.
    _FakeCatalogRow("korea-lighthouse-museum", "lighthouse-museum-curations", 101),
    _FakeCatalogRow("korea-lighthouse-museum", "lighthouse-stamp-tour-season-5", 102),
    _FakeCatalogRow("korea-tourism-organization", "tourism-100-2026", 103),
)

#: ``_lighthouse_dataset_pairs``의 ``LIKE`` 술어와 같은 축. 공식 등대 판정은
#: 자연키 dataset_key prefix로만 한다 (``curation_provenance`` docstring).
_LIGHTHOUSE_DATASET_PREFIX = "lighthouse-stamp-tour-season-"


class _FakeResult:
    def __init__(self, rows: tuple[_FakeCatalogRow, ...]) -> None:
        self._rows = rows

    def __iter__(self) -> Iterator[_FakeCatalogRow]:
        return iter(self._rows)


class _FakeSession:
    """라우터 경계용 stub.

    CSV가 자연키를 들고 오므로 import 경로는 catalog에서 canonical
    ``provider_dataset_id``를 한 번 해석한다(T-VN-33). 이 stub은 그 조회에
    고정 매핑을 돌려준다 — 실제 해석은 통합 테스트가 검증한다.
    """

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def execute(
        self, statement: object, params: Mapping[str, Any] | None = None
    ) -> _FakeResult:
        """``provider_sync.provider_datasets`` 조회 2종을 술어까지 흉내낸다.

        둘 다 같은 표를 읽지만 술어가 다르다 — pair 해석은 (provider,
        dataset_key) 전부를, 등대 판정은 ``LIKE 'lighthouse-stamp-tour-season-%'``
        로 좁힌 것만 돌려준다. 술어를 무시하고 한 벌을 그대로 돌려주면 평범한
        dataset까지 공식 등대로 오판돼 모든 import가 provenance 422가 된다.
        """
        sql = str(statement)
        if sql == "SET TRANSACTION ISOLATION LEVEL SERIALIZABLE":
            return _FakeResult(())
        if "provider_sync.provider_datasets" not in sql:
            raise AssertionError(f"stub이 모르는 질의입니다: {sql}")
        bound = params or {}
        dataset_keys = frozenset(bound.get("dataset_keys", ()))
        rows = tuple(row for row in _CATALOG_ROWS if row.dataset_key in dataset_keys)
        providers = bound.get("providers")
        if providers is not None:
            pairs = frozenset(zip(providers, bound["dataset_keys"], strict=True))
            rows = tuple(row for row in rows if (row.provider, row.dataset_key) in pairs)
        if _LIGHTHOUSE_DATASET_PREFIX in sql:
            rows = tuple(
                row
                for row in rows
                if row.dataset_key.startswith(_LIGHTHOUSE_DATASET_PREFIX)
            )
        return _FakeResult(rows)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import curations as curations_router

    app = create_app(
        ApiSettings(
            admin_proxy_secret=None,
            public_api_key_required=False,
            vworld_api_key=None,
        )
    )

    async def _session() -> AsyncIterator[object]:
        yield _FakeSession()

    app.dependency_overrides[get_session] = _session
    monkeypatch.setattr(
        domain_command_service,
        "begin_domain_command",
        AsyncMock(
            return_value=domain_command_service.DomainCommandHandle(
                command_id=1,
                actor="local-dev",
                operation="admin.curation-item.patch",
                idempotency_key="95000000-0000-4000-8000-000000000001",
                request_fingerprint="a" * 64,
            )
        ),
    )
    monkeypatch.setattr(
        domain_command_service,
        "complete_domain_command",
        AsyncMock(),
    )
    monkeypatch.setattr(
        curations_router.curation_repo,
        "build_curation_import_revision_vector",
        AsyncMock(return_value=()),
    )
    monkeypatch.setattr(
        curations_router.curation_repo,
        "create_curation_import_plan_command",
        AsyncMock(),
    )
    return TestClient(
        app,
        headers={"Idempotency-Key": "95000000-0000-4000-8000-000000000001"},
    )


def _item(*, item_id: str, edition: str) -> CurationItem:
    now = datetime(2026, 7, 13, tzinfo=UTC)
    return CurationItem(
        curation_item_id=_uuid(item_id),
        collection_id=_uuid(f"collection-{edition}"),
        collection_key=f"tourism-100:{edition}",
        title=f"{edition} 한국관광 100선",
        edition_key=edition,
        theme_slug="korean-tourism-100",
        theme_name="한국관광 100선",
        theme_group="관광 선정",
        provider_dataset_id=101,
        provider="korea-tourism-organization",
        dataset_key=f"tourism-100-{edition}",
        source_name="문화체육관광부·한국관광공사",
        source_url="https://example.test/official",
        feature_id="feature:shared",
        # T-VN-32C — 응답 feature 참조 치환용 UUID 정본 (연결된 item은 필수).
        feature_uuid=_uuid("feature:shared"),
        feature_name="겹치는 관광지",
        feature_kind="place",
        feature_category="01070100",
        lon=126.978,
        lat=37.566,
        address={"road": "서울특별시"},
        source_record_key=f"source::{edition}",
        external_item_id=f"official-{edition}",
        external_component_id="primary",
        place_name="겹치는 관광지",
        address_hint="서울특별시",
        source_present=True,
        status="included",
        sort_order=1,
        item_title="겹치는 관광지",
        item_summary=None,
        curation_relation="nearby_option",
        reuse_policy="manual_review",
        metadata={"edition": edition},
        current_import_row_id=None,
        accepted_link_decision_id=None,
        link_match_basis=None,
        link_resolver_version=None,
        link_evidence={},
        link_actor=None,
        link_decided_at=None,
        row_revision=1,
        created_by="fixture-creator",
        updated_by="fixture-updater",
        created_at=now,
        updated_at=now,
        archived_at=None,
    )


def _collection() -> CurationCollection:
    now = datetime(2026, 7, 13, tzinfo=UTC)
    return CurationCollection(
        collection_id=COLLECTION_ID,
        collection_key="public-count-contract",
        theme_id="33333333-3333-4333-8333-333333333333",
        theme_slug="public-count-contract",
        theme_name="공개 건수 계약",
        theme_group="테스트",
        source_id="44444444-4444-4444-8444-444444444444",
        provider_dataset_id=101,
        provider="test-provider",
        dataset_key="test-dataset",
        source_name="테스트 출처",
        source_url=None,
        title="공개 건수 계약",
        edition_key="2026",
        description=None,
        status="published",
        visibility="public",
        metadata={},
        item_count=2,
        public_item_count=1,
        row_revision=1,
        created_by="fixture-creator",
        updated_by="fixture-updater",
        created_at=now,
        updated_at=now,
        archived_at=None,
    )


def _csv_content(
    *,
    valid: bool = True,
    feature_ids: tuple[str, ...] = ("",),
    address_hint: str = "",
    distinct_source_items: bool = False,
    official_ordinal: str = "",
    sort_order: str = "",
    official_lighthouse: bool = False,
    dataset_key: str | None = None,
) -> bytes:
    values = dict.fromkeys(CURATION_CSV_HEADERS, "")
    values.update(
        {
            "collection_key": "lighthouse:healing",
            "theme_slug": "lighthouse-stamp-tour-healing",
            "theme_name": "등대 스탬프투어 힐링",
            "theme_group": "등대 스탬프투어",
            "title": "힐링의 등대",
            "edition_key": "season-5",
            "provider": "korea-lighthouse-museum",
            "dataset_key": "lighthouse-museum-curations",
            "source_name": "국립등대박물관",
            "source_item_key": "healing:ganjeolgot",
            "source_component_key": "primary",
            "place_name": "간절곶등대" if valid else "",
            "address_hint": address_hint,
            "official_ordinal": official_ordinal,
            "sort_order": sort_order,
        }
    )
    if official_lighthouse:
        values.update(
            {
                "collection_key": "lighthouse-stamp-tour:healing-lighthouses:season-5",
                "dataset_key": "lighthouse-stamp-tour-season-5",
            }
        )
    if dataset_key is not None:
        values["dataset_key"] = dataset_key
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CURATION_CSV_HEADERS)
    writer.writeheader()
    for index, feature_id in enumerate(feature_ids, start=1):
        values["feature_id"] = feature_id
        if distinct_source_items:
            values["source_item_key"] = f"healing:ganjeolgot:{index}"
            values["source_component_key"] = "primary"
        elif len(feature_ids) > 1:
            values["source_component_key"] = f"component-{index:02d}"
        writer.writerow(values)
    return output.getvalue().encode()


def _provenance_content(csv_content: bytes) -> bytes:
    row = parse_curation_csv(csv_content).rows[0]
    return json.dumps(
        {
            "schema_version": 1,
            "source_csv_sha256": hashlib.sha256(csv_content).hexdigest(),
            "rows": [
                {
                    "collection_key": row.collection_key,
                    "source_item_key": row.source_item_key,
                    "source_component_key": row.source_component_key,
                    "source_type": "official_document",
                    "derivation": "document",
                    "source_urls": ["https://example.test/official-document"],
                    "observed_at": "2026-07-31T09:00:00+09:00",
                    "input_coordinate": None,
                    "probe_coordinate": None,
                    "resolved_coordinate": None,
                    "probe_offset_m": 0,
                    "returned_address": [
                        {"kind": "document", "text": "울산광역시 울주군"}
                    ],
                    "normalized_address": "울산광역시 울주군",
                    "confidence": "high",
                    "source_reference": "공식 문서 1쪽",
                    "rationale": "공식 주소 원문",
                }
            ],
        },
        ensure_ascii=False,
    ).encode()


@pytest.mark.unit
def test_csv_preview_and_commit_keep_unresolved_official_item(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[Any, ...]]:
        return {2: ()}

    async def _import(_session: object, **_kwargs: Any) -> CurationImportResult:
        return {
            "rows": 1,
            "collections": 1,
            "inserted": 1,
            "updated": 0,
            "removed": 2,
            "removals": (
                _item(item_id="removed-2023", edition="2023-2024"),
                _item(item_id="removed-2025", edition="2025-2026"),
            ),
            "import_batch_id": "55555555-5555-4555-8555-555555555555",
            "row_receipts": (),
        }

    async def _preview(_session: object, **_kwargs: Any) -> CurationImportPlan:
        return CurationImportPlan(
            collections=1,
            inserted=1,
            updated=0,
            removals=(
                _item(item_id="removed-2023", edition="2023-2024"),
                _item(item_id="removed-2025", edition="2025-2026"),
            ),
        )

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    monkeypatch.setattr(module.curation_repo, "preview_curation_import", _preview)
    monkeypatch.setattr(module.curation_repo, "import_curation_rows", _import)
    files = {"file": ("lighthouse.csv", _csv_content(), "text/csv")}

    preview = client.post("/v1/admin/curations/imports/preview", files=files)

    assert preview.status_code == 201
    assert preview.json()["data"]["unresolved_rows"] == 1
    assert preview.json()["data"]["items"][0]["status"] == "unmatched"
    assert preview.json()["data"]["removed"] == 2
    assert len(preview.json()["data"]["removals"]) == 2
    preview_data = preview.json()["data"]
    create_plan = module.curation_repo.create_curation_import_plan_command
    resolved_rows = create_plan.await_args.kwargs["rows"]
    expires_at = create_plan.await_args.kwargs["expires_at"]
    monkeypatch.setattr(
        module.curation_repo,
        "claim_curation_import_plan_command",
        AsyncMock(
            return_value=(
                "a" * 64,
                resolved_rows,
                {
                    "rows_total": preview_data["rows_total"],
                    "valid_rows": preview_data["valid_rows"],
                    "invalid_rows": preview_data["invalid_rows"],
                    "unresolved_rows": preview_data["unresolved_rows"],
                },
                preview_data["items"],
                expires_at,
            )
        ),
    )
    monkeypatch.setattr(
        module.curation_repo,
        "complete_curation_import_plan_command",
        AsyncMock(),
    )
    committed = client.post(
        f"/v1/admin/curations/import-plans/{preview_data['import_plan_id']}/commit",
        headers={"If-Match": preview_data["plan_etag"]},
    )

    assert committed.status_code == 200
    committed_data = committed.json()["data"]
    assert committed_data["inserted"] == 1
    assert committed_data["updated"] == 0
    assert committed_data["removed"] == 2
    assert len(committed_data["removals"]) == committed_data["removed"]
    assert committed_data["collections"] == 1
    assert committed_data["import_batch_id"] == "55555555-5555-4555-8555-555555555555"


@pytest.mark.unit
def test_official_lighthouse_import_requires_provenance_sidecar(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    matches = AsyncMock()
    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", matches)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "false"},
        files={
            "file": (
                "lighthouse-stamp-tour.csv",
                _csv_content(official_lighthouse=True),
                "text/csv",
            )
        },
    )

    assert response.status_code == 422
    assert "provenance_file" in response.json()["detail"]
    matches.assert_not_awaited()


@pytest.mark.unit
def test_import_preview_replay_finishes_before_mutable_catalog_lookup(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import curations as module

    monkeypatch.setattr(
        module.curation_repo,
        "resolve_feature_matches",
        AsyncMock(return_value={}),
    )
    monkeypatch.setattr(
        module.curation_repo,
        "preview_curation_import",
        AsyncMock(
            return_value=CurationImportPlan(
                collections=0,
                inserted=0,
                updated=0,
                removals=(),
            )
        ),
    )
    csv_content = _csv_content(official_lighthouse=True)
    files = {
        "file": ("lighthouse.csv", csv_content, "text/csv"),
        "provenance_file": (
            "lighthouse.provenance.json",
            _provenance_content(csv_content),
            "application/json",
        ),
    }
    first = client.post("/v1/admin/curations/imports/preview", files=files)
    assert first.status_code == 201
    etag = first.headers["ETag"]
    terminal = DomainCommandRecord(
        command_id=1,
        actor="local-dev",
        operation="admin.curation-import.preview",
        idempotency_key="95000000-0000-4000-8000-000000000001",
        fingerprint_version=1,
        request_fingerprint="a" * 64,
        response_status=201,
        response_body=first.json(),
        response_headers={"ETag": etag},
        claimed_at=datetime(2026, 8, 14, tzinfo=UTC),
        completed_at=datetime(2026, 8, 14, tzinfo=UTC),
    )
    begin = domain_command_service.begin_domain_command
    assert isinstance(begin, AsyncMock)
    begin.side_effect = domain_command_service.DomainCommandReplay(terminal)
    mutable_lookup = AsyncMock(side_effect=AssertionError("replay 뒤 catalog 조회"))
    monkeypatch.setattr(module, "_lighthouse_dataset_pairs", mutable_lookup)

    replay = client.post("/v1/admin/curations/imports/preview", files=files)

    assert replay.status_code == 201
    assert replay.headers["ETag"] == etag
    assert replay.json() == first.json()
    mutable_lookup.assert_not_awaited()


@pytest.mark.unit
def test_official_lighthouse_dataset_key_alone_requires_provenance_sidecar(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """collection_key가 등대 접두어가 아니어도 catalog dataset이 등대면 422다.

    T-VN-33이 남긴 두 번째 판정 축(자연키 pair를 catalog에서 확인)을 단독으로
    고정한다. 위 테스트의 CSV는 collection_key 접두어로도 걸려서 이 축이
    죽어도 통과한다 — 그러면 등대 seed가 provenance 없이 들어온다.
    """
    from kortravelmap.api.routers import curations as module

    matches = AsyncMock()
    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", matches)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "false"},
        files={
            "file": (
                "lighthouse-stamp-tour.csv",
                # collection_key는 기본값 `lighthouse:healing` — 접두어 축은 꺼진다.
                _csv_content(dataset_key="lighthouse-stamp-tour-season-5"),
                "text/csv",
            )
        },
    )

    assert response.status_code == 422
    assert "provenance_file" in response.json()["detail"]
    matches.assert_not_awaited()


@pytest.mark.unit
def test_official_lighthouse_import_rejects_mismatched_sidecar(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    content = _csv_content(official_lighthouse=True)
    provenance = json.loads(_provenance_content(content))
    provenance["source_csv_sha256"] = "0" * 64
    matches = AsyncMock()
    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", matches)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "false"},
        files={
            "file": ("lighthouse-stamp-tour.csv", content, "text/csv"),
            "provenance_file": (
                "lighthouse-stamp-tour.provenance.json",
                json.dumps(provenance).encode(),
                "application/json",
            ),
        },
    )

    assert response.status_code == 422
    assert "CSV와 일치하지 않습니다" in response.json()["detail"]
    matches.assert_not_awaited()


@pytest.mark.unit
def test_official_lighthouse_import_persists_validated_row_provenance(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    content = _csv_content(official_lighthouse=True)
    sidecar = _provenance_content(content)

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[Any, ...]]:
        return {2: ()}

    async def _preview(_session: object, **_kwargs: Any) -> CurationImportPlan:
        return CurationImportPlan(collections=1, inserted=1, updated=0, removals=())

    async def _import(
        _session: object,
        *,
        rows: tuple[Any, ...],
        **_kwargs: Any,
    ) -> CurationImportResult:
        assert rows[0].provenance == {
            "schema_version": 1,
            "source_csv_sha256": hashlib.sha256(content).hexdigest(),
            "row": {
                "collection_key": (
                    "lighthouse-stamp-tour:healing-lighthouses:season-5"
                ),
                "source_item_key": "healing:ganjeolgot",
                "source_component_key": "primary",
                "source_type": "official_document",
                "derivation": "document",
                "source_urls": ["https://example.test/official-document"],
                "observed_at": "2026-07-31T09:00:00+09:00",
                "input_coordinate": None,
                "probe_coordinate": None,
                "resolved_coordinate": None,
                "probe_offset_m": 0,
                "returned_address": [
                    {"kind": "document", "text": "울산광역시 울주군"}
                ],
                "normalized_address": "울산광역시 울주군",
                "confidence": "high",
                "source_reference": "공식 문서 1쪽",
                "rationale": "공식 주소 원문",
            },
        }
        return {
            "rows": 1,
            "collections": 1,
            "inserted": 1,
            "updated": 0,
            "removed": 0,
            "removals": (),
            "import_batch_id": "55555555-5555-4555-8555-555555555555",
            "row_receipts": (),
        }

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    monkeypatch.setattr(module.curation_repo, "preview_curation_import", _preview)
    monkeypatch.setattr(module.curation_repo, "import_curation_rows", _import)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "false"},
        files={
            "file": ("lighthouse-stamp-tour.csv", content, "text/csv"),
            "provenance_file": (
                "lighthouse-stamp-tour.provenance.json",
                sidecar,
                "application/json",
            ),
        },
    )

    assert response.status_code == 201
    stored_rows = (
        module.curation_repo.create_curation_import_plan_command.await_args.kwargs["rows"]
    )
    assert stored_rows[0].provenance["source_csv_sha256"] == hashlib.sha256(
        content
    ).hexdigest()
    assert response.json()["data"]["import_batch_id"] is None


@pytest.mark.unit
def test_admin_link_audit_exposes_fail_closed_items(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    decided_at = datetime(2026, 7, 31, tzinfo=UTC)
    audit = AsyncMock(
        return_value=(
            (
                CurationLinkAudit(
                    curation_item_id=ITEM_ID,
                    collection_key="lighthouse:healing",
                    external_item_id="healing:ganjeolgot",
                    external_component_id="primary",
                    feature_id="feature:legacy-link",
                    place_name="간절곶등대",
                    address_hint="울산광역시 울주군",
                    match_basis="legacy_unattributed",
                    resolver_version="pre-0072-unknown",
                    decided_at=decided_at,
                ),
            ),
            "opaque-next",
        )
    )
    monkeypatch.setattr(
        module.curation_repo,
        "list_unattributed_curation_links_page",
        audit,
    )

    response = client.get("/v1/admin/curations/link-audit", params={"limit": 25})

    assert response.status_code == 200
    assert response.json()["data"] == {
        "items": [
            {
                "curation_item_id": ITEM_ID,
                "collection_key": "lighthouse:healing",
                "external_item_id": "healing:ganjeolgot",
                "external_component_id": "primary",
                "feature_id": "feature:legacy-link",
                "place_name": "간절곶등대",
                "address_hint": "울산광역시 울주군",
                "match_basis": "legacy_unattributed",
                "resolver_version": "pre-0072-unknown",
                "decided_at": "2026-07-31T00:00:00Z",
            }
        ],
        "count": 1,
        "has_more": True,
        "next_cursor": "opaque-next",
    }
    audit.assert_awaited_once()
    assert audit.await_args.kwargs == {"limit": 25, "cursor": None}


@pytest.mark.unit
def test_admin_import_batch_and_current_row_expose_durable_provenance(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    imported_at = datetime(2026, 7, 31, 1, 2, 3, tzinfo=UTC)
    batch_id = "55555555-5555-4555-8555-555555555555"
    row_id = "66666666-6666-4666-8666-666666666666"
    row = CurationImportRowReceipt(
        import_row_id=row_id,
        import_batch_id=batch_id,
        curation_item_id=ITEM_ID,
        row_number=2,
        source_row_sha256="a" * 64,
        row_payload={"place_name": "간절곶등대"},
        provenance={
            "schema_version": 1,
            "source_csv_sha256": "b" * 64,
            "row": {"source_type": "official_document"},
        },
        imported_at=imported_at,
    )
    batch = CurationImportBatch(
        import_batch_id=batch_id,
        content_sha256="b" * 64,
        batch_kind="csv_upload",
        row_count=1,
        actor="admin:test",
        metadata={"schema_version": 1},
        imported_at=imported_at,
    )
    get_batch = AsyncMock(return_value=(batch, (row,)))
    get_current = AsyncMock(return_value=row)
    monkeypatch.setattr(module.curation_repo, "get_curation_import_batch", get_batch)
    monkeypatch.setattr(
        module.curation_repo,
        "get_current_curation_import_row",
        get_current,
    )

    batch_response = client.get(
        f"/v1/admin/curations/import-batches/{batch_id}"
    )
    row_response = client.get(
        f"/v1/admin/curations/items/{ITEM_ID}/current-import-row"
    )

    assert batch_response.status_code == 200
    assert batch_response.json()["data"]["content_sha256"] == "b" * 64
    assert batch_response.json()["data"]["rows"][0]["row_payload"] == {
        "place_name": "간절곶등대"
    }
    assert batch_response.json()["data"]["rows"][0]["provenance"] == row.provenance
    assert row_response.status_code == 200
    assert row_response.json()["data"]["import_row_id"] == row_id
    assert row_response.json()["data"]["provenance"] == row.provenance
    assert get_batch.await_args.kwargs == {"import_batch_id": batch_id}
    assert get_current.await_args.kwargs == {"curation_item_id": ITEM_ID}


@pytest.mark.unit
def test_csv_preview_persists_whole_file_format_errors_without_import(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[Any, ...]]:
        return {}

    async def _unexpected_import(_session: object, **_kwargs: Any) -> dict[str, int]:
        raise AssertionError("형식 오류 파일은 DB import를 호출하면 안 됩니다.")

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    monkeypatch.setattr(module.curation_repo, "import_curation_rows", _unexpected_import)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "false"},
        files={"file": ("invalid.csv", _csv_content(valid=False), "text/csv")},
    )

    assert response.status_code == 201
    assert response.json()["data"]["invalid_rows"] == 1
    assert response.json()["data"]["import_batch_id"] is None


@pytest.mark.unit
@pytest.mark.parametrize("dry_run", [True, False])
def test_csv_import_maps_legacy_adoption_conflict_to_422(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    dry_run: bool,
) -> None:
    from kortravelmap.api.routers import curations as module

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[Any, ...]]:
        return {2: ()}

    async def _preview(_session: object, **_kwargs: Any) -> CurationImportPlan:
        raise ValueError("legacy component identity 승계 후보가 모호합니다")

    async def _unexpected_import(_session: object, **_kwargs: Any) -> CurationImportResult:
        raise AssertionError("preview 충돌 뒤 import를 실행하면 안 됩니다.")

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    monkeypatch.setattr(module.curation_repo, "preview_curation_import", _preview)
    monkeypatch.setattr(module.curation_repo, "import_curation_rows", _unexpected_import)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": str(dry_run).lower()},
        files={"file": ("ambiguous.csv", _csv_content(), "text/csv")},
    )

    assert response.status_code == 422
    assert "승계 후보가 모호합니다" in response.json()["detail"]


@pytest.mark.unit
def test_csv_zero_official_ordinal_is_preserved_as_sort_order(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[Any, ...]]:
        return {2: ()}

    async def _preview(
        _session: object, *, rows: tuple[Any, ...]
    ) -> CurationImportPlan:
        assert rows[0].sort_order == 0
        return CurationImportPlan(collections=1, inserted=1, updated=0, removals=())

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    monkeypatch.setattr(module.curation_repo, "preview_curation_import", _preview)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "true"},
        files={
            "file": (
                "zero-ordinal.csv",
                _csv_content(official_ordinal="0"),
                "text/csv",
            )
        },
    )

    assert response.status_code == 201


@pytest.mark.unit
def test_csv_accepts_mixed_component_resolution(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[FeatureMatch, ...]]:
        return {
            2: (
                FeatureMatch(
                    feature_id="feature:active",
                    name="간절곶등대",
                    address={},
                    lon=129.36,
                    lat=35.36,
                    feature_uuid=_uuid("feature:active"),
                ),
            ),
            3: (),
        }

    async def _preview(
        _session: object, *, rows: tuple[Any, ...]
    ) -> CurationImportPlan:
        assert [row.source_component_key for row in rows] == [
            "component-01",
            "component-02",
        ]
        return CurationImportPlan(
            collections=1,
            inserted=2,
            updated=0,
            removals=(),
        )

    async def _import(
        _session: object,
        *,
        rows: tuple[Any, ...],
        actor: str,
        source_content_sha256: str,
        batch_kind: str,
        command_id: int,
    ) -> CurationImportResult:
        assert actor == "local-dev"
        assert len(source_content_sha256) == 64
        assert batch_kind == "csv_upload"
        assert command_id == 1
        return {
            "rows": len(rows),
            "collections": 1,
            "inserted": 2,
            "updated": 0,
            "removed": 0,
            "removals": (),
            "import_batch_id": "55555555-5555-4555-8555-555555555555",
            "row_receipts": (),
        }

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    monkeypatch.setattr(module.curation_repo, "preview_curation_import", _preview)
    monkeypatch.setattr(module.curation_repo, "import_curation_rows", _import)
    files = {
        "file": (
            "mixed.csv",
            _csv_content(feature_ids=("feature:active", "feature:missing")),
            "text/csv",
        )
    }

    preview = client.post("/v1/admin/curations/imports/preview", files=files)

    assert preview.status_code == 201
    assert preview.json()["data"]["invalid_rows"] == 0
    assert preview.json()["data"]["unresolved_rows"] == 1


@pytest.mark.unit
def test_csv_too_many_rows_does_not_count_unprocessed_row_as_valid(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[Any, ...]]:
        return {}

    async def _unexpected_preview(_session: object, **_kwargs: Any) -> Any:
        raise AssertionError("행 제한 오류 파일은 변경 preview를 실행하면 안 됩니다.")

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    monkeypatch.setattr(module.curation_repo, "preview_curation_import", _unexpected_preview)
    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "true"},
        files={
            "file": (
                "too-many.csv",
                _csv_content(
                    feature_ids=("",) * 2_001,
                    distinct_source_items=True,
                ),
                "text/csv",
            )
        },
    )

    data = response.json()["data"]
    assert response.status_code == 201
    assert data["rows_total"] == 2_001
    assert data["valid_rows"] == 2_000
    assert data["invalid_rows"] == 0
    assert "too_many_rows" in {issue["code"] for issue in data["issues"]}


@pytest.mark.unit
def test_public_group_returns_all_editions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    async def _groups(
        _session: object, **_kwargs: Any
    ) -> tuple[tuple[FeatureCurationGroup, ...], None]:
        return (
            (
                FeatureCurationGroup(
                    feature_id="feature:shared",
                    name="겹치는 관광지",
                    kind="place",
                    category="01070100",
                    lon=126.978,
                    lat=37.566,
                    address={"road": "서울특별시"},
                    lifecycle_state="active",
                    publication_state="published",
                    quality_state="valid",
                    curations=(
                        _item(item_id="item-2025", edition="2025-2026"),
                        _item(item_id="item-2023", edition="2023-2024"),
                    ),
                    feature_uuid=_uuid("feature:shared"),
                ),
            ),
            None,
        )

    monkeypatch.setattr(module.curation_repo, "list_feature_curation_groups", _groups)

    response = client.get("/v1/curations", params={"page_size": 10})

    assert response.status_code == 200
    group = response.json()["data"]["items"][0]
    # T-VN-32C 값 전환 — group feature record·item feature 참조 값은 UUID 정본.
    assert group["feature"]["feature_id"] == _uuid("feature:shared")
    # T-VN-34C: public curation은 visibility fence로만 feature를 읽는다. internal
    # axes는 admin 표면에만 있으므로 collection response에 노출하지 않는다.
    assert "lifecycle_state" not in group["feature"]
    assert "publication_state" not in group["feature"]
    assert "quality_state" not in group["feature"]
    assert "status" not in group["feature"]
    assert group["curation_count"] == 2
    assert {item["edition_key"] for item in group["curations"]} == {
        "2023-2024",
        "2025-2026",
    }
    for item in group["curations"]:
        assert "source_record_key" not in item
        assert "metadata" not in item


@pytest.mark.unit
def test_public_collection_count_hides_non_public_items(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    async def _collections(
        _session: object, **_kwargs: Any
    ) -> tuple[tuple[CurationCollection, ...], None]:
        return ((_collection(),), None)

    monkeypatch.setattr(module.curation_repo, "list_curation_collections", _collections)
    response = client.get("/v1/curations/collections")
    payload = response.json()["data"]["items"][0]

    assert response.status_code == 200
    assert payload["item_count"] == 1
    assert "public_item_count" not in payload
    assert "metadata" not in payload


@pytest.mark.unit
def test_admin_csv_template_has_bom_header_and_download_name(
    client: TestClient,
) -> None:
    response = client.get("/v1/admin/curations/import-template.csv")

    assert response.status_code == 200
    assert response.content.startswith(b"\xef\xbb\xbfcollection_key,")
    assert "kor-travel-map-curations-template.csv" in response.headers["content-disposition"]
    assert "text/csv" in response.headers["content-type"]


@pytest.mark.unit
def test_admin_can_patch_and_archive_single_curation_item(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    calls: list[tuple[str, dict[str, Any]]] = []

    async def _update(_session: object, **kwargs: Any) -> CurationItem:
        calls.append(("patch", kwargs))
        return _item(item_id=kwargs["curation_item_id"], edition="2026")

    async def _archive(_session: object, **kwargs: Any) -> CurationItem:
        calls.append(("delete", kwargs))
        return _item(item_id=kwargs["curation_item_id"], edition="2026")

    monkeypatch.setattr(module.curation_repo, "patch_curation_item_command", _update)
    monkeypatch.setattr(module.curation_repo, "archive_curation_item_command", _archive)

    patched = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}/items/{ITEM_ID}",
        headers={"If-Match": '"1"'},
        json={"feature_id": "feature:resolved", "address_hint": None},
    )
    archived = client.delete(
        f"/v1/admin/curations/{COLLECTION_ID}/items/{ITEM_ID}",
        headers={"If-Match": '"1"'},
    )

    assert patched.status_code == 200
    assert archived.status_code == 200
    assert calls[0] == (
        "patch",
        {
            "collection_id": COLLECTION_ID,
            "curation_item_id": ITEM_ID,
            "updates": {"feature_id": "feature:resolved", "address_hint": None},
            "expected_revision": 1,
            "command_id": 1,
            "principal": "local-dev",
        },
    )
    assert calls[1][0] == "delete"
    assert calls[1][1]["principal"] == "local-dev"
    assert calls[1][1]["command_id"] == 1
    assert calls[1][1]["expected_revision"] == 1
    assert patched.json()["data"]["created_by"] == "fixture-creator"
    assert patched.json()["data"]["source_record_key"] == "source::2026"
    assert patched.json()["data"]["metadata"] == {"edition": "2026"}


@pytest.mark.unit
def test_admin_empty_patch_does_not_expose_archived_curation_item(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    async def _archived_noop(_session: object, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(module.curation_repo, "patch_curation_item_command", _archived_noop)
    response = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}/items/{ITEM_ID}",
        headers={"If-Match": '"1"'},
        json={},
    )

    assert response.status_code == 404


@pytest.mark.unit
def test_admin_collection_representation_etag_and_command_cas_are_distinct(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    collection = _collection()
    item = _item(item_id="etag-item", edition="2026")
    get_collection = AsyncMock(return_value=(collection, (item,)))
    update_collection = AsyncMock(return_value=collection)
    monkeypatch.setattr(
        module.curation_repo,
        "get_curation_collection",
        get_collection,
    )
    monkeypatch.setattr(
        module.curation_repo,
        "patch_curation_collection_command",
        update_collection,
    )

    fetched = client.get(f"/v1/admin/curations/{COLLECTION_ID}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["collection"]["row_revision"] == "1"
    assert fetched.json()["data"]["collection"]["command_etag"] == '"1"'
    assert fetched.json()["data"]["items"][0]["command_etag"] == '"1"'
    assert fetched.headers["etag"].startswith('"sha256:')

    not_modified = client.get(
        f"/v1/admin/curations/{COLLECTION_ID}",
        headers={"If-None-Match": fetched.headers["etag"]},
    )
    assert not_modified.status_code == 304

    missing = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}",
        json={"title": "변경"},
    )
    changed = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}",
        headers={"If-Match": '"1"'},
        json={"title": "변경"},
    )
    assert missing.status_code == 428
    assert changed.status_code == 200
    assert changed.headers["etag"].startswith('"sha256:')
    assert update_collection.await_args.kwargs["expected_revision"] == 1
    assert update_collection.await_args.kwargs["principal"] == "local-dev"
    assert isinstance(update_collection.await_args.kwargs["command_id"], int)


@pytest.mark.unit
def test_admin_collection_and_item_stale_revisions_return_412(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    stale = module.curation_repo.CurationRevisionConflictError("stale")
    monkeypatch.setattr(
        module.curation_repo,
        "patch_curation_collection_command",
        AsyncMock(side_effect=stale),
    )
    monkeypatch.setattr(
        module.curation_repo,
        "patch_curation_item_command",
        AsyncMock(side_effect=stale),
    )

    collection_response = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}",
        headers={"If-Match": '"1"'},
        json={"title": "변경"},
    )
    item_response = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}/items/{ITEM_ID}",
        headers={"If-Match": '"1"'},
        json={"item_title": "변경"},
    )

    assert collection_response.status_code == 412
    assert item_response.status_code == 412


@pytest.mark.unit
def test_admin_item_post_is_create_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    async def _duplicate(_session: object, **_kwargs: Any) -> CurationItem:
        raise HTTPException(status_code=409, detail="curation item identity conflict")

    monkeypatch.setattr(module.curation_repo, "create_curation_item_command", _duplicate)
    response = client.post(
        f"/v1/admin/curations/{COLLECTION_ID}/items",
        json={
            "external_item_id": "existing-item",
            "place_name": "이미 존재하는 항목",
        },
    )

    assert response.status_code == 409


@pytest.mark.unit
def test_admin_curation_uuid_and_archive_status_are_validated(
    client: TestClient,
) -> None:
    bad_path = client.get("/v1/admin/curations/not-a-uuid")
    bad_theme = client.post(
        "/v1/admin/curations",
        json={
            "collection_key": "bad-theme-id",
            "theme_id": "not-a-uuid",
            "title": "잘못된 UUID",
        },
    )
    archived_collection = client.post(
        "/v1/admin/curations",
        json={
            "collection_key": "archived-create",
            "theme_id": "33333333-3333-4333-8333-333333333333",
            "title": "생성 시 archived 금지",
            "status": "archived",
        },
    )
    archived_item = client.post(
        f"/v1/admin/curations/{COLLECTION_ID}/items",
        json={
            "external_item_id": "archived-create",
            "place_name": "생성 시 archived 금지",
            "status": "archived",
        },
    )
    null_collection_metadata = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}", json={"metadata": None}
    )
    null_collection_title = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}", json={"title": None}
    )
    null_item_place_name = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}/items/{ITEM_ID}",
        json={"place_name": None},
    )
    overflow_item = client.post(
        f"/v1/admin/curations/{COLLECTION_ID}/items",
        json={
            "external_item_id": "overflow-order",
            "place_name": "범위 초과",
            "sort_order": 2_147_483_648,
        },
    )
    overflow_item_patch = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}/items/{ITEM_ID}",
        json={"sort_order": 2_147_483_648},
    )

    assert bad_path.status_code == 422
    assert bad_theme.status_code == 422
    assert archived_collection.status_code == 422
    assert archived_item.status_code == 422
    assert null_collection_metadata.status_code == 422
    assert null_collection_title.status_code == 422
    assert null_item_place_name.status_code == 422
    assert overflow_item.status_code == 422
    assert overflow_item_patch.status_code == 422


@pytest.mark.unit
def test_curation_paths_are_in_openapi(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    paths = spec["paths"]
    assert "/v1/curations" in paths
    assert "/v1/curations/features/{feature_id}" in paths
    assert "/v1/admin/curations/imports/preview" in paths
    assert "/v1/admin/curations/import-batches/{import_batch_id}" in paths
    assert "/v1/admin/curations/import-template.csv" in paths
    assert (
        "/v1/admin/curations/items/{curation_item_id}/current-import-row"
        in paths
    )
    assert "/v1/admin/curations/link-audit" in paths
    assert "/v1/admin/curations/{collection_id}/items/{curation_item_id}" in paths
    collection_parameter = next(
        parameter
        for parameter in paths["/v1/admin/curations/{collection_id}"]["get"]["parameters"]
        if parameter["name"] == "collection_id"
    )
    assert collection_parameter["schema"]["format"] == "uuid"
    template_content = paths["/v1/admin/curations/import-template.csv"]["get"]["responses"]["200"][
        "content"
    ]
    assert set(template_content) == {"text/csv"}




@pytest.mark.unit
def test_legacy_curated_read_routes_survive_the_fence(client: TestClient) -> None:
    """읽기는 살아 있어야 한다 — soak 동안 legacy를 읽어 canonical과 대조한다.

    fence dependency가 method를 안 보고 전부 410을 주면 이 테스트가 잡는다.
    """
    # 이 fixture의 client는 DB를 스텁한다. GET은 fence를 통과한 뒤 스텁 repo까지 내려가
    # 예외로 죽을 수 있다 — 그게 정확히 "fence를 통과했다"는 증거다. fence에 걸리면
    # 예외 없이 410 응답이 돌아온다. 그래서 응답이 오면 410이 아님을, 예외가 나면
    # 그 예외가 HTTPException(410)이 아님을 각각 확인한다.
    from fastapi import HTTPException

    status: int | None
    try:
        status = client.get("/v1/admin/features/curated").status_code
    except HTTPException as exc:
        status = exc.status_code
    except Exception:  # noqa: BLE001 — 스텁 repo가 GET을 못 받아 죽는 것은 fence 통과의 증거
        status = None
    assert status != 410, "read까지 fence에 걸렸다 — dependency가 method를 안 본다"


@pytest.mark.unit
def test_theme_catalog_write_routes_are_not_fenced(client: TestClient) -> None:
    """theme/source/rule catalog는 legacy가 아니다 — fence 대상이 아니다.

    plan:28이 그 셋을 "catalog input만 유지"로 정했고 T-VN-40이 새 procedure로 쓴다.
    fence가 `/admin` prefix 전체를 잡으면 여기서 잡힌다 — 그러면 T-VN-40 자체가 깨진다.
    """
    response = client.post("/v1/admin/curated-themes", json={})
    assert response.status_code != 410, "theme catalog write가 fence에 걸렸다 — plan:28 위반"


@pytest.mark.unit
@pytest.mark.parametrize(
    "spoof_field",
    ["actor", "selected_by", "operator_updated_by", "updated_by", "created_by"],
)
def test_canonical_item_writes_reject_spoofable_provenance_in_body(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, spoof_field: str
) -> None:
    """ADR-066 D-2 — canonical item write는 body의 provenance 필드를 422로 거부한다.

    fence로 지운 legacy 라우터 테스트 6개 중 'body actor 거부·spoofable provenance 거부'의
    canonical 대응이다(적대 리뷰 P2). actor는 인증 principal에서만 온다 — 위
    `test_admin_can_patch_and_archive_single_curation_item`이 그 양성 케이스
    (`principal == "local-dev"`)고, 여기는 음성 케이스다: body에 provenance를 실으면
    `extra="forbid"`가 422를 내고 **repo command는 호출되지 않는다.**
    """
    from kortravelmap.api.routers import curations as module

    called: list[str] = []

    async def _create(_session: object, **_kwargs: Any) -> CurationItem:
        called.append("create")
        return _item(item_id=ITEM_ID, edition="2026")

    async def _patch(_session: object, **_kwargs: Any) -> CurationItem:
        called.append("patch")
        return _item(item_id=ITEM_ID, edition="2026")

    monkeypatch.setattr(module.curation_repo, "create_curation_item_command", _create)
    monkeypatch.setattr(module.curation_repo, "patch_curation_item_command", _patch)

    created = client.post(
        f"/v1/admin/curations/{COLLECTION_ID}/items",
        json={
            "external_item_id": "spoof-item",
            "place_name": "provenance 위조 시도",
            spoof_field: "attacker",
        },
    )
    patched = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}/items/{ITEM_ID}",
        headers={"If-Match": '"1"'},
        json={"feature_id": "feature:resolved", spoof_field: "attacker"},
    )

    assert created.status_code == 422, (created.status_code, created.text)
    assert patched.status_code == 422, (patched.status_code, patched.text)
    assert called == [], f"422여야 할 요청이 repo command까지 닿았다: {called}"


def _namesake_match(feature_id: str, name: str, sido_name: str) -> FeatureMatch:
    """이름은 같지만 지역이 다른 후보. 실제 사고를 그대로 본뜬 것이다."""
    return FeatureMatch(
        feature_id=feature_id,
        name=name,
        address={"road": f"{sido_name} 어딘가 1", "sido_name": sido_name},
        lon=127.0,
        lat=37.5,
        feature_uuid=_uuid(feature_id),
    )


@pytest.mark.unit
def test_blank_feature_id_never_autolinks_on_single_name_match(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """빈 feature_id + 유일한 동명 후보 → 링크하지 않는다 (T-VN-H36 핵심)."""
    from kortravelmap.api.routers import curations as module

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[Any, ...]]:
        return {2: (_namesake_match("f_seoul_namesake", "간절곶등대", "서울특별시"),)}

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    async def _preview(_session: object, **_kwargs: Any) -> CurationImportPlan:
        return CurationImportPlan(collections=1, inserted=0, updated=0, removals=())

    monkeypatch.setattr(module.curation_repo, "preview_curation_import", _preview)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "true"},
        files={"file": ("official.csv", _csv_content(), "text/csv")},
    )

    assert response.status_code == 201
    row = response.json()["data"]["items"][0]
    assert row["resolved_feature_id"] is None, "이름만 맞는 후보를 자동 링크했다"
    assert row["status"] == "review_required"
    codes = [issue["code"] for issue in row["issues"]]
    assert codes == ["name_only_match"]
    # 후보는 버리지 않는다 — 운영자가 preview에서 보고 직접 링크할 수 있어야 한다.
    # T-VN-32C 값 전환 — 후보 표시 feature_id는 UUID 정본.
    assert [c["feature_id"] for c in row["candidates"]] == [
        _uuid("f_seoul_namesake")
    ]


@pytest.mark.unit
def test_blank_feature_id_with_address_hint_requires_explicit_review(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """이름+주소 유일 후보도 preview로만 보이고 자동 링크하지 않는다."""
    from kortravelmap.api.routers import curations as module

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[Any, ...]]:
        return {
            2: (
                _namesake_match(
                    "feature:ganjeolgot",
                    "간절곶등대",
                    "울산광역시",
                ),
            )
        }

    async def _preview(_session: object, **_kwargs: Any) -> CurationImportPlan:
        return CurationImportPlan(collections=1, inserted=1, updated=0, removals=())

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    monkeypatch.setattr(module.curation_repo, "preview_curation_import", _preview)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "true"},
        files={
            "file": (
                "official.csv",
                _csv_content(address_hint="울산광역시 울주군"),
                "text/csv",
            )
        },
    )

    assert response.status_code == 201
    row = response.json()["data"]["items"][0]
    assert row["resolved_feature_id"] is None
    assert row["status"] == "review_required"
    assert [issue["code"] for issue in row["issues"]] == [
        "address_candidate_requires_review"
    ]
    # T-VN-32C 값 전환 — 후보 표시 feature_id는 UUID 정본.
    assert [candidate["feature_id"] for candidate in row["candidates"]] == [
        _uuid("feature:ganjeolgot")
    ]


@pytest.mark.unit
def test_blank_feature_id_reason_names_the_candidate_region(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """사유가 '그냥 안 붙었다'와 구분돼야 한다 — 후보 소재지를 말한다."""
    from kortravelmap.api.routers import curations as module

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[Any, ...]]:
        return {2: (_namesake_match("f_seoul_namesake", "간절곶등대", "서울특별시"),)}

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    async def _preview(_session: object, **_kwargs: Any) -> CurationImportPlan:
        return CurationImportPlan(collections=1, inserted=0, updated=0, removals=())

    monkeypatch.setattr(module.curation_repo, "preview_curation_import", _preview)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "true"},
        files={"file": ("official.csv", _csv_content(), "text/csv")},
    )

    message = response.json()["data"]["items"][0]["issues"][0]["message"]
    assert "서울특별시" in message, message
    assert "T-VN-H36" in message
    assert "어긋" not in message


@pytest.mark.unit
def test_no_candidates_still_reports_unmatched_not_name_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """음성 대조. 후보가 아예 없는 행은 여전히 `unmatched`여야 한다.

    이게 없으면 "모든 행이 미연결"이라는 결과가 수정의 성공인지 아니면 리졸버가
    통째로 죽은 것인지 구분되지 않는다.
    """
    from kortravelmap.api.routers import curations as module

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[Any, ...]]:
        return {2: ()}

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    async def _preview(_session: object, **_kwargs: Any) -> CurationImportPlan:
        return CurationImportPlan(collections=1, inserted=0, updated=0, removals=())

    monkeypatch.setattr(module.curation_repo, "preview_curation_import", _preview)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "true"},
        files={"file": ("official.csv", _csv_content(), "text/csv")},
    )

    row = response.json()["data"]["items"][0]
    assert row["status"] == "unmatched"
    assert [issue["code"] for issue in row["issues"]] == ["unmatched"]
    assert row["candidates"] == []


@pytest.mark.unit
def test_explicit_feature_id_still_links(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """양성 대조. CSV가 feature_id를 적은 행은 그대로 링크돼야 한다.

    이게 없으면 위 테스트들은 "링크 기능을 통째로 껐다"로도 통과한다.
    """
    from kortravelmap.api.routers import curations as module

    async def _matches(_session: object, **_kwargs: Any) -> dict[int, tuple[Any, ...]]:
        return {2: (_namesake_match("feature:active", "간절곶등대", "울산광역시"),)}

    monkeypatch.setattr(module.curation_repo, "resolve_feature_matches", _matches)
    async def _preview(_session: object, **_kwargs: Any) -> CurationImportPlan:
        return CurationImportPlan(collections=1, inserted=0, updated=0, removals=())

    monkeypatch.setattr(module.curation_repo, "preview_curation_import", _preview)

    response = client.post(
        "/v1/admin/curations/imports/preview",
        params={"dry_run": "true"},
        files={
            "file": (
                "official.csv",
                _csv_content(feature_ids=("feature:active",)),
                "text/csv",
            )
        },
    )

    row = response.json()["data"]["items"][0]
    # T-VN-32C — resolved는 응답 표시 필드라 UUID 정본, requested는 CSV 원문
    # echo 보존(치환 금지).
    assert row["resolved_feature_id"] == _uuid("feature:active")
    assert row["requested_feature_id"] == "feature:active"
    assert row["status"] == "valid"
    assert row["issues"] == []


def _quarantine_collection_row() -> CurationQuarantineCollection:
    return CurationQuarantineCollection(
        collection_id=_uuid("quarantine-collection"),
        row_revision=7,
        collection_key=f"legacy:quarantine:{_uuid('quarantine-collection')}",
        title="[0065 격리] 등대 스탬프투어",
        edition_key="season-5",
        status="draft",
        visibility="admin_only",
        created_by="migration:0065",
        item_count=2,
        marker_intact=True,
        quarantine_theme=CurationQuarantineThemeRef(
            theme_id=_uuid("quarantine-theme"),
            theme_slug="lighthouse-stamp-tour",
            theme_name="등대 스탬프투어",
            theme_group="official",
            visibility="public",
        ),
        quarantine_source=CurationQuarantineSourceRef(
            source_id=_uuid("quarantine-source"),
            provider_dataset_id=101,
            provider="korea-navigation-aids-agency",
            dataset_key="lighthouse-stamp-tour",
            source_name="국립등대박물관",
        ),
        original_collection=CurationQuarantineOriginalCollection(
            collection_id=_uuid("original-collection"),
            row_revision=11,
            title="등대 스탬프투어",
            status="published",
            visibility="public",
            exists=True,
            theme=CurationQuarantineThemeRef(
                theme_id=_uuid("original-theme"),
                theme_slug="lighthouse-stamp-tour-2026",
                theme_name="등대 스탬프투어 2026",
                theme_group="official",
                visibility="public",
            ),
            source=None,
        ),
    )


@pytest.mark.unit
def test_admin_quarantine_list_uses_adr048_page_envelope(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`data.items` + `meta.page.{page_size,next_cursor}` 봉투 고정.

    link-audit의 ADR-048 위반 shape(`data.{count,has_more,next_cursor}`)를
    따라하지 않는다.
    """
    from kortravelmap.api.routers import curations as module

    listing = AsyncMock(return_value=((_quarantine_collection_row(),), "opaque-next"))
    monkeypatch.setattr(
        module.curation_repo,
        "list_curation_quarantine_collections",
        listing,
    )

    response = client.get("/v1/admin/curations/quarantine", params={"page_size": 25})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"data", "meta"}
    assert set(body["data"]) == {"items"}
    row = body["data"]["items"][0]
    assert row["collection_id"] == _uuid("quarantine-collection")
    assert row["marker_intact"] is True
    assert row["item_count"] == 2
    assert row["quarantine_theme"]["theme_slug"] == "lighthouse-stamp-tour"
    assert row["quarantine_source"]["provider"] == "korea-navigation-aids-agency"
    assert row["original_collection"]["exists"] is True
    assert row["original_collection"]["theme"]["theme_slug"] == (
        "lighthouse-stamp-tour-2026"
    )
    assert row["original_collection"]["source"] is None
    page = body["meta"]["page"]
    assert page["page_size"] == 25
    assert "next_cursor" in page
    assert page["next_cursor"] == "opaque-next"
    assert listing.await_args.kwargs == {"limit": 25, "cursor": None}


@pytest.mark.unit
def test_admin_quarantine_list_serializes_exhausted_cursor_as_null(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    listing = AsyncMock(return_value=((), None))
    monkeypatch.setattr(
        module.curation_repo,
        "list_curation_quarantine_collections",
        listing,
    )

    response = client.get("/v1/admin/curations/quarantine")

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"] == []
    assert body["meta"]["page"]["page_size"] == 50
    assert "next_cursor" in body["meta"]["page"]
    assert body["meta"]["page"]["next_cursor"] is None


@pytest.mark.unit
def test_admin_quarantine_items_expose_conflict_preview(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    preview = CurationQuarantineItemsPreview(
        target_collection_id=_uuid("original-collection"),
        target_collection_revision=11,
        target_missing=False,
        target_archived=False,
        items=(
            CurationQuarantineItem(
                curation_item_id=_uuid("quarantine-item-movable"),
                external_item_id="probe-1",
                external_component_id="primary",
                feature_id=None,
                place_name="간절곶등대",
                status="included",
                source_present=True,
                archived_at=None,
                conflict_kind="movable",
                conflict_item_id=None,
            ),
            CurationQuarantineItem(
                curation_item_id=_uuid("quarantine-item-conflict"),
                external_item_id="probe-2",
                external_component_id="primary",
                feature_id="feature:shared",
                place_name="겹치는 관광지",
                status="included",
                source_present=True,
                archived_at=None,
                conflict_kind="component_identity_conflict",
                conflict_item_id=_uuid("occupant-item"),
            ),
        ),
    )
    items = AsyncMock(return_value=(preview, None))
    monkeypatch.setattr(module.curation_repo, "list_curation_quarantine_items", items)

    response = client.get(
        f"/v1/admin/curations/quarantine/{_uuid('quarantine-collection')}/items",
        params={"target_collection_id": _uuid("explicit-target")},
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["target_collection_id"] == _uuid("original-collection")
    assert data["target_missing"] is False
    assert data["target_archived"] is False
    assert [item["conflict_kind"] for item in data["items"]] == [
        "movable",
        "component_identity_conflict",
    ]
    assert data["items"][1]["conflict_item_id"] == _uuid("occupant-item")
    assert "next_cursor" in response.json()["meta"]["page"]
    assert items.await_args.kwargs == {
        "collection_id": _uuid("quarantine-collection"),
        "target_collection_id": _uuid("explicit-target"),
        "limit": 50,
        "cursor": None,
    }


@pytest.mark.unit
def test_admin_quarantine_items_404_without_canonical_marker(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    items = AsyncMock(return_value=None)
    monkeypatch.setattr(module.curation_repo, "list_curation_quarantine_items", items)

    response = client.get(
        f"/v1/admin/curations/quarantine/{_uuid('not-quarantine')}/items"
    )

    assert response.status_code == 404


@pytest.mark.unit
def test_reclassify_idempotency_lifecycle(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """최초 200 → 같은 key+같은 body는 `Idempotency-Replayed: true` 재생 →
    같은 key+다른 body는 409 `IDEMPOTENCY_KEY_REUSED`."""
    from kortravelmap.infra.domain_command_repo import (
        DomainCommandClaim,
        DomainCommandRecord,
    )

    from kortravelmap.api import domain_command_service
    from kortravelmap.api.routers import curations as module

    move = AsyncMock(return_value=((_uuid("moved-item"),), True))
    monkeypatch.setattr(module.curation_repo, "move_curation_quarantine_items", move)
    path = f"/v1/admin/curations/quarantine/{_uuid('quarantine-collection')}/reclassify"

    first = client.post(
        path,
        headers={"If-Match": '"7"'},
        json={"action": "move", "target_collection_revision": "11"},
    )

    assert first.status_code == 200
    assert first.headers["etag"].startswith('"sha256:')
    assert first.json()["data"] == {
        "action": "move",
        "moved_item_ids": [_uuid("moved-item")],
        "quarantine_collection_deleted": True,
        "collection_id": None,
        "collection_key": None,
    }
    assert move.await_args.kwargs == {
        "collection_id": _uuid("quarantine-collection"),
        "expected_collection_revision": 7,
        "target_collection_id": None,
        "expected_target_revision": 11,
        "item_ids": None,
        "command_id": 1,
        "actor": "local-dev",
    }

    now = datetime(2026, 8, 4, tzinfo=UTC)
    record = DomainCommandRecord(
        command_id=1,
        actor="local-dev",
        operation="admin.curation-quarantine.reclassify",
        idempotency_key="95000000-0000-4000-8000-000000000001",
        fingerprint_version=1,
        request_fingerprint="a" * 64,
        response_status=200,
        response_body=first.json(),
        response_headers={"ETag": first.headers["etag"]},
        claimed_at=now,
        completed_at=now,
    )

    async def _replay(*_args: Any, **_kwargs: Any) -> Any:
        raise domain_command_service.DomainCommandReplay(record)

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _replay)
    move.reset_mock()

    replayed = client.post(
        path,
        headers={"If-Match": '"7"'},
        json={"action": "move", "target_collection_revision": "11"},
    )

    assert replayed.status_code == 200
    assert replayed.headers["Idempotency-Replayed"] == "true"
    assert replayed.headers["etag"] == first.headers["etag"]
    assert replayed.json() == first.json()
    move.assert_not_awaited()

    claim = DomainCommandClaim(
        command_id=1,
        actor="local-dev",
        operation="admin.curation-quarantine.reclassify",
        idempotency_key="95000000-0000-4000-8000-000000000001",
        fingerprint_version=1,
        request_fingerprint="a" * 64,
        created_at=now,
    )

    async def _conflicted(*_args: Any, **_kwargs: Any) -> Any:
        raise domain_command_service.DomainCommandFingerprintConflict(claim)

    monkeypatch.setattr(domain_command_service, "begin_domain_command", _conflicted)

    reused = client.post(
        path,
        headers={"If-Match": '"7"'},
        json={
            "action": "move",
            "target_collection_revision": "11",
            "item_ids": [_uuid("other-item")],
        },
    )

    assert reused.status_code == 409
    assert reused.json()["code"] == "IDEMPOTENCY_KEY_REUSED"
    move.assert_not_awaited()


@pytest.mark.unit
def test_reclassify_move_conflict_fails_closed_with_conflict_detail(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    conflict = CurationQuarantineMoveConflictError(
        (
            CurationQuarantineMoveConflict(
                curation_item_id=_uuid("quarantine-item-conflict"),
                conflict_kind="component_identity_conflict",
                conflict_item_id=_uuid("occupant-item"),
            ),
        )
    )
    move = AsyncMock(side_effect=conflict)
    monkeypatch.setattr(module.curation_repo, "move_curation_quarantine_items", move)

    response = client.post(
        f"/v1/admin/curations/quarantine/{_uuid('quarantine-collection')}/reclassify",
        headers={"If-Match": '"7"'},
        json={"action": "move", "target_collection_revision": "11"},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "CURATION_QUARANTINE_MOVE_CONFLICT"
    assert body["details"]["conflicts"] == [
        {
            "curation_item_id": _uuid("quarantine-item-conflict"),
            "conflict_kind": "component_identity_conflict",
            "conflict_item_id": _uuid("occupant-item"),
        }
    ]


@pytest.mark.unit
def test_reclassify_confirm_standalone_returns_confirmed_key(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    confirm = AsyncMock(
        return_value=(_uuid("quarantine-collection"), "lighthouse:standalone")
    )
    monkeypatch.setattr(
        module.curation_repo,
        "confirm_curation_quarantine_standalone",
        confirm,
    )

    response = client.post(
        f"/v1/admin/curations/quarantine/{_uuid('quarantine-collection')}/reclassify",
        headers={"If-Match": '"7"'},
        json={
            "action": "confirm_standalone",
            "collection_key": "lighthouse:standalone",
            "title": "등대 독립 확정",
        },
    )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "action": "confirm_standalone",
        "moved_item_ids": None,
        "quarantine_collection_deleted": None,
        "collection_id": _uuid("quarantine-collection"),
        "collection_key": "lighthouse:standalone",
    }
    assert confirm.await_args.kwargs == {
        "collection_id": _uuid("quarantine-collection"),
        "expected_collection_revision": 7,
        "collection_key": "lighthouse:standalone",
        "title": "등대 독립 확정",
        "command_id": 1,
        "actor": "local-dev",
    }


@pytest.mark.unit
def test_reclassify_missing_quarantine_maps_lookup_error_to_404(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    move = AsyncMock(side_effect=LookupError("curation quarantine collection 없음"))
    monkeypatch.setattr(module.curation_repo, "move_curation_quarantine_items", move)

    response = client.post(
        f"/v1/admin/curations/quarantine/{_uuid('not-quarantine')}/reclassify",
        headers={"If-Match": '"7"'},
        json={"action": "move", "target_collection_revision": "11"},
    )

    assert response.status_code == 404


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        {"action": "move", "collection_key": "not-allowed"},
        {"action": "move", "item_ids": []},
        {"action": "confirm_standalone"},
        {"action": "confirm_standalone", "collection_key": "only-key"},
        {
            "action": "confirm_standalone",
            "collection_key": "k",
            "title": "t",
            "item_ids": ["22222222-2222-4222-8222-222222222222"],
        },
    ],
)
def test_reclassify_rejects_action_field_mismatch(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    body: dict[str, Any],
) -> None:
    from kortravelmap.api.routers import curations as module

    move = AsyncMock()
    confirm = AsyncMock()
    monkeypatch.setattr(module.curation_repo, "move_curation_quarantine_items", move)
    monkeypatch.setattr(
        module.curation_repo,
        "confirm_curation_quarantine_standalone",
        confirm,
    )

    response = client.post(
        f"/v1/admin/curations/quarantine/{_uuid('quarantine-collection')}/reclassify",
        json=body,
    )

    assert response.status_code == 422
    move.assert_not_awaited()
    confirm.assert_not_awaited()


@pytest.mark.unit
def test_admin_theme_candidate_list_uses_and_filters_and_decimal_revisions(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    listing = AsyncMock(
        return_value=ThemeCandidatePage((_theme_candidate(),), "opaque-next")
    )
    monkeypatch.setattr(
        module.curation_candidate_repo,
        "list_theme_candidates",
        listing,
    )

    response = client.get(
        "/v1/admin/theme-feature-candidates",
        params={
            "rule_id": _uuid("rule"),
            "theme_id": _uuid("theme"),
            "source_id": _uuid("source"),
            "review_state": "open",
            "eligibility_present": "true",
            "feature_id": "feature:one",
            "page_size": 25,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["items"][0]["feature_id"] == _uuid("feature:one")
    assert body["data"]["items"][0]["candidate_revision"] == "7"
    assert body["data"]["items"][0]["feature_row_revision"] == "9"
    assert body["meta"]["page"]["page_size"] == 25
    assert body["meta"]["page"]["next_cursor"] == "opaque-next"
    assert listing.await_args.kwargs == {
        "rule_id": _uuid("rule"),
        "theme_id": _uuid("theme"),
        "source_id": _uuid("source"),
        "review_state": "open",
        "eligibility_present": True,
        "feature_id": "feature:one",
        "limit": 25,
        "cursor": None,
    }


@pytest.mark.unit
def test_admin_theme_candidate_detail_has_separate_representation_etag_and_304(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    detail = AsyncMock(return_value=_theme_candidate())
    monkeypatch.setattr(module.curation_candidate_repo, "get_theme_candidate", detail)
    path = f"/v1/admin/theme-feature-candidates/{CANDIDATE_ID}"

    first = client.get(path)

    assert first.status_code == 200
    representation_etag = first.headers["etag"]
    assert representation_etag.startswith('"sha256:')
    assert first.json()["data"]["candidate_etag"] == '"7"'
    assert first.json()["data"]["representation_etag"] == representation_etag

    cached = client.get(path, headers={"If-None-Match": representation_etag})

    assert cached.status_code == 304
    assert cached.content == b""
    assert cached.headers["etag"] == representation_etag


@pytest.mark.unit
def test_admin_theme_candidate_transition_ids_are_decimal_strings(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    now = datetime(2026, 8, 13, tzinfo=UTC)
    monkeypatch.setattr(
        module.curation_candidate_repo,
        "get_theme_candidate",
        AsyncMock(return_value=_theme_candidate()),
    )
    listing = AsyncMock(
        return_value=ThemeCandidateTransitionPage(
            (
                ThemeCandidateTransitionRecord(
                    transition_id=9_007_199_254_740_993,
                    candidate_id=CANDIDATE_ID,
                    transition_kind="admin_reject",
                    from_review_state="open",
                    to_review_state="rejected",
                    from_eligibility_present=True,
                    to_eligibility_present=True,
                    candidate_row_revision=8,
                    generation_id=None,
                    command_id=9_007_199_254_740_995,
                    actor="local-dev",
                    reason_code="not_relevant",
                    causation_ref={"command_id": 9_007_199_254_740_995},
                    occurred_at=now,
                ),
            ),
            9_007_199_254_740_993,
        )
    )
    monkeypatch.setattr(
        module.curation_candidate_repo,
        "list_theme_candidate_transitions",
        listing,
    )

    response = client.get(
        f"/v1/admin/theme-feature-candidates/{CANDIDATE_ID}/transitions"
    )

    assert response.status_code == 200
    row = response.json()["data"]["items"][0]
    assert row["transition_id"] == "9007199254740993"
    assert row["command_id"] == "9007199254740995"
    assert response.json()["meta"]["page"]["next_cursor"] == "9007199254740993"


@pytest.mark.unit
def test_admin_theme_candidate_reject_requires_revision_and_returns_new_etag(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    reject = AsyncMock(return_value=(CANDIDATE_ID, 8, 101))
    monkeypatch.setattr(
        module.curation_candidate_repo,
        "reject_theme_candidate",
        reject,
    )
    path = f"/v1/admin/theme-feature-candidates/{CANDIDATE_ID}/reject"

    missing = client.post(path, json={"reason_code": "not_relevant"})
    accepted = client.post(
        path,
        headers={"If-Match": '"7"'},
        json={"reason_code": "not_relevant"},
    )

    assert missing.status_code == 428
    assert accepted.status_code == 200
    assert accepted.headers["etag"] == '"8"'
    assert accepted.json()["data"] == {
        "candidate_id": CANDIDATE_ID,
        "candidate_revision": "8",
        "transition_id": "101",
        "curation_item_id": None,
        "curation_item_revision": None,
    }
    assert reject.await_args.kwargs == {
        "candidate_id": CANDIDATE_ID,
        "expected_revision": 7,
        "command_id": 1,
        "reason_code": "not_relevant",
        "principal": "local-dev",
    }


@pytest.mark.unit
def test_admin_theme_candidate_promote_passes_all_cas_axes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from kortravelmap.api.routers import curations as module

    item_id = _uuid("promoted-item")
    promote = AsyncMock(return_value=(CANDIDATE_ID, 8, item_id, 3, 102))
    monkeypatch.setattr(
        module.curation_candidate_repo,
        "promote_theme_candidate",
        promote,
    )

    response = client.post(
        f"/v1/admin/theme-feature-candidates/{CANDIDATE_ID}/promote",
        headers={"If-Match": '"7"'},
        json={
            "collection_id": COLLECTION_ID,
            "collection_revision": "11",
            "item_revision": None,
            "external_item_id": "candidate-1",
            "external_component_id": "primary",
            "place_name": "바다 카페",
            "sort_order": 2,
            "curation_relation": "nearby_option",
            "reuse_policy": "manual_review",
            "item_status": "included",
            "reason_code": "approved",
        },
    )

    assert response.status_code == 200
    assert response.headers["etag"] == '"8"'
    assert response.json()["data"]["curation_item_id"] == item_id
    assert response.json()["data"]["curation_item_revision"] == "3"
    assert promote.await_args.kwargs == {
        "candidate_id": CANDIDATE_ID,
        "collection_id": COLLECTION_ID,
        "external_item_id": "candidate-1",
        "external_component_id": "primary",
        "place_name": "바다 카페",
        "address_hint": None,
        "item_title": None,
        "item_summary": None,
        "sort_order": 2,
        "curation_relation": "nearby_option",
        "reuse_policy": "manual_review",
        "item_status": "included",
        "expected_candidate_revision": 7,
        "expected_collection_revision": 11,
        "expected_item_revision": None,
        "command_id": 1,
        "reason_code": "approved",
        "principal": "local-dev",
    }
