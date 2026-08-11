"""Dagster ETL 적재 전 좌표/주소 정합성 검증."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from kortravelmap.dto import FeatureBundle

IssueSeverity = Literal["error", "warning"]

DROPPABLE_ISSUE_CODES: Final[frozenset[str]] = frozenset(
    {"reverse_geocode_failed", "missing_address"}
)
"""영구 손실(drop)·run 실패를 일으킬 수 있는 issue code **화이트리스트** (T-VN-H28B).

이전에는 severity가 ``error``이기만 하면 code와 무관하게 drop됐다. 그래서 새 error 하나가
추가될 때마다 drop 정책이 조용히 넓어졌고, 실제로 ``provider_address_mismatch``가 그렇게
1,477건 중 380건을 영구 파괴했다.

그 380건을 두고 초안은 *"전부 오탐"*이라 적었으나 **근거가 tautology였다** — concierge
payload의 행정코드는 같은 좌표로 같은 geo reverse를 호출한 **캐시**라 항상 일치한다.
유효한 결론은 독립 축(provider ``Address.sigungu_name`` 대조 + 정지오코딩)으로 재수립한
"기존 규칙으로 **좌표 오류가 성립한 건 0건**"이다. 어느 쪽이든 **영구 drop이 과했다**는
이 화이트리스트의 근거는 그대로다.

