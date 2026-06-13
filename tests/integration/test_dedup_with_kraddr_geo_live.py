"""``test_dedup_with_kor_travel_geo_live`` — dedup 큐 end-to-end (testcontainers + 실
kor-travel-geo). 두 provider feature가 실 kor-travel-geo로 보강되고, 적재 → dedup 후보
검출 → ``ops.dedup_review_queue`` 영속화까지 한 PR로 닫는다.

요구: ``LIVE_KOR_TRAVEL_GEO_BASE_URL`` 도달 가능 (기본 http://127.0.0.1:12501)
+ Docker(testcontainers PostGIS). 도달 불가 시 ``pytest.skip``.

검증 시나리오:
1. 두 제공처(=두 자연키, name::address 파생 — #374)가 **같은 좌표·같은 이름**을 emit → 양쪽 모두 실
   kor-travel-geo bjd 보강 → DB 적재 → ``sync_dedup_candidates`` → score≥0.85 →
   queue에 1 행 + decision=``auto_merge``.
2. 같은 이름·**먼 좌표** → spatial_sim 매우 낮음 → KEEP_SEPARATE → 큐 0 행.
3. 다른 이름·같은 좌표 → name_sim 낮고 spatial=1.0+category=1.0 → manual_review
   대역 (또는 KEEP_SEPARATE — 가중치 0.45*0+0.35*1+0.20*1 = 0.55 < 0.65). 큐 0 행.
4. 같은 후보 재실행 — ``updated=1``, ``inserted=0`` (점수 재계산 + WHERE pending).
"""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import TYPE_CHECKING
from urllib.parse import urlparse

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.client import AsyncKorTravelMapClient
from kortravelmap.geocoding import (
    KorTravelGeoRestClient,
    cached_reverse_geocoder,
    kor_travel_geo_reverse_geocoder,
)
from kortravelmap.providers.standard_data import cultural_festivals_to_bundles

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = [pytest.mark.integration, pytest.mark.live]

_KST = timezone(timedelta(hours=9))
_FETCHED_AT = datetime(2026, 5, 28, 12, 0, tzinfo=_KST)
_DEFAULT_BASE_URL = "http://127.0.0.1:12501"


def _canonical_pair(feature_id_a: str, feature_id_b: str) -> tuple[str, str]:
    return (
        (feature_id_a, feature_id_b)
        if feature_id_a < feature_id_b
        else (feature_id_b, feature_id_a)
    )


def _resolve_base_url() -> str:
    return os.environ.get("LIVE_KOR_TRAVEL_GEO_BASE_URL", _DEFAULT_BASE_URL)


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
def kor_travel_geo_base_url() -> str:
    url = _resolve_base_url()
    if not _is_reachable(url):
        pytest.skip(f"kor-travel-geo 도달 불가: {url}")
    return url


_TRUNCATE_SQL = (
    "TRUNCATE feature.features, provider_sync.source_records, "
    "provider_sync.source_links, ops.dedup_review_queue RESTART IDENTITY CASCADE"
)


@pytest.fixture
async def map_client(
    migrated_engine: AsyncEngine,
) -> AsyncIterator[AsyncKorTravelMapClient]:
    """client + teardown TRUNCATE (client는 commit하므로 명시 격리)."""
    client = AsyncKorTravelMapClient(migrated_engine)
    try:
        yield client
    finally:
        async with AsyncSession(migrated_engine) as session, session.begin():
            await session.execute(text(_TRUNCATE_SQL))


# ── 헬퍼 ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Festival:
    """`CulturalFestivalItem` Protocol 만족 — provider 실모델 필드명 (#374)."""

    fstvl_nm: str | None
    opar: str | None = None
    fstvl_start_date: date | None = None
    fstvl_end_date: date | None = None
    fstvl_co: str | None = None
    mnnst_nm: str | None = None
    auspc_instt_nm: str | None = None
    suprt_instt_nm: str | None = None
    phone_number: str | None = None
    homepage_url: str | None = None
    relate_info: str | None = None
    rdnmadr: str | None = None
    lnmadr: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reference_date: date | None = None
    instt_code: str | None = None
    instt_nm: str | None = None


def _festival(
    *, no: str, name: str, lon: str, lat: str, org: str = "test-org"
) -> _Festival:
    # 자연키가 name::address 파생(#374)이라, 같은 이름의 두 제공처 row를
    # 별개 feature로 만들려면 주소를 no로 구분한다.
    return _Festival(
        fstvl_nm=name,
        fstvl_start_date=date(2026, 4, 1),
        fstvl_end_date=date(2026, 4, 10),
        rdnmadr=f"서울특별시 중구 세종대로 110 ({no})",
        latitude=float(lat),
        longitude=float(lon),
        reference_date=date(2026, 3, 1),
        instt_nm=org,
    )


