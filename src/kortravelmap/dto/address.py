"""``Address`` — 한국 주소 + 행정구역 코드 통합 DTO.

ADR-041 (2026-05-27)으로 `python-kraddr-base`에서 흡수. kraddr-base의
`Address` / `LegalAddress` / `RoadAddress` / `AddressRegion`을 단일
``Address`` 모델로 통합 (분리 모델 X — provider raw에서 채워지지 않는 필드는
None으로). ``PlaceCoordinate``는 명시적 제외 — 좌표 DTO는
``kortravelmap.dto.coordinate.Coordinate``가 단일 source.

본 DTO는 ``Feature.address`` + ``FeatureRow.address`` JSONB + 행정코드 칼럼
들(`legal_dong_code`, `road_name_code`, `road_address_management_no`,
`admin_dong_code`, `sido_code`, `sigungu_code`)을 모두 커버한다.

정규화/파싱 helper는 ``kortravelmap.core.address`` (분리 — dto는 stdlib만).

ADR 참조
--------
- ADR-018 — DTO ``extra="forbid"`` 강제
- ADR-041 — `python-kraddr-base` 흡수, `PlaceCoordinate` 제외
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["Address"]


# 행정 코드 정규식 — strict validation (잘못된 길이/형식 거부, kraddr-base 정합).
_BJD_CODE_PATTERN = re.compile(r"^\d{10}$")  # 법정동: 시도2 + 시군구3 + 읍면동3 + 리2
_ADMIN_DONG_CODE_PATTERN = re.compile(r"^\d{10}$")
_SIGUNGU_CODE_PATTERN = re.compile(r"^\d{5}$")  # 시도2 + 시군구3
_SIDO_CODE_PATTERN = re.compile(r"^\d{2}$")
_ZIPCODE_PATTERN = re.compile(r"^\d{5}$")  # 신우편번호 5자리


class Address(BaseModel):
    """한국 주소 + 행정구역 코드 통합 DTO.

    provider raw에서 채워지지 않는 필드는 ``None``으로 남긴다. 정규화/파싱은
    호출자 또는 ``kortravelmap.core.address``의 helper(`normalize_bjd_code` 등)에서.

    예시 — 표준데이터 1차 source:
        >>> Address(
        ...     road="서울특별시 영등포구 여의공원로 120",
        ...     legal="서울특별시 영등포구 여의도동 8",
        ...     bjd_code="1156010100",
        ...     sigungu_code="11560",
        ...     sido_code="11",
        ... )
        Address(...)

    예시 — 좌표만 있고 reverse geocoding 미적용:
        >>> Address()  # 모든 필드 None — 호출자가 후속 enrichment에서 채움
        Address(...)
    """

    model_config = ConfigDict(extra="forbid")

    # ── 1) 사람이 읽는 주소 텍스트 ────────────────────────────────────────

    road: str | None = Field(default=None, description="도로명 주소 (정규화된 형태).")
    legal: str | None = Field(default=None, description="법정동 주소 (지번 포함).")
    admin: str | None = Field(default=None, description="행정동 주소.")

    # ── 2) 행정 코드 (모두 strict 자릿수 검증) ───────────────────────────

    bjd_code: str | None = Field(
        default=None,
        description=(
            "법정동 코드 10자리 (시도2 + 시군구3 + 읍면동3 + 리2). reverse "
            "geocoding 결과 또는 provider 원천에서 채워짐."
        ),
    )
    admin_dong_code: str | None = Field(
        default=None,
        description="행정동 코드 10자리. 행정구역 변경 시 갱신 — 법정동과 다름.",
    )
    sigungu_code: str | None = Field(
        default=None,
        description="시·군·구 코드 5자리 (시도2 + 시군구3). `infra.models` 별도 칼럼.",
    )
    sido_code: str | None = Field(
        default=None,
        description="시·도 코드 2자리.",
    )

    # ── 3) 도로명/우편번호 부가 식별자 (kraddr-base 흡수 추가 필드) ──────

    road_name_code: str | None = Field(
        default=None,
        description=(
            "도로명 코드 (PNU 기반 7~12자리 — provider별 길이 다양). "
            "도로명주소 표준 매핑 시 사용."
        ),
    )
    road_address_management_no: str | None = Field(
        default=None,
        description=(
            "도로명주소 관리번호 (행정안전부 발급 25자리 식별자). 도로명주소 "
            "변경 이력 추적용."
        ),
    )
    zipcode: str | None = Field(
        default=None,
        description="신우편번호 5자리 (구 우편번호 6자리는 폐기).",
    )

    # ── 4) 표시용 한글 이름 (검색/UI 보강용, kraddr-base 흡수) ──────────

    sido_name: str | None = Field(
        default=None,
        description="시·도 한글 명 (예: '서울특별시'). 검색/UI 표시용.",
    )
    sigungu_name: str | None = Field(
        default=None,
        description="시·군·구 한글 명 (예: '영등포구'). 검색/UI 표시용.",
    )

    # ── validators ────────────────────────────────────────────────────────

    @field_validator("bjd_code", "admin_dong_code")
    @classmethod
    def _check_10digit_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _BJD_CODE_PATTERN.match(value):
            raise ValueError(
                f"법정동/행정동 코드는 10자리 숫자여야 함, got {value!r}."
            )
        return value

    @field_validator("sigungu_code")
    @classmethod
    def _check_sigungu_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _SIGUNGU_CODE_PATTERN.match(value):
            raise ValueError(f"sigungu_code는 5자리 숫자여야 함, got {value!r}.")
        return value

    @field_validator("sido_code")
    @classmethod
    def _check_sido_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _SIDO_CODE_PATTERN.match(value):
            raise ValueError(f"sido_code는 2자리 숫자여야 함, got {value!r}.")
        return value

    @field_validator("zipcode")
    @classmethod
    def _check_zipcode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not _ZIPCODE_PATTERN.match(value):
            raise ValueError(
                f"zipcode는 신우편번호 5자리 숫자여야 함, got {value!r}."
            )
        return value

    @model_validator(mode="after")
    def _check_code_consistency(self) -> Address:
        """``bjd_code`` 앞 2자리/5자리가 ``sido_code``/``sigungu_code``와 일치.

        둘 다 있을 때만 검증. 한 쪽이 None이면 skip — provider raw에서 부분
        채움 허용.
        """
        if self.bjd_code is not None:
            if self.sido_code is not None and self.bjd_code[:2] != self.sido_code:
                raise ValueError(
                    f"bjd_code[:2]={self.bjd_code[:2]!r} != "
                    f"sido_code={self.sido_code!r}"
                )
            if (
                self.sigungu_code is not None
                and self.bjd_code[:5] != self.sigungu_code
            ):
                raise ValueError(
                    f"bjd_code[:5]={self.bjd_code[:5]!r} != "
                    f"sigungu_code={self.sigungu_code!r}"
                )
        return self

    # ── 편의 메서드 ──────────────────────────────────────────────────────

    def is_complete(self) -> bool:
        """1차 검색/적재에 필요한 필드가 모두 채워졌는가.

        ``bjd_code`` + (`road` or `legal`) 둘 다 있어야 True. reverse geocoding
        후/적재 직전 sanity check에 사용.
        """
        return bool(self.bjd_code) and bool(self.road or self.legal)

    def display(self) -> str:
        """UI 표시용 단일 주소 문자열. 우선순위: road → legal → admin → ''."""
        return self.road or self.legal or self.admin or ""
