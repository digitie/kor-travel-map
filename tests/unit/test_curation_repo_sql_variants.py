"""curation repo의 h35 pre-uuid SQL 변형 핀 (T-VN-32C PR-2, ADR-075 역사 표면).

`.replace` 파생은 needle 표기가 drift하면 **조용히 no-op**되어 h35 cutover
rehearsal(0063 고정 스키마)에서 UndefinedColumnError로만 재발한다 — 변형이
실제로 feature_uuid 참조를 제거했음을 여기서 고정한다(적대 리뷰 2 권고).

`_PREVIEW_IMPORT_REMOVALS_SQL`은 feature_uuid를 포함하지만 실행 지점이
`preview_curation_import`(admin 라우터 전용) 1곳이라 h35 미도달 — h35에
DB-preview 단계가 추가되면 pre-uuid 변형이 함께 필요하다.
"""

from __future__ import annotations

import pytest

from kortravelmap.infra.curation_repo import (
    _MARK_IMPORT_REMOVALS_PRE_UUID_SQL,
    _MARK_IMPORT_REMOVALS_SQL,
    _RESOLVE_FEATURES_BATCH_PRE_UUID_SQL,
    _RESOLVE_FEATURES_BATCH_SQL,
)

pytestmark = pytest.mark.unit


def test_pre_uuid_variants_strip_feature_uuid_column_references() -> None:
    for variant in (
        _RESOLVE_FEATURES_BATCH_PRE_UUID_SQL,
        _MARK_IMPORT_REMOVALS_PRE_UUID_SQL,
    ):
        assert "f.feature_uuid" not in variant
        assert "NULL::text AS feature_uuid" in variant


def test_current_surface_sql_keeps_feature_uuid_projection() -> None:
    # LATERAL 양 arm(matcher) 2회 + removal projection 1회 — 표기 drift로
    # `.replace`가 no-op되면 여기서 즉시 드러난다.
    assert _RESOLVE_FEATURES_BATCH_SQL.count("CAST(f.feature_uuid AS text)") == 2
    assert _MARK_IMPORT_REMOVALS_SQL.count("CAST(f.feature_uuid AS text)") == 1
    assert "NULL::text AS feature_uuid" not in _RESOLVE_FEATURES_BATCH_SQL
    assert "NULL::text AS feature_uuid" not in _MARK_IMPORT_REMOVALS_SQL