이제 drop 대상은 여기 **명시된 code만**이다. 다른 검증이 error를 내더라도 이 집합을 고치는
별도 변경 없이는 데이터가 사라지지 않는다. 두 code는 위치 단서 자체가 없어 적재해도 의미가
없는 경우다.
"""


@dataclass(frozen=True)
class FeatureAddressIssue:
    """주소/좌표 검증 issue 1건."""

    feature_id: str
    source_record_key: str
    code: str
    severity: IssueSeverity
    message: str
    provider_address: str | None = None
    bjd_code: str | None = None
    sigungu_code: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {
            "feature_id": self.feature_id,
            "source_record_key": self.source_record_key,
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "provider_address": self.provider_address,
            "bjd_code": self.bjd_code,
            "sigungu_code": self.sigungu_code,
        }


@dataclass(frozen=True)
class FeatureAddressValidation:
    """한 ``FeatureBundle``의 주소/좌표 검증 결과."""

    feature_id: str
    source_record_key: str
    issue_codes: tuple[str, ...]
    issues: tuple[FeatureAddressIssue, ...]

    @property
    def has_errors(self) -> bool:
        return any(issue.severity == "error" for issue in self.issues)


@dataclass(frozen=True)
class FeatureAddressValidationSummary:
    """batch 주소/좌표 검증 요약."""

    total: int
    issue_count: int
    error_count: int
    warning_count: int
    issues: tuple[FeatureAddressIssue, ...]
    evidence_grade_counts: dict[str, int] = field(default_factory=dict)
    """행정코드 교차검증 **커버리지** (T-VN-H28B).

    ``dual``만 실제로 판정된 건수다. ``claim_only``/``obs_only``/``none``/``unarmed``는
    "통과"가 아니라 **판정하지 못함**이다. 이 집계가 없으면 침묵을 통과로 착각하게 된다.
    """
    name_state_counts: dict[str, int] = field(default_factory=dict)
    """독립 이름축 판정 상태(``matched``/``disagreed``/판정 불가 사유) 집계."""

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    @property
    def blocking_issues(self) -> tuple[FeatureAddressIssue, ...]:
        """``drop`` 모드에서 영구 격리할 issue만."""
        return tuple(
            issue
            for issue in self.issues
            if issue.severity == "error" and issue.code in DROPPABLE_ISSUE_CODES
        )

    @property
    def has_blocking_errors(self) -> bool:
        return bool(self.blocking_issues)

    def as_metadata(self) -> dict[str, int | list[dict[str, str | None]] | dict[str, int]]:
        return {
            "address_validation_total": self.total,
            "address_validation_issue_count": self.issue_count,
            "address_validation_error_count": self.error_count,
            "address_validation_warning_count": self.warning_count,
            "address_validation_issues": [issue.as_dict() for issue in self.issues],
            "address_validation_evidence_grades": dict(self.evidence_grade_counts),
            "address_validation_name_states": dict(self.name_state_counts),
        }


def validate_feature_bundle_address(
    bundle: FeatureBundle,
) -> FeatureAddressValidation:
    """FeatureBundle 1건의 좌표/주소 보강 상태를 검증한다.

    정책은 ``docs/architecture/address-geocoding.md``의 ADR-046 주소 정본 규칙을 따른다.
    좌표가 있는 feature는 kor-travel-geo reverse 결과로 ``bjd_code``가 있어야 한다.
    provider 주소 문자열이 있으면 reverse 결과의 시군구명과 같은 행정권인지
    보수적으로 확인한다.
    """
    feature = bundle.feature
    address = feature.address
    provider_address = _provider_address(bundle)
    issues: list[FeatureAddressIssue] = []

    # T-VN-H28B: reverse 실패 판정은 "bjd가 비었는가"가 아니라 "reverse가 실제로 값을
    # 냈는가"로 한다. provider payload가 bjd를 실어 주면(concierge는 1,477/1,477) 예전
    # 조건은 **영원히 거짓**이 되어, kor-travel-geo가 run 내내 죽어 있어도 전량이 좌표
    # 검증 없이 적재된다. AdminEvidence.obs_code가 reverse 성공 여부를 직접 말해 준다.
    evidence = bundle.admin_evidence

    if (
        feature.coord is not None
        and evidence is not None
        and not evidence.reverse_attempted
    ):
        issues.append(
            FeatureAddressIssue(
                feature_id=feature.feature_id,
                source_record_key=bundle.source_record.source_record_key,
                code="reverse_geocode_not_attempted",
                severity="warning",
                message="좌표가 있지만 reverse geocoder가 결선되지 않아 검증을 시도하지 못함.",
                provider_address=provider_address,
                bjd_code=address.bjd_code,
                sigungu_code=address.sigungu_code,
            )
        )

    # T-VN-H28B: reverse가 결과를 못 냈어도 payload가 법정동코드를 실어 주면 위치 단서는
    # 남아 있다 — 그건 **저하**이지 손실 사유가 아니다. 이걸 error로 올리면 실측 105건이
    # 새로 drop되어, 이 task가 없애려던 바로 그 피해를 재생산한다.
    # 반대로 완전히 침묵하면 geo가 run 내내 죽어 있어도 전량이 무검증 적재된다(적대 리뷰
    # 지적). 그래서 **warning으로 드러내고 적재는 유지**한다.
    if (
        feature.coord is not None
        and evidence is not None
        and evidence.reverse_attempted
        and evidence.obs_code is None
        and address.bjd_code is not None
    ):
        issues.append(
            FeatureAddressIssue(
                feature_id=feature.feature_id,
                source_record_key=bundle.source_record.source_record_key,
                code="reverse_geocode_unavailable",
                severity="warning",
                message=(
                    "좌표 reverse가 결과를 내지 못해 좌표 기준 검증을 못 했다 "
                    "(provider 행정코드로 적재 — 좌표 정합성은 미확인)."
                ),
                provider_address=provider_address,
                bjd_code=address.bjd_code,
                sigungu_code=address.sigungu_code,
            )
        )

    if (
        feature.coord is not None
        and address.bjd_code is None
        and (
            evidence is None
            or (evidence.reverse_attempted and evidence.obs_code is None)
        )
    ):
        issues.append(
            FeatureAddressIssue(
                feature_id=feature.feature_id,
                source_record_key=bundle.source_record.source_record_key,
                code="reverse_geocode_failed",
                severity="error",
                message="좌표가 있지만 kor-travel-geo reverse 결과 법정동코드가 없음.",
                provider_address=provider_address,
                bjd_code=address.bjd_code,
                sigungu_code=address.sigungu_code,
            )
        )

    if feature.coord is None and not provider_address and address.bjd_code is None:
        issues.append(
            FeatureAddressIssue(
                feature_id=feature.feature_id,
                source_record_key=bundle.source_record.source_record_key,
                code="missing_address",
                severity="error",
                message="좌표와 provider 주소가 모두 없어 위치 정규화 단서가 없음.",
                provider_address=None,
                bjd_code=address.bjd_code,
                sigungu_code=address.sigungu_code,
            )
        )

    issues.extend(_provider_address_region_issues(bundle, provider_address))
    issues.extend(_admin_code_stale_issues(bundle, provider_address))

    return FeatureAddressValidation(
        feature_id=feature.feature_id,
        source_record_key=bundle.source_record.source_record_key,
        issue_codes=tuple(issue.code for issue in issues),
        issues=tuple(issues),
    )


def validate_feature_bundles_address(
    bundles: Iterable[FeatureBundle],
) -> FeatureAddressValidationSummary:
    """FeatureBundle batch의 좌표/주소 검증 요약."""
    materialized = list(bundles)
    validations = [validate_feature_bundle_address(bundle) for bundle in materialized]
    issues = tuple(issue for validation in validations for issue in validation.issues)
    error_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    grades: Counter[str] = Counter(
        "unarmed" if b.admin_evidence is None else str(b.admin_evidence.grade)
        for b in materialized
    )
    name_states: Counter[str] = Counter(
        _provider_address_name_state(b, _provider_address(b)) for b in materialized
    )
    return FeatureAddressValidationSummary(
        total=len(validations),
        issue_count=len(issues),
        error_count=error_count,
        warning_count=warning_count,
        evidence_grade_counts=dict(grades),
        name_state_counts=dict(name_states),
        issues=issues,
    )


def ensure_feature_address_valid(
    bundles: Iterable[FeatureBundle],
) -> FeatureAddressValidationSummary:
    """검증 error가 있으면 ``ValueError``로 중단한다."""
    summary = validate_feature_bundles_address(bundles)
    if summary.has_errors:
        error_issues = tuple(
            issue for issue in summary.issues if issue.severity == "error"
        )
        codes = ", ".join(issue.code for issue in error_issues)
        raise ValueError(f"Feature 주소/좌표 검증 실패: {codes}")
    return summary


def _provider_address(bundle: FeatureBundle) -> str | None:
    """이 bundle이 주장하는 **주소 문자열**. 주장이 없으면 ``None``.

    ``None``과 문자열의 경계가 이 모듈의 여러 판정을 가른다 — ``missing_address``
    (droppable error)는 여기가 ``None``일 때만 발화하고, 독립 이름축은 여기가 문자열일
    때만 판정한다. 그래서 "값이 없다"가 절대 문자열로 새면 안 된다
    (``_clue_text`` docstring).

    우선순위는 provider 원 payload → ``Address``의 텍스트다. ``Address`` 쪽은
    ``road`` → ``legal`` → ``admin``으로, ``Address.display()``와 같은 순서다.
    ``admin``까지 보는 이유는 mcst가 좌표 없는 row의 provider 주소를 거기에만 남기기
    때문이다(``providers/mcst.py`` ``_resolve_address`` — ``road``/``legal``을 채우지
    않는다). ``admin``을 빼면 골프장 현황처럼 좌표가 없는 dataset 전체가 "단서 없음"이
    되어 ``missing_address``로 영구 drop된다.

    **독립성 한계**: 뒤 둘은 provider가 원 주소를 옮겨 담은 값일 수도 있고, reverse가
    채운 값일 수도 있다. ``Address``만 보고는 출처를 구분할 수 없으므로, payload 주소
    키가 없는 provider에서는 이름축이 geo 결과끼리 비교하는 형태로 약해질 수 있다
    (그때는 늘 ``matched``로 조용하다 — 오탐이 아니라 **탐지력 상실**이다).
    provider 원천임이 보장되는 문자열은 ``AdminEvidence.claim_text``뿐이므로, 축을
    엄밀히 세우려면 그쪽으로 옮기는 별도 결정이 필요하다.

    그래서 payload의 **교통 단서**(노선/지점/방향)는 ``_raw_payload_address`` 안에서만
    마지막이고, ``Address`` 텍스트보다는 여전히 **앞**이다 — 의도한 순서다. 교통 단서를
    ``Address`` 뒤로 미루면 krex 휴게소·휴게소기상·traffic notice가 ``Address.admin``을
    주장으로 삼는데, 세 dataset 모두 ``road=None``이고 ``admin``은 reverse가 채운
    값이라(``providers/krex`` ``_rest_area_item_to_bundle`` /
    ``_rest_area_weather_record_to_bundle`` / ``_traffic_notice_item_to_bundle``)
    geo를 geo와 대조하는 자기비교가 되어 이름축이 **거짓 ``matched``**로 조용해진다.
    ``no_token``으로 판정 불가를 드러내는 쪽이 낫다.

    **잔여 위험**(현재 dataset에는 해당 없음): provider가 진짜 주소를 열거되지 않은
    payload 키로만 주고 그 값이 ``Address``에만 남는데 payload에 교통 키까지 있는
    경우, 교통 단서가 그 주소를 가린다. 위 세 dataset이 유일한 교통 키 보유처이고
    셋 다 provider 주소 컬럼 자체가 없으므로 지금은 발생하지 않는다.
    """
    address = bundle.feature.address
    raw = _raw_payload_address(bundle.source_record.raw_data)
    if raw is not None:
        return raw
    return (
        _clue_text(address.road)
        or _clue_text(address.legal)
        or _clue_text(address.admin)
    )


def _clue_text(value: object) -> str | None:
    """payload 값 하나를 위치 단서 문자열로 정규화한다. 단서가 없으면 ``None``.

    ``None``을 절대 문자열로 만들지 않는다. ``str(None) == "None"``은 truthy라, 값이
    없다는 사실이 "주소 주장이 있다"로 뒤집힌다 — 이전 구현이 정확히 그래서 주소
    대조축 전체를 조용히 무력화했다.
    """
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


_RAW_ADDRESS_KEYS: Final[tuple[str, ...]] = (
    "address",
    "addr",
    "address_road",
    "road_address",
    "address_jibun",
    "lot_address",
    "rdnmadr",
    "lnmadr",
    "location_text",
    "region_name",
)
"""provider 원 payload에서 단일 주소 문자열로 인정하는 키.

