"""큐레이션 collection/group/template REST 계약."""

from __future__ import annotations

import csv
import io
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, uuid5

import pytest
from fastapi.testclient import TestClient
from kortravelmap.curation_import import CURATION_CSV_HEADERS
from kortravelmap.infra.curation_repo import (
    CurationCollection,
    CurationImportPlan,
    CurationImportResult,
    CurationItem,
    FeatureCurationGroup,
    FeatureMatch,
)

from kortravelmap.api.app import create_app
from kortravelmap.api.db import get_session
from kortravelmap.api.settings import ApiSettings

COLLECTION_ID = "11111111-1111-4111-8111-111111111111"
ITEM_ID = "22222222-2222-4222-8222-222222222222"


def _uuid(label: str) -> str:
    return str(uuid5(NAMESPACE_URL, label))


class _FakeSession:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    @asynccontextmanager
    async def begin(self) -> AsyncIterator[None]:
        yield


@pytest.fixture
def client() -> TestClient:
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
    return TestClient(app)


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
        provider="korea-tourism-organization",
        dataset_key=f"tourism-100-{edition}",
        source_name="문화체육관광부·한국관광공사",
        source_url="https://example.test/official",
        feature_id="feature:shared",
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
    distinct_source_items: bool = False,
    official_ordinal: str = "",
    sort_order: str = "",
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
            "provider": "korea-navigation-aids-agency",
            "dataset_key": "lighthouse-stamp-tour",
            "source_name": "국립등대박물관",
            "source_item_key": "healing:ganjeolgot",
            "source_component_key": "primary",
            "place_name": "간절곶등대" if valid else "",
            "official_ordinal": official_ordinal,
            "sort_order": sort_order,
        }
    )
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

    preview = client.post("/v1/admin/curations/import", params={"dry_run": "true"}, files=files)
    committed = client.post("/v1/admin/curations/import", params={"dry_run": "false"}, files=files)

    assert preview.status_code == 200
    assert preview.json()["data"]["unresolved_rows"] == 1
    assert preview.json()["data"]["items"][0]["status"] == "unmatched"
    assert preview.json()["data"]["removed"] == 2
    assert len(preview.json()["data"]["removals"]) == 2
    assert committed.status_code == 200
    committed_data = committed.json()["data"]
    assert committed_data["inserted"] == 1
    assert committed_data["updated"] == 0
    assert committed_data["removed"] == 2
    assert len(committed_data["removals"]) == committed_data["removed"]
    assert committed_data["collections"] == 1


@pytest.mark.unit
def test_csv_commit_rejects_whole_file_on_format_error(
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
        "/v1/admin/curations/import",
        params={"dry_run": "false"},
        files={"file": ("invalid.csv", _csv_content(valid=False), "text/csv")},
    )

    assert response.status_code == 422


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
        "/v1/admin/curations/import",
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
        "/v1/admin/curations/import",
        params={"dry_run": "true"},
        files={
            "file": (
                "zero-ordinal.csv",
                _csv_content(official_ordinal="0"),
                "text/csv",
            )
        },
    )

    assert response.status_code == 200


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
        _session: object, *, rows: tuple[Any, ...], actor: str
    ) -> CurationImportResult:
        assert actor == "local-dev"
        return {
            "rows": len(rows),
            "collections": 1,
            "inserted": 2,
            "updated": 0,
            "removed": 0,
            "removals": (),
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

    preview = client.post("/v1/admin/curations/import", params={"dry_run": "true"}, files=files)
    commit = client.post("/v1/admin/curations/import", params={"dry_run": "false"}, files=files)

    assert preview.status_code == 200
    assert preview.json()["data"]["invalid_rows"] == 0
    assert preview.json()["data"]["unresolved_rows"] == 1
    assert commit.status_code == 200


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
        "/v1/admin/curations/import",
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
    assert response.status_code == 200
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
                    status="active",
                    curations=(
                        _item(item_id="item-2025", edition="2025-2026"),
                        _item(item_id="item-2023", edition="2023-2024"),
                    ),
                ),
            ),
            None,
        )

    monkeypatch.setattr(module.curation_repo, "list_feature_curation_groups", _groups)

    response = client.get("/v1/curations", params={"page_size": 10})

    assert response.status_code == 200
    group = response.json()["data"]["items"][0]
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

    monkeypatch.setattr(module.curation_repo, "update_curation_item", _update)
    monkeypatch.setattr(module.curation_repo, "archive_curation_item", _archive)

    patched = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}/items/{ITEM_ID}",
        json={"feature_id": "feature:resolved", "address_hint": None},
    )
    archived = client.delete(f"/v1/admin/curations/{COLLECTION_ID}/items/{ITEM_ID}")

    assert patched.status_code == 200
    assert archived.status_code == 200
    assert calls[0] == (
        "patch",
        {
            "collection_id": COLLECTION_ID,
            "curation_item_id": ITEM_ID,
            "updates": {"feature_id": "feature:resolved", "address_hint": None},
            "actor": "local-dev",
        },
    )
    assert calls[1][0] == "delete"
    assert calls[1][1]["actor"] == "local-dev"
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

    monkeypatch.setattr(module.curation_repo, "update_curation_item", _archived_noop)
    response = client.patch(
        f"/v1/admin/curations/{COLLECTION_ID}/items/{ITEM_ID}",
        json={},
    )

    assert response.status_code == 404


