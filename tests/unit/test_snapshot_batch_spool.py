"""스트리밍 snapshot 적재는 stream을 다 받은 **뒤에** 쓰기 transaction을 연다(ADR-113).

stream(upstream fetch·역지오코딩)을 transaction 안에서 당기면 첫 batch가 잡은 전역
``feature-curation-write`` fence를 나머지 fetch 내내 쥔다(2026-10-22 prod 2.5시간+). 이 파일은
사건 순서로 그 경계를 결박한다 — stream의 모든 yield와 끝이 session 열기보다 앞이고, 쓰기는 같은
batch를 같은 순서로 받으며, seal은 같은 transaction 끝에 읽힌다. 실제 fence 경합은 통합 검사
``tests/integration/test_snapshot_batch_load_fence_hold.py``.
"""

from __future__ import annotations

import gc
import weakref
from collections.abc import AsyncIterator, Sequence
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace, TracebackType
from typing import Any

import pytest

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client._bundle_spool import BundleSpool
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra.feature_repo import FeatureLoadResult
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles


class _Bundle:
    """pickle 가능한 최소 대역 — spool은 bundle 내용을 보지 않는다."""

    def __init__(self, key: str) -> None:
        self.key = key


class _Recorder:
    def __init__(self) -> None:
        self.events: list[str] = []


def _client(recorder: _Recorder) -> AsyncKorTravelMapClient:
    class _Tx:
        async def __aenter__(self) -> None:
            recorder.events.append("begin")

        async def __aexit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> None:
            recorder.events.append("commit" if exc is None else "rollback")

    class _Session:
        def __init__(self) -> None:
            self.info: dict[str, Any] = {}

        async def __aenter__(self) -> _Session:
            recorder.events.append("session")
            return self

        async def __aexit__(self, *_exc: object) -> None:
            return None

        def begin(self) -> _Tx:
            return _Tx()

    instance = AsyncKorTravelMapClient(object())  # type: ignore[arg-type]
    instance._session_factory = _Session  # type: ignore[assignment]  # noqa: SLF001
    return instance


def _patch_writes(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder) -> None:
    async def _fake_load_bundles(
        session: Any, bundles: Sequence[_Bundle], *, geo: object = None
    ) -> FeatureLoadResult:
        recorder.events.append("write:" + ",".join(bundle.key for bundle in bundles))
        return FeatureLoadResult(bundles_total=len(bundles))

    async def _fake_capture(session: Any, **kwargs: Any) -> FeatureLoadResult:
        recorder.events.append(f"seal:{kwargs['provider']}/{kwargs['dataset_key']}")
        return FeatureLoadResult(curation_input_member_count=7, curation_input_set_hash="h")

    async def _fake_fence(session: Any) -> None:
        recorder.events.append("fence")

    monkeypatch.setattr("kortravelmap.client.load_bundles", _fake_load_bundles)
    monkeypatch.setattr("kortravelmap.client.capture_provider_curation_input", _fake_capture)
    monkeypatch.setattr("kortravelmap.client.lock_feature_curation_write", _fake_fence)


@pytest.mark.asyncio
async def test_stream_is_drained_before_the_write_transaction_opens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = _Recorder()
    _patch_writes(monkeypatch, recorder)

    async def _stream() -> AsyncIterator[list[_Bundle]]:
        recorder.events.append("fetch:1")
        yield [_Bundle("a"), _Bundle("b")]
        recorder.events.append("fetch:2")
        yield []
        recorder.events.append("fetch:3")
        yield [_Bundle("c")]
        recorder.events.append("fetch:end")

    result = await _client(recorder).load_feature_bundle_batches(
        _stream(),  # type: ignore[arg-type]
        curation_dataset=("p", "d"),
    )

    assert recorder.events == [
        "fetch:1",
        "fetch:2",
        "fetch:3",
        "fetch:end",
        "session",
        "begin",
        "fence",
        "write:a,b",
        "write:c",
        "seal:p/d",
        "commit",
    ]
    assert result.bundles_total == 3
    assert result.curation_input_member_count == 7
    assert result.curation_input_set_hash == "h"


@pytest.mark.asyncio
async def test_failing_stream_never_opens_a_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """받기 실패(fetch·검증 Failure·소실 하한)는 DB에 아무것도 열지 않는다."""
    recorder = _Recorder()
    _patch_writes(monkeypatch, recorder)

    async def _stream() -> AsyncIterator[list[_Bundle]]:
        yield [_Bundle("a")]
        raise RuntimeError("second page failed")

    with pytest.raises(RuntimeError, match="second page failed"):
        await _client(recorder).load_feature_bundle_batches(_stream())  # type: ignore[arg-type]
    assert recorder.events == []


@pytest.mark.asyncio
async def test_empty_stream_still_seals_in_one_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """빈 snapshot도 종전처럼 seal을 읽는다(쓰기·fence 선점 없이 transaction 하나)."""
    recorder = _Recorder()
    _patch_writes(monkeypatch, recorder)

    async def _stream() -> AsyncIterator[list[_Bundle]]:
        if False:  # pragma: no cover
            yield []

    await _client(recorder).load_feature_bundle_batches(
        _stream(),  # type: ignore[arg-type]
        curation_dataset=("p", "d"),
    )
    assert recorder.events == ["session", "begin", "seal:p/d", "commit"]


