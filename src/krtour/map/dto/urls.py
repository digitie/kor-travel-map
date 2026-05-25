"""``FeatureUrls`` + ``RawDataRef`` — Feature 부가 URL / source 참조."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator

from ._enums import SourceRole
from ._time import check_aware_datetime

__all__ = ["FeatureUrls", "RawDataRef"]


class FeatureUrls(BaseModel):
    """Feature의 외부 URL (홈페이지/SNS/리뷰).

    모든 필드는 optional. 일부 provider는 review URL을 별도 dict로 노출하지만
    여기서는 정형 필드만 둔다. 그 외는 ``Feature.payload`` 또는 detail-level
    payload에.
    """

    model_config = ConfigDict(extra="forbid")

    homepage: AnyUrl | None = None
    sns1: AnyUrl | None = None
    sns2: AnyUrl | None = None
    review_naver: AnyUrl | None = None
    review_kakao: AnyUrl | None = None
    review_google: AnyUrl | None = None


class RawDataRef(BaseModel):
    """Feature에 박힌 빠른 lookup용 source 요약.

    정확한 source 관계는 ``source_links`` 테이블이 정답. 본 ref는 디버그 UI/
    빠른 query용 cache.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="canonical name (``normalize_provider_name`` 결과).")
    dataset_key: str = Field(description="provider별 dataset 식별자.")
    source_entity_id: str = Field(description="provider 원천의 entity id.")
    source_role: SourceRole = SourceRole.PRIMARY
    fetched_at: datetime | None = None
    payload_hash: str | None = None
    extra: dict[str, Any] = Field(default_factory=dict)

    @field_validator("fetched_at")
    @classmethod
    def _check_aware(cls, value: datetime | None) -> datetime | None:
        """ADR-019 — naive datetime 입력은 ValidationError (review report P0-2)."""
        return check_aware_datetime(value)
