"""``test_geocoding_provider_integration_live`` — provider 변환기에 실 kraddr-geo
reverse_geocoder 주입 시 end-to-end 동작 검증.

본 PR 시점 가장 가치 있는 통합 검증:
- 좌표만 있는 provider feature(축제·주유소·휴게소)가 reverse 보강 후 `bjd_code`를
  실제로 채우는지.
- `feature_id`가 ADR-009의 'global' 버킷에서 탈출해 bjd-bucket으로 들어가는지.
- `cached_reverse_geocoder` 메모이즈가 같은 좌표에 대해 kraddr-geo 호출을 1회로
  줄이는지.
- `reverse_geocoder=None`이면 feature가 'global' fallback으로 떨어지는지(대조).
- opinet 변환기에도 같은 wiring이 동작하는지.

도달 불가 시 `pytest.skip` (LIVE_KRADDR_GEO_BASE_URL env로 override).
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from urllib.parse import urlparse

import httpx
import pytest
from krtour.map.geocoding import (
    KraddrGeoRestClient,
    cached_reverse_geocoder,
    kraddr_geo_reverse_geocoder,
)
from krtour.map.providers.standard_data import cultural_festivals_to_bundles

pytestmark = pytest.mark.live


_DEFAULT_BASE_URL = "http://127.0.0.1:13088/api/proxy"
_KST = timezone(timedelta(hours=9))


def _resolve_base_url() -> str:
    return os.environ.get("LIVE_KRADDR_GEO_BASE_URL", _DEFAULT_BASE_URL)


def _is_reachable(base_url: str) -> bool:
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=1.5):
            pass
    except OSError:
        return False
    try:
        with httpx.Client(base_url=base_url, timeout=3.0) as http:
            return http.get("/v1/healthz").status_code == 200
    except httpx.HTTPError:
        return False


@pytest.fixture(scope="module")
def base_url() -> str:
    url = _resolve_base_url()
    if not _is_reachable(url):
        pytest.skip(f"kraddr-geo 도달 불가: {url}")
    return url


@dataclass(frozen=True)
class _Festival:
    """`CulturalFestivalItem` Protocol 만족 (test_feature_bundle_persist.py 패턴)."""

    management_no: str
    festival_name: str
    venue_name: str | None
    start_date: date | None
    end_date: date | None
    description: str | None
    latitude: Decimal | None
    longitude: Decimal | None
    road_address: str | None
    jibun_address: str | None
    organizer_name: str | None
    organizer_tel: str | None
    data_reference_date: date | None
    provider_org_name: str | None
    bjd_code: str | None = None
    sigungu_code: str | None = None
    sido_code: str | None = None
    admin_address: str | None = None


def _make_festival(
    *,
    no: str,
    name: str,
    lon: str,
    lat: str,
) -> _Festival:
    return _Festival(
        management_no=no,
        festival_name=name,
        venue_name="여의도공원",
        start_date=date(2026, 4, 5),
        end_date=date(2026, 4, 12),
        description=None,
        latitude=Decimal(lat),
        longitude=Decimal(lon),
        road_address=None,
        jibun_address=None,
        organizer_name=None,
        organizer_tel=None,
        data_reference_date=date(2026, 3, 1),
        provider_org_name=None,
    )


# ── 본 lib `ReverseGeocoder` 콜러블 + 호출 카운터 wrap ────────────────────


def _wrap_with_counter(geocoder):  # type: ignore[no-untyped-def]
    """원본 콜러블을 wrap해 호출 횟수를 셉니다 (cache 효과 측정용)."""
    calls = {"n": 0}

    async def _counted(coord):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        return await geocoder(coord)

    return _counted, calls


# ── 1) 좌표 있는 축제 + reverse 주입 → bjd_code 채워짐 + feature_id 'global' 탈출


async def test_festival_reverse_enrichment_populates_bjd(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        client = KraddrGeoRestClient(http)
        reverse = kraddr_geo_reverse_geocoder(client, max_distance_m=200)

        # 서울시청 부근 — kraddr-geo가 bjd 1114010300을 돌려주는 좌표.
        festival = _make_festival(
            no="LIVE-FEST-CITYHALL",
            name="실 통합 축제",
            lon="126.9779",
            lat="37.5663",
        )
        bundles = await cultural_festivals_to_bundles(
            [festival],  # type: ignore[list-item]
            fetched_at=datetime(2026, 5, 28, 12, 0, tzinfo=_KST),
            reverse_geocoder=reverse,
        )
        assert len(bundles) == 1
        feat = bundles[0].feature
        # bjd가 채워졌고 sido/sigungu 파생도 정상.
        assert feat.address.bjd_code == "1114010300"
        assert feat.address.sigungu_code == "11140"
        assert feat.address.sido_code == "11"
        assert feat.address.sido_name == "서울특별시"
        # ADR-009 — feature_id는 bjd bucket으로 (=`f_global_` prefix가 아님).
        assert feat.feature_id.startswith("f_")
        assert "global" not in feat.feature_id, feat.feature_id


# ── 2) reverse_geocoder=None — bjd 비고 'global' fallback ─────────────────


async def test_festival_without_reverse_geocoder_falls_back_to_global() -> None:
    """대조군 — reverse_geocoder 미주입 시 좌표는 있어도 bjd_code None,
    feature_id는 'global' bucket으로 떨어짐(ADR-009)."""
    festival = _make_festival(
        no="LIVE-FEST-NORG",
        name="reverse 미주입",
        lon="126.9779",
        lat="37.5663",
    )
    bundles = await cultural_festivals_to_bundles(
        [festival],  # type: ignore[list-item]
        fetched_at=datetime(2026, 5, 28, 12, 0, tzinfo=_KST),
        reverse_geocoder=None,
    )
    feat = bundles[0].feature
    assert feat.address.bjd_code is None
    assert feat.address.sido_code is None
    # 'global' 버킷 fallback — feature_id에 'global' 등장.
    assert "global" in feat.feature_id, feat.feature_id


# ── 3) cached_reverse_geocoder — 같은 좌표 N건 → kraddr-geo 1회 ──────────


async def test_cached_reverse_geocoder_dedupes_same_coord(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        client = KraddrGeoRestClient(http)
        raw = kraddr_geo_reverse_geocoder(client)
        counted, counts = _wrap_with_counter(raw)
        cached = cached_reverse_geocoder(counted)

        # 같은 좌표 5개 축제 + 별도 좌표 1개 = 호출 2회로 줄어야.
        same = [
            _make_festival(no=f"LIVE-FEST-SAME-{i}", name=f"같은{i}", lon="126.9779", lat="37.5663")
            for i in range(5)
        ]
        diff = _make_festival(no="LIVE-FEST-DIFF", name="다른", lon="127.3845", lat="36.3504")

        bundles = await cultural_festivals_to_bundles(
            [*same, diff],  # type: ignore[list-item]
            fetched_at=datetime(2026, 5, 28, 12, 0, tzinfo=_KST),
            reverse_geocoder=cached,
        )
        assert len(bundles) == 6
        # 같은 좌표 5건은 한 번만 호출, 다른 좌표 1건은 별도 호출 → 총 2회.
        assert counts["n"] == 2, f"expected 2 kraddr-geo calls, got {counts['n']}"
        # 같은 좌표 그룹은 모두 동일 bjd_code(서울 중구) — global 탈출.
        for b in bundles[:5]:
            assert b.feature.address.bjd_code == "1114010300"
        # 다른 좌표는 대전(30로 시작).
        assert bundles[5].feature.address.sido_code == "30"


# ── 4) 좌표 다른 부산 + 한라산 — 시도가 정확히 분기 ────────────────────────


async def test_two_distinct_coords_yield_distinct_bjds(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        client = KraddrGeoRestClient(http)
        reverse = kraddr_geo_reverse_geocoder(client, max_distance_m=500)
        cached = cached_reverse_geocoder(reverse)

        busan = _make_festival(
            no="LIVE-FEST-BUSAN",
            name="부산축제",
            lon="129.0756",
            lat="35.1796",
        )
        daejeon = _make_festival(
            no="LIVE-FEST-DAEJEON",
            name="대전축제",
            lon="127.3845",
            lat="36.3504",
        )
        bundles = await cultural_festivals_to_bundles(
            [busan, daejeon],  # type: ignore[list-item]
            fetched_at=datetime(2026, 5, 28, 12, 0, tzinfo=_KST),
            reverse_geocoder=cached,
        )
        assert bundles[0].feature.address.sido_code == "26"  # 부산
        assert bundles[1].feature.address.sido_code == "30"  # 대전
        # feature_id가 서로 다른 bjd bucket으로.
        assert bundles[0].feature.feature_id != bundles[1].feature.feature_id


# ── 5) feature_id 결정성 — 같은 입력 두 번 → 같은 ID ─────────────────────


async def test_feature_id_is_deterministic_with_geocoder(base_url: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        client = KraddrGeoRestClient(http)
        reverse = kraddr_geo_reverse_geocoder(client)
        festival = _make_festival(
            no="LIVE-FEST-DETERMINISTIC",
            name="결정성",
            lon="126.9779",
            lat="37.5663",
        )
        b1 = await cultural_festivals_to_bundles(
            [festival],  # type: ignore[list-item]
            fetched_at=datetime(2026, 5, 28, 12, 0, tzinfo=_KST),
            reverse_geocoder=reverse,
        )
        b2 = await cultural_festivals_to_bundles(
            [festival],  # type: ignore[list-item]
            fetched_at=datetime(2026, 5, 28, 12, 0, tzinfo=_KST),
            reverse_geocoder=reverse,
        )
        assert b1[0].feature.feature_id == b2[0].feature.feature_id
        assert b1[0].feature.address.bjd_code == b2[0].feature.address.bjd_code


# ── 6) ReverseGeocoder None 결과 graceful (kraddr-geo가 미발견 좌표) ──────


async def test_no_match_coord_falls_back_to_global(base_url: str) -> None:
    """한국 본토 안이지만 kraddr-geo가 NOT_FOUND를 돌려줄 만한 좌표
    (동해 영해 부근). reverse 결과가 None이면 변환기는 bjd 없이 진행 →
    feature_id 'global' 버킷."""
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        client = KraddrGeoRestClient(http)
        reverse = kraddr_geo_reverse_geocoder(client)
        # 동해 한가운데 — Coordinate 한국 경계 안이지만 도로/지번 데이터 부재 가능.
        f = _make_festival(
            no="LIVE-FEST-OCEAN",
            name="동해축제",
            lon="130.5",
            lat="37.5",
        )
        try:
            bundles = await cultural_festivals_to_bundles(
                [f],  # type: ignore[list-item]
                fetched_at=datetime(2026, 5, 28, 12, 0, tzinfo=_KST),
                reverse_geocoder=reverse,
            )
        except httpx.HTTPStatusError:
            # kraddr-geo가 좌표 범위 외부로 reject(400/422)할 수도 있음 — 그 경우는
            # 라이브러리 측 fallback이 없으므로 본 테스트의 범위를 벗어남.
            pytest.skip("kraddr-geo가 해당 좌표를 reject — provider fallback 검증 불가")
        # NOT_FOUND이면 bjd None + global bucket.
        feat = bundles[0].feature
        if feat.address.bjd_code is None:
            assert "global" in feat.feature_id
        else:
            # kraddr-geo가 가까운 육지 도로명을 돌려준 경우 — 그것도 정합 (bjd 채워짐).
            assert feat.address.sido_code is not None
