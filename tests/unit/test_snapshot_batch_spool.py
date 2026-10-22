"""스트리밍 snapshot 적재는 stream을 다 받은 **뒤에** 쓰기 transaction을 연다(ADR-113).

stream(upstream fetch·역지오코딩)을 transaction 안에서 당기면 첫 batch가 잡은 전역
``feature-curation-write`` fence를 나머지 fetch 내내 쥔다(2026-10-22 prod 2.5시간+). 이 파일은
사건 순서로 그 경계를 결박한다 — stream의 모든 yield와 끝이 session 열기보다 앞이고, 쓰기는 같은
batch를 같은 순서로 받으며, seal은 같은 transaction 끝에 읽힌다. 실제 fence 경합은 통합 검사
``tests/integration/test_snapshot_batch_load_fence_hold.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from types import TracebackType
from typing import Any

import pytest

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.client._bundle_spool import BundleSpool
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra.feature_repo import FeatureLoadResult


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

    monkeypatch.setattr("kortravelmap.client.load_bundles", _fake_load_bundles)
    monkeypatch.setattr("kortravelmap.client.capture_provider_curation_input", _fake_capture)


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
    """빈 snapshot도 종전처럼 seal을 읽는다(쓰기 없이 transaction 하나)."""
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

    monkeypatch.setattr("kortravelmap.client.load_bundles", _fake_load_bundles)

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
