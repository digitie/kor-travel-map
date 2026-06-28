"""``kortravelmap.api.provider_catalog`` — 전 provider×dataset 카탈로그 (정본).

배경
----
admin UI의 **ETL preview**(`/etl`)와 **Providers**(`/ops/providers`) 메뉴는
지금까지 서로 다른, 불완전한 source에서 provider 목록을 그렸다:

- `/etl`  → `etl_fixtures.list_providers()` (fixture-backed 9종)
- `/ops/providers` → `provider_sync_state` row (한 번이라도 RUN 된 6종)

둘 중 어느 쪽도 mois/knps/krheritage/mcst 같은 "구현은 됐으나 fixture/sync
state가 아직 없는" provider를 나타내지 못했다. 본 모듈은 **시스템이 ETL 하는
모든 provider×dataset**의 단일 정본 카탈로그를 둔다.

설계 원칙
--------
- **drift-safe**: dataset_key/provider 이름은 가능한 한 provider 모듈의 **상수·
  dict를 import 해서** 참조한다 (literal 중복 금지). provider 모듈이 dataset_key
  를 바꾸면 본 카탈로그도 자동으로 따라간다.
- **preview 가용성**: 각 dataset의 `preview`(`fixture`/`live`/`none`)는 import
  시점에 `etl_fixtures.FIXTURE_REGISTRY`/`etl_live.LIVE_LOADER_REGISTRY`를 조회해
  결정한다 — 카탈로그와 registry가 어긋나면 자동으로 드러난다.
- 본 모듈은 **데이터(상수)만** 둔다 — DB/외부 호출 없음. 라우터가 이 카탈로그를
  sync state와 LEFT JOIN 해서 응답을 만든다.

ADR 참조
--------
- ADR-006 — provider wrapper 금지. 본 모듈은 provider 모듈의 상수만 참조.
- ADR-020 — REST API dist(`kortravelmap.api`)는 `kortravelmap` core/providers를
  자유롭게 import. 본 모듈이 providers를 import 하는 건 dist 측이라 허용.
- ADR-034 — provider 9단계 구현 순서.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from kortravelmap.enrichment import ENRICHMENT_DATASET_KEY
from kortravelmap.providers.airkorea import (
    AIRKOREA_PROVIDER_NAME,
    DATASET_KEY_AIR_QUALITY,
    DATASET_KEY_STATIONS,
)
from kortravelmap.providers.datagokr_file_data import (
    DATAGOKR_FILEDATA_DATASETS,
    DATAGOKR_FILEDATA_PROVIDER_NAME,
)
from kortravelmap.providers.khoa import DATASET_KEY_BEACHES, KHOA_PROVIDER_NAME
from kortravelmap.providers.kma import (
    KMA_MID_FORECAST_DATASET_KEY,
    KMA_PROVIDER_NAME,
    KMA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
    KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
    KMA_WEATHER_ALERT_DATASET_KEY,
)
from kortravelmap.providers.knps import (
    KNPS_GEOMETRY_DATASETS,
    KNPS_PLACE_DATASETS,
)
from kortravelmap.providers.knps import (
    PROVIDER_NAME as KNPS_PROVIDER_NAME,
)
from kortravelmap.providers.kor_travel_concierge import (
    DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
    KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
)
from kortravelmap.providers.krairport import (
    DATASET_KEY_AIRPORTS,
    KRAIRPORT_PROVIDER_NAME,
)
from kortravelmap.providers.krex import (
    KREX_PROVIDER_NAME,
    REST_AREA_DATASET_KEY,
    REST_AREA_PRICES_DATASET_KEY,
    REST_AREA_WEATHER_DATASET_KEY,
    TRAFFIC_NOTICES_DATASET_KEY,
)
from kortravelmap.providers.krforest import (
    DATASET_KEY_ARBORETUMS,
    DATASET_KEY_RECREATION_FORESTS,
    KRFOREST_PROVIDER_NAME,
)
from kortravelmap.providers.krheritage import (
    DATASET_KEY_EVENT as KRHERITAGE_DATASET_KEY_EVENT,
)
from kortravelmap.providers.krheritage import (
    DATASET_KEY_HERITAGE,
)
from kortravelmap.providers.krheritage import (
    PROVIDER_NAME as KRHERITAGE_PROVIDER_NAME,
)
from kortravelmap.providers.mcst import (
    MCST_FILE_DATASETS,
    MCST_PROVIDER_NAME,
)
from kortravelmap.providers.mois import (
    DATASET_KEY_BULK,
    DATASET_KEY_CLOSED,
    DATASET_KEY_DETAIL,
    DATASET_KEY_HISTORY,
)
from kortravelmap.providers.mois import (
    PROVIDER_NAME as MOIS_PROVIDER_NAME,
)
from kortravelmap.providers.opinet import (
    OPINET_PRICE_DATASET_KEY,
    OPINET_PROVIDER_NAME,
    OPINET_STATION_DATASET_KEY,
)
from kortravelmap.providers.standard_data import (
    DATASET_KEY_CULTURAL_FESTIVALS,
    DATASET_KEY_MUSEUMS,
    DATASET_KEY_PARKING_LOTS,
    DATASET_KEY_SPECIAL_STREETS,
    DATASET_KEY_TOURIST_ATTRACTIONS,
    STANDARD_DATA_PROVIDER_NAME,
)
from kortravelmap.providers.visitkorea import (
    DATASET_KEY_FESTIVAL_EVENTS,
    VISITKOREA_PROVIDER_NAME,
)

from kortravelmap.api.etl_fixtures import FIXTURE_REGISTRY
from kortravelmap.api.etl_live import LIVE_LOADER_REGISTRY

__all__ = [
    "PreviewKind",
    "ProviderDatasetCatalogEntry",
    "PROVIDER_DATASET_CATALOG",
    "list_catalog_providers",
    "catalog_datasets",
    "catalog_feature_load_entries",
    "catalog_refreshable_entries",
    "find_catalog_entry",
]


PreviewKind = Literal["fixture", "live", "none"]
"""dataset preview 가용성 — fixture(오프라인 replay) / live(provider 실호출) / none."""


@dataclass(frozen=True)
class ProviderDatasetCatalogEntry:
    """시스템이 ETL 하는 1 provider×dataset 카탈로그 항목.

    Attributes
    ----------
    provider:
        provider canonical name (provider 모듈 ``*_PROVIDER_NAME`` 상수).
    dataset_key:
        provider_sync ``dataset_key`` (provider 모듈 상수/dict 키).
    feature_kind:
        산출 Feature 종류 (place/event/notice/price/weather/route/area).
        WeatherValue/PriceValue load는 매칭 대상 Feature kind를 표기.
    sync_scope:
        provider_sync ``sync_scope`` — 대부분 ``default``, KMA 격자/region 예외.
    label:
        운영자용 한글 라벨.
    is_feature_load:
        새 Feature(FeatureBundle)를 적재하면 True. WeatherValue/PriceValue/
        enrichment-only 경로는 False.
    is_refreshable:
        Dagster feature update request로 실행 가능한 적재/갱신 단위이면 True.
        ``is_feature_load=False``인 PriceValue/WeatherValue/enrichment도 여기에
        포함될 수 있다. 아직 runner가 없는 수동 보강/alias 항목은 False.
    preview:
        ETL preview 가용성 — import 시점에 fixture/live registry 조회로 결정.
    """

    provider: str
    dataset_key: str
    feature_kind: str
    sync_scope: str
    label: str
    is_feature_load: bool
    is_refreshable: bool
    preview: PreviewKind


_FIXTURE_KEYS: Final[frozenset[tuple[str, str]]] = frozenset(
    (entry.provider, entry.dataset) for entry in FIXTURE_REGISTRY
)


def _preview_for(provider: str, dataset_key: str) -> PreviewKind:
    """fixture/live registry를 조회해 dataset의 preview 가용성을 결정.

    fixture가 있으면 ``fixture``(오프라인이라 가장 견고), 없고 live loader만 있으면
    ``live``, 둘 다 없으면 ``none``.
    """
    if (provider, dataset_key) in _FIXTURE_KEYS:
        return "fixture"
    if (provider, dataset_key) in LIVE_LOADER_REGISTRY:
        return "live"
    return "none"


def _entry(
    *,
    provider: str,
    dataset_key: str,
    feature_kind: str,
    label: str,
    is_feature_load: bool,
    is_refreshable: bool | None = None,
    sync_scope: str = "default",
) -> ProviderDatasetCatalogEntry:
    return ProviderDatasetCatalogEntry(
        provider=provider,
        dataset_key=dataset_key,
        feature_kind=feature_kind,
        sync_scope=sync_scope,
        label=label,
        is_feature_load=is_feature_load,
        is_refreshable=is_feature_load if is_refreshable is None else is_refreshable,
        preview=_preview_for(provider, dataset_key),
    )


# MCST 13 파일데이터 slug → 한글 라벨/category는 provider dict가 정본. 카탈로그는
# dataset_key/label을 그 dict에서 그대로 끌어온다 (drift-safe, literal 중복 회피).
_MCST_ENTRIES: Final[tuple[ProviderDatasetCatalogEntry, ...]] = tuple(
    _entry(
        provider=MCST_PROVIDER_NAME,
        dataset_key=spec.dataset_key,
        feature_kind="place",
        label=spec.label,
        is_feature_load=True,
    )
    for spec in MCST_FILE_DATASETS.values()
)

# KNPS place(point) 5 dataset — provider dict 키가 dataset_key 정본.
_KNPS_PLACE_LABELS: Final[dict[str, str]] = {
    "knps_visitor_centers": "국립공원 탐방안내소",
    "knps_restrooms": "국립공원 화장실",
    "knps_campgrounds": "국립공원 야영장",
    "knps_shelters": "국립공원 대피소(산장)",
    "knps_cultural_resources": "국립공원 문화자원(동적 category)",
}
_KNPS_GEOMETRY_LABELS: Final[dict[str, str]] = {
    "knps_trails": "국립공원 탐방로(LINESTRING)",
    "knps_linear_facilities": "국립공원 선형 시설도로(LINESTRING)",
    "knps_park_boundaries": "국립공원 경계(POLYGON)",
    "knps_hazard_zones": "국립공원 위험지역(POLYGON)",
    "knps_protected_areas": "국립공원 보호지역(POLYGON)",
}
_KNPS_ENTRIES: Final[tuple[ProviderDatasetCatalogEntry, ...]] = tuple(
    _entry(
        provider=KNPS_PROVIDER_NAME,
        dataset_key=spec.dataset_key,
        feature_kind="place",
        label=_KNPS_PLACE_LABELS.get(spec.dataset_key, spec.dataset_key),
        is_feature_load=True,
    )
    for spec in KNPS_PLACE_DATASETS.values()
) + tuple(
    _entry(
        provider=KNPS_PROVIDER_NAME,
        dataset_key=spec.dataset_key,
        # KnpsGeometryDatasetSpec.feature_kind는 FeatureKind StrEnum → str.
        feature_kind=str(spec.feature_kind),
        label=_KNPS_GEOMETRY_LABELS.get(spec.dataset_key, spec.dataset_key),
        is_feature_load=True,
    )
    for spec in KNPS_GEOMETRY_DATASETS.values()
)

# datagokr fileData curated 4 dataset — provider dict 키가 dataset_key 정본.
_DATAGOKR_FILEDATA_ENTRIES: Final[tuple[ProviderDatasetCatalogEntry, ...]] = tuple(
    _entry(
        provider=DATAGOKR_FILEDATA_PROVIDER_NAME,
        dataset_key=spec.dataset_key,
        feature_kind="place",
        label=spec.label,
        is_feature_load=True,
    )
    for spec in DATAGOKR_FILEDATA_DATASETS.values()
)


PROVIDER_DATASET_CATALOG: Final[tuple[ProviderDatasetCatalogEntry, ...]] = (
    # ── data.go.kr 표준데이터 (standard_data) ─────────────────────────────
    _entry(
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_CULTURAL_FESTIVALS,
        feature_kind="event",
        label="전국문화축제표준데이터 (1차 source, ADR-042)",
        is_feature_load=True,
    ),
    _entry(
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_MUSEUMS,
        feature_kind="place",
        label="전국박물관미술관표준데이터",
        is_feature_load=True,
    ),
    _entry(
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_TOURIST_ATTRACTIONS,
        feature_kind="place",
        label="전국관광지표준데이터",
        is_feature_load=True,
    ),
    _entry(
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_PARKING_LOTS,
        feature_kind="place",
        label="전국주차장표준데이터",
        is_feature_load=True,
    ),
    _entry(
        provider=STANDARD_DATA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_SPECIAL_STREETS,
        feature_kind="place",
        label="전국지역특화거리표준데이터 (테마 구역 anchor)",
        is_feature_load=True,
    ),
    # ── 기상청 (KMA) ─────────────────────────────────────────────────────
    _entry(
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_SHORT_FORECAST_DATASET_KEY,
        feature_kind="weather",
        sync_scope="target_grids",
        label="KMA 단기예보 (getVilageFcst, 3시간×5일)",
        is_feature_load=False,
        is_refreshable=True,
    ),
    _entry(
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_ULTRA_SHORT_NOWCAST_DATASET_KEY,
        feature_kind="weather",
        sync_scope="target_grids",
        label="KMA 초단기실황 (getUltraSrtNcst, 관측)",
        is_feature_load=False,
        is_refreshable=True,
    ),
    _entry(
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_ULTRA_SHORT_FORECAST_DATASET_KEY,
        feature_kind="weather",
        sync_scope="target_grids",
        label="KMA 초단기예보 (getUltraSrtFcst, 30분×6시간)",
        is_feature_load=False,
        is_refreshable=True,
    ),
    _entry(
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_MID_FORECAST_DATASET_KEY,
        feature_kind="weather",
        sync_scope="mid_region",
        label="KMA 중기예보 (getMidLandFcst + getMidTa, 3~10일)",
        is_feature_load=False,
        is_refreshable=True,
    ),
    _entry(
        provider=KMA_PROVIDER_NAME,
        dataset_key=KMA_WEATHER_ALERT_DATASET_KEY,
        feature_kind="notice",
        sync_scope="region",
        label="KMA 기상특보 (특보×구역 fan-out)",
        is_feature_load=True,
    ),
    # ── 해양수산부 (KHOA) ────────────────────────────────────────────────
    _entry(
        provider=KHOA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_BEACHES,
        feature_kind="place",
        label="해양수산부 해수욕장정보",
        is_feature_load=True,
    ),
    # ── 한국환경공단 (AirKorea) ──────────────────────────────────────────
    _entry(
        provider=AIRKOREA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_STATIONS,
        feature_kind="weather",
        label="대기질 측정소 (weather-kind Feature)",
        is_feature_load=False,
        is_refreshable=False,
    ),
    _entry(
        provider=AIRKOREA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_AIR_QUALITY,
        feature_kind="weather",
        label="대기질 측정소 + 측정값 (weather Feature + WeatherValue)",
        is_feature_load=True,
    ),
    # ── 한국석유공사 (OpiNet) ────────────────────────────────────────────
    _entry(
        provider=OPINET_PROVIDER_NAME,
        dataset_key=OPINET_STATION_DATASET_KEY,
        feature_kind="place",
        label="OpiNet 주유소 상세 (place Feature)",
        is_feature_load=True,
    ),
    _entry(
        provider=OPINET_PROVIDER_NAME,
        dataset_key=OPINET_PRICE_DATASET_KEY,
        feature_kind="price",
        label="OpiNet 유가 시계열 (PriceValue)",
        is_feature_load=False,
        is_refreshable=True,
    ),
    # ── 한국도로공사 (krex) ──────────────────────────────────────────────
    _entry(
        provider=KREX_PROVIDER_NAME,
        dataset_key=REST_AREA_DATASET_KEY,
        feature_kind="place",
        label="고속도로 휴게소 (place Feature)",
        is_feature_load=True,
    ),
    _entry(
        provider=KREX_PROVIDER_NAME,
        dataset_key=REST_AREA_PRICES_DATASET_KEY,
        feature_kind="price",
        label="휴게소 food/fuel 가격 시계열 (PriceValue)",
        is_feature_load=False,
        is_refreshable=True,
    ),
    _entry(
        provider=KREX_PROVIDER_NAME,
        dataset_key=REST_AREA_WEATHER_DATASET_KEY,
        feature_kind="weather",
        label="휴게소 관측 기상 (observed WeatherValue + weather Feature)",
        is_feature_load=False,
        is_refreshable=True,
    ),
    _entry(
        provider=KREX_PROVIDER_NAME,
        dataset_key=TRAFFIC_NOTICES_DATASET_KEY,
        feature_kind="notice",
        label="고속도로 교통 공지/돌발 (notice Feature)",
        is_feature_load=True,
    ),
    # ── 산림청 (krforest) ────────────────────────────────────────────────
    _entry(
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=DATASET_KEY_RECREATION_FORESTS,
        feature_kind="place",
        label="전국자연휴양림",
        is_feature_load=True,
    ),
    _entry(
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=DATASET_KEY_ARBORETUMS,
        feature_kind="place",
        label="수목원/식물원 (SHP)",
        is_feature_load=True,
    ),
    # ── 한국공항공사 (krairport) ─────────────────────────────────────────
    _entry(
        provider=KRAIRPORT_PROVIDER_NAME,
        dataset_key=DATASET_KEY_AIRPORTS,
        feature_kind="place",
        label="공항 메타데이터 (번들 정적)",
        is_feature_load=True,
    ),
    # ── 국가유산청 (krheritage) ──────────────────────────────────────────
    _entry(
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_key=DATASET_KEY_HERITAGE,
        feature_kind="place",
        label="국가유산 (국보/보물/사적/명승 등; place 또는 area)",
        is_feature_load=True,
    ),
    _entry(
        provider=KRHERITAGE_PROVIDER_NAME,
        dataset_key=KRHERITAGE_DATASET_KEY_EVENT,
        feature_kind="event",
        label="국가유산 행사 목록",
        is_feature_load=True,
    ),
    # ── 행정안전부 인허가 (MOIS) ─────────────────────────────────────────
    _entry(
        provider=MOIS_PROVIDER_NAME,
        dataset_key=DATASET_KEY_BULK,
        feature_kind="place",
        label="MOIS 지방행정 인허가 bulk (영업중, PROMOTED 42업종)",
        is_feature_load=True,
    ),
    _entry(
        provider=MOIS_PROVIDER_NAME,
        dataset_key=DATASET_KEY_HISTORY,
        feature_kind="place",
        label="MOIS 인허가 history (증분/변경분)",
        is_feature_load=True,
    ),
    _entry(
        provider=MOIS_PROVIDER_NAME,
        dataset_key=DATASET_KEY_CLOSED,
        feature_kind="place",
        label="MOIS 인허가 closed (폐업 — tombstone/inactive)",
        is_feature_load=True,
    ),
    _entry(
        provider=MOIS_PROVIDER_NAME,
        dataset_key=DATASET_KEY_DETAIL,
        feature_kind="place",
        label="MOIS 인허가 상세(detail) 보강",
        is_feature_load=False,
        is_refreshable=True,
    ),
    # ── VisitKorea / 전화번호 enrichment ─────────────────────────────────
    _entry(
        provider=VISITKOREA_PROVIDER_NAME,
        dataset_key=DATASET_KEY_FESTIVAL_EVENTS,
        feature_kind="event",
        label="VisitKorea 축제 enrichment (datagokr 1차에 2차 보강)",
        is_feature_load=False,
        is_refreshable=True,
    ),
    _entry(
        provider=VISITKOREA_PROVIDER_NAME,
        dataset_key=ENRICHMENT_DATASET_KEY,
        feature_kind="place",
        label="전화번호 보강 (place detail.phones; candidate: kakao/naver/google)",
        is_feature_load=False,
        is_refreshable=False,
    ),
    # ── kor-travel-concierge YouTube ─────────────────────────────────────
    _entry(
        provider=KOR_TRAVEL_CONCIERGE_PROVIDER_NAME,
        dataset_key=DATASET_KEY_YOUTUBE_PLACE_CANDIDATES,
        feature_kind="place",
        label="kor-travel-concierge YouTube 장소 후보",
        is_feature_load=True,
    ),
    # ── data.go.kr fileData curated (python-datagokr-api) ────────────────
    *_DATAGOKR_FILEDATA_ENTRIES,
    # ── 문화체육관광부 파일데이터 (MCST) 13 slug ────────────────────────
    *_MCST_ENTRIES,
    # ── 국립공원공단 (KNPS) place + geometry ─────────────────────────────
    *_KNPS_ENTRIES,
)
"""시스템이 ETL 하는 전 provider×dataset 카탈로그 (단일 정본).

