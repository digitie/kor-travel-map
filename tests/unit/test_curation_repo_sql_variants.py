"""curation repo의 h35 pre-uuid SQL 변형 핀 (T-VN-32C PR-2, ADR-075 역사 표면).

h35 cutover rehearsal은 0063 고정 스키마(pre-0080, `feature_uuid` column 부재)에서
같은 import 경로를 돌린다. `_replace_once`는 needle 표기가 drift하면 import 시점에
RuntimeError로 죽지만, `.format` 파생은 template에서 slot이 사라져도 조용히 통과한다.
그래서 **현행 표면과 고정-세대 변형의 `feature_uuid` 투영 개수가 서로 맞는지**를
여기서 고정한다 — 한쪽 arm만 변형돼도 rehearsal에서 UndefinedColumnError로만
드러나기 때문이다(적대 리뷰 2 권고).

T-VN-39 재키(309) 이후 현행 표면의 `feature_uuid` **출처**는 shadow column
`f.feature_uuid`(309가 DROP)가 아니라 uuid가 된 `feature.features.feature_id`다.
바깥으로 나가는 이름 — 출력 별칭 `feature_uuid` — 은 그대로이므로, 아래 핀은
출처 표기가 아니라 **별칭이 투영에 남아 있는지**를 센다.

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

#: (현행 표면, 고정-세대 변형, `feature_uuid` 투영 개수).
#: matcher는 LATERAL 양 arm에서 2회, removal projection은 1회 투영한다.
_SURFACE_PAIRS: tuple[tuple[str, str, int], ...] = (
    (_RESOLVE_FEATURES_BATCH_SQL, _RESOLVE_FEATURES_BATCH_PRE_UUID_SQL, 2),
    (_MARK_IMPORT_REMOVALS_SQL, _MARK_IMPORT_REMOVALS_PRE_UUID_SQL, 1),
)


def test_pre_uuid_variants_strip_feature_uuid_column_references() -> None:
    for _current, variant, projections in _SURFACE_PAIRS:
        # 0063 고정 세대엔 `feature.features.feature_uuid`가 아예 없다.
        assert "f.feature_uuid" not in variant
        # 현행 표면이 투영하는 자리마다 빠짐없이 NULL로 대체됐다.
        assert variant.count("NULL::text AS feature_uuid") == projections


def test_current_surface_sql_keeps_feature_uuid_projection() -> None:
    for current, _variant, projections in _SURFACE_PAIRS:
        # 경계 계약: 출력 별칭 `feature_uuid`는 재키 뒤에도 그대로 남는다.
        # 출처 표기(`CAST(f.feature_id AS text)`)를 세면 출처가 바뀔 때마다
        # 깨지므로, 지키려는 것 — 별칭이 투영에서 사라지지 않는 것 — 만 센다.
        assert current.count(" AS feature_uuid") == projections
        # 309가 shadow column을 DROP했다. 현행 표면에 남아 있으면 실행 시
        # UndefinedColumnError다.
        assert "f.feature_uuid" not in current
        # 현행 표면이 고정-세대 변형으로 뒤바뀌지 않았다(투영이 NULL이 아니다).
        assert "NULL::text AS feature_uuid" not in current


def test_resolve_batch_matcher_projects_feature_uuid_through_lateral() -> None:
    # 별칭 개수만 세면 LATERAL 안쪽에만 남고 바깥 SELECT에서 빠져도 통과한다 —
    # 호출자가 실제로 읽는 것은 `matched.feature_uuid`이므로 그것도 함께 고정한다.
    assert "matched.feature_uuid" in _RESOLVE_FEATURES_BATCH_SQL
    assert "matched.feature_uuid" in _RESOLVE_FEATURES_BATCH_PRE_UUID_SQL
