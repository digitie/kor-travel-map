"""provider ``Protocol`` ↔ 실모델 결박 선언 (ADR-006 구조 Protocol의 정본 표).

ADR-006에 따라 본 저장소는 provider wrapper/adapter를 만들지 않고, 입력 shape을
structural ``Protocol``로만 선언한다. 런타임 결선은 ``importlib.import_module()`` +
``cast(Any, ...)``이라 **어떤 정적 검사도 Protocol과 실모델의 결박을 보지 못한다.**
그래서 종전에는 그 결박이 각 모듈 docstring의 산문에만 있었다.

    ``KrHeritageItem``은 provider 실모델 ``krheritage.models.HeritageDetail``을
    **필드명 그대로** 만족한다

산문은 provider가 필드를 지워도 아무것도 실패시키지 못한다. 실제로
``HeritageDetail.manager`` 삭제는 mypy·import-linter·단위 테스트를 모두 통과한 채
live/Dagster 경로에서만 터졌다(단위 테스트가 자체 fake dataclass를 쓰기 때문이다).

본 모듈은 그 산문을 **기계가 읽는 선언**으로 옮긴다.
``tests/lint/test_provider_protocol_conformance.py``가 이 표와
``_provider_surface.json``(핀된 SHA의 provider 표면)을 대조한다.

두 표는 **전수**여야 한다 — ``providers/`` 안의 모든 ``Protocol``은 정확히 한쪽에만
있어야 하고, 어느 쪽에도 없으면 게이트가 실패한다. 새 Protocol이 선언 없이 조용히
끼어들 수 없다는 뜻이다.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final

PROVIDER_MODEL_BINDINGS: Final[Mapping[str, str]] = {
    # ``kortravelmap.providers`` 모듈.Protocol → provider 패키지의 실모델 경로.
    "airkorea.AirQualityStationItem": "airkorea.models.Station",
    "airkorea.AirQualityMeasurementItem": "airkorea.models.AirQualityMeasurement",
    "datagokr_file_data.DataGoKrFileDataRecord": "datagokr.models.PublicFileDataRecord",
    "khoa.OceanBeachInfoItem": "khoa.models.OceanBeachInfo",
    "knps.KnpsPointRecord": "knps.models.KnpsPlaceRecord",
    "knps.KnpsGeometryRecord": "knps.models.KnpsGeoRecord",
    "knps.KnpsCsvRow": "knps.models.CsvPreviewRow",
    "knps.KnpsCsvPreview": "knps.models.CsvPreview",
    "krairport.AirportMetadataItem": "krairport.models.AirportMetadata",
    "krex.KrexRestAreaItem": "krex.models.RestArea",
    "krex.KrexRestAreaFuelPriceRecord": "krex.models.RestAreaFuelPrice",
    "krex.KrexRestAreaWeatherRecord": "krex.models.RestAreaWeather",
    "krex.KrexTrafficNoticeItem": "krex.models.Incident",
    "krforest.RecreationForestItem": "krforest.models.StandardRecreationForest",
    "krforest.ForestSpatialItem": "krforest.models.ForestSpatialPoint",
    "krforest.ForestTrailItem": "krforest.models.ForestSpatialFeature",
    "krforest_safety.MountainWeatherItem": "krforest.models.MountainWeather",
    "krforest_safety.WildfireRiskForecastItem": "krforest.models.WildfireRiskForecast",
    "krforest_safety.LandslideForecastIssueItem": "krforest.models.LandslideForecastIssue",
    "krheritage.KrHeritageItemKey": "krheritage.models.heritage.HeritageKey",
    "krheritage.KrHeritageItem": "krheritage.models.heritage.HeritageDetail",
    "krheritage.KrHeritageEvent": "krheritage.models.event.HeritageEvent",
    "mois.MoisLicensePlaceRecord": "mois.db.PlaceRecord",
    "opinet.OpinetStationItem": "opinet.models.Station",
    "opinet.OpinetStationPriceItem": "opinet.models.Station",
    "opinet.OpinetStationDetailPriceItem": "opinet.models.OilPrice",
    "opinet.OpinetStationDetailItem": "opinet.models.StationDetail",
    "standard_data.CulturalFestivalItem": "datagokr.models.PublicCulturalFestival",
    "standard_data.PublicMuseumArtItem": "datagokr.models.PublicMuseumArtGallery",
    "standard_data.PublicTouristAttractionItem": "datagokr.models.PublicTouristAttraction",
    "standard_data.PublicParkingLotItem": "datagokr.models.PublicParkingLot",
    "standard_data.PublicSpecialStreetItem": "datagokr.models.PublicSpecialStreet",
    "visitkorea.VisitKoreaFestivalItem": "visitkorea.models.TourItem",
}
"""provider 실모델이 **직접** 만족해야 하는 Protocol.