새 provider/dataset 추가 시 본 tuple에 1행(또는 provider dict 참조) 추가하면
`/etl`·`/ops/providers` 양쪽 메뉴에 자동 반영된다.
"""


def list_catalog_providers(*, feature_load_only: bool = False) -> list[str]:
    """카탈로그 provider canonical name 목록 (중복 제거, 정렬).

    Parameters
    ----------
    feature_load_only:
        True면 새 Feature를 적재하는 dataset이 1개라도 있는 provider만.
    """
    if feature_load_only:
        return sorted({e.provider for e in PROVIDER_DATASET_CATALOG if e.is_feature_load})
    return sorted({e.provider for e in PROVIDER_DATASET_CATALOG})


def catalog_datasets(provider: str) -> list[ProviderDatasetCatalogEntry]:
    """주어진 provider의 카탈로그 항목 (dataset_key 정렬)."""
    return sorted(
        (e for e in PROVIDER_DATASET_CATALOG if e.provider == provider),
        key=lambda e: e.dataset_key,
    )


def catalog_feature_load_entries() -> list[ProviderDatasetCatalogEntry]:
    """새 Feature를 적재하는 (FeatureBundle) 항목만, provider→dataset 정렬.

    WeatherValue/PriceValue/enrichment처럼 Feature를 만들지 않는 실행 단위는
    ``catalog_refreshable_entries``에서 다룬다.
    """
    return sorted(
        (e for e in PROVIDER_DATASET_CATALOG if e.is_feature_load),
        key=lambda e: (e.provider, e.dataset_key),
    )


def catalog_refreshable_entries() -> list[ProviderDatasetCatalogEntry]:
    """Dagster feature update request로 실행 가능한 항목만, provider→dataset 정렬."""
    return sorted(
        (e for e in PROVIDER_DATASET_CATALOG if e.is_refreshable),
        key=lambda e: (e.provider, e.dataset_key),
    )


def find_catalog_entry(provider: str, dataset_key: str) -> ProviderDatasetCatalogEntry | None:
    """``(provider, dataset_key)`` 항목 또는 ``None``."""
    for entry in PROVIDER_DATASET_CATALOG:
        if entry.provider == provider and entry.dataset_key == dataset_key:
            return entry
    return None
