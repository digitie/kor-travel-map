"""ADR115 shadow 후보의 필드 존재 증거. 완성된 Feature DTO의 기본값과 구분한다."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProviderFieldPresence(BaseModel):
    """원천 계약을 해석한 변환기가 명시하는 field-path 존재 집합.

    supplied_fields에 없는 경로는 omitted다. 포함된 경로의 None은 명시 null이다.
    이 객체가 없으면 presence를 추측하지 않고 shadow coverage를 미완으로 기록한다.
    normalizer_revision은 shadow 정책에 선언된 변환 revision과 같아야 한다.
    값 자체는 기존 typed Feature와 source record lineage에서 가져온다.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    normalizer_revision: str = Field(min_length=1, max_length=128)
    supplied_fields: frozenset[str] = Field(max_length=256)

    @field_validator("normalizer_revision")
    @classmethod
    def revision_is_canonical(cls, value: str) -> str:
        if value != value.strip():
            raise ValueError("normalizer_revision에 앞뒤 공백을 둘 수 없습니다.")
        return value

    @field_validator("supplied_fields")
    @classmethod
    def paths_are_canonical(cls, values: frozenset[str]) -> frozenset[str]:
        for value in values:
            if not value or value != value.strip() or len(value) > 120 or "." not in value:
                raise ValueError("supplied_fields는 registry의 정확한 field path여야 합니다.")
        return values
