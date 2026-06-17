"""``FeatureFileSource`` — provider가 만든 미디어 파일 참조 (업로드 전 입력).

`docs/architecture/feature-files-rustfs.md §2.2`. provider 변환 함수가 응답의 미디어 URL을
이 DTO로 만들어 ``FeatureBundle.file_sources``에 담는다. 아직 다운로드/업로드
전이라 ``source_url``(provider 원본 URL)만 갖고, 실제 객체 저장소(rustfs/s3)
적재 후 ``FeatureFile``(저장 DTO, §2.1)로 승격된다.

ADR 참조
--------
- ADR-018 — DTO ``extra='forbid'``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["FeatureFileSource", "FileRole", "FileType"]

FileRole = Literal["primary", "thumbnail", "gallery"]
"""파일 역할 — 대표(primary) / 썸네일(thumbnail) / 갤러리(gallery)."""

FileType = Literal["image", "video", "audio", "document", "file"]
"""파일 종류 — content_type 추론 보조 + 표시 분기."""


class FeatureFileSource(BaseModel):
    """미디어 파일 1건의 업로드 입력 (provider URL 기반, 다운로드 전).

    object 저장소 적재(``upload_feature_file_sources_to_rustfs``)가 본 DTO를
    받아 URL 다운로드 → checksum → object_key 결정 → PUT → ``FeatureFile`` 생성.
    """

    model_config = ConfigDict(extra="forbid")

    feature_id: str = Field(
        description="이 파일이 속한 Feature의 ``feature_id`` (FK)."
    )
    source_url: str = Field(
        description="provider가 준 원본 미디어 URL (다운로드 대상)."
    )
    role: FileRole = Field(
        default="gallery",
        description="primary(대표) / thumbnail / gallery. feature당 primary는 보통 1건.",
    )
    display_order: int = Field(
        default=0,
        ge=0,
        description="동일 feature 내 표시 순서 (object_key·정렬에 사용).",
    )
    file_type: FileType = Field(
        default="image",
        description="image/video/audio/document/file.",
    )
    content_type: str | None = Field(
        default=None,
        description="MIME (알려진 경우). 미상이면 다운로드 단계에서 추론.",
    )
    alt_text: str | None = Field(
        default=None,
        description="대체 텍스트/캡션 (접근성·표시용).",
    )
    provider: str | None = Field(
        default=None,
        description="출처 provider canonical name (ADR-024).",
    )
    dataset_key: str | None = Field(
        default=None,
        description="출처 dataset key.",
    )
    source_record_key: str | None = Field(
        default=None,
        description="출처 ``SourceRecord``의 key (lineage, FK SET NULL).",
    )
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="provider 고유 메타 (원본 필드명 등).",
    )