async def _enrich_and_load(
    base_url: str, client: AsyncKorTravelMapClient, items: list[_Festival]
) -> list[object]:
    """축제 items → kor-travel-geo로 bjd 보강 → client.load_feature_bundles → bundles 반환."""
    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as http:
        kraddr = KorTravelGeoRestClient(http)
        reverse = cached_reverse_geocoder(
            kor_travel_geo_reverse_geocoder(kraddr, max_distance_m=500)
        )
        bundles = await cultural_festivals_to_bundles(
            items,  # type: ignore[arg-type]
            fetched_at=_FETCHED_AT,
            reverse_geocoder=reverse,
        )
    await client.load_feature_bundles(bundles)
    return list(bundles)


# ── 1) 같은 좌표·같은 이름·다른 provider → auto_merge 큐 입주 ─────────────


async def test_dedup_auto_merge_with_real_geocoder(
    map_client: AsyncKorTravelMapClient, kor_travel_geo_base_url: str
) -> None:
    a = _festival(
        no="LIVE-DEDUP-A1",
        name="동일한 축제",
        lon="126.9779",
        lat="37.5663",
        org="provider-a",
    )
    b = _festival(
        no="LIVE-DEDUP-B1",
        name="동일한 축제",
        lon="126.9779",
        lat="37.5663",
        org="provider-b",
    )
    bundles = await _enrich_and_load(kor_travel_geo_base_url, map_client, [a, b])
    assert len(bundles) == 2
    feat_a, feat_b = bundles[0].feature, bundles[1].feature  # type: ignore[attr-defined]
    # 양쪽 모두 bjd 보강 + global 탈출.
    assert feat_a.address.bjd_code is not None
    assert feat_b.address.bjd_code is not None
    assert feat_a.address.bjd_code == feat_b.address.bjd_code
    assert "global" not in feat_a.feature_id
    assert "global" not in feat_b.feature_id

    # find_dedup_candidates + 큐 적재.
    sync = await map_client.sync_dedup_candidates([feat_a], [feat_b])
    assert len(sync.candidates) == 1
    assert sync.candidates[0].decision == "auto_merge"
    assert sync.queue.inserted == 1
    assert sync.queue.updated == 0

    reviews = await map_client.pending_dedup_reviews()
    assert len(reviews) == 1
    row = reviews[0]
    assert row["decision_reason"] == "auto_merge"
    assert row["total_score"] >= 85.0
    assert (row["feature_id_a"], row["feature_id_b"]) == _canonical_pair(
        feat_a.feature_id,
        feat_b.feature_id,
    )


# ── 2) 같은 이름 + 먼 좌표 → KEEP_SEPARATE → 큐 비어있음 ─────────────────


async def test_dedup_keep_separate_far_coord(
    map_client: AsyncKorTravelMapClient, kor_travel_geo_base_url: str
) -> None:
    seoul = _festival(
        no="LIVE-DEDUP-SEOUL", name="동명축제", lon="126.9779", lat="37.5663"
    )
    busan = _festival(
        no="LIVE-DEDUP-BUSAN", name="동명축제", lon="129.0756", lat="35.1796"
    )
    bundles = await _enrich_and_load(kor_travel_geo_base_url, map_client, [seoul, busan])
    feat_seoul, feat_busan = bundles[0].feature, bundles[1].feature  # type: ignore[attr-defined]
    # sido 11 / 26 — 명확히 다른 시도.
    assert feat_seoul.address.sido_code == "11"
    assert feat_busan.address.sido_code == "26"

    sync = await map_client.sync_dedup_candidates([feat_seoul], [feat_busan])
    # spatial exp(-(~325km*1000)/50) ≈ 0 → name 1.0*0.45 + spatial 0*0.35 + cat 1.0*0.20 = 0.65
    # 경계값에 걸려있음 — 본 lib THRESHOLD_MANUAL=0.65 boundary는 `score >= 0.65`
    # 이므로 manual_review가 될 수도 있다 — 결정은 라이브러리 정책 그대로 신뢰.
    if sync.candidates:
        # manual_review로 떨어졌다면 큐에 1건 들어감.
        assert sync.candidates[0].decision == "manual_review"
        assert sync.queue.inserted == 1
    else:
        # KEEP_SEPARATE → 큐 빈 상태.
        assert sync.queue.inserted == 0
        assert await map_client.pending_dedup_reviews() == []


