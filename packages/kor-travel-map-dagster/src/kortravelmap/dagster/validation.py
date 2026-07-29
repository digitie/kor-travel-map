"""Dagster ETL 적재 전 좌표/주소 정합성 검증."""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

    from kortravelmap.dto import FeatureBundle

IssueSeverity = Literal["error", "warning"]

DROPPABLE_ISSUE_CODES: Final[frozenset[str]] = frozenset(
    {"reverse_geocode_failed", "missing_address"}
)
"""영구 손실(drop)·run 실패를 일으킬 수 있는 issue code **화이트리스트** (T-VN-H28B).

이전에는 severity가 ``error``이기만 하면 code와 무관하게 drop됐다. 그래서 새 error 하나가
추가될 때마다 drop 정책이 조용히 넓어졌고, 실제로 ``provider_address_mismatch``가 그렇게
1,477건 중 380건을 영구 파괴했다(전부 오탐 — 위 리포트).

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

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    @property
    def blocking_issues(self) -> tuple[FeatureAddressIssue, ...]:
        """drop/실패를 일으키는 issue만 (``DROPPABLE_ISSUE_CODES`` 화이트리스트)."""
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
    reverse_produced_nothing = (
        address.bjd_code is None
        if evidence is None
        else evidence.obs_code is None
    )
    if feature.coord is not None and reverse_produced_nothing:
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
    grades = Counter(
        "unarmed" if b.admin_evidence is None else b.admin_evidence.grade
        for b in materialized
    )
    return FeatureAddressValidationSummary(
        total=len(validations),
        issue_count=len(issues),
        error_count=error_count,
        warning_count=warning_count,
        evidence_grade_counts=dict(grades),
        issues=issues,
    )


def ensure_feature_address_valid(
    bundles: Iterable[FeatureBundle],
) -> FeatureAddressValidationSummary:
    """검증 error가 있으면 ``ValueError``로 중단한다."""
    summary = validate_feature_bundles_address(bundles)
    # T-VN-H28B: load 경로와 같은 allowlist를 쓴다. 두 공개 진입점이 서로 다른 drop
    # 정책을 갖고 있으면 "allowlist를 고치기 전에는 손실 불가"라는 불변식이 깨진다.
    if summary.has_blocking_errors:
        codes = ", ".join(issue.code for issue in summary.blocking_issues)
        raise ValueError(f"Feature 주소/좌표 검증 실패: {codes}")
    return summary


def _provider_address(bundle: FeatureBundle) -> str | None:
    record = bundle.source_record
    address = bundle.feature.address
    raw = record.raw_address or address.road or address.legal
    if raw is None:
        return None
    normalized = " ".join(str(raw).split())
    return normalized or None


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


_ADMIN_NAME_TOKEN: Final = re.compile(r"[가-힣]+[시군구]")
"""provider 주소 문자열에서 시/군/구로 끝나는 행정구역 토큰."""

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


def _provider_address_region_issues(
    bundle: FeatureBundle,
    provider_address: str | None,
) -> tuple[FeatureAddressIssue, ...]:
    """provider가 **쓴 주소 문자열**과 좌표 reverse 행정구역명을 대조한다 (T-VN-H28B).

    이것이 "좌표가 주소와 다른 곳을 가리키는가"를 물을 수 있는 **유일한 독립 축**이다.
    payload 행정코드는 최소 concierge에서 같은 geo reverse의 캐시본이라 쓸 수 없다
    (``AdminEvidence`` 모듈 docstring).

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
    if not provider_address:
        return ()
    address = bundle.feature.address
    evidence = bundle.admin_evidence

    observed: list[str] = []
    if evidence is not None and evidence.obs_sigungu_names:
        observed.extend(evidence.obs_sigungu_names)
    elif address.sigungu_name:
        observed.append(address.sigungu_name)
    if not observed:
        return ()

    text = _compact(provider_address)
    if not _ADMIN_NAME_TOKEN.search(text):
        # 판정 불가 — 통과가 아니다. 커버리지는 name_state로 집계된다.
        return ()

    if any(_region_stem(name) and _region_stem(name) in text for name in observed):
        return ()

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
