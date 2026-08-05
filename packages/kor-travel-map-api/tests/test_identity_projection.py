"""``api/identity_projection`` 응답 치환 헬퍼 계약 (T-VN-32C PR-2).

DB 없이 검증하는 순수 계약: 응답 feature_id 값은 UUID 정본으로 치환되고,
projection이 feature_uuid를 누락하면 fail-close(ValueError)한다. cursor·echo가
치환 **전** row를 써야 한다는 규칙은 통합 테스트(cursor 연속성·batch echo
등식) 소관이다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from kortravelmap.api.identity_projection import response_feature_id, uuid_substituted_row

_UUID = "01890a5d-ac96-774b-bcce-b302099a8057"
_LEGACY = "f_1168010100_p_3c0c2820e96d28d3"


@dataclass(frozen=True)
class _Row:
    feature_id: str
    feature_uuid: str | None


def test_response_feature_id_reads_mapping_and_attribute_rows() -> None:
    assert response_feature_id({"feature_id": _LEGACY, "feature_uuid": _UUID}) == _UUID
    assert response_feature_id(_Row(feature_id=_LEGACY, feature_uuid=_UUID)) == _UUID


def test_response_feature_id_fails_close_on_missing_or_empty_uuid() -> None:
    with pytest.raises(ValueError, match="projection"):
        response_feature_id({"feature_id": _LEGACY})
    with pytest.raises(ValueError, match="projection"):
        response_feature_id({"feature_id": _LEGACY, "feature_uuid": None})
    with pytest.raises(ValueError, match="projection"):
        response_feature_id(_Row(feature_id=_LEGACY, feature_uuid=None))


def test_uuid_substituted_row_replaces_only_feature_id_and_copies() -> None:
    row = {"feature_id": _LEGACY, "feature_uuid": _UUID, "name": "장소"}
    substituted = uuid_substituted_row(row)
    assert substituted == {"feature_id": _UUID, "feature_uuid": _UUID, "name": "장소"}
    # 원본 row는 무변경 — cursor/내부 키가 치환 전 값을 계속 읽을 수 있어야 한다.
    assert row["feature_id"] == _LEGACY