**도로명이 지번보다 앞선다 — 단, 그 보증은 provider 계열 안에서 성립한다.** 평탄
튜플만 보면 지번 계열(``address_jibun``/``lot_address``)이 표준데이터 도로명
(``rdnmadr``)보다 앞서지만, 세 계열의 키는 서로 겹치지 않아 한 payload에 두 계열이
같이 오지 않는다(2026-08-11 실측: ``address_road``/``address_jibun`` = opinet,
``road_address``/``lot_address`` = mois, ``rdnmadr``/``lnmadr`` = standard_data).
계열이 섞이는 provider가 생기면 이 배열을 계열 무관하게 재정렬해야 한다 —
``test_admin_code_validation.py``가 계열별 우선순위를 못박는다.

``road_address``/``lot_address``는 mois 실측 payload 키다(``providers/mois._raw_data``).
정규화 패스가 없어도 맞아야 977k 레코드가 매번 정규화 dict를 만들지 않는다.
"""

_TRAFFIC_CLUE_KEYS: Final[tuple[tuple[str, ...], ...]] = (
    ("roadNM", "routeName", "nosunNM", "routeNo"),
    ("accPointNM", "pointName"),
    ("startEndTypeCode", "direction"),
)
"""고속도로 row의 노선/지점/방향 — 그룹별로 **먼저 채워진 하나**만 쓴다.

