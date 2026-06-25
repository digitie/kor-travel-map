"""``FeatureBundle`` — provider → load 전달 단위.

provider 변환 함수의 출력 = load 함수의 입력. 하나의 raw payload (예: 축제
한 건)를 적재하는 데 필요한 모든 DTO를 한 묶음으로 전달:

- ``feature`` (필수) — Feature 본체
- ``source_record`` (필수) — provider raw payload 보존
- ``source_link`` (필수) — feature ↔ source 매핑
- ``file_sources``. WeatherValue/PriceValue는 전용 적재 메서드가 별도로 받는다.

``AsyncKorTravelMapClient.load_feature_bundles(bundles)``가 본 DTO 리스트를 받아
DB upsert + 객체 저장소 업로드 + source_link 생성을 한 transaction에서 수행.

``docs/architecture/feature-model.md §18``.

ADR 참조
--------
- ADR-018 — DTO union/forbidden_extra
- ADR-002 — async-only API (load_feature_bundles는 async)
- ADR-013 — bulk insert ``psycopg.copy_*`` 우선 (load 함수 책임)
"""

from __future__ import annotations

from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .area import AreaDetail
from .event import EventDetail
from .feature import Feature
from .file import FeatureFileSource
from .notice import NoticeDetail
from .place import PlaceDetail
from .route import RouteDetail
from .source import SourceLink, SourceRecord

__all__ = ["FeatureBundle"]


class FeatureBundle(BaseModel):
    """provider → load 한 묶음. raw payload 한 건의 적재 단위.

    ``feature.kind``별 detail은 ``feature.detail``에 박힘 (ADR-018) — 본
    bundle은 별도 ``detail`` 필드를 두지 않는다 (중복 회피, single source of
    truth).

    ``file_sources``는 미디어(이미지 등) 파일 참조 — provider 응답의 미디어 URL을
    ``FeatureFileSource``(docs/architecture/feature-files-rustfs.md §2.2)로 담는다. load 시
    객체 저장소(rustfs/s3) 업로드 대상. WeatherValue/PriceValue는 별도
    repository/client 메서드에서 feature anchor와 같은 transaction으로 적재한다.

    예시 (Sprint 2 첫 provider 변환 함수 출력):

    >>> # bundle = FeatureBundle(
    ... #     feature=Feature(feature_id="f_...", kind="event", name="...", ...),
    ... #     source_record=SourceRecord(provider="python-visitkorea-api", ...),
    ... #     source_link=SourceLink(feature_id="f_...", source_record_key="sr_...",
    ... #                            source_role=SourceRole.PRIMARY,
    ... #                            match_method="natural_key", confidence=100,
    ... #                            is_primary_source=True),
    ... # )
    """

    model_config = ConfigDict(extra="forbid")

    feature: Feature
    source_record: SourceRecord
    source_link: SourceLink
    file_sources: list[FeatureFileSource] = Field(
        default_factory=list,
        description=(
            "미디어 파일 참조 (이미지/영상 등). provider 응답 URL → load 시 "
            "객체 저장소 업로드 (docs/architecture/feature-files-rustfs.md). 기본 빈 list."
        ),
    )

    @model_validator(mode="after")
    def _check_source_consistency(self) -> Self:
        """Feature와 source lineage FK가 같은 bundle 안에서 닫혀 있는지 검증."""
        if self.source_link.feature_id != self.feature.feature_id:
            raise ValueError(
                "source_link.feature_id must match feature.feature_id "
                f"({self.source_link.feature_id!r} != {self.feature.feature_id!r})."
            )
        if self.source_link.source_record_key != self.source_record.source_record_key:
            raise ValueError(
                "source_link.source_record_key must match "
                "source_record.source_record_key "
                f"({self.source_link.source_record_key!r} != "
                f"{self.source_record.source_record_key!r})."
            )
        for fs in self.file_sources:
            if fs.feature_id != self.feature.feature_id:
                raise ValueError(
                    "file_sources[].feature_id must match feature.feature_id "
                    f"({fs.feature_id!r} != {self.feature.feature_id!r})."
                )
        return self

    # ── convenience ─────────────────────────────────────────────────────

    @property
    def detail(
        self,
    ) -> PlaceDetail | EventDetail | NoticeDetail | RouteDetail | AreaDetail | None:
        """``feature.detail``의 alias (편의용).

        ``FeatureBundle``은 별도 ``detail`` 필드를 두지 않고 ``feature.detail``을
        그대로 노출 — single source of truth.
        """
        return self.feature.detail
