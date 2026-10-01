"""산림청 산사태 예보를 map notice DTO로 정규화한다.

`python-krforest-api`는 provider typed model과 원문을 소유하고, 이 모듈은 그
모델을 notice `FeatureBundle`로 바꾸는 순수 변환만 담당한다. API 호출이나
provider wrapper는 두지 않는다.

산악기상(``krforest_mountain_weather``)과 산불위험예보
(``krforest_wildfire_risk_forecast``)는 weather kind라 ADR-105로 제거했다 — 날씨
정본은 kor-travel-weather다. 산사태 예보는 기상 원천이 아닌 산림청 재해 notice라
남는다.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Final, Protocol, runtime_checkable

from kortravelmap.core.ids import (
    make_feature_id,
    make_payload_hash,
    make_source_record_key,
)
from kortravelmap.core.providers import normalize_provider_name
from kortravelmap.dto import (
    Address,
    Feature,
    FeatureBundle,
    FeatureKind,
    NoticeDetail,
    SourceLink,
    SourceRecord,
    SourceRole,
)
from kortravelmap.dto.notice import NOTICE_TYPE_LANDSLIDE

__all__ = [
    "LANDSLIDE_FORECAST_DATASET_KEY",
    "LandslideForecastIssueItem",
    "LANDSLIDE_FORECAST_SOURCE_ENTITY_TYPE",
    "landslide_forecast_issues_to_bundles",
    "landslide_active_lineage_keys",
    "KRFOREST_PROVIDER_NAME",
]


KRFOREST_PROVIDER_NAME: Final[str] = "python-krforest-api"
LANDSLIDE_FORECAST_DATASET_KEY: Final[str] = "krforest_landslide_forecast_issues"

LANDSLIDE_FORECAST_SOURCE_ENTITY_TYPE: Final[str] = "landslide_forecast_issue"

FOREST_SAFETY_CATEGORY: Final[str] = "99000000"
LANDSLIDE_FORECAST_MARKER_ICON: Final[str] = "warning"
LANDSLIDE_FORECAST_MARKER_COLOR: Final[str] = "P-13"

_KST: Final[timezone] = timezone(timedelta(hours=9))


@runtime_checkable
class LandslideForecastIssueItem(Protocol):
    """`python-krforest-api`의 `LandslideForecastIssue` 입력 shape."""

    issue_kind_code: str | None
    issue_kind_name: str | None
    issuing_institution: str | None
    status: str | None
    issued_at: datetime | None
    raw: Mapping[str, Any]


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=_KST)


def _jsonable(value: object) -> Any:
    """provider raw/typed 값을 SourceRecord가 받을 JSON 값으로 만든다."""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return str(value)


def _raw_data(item: object, typed: Mapping[str, object]) -> dict[str, Any]:
    raw = getattr(item, "raw", {})
    raw_payload = _jsonable(raw if isinstance(raw, Mapping) else {})
    return {
        "provider_raw": raw_payload,
        "typed": {key: _jsonable(value) for key, value in typed.items()},
    }


def _source_record(
    *,
    dataset_key: str,
    source_entity_type: str,
    source_entity_id: str,
    raw_data: dict[str, Any],
    fetched_at: datetime,
) -> SourceRecord:
    payload_hash = make_payload_hash(raw_data)
    source_record_key = make_source_record_key(
        provider=KRFOREST_PROVIDER_NAME,
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
    )
    return SourceRecord(
        provider=normalize_provider_name(KRFOREST_PROVIDER_NAME),
        dataset_key=dataset_key,
        source_entity_type=source_entity_type,
        source_entity_id=source_entity_id,
        raw_payload_hash=payload_hash,
        raw_data=raw_data,
        fetched_at=fetched_at,
        source_record_key=source_record_key,
    )


def _landslide_key(item: LandslideForecastIssueItem) -> str:
    kind = _text(item.issue_kind_code) or _text(item.issue_kind_name) or "unknown"
    institution = _text(item.issuing_institution) or "unknown"
    raw = getattr(item, "raw", {})
    if isinstance(raw, Mapping):
        for field in (
            "issue_id",
            "issueId",
            "frstFrcstIssuNo",
            "발령번호",
            "발령ID",
            "seq",
            "id",
        ):
            raw_id = _text(raw.get(field))
            if raw_id is not None:
                return f"{kind}::{institution}::{raw_id}"
    # status는 같은 issue의 발령→해제 전이를 같은 Feature에 남겨야 하므로
    # 자연키에서 제외한다. provider의 first-issue time은 별도 사건을
    # 분리할 수 있는 유일한 typed 식별자이므로 fallback identity에 포함한다.
    issued_at = _aware(item.issued_at)
    issued_key = issued_at.isoformat() if issued_at is not None else "unknown"
    return f"{kind}::{institution}::{issued_key}"


def _landslide_is_active(item: LandslideForecastIssueItem) -> bool:
    status = (_text(item.status) or "").lower()
    if not status or any(
        token in status for token in ("해제", "종료", "해소", "취소", "release", "close")
    ):
        return False
    return any(
        token in status
        for token in ("발령", "발효", "유지", "active", "issued", "ongoing", "warning", "alert")
    )


def _landslide_typed(item: LandslideForecastIssueItem) -> dict[str, object]:
    return {
        "issue_kind_code": item.issue_kind_code,
        "issue_kind_name": item.issue_kind_name,
        "issuing_institution": item.issuing_institution,
        "status": item.status,
        "issued_at": item.issued_at,
    }


def landslide_forecast_issues_to_bundles(
    items: Iterable[LandslideForecastIssueItem],
    *,
    fetched_at: datetime,
) -> list[FeatureBundle]:
    """산사태 예보발령·해제 row를 notice snapshot bundle로 만든다."""

    selected = _select_landslide_items(items)
    bundles: list[FeatureBundle] = []
    for natural_key, item in selected.items():
        issued_at = _aware(item.issued_at) or fetched_at
        name = _text(item.issue_kind_name) or _text(item.issue_kind_code) or "산사태 예보"
        raw_data = _raw_data(item, _landslide_typed(item))
        source_record = _source_record(
            dataset_key=LANDSLIDE_FORECAST_DATASET_KEY,
            source_entity_type=LANDSLIDE_FORECAST_SOURCE_ENTITY_TYPE,
            source_entity_id=natural_key,
            raw_data=raw_data,
            fetched_at=fetched_at,
        )
        feature_id = make_feature_id(
            bjd_code=None,
            kind=FeatureKind.NOTICE.value,
            category=FOREST_SAFETY_CATEGORY,
            source_type=f"{KRFOREST_PROVIDER_NAME}:{LANDSLIDE_FORECAST_DATASET_KEY}",
            source_natural_key=natural_key,
        )
        active = _landslide_is_active(item)
        feature = Feature(
            feature_id=feature_id,
            provider_natural_key=natural_key,
            kind=FeatureKind.NOTICE,
            name=name,
            coord=None,
            # **상류가 주는 단 하나의 위치 단서를 버리면 안 된다.**
            #
            # 이 dataset의 상류 row에는 필드가 일곱 개뿐이고 그중 위치를 말하는 것은
            # `ocrnFrcstIssuInsttNm` 하나다. 2026-09-19에 10,562건을 전수로 재 보니
            # 97%가 "충청남도 당진시"처럼 **시도+시군구**이고, 시도만 0.6%,
            # 시도+연구소명("경기도 산림환경연구소")이 0.1%, 빈 값이 1.5%였다.
            # 즉 98.5%가 행정구역을 말한다.
            #
            # 그런데 여기가 `Address()`를 넣는 바람에 `_provider_address`가 `None`이
            # 되고, 적재기는 "좌표와 provider 주소가 모두 없음"으로 **전량을 버렸다**
            # (prod 실측: 10,467건 전부 `missing_address`, notice feature 0건,
            # 그런데 job은 SUCCESS). 좌표가 없는 row의 주소 단서를 `admin`에 남기는
            # 것은 이 저장소의 기존 관례다 — `providers/mcst.py`의 `_resolve_address`가
            # 같은 일을 하고, `dagster/validation.py`의 `_provider_address`는 그것을
            # 읽으려고 `road`→`legal`→`admin` 순서를 본다.
            #
            # 값은 **손대지 않고 그대로** 넣는다. 0.1%의 "경기도 산림환경연구소"를
            # 여기서 잘라 내면 provider가 말한 것과 다른 것을 저장하게 된다 —
            # 행정구역과의 불일치는 `_provider_address_region_issues`가 warning으로
            # 따로 센다. 빈 값 1.5%는 정말로 단서가 없으므로 계속 버려져야 한다.
            address=Address(admin=_text(item.issuing_institution)),
            category=FOREST_SAFETY_CATEGORY,
            marker_icon=LANDSLIDE_FORECAST_MARKER_ICON,
            marker_color=LANDSLIDE_FORECAST_MARKER_COLOR,
            detail=NoticeDetail(
                feature_id=feature_id,
                notice_type=NOTICE_TYPE_LANDSLIDE,
                    severity=2 if active else 0,
                    valid_start_time=issued_at,
                    valid_end_time=None if active else fetched_at,
                source_agency=_text(item.issuing_institution),
                payload={
                    "domain": "forest",
                    "issue_kind_code": item.issue_kind_code,
                    "issue_kind_name": item.issue_kind_name,
                    "status": item.status,
                    "active": active,
                    "issued_at": issued_at.isoformat(),
                    "closed_observed_at": None if active else fetched_at.isoformat(),
                    "provider_raw": raw_data["provider_raw"],
                },
            ),
        )
        bundles.append(
            FeatureBundle(
                feature=feature,
                source_record=source_record,
                source_link=SourceLink(
                    feature_id=feature_id,
                    source_record_key=source_record.source_record_key,
                    source_role=SourceRole.PRIMARY,
                    match_method="natural_key",
                    confidence=100,
                ),
            )
        )
    return bundles


def _select_landslide_items(
    items: Iterable[LandslideForecastIssueItem],
) -> dict[str, LandslideForecastIssueItem]:
    """같은 issue의 중복 응답 중 가장 최신 발령 시각을 선택한다."""

    selected: dict[str, LandslideForecastIssueItem] = {}
    for item in items:
        key = _landslide_key(item)
        current = selected.get(key)
        issued_at = _aware(item.issued_at)
        current_at = _aware(current.issued_at) if current is not None else None
        if current is None or (
            issued_at is not None and (current_at is None or issued_at >= current_at)
        ):
            selected[key] = item
    return selected


def landslide_active_lineage_keys(
    items: Iterable[LandslideForecastIssueItem],
) -> set[str]:
    """notice snapshot에서 발령 상태로 남길 lineage key를 계산한다."""

    return {
        _landslide_key(item)
        for item in _select_landslide_items(items).values()
        if _landslide_is_active(item)
    }