@pytest.mark.unit
def test_admin_item_post_is_create_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curations as module

    async def _duplicate(_session: object, **_kwargs: Any) -> tuple[CurationItem, bool]:
        return _item(item_id="existing-item", edition="2026"), False

    monkeypatch.setattr(module.curation_repo, "add_curation_item", _duplicate)
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
    assert "/v1/admin/curations/import" in paths
    assert "/v1/admin/curations/import-template.csv" in paths
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
def test_curated_select_records_principal_not_body_actor(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # T-VN-20 (ADR-066 D-2): curated select는 인증 principal(local-dev)을 actor로
    # 넘겨야 한다. row None → 404지만 repo가 받은 actor kwarg로 검증한다.
    from kortravelmap.api.routers import curated as module

    captured: dict[str, Any] = {}

    async def _set(_session: object, **kwargs: Any) -> None:
        captured.update(kwargs)
        return

    monkeypatch.setattr(module.curated_repo, "set_curated_feature_status", _set)
    response = client.post(
        "/v1/admin/features/curated/cf-1/select",
        json={"reason": "admin select"},
    )
    assert response.status_code == 404
    assert captured["actor"] == "local-dev"
    assert captured["curation_status"] == "curated"


@pytest.mark.unit
def test_curated_select_rejects_removed_actor_field(client: TestClient) -> None:
    # T-VN-20 (ADR-066 D-2): 제거된 body actor 필드를 보내면 extra="forbid"로 422.
    response = client.post(
        "/v1/admin/features/curated/cf-1/select",
        json={"actor": "attacker", "reason": "x"},
    )
    assert response.status_code == 422


@pytest.mark.unit
def test_curated_legacy_admin_writes_record_authenticated_principal(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from kortravelmap.api.routers import curated as module

    calls: list[tuple[str, dict[str, Any]]] = []

    async def _create(_session: object, **kwargs: Any) -> None:
        calls.append(("create", kwargs))
        raise ValueError("captured")

    async def _update(_session: object, **kwargs: Any) -> None:
        calls.append(("update", kwargs))
        raise ValueError("captured")

    async def _archive(_session: object, **kwargs: Any) -> None:
        calls.append(("archive", kwargs))

    monkeypatch.setattr(module.curated_repo, "create_curated_feature", _create)
    monkeypatch.setattr(module.curated_repo, "update_curated_feature", _update)
    monkeypatch.setattr(module.curated_repo, "archive_curated_feature", _archive)

    create_response = client.post(
        "/v1/admin/features/curated",
        json={
            "theme_id": "11111111-1111-4111-8111-111111111111",
            "feature_id": "feature:principal",
            "source_id": "22222222-2222-4222-8222-222222222222",
            "curation_status": "curated",
        },
    )
    patch_response = client.patch(
        "/v1/admin/features/curated/cf-1",
        json={"curation_relation": "primary_stop"},
    )
    delete_response = client.delete("/v1/admin/features/curated/cf-1")

    assert create_response.status_code == 422
    assert patch_response.status_code == 422
    assert delete_response.status_code == 404
    assert calls == [
        (
            "create",
            {
                "theme_id": "11111111-1111-4111-8111-111111111111",
                "feature_id": "feature:principal",
                "source_id": "22222222-2222-4222-8222-222222222222",
                "source_record_key": None,
                "curation_status": "curated",
                "rejection_reason": None,
                "rank_score": 0.0,
                "display_title": None,
                "display_summary": None,
                "curation_relation": "nearby_option",
                "reuse_policy": "manual_review",
                "metadata": {},
                "selection_origin": "admin",
                "selected_by": "local-dev",
                "rejected_by": None,
                "actor": "local-dev",
            },
        ),
        (
            "update",
            {
                "curated_feature_id": "cf-1",
                "updates": {"curation_relation": "primary_stop"},
                "actor": "local-dev",
            },
        ),
        (
            "archive",
            {
                "curated_feature_id": "cf-1",
                "actor": "local-dev",
            },
        ),
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("selection_origin", "external_api"),
        ("selected_by", "attacker"),
        ("rejected_by", "attacker"),
    ],
)
def test_curated_create_rejects_spoofable_provenance_fields(
    client: TestClient, field: str, value: str
) -> None:
    response = client.post(
        "/v1/admin/features/curated",
        json={
            "theme_id": "11111111-1111-4111-8111-111111111111",
            "feature_id": "feature:spoof",
            "source_id": "22222222-2222-4222-8222-222222222222",
            field: value,
        },
    )
    assert response.status_code == 422


@pytest.mark.unit
@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        (
            "post",
            "/v1/admin/features/curated",
            {
                "theme_id": "11111111-1111-4111-8111-111111111111",
                "feature_id": "feature:reserved-metadata",
                "source_id": "22222222-2222-4222-8222-222222222222",
                "metadata": {"merge_projection_detached": True},
            },
        ),
        (
            "patch",
            "/v1/admin/features/curated/cf-1",
            {"metadata": {"merge_projection_detached": False}},
        ),
    ],
)
def test_curated_write_rejects_reserved_detach_marker(
    client: TestClient,
    method: str,
    path: str,
    payload: dict[str, Any],
) -> None:
    response = client.request(method, path, json=payload)
    assert response.status_code == 422


