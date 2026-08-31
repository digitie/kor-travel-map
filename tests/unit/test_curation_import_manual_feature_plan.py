"""T-VN-M03 — manual Feature payload가 plan round-trip에서 살아남는지.

preview가 굳힌 typed payload와 canonical SHA는 commit 시점에 그대로 다시 읽혀야 한다.
child idempotency identity가 그 SHA에서 유도되므로(설계 §6.2), round-trip에서 한
글자라도 달라지면 같은 plan이 다른 child를 만든다.

``normalized_payload``는 jsonb로 저장되므로 **JSON을 실제로 왕복**시켜 확인한다 —
dataclass만 왕복시키면 직렬화 단계의 손실을 보지 못한다.
"""

from __future__ import annotations

import json

import pytest

from kortravelmap.curation_import import manual_feature_payload_sha256
from kortravelmap.infra.curation_repo import (
    ResolvedCurationImportRow,
    _canonical_import_row_payload,
    _resolved_import_row_from_payload,
)

pytestmark = pytest.mark.unit


def _row(**overrides: object) -> ResolvedCurationImportRow:
    base: dict[str, object] = {
        "row_number": 2,
        "collection_key": "visit-korea-100:2025-2026",
        "theme_slug": "visit-korea-100",
        "theme_name": "한국관광 100선",
        "theme_group": "관광",
        "title": "2025-2026 한국관광 100선",
        "edition_key": "2025-2026",
        "provider_dataset_id": 7,
        "source_name": "한국관광공사",
        "source_url": None,
        "source_item_key": "2025-2026:1",
        "feature_id": None,
        "place_name": "창덕궁",
        "address_hint": None,
        "sort_order": 0,
        "item_title": None,
        "item_summary": None,
        "metadata": {},
    }
    base.update(overrides)
    return ResolvedCurationImportRow(**base)  # type: ignore[arg-type]


def _round_trip(row: ResolvedCurationImportRow) -> ResolvedCurationImportRow:
    payload = _canonical_import_row_payload(row)
    # jsonb 저장을 흉내 내 실제 직렬화 손실을 드러낸다.
    restored = json.loads(json.dumps(payload, ensure_ascii=False))
    return _resolved_import_row_from_payload(restored)


def test_row_without_manual_feature_round_trips_as_none() -> None:
    restored = _round_trip(_row())

    assert restored.manual_feature is None
    assert restored.manual_feature_sha256 is None


def test_manual_feature_payload_and_sha_survive_json_round_trip() -> None:
    payload = {"kind": "place", "coord": {"lon": "126.99100", "lat": "37.57960"}}
    sha = manual_feature_payload_sha256(payload)

    restored = _round_trip(_row(manual_feature=payload, manual_feature_sha256=sha))

    assert restored.manual_feature == payload
    assert restored.manual_feature_sha256 == sha
    # 저장된 payload를 다시 해싱해도 같은 값이어야 한다 — 그렇지 않으면 commit 시점의
    # child identity가 preview 시점과 달라진다.
    assert restored.manual_feature is not None
    assert manual_feature_payload_sha256(restored.manual_feature) == sha


def test_coordinate_precision_is_not_lost_in_storage() -> None:
    """좌표를 문자열로 담는 이유가 여기서 드러난다.

    JSON number였다면 ``126.99100``이 ``126.991``로 정규화돼 SHA가 달라졌을 것이다.
    """
    payload = {"kind": "place", "coord": {"lon": "126.99100", "lat": "37.57960"}}

    restored = _round_trip(_row(manual_feature=payload, manual_feature_sha256="x" * 64))

    assert restored.manual_feature is not None
    coord = restored.manual_feature["coord"]
    assert coord == {"lon": "126.99100", "lat": "37.57960"}


def test_manual_feature_is_not_merged_into_metadata() -> None:
    """설계 §6.1 — typed 입력을 ``metadata``에 숨기지 않는다."""
    payload = {"kind": "event", "coord": {"lon": "127.0", "lat": "37.5"}}

    stored = _canonical_import_row_payload(
        _row(manual_feature=payload, manual_feature_sha256="y" * 64)
    )

    assert stored["manual_feature"] == payload
    assert stored["metadata"] == {}