값은 ``_provider_surface.json``의 클래스 키와 같은 형식(``패키지.모듈.클래스``)이다.
게이트는 Protocol이 요구하는 모든 멤버가 그 클래스 표면에 있는지 확인한다.
"""


PROTOCOLS_WITHOUT_PROVIDER_MODEL: Final[Mapping[str, str]] = {
    # provider 모델이 직접 만족하지 않는 Protocol과 그 사유.
    # 사유 없이 여기에 넣는 것은 게이트를 무력화하는 것과 같다 — 반드시 근거를 적는다.
    "kma.KmaShortForecastItem": (
        "provider ``ForecastItem``의 typed 필드가 아니라 ``item.raw`` dict 키를 읽어 "
        "Dagster ``KmaForecastRow``를 만든다(kma_weather.forecast_rows_from_items). "
        "결박 대상은 모델 속성이 아니라 raw 키라 표면 대조가 성립하지 않는다."
    ),
    "kma.KmaUltraShortNowcastItem": (
        "``WeatherSnapshot.raw['items']`` dict에서 Dagster ``KmaNowcastRow``를 만든다"
        "(kma_weather.nowcast_rows_from_snapshot). 위와 같은 사유."
    ),
    "kma.KmaUltraShortForecastItem": "``KmaShortForecastItem``과 같은 raw 기반 row 경로.",
    "kma.KmaWeatherAlertRegion": "특보 지역 — Map이 파싱해 만드는 중첩 shape.",
    "kma.KmaWeatherAlertItem": (
        "provider ``WeatherWarningItem``을 Map이 alert 도메인 shape으로 재구성한다. "
        "필드명이 provider와 1:1이 아니다."
    ),
    "kma.KmaMidLandForecastItem": (
        "중기육상예보 — provider ``MidForecastItem``의 단일 행을 Map이 "
        "``rn_st_*`` 등 확장 필드로 펼친 shape."
    ),
    "kma.KmaMidTemperatureItem": "중기기온예보 — 위와 같은 펼침 shape(``ta_max_*``/``ta_min_*``).",
    "krex.KrexRestAreaPriceItem": (
        "etl_live fixture 전용 narrow row. 실 Dagster 경로는 "
        "``KrexRestAreaFuelPriceRecord``(provider ``RestAreaFuelPrice``)를 쓴다."
    ),
    "krex.KrexRestAreaWeatherItem": (
        "etl_live fixture 전용 melt된 narrow row(1 metric/1행). 실 Dagster 경로는 "
        "wide row인 ``KrexRestAreaWeatherRecord``(provider ``RestAreaWeather``)를 쓴다."
    ),
    "opinet.OpinetPriceItem": (
        "``uni_id``/``prodcd``/``trade_dt`` — provider 모델에 없는 이름이고 "
        "현재 소비자는 ``kortravelmap.api.etl_fixtures``뿐이다. 실 provider 경로는 "
        "``OpinetStationPriceItem``/``OpinetStationDetailPriceItem``을 쓴다."
    ),
    "visitkorea.FestivalMatch": "Map 내부 매칭 결과 shape — provider 모델이 아니다.",
    "visitkorea.FestivalMatcher": "Map이 주입받는 매처 콜백 shape — provider 모델이 아니다.",
}
"""provider 실모델과 결박되지 않는 Protocol과 그 사유.

두 부류다.

1. provider 모델의 ``raw`` dict를 읽어 Map이 자체 row를 만드는 경로(kma 전부).
   이 경계의 취약점은 **모델 속성이 아니라 raw 키**이며 본 게이트의 대상이 아니다.
2. fixture 전용 shape(krex narrow row, ``OpinetPriceItem``).
"""
