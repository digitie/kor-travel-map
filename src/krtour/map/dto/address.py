"""``Address`` — 주소 + 행정구역 코드 (kraddr-base 호환).

자세한 ``kraddr.base`` 타입 사용은 ``docs/kraddr-base-types.md``. 본 PR
(Sprint 1)에서는 최소 형태만. Sprint 2에서 ``python-kraddr-base`` 클래스를
직접 import해 통합 검토.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["Address"]


class Address(BaseModel):
    """주소 + 행정구역 코드 (간단형).

    Sprint 1 시점에는 string 필드만. ``python-kraddr-base``의 ``LegalAddress``/
    ``RoadAddress`` 통합은 Sprint 2 PR (``docs/kraddr-base-types.md``).
    """

    model_config = ConfigDict(extra="forbid")

    road: str | None = Field(default=None, description="도로명 주소 (정규화된 형태).")
    legal: str | None = Field(default=None, description="법정동 주소.")
    admin: str | None = Field(default=None, description="행정동 주소.")
    bjd_code: str | None = Field(
        default=None,
        description="법정동 코드 (10자리). reverse geocoding 보강 결과.",
        min_length=10,
        max_length=10,
    )
    sigungu_code: str | None = Field(
        default=None,
        description="시·군·구 코드 (5자리, 행정안전부 표준).",
        min_length=5,
        max_length=5,
    )
    sido_code: str | None = Field(
        default=None,
        description="시·도 코드 (2자리).",
        min_length=2,
        max_length=2,
    )