# --- T-VN-H36: 이름 단독 일치로는 자동 링크하지 않는다 ---------------------------
#
# 회귀 대상은 실제로 일어난 사고다. 한국관광100선 "남이섬"이 서울 중구의 동명 업소
# feature에 붙어 공개 응답에 나왔다(T-VN-H33이 해제). prod에 그 이름의 live feature가
# 하나뿐이라 옛 규칙(`matches[0] if len(matches) == 1`)이 항상 "유일 매칭"으로 채택했다.


def _namesake_match(feature_id: str, name: str, sido_name: str) -> FeatureMatch:
    """이름은 같지만 지역이 다른 후보. 실제 사고를 그대로 본뜬 것이다."""
    return FeatureMatch(
        feature_id=feature_id,
        name=name,
        address={"road": f"{sido_name} 어딘가 1", "sido_name": sido_name},
        lon=127.0,
        lat=37.5,
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
        "/v1/admin/curations/import",
        params={"dry_run": "true"},
        files={"file": ("official.csv", _csv_content(), "text/csv")},
    )

    assert response.status_code == 200
    row = response.json()["data"]["items"][0]
    assert row["resolved_feature_id"] is None, "이름만 맞는 후보를 자동 링크했다"
    assert row["status"] == "ambiguous"
    codes = [issue["code"] for issue in row["issues"]]
    assert codes == ["name_only_match"]
    # 후보는 버리지 않는다 — 운영자가 preview에서 보고 직접 링크할 수 있어야 한다.
    assert [c["feature_id"] for c in row["candidates"]] == ["f_seoul_namesake"]


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
        "/v1/admin/curations/import",
        params={"dry_run": "true"},
        files={"file": ("official.csv", _csv_content(), "text/csv")},
    )

    message = response.json()["data"]["items"][0]["issues"][0]["message"]
    assert "서울특별시" in message, message
    assert "T-VN-H36" in message


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
        "/v1/admin/curations/import",
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
        "/v1/admin/curations/import",
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
    assert row["resolved_feature_id"] == "feature:active"
    assert row["status"] == "valid"
    assert row["issues"] == []