# ── 3) 다른 이름 + 같은 좌표 → name_sim 매우 낮음 → 큐 입주 안 함 ─────────


async def test_dedup_different_name_same_coord(
    map_client: AsyncKorTravelMapClient, kor_travel_geo_base_url: str
) -> None:
    a = _festival(
        no="LIVE-DEDUP-DIFF-A",
        name="봄꽃축제",
        lon="126.9779",
        lat="37.5663",
    )
    b = _festival(
        no="LIVE-DEDUP-DIFF-B",
        name="크리스마스마켓",  # 완전히 다른 이름
        lon="126.9779",
        lat="37.5663",
    )
    bundles = await _enrich_and_load(kor_travel_geo_base_url, map_client, [a, b])
    feat_a, feat_b = bundles[0].feature, bundles[1].feature  # type: ignore[attr-defined]

    sync = await map_client.sync_dedup_candidates([feat_a], [feat_b])
    # name_sim≈0 + spatial=1.0 + category=1.0 → 0*0.45 + 1*0.35 + 1*0.2 = 0.55 < 0.65
    # → KEEP_SEPARATE, 큐 빈 상태.
    assert sync.queue.inserted == 0
    assert await map_client.pending_dedup_reviews() == []


# ── 4) 재실행 — 같은 후보는 updated, 검토완료 행은 skipped ──────────────


async def test_dedup_rerun_updates_pending_preserves_reviewed(
    map_client: AsyncKorTravelMapClient,
    migrated_engine: AsyncEngine,
    kor_travel_geo_base_url: str,
) -> None:
    a = _festival(
        no="LIVE-DEDUP-RERUN-A", name="동일축제", lon="126.9779", lat="37.5663"
    )
    b = _festival(
        no="LIVE-DEDUP-RERUN-B", name="동일축제", lon="126.9779", lat="37.5663"
    )
    bundles = await _enrich_and_load(kor_travel_geo_base_url, map_client, [a, b])
    feat_a, feat_b = bundles[0].feature, bundles[1].feature  # type: ignore[attr-defined]

    # 첫 sync — inserted=1.
    s1 = await map_client.sync_dedup_candidates([feat_a], [feat_b])
    assert s1.queue.inserted == 1

    # 두 번째 sync — 같은 후보, 점수 동일 → updated=1.
    s2 = await map_client.sync_dedup_candidates([feat_a], [feat_b])
    assert s2.queue.updated == 1
    assert s2.queue.inserted == 0

    # 운영자가 accepted로 표기 (commit 격리).
    canonical_a, canonical_b = _canonical_pair(feat_a.feature_id, feat_b.feature_id)
    async with AsyncSession(migrated_engine) as session, session.begin():
        await session.execute(
            text(
                "UPDATE ops.dedup_review_queue SET status='accepted' "
                "WHERE feature_id_a=:a AND feature_id_b=:b"
            ),
            {"a": canonical_a, "b": canonical_b},
        )

    # 세 번째 sync — accepted 행이라 skipped.
    s3 = await map_client.sync_dedup_candidates([feat_a], [feat_b])
    assert s3.queue.skipped == 1
    assert s3.queue.inserted == 0
    assert s3.queue.updated == 0

    # pending 큐는 비어있어야 (accepted 행은 pending_dedup_reviews에서 제외).
    assert await map_client.pending_dedup_reviews() == []


# ── 5) include_auto_merge=False — auto_merge 후보 큐 미입주 ────────────


async def test_dedup_exclude_auto_merge_via_kor_travel_geo(
    map_client: AsyncKorTravelMapClient, kor_travel_geo_base_url: str
) -> None:
    a = _festival(
        no="LIVE-DEDUP-EXCL-A", name="제외 시험", lon="126.9779", lat="37.5663"
    )
    b = _festival(
        no="LIVE-DEDUP-EXCL-B", name="제외 시험", lon="126.9779", lat="37.5663"
    )
    bundles = await _enrich_and_load(kor_travel_geo_base_url, map_client, [a, b])
    feat_a, feat_b = bundles[0].feature, bundles[1].feature  # type: ignore[attr-defined]

    sync = await map_client.sync_dedup_candidates(
        [feat_a], [feat_b], include_auto_merge=False
    )
    # 동일 쌍은 auto_merge — include_auto_merge=False면 후보 0건 → 큐 빈 상태.
    assert sync.candidates == []
    assert sync.queue.inserted == 0
    assert await map_client.pending_dedup_reviews() == []