이 세 그룹은 **주소가 아니다.** 그래서 ``_raw_payload_address``에서 주소 키(원 철자
+ 정규화 철자) 조회가 전부 빈손일 때에만 마지막 수단으로 조립한다. 이 순서가 없으면
``direction`` 같은 흔한 키 하나가 철자만 다른 진짜 도로명 주소(``roadAddress``)를
가로챈다.

철자 출처는 둘 다 실측이다.

- EX 원 payload 철자 — ``python-krex-api`` ``client._incident``가 읽는
  ``roadNM``/``nosunNM``/``accPointNM``/``startEndTypeCode``. ``dict(item.raw)``를
  그대로 싣는 traffic notices(``providers/krex._traffic_notice_item_to_bundle``)가
  이 철자로 온다.
- typed 속성명 — ``providers/krex``가 **직접 조립하는** raw_data에는 오히려 이쪽이
  들어 있다: 휴게소 place는 ``route_name``/``direction``, 휴게소 기상은
  ``route_name``/``direction_code``. 위 열거는 원 철자만 담지만
  ``_normalized_key``가 ``routeName``↔``route_name``을 같은 키로 접으므로
  정규화 패스에서 잡힌다(``direction_code``는 어느 쪽으로도 안 잡힌다 — 방향
  조각이 빠질 뿐 다른 조각은 그대로다).

