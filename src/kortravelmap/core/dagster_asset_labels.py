"""Dagster asset 한국어 표시명 상수."""

from __future__ import annotations

from typing import Final

DAGSTER_ASSET_KOREAN_LABELS: Final[dict[str, str]] = {
    "feature_event_datagokr_cultural_festivals": "전국 문화축제",
    "feature_place_transport_fuel_stations": "주유소 위치",
    "feature_price_transport_fuel_stations": "주유소 가격",
    "feature_place_transport_rest_areas": "고속도로 휴게소",
    "feature_price_transport_rest_areas": "휴게소 유가",
    "feature_notice_transport_highway_incidents": "고속도로 교통공지",
    "feature_place_krheritage_items": "국가유산",
    "feature_event_krheritage_events": "국가유산 행사",
    "feature_place_mois_licenses": "인허가 장소",
    "feature_place_knps_points": "국립공원 지점",
    "feature_geometry_knps_records": "국립공원 경로/구역",
    "feature_place_krforest_recreation_forests": "자연휴양림",
    "feature_place_krforest_arboretums": "수목원",
    "feature_route_krforest_mountain_trails": "산림청 등산로",
    "feature_route_krforest_dulle_trails": "산림청 둘레길",
    "feature_notice_krforest_landslide_forecast_issues": "산림청 산사태 예보",
    "feature_place_standard_museums": "박물관/미술관",
    "feature_place_standard_tourist_attractions": "관광지",
    "feature_place_standard_parking_lots": "주차장",
    "feature_place_standard_special_streets": "지역특화거리",
    "feature_place_datagokr_file_data": "공공 파일 장소",
    "feature_place_khoa_beaches": "해수욕장",
    "feature_place_transport_airports": "공항",
    "feature_place_kor_travel_concierge_youtube": "영상 기반 장소 후보",
    "feature_event_visitkorea_enrichment": "VisitKorea 축제 보강 후보",
    "feature_place_mcst_culture": "문화시설 파일데이터",
}
"""asset code-level name → 한국어 표시명."""
