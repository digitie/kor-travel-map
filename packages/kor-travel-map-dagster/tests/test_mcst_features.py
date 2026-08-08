"""MCST Dagster asset/fetcher 단위 테스트 (T-220 재배선, #395)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from dagster import AssetKey, build_asset_context
from kortravelmap.client import IntegrityFindingSyncResult
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.dto import Address, Coordinate
from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.providers.mcst import MCST_FILE_DATASETS
from kortravelmap.settings import KorTravelMapSettings

from kortravelmap.dagster import mcst_features as mcst_module
from kortravelmap.dagster.feature_operation_tracking import (
    FeatureOperationExecutionGuard,
)
from kortravelmap.dagster.mcst_features import (
    feature_place_mcst_culture,
    group_records_by_slug,
    run_feature_place_mcst_culture,
)
from kortravelmap.dagster.provider_fetchers import fetch_mcst_culture_records

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


def _common_row(name: str) -> dict[str, Any]:
    """공통 방언 A CSV row (실측 컬럼 모양)."""
    return {
        "TITLE": name,
        "ADDRESS": "서울특별시 종로구 세종대로 1",
        "COORDINATES": "N37.5665, E126.978",
        "RNUM": "1",
    }


async def _fake_reverse(_coord: Coordinate) -> Address:
    return Address(bjd_code="1111010100", sido_name="서울특별시")


class _FakeBundleLoadClient:
    def __init__(self) -> None:
        self.loaded: list[Any] = []

    async def load_feature_bundles(self, bundles: Any) -> FeatureLoadResult:
        materialized = list(bundles)
        self.loaded.extend(materialized)
        return FeatureLoadResult(
            bundles_total=len(materialized), features_inserted=len(materialized)
        )

    async def record_address_validation_findings(
        self, findings: object, **kwargs: object
    ) -> IntegrityFindingSyncResult:
        """T-VN-H30A: durable finding 기록 (테스트 double은 보관만 한다)."""
        self.recorded_findings = list(findings)  # type: ignore[arg-type]
        count = len(self.recorded_findings)
        return IntegrityFindingSyncResult(count, count, count)


def _context(records: list[Any]) -> Any:
    return build_asset_context(
        resources={
            "kor_travel_map_client": _FakeBundleLoadClient(),
            "reverse_geocoder": _fake_reverse,
            "fetched_at": None,
            "strict_address": True,
            "mcst_culture_records": records,
        }
    )


def test_group_records_by_slug_preserves_order() -> None:
    grouped = group_records_by_slug(
        [("a", 1), ("b", 2), ("a", 3)],
    )
    assert grouped == {"a": [1, 3], "b": [2]}


async def test_culture_asset_loads_per_slug_datasets() -> None:
    records = [
        ("independent_bookstores_csv", _common_row("서점 1")),
        ("world_restaurants_csv", _common_row("식당 1")),
        ("independent_bookstores_csv", _common_row("서점 2")),
    ]

    result = await run_feature_place_mcst_culture(_context(records))

    assert result.provider == "python-mcst-api"
    assert {r.dataset_key for r in result.results} == {
        "mcst_independent_bookstores_csv",
        "mcst_world_restaurants_csv",
    }
    by_key = {r.dataset_key: r for r in result.results}
    assert by_key["mcst_independent_bookstores_csv"].load.bundles_total == 2
    assert by_key["mcst_world_restaurants_csv"].load.bundles_total == 1
    assert result.bundles_total == 3
    assert result.as_metadata()["datasets_loaded"] == 2


async def test_culture_asset_rejects_unknown_slug() -> None:
    with pytest.raises(KeyError, match="nope"):
        await run_feature_place_mcst_culture(_context([("nope", _common_row("어딘가"))]))


async def test_culture_asset_rejects_excluded_slug() -> None:
    """제외 dataset(예: public_libraries)은 메타표에 없어 적재 시도 시 실패."""
    with pytest.raises(KeyError, match="public_libraries"):
        await run_feature_place_mcst_culture(
            _context([("public_libraries", {"도서관명": "더불어 숲"})])
        )


async def test_culture_asset_skips_unidentifiable_rows_with_warning() -> None:
    records = [
        ("golf_courses_status", {"이름": "라데나골프클럽", "소재지": "춘천시 1"}),
        # 이름 없는 row — 변환에서 제외(경고 로그).
        ("golf_courses_status", {"소재지": "어딘가"}),
    ]

    result = await run_feature_place_mcst_culture(_context(records))

    by_key = {r.dataset_key: r for r in result.results}
    assert by_key["mcst_golf_courses_status"].load.bundles_total == 1
    assert result.bundles_total == 1


async def test_culture_raw_callback_completes_exact_membership_snapshot() -> None:
    memberships = tuple(
        ProviderDatasetOperationMembership(
            provider_dataset_id=index,
            sync_scope="dataset_wide",
            operation_key="feature_place_mcst_culture_job",
        )
        for index, _spec in enumerate(MCST_FILE_DATASETS.values(), start=1)
    )
    completed: list[ProviderDatasetOperationMembership] = []

    async def _done(
        completed_memberships: tuple[ProviderDatasetOperationMembership, ...],
    ) -> None:
        completed.extend(completed_memberships)

    result = await run_feature_place_mcst_culture(
        _context([]),
        memberships=memberships,
        on_memberships_completed=_done,
    )

    assert result.results == ()
    assert completed == list(memberships)


async def test_culture_raw_callback_emits_no_membership_on_late_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_slug, second_slug = tuple(MCST_FILE_DATASETS)[:2]
    first_dataset = MCST_FILE_DATASETS[first_slug].dataset_key
    second_dataset = MCST_FILE_DATASETS[second_slug].dataset_key
    events: list[tuple[str, str]] = []

    async def _load(
        _context: object,
        *,
        provider: str,
        dataset_key: str,
        bundles: object,
        authoritative_snapshot_complete: bool,
    ) -> Any:
        del provider, bundles
        assert authoritative_snapshot_complete is True
        events.append(("load", dataset_key))
        if dataset_key == second_dataset:
            raise RuntimeError("late MCST failure")
        return object()

    async def _done(
        completed_memberships: tuple[ProviderDatasetOperationMembership, ...],
    ) -> None:
        events.append(("done", str(len(completed_memberships))))

    monkeypatch.setattr(mcst_module, "_load", _load)
    records = [
        (first_slug, _common_row("첫 dataset")),
        (second_slug, _common_row("둘째 dataset")),
    ]

    with pytest.raises(RuntimeError, match="late MCST failure"):
        await run_feature_place_mcst_culture(
            _context(records),
            memberships=(
                ProviderDatasetOperationMembership(
                    provider_dataset_id=1,
                    sync_scope="dataset_wide",
                    operation_key="feature_place_mcst_culture_job",
                ),
            ),
            on_memberships_completed=_done,
        )

    assert events == [
        ("load", first_dataset),
        ("load", second_dataset),
    ]


async def test_culture_public_wrapper_retries_canonical_members_stably(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_slug, second_slug = tuple(MCST_FILE_DATASETS)[:2]
    second_dataset = MCST_FILE_DATASETS[second_slug].dataset_key
    operation_key = "feature_place_mcst_culture_job"
    memberships = tuple(
        ProviderDatasetOperationMembership(
            provider_dataset_id=index,
            sync_scope="dataset_wide",
            operation_key=operation_key,
        )
        for index, _spec in enumerate(MCST_FILE_DATASETS.values(), start=1)
    )

    class _TrackingClient:
        def __init__(self) -> None:
            self.calls: list[tuple[str, dict[str, Any]]] = []
            self.done_memberships: set[Any] = set()
            self.finish_outcomes: list[str] = []

        async def ensure_dagster_feature_operation(self, **kwargs: Any) -> Any:
            self.calls.append(("ensure", kwargs))
            return SimpleNamespace(outcome="applied", block_reason=None)

        async def finish_dagster_feature_membership(self, **kwargs: Any) -> Any:
            self.calls.append(("finish", kwargs))
            membership = kwargs["membership"]
            outcome = "noop" if membership in self.done_memberships else "applied"
            self.done_memberships.add(membership)
            self.finish_outcomes.append(outcome)
            return SimpleNamespace(outcome=outcome, block_reason=None)

        async def append_dagster_feature_attempt_event(self, **kwargs: Any) -> Any:
            self.calls.append(("attempt", kwargs))
            return object()

    tracking_client = _TrackingClient()
    authoritative_run = SimpleNamespace(
        job_name=operation_key,
        run_id="mcst-run",
        run_config={},
        tags={
            "kor_travel_map.operation_key": operation_key,
            "kor_travel_map.trigger_kind": "schedule",
        },
        asset_selection=None,
        resolved_op_selection=None,
        status=SimpleNamespace(value="STARTED"),
    )
    record = SimpleNamespace(
        dagster_run=authoritative_run,
        create_timestamp=datetime(2026, 7, 16, 1, 0, tzinfo=UTC),
        start_time=datetime(2026, 7, 16, 1, 1, tzinfo=UTC).timestamp(),
    )
    instance = SimpleNamespace(
        run=authoritative_run,
        get_run_record_by_id=lambda _run_id: record,
    )
    guard = FeatureOperationExecutionGuard(
        client=tracking_client,  # type: ignore[arg-type]
        instance=instance,
        operation_key=operation_key,
        memberships=memberships,
        dagster_run_id="mcst-run",
        trigger_kind="schedule",
    )

    async def _load(
        _context: object,
        *,
        provider: str,
        dataset_key: str,
        bundles: object,
        authoritative_snapshot_complete: bool,
    ) -> Any:
        del provider, bundles
        assert authoritative_snapshot_complete is True
        if dataset_key == second_dataset:
            raise RuntimeError("late MCST failure")
        return object()

    monkeypatch.setattr(mcst_module, "_load", _load)
    base = _context(
        [
            (first_slug, _common_row("첫 dataset")),
            (second_slug, _common_row("둘째 dataset")),
        ]
    )
    wrapper = cast(Any, feature_place_mcst_culture.op.compute_fn).decorated_fn

    def _wrapper_context(retry_number: int) -> Any:
        return SimpleNamespace(
            resources=SimpleNamespace(
                feature_operation_guard=guard,
                kor_travel_map_client=tracking_client,
                mcst_culture_records=base.resources.mcst_culture_records,
                reverse_geocoder=base.resources.reverse_geocoder,
                fetched_at=None,
            ),
            log=base.log,
            add_output_metadata=base.add_output_metadata,
            instance=instance,
            run=authoritative_run,
            run_id=authoritative_run.run_id,
            selected_asset_keys={AssetKey("feature_place_mcst_culture")},
            asset_key=AssetKey("feature_place_mcst_culture"),
            job_name="feature_place_mcst_culture_job",
            retry_number=retry_number,
        )

    with pytest.raises(RuntimeError, match="late MCST failure"):
        await wrapper(_wrapper_context(0))
    with pytest.raises(RuntimeError, match="late MCST failure"):
        await wrapper(_wrapper_context(1))

    attempts_per_run = len(memberships)
    assert [name for name, _kwargs in tracking_client.calls] == [
        "ensure",
        *["attempt"] * attempts_per_run,
        "ensure",
        *["attempt"] * attempts_per_run,
    ]
    assert tracking_client.calls[0][1]["selected_memberships"] == memberships
    first_attempts = tracking_client.calls[1 : 1 + attempts_per_run]
    second_ensure_index = 1 + attempts_per_run
    second_attempts = tracking_client.calls[second_ensure_index + 1 :]
    assert [call[1]["membership"] for call in first_attempts] == list(memberships)
    assert [call[1]["membership"] for call in second_attempts] == list(memberships)
    assert [call[1]["attempt_number"] for call in first_attempts] == [1] * attempts_per_run
    assert [call[1]["attempt_number"] for call in second_attempts] == [2] * attempts_per_run
    assert tracking_client.finish_outcomes == []


async def test_culture_public_wrapper_finishes_every_exact_member_after_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memberships = (
        ProviderDatasetOperationMembership(
            provider_dataset_id=1,
            sync_scope="dataset_wide",
            operation_key="feature_place_mcst_culture_job",
        ),
        ProviderDatasetOperationMembership(
            provider_dataset_id=2,
            sync_scope="dataset_wide",
            operation_key="feature_place_mcst_culture_job",
        ),
    )
    guard = SimpleNamespace(memberships=memberships)
    finished: list[ProviderDatasetOperationMembership] = []

    async def _ensure(_context: object) -> object:
        return guard

    async def _finish(
        received_guard: object,
        membership: ProviderDatasetOperationMembership,
    ) -> None:
        assert received_guard is guard
        finished.append(membership)

    async def _run(
        _context: object,
        *,
        memberships: tuple[ProviderDatasetOperationMembership, ...],
        on_memberships_completed: Any,
    ) -> Any:
        assert on_memberships_completed is not None
        await on_memberships_completed(memberships)
        return SimpleNamespace(status="done")

    monkeypatch.setattr(mcst_module, "ensure_tracked_multi_member_asset", _ensure)
    monkeypatch.setattr(mcst_module, "finish_tracked_feature_membership", _finish)
    monkeypatch.setattr(mcst_module, "run_feature_place_mcst_culture", _run)

    wrapper = cast(Any, feature_place_mcst_culture.op.compute_fn).decorated_fn
    result = await wrapper(SimpleNamespace())

    assert result.status == "done"
    assert finished == list(memberships)


# -- fetcher ------------------------------------------------------------------


class _FakeFileDataClient:
    instances: list[_FakeFileDataClient] = []
    rows_per_dataset: int = 2

    def __init__(self) -> None:
        self.closed = False
        self.calls: list[str] = []
        _FakeFileDataClient.instances.append(self)

    def iter_csv(self, slug: str) -> Any:
        self.calls.append(slug)
        for index in range(type(self).rows_per_dataset):
            yield {"TITLE": f"{slug}-{index}", "RNUM": str(index + 1)}

    def close(self) -> None:
        self.closed = True


def _install_fake_mcst(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeFileDataClient.instances = []
    module = ModuleType("mcst")
    module.__dict__["FileDataClient"] = _FakeFileDataClient
    monkeypatch.setitem(sys.modules, "mcst", module)


def test_fetch_mcst_culture_records_is_keyless_and_streams_slug_tuples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mcst(monkeypatch)
    # keyless(#395) — credential 없이도 fetch (knps/krheritage items 패턴).
    settings = KorTravelMapSettings(
        data_go_kr_service_key=None,
        mcst_max_items_per_dataset=1,
    )

    records = list(fetch_mcst_culture_records(settings))

    # 등록 slug × max_items=1.
    assert len(records) == len(MCST_FILE_DATASETS)
    assert {slug for slug, _row in records} == set(MCST_FILE_DATASETS)
    [client] = _FakeFileDataClient.instances
    assert client.closed is True
    assert client.calls == list(MCST_FILE_DATASETS)


def test_fetch_mcst_culture_records_caps_rows_per_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mcst(monkeypatch)
    _FakeFileDataClient.rows_per_dataset = 5
    try:
        settings = KorTravelMapSettings(mcst_max_items_per_dataset=3)

        records = list(fetch_mcst_culture_records(settings))

        per_slug: dict[str, int] = {}
        for slug, _row in records:
            per_slug[slug] = per_slug.get(slug, 0) + 1
        assert set(per_slug) == set(MCST_FILE_DATASETS)
        assert all(count == 3 for count in per_slug.values())
    finally:
        _FakeFileDataClient.rows_per_dataset = 2


def test_fetch_mcst_culture_records_limits_worker_to_explicit_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mcst(monkeypatch)
    selected_slug = next(iter(MCST_FILE_DATASETS))

    records = list(
        fetch_mcst_culture_records(
            KorTravelMapSettings(mcst_max_items_per_dataset=1),
            slugs=(selected_slug,),
        )
    )

    assert [slug for slug, _row in records] == [selected_slug]
    [client] = _FakeFileDataClient.instances
    assert client.calls == [selected_slug]


def test_fetch_mcst_culture_records_closes_on_partial_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mcst(monkeypatch)
    settings = KorTravelMapSettings()

    gen = fetch_mcst_culture_records(settings)
    first = next(iter(gen))
    assert first is not None
    # 조기 종료 시에도 finally의 ``close()``가 실행되어 client가 닫혀야 한다.
    gen.close()

    [client] = _FakeFileDataClient.instances
    assert client.closed is True