@pytest.mark.asyncio
async def test_every_batch_sees_the_whole_runs_geo_observations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """geo 관측 토큰은 받기가 끝난 뒤의 집합으로 본다(ADR-113 §2, ADR-109).

    stream 끝에서 데이터셋 전환(다른 토큰)을 관측하면 **앞 batch도** 새 토큰으로 스탬프하지 않는다 —
    종전에는 앞 batch가 그때까지 본 토큰으로 스탬프됐다.
    """
    recorder = _Recorder()
    old, new = "dd1-" + "a" * 32, "dd1-" + "b" * 32
    observed: set[str] = set()
    geo = GeoLoadContext(
        geo_applied=GeoApplied(reverse=True, geocode=False),
        current_dataset=DatasetRef(version_token="dv1-" + "c" * 32, data_token=old),
        observed_data_tokens=observed,
    )
    tokens_at_write: list[str | None] = []

    async def _fake_load_bundles(
        session: Any, bundles: Sequence[_Bundle], *, geo: GeoLoadContext | None = None
    ) -> FeatureLoadResult:
        assert geo is not None
        tokens_at_write.append(geo.effective_token())
        return FeatureLoadResult(bundles_total=len(bundles))

    async def _fake_fence(session: Any) -> None:
        return None

    monkeypatch.setattr("kortravelmap.client.load_bundles", _fake_load_bundles)
    monkeypatch.setattr("kortravelmap.client.lock_feature_curation_write", _fake_fence)

    async def _stream() -> AsyncIterator[list[_Bundle]]:
        observed.add(old)
        yield [_Bundle("a")]
        observed.add(new)  # 뒤 batch의 역지오코딩이 전환 뒤 응답을 받았다
        yield [_Bundle("b")]

    await _client(recorder).load_feature_bundle_batches(
        _stream(),  # type: ignore[arg-type]
        geo=geo,
    )
    assert tokens_at_write == [None, None]


def test_spool_replays_batches_in_order_and_skips_empty() -> None:
    with BundleSpool() as spool:
        spool.append([_Bundle("a"), _Bundle("b")])  # type: ignore[list-item]
        spool.append([])
        spool.append([_Bundle("c")])  # type: ignore[list-item]
        assert (spool.batch_count, spool.bundle_count) == (2, 3)
        assert spool.byte_count > 0
        replayed = [[bundle.key for bundle in batch] for batch in spool.batches()]  # type: ignore[attr-defined]
        assert replayed == [["a", "b"], ["c"]]
        # 다시 읽어도 같다(처음으로 되감는다).
        assert [len(batch) for batch in spool.batches()] == [2, 1]


@pytest.mark.asyncio
async def test_received_batches_are_not_kept_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """받은 batch는 spool로 내려가고 메모리에 남지 않는다 — snapshot 전체를 쥐지 않는다(ADR-113 §1).

    spool 대신 목록에 모아 두는 변경(``[b async for b in batches]``)을 잡는다.
    """
    recorder = _Recorder()
    _patch_writes(monkeypatch, recorder)

    refs: list[weakref.ref[_Bundle]] = []

    async def _stream() -> AsyncIterator[list[_Bundle]]:
        for key in ("a", "b", "c", "d"):
            batch = [_Bundle(key)]
            refs.append(weakref.ref(batch[0]))
            yield batch
            del batch
            # 소비자의 루프 변수는 방금 받은 batch를 아직 가리킨다 — 그 **앞** batch부터 본다.
            if len(refs) >= 2:
                gc.collect()
                assert refs[-2]() is None, f"batch {len(refs) - 1}이 받은 뒤에도 메모리에 남아 있다"

    await _client(recorder).load_feature_bundle_batches(_stream())  # type: ignore[arg-type]
    assert [event for event in recorder.events if event.startswith("write:")] == [
        "write:a",
        "write:b",
        "write:c",
        "write:d",
    ]


@pytest.mark.asyncio
async def test_real_feature_bundles_round_trip_through_the_spool() -> None:
    """실제 provider 변환 결과가 spool을 거쳐 값·설정 필드까지 그대로 돌아온다."""
    bundles = await cultural_festivals_to_bundles(
        [
            SimpleNamespace(
                fstvl_nm="스풀 왕복 축제",
                opar="여의도공원",
                fstvl_start_date=date(2026, 4, 5),
                fstvl_end_date=date(2026, 4, 12),
                fstvl_co="상세",
                mnnst_nm="영등포구청",
                auspc_instt_nm=None,
                suprt_instt_nm=None,
                phone_number="02-2670-3114",
                homepage_url=None,
                relate_info=None,
                rdnmadr="서울특별시 영등포구 여의공원로 120",
                lnmadr="서울특별시 영등포구 여의도동 8",
                latitude=37.5263,
                longitude=126.9239,
                reference_date=date(2026, 3, 1),
                instt_code=None,
                instt_nm="서울특별시 영등포구",
            )
        ],  # type: ignore[list-item]
        fetched_at=datetime(2026, 10, 22, 12, 0, tzinfo=timezone(timedelta(hours=9))),
    )
    assert bundles
    with BundleSpool() as spool:
        spool.append(bundles)
        (replayed,) = list(spool.batches())
    assert list(replayed) == bundles
    for before, after in zip(bundles, replayed, strict=True):
        assert after.model_fields_set == before.model_fields_set
        assert after.feature.model_fields_set == before.feature.model_fields_set
        assert after.model_dump(mode="json") == before.model_dump(mode="json")

