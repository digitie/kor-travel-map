"""선택 provider extra의 고정 public DTO와 실제 Map fetcher/converter 복원 계약.

기본 CI는 SDK를 설치하지 않으므로 이 모듈은 명시 skip이다. SDK pin을 설치한 별도 수용에서
동일 시험을 반드시 실행한다. 외부 HTTP는 호출하지 않고 기존 public service fixture 경계를 쓴다.
"""

from types import SimpleNamespace

import pytest

from kortravelmap.dto import Address
from kortravelmap.providers.krheritage import (
    HERITAGE_NAME_NORMALIZER_REVISION,
    heritage_items_to_bundles,
)
from kortravelmap.providers.krheritage_native import (
    HeritageGeoEvidence,
    assess_heritage_name_refresh,
    rebuild_heritage_projection,
)
from tests.unit.test_providers_krheritage import _FETCHED

sdk_models = pytest.importorskip(
    "krheritage.models", reason="optional pinned heritage SDK required"
)

_RAW = {
    "key": {"ccbaKdcd": "11", "ccbaAsno": "990001", "ccbaCtcd": "11"},
    "ccbaMnm1": "기준 유산",
    "ccmaName": "문화유산",
    "ccbaAdmin": "관리기관",
    "longitude": 126.9239,
    "latitude": 37.5263,
    "ccbaLcad": "서울특별시 영등포구 여의도동 8",
}
_ADDRESS = Address(legal="서울특별시 영등포구 여의도동 8", bjd_code="1156011000")
_GEO = HeritageGeoEvidence("resolved", "geo-v1", _ADDRESS, "a" * 64)


async def _convert(raw):
    async def reverse(_):
        return _ADDRESS

    model = sdk_models.HeritageDetail.model_validate(raw)
    return (
        await heritage_items_to_bundles([model], fetched_at=_FETCHED, reverse_geocoder=reverse)
    )[0]


async def test_public_sdk_projection_roundtrip_and_real_normalized_name_diagnostic():
    before = await _convert(_RAW)
    after = await _convert(_RAW | {"ccbaMnm1": "새 유산"})
    rebuilt = await rebuild_heritage_projection(
        before.source_record,
        validate=sdk_models.HeritageDetail.model_validate,
        geo=_GEO,
    )
    assert rebuilt.source_record.raw_data == before.source_record.raw_data
    assert rebuilt.source_record == before.source_record
    result = await assess_heritage_name_refresh(
        before.source_record,
        after,
        previous_normalizer_revision=HERITAGE_NAME_NORMALIZER_REVISION,
        previous_geo=_GEO,
        current_geo=_GEO,
        validate=sdk_models.HeritageDetail.model_validate,
    )
    assert result.eligible
    assert result.reason == "name_only"
    assert not result.collector_ready


async def test_actual_map_fetcher_public_sdk_records_then_converter(monkeypatch):
    import krheritage
    from kortravelmap.dagster.provider_fetchers import fetch_krheritage_items

    from kortravelmap.settings import KorTravelMapSettings

    calls = []
    model = sdk_models.HeritageDetail.model_validate(_RAW)

    class Search:
        async def list(self, *, page_size, page, ccba_kdcd):
            calls.append(("list", page_size, page, ccba_kdcd))
            return SimpleNamespace(items=[model], total=1)

        async def details(self, kdcd, asno, ctcd):
            calls.append(("details", kdcd, asno, ctcd))
            return model

    class Client:
        def __init__(self):
            self.search = Search()

        async def aclose(self):
            calls.append(("close",))

    monkeypatch.setattr(krheritage, "HeritageClient", Client)
    settings = KorTravelMapSettings(krheritage_kind_codes="11", krheritage_max_items_per_run=10)
    items = [record async for record in fetch_krheritage_items(settings)]
    assert items == [model]
    assert calls == [("list", 100, 1, "11"), ("details", "11", "990001", "11"), ("close",)]
    bundles = await heritage_items_to_bundles(items, fetched_at=_FETCHED)
    assert bundles[0].source_record.source_entity_id == model.key.natural_key
    assert (
        bundles[0].provider_field_presence.normalizer_revision == HERITAGE_NAME_NORMALIZER_REVISION
    )
