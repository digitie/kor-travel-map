from __future__ import annotations

from dataclasses import dataclass

DATA_GO_KR_STANDARD_PROVIDER = "data.go.kr-standard"

STANDARD_TOURISM_ROADS = "standard_tourism_roads"
STANDARD_MUSEUMS = "standard_museums"
STANDARD_PARKING_LOTS = "standard_parking_lots"
STANDARD_TOURIST_SITES = "standard_tourist_sites"
STANDARD_CULTURAL_FESTIVALS = "standard_cultural_festivals"


@dataclass(frozen=True, slots=True)
class StandardDatasetSpec:
    dataset_key: str
    dataset_id: str
    title: str
    endpoint_url: str
    portal_url: str
    feature_kind: str
    source_entity_type: str
    official_refresh_cycle: str
    metadata_probe_interval_days: int
    full_scan_interval_days: int
    request_fields: tuple[str, ...]
    output_fields: tuple[str, ...]


STANDARD_DATASET_SPECS: dict[str, StandardDatasetSpec] = {
    STANDARD_TOURISM_ROADS: StandardDatasetSpec(
        dataset_key=STANDARD_TOURISM_ROADS,
        dataset_id="15017321",
        title="전국길관광정보표준데이터",
        endpoint_url="https://api.data.go.kr/openapi/tn_pubr_public_stret_tursm_info_api",
        portal_url="https://www.data.go.kr/data/15017321/standard.do",
        feature_kind="route",
        source_entity_type="tourism_road",
        official_refresh_cycle="annual",
        metadata_probe_interval_days=30,
        full_scan_interval_days=365,
        request_fields=(
            "stretNm",
            "stretIntrcn",
            "stretLt",
            "reqreTime",
            "beginSpotNm",
            "beginRdnmadr",
            "beginLnmadr",
            "endSpotNm",
            "endRdnmadr",
            "endLatitude",
            "coursInfo",
            "phoneNumber",
            "institutionNm",
            "referenceDate",
            "instt_code",
            "instt_nm",
        ),
        output_fields=(
            "stretNm",
            "stretIntrcn",
            "stretLt",
            "reqreTime",
            "beginSpotNm",
            "beginRdnmadr",
            "beginLnmadr",
            "endSpotNm",
            "endRdnmadr",
            "endLatitude",
            "coursInfo",
            "phoneNumber",
            "institutionNm",
            "referenceDate",
            "instt_code",
            "instt_nm",
        ),
    ),
    STANDARD_MUSEUMS: StandardDatasetSpec(
        dataset_key=STANDARD_MUSEUMS,
        dataset_id="15017323",
        title="전국박물관미술관정보표준데이터",
        endpoint_url="https://api.data.go.kr/openapi/tn_pubr_public_museum_artgr_info_api",
        portal_url="https://www.data.go.kr/data/15017323/standard.do",
        feature_kind="place",
        source_entity_type="museum_art_gallery",
        official_refresh_cycle="annual",
        metadata_probe_interval_days=30,
        full_scan_interval_days=365,
        request_fields=(
            "fcltyNm",
            "fcltyType",
            "rdnmadr",
            "lnmadr",
            "latitude",
            "longitude",
            "operPhoneNumber",
            "operInstitutionNm",
            "homepageUrl",
            "fcltyInfo",
            "weekdayOperOpenHhmm",
            "weekdayOperColseHhmm",
            "holidayOperOpenHhmm",
            "holidayCloseOpenHhmm",
            "rstdeInfo",
            "adultChrge",
            "yngbgsChrge",
            "childChrge",
            "etcChrgeInfo",
            "fcltyIntrcn",
            "trnsportInfo",
            "phoneNumber",
            "institutionNm",
            "referenceDate",
            "instt_code",
        ),
        output_fields=(),
    ),
    STANDARD_PARKING_LOTS: StandardDatasetSpec(
        dataset_key=STANDARD_PARKING_LOTS,
        dataset_id="15012896",
        title="전국주차장정보표준데이터",
        endpoint_url="https://api.data.go.kr/openapi/tn_pubr_prkplce_info_api",
        portal_url="https://www.data.go.kr/data/15012896/standard.do",
        feature_kind="place",
        source_entity_type="parking_lot",
        official_refresh_cycle="semiannual",
        metadata_probe_interval_days=30,
        full_scan_interval_days=180,
        request_fields=(
            "prkplceNo",
            "prkplceNm",
            "prkplceSe",
            "prkplceType",
            "rdnmadr",
            "lnmadr",
            "prkcmprt",
            "operDay",
            "parkingchrgeInfo",
            "phoneNumber",
            "latitude",
            "longitude",
            "pwdbsPpkZoneYn",
            "referenceDate",
            "instt_code",
            "instt_nm",
        ),
        output_fields=(),
    ),
    STANDARD_TOURIST_SITES: StandardDatasetSpec(
        dataset_key=STANDARD_TOURIST_SITES,
        dataset_id="15021141",
        title="전국관광지정보표준데이터",
        endpoint_url="https://api.data.go.kr/openapi/tn_pubr_public_trrsrt_api",
        portal_url="https://www.data.go.kr/data/15021141/standard.do",
        feature_kind="place",
        source_entity_type="tourist_site",
        official_refresh_cycle="annual",
        metadata_probe_interval_days=30,
        full_scan_interval_days=365,
        request_fields=(
            "trrsrtNm",
            "trrsrtSe",
            "rdnmadr",
            "lnmadr",
            "latitude",
            "longitude",
            "ar",
            "cnvnncFclty",
            "stayngInfo",
            "mvmAmsmtFclty",
            "recrtClturFclty",
            "hospitalityFclty",
            "sportFclty",
            "appnDate",
            "aceptncCo",
            "prkplceCo",
            "trrsrtIntrcn",
            "phoneNumber",
            "institutionNm",
            "referenceDate",
            "instt_code",
        ),
        output_fields=(),
    ),
    STANDARD_CULTURAL_FESTIVALS: StandardDatasetSpec(
        dataset_key=STANDARD_CULTURAL_FESTIVALS,
        dataset_id="15013104",
        title="전국문화축제표준데이터",
        endpoint_url="https://api.data.go.kr/openapi/tn_pubr_public_cltur_fstvl_api",
        portal_url="https://www.data.go.kr/data/15013104/standard.do",
        feature_kind="event",
        source_entity_type="cultural_festival",
        official_refresh_cycle="quarterly",
        metadata_probe_interval_days=7,
        full_scan_interval_days=30,
        request_fields=(
            "fstvlNm",
            "opar",
            "fstvlStartDate",
            "fstvlEndDate",
            "fstvlCo",
            "mnnstNm",
            "auspcInsttNm",
            "suprtInsttNm",
            "phoneNumber",
            "homepageUrl",
            "relateInfo",
            "rdnmadr",
            "lnmadr",
            "latitude",
            "longitude",
            "referenceDate",
            "instt_code",
            "instt_nm",
        ),
        output_fields=(),
    ),
}


def standard_dataset_spec(dataset_key: str) -> StandardDatasetSpec:
    try:
        return STANDARD_DATASET_SPECS[dataset_key]
    except KeyError as exc:
        raise ValueError(f"Unsupported standard dataset: {dataset_key}") from exc


def standard_dataset_specs() -> tuple[StandardDatasetSpec, ...]:
    return tuple(STANDARD_DATASET_SPECS.values())
