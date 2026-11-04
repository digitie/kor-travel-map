"""MCST Dagster asset/fetcher 단위 테스트 (T-220 재배선, #395)."""

from __future__ import annotations

import sys
from collections.abc import AsyncIterator
from types import ModuleType, SimpleNamespace
from typing import Any, cast

import pytest
from dagster import Failure, build_asset_context
from kortravelmap.client import IntegrityFindingSyncResult
from kortravelmap.core.feature_operation import ProviderDatasetOperationMembership
from kortravelmap.dto import Address, Coordinate
from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.providers.mcst import (
    MCST_FILE_DATASETS,
    McstSlugAttempt,
    McstSlugFailure,
)
from kortravelmap.settings import KorTravelMapSettings

from kortravelmap.dagster import mcst_features as mcst_module
from kortravelmap.dagster.mcst_features import (
    feature_place_mcst_culture,
    group_records_by_slug,
    run_feature_place_mcst_culture,
    split_slug_markers,
)
from kortravelmap.dagster.provider_fetchers import fetch_mcst_culture_records
from kortravelmap.dagster.upstream_requests import (
    counting_upstream_requests,
    observed_upstream_requests,
)

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

    async def load_feature_bundles(
        self,
        bundles: Any,
        *,
        curation_dataset: tuple[str, str] | None = None,
        geo: Any = None,
    ) -> FeatureLoadResult:
        materialized = list(bundles)
        self.loaded.extend(materialized)
        return FeatureLoadResult(
            bundles_total=len(materialized),
            features_inserted=len(materialized),
            curation_input_member_count=(
                len(materialized) if curation_dataset is not None else None
            ),
            curation_input_set_hash=("0" * 64 if curation_dataset is not None else None),
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


def _rows_only(records: list[Any]) -> list[Any]:
    """stream에서 ``(slug, row)`` 튜플만 남긴다.

    fetcher는 slug마다 :class:`McstSlugAttempt`를, 실패 시
    :class:`McstSlugFailure`를 함께 흘린다. 이 검사들이 보는 것은 **행**이므로
    asset과 같은 방법으로 가른 뒤 센다 — 위치나 개수로 가정하면 표식이 하나
    늘어날 때마다 다시 깨진다.
    """

    rows, _attempted, _failures = split_slug_markers(records)
    return rows


def _attempt_all() -> list[Any]:
    """전량 경로 — fetcher가 13개 slug를 모두 시도했다고 알린다."""

    return [McstSlugAttempt(slug=slug) for slug in MCST_FILE_DATASETS]


async def test_culture_asset_loads_per_slug_datasets() -> None:
    """전량 경로에서는 시도한 13개를 모두 적재한다(상류가 0건인 것 포함)."""

    records = [
        *_attempt_all(),
        ("independent_bookstores_csv", _common_row("서점 1")),
        ("world_restaurants_csv", _common_row("식당 1")),
        ("independent_bookstores_csv", _common_row("서점 2")),
    ]

    result = await run_feature_place_mcst_culture(_context(records))

    assert result.provider == "python-mcst-api"
    assert {r.dataset_key for r in result.results} == {
        spec.dataset_key for spec in MCST_FILE_DATASETS.values()
    }
    by_key = {r.dataset_key: r for r in result.results}
    assert by_key["mcst_independent_bookstores_csv"].load.bundles_total == 2
    assert by_key["mcst_world_restaurants_csv"].load.bundles_total == 1
    assert result.bundles_total == 3
    assert result.as_metadata()["datasets_loaded"] == len(MCST_FILE_DATASETS)


async def test_a_narrowed_run_only_loads_what_it_attempted() -> None:
    """**시도하지 않은 dataset은 적재하지 않는다.**

    feature-update worker는 fetcher를 slug 하나로 좁혀 부른다
    (`_mcst_resources`가 `slugs=matched_slugs`로 정확히 1개를 넘긴다). 그런데
    asset은 `MCST_FILE_DATASETS` **전체**를 돌며 빈 목록으로 적재했다 — 나머지
    12개가 **시도한 적도 없이** authoritative 적재와 sync-success를 받아
    수집하지 않은 dataset이 신선한 것으로 보였다.

    종전 검사(`test_culture_asset_loads_per_slug_datasets`)는 slug 2개만 넣고도
    `datasets_loaded == 13`을 단언해 **그 동작을 정본으로 못 박고 있었다.**
    """

    records = [
        McstSlugAttempt(slug="world_restaurants_csv"),
        ("world_restaurants_csv", _common_row("식당 1")),
    ]

    result = await run_feature_place_mcst_culture(_context(records))

    assert [r.dataset_key for r in result.results] == ["mcst_world_restaurants_csv"]
    assert result.as_metadata()["datasets_loaded"] == 1


async def test_one_failing_slug_does_not_take_down_the_others() -> None:
    """slug 하나의 수집 실패가 나머지를 죽이지 않는다.

    2026-09-18 prod: 아동서점 원천이 이동해 그 slug의 수집이 실패했는데, stream을
    리스트로 걷는 쪽이 예외를 그대로 통과시켜 **13개 dataset이 전부 0건**이 됐다.
    앞서 수집해 둔 slug의 행까지 함께 버려졌다.

    이 검사는 세 가지를 **동시에** 센다 — 셋 중 하나만 빠져도 사고가 다른 모양으로
    돌아온다.
    """

    failed_slug = "children_bookstores_csv"
    records = [
        *_attempt_all(),
        ("independent_bookstores_csv", _common_row("서점 1")),
        McstSlugFailure(slug=failed_slug, reason="McstParseError: CSV 링크 없음"),
        ("world_restaurants_csv", _common_row("식당 1")),
    ]

    with pytest.raises(Failure) as excinfo:
        await run_feature_place_mcst_culture(_context(records))

    # (1) run은 실패로 끝난다 — 일부가 죽었는데 초록이면 그것이 다음 사고다.
    assert failed_slug in excinfo.value.metadata["failed_slugs"].value
    # (2) 재시도는 끈다 — 상류 이동은 같은 run 안에서 나아지지 않는다.
    assert excinfo.value.allow_retries is False


async def test_a_failed_slug_is_not_sealed_as_an_empty_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """실패한 slug는 **적재 자체를 건너뛴다**.

    빈 목록으로 `_load`를 부르면 `authoritative_snapshot_complete=True`가 그것을
    '전량'으로 선언해 그 dataset의 기존 feature가 **전부 은퇴**한다 — 수집이
    실패했을 뿐인데 데이터를 지우는 셈이다. 그래서 건너뛴 것이 맞는지, 그리고
    나머지는 그대로 적재됐는지를 `_load` 호출 자체로 센다.
    """

    loaded: list[str] = []
    original = mcst_module._load

    async def _spy(context: Any, **kwargs: Any) -> Any:
        loaded.append(str(kwargs["dataset_key"]))
        return await original(context, **kwargs)

    monkeypatch.setattr(mcst_module, "_load", _spy)

    failed_slug = "children_bookstores_csv"
    records = [
        *_attempt_all(),
        ("independent_bookstores_csv", _common_row("서점 1")),
        McstSlugFailure(slug=failed_slug, reason="McstParseError: CSV 링크 없음"),
    ]

    with pytest.raises(Failure):
        await run_feature_place_mcst_culture(_context(records))

    failed_key = MCST_FILE_DATASETS[failed_slug].dataset_key
    assert failed_key not in loaded, loaded
    # 나머지는 전부 적재됐다 — 전멸하지 않는다는 것이 이 수정의 요지다.
    assert len(loaded) == len(MCST_FILE_DATASETS) - 1
    assert "mcst_independent_bookstores_csv" in loaded


def test_split_slug_markers_keeps_rows_attempts_and_first_reason() -> None:
    rows, attempted, failures = split_slug_markers(
        [
            McstSlugAttempt(slug="a"),
            ("a", 1),
            McstSlugFailure(slug="b", reason="첫 사유"),
            ("a", 2),
            McstSlugFailure(slug="b", reason="나중 사유"),
        ]
    )

    assert rows == [("a", 1), ("a", 2)]
    # 실패한 slug도 **시도한** slug다 — 그래야 asset이 그것을 실패로 보고한다.
    assert attempted == {"a", "b"}
    # 나중 것으로 덮으면 원인 추적이 한 단계 멀어진다.
    assert set(failures) == {"b"}
    assert failures["b"].reason == "첫 사유"
    # 표식을 통째로 들고 있어야 asset이 재시도 가능 여부까지 볼 수 있다.
    assert failures["b"].retryable is False


async def test_culture_asset_rejects_unknown_slug() -> None:
    with pytest.raises(KeyError, match="nope"):
        await run_feature_place_mcst_culture(
            _context([*_attempt_all(), ("nope", _common_row("어딘가"))])
        )


async def test_culture_asset_rejects_excluded_slug() -> None:
    """제외 dataset(예: public_libraries)은 메타표에 없어 적재 시도 시 실패."""
    with pytest.raises(KeyError, match="public_libraries"):
        await run_feature_place_mcst_culture(
            _context([*_attempt_all(), ("public_libraries", {"도서관명": "더불어 숲"})])
        )


async def test_culture_asset_skips_unidentifiable_rows_with_warning() -> None:
    records = [
        *_attempt_all(),
        ("golf_courses_status", {"이름": "라데나골프클럽", "소재지": "춘천시 1"}),
        # 이름 없는 row — 변환에서 제외(경고 로그).
        ("golf_courses_status", {"소재지": "어딘가"}),
    ]

    result = await run_feature_place_mcst_culture(_context(records))

    by_key = {r.dataset_key: r for r in result.results}
    assert by_key["mcst_golf_courses_status"].load.bundles_total == 1
    assert result.bundles_total == 1


# -- fetcher ------------------------------------------------------------------


class _FakeFileDataClient:
    instances: list[_FakeFileDataClient] = []
    rows_per_dataset: int = 2

    def __init__(self) -> None:
        self.closed = False
        self.calls: list[str] = []
        _FakeFileDataClient.instances.append(self)

    # 실물: ``mcst/file_data.py:259``의 ``async def iter_csv``
    # (``AsyncIterator[dict[str, str]]``, dataset은 위치인자).
    async def iter_csv(self, slug: str) -> AsyncIterator[dict[str, str]]:
        self.calls.append(slug)
        for index in range(type(self).rows_per_dataset):
            yield {"TITLE": f"{slug}-{index}", "RNUM": str(index + 1)}

    # 실물 ``FileDataClient``의 정리 메서드는 ``aclose``뿐이다
    # (``mcst/file_data.py:107``) — sync ``close``는 없다.
    async def aclose(self) -> None:
        self.closed = True


def _install_fake_mcst(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeFileDataClient.instances = []
    module = ModuleType("mcst")
    module.__dict__["FileDataClient"] = _FakeFileDataClient
    monkeypatch.setitem(sys.modules, "mcst", module)


async def test_fetch_mcst_culture_records_is_keyless_and_streams_slug_tuples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mcst(monkeypatch)
    # keyless(#395) — credential 없이도 fetch (knps/krheritage items 패턴).
    settings = KorTravelMapSettings(
        data_go_kr_service_key=None,
        mcst_max_items_per_dataset=1,
    )

    stream = [record async for record in fetch_mcst_culture_records(settings)]
    records = _rows_only(stream)

    # 등록 slug × max_items=1.
    assert len(records) == len(MCST_FILE_DATASETS)
    assert {slug for slug, _row in records} == set(MCST_FILE_DATASETS)
    # 표식도 slug마다 정확히 하나씩 나온다 — asset의 적재 범위가 여기서 온다.
    _rows, attempted, _failures = split_slug_markers(stream)
    assert attempted == set(MCST_FILE_DATASETS)
    [client] = _FakeFileDataClient.instances
    assert client.closed is True
    assert client.calls == list(MCST_FILE_DATASETS)


async def test_fetch_mcst_culture_records_caps_rows_per_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mcst(monkeypatch)
    _FakeFileDataClient.rows_per_dataset = 5
    try:
        settings = KorTravelMapSettings(mcst_max_items_per_dataset=3)

        records = _rows_only(
            [record async for record in fetch_mcst_culture_records(settings)]
        )

        per_slug: dict[str, int] = {}
        for slug, _row in records:
            per_slug[slug] = per_slug.get(slug, 0) + 1
        assert set(per_slug) == set(MCST_FILE_DATASETS)
        assert all(count == 3 for count in per_slug.values())
    finally:
        _FakeFileDataClient.rows_per_dataset = 2


async def test_fetch_mcst_culture_records_limits_worker_to_explicit_slug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mcst(monkeypatch)
    selected_slug = next(iter(MCST_FILE_DATASETS))

    records = [
        record
        async for record in fetch_mcst_culture_records(
            KorTravelMapSettings(mcst_max_items_per_dataset=1),
            slugs=(selected_slug,),
        )
    ]

    assert [slug for slug, _row in _rows_only(records)] == [selected_slug]
    # worker 경로는 slug 하나만 **시도한다** — asset이 그 하나만 적재하는
    # 근거가 이 집합이다.
    _rows, attempted, _failures = split_slug_markers(records)
    assert attempted == {selected_slug}
    [client] = _FakeFileDataClient.instances
    assert client.calls == [selected_slug]


async def test_fetch_mcst_culture_records_rejects_slug_absent_from_the_meta_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """메타표에 없는 slug는 **다운로드를 시작하기 전에** ``KeyError``로 끊는다.

    worker가 명시하는 slug는 ``feature_update_runner``의 membership 해석에서 오고
    (``provider_fetchers.fetch_mcst_culture_records(settings, slugs=matched_slugs)``),
    ``MCST_FILE_DATASETS``는 변환과 fetch가 공유하는 단일 메타표다. 검사가 없으면
    미등록 slug가 그대로 ``client.iter_csv(slug)``로 흘러가 dataset_key를 알 수 없는
    row가 적재 경로에 들어간다.

    등록 slug를 **함께** 넘겨도 막혀야 한다 — 한 건이라도 미지면 전체가 거부다.
    client가 아예 열리지 않는 것까지 단언해 "열고 나서 실패"와 구분한다.
    """
    _install_fake_mcst(monkeypatch)
    registered_slug = next(iter(MCST_FILE_DATASETS))

    records = fetch_mcst_culture_records(
        KorTravelMapSettings(mcst_max_items_per_dataset=1),
        slugs=(registered_slug, "krtour-unregistered-slug"),
    )

    with pytest.raises(KeyError, match="krtour-unregistered-slug"):
        await anext(records)

    assert _FakeFileDataClient.instances == []


async def test_fetch_mcst_culture_records_closes_on_partial_consumption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_mcst(monkeypatch)
    settings = KorTravelMapSettings()

    gen = fetch_mcst_culture_records(settings)
    first = await anext(gen)
    assert first is not None
    # 조기 종료 시에도 finally의 ``aclose()``가 실행되어 client가 닫혀야 한다.
    await gen.aclose()

    [client] = _FakeFileDataClient.instances
    assert client.closed is True


async def test_fetch_mcst_culture_records_counts_one_request_per_dataset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """slug 하나 = 카탈로그 스크레이핑 + CSV 다운로드 — **1건(하한)**으로 센다.

    lib 안에서 몇 번 나가는지 이 층은 볼 수 없어 분자는 하한이다. 그 하한이
    사라지면(``note_upstream_request()`` 한 줄이 빠지면) 보고는 "0번 요청했다"가
    아니라 침묵이 된다 — 계수되지 않은 경로는 ``None``이다. row 수로는 역산되지
    않으므로(빈 dataset도 요청 1건을 쓴다) 이 수는 따로 결박해야 한다.
    """
    _install_fake_mcst(monkeypatch)
    # **상한을 2로 둔다.** 1이면 row 수와 slug 수가 같아져 "slug당 1건"과 "row당
    # 1건"이 같은 수가 되고, 계수기를 row 루프로 옮기는 변이가 초록으로 지나간다
    # (적대 리뷰 실증 — 그 변이는 실제로는 보고 건수를 row 배수로 부풀린다).
    settings = KorTravelMapSettings(mcst_max_items_per_dataset=2)

    with counting_upstream_requests():
        records = _rows_only(
            [record async for record in fetch_mcst_culture_records(settings)]
        )
        observed = observed_upstream_requests()

    assert len(records) == 2 * len(MCST_FILE_DATASETS), (
        "이 검사는 row 수와 slug 수가 **달라야** 의미가 있다 — 대역이 dataset마다 "
        "2행을 내는지 먼저 확인한다"
    )
    assert observed == len(MCST_FILE_DATASETS), (
        f"dataset {len(MCST_FILE_DATASETS)}개인데 {observed}건을 셌다 — "
        "slug당 1건이 이 fetcher의 분자 하한이고, row 수(2배)가 아니다"
    )



async def test_a_stream_with_no_attempt_markers_is_not_a_quiet_success() -> None:
    """**시도 표식이 하나도 없으면 0건 적재로 초록이 된다** — 그것을 막는다.

    asset은 시도하지 않은 slug를 전부 건너뛴다. 그러므로 표식이 없는 stream은
    13개를 모두 건너뛰어 `results`도 `slug_failures`도 비고, 완료 콜백까지 불린
    뒤 초록으로 끝난다 — 이 asset이 막으려던 "조용한 0건"의 새 입구다
    (2026-09-19 적대 리뷰). fetcher는 slug마다 표식을 먼저 흘리므로, 표식이
    없다는 것은 한 slug도 시작하지 못했다는 뜻이다.
    """

    completed: list[object] = []

    async def _done(loaded: Any) -> None:
        completed.append(loaded)

    with pytest.raises(Failure, match="시도 표식이 하나도 없다"):
        await run_feature_place_mcst_culture(
            _context([]),
            on_dataset_completed=_done,
        )
    assert completed == []


async def test_a_transient_failure_keeps_retries_open() -> None:
    """일시적 네트워크 실패까지 재시도 불가로 만들지 않는다.

    `allow_retries=False`의 근거는 "같은 run 안에서 나아지지 않는다"인데, 종전에는
    **모든** 비-쿼터 예외를 같은 바구니에 넣었다. 연결 끊김 한 번이 그 달의 적재를
    통째로 버리게 된다(2026-09-19 적대 리뷰).
    """

    records = [
        *_attempt_all(),
        ("independent_bookstores_csv", _common_row("서점 1")),
        McstSlugFailure(
            slug="children_bookstores_csv",
            reason="ConnectError: connection reset",
            retryable=True,
        ),
    ]

    with pytest.raises(Failure) as excinfo:
        await run_feature_place_mcst_culture(_context(records))

    assert excinfo.value.allow_retries is True


async def test_a_mixed_failure_set_closes_retries() -> None:
    """하나라도 비재시도가 섞이면 닫는다 — 재시도해도 그 하나에서 또 죽는다."""

    records = [
        *_attempt_all(),
        McstSlugFailure(slug="children_bookstores_csv", reason="McstParseError: 링크 없음"),
        McstSlugFailure(
            slug="used_bookstores_csv", reason="ReadTimeout: ", retryable=True
        ),
    ]

    with pytest.raises(Failure) as excinfo:
        await run_feature_place_mcst_culture(_context(records))

    assert excinfo.value.allow_retries is False


async def test_dataset_completion_is_immediate_and_preserves_load_seal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    slugs = tuple(MCST_FILE_DATASETS)[:2]
    keys = tuple(MCST_FILE_DATASETS[slug].dataset_key for slug in slugs)
    events: list[tuple[str, str]] = []

    async def _load(_context: object, **kwargs: Any) -> Any:
        key = kwargs["dataset_key"]
        events.append(("load", key))
        if key == keys[1]:
            raise RuntimeError("private upstream response ?token=secret")
        return SimpleNamespace(
            dataset_key=key,
            load=FeatureLoadResult(
                curation_input_member_count=7, curation_input_set_hash="a" * 64,
            ),
        )

    async def _done(loaded: Any) -> None:
        assert loaded.load.curation_input_member_count == 7
        assert loaded.load.curation_input_set_hash == "a" * 64
        events.append(("done", loaded.dataset_key))

    monkeypatch.setattr(mcst_module, "_load", _load)
    with pytest.raises(mcst_module.McstImportFailure) as caught:
        await run_feature_place_mcst_culture(
            _context([McstSlugAttempt(slug) for slug in slugs]),
            on_dataset_completed=_done,
        )
    assert events == [("load", keys[0]), ("done", keys[0]), ("load", keys[1])]
    assert caught.value.failures[keys[1]] == {
        "code": "MCST_DATASET_LOAD_FAILED", "phase": "load",
        "reason": "RuntimeError", "retryable": False,
    }
    assert "secret" not in str(caught.value)


async def test_completed_dataset_is_never_reloaded_or_failed_on_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = tuple(MCST_FILE_DATASETS)[:2]
    first_key = MCST_FILE_DATASETS[first].dataset_key
    context = _context([
        McstSlugAttempt(first), McstSlugFailure(first, "DOWNLOAD_CHECK_FAILED"),
        McstSlugAttempt(second),
    ])
    loaded: list[str] = []
    original = mcst_module._load

    async def _load(ctx: Any, **kwargs: Any) -> Any:
        loaded.append(kwargs["dataset_key"])
        return await original(ctx, **kwargs)

    monkeypatch.setattr(mcst_module, "_load", _load)
    result = await run_feature_place_mcst_culture(
        context, completed_dataset_keys=frozenset({first_key}),
    )
    assert loaded == [MCST_FILE_DATASETS[second].dataset_key]
    assert len(result.results) == 1


@pytest.mark.parametrize("failure_phase", ["fetch", "load"])
async def test_public_wrapper_records_twelve_successes_and_only_one_failure(
    monkeypatch: pytest.MonkeyPatch, failure_phase: str,
) -> None:
    specs = tuple(MCST_FILE_DATASETS.values())
    memberships = tuple(
        ProviderDatasetOperationMembership(i + 1, "dataset_wide", "feature_place_mcst_culture_job")
        for i in range(len(specs))
    )
    by_key = dict(zip((spec.dataset_key for spec in specs), memberships, strict=True))
    done: set[Any] = set()
    attempts: list[dict[str, Any]] = []
    loads: list[str] = []
    failing = specs[-1]

    class Client:
        async def resolve_frozen_feature_operation_datasets(self, **kwargs: Any) -> Any:
            assert kwargs["memberships"] == memberships
            return by_key

        async def append_dagster_feature_attempt_event(self, **kwargs: Any) -> None:
            attempts.append(kwargs)

    class Guard:
        operation_key = "feature_place_mcst_culture_job"
        dagster_run_id = "mcst-partial"
        client = Client()

        async def ensure(self) -> Any:
            return SimpleNamespace(operation=SimpleNamespace(members=tuple(
                SimpleNamespace(membership=m, status="done" if m in done else "running")
                for m in memberships
            )))

    guard = Guard()
    guard.memberships = memberships

    async def ensure(_context: Any) -> Any:
        return guard

    async def finish(_guard: Any, member: Any, **kwargs: Any) -> None:
        assert kwargs["curation_input_member_count"] == 0
        assert kwargs["curation_input_set_hash"] == "0" * 64
        assert member not in done
        done.add(member)

    async def load(_context: Any, **kwargs: Any) -> Any:
        key = kwargs["dataset_key"]
        loads.append(key)
        if failure_phase == "load" and key == failing.dataset_key:
            raise RuntimeError("secret sql")
        return SimpleNamespace(dataset_key=key, load=FeatureLoadResult(
            curation_input_member_count=0, curation_input_set_hash="0" * 64,
        ))

    monkeypatch.setattr(mcst_module, "ensure_tracked_multi_member_asset", ensure)
    monkeypatch.setattr(mcst_module, "finish_tracked_feature_membership", finish)
    monkeypatch.setattr(mcst_module, "_load", load)
    records: list[Any] = _attempt_all()
    if failure_phase == "fetch":
        records.append(McstSlugFailure(failing.slug, "DOWNLOAD_CHECK_FAILED", retryable=True))
    base = _context(records)
    context = SimpleNamespace(
        resources=base.resources, log=base.log,
        add_output_metadata=base.add_output_metadata, retry_number=0,
    )
    wrapper = cast(Any, feature_place_mcst_culture.op.compute_fn).decorated_fn
    for retry in range(2):
        context.retry_number = retry
        with pytest.raises(mcst_module.McstImportFailure):
            await wrapper(context)
    assert len(done) == 12
    assert len(attempts) == 2
    assert [a["membership"] for a in attempts] == [memberships[-1]] * 2
    assert [a["attempt_number"] for a in attempts] == [1, 2]
    assert all(a["error"]["phase"] == failure_phase for a in attempts)
    assert all(loads.count(spec.dataset_key) == 1 for spec in specs[:-1])


async def test_narrowed_selection_never_transforms_or_loads_unselected_records(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chosen = tuple(MCST_FILE_DATASETS.values())[0]
    context = _context(_attempt_all())
    loaded: list[str] = []
    original = mcst_module._load

    async def load(ctx: Any, **kwargs: Any) -> Any:
        loaded.append(kwargs["dataset_key"])
        return await original(ctx, **kwargs)

    monkeypatch.setattr(mcst_module, "_load", load)
    result = await run_feature_place_mcst_culture(
        context, selected_dataset_keys=frozenset({chosen.dataset_key}),
    )
    assert loaded == [chosen.dataset_key]
    assert len(result.results) == 1


@pytest.mark.parametrize("sqlstate", ["40001", "40P01", "55P03", "08006", "23514"])
async def test_load_db_failure_preserves_typed_retry_policy(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str,
) -> None:
    from sqlalchemy.exc import DBAPIError

    class DatabaseFailure(Exception):
        pass

    original = DatabaseFailure("SECRET SQL")
    original.sqlstate = sqlstate
    failure = DBAPIError("SECRET SQL", {}, original)

    async def load(_ctx: Any, **_kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(mcst_module, "_load", load)
    slug = tuple(MCST_FILE_DATASETS)[0]
    with pytest.raises(mcst_module.McstImportFailure) as captured:
        await run_feature_place_mcst_culture(_context([McstSlugAttempt(slug)]))
    assert captured.value.allow_retries is (sqlstate != "23514")
    assert "SECRET" not in str(captured.value)


@pytest.mark.parametrize("mode", ["missing", "foreign", "duplicate", "finalize_failure"])
async def test_wrapper_rejects_invalid_completion_without_failing_finished_members(
    monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    specs = tuple(MCST_FILE_DATASETS.values())[:2]
    memberships = tuple(
        ProviderDatasetOperationMembership(i + 1, "dataset_wide", "feature_place_mcst_culture_job")
        for i in range(2)
    )
    mapping = dict(zip((spec.dataset_key for spec in specs), memberships, strict=True))
    finished: list[Any] = []
    attempts: list[dict[str, Any]] = []

    class Client:
        async def resolve_frozen_feature_operation_datasets(self, **_kwargs: Any) -> Any:
            return mapping

        async def append_dagster_feature_attempt_event(self, **kwargs: Any) -> None:
            attempts.append(kwargs)

    class Guard:
        client = Client()
        dagster_run_id = "invalid-completion"

        async def ensure(self) -> Any:
            return SimpleNamespace(operation=SimpleNamespace(members=()))

    guard = Guard()
    guard.memberships = memberships

    async def ensure(_context: Any) -> Any:
        return guard

    async def finish(_guard: Any, member: Any, **_kwargs: Any) -> None:
        if mode == "finalize_failure":
            raise ConnectionError("SECRET connection details")
        finished.append(member)

    async def run(_context: Any, **kwargs: Any) -> Any:
        callback = kwargs["on_dataset_completed"]
        if mode != "missing":
            loaded = SimpleNamespace(
                dataset_key="foreign" if mode == "foreign" else specs[0].dataset_key,
                load=FeatureLoadResult(
                    curation_input_member_count=0, curation_input_set_hash="0" * 64,
                ),
            )
            await callback(loaded)
            if mode == "duplicate":
                await callback(loaded)
        return SimpleNamespace()

    monkeypatch.setattr(mcst_module, "ensure_tracked_multi_member_asset", ensure)
    monkeypatch.setattr(mcst_module, "finish_tracked_feature_membership", finish)
    monkeypatch.setattr(mcst_module, "run_feature_place_mcst_culture", run)
    wrapper = cast(Any, feature_place_mcst_culture.op.compute_fn).decorated_fn
    with pytest.raises((RuntimeError, mcst_module.McstImportFailure)):
        await wrapper(SimpleNamespace(retry_number=0))
    assert finished == ([memberships[0]] if mode == "duplicate" else [])
    assert {a["membership"] for a in attempts} == set(memberships) - set(finished)
    assert "SECRET" not in str(attempts)
    if mode == "finalize_failure":
        assert attempts[0]["error"]["phase"] == "finalize"
        assert attempts[0]["error"]["retryable"] is True


@pytest.mark.parametrize("failed_fetch_after_finalize", [False, True])
async def test_finalize_failure_preserves_other_fetch_failure_and_redacts_dagster_chain(
    monkeypatch: pytest.MonkeyPatch, failed_fetch_after_finalize: bool,
) -> None:
    from dagster._utils.error import serializable_error_info_from_exc_info

    slugs = tuple(MCST_FILE_DATASETS)[:2]
    fetch_slug, finalize_slug = slugs if not failed_fetch_after_finalize else slugs[::-1]
    fetch_key = MCST_FILE_DATASETS[fetch_slug].dataset_key
    finalize_key = MCST_FILE_DATASETS[finalize_slug].dataset_key

    async def finish(*_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("SECRET_UPSTREAM_BODY_TOKEN")

    async def load(_context: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(dataset_key=kwargs["dataset_key"], load=FeatureLoadResult(
            curation_input_member_count=0, curation_input_set_hash="0" * 64,
        ))

    async def completed(loaded: Any) -> None:
        await mcst_module._finalize_mcst_dataset(
            cast(Any, object()),
            ProviderDatasetOperationMembership(1, "dataset_wide", "feature_place_mcst_culture_job"),
            loaded, completed_dataset_keys=(),
        )

    monkeypatch.setattr(mcst_module, "finish_tracked_feature_membership", finish)
    monkeypatch.setattr(mcst_module, "_load", load)
    with pytest.raises(mcst_module.McstImportFailure) as captured:
        await run_feature_place_mcst_culture(
            _context([
                *(McstSlugAttempt(slug) for slug in slugs),
                McstSlugFailure(fetch_slug, "CAPTCHA_REQUIRED", retryable=False),
            ]),
            on_dataset_completed=completed,
        )
    error = captured.value
    serialized = serializable_error_info_from_exc_info((type(error), error, error.__traceback__))
    assert "SECRET_UPSTREAM_BODY_TOKEN" not in serialized.to_string()
    assert captured.value.failures[fetch_key]["reason"] == "CAPTCHA_REQUIRED"
    assert captured.value.failures[finalize_key]["phase"] == "finalize"
    assert captured.value.failures[finalize_key]["retryable"] is True
    assert captured.value.allow_retries is False
    assert captured.value.__cause__ is None


async def test_retryable_finalize_abort_keeps_unreached_datasets_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """일시적 완료 기록 실패로 멈춘 run에서 아직 못 간 dataset도 재시도 대상이다(#1444 리뷰).

    집계 실패는 재시도를 허용하는데, 도달하지 못한 dataset을 영구 ``failed``로 기록하면
    운영 화면이 재시도될 dataset을 실패로 보여 준다.
    """
    specs = tuple(MCST_FILE_DATASETS.values())
    memberships = tuple(
        ProviderDatasetOperationMembership(i + 1, "dataset_wide", "feature_place_mcst_culture_job")
        for i in range(len(specs))
    )
    by_key = dict(zip((spec.dataset_key for spec in specs), memberships, strict=True))
    attempts: list[dict[str, Any]] = []

    class Client:
        async def resolve_frozen_feature_operation_datasets(self, **_kwargs: Any) -> Any:
            return by_key

        async def append_dagster_feature_attempt_event(self, **kwargs: Any) -> None:
            attempts.append(kwargs)

    class Guard:
        operation_key = "feature_place_mcst_culture_job"
        dagster_run_id = "mcst-finalize-abort"
        client = Client()

        async def ensure(self) -> Any:
            return SimpleNamespace(operation=SimpleNamespace(members=tuple(
                SimpleNamespace(membership=m, status="running") for m in memberships
            )))

    guard = Guard()
    guard.memberships = memberships

    async def ensure(_context: Any) -> Any:
        return guard

    async def finish(*_args: Any, **_kwargs: Any) -> None:
        raise ConnectionError("transient")

    async def load(_context: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(dataset_key=kwargs["dataset_key"], load=FeatureLoadResult(
            curation_input_member_count=0, curation_input_set_hash="0" * 64,
        ))

    monkeypatch.setattr(mcst_module, "ensure_tracked_multi_member_asset", ensure)
    monkeypatch.setattr(mcst_module, "finish_tracked_feature_membership", finish)
    monkeypatch.setattr(mcst_module, "_load", load)
    base = _context(_attempt_all())
    context = SimpleNamespace(
        resources=base.resources, log=base.log,
        add_output_metadata=base.add_output_metadata, retry_number=0,
    )
    wrapper = cast(Any, feature_place_mcst_culture.op.compute_fn).decorated_fn
    with pytest.raises(mcst_module.McstImportFailure) as captured:
        await wrapper(context)
    assert captured.value.allow_retries is True
    assert len(attempts) == len(specs)
    assert attempts[0]["error"]["phase"] == "finalize"
    assert {a["outcome"] for a in attempts} == {"retryable_failure"}
