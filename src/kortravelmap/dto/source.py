"""``SourceRecord`` + ``SourceLink`` — provider raw payload 추적 DTO.

provider 측 응답을 raw 형태로 보존하고 (`SourceRecord`), 어떤 Feature가 어떤
source에서 왔는지 (1:N 매핑) 추적한다 (`SourceLink`).

``docs/architecture/feature-model.md §11-§12`` + ``docs/architecture/data-model.md §2-§3``.

ADR 참조
--------
- ADR-018 — DTO union/forbidden_extra
- ADR-019 — datetime aware (``check_aware_datetime``)
- ADR-009 — ID 생성 (``make_source_record_key`` / ``make_payload_hash``)
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._enums import SourceRole
from ._time import check_aware_datetime, kst_now

__all__ = ["SourceRecord", "SourceLink"]


class SourceRecord(BaseModel):
    """provider raw payload 한 건 — ``provider_sync.source_records`` row.

    입력 identity(``provider``/``dataset_key``/entity type/id)는 적재 시 canonical
    ``source_entity_key``로 해석한다. record row에는 raw payload와 hash만 immutable
    이력으로 남긴다. 같은 entity라도 payload가 바뀌면 새 row가 생기며, PK는
    ``source_record_key`` (``make_source_record_key(...)``)다.

    provider 응답은 ``raw_data``에만 원형으로 보존한다. 이름·주소·좌표·버전의
    표준화된 복사본을 두지 않는다. 만료 관측값은 entity head를 갱신하는 입력이다.

    ``docs/architecture/feature-model.md §11`` + ``docs/architecture/data-model.md §2``.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(
        min_length=1,
        description=(
            "canonical provider name (예: ``'python-visitkorea-api'``, "
            "``'python-knps-api'``)."
        ),
    )
    dataset_key: str = Field(
        min_length=1,
        description="provider 내 dataset 식별자 (예: ``'festival'``, ``'knps_trails'``).",
    )
    source_entity_type: str = Field(
        min_length=1,
        description="provider 내 entity 종류 (예: ``'festival_record'``).",
    )
    source_entity_id: str = Field(
        min_length=1,
        description="provider 원천 entity id (예: ``'E001234'``, ``'RA00012'``).",
    )
    raw_payload_hash: str = Field(
        min_length=1,
        description="``make_payload_hash(raw_data)`` 결과 (ADR-009).",
    )
    raw_data: dict[str, Any] = Field(
        default_factory=dict,
        description="provider 응답 raw payload 원형 (``JSONB``). JSON 직렬화만 허용.",
    )
    fetched_at: datetime = Field(
        description="provider 호출 시각 (aware datetime, ADR-019).",
    )
    imported_at: datetime = Field(
        default_factory=kst_now,
        description="본 라이브러리 적재 시각 (aware datetime).",
    )
    expires_at: datetime | None = Field(
        default=None,
        description=(
            "entity head의 재호출/만료 관측 입력 (옵션). 예: notice는 "
            "``valid_end_time + 1 year`` 후 purge (ADR-017)."
        ),
    )
    source_record_key: str = Field(
        min_length=1,
        description=(
            "PK. 호출자가 ``make_source_record_key(...)``로 계산해서 명시적으로 넣는다."
        ),
    )

    @field_validator("fetched_at", "imported_at", "expires_at")
    @classmethod
    def _check_aware(cls, value: datetime | None) -> datetime | None:
        """ADR-019 — naive datetime 입력은 ValidationError."""
        return check_aware_datetime(value)

    # ``key()`` 메서드는 두지 않는다 — dto는 core를 import할 수 없다
    # (ADR-001/002 의존 방향: ``category → dto → core``). 호출자는
    # ``kortravelmap.core.make_source_record_key(...)``로 직접 계산해서
    # ``self.source_record_key``에 박는다.


class SourceLink(BaseModel):
    """Feature ↔ SourceRecord 1:N 매핑 — ``provider_sync.source_links`` row.

    한 Feature는 여러 source에서 enrichment될 수 있다 (예: visitkorea primary +
    kakao_local 전화번호 보강). 한 SourceRecord는 한 Feature에 1차 매핑되는 것이
    원칙 (``source_role='primary'`` link는 한 SourceRecord당 최대 1건).

    ``docs/architecture/feature-model.md §12`` + ``docs/architecture/data-model.md §3``.
    """

    model_config = ConfigDict(extra="forbid")

    feature_id: str = Field(
        min_length=1,
        description="``make_feature_id(...)`` 결과.",
    )
    source_record_key: str = Field(
        min_length=1,
        description="``make_source_record_key(...)`` 결과.",
    )
    source_role: SourceRole = Field(
        default=SourceRole.ENRICHMENT,
        description=(
            "``primary`` (1차 source) / ``enrichment`` (보강) / ``media`` (사진/VR) "
            "/ ``weather_context`` 등 (``SourceRole`` enum 8종)."
        ),
    )
    match_method: str = Field(
        min_length=1,
        description=(
            "feature ↔ source 매칭 방법. ``'natural_key'`` (provider 자연키 직접), "
            "``'reverse_geocode'``, ``'place_phone_search'``, ``'dedup_merge'``, "
            "``'manual'`` 등. ADR-016 Record Linkage scoring 결과는 별도 필드 X "
            "— ``confidence``로 통합."
        ),
    )
    confidence: int = Field(
        ge=0,
        le=100,
        description="매칭 신뢰도 0~100 (ADR-016 scoring 결과 × 100).",
    )
    created_at: datetime = Field(
        default_factory=kst_now,
        description="link 생성 시각 (aware datetime, ADR-019).",
    )

    @field_validator("created_at")
    @classmethod
    def _check_aware(cls, value: datetime) -> datetime:
        """ADR-019 — naive datetime 입력은 ValidationError."""
        result = check_aware_datetime(value)
        # created_at은 default_factory가 있어 None이 들어올 수 없음.
        assert result is not None
        return result
