"""H35 cutover의 단일 schema 경계 상수."""

from __future__ import annotations

from typing import Final

PRE_SCHEMA: Final = "0063_pipeline_root_id"
TARGET_SCHEMA: Final = "0079_cache_target_writer_drain"
FORWARD_BOUNDARY: Final = "schema_0079"