같은 필드라도 dataset마다 철자가 달라(``routeNo``/``routeName``) 열거만으로는
새므로, 아래 조회가 그룹마다 원 철자 → 정규화 철자 순으로 두 번 본다.
"""

_NON_KEY_CHARS: Final = re.compile(r"[^0-9a-z가-힣]")


def _normalized_key(key: str) -> str:
    """``routeNo``/``route_no``/``ROUTE-NO``를 같은 키로 본다."""
    return _NON_KEY_CHARS.sub("", key.lower())


_RAW_ADDRESS_KEYS_NORMALIZED: Final[tuple[str, ...]] = tuple(
    _normalized_key(key) for key in _RAW_ADDRESS_KEYS
)
_TRAFFIC_CLUE_KEYS_NORMALIZED: Final[tuple[tuple[str, ...], ...]] = tuple(
    tuple(_normalized_key(key) for key in group) for group in _TRAFFIC_CLUE_KEYS
)


def _first_clue(get: Callable[[str], object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        text = _clue_text(get(key))
        if text is not None:
            return text
    return None


def _normalized_view(raw_data: Mapping[str, object]) -> dict[str, object]:
    """철자를 접은 payload 사본. 먼저 나온 키가 이긴다."""
    normalized: dict[str, object] = {}
    for key, value in raw_data.items():
        folded = _normalized_key(key)
        if folded and folded not in normalized:
            normalized[folded] = value
    return normalized


def _raw_payload_address(raw_data: Mapping[str, object]) -> str | None:
    """원 provider payload에서만 주소 단서를 읽는다. 없으면 ``None``.

    ``SourceRecord``에는 표준화한 ``raw_address`` 복사본을 저장하지 않으므로, 원
    payload의 주소 필드 또는 고속도로 row의 원 노선/지점/방향 필드가 유일한 원천측
    단서다. 이 함수는 ``_load``의 모든 bundle에서 돌며(``etl.py`` →
    ``validate_feature_bundles_address``), ``Address``의 텍스트보다 **먼저** 쓰인다.

    KNPS처럼 ``dict(record.raw)``로 provider 원 필드명을 그대로 싣는 dataset은 여기
    나열한 키가 하나도 없을 수 있다. 그건 **주소 주장이 없는** 상태이지, 빈 조각을
    이어 붙여 주장을 만들 상황이 아니다 — 그때 ``None``을 돌려주어야 호출자의
    ``Address`` fallback이 발동한다.

    조회 순서는 **주소 → 교통 단서**이고, 각 단계 안에서 원 철자 → 정규화 철자다.
    단계와 철자를 이 순서로 겹치는 것이 핵심이다. 이전 구현은 "(주소+교통) 원 철자"
    한 패스를 먼저 돌고 실패할 때만 "(주소+교통) 정규화 철자"를 돌았는데, 그러면
    ``{"roadAddress": "서울특별시 종로구 통일로 251", "direction": "부산방향"}``에서
    원 철자 패스의 ``direction``이 먼저 걸려 **맨 방향 문자열이 진짜 도로명 주소를
    이겼다**. 교통 단서는 주소가 아니므로 언제나 마지막이다.

    철자 정규화가 필요한 이유는 provider가 같은 필드를 endpoint마다 다르게 쓰기
    때문이다 — ``python-krex-api``의 ``_get`` 자체가 ``conzoneId``/``conzoneID``,
    ``updTime``/``updateTime``/``updatedAt`` 같은 다중 철자를 흡수한다. 철자 하나를
    놓치면 좌표 없는 row가 통째로 "단서 없음"이 되어 ``missing_address``로 **영구
    drop**되므로, 키 목록을 늘리는 대신 철자 자체를 정규화한다.
    """
    direct = _first_clue(raw_data.get, _RAW_ADDRESS_KEYS)
    if direct is not None:
        return direct

    normalized = _normalized_view(raw_data)
    folded = _first_clue(normalized.get, _RAW_ADDRESS_KEYS_NORMALIZED)
    if folded is not None:
        return folded

    # 고속도로 row는 원천에 단일 주소 필드가 없다. 아래 세 원 필드는 각각 원
    # payload에서 보존되며, 검증 순간에만 위치 단서로 결합한다. 없는 조각은
    # 건너뛴다 — 자리를 채우지 않는다.
    parts: list[str] = []
    for exact_group, folded_group in zip(
        _TRAFFIC_CLUE_KEYS, _TRAFFIC_CLUE_KEYS_NORMALIZED, strict=True
    ):
        text = _first_clue(raw_data.get, exact_group) or _first_clue(
            normalized.get, folded_group
        )
        if text is not None:
            parts.append(text)
    return " ".join(parts) or None


_CLAIM_PRECISION: Final[dict[str, int]] = {
    "bjd": 10,
    "emd": 8,
    "sigungu": 5,
    "sido": 2,
}
"""``AdminEvidence.claim_kind``별 법정동코드 접두 비교 자리수."""

_MAX_COMPARE_PRECISION: Final = 8
"""리(8:10)는 비교하지 않는다.

