"""합성 중첩 SHP의 public provider → Map 계약 회귀 (#1450, knps-api#17).

HTTP bytes만 대체한다. typed record와 Map 변환기는 실제 public 구현을 쓴다.
ID_CD/KOR_NM·CP949·EPSG:5179/4326은 명시한 합성 계약이며 공식 원천 검증이 아니다.
실제 원천의 필드/CRS/시설 식별·중복 정책은 Claude의 공식 fixture 검증에 남긴다.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import pytest
import shapefile
from knps import KnpsClient
from pyproj import CRS, Transformer

from kortravelmap.core.ids import make_feature_id, make_payload_hash, make_source_record_key
from kortravelmap.dto import Address, FeatureKind, SourceRole
from kortravelmap.providers.knps import knps_point_records_to_bundles

SHELTER_DATASET = "knps_shelters"
FETCHED_AT = datetime(2026, 11, 7, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
FIXTURE_BJD = "4211000000"
SHELTER_POINTS = (
    ("SHELTER-A", "합성 북쪽 대피소", 128.535422, 37.130878, "원문 보존 · 북쪽"),
    ("SHELTER-B", "합성 남쪽 대피소", 128.843683, 36.727438, "원문 보존 · 남쪽"),
)


def _shape_zip(index: int, *, crs: str, polygon: bool = False) -> bytes:
    """동일한 로컬 OBJECTID를 가진 별도 SHP에서도 전역 ID_CD를 보존한다."""
    source_id, name, lon, lat, note = SHELTER_POINTS[index]
    projected = Transformer.from_crs("EPSG:4326", crs, always_xy=True)
    x, y = projected.transform(lon, lat)
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    with shapefile.Writer(
        shp=shp,
        shx=shx,
        dbf=dbf,
        shapeType=shapefile.POLYGON if polygon else shapefile.POINT,
        encoding="cp949",
    ) as writer:
        writer.field("ID_CD", "C", size=40)
        writer.field("OBJECTID", "C", size=12)
        writer.field("KOR_NM", "C", size=100)
        writer.field("NOTE", "C", size=100)
        if polygon:
            delta = 10 if crs != "EPSG:4326" else 0.001
            writer.poly(
                [
                    [
                        (x - delta, y - delta),
                        (x - delta, y + delta),
                        (x + delta, y + delta),
                        (x + delta, y - delta),
                        (x - delta, y - delta),
                    ]
                ]
            )
            # Same facility key, different geometry: must not become another place.
            writer.record(source_id, "1", "제외할 대피소 부지 면", "POLYGON_ONLY")
        else:
            writer.point(x, y)
            writer.record(source_id, "1", name, note)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for suffix, content in (
            (".shp", shp.getvalue()),
            (".shx", shx.getvalue()),
            (".dbf", dbf.getvalue()),
            (".prj", CRS.from_user_input(crs).to_wkt().encode("utf-8")),
            (".cpg", b"CP949"),
        ):
            output.writestr("layers/SHELTER" + suffix, content)
    return archive.getvalue()


def build_shelter_archive(*, crs: str = "EPSG:5179", reverse_members: bool = False) -> bytes:
    """Parent live harness용: PT 두 행 + 같은 ID의 PG 면을 담은 합성 중첩 ZIP."""
    members = [
        ("GSTN_SHELTER_PT2.zip", _shape_zip(0, crs=crs)),
        ("GSTN_SHELTER_PT3.zip", _shape_zip(1, crs=crs)),
        ("GSTN_SHELTER_PG.ZIP", _shape_zip(0, crs=crs, polygon=True)),
    ]
    if reverse_members:
        members.reverse()
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
        for filename, payload in members:
            output.writestr("nested/" + filename, payload)
    return archive.getvalue()


async def _public_records(payload: bytes) -> tuple[Any, ...]:
    requested: list[str] = []

    async def respond(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url == httpx.URL(download_url)
        requested.append(str(request.url))
        return httpx.Response(200, content=payload, headers={"Content-Type": "application/zip"})

    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(respond)) as session,
        KnpsClient(session=session, max_rps=1000) as client,
    ):
        dataset = next(item for item in client.file_datasets() if item.key == SHELTER_DATASET)
        assert dataset.download_url
        download_url = dataset.download_url
        records = await client.files.read_place_records(SHELTER_DATASET)
    assert requested == [download_url]
    return records


async def fixture_address(_coord: object) -> Address:
    """명시적인 합성 reverse 결과; 실제 행정경계 검증 결과로 주장하지 않는다."""
    return Address(bjd_code=FIXTURE_BJD)


@pytest.mark.parametrize("crs", ["EPSG:5179", "EPSG:4326"])
@pytest.mark.asyncio
async def test_public_nested_shelter_records_preserve_map_contract(crs: str) -> None:
    records = await _public_records(build_shelter_archive(crs=crs))
    assert len(records) == 2  # PG polygon must not be counted as a third shelter.
    by_id = {record.source_id: record for record in records}
    assert len(by_id) == 2
    assert set(by_id) == {point[0] for point in SHELTER_POINTS}
    bundles = await knps_point_records_to_bundles(
        records,
        dataset_key=SHELTER_DATASET,
        fetched_at=FETCHED_AT,
        reverse_geocoder=fixture_address,
    )
    assert len(bundles) == 2
    bundles_by_id = {bundle.source_record.source_entity_id: bundle for bundle in bundles}
    for source_id, name, lon, lat, note in SHELTER_POINTS:
        record, bundle = by_id[source_id], bundles_by_id[source_id]
        assert record.dataset_key == SHELTER_DATASET
        assert record.name == name
        assert record.longitude == pytest.approx(lon, abs=1e-7)
        assert record.latitude == pytest.approx(lat, abs=1e-7)
        assert record.raw["ID_CD"] == source_id
        assert record.raw["OBJECTID"] == "1"
        assert record.raw["KOR_NM"] == name
        assert record.raw["NOTE"] == note
        feature, source, link = bundle.feature, bundle.source_record, bundle.source_link
        assert feature.provider_natural_key == source_id
        assert feature.kind is FeatureKind.PLACE
        assert feature.name == name
        assert feature.category == "03080100"
        assert feature.marker_icon == "shelter"
        assert feature.marker_color == "P-06"
        assert feature.detail.place_kind == "mountain_shelter"
        assert feature.detail.payload == {"knps_dataset": SHELTER_DATASET}
        assert feature.coord is not None
        assert float(feature.coord.lon) == pytest.approx(lon, abs=1e-7)
        assert float(feature.coord.lat) == pytest.approx(lat, abs=1e-7)
        assert feature.address.bjd_code == FIXTURE_BJD
        assert feature.feature_id == make_feature_id(
            bjd_code=FIXTURE_BJD,
            kind="place",
            category="03080100",
            source_type="python-knps-api:" + SHELTER_DATASET,
            source_natural_key=source_id,
        )
        assert source.provider == "python-knps-api"
        assert source.dataset_key == SHELTER_DATASET
        assert source.source_entity_type == "knps_facility"
        assert source.source_entity_id == source_id
        assert source.raw_data == record.raw
        assert source.raw_payload_hash == make_payload_hash(record.raw)
        assert source.source_record_key == make_source_record_key(
            provider="python-knps-api",
            dataset_key=SHELTER_DATASET,
            source_entity_type="knps_facility",
            source_entity_id=source_id,
            raw_payload_hash=source.raw_payload_hash,
        )
        assert source.fetched_at == FETCHED_AT
        assert link.source_role is SourceRole.PRIMARY
        assert link.match_method == "natural_key"
        assert link.confidence == 100
        assert link.feature_id == feature.feature_id
        assert link.source_record_key == source.source_record_key


@pytest.mark.asyncio
async def test_public_nested_shelter_replay_keeps_identity_and_raw() -> None:
    payload = build_shelter_archive()
    first = await _public_records(payload)
    again = await _public_records(payload)
    reordered = await _public_records(build_shelter_archive(reverse_members=True))

    async def project(records: tuple[Any, ...]) -> dict[str, Any]:
        bundles = await knps_point_records_to_bundles(
            records,
            dataset_key=SHELTER_DATASET,
            fetched_at=FETCHED_AT,
            reverse_geocoder=fixture_address,
        )
        return {
            bundle.source_record.source_entity_id: bundle.model_dump(mode="json")
            for bundle in bundles
        }

    assert len(first) == len(again) == len(reordered) == 2
    assert await project(first) == await project(again) == await project(reordered)
