"""**데이터셋이 통째로 사라지는 실행은 성공으로 끝나면 안 된다.**

경위. `strict_address`가 prod에서 `drop`이다. 그 모드는 error가 난 row만 빼고 나머지를
적재하는데, "나머지"가 0건이어도 아무도 세지 않았다. 2026-09-19 실측:
`krforest_landslide_forecast_issues`가 상류 10,467건을 받아 **전부** `missing_address`로
버렸고 notice feature는 0건이 됐는데 job은 **SUCCESS**로 끝났다. 위반 10,467건이
`ops.data_integrity_violations`에 `open`으로 남아 있었지만 아무도 읽지 않았다.

이 검사가 보는 것은 **효과**다 — 상수를 어떻게 적었는가가 아니라, 반 넘게 버리는 입력을
줬을 때 적재가 **실제로 일어나지 않고** 실행이 죽는가다. 그래서 진짜 적재 함수를 부르고
loader가 호출됐는지를 센다. 비율 상수를 0.99로 올려도, drop 분기를 지워도, 하한을
`load_all` 뒤로 옮겨도 이 검사는 빨개진다.

**두 경로를 모두 센다.** 이 모듈에는 적재 경로가 둘 있고(materialize 경로와 chunked
stream 경로), 이 저장소에서 반복된 사고가 "선언을 바꿨는데 그 선언을 얼려 둔 자리를
같이 못 봤다"이다. 한쪽만 막으면 다른 쪽으로 같은 소실이 지나간다.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import AsyncIterator, Sequence
from typing import Any

import pytest
from dagster import Failure
from kortravelmap.dagster import etl

from kortravelmap.dto import Address, Feature, FeatureBundle, FeatureKind
from kortravelmap.dto.source import SourceLink, SourceRecord, SourceRole

pytestmark = pytest.mark.unit

_FETCHED_AT = dt.datetime(2026, 9, 19, tzinfo=dt.UTC)
_PROVIDER = "testprov"
_DATASET = "testprov_things"


def _bundle(index: int, *, locatable: bool) -> FeatureBundle:
    """`locatable=False`면 좌표도 provider 주소도 없어 `missing_address`가 난다."""

    feature_id = f"f_test_{index:06d}"
    source_record_key = f"sr_test_{index:06d}"
    feature = Feature(
        feature_id=feature_id,
        provider_natural_key=f"nk-{index}",
        kind=FeatureKind.PLACE,
        name=f"이름 {index}",
        coord=None,
        address=Address(admin="서울특별시 종로구") if locatable else Address(),
        category="02020101",
        marker_icon="restaurant",
        marker_color="P-03",
    )
    return FeatureBundle(
        feature=feature,
        source_record=SourceRecord(
            source_record_key=source_record_key,
            provider=_PROVIDER,
            dataset_key=_DATASET,
            source_entity_type="thing",
            source_entity_id=f"nk-{index}",
            raw_data={"i": index},
            raw_payload_hash=f"h{index}",
            fetched_at=_FETCHED_AT,
        ),
        source_link=SourceLink(
            feature_id=feature_id,
            source_record_key=source_record_key,
            source_role=SourceRole.PRIMARY,
            match_method="natural_key",
            confidence=100,
        ),
    )


def _bundles(*, total: int, locatable: int) -> list[FeatureBundle]:
    return [_bundle(i, locatable=i < locatable) for i in range(total)]


@dataclasses.dataclass
class _FindingSync:
    observed_count: int = 0
    unique_count: int = 0
    upserted_count: int = 0
    unrecorded_count: int = 0


class _SpyClient:
    """적재가 **실제로 일어났는지**만 답하는 대역."""

    def __init__(self) -> None:
        self.load_calls = 0
        self.recorded_findings = 0

    async def record_address_validation_findings(
        self, findings: Any, **_: Any
    ) -> _FindingSync:
        items = tuple(findings)
        self.recorded_findings += len(items)
        return _FindingSync(
            observed_count=len(items),
            unique_count=len(items),
            upserted_count=len(items),
        )


class _Context:
    """`_add_output_metadata`와 `_dagster_run_id`만 쓰는 최소 대역."""

    def __init__(self) -> None:
        self.metadata: dict[str, Any] = {}
        self.run_id = "run-test"

    def add_output_metadata(self, metadata: dict[str, Any]) -> None:
        self.metadata.update(metadata)


async def _run_materialized(
    bundles: Sequence[FeatureBundle], client: _SpyClient
) -> Any:
    async def _load_all(kept: Sequence[FeatureBundle]) -> Any:
        client.load_calls += 1
        return _load_result(len(kept))

    return await etl.load_feature_bundles_for_dagster(
        context=_Context(),  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        bundles=list(bundles),
        provider=_PROVIDER,
        dataset_key=_DATASET,
        strict_address="drop",
        load_all=_load_all,
    )


def _load_result(count: int) -> Any:
    from kortravelmap.infra.feature_repo import FeatureLoadResult

    return FeatureLoadResult(
        bundles_total=count,
        features_inserted=count,
        features_updated=0,
        source_records_inserted=count,
        source_links_inserted=count,
        source_links_updated=0,
    )


async def _run_chunked(
    bundles: Sequence[FeatureBundle], client: _SpyClient
) -> Any:
    async def _batches() -> AsyncIterator[Sequence[FeatureBundle]]:
        for start in range(0, len(bundles), 3):
            yield list(bundles[start : start + 3])

    async def _load_all(stream: Any) -> Any:
        total = 0
        async for batch in stream:
            total += len(batch)
        # stream이 끝까지 돌아야 commit이다. 하한이 stream 안에서 터지면
        # 여기 도달하지 못한다.
        client.load_calls += 1
        return _load_result(total)

    return await etl.load_feature_bundle_batches_for_dagster(
        context=_Context(),  # type: ignore[arg-type]
        client=client,  # type: ignore[arg-type]
        batches=_batches(),
        provider=_PROVIDER,
        dataset_key=_DATASET,
        strict_address="drop",
        load_all=_load_all,
    )


@pytest.mark.parametrize("runner", [_run_materialized, _run_chunked])
async def test_a_vanished_dataset_stops_the_run_before_loading(runner: Any) -> None:
    """상류가 준 것을 전부 버리면 **적재하지 않고** 죽는다(landslide 재현)."""

    client = _SpyClient()
    with pytest.raises(Failure) as raised:
        await runner(_bundles(total=12, locatable=0), client)

    assert client.load_calls == 0, (
        "전량을 버린 실행이 loader까지 갔다 — 하한이 적재 뒤에 있다."
    )
    assert "소실" in str(raised.value.description), raised.value.description


@pytest.mark.parametrize("runner", [_run_materialized, _run_chunked])
async def test_losing_more_than_half_stops_the_run(runner: Any) -> None:
    """전량이 아니어도 절반을 넘기면 멈춘다 — 0건만 잡으면 99% 소실이 지나간다."""

    client = _SpyClient()
    with pytest.raises(Failure):
        await runner(_bundles(total=12, locatable=4), client)
    assert client.load_calls == 0


@pytest.mark.parametrize("runner", [_run_materialized, _run_chunked])
async def test_ordinary_partial_drops_still_load(runner: Any) -> None:
    """**늘 죽는 하한은 하한이 아니다.** 소수 탈락은 지금처럼 적재된다."""

    client = _SpyClient()
    result = await runner(_bundles(total=12, locatable=11), client)
    assert client.load_calls == 1, "정상 부분 탈락에서 적재가 막혔다."
    assert result.load.bundles_total == 11


@pytest.mark.parametrize("runner", [_run_materialized, _run_chunked])
async def test_an_empty_upstream_is_not_a_loss(runner: Any) -> None:
    """상류가 0건이면 버린 것도 0건이다 — 0/0을 소실로 부르면 안 된다."""

    client = _SpyClient()
    result = await runner([], client)
    assert client.load_calls == 1
    assert result.load.bundles_total == 0


@pytest.mark.parametrize("runner", [_run_materialized, _run_chunked])
async def test_the_loss_failure_still_records_its_evidence(runner: Any) -> None:
    """죽기 **전에** finding을 남긴다 — 이유 없는 빨간 run을 만들지 않는다."""

    client = _SpyClient()
    with pytest.raises(Failure):
        await runner(_bundles(total=12, locatable=0), client)
    assert client.recorded_findings >= 12, (
        "소실로 죽었는데 증거가 기록되지 않았다 — 무엇이 왜 사라졌는지 알 수 없다."
    )


def test_the_floor_sits_far_above_the_measured_drop_rate() -> None:
    """하한이 정상 탈락률에 **닿아 있지 않은지** 센다.

    2026-09-19 실측: landslide를 뺀 모든 dataset의 error-severity 탈락률은 0%,
    landslide도 주소 단서를 살리면 1.5%(156/10,562)다. 하한이 그 근처로 내려오면
    정상 실행이 죽기 시작한다 — 그때는 값을 바꾸기 전에 측정을 다시 해야 한다.
    """

    measured_worst = 156 / 10_562
    assert measured_worst * 10 < etl._DATASET_LOSS_DROP_RATIO, (
        f"하한 {etl._DATASET_LOSS_DROP_RATIO}가 실측 최악 탈락률 "
        f"{measured_worst:.4f}의 10배 아래로 내려왔다 — 정상 실행을 죽일 수 있다."
    )
    assert etl._DATASET_LOSS_DROP_RATIO < 1.0, (
        "하한이 1.0이면 **전량 소실만** 잡는다 — 99% 소실이 지나간다."
    )