``geocoding._bjd_code_from_emd_code``는 region fallback 경로에서 읍면동 8자리에 ``"00"``을
붙여 법정동코드를 **합성**한다. 0~8자리는 권위 있는 값이지만 마지막 2자리는 합성물일 수
있으므로, 8자리로 캡해 합성값을 판정 근거로 쓰지 않는다.
"""

_DIVERGENCE_LEVELS: Final[tuple[tuple[str, int, int], ...]] = (
    ("sido", 0, 2),
    ("sigungu", 2, 5),
    ("emd", 5, 8),
)


def _first_divergence_level(obs: str, claim: str, precision: int) -> str:
    """두 코드가 처음 갈라지는 행정 단계 이름."""
    for name, start, end in _DIVERGENCE_LEVELS:
        if end > precision:
            break
        if obs[start:end] != claim[start:end]:
            return name
    return "emd"


_ADMIN_NAME_TOKEN: Final = re.compile(
    r"(?<![가-힣])([가-힣]{1,4}(?:시|군|구))(?![가-힣])"
)
"""provider 주소의 독립된 2~5자 시/군/구 토큰.

상호명 내부 부분문자열(``종로김밥``)과 일반 명사(``현대미술전시``)는 행정구역 주장으로
오인하지 않는다.
"""

_REGION_SUFFIXES: Final = ("특별자치시", "특별자치도", "광역시", "특별시", "시", "군", "구")


def _region_stem(name: str) -> str:
    """``기장군`` → ``기장``. 같은 지역의 축약 표기를 같게 본다."""
    compact = _compact(name)
    for suffix in _REGION_SUFFIXES:
        if len(compact) > len(suffix) and compact.endswith(suffix):
            return compact[: -len(suffix)]
    return compact


def _compact(value: str) -> str:
    return "".join(str(value).split())


def _observed_region_stems(names: Iterable[str]) -> set[str]:
    stems: set[str] = set()
    for name in names:
        compact = _compact(name)
        stem = _region_stem(compact)
        if stem:
            stems.add(stem)
        for token in _ADMIN_NAME_TOKEN.findall(name):
            token_stem = _region_stem(token)
            if token_stem:
                stems.add(token_stem)
    return stems


def _provider_address_name_state(
    bundle: FeatureBundle,
    provider_address: str | None,
) -> Literal["matched", "disagreed", "no_token", "no_observation", "no_claim"]:
    """독립 이름축 판정 상태. 판정 불가 사유를 **서로 다른 값으로** 남긴다.

    - ``no_claim`` — 원 payload에도 ``Address``에도 주소 문자열이 없다. 축이 설 자리가
      없다.
    - ``no_observation`` — 주장은 있으나 대조할 reverse 시군구명이 없다(좌표 없음 또는
      geocoder 미결선).
    - ``no_token`` — 주장·관측이 모두 있으나 주장 문자열에 시/군/구 토큰이 없다
      (``부산 기장 조방국밥``). 실측 380건 중 375건이 이 형태였고, 이걸 불일치로 세다
      영구 drop을 냈다.
    - ``matched`` / ``disagreed`` — 실제 판정.

    ``no_claim``과 ``no_token``의 구분이 중요하다. 전자는 **원천에 주소가 없다**,
    후자는 **주소는 있는데 행정구역을 지목하지 않는다**로, 커버리지를 올리려면 손대야
    할 곳이 완전히 다르다. 이전 구현은 ``_provider_address``가 ``'None None None'``을
    돌려주는 바람에 ``no_claim``이 **한 건도 나올 수 없었다**. 그 row들이 대신 어디로
    갔는지는 아래 판정 순서 그대로 갈렸다 — 관측(reverse 시군구명)이 있으면
    ``no_token``, 없으면 ``no_observation``이다. 주소가 없다는 사실은 어느 쪽으로도
    드러나지 않았고, 두 지표는 서로 다른 방식으로 오염됐다.

    사유 판정 순서는 claim → observation → token이다. 관측과 토큰이 동시에 없으면
    ``no_observation``으로 집계된다 — 둘 다 없다는 사실까지 나누려면 상태를 더
    쪼개야 하므로, 여기서는 "가장 바깥 축부터" 한 가지 사유만 남긴다.
    """
    if not provider_address:
        return "no_claim"
    evidence = bundle.admin_evidence
    observed = list(evidence.obs_sigungu_names) if evidence is not None else []
    if not observed and bundle.feature.address.sigungu_name:
        observed.append(bundle.feature.address.sigungu_name)
    if not observed:
        return "no_observation"
    claim_tokens = _ADMIN_NAME_TOKEN.findall(provider_address)
    if not claim_tokens:
        return "no_token"
    claim_stems = {_region_stem(token) for token in claim_tokens}
    claim_stems.discard("")
    return (
        "matched"
        if claim_stems & _observed_region_stems(observed)
        else "disagreed"
    )


def _provider_address_region_issues(
    bundle: FeatureBundle,
    provider_address: str | None,
) -> tuple[FeatureAddressIssue, ...]:
    """provider가 **쓴 주소 문자열**과 좌표 reverse 행정구역명을 대조한다 (T-VN-H28B).

    이것이 "좌표가 주소와 다른 곳을 가리키는가"를 물을 수 있는 **유일한 독립 축**이다.
    payload 행정코드는 최소 concierge에서 같은 geo reverse의 캐시본이라 쓸 수 없다
    (``AdminEvidence`` 모듈 docstring).

    다만 이 문장은 **설계 의도이지 자동으로 보장되는 사실이 아니다.** T-VN-33 초판에서
    ``_raw_payload_address``가 ``str(None)``을 진리값으로 썼고, 그 결함은 **주소 키
    조회가 빈손이었을 때만** 발화했다 — 그 경우 교통 단서 조립이 없는 조각을
    ``'None'``으로 채워 ``'None None None'`` 같은 문자열을 주장으로 돌려주었고, 그
    값이 truthy라 호출자의 ``Address`` fallback까지 함께 막혔다. 그래서 피해 범위는
    **dataset마다 갈렸다**(payload 키를 직접 조사해 확인).

    - 축이 **살아 있던** dataset — 당시 열거하던 원 철자 키가 payload에 그대로 있었다:
      standard_data 5종(``rdnmadr``/``lnmadr``), krforest(``address``),
      krheritage place(``location_text``), airkorea 측정소(``addr``),
      kma 특보(``region_name``), opinet legacy fallback shape(``address_road``).
    - 축이 **죽어 있던** dataset — 열거 키와 철자가 달랐거나 아예 없었다:
      mois(``road_address``/``lot_address`` — 당시 목록은 ``address_road``/
      ``address_jibun``이었다), visitkorea(``addr1``), mcst 파일데이터(원 컬럼명 —
      kcisa 방언 ``ADDRESS``, 골프장 ``지역``/``소재지``), knps(원 헤더),
      opinet(provider raw row가 있으면 ``NEW_ADR``/``VAN_ADR``), khoa, krairport,
      kma 격자.
    - **부분 오염**: krex 휴게소/휴게소기상은 교통 키가 일부만 있어
      ``'경부고속도로 None 부산방향'``처럼 ``'None'`` 조각이 섞인 주장이 나왔다.

    즉 "이름축 finding 0건"은 전 dataset이 아니라 위 두 번째·세 번째 묶음에서 성립한
    현상이다. 축이 실제로 서 있는지는
    ``FeatureAddressValidationSummary.name_state_counts``의 ``matched``/``disagreed``
    건수로만 확인할 수 있다 — 침묵은 통과가 아니다. 주장 문자열의 출처가 provider인지
    geo인지에 대한 한계는 ``_provider_address`` docstring에 적었다.

    이전 규칙은 이 축을 쓰면서 셋을 틀렸고 그래서 1,477 후보 중 380건을 **영구 drop**했다
    (``docs/reports/concierge-address-mismatch-evidence-2026-07-29.md``).

    1. **행정구역 토큰이 없는 문자열을 불일치로 셌다.** 실측 375/380이 ``부산 기장 조방국밥``
       처럼 시/군/구 토큰이 아예 없어 부분문자열 검사가 좌표와 무관하게 통과 불가였다.
       → 토큰이 없으면 **판정하지 않는다**.
    2. **축약·단계 표기를 불일치로 셌다** (``기장`` vs ``기장군``, ``양구읍`` vs ``양구군``).
       → 어간(``_region_stem``)으로 비교한다.
    3. **경계 좌표를 불일치로 셌다.** 유일한 잔여 후보였던 ``서울 서대문구 통일로 251``은
       텍스트를 정지오코딩하면 서대문구이고 후보 좌표에서 **143m**였다(종로구 경계).
       → reverse **후보 전체**의 시군구명 중 하나와 맞으면 일치로 본다.

    severity는 ``warning``이며 drop allowlist에 없다 — 이 축으로는 데이터가 사라지지 않는다.
    """
    if _provider_address_name_state(bundle, provider_address) != "disagreed":
        return ()

    address = bundle.feature.address
    evidence = bundle.admin_evidence
    observed = list(evidence.obs_sigungu_names) if evidence is not None else []
    if not observed and address.sigungu_name:
        observed.append(address.sigungu_name)
    feature = bundle.feature
    return (
        FeatureAddressIssue(
            feature_id=feature.feature_id,
            source_record_key=bundle.source_record.source_record_key,
            code="provider_address_region_disagreement",
            severity="warning",
            message=(
                "provider 주소 문자열이 지목하는 행정구역이 좌표 reverse 후보"
                f"({', '.join(observed[:4])}) 어디에도 해당하지 않음."
            ),
            provider_address=provider_address,
            bjd_code=address.bjd_code,
            sigungu_code=address.sigungu_code,
        ),
    )


def _admin_code_stale_issues(
    bundle: FeatureBundle,
    provider_address: str | None,
) -> tuple[FeatureAddressIssue, ...]:
    """payload 행정코드가 좌표 reverse 결과와 어긋나는지 본다 — **staleness 검출** (T-VN-H28B).

    위치 검증이 **아니다**. concierge의 payload 코드는 같은 geo reverse를 같은 좌표로 호출해
    만든 캐시본이고, 그 producer는 코드가 이미 있으면 갱신하지 않는다. 따라서 불일치는
    "좌표가 틀렸다"가 아니라 **"캐시된 코드가 좌표 변경을 따라가지 못했다"**는 뜻이다.
    적재를 막지 않고 warning으로만 남긴다.
    """
    evidence = bundle.admin_evidence
    if evidence is None or evidence.grade != "dual":
        return ()

    obs = evidence.obs_code or ""
    claim = evidence.claim_code or ""
    kind = evidence.claim_kind or "bjd"
    precision = min(_MAX_COMPARE_PRECISION, _CLAIM_PRECISION[kind], len(claim), len(obs))
    if precision <= 0 or obs[:precision] == claim[:precision]:
        return ()

    feature = bundle.feature
    level = _first_divergence_level(obs, claim, precision)
    return (
        FeatureAddressIssue(
            feature_id=feature.feature_id,
            source_record_key=bundle.source_record.source_record_key,
            code=f"admin_code_stale_{level}",
            severity="warning",
            message=(
                f"payload 행정코드가 좌표 reverse 결과와 {level} 단계에서 다름 — "
                f"producer 캐시가 낡았을 수 있다 "
                f"(obs={obs[:precision]}, claim={claim[:precision]})."
            ),
            provider_address=provider_address,
            bjd_code=feature.address.bjd_code,
            sigungu_code=feature.address.sigungu_code,
        ),
    )
