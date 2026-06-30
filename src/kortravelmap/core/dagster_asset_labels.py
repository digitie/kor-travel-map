"""Dagster asset 한국어 표시명 상수."""

from __future__ import annotations

from typing import Final

DAGSTER_ASSET_KOREAN_LABELS: Final[dict[str, str]] = {
    "feature_event_datagokr_cultural_festivals": "전국 문화축제",
    "feature_place_opinet_stations": "주유소 위치",
    "feature_price_opinet_stations": "주유소 가격",
    "feature_place_krex_rest_areas": "고속도로 휴게소",
    "feature_price_krex_rest_areas": "휴게소 유가",
    "feature_notice_krex_traffic_notices": "고속도로 교통공지",
    "feature_weather_krex_rest_areas": "휴게소 기상",
    "feature_place_krheritage_items": "국가유산",
    "feature_event_krheritage_events": "국가유산 행사",
    "feature_place_mois_licenses": "인허가 장소",
    "feature_place_knps_points": "국립공원 지점",
    "feature_geometry_knps_records": "국립공원 경로/구역",
    "feature_place_krforest_recreation_forests": "자연휴양림",
    "feature_place_krforest_arboretums": "수목원",
    "feature_place_standard_museums": "박물관/미술관",
    "feature_place_standard_tourist_attractions": "관광지",
    "feature_place_standard_parking_lots": "주차장",
    "feature_place_standard_special_streets": "지역특화거리",
    "feature_place_datagokr_file_data": "공공 파일 장소",
    "feature_place_khoa_beaches": "해수욕장",
    "feature_place_krairport_airports": "공항",
    "feature_place_kor_travel_concierge_youtube": "영상 기반 장소 후보",
    "feature_event_visitkorea_enrichment": "VisitKorea 축제 보강 후보",
    "feature_weather_airkorea_air_quality": "대기질",
    "feature_weather_kma_ultra_short_nowcast": "기상청 초단기실황",
    "feature_weather_kma_ultra_short_forecast": "기상청 초단기예보",
    "feature_weather_kma_short_forecast": "기상청 단기예보",
    "feature_weather_kma_mid_forecast": "기상청 중기예보",
    "feature_notice_kma_weather_alerts": "기상특보",
    "feature_place_mcst_culture": "문화시설 파일데이터",
    "curated_source_metadata": "큐레이션 원천 메타데이터",
    "curated_feature_candidates": "큐레이션 후보 생성",
    "curated_feature_status_sweep": "큐레이션 상태 정리",
    "curated_feature_detail_snapshots": "큐레이션 상세 스냅샷",
}
"""asset code-level name → 한국어 표시명."""
