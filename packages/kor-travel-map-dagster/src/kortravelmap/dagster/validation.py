"""Dagster ETL 적재 전 좌표/주소 정합성 검증."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

    from kortravelmap.dto import FeatureBundle

IssueSeverity = Literal["error", "warning"]


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

    @property
    def has_errors(self) -> bool:
        return self.error_count > 0

    def as_metadata(self) -> dict[str, int | list[dict[str, str | None]]]:
        return {
            "address_validation_total": self.total,
            "address_validation_issue_count": self.issue_count,
            "address_validation_error_count": self.error_count,
            "address_validation_warning_count": self.warning_count,
            "address_validation_issues": [issue.as_dict() for issue in self.issues],
        }


def validate_feature_bundle_address(
    bundle: FeatureBundle,
) -> FeatureAddressValidation:
    """FeatureBundle 1건의 좌표/주소 보강 상태를 검증한다.

    정책은 ``docs/address-geocoding.md``의 ADR-046 주소 정본 규칙을 따른다.
    좌표가 있는 feature는 kor-travel-geo reverse 결과로 ``bjd_code``가 있어야 한다.
    provider 주소 문자열이 있으면 reverse 결과의 시군구명과 같은 행정권인지
    보수적으로 확인한다.
    """
    feature = bundle.feature
    address = feature.address
    provider_address = _provider_address(bundle)
    issues: list[FeatureAddressIssue] = []

    if feature.coord is not None and address.bjd_code is None:
        issues.append(
            FeatureAddressIssue(
                feature_id=feature.feature_id,
                source_record_key=bundle.source_record.source_record_key,
                code="missing_bjd_code",
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

    if provider_address and feature.coord is not None and address.bjd_code is not None:
        issues.extend(_provider_address_match_issues(bundle, provider_address))

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
    validations = [validate_feature_bundle_address(bundle) for bundle in bundles]
    issues = tuple(issue for validation in validations for issue in validation.issues)
    error_count = sum(1 for issue in issues if issue.severity == "error")
    warning_count = sum(1 for issue in issues if issue.severity == "warning")
    return FeatureAddressValidationSummary(
        total=len(validations),
        issue_count=len(issues),
        error_count=error_count,
        warning_count=warning_count,
        issues=issues,
    )


def ensure_feature_address_valid(
    bundles: Iterable[FeatureBundle],
) -> FeatureAddressValidationSummary:
    """검증 error가 있으면 ``ValueError``로 중단한다."""
    summary = validate_feature_bundles_address(bundles)
    if summary.has_errors:
        codes = ", ".join(issue.code for issue in summary.issues if issue.severity == "error")
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


def _provider_address_match_issues(
    bundle: FeatureBundle,
    provider_address: str,
) -> tuple[FeatureAddressIssue, ...]:
    feature = bundle.feature
    address = feature.address
    normalized_provider = _compact(provider_address)
    issues: list[FeatureAddressIssue] = []

    if address.sigungu_name and _compact(address.sigungu_name) not in normalized_provider:
        issues.append(
            FeatureAddressIssue(
                feature_id=feature.feature_id,
                source_record_key=bundle.source_record.source_record_key,
                code="provider_address_mismatch",
                severity="error",
                message="provider 주소 문자열과 좌표 기준 kor-travel-geo 시군구명이 다름.",
                provider_address=provider_address,
                bjd_code=address.bjd_code,
                sigungu_code=address.sigungu_code,
            )
        )
        return tuple(issues)

    if address.sido_name and _compact(address.sido_name) not in normalized_provider:
        issues.append(
            FeatureAddressIssue(
                feature_id=feature.feature_id,
                source_record_key=bundle.source_record.source_record_key,
                code="provider_address_partial_match",
                severity="warning",
                message="시군구는 맞지만 provider 주소에 kor-travel-geo 시도명이 명시되지 않음.",
                provider_address=provider_address,
                bjd_code=address.bjd_code,
                sigungu_code=address.sigungu_code,
            )
        )

    return tuple(issues)


def _compact(value: str) -> str:
    return "".join(str(value).split())
