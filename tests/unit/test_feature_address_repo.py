"""``feature_address_repo`` DB 무관 단위 테스트 (T-212 / DA-D-04).

PostGIS 없이 raw SQL 분기/파라미터 조립을 검증한다 — 실제 SQL 실행은
``tests/integration/test_feature_address_repo.py``가 PostGIS에서 실측한다.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from kortravelmap.infra import feature_address_repo as repo


class _Row:
    def __init__(self, data: dict[str, Any]) -> None:
        self.__dict__.update(data)


class _Result:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self._row = row

    def one_or_none(self) -> _Row | None:
        return _Row(self._row) if self._row is not None else None

    def one(self) -> _Row:
        assert self._row is not None
        return _Row(self._row)


class _Session:
    def __init__(self, results: list[dict[str, Any] | None]) -> None:
        self._results = results
        self.calls: list[dict[str, Any]] = []

    async def execute(self, statement: object, params: dict[str, Any]) -> _Result:
        self.calls.append({"sql": str(statement), "params": params})
        return _Result(self._results.pop(0))


def _snap_row(**over: Any) -> dict[str, Any]:
    base = {
        "feature_id": "f1",
        "lon": 126.97,
        "lat": 37.57,
        "address": {"road": "옛 주소"},
        "legal_dong_code": "1111010100",
        "sido_code": "11",
        "sigungu_code": "11110",
        "road_address_management_no": None,
        "status": "active",
    }
    base.update(over)
    return base


async def test_get_snapshot_present_and_missing() -> None:
    session = _Session([_snap_row()])
    snap = await repo.get_feature_address_snapshot(session, "f1")  # type: ignore[arg-type]
    assert snap is not None
    assert snap.lon == 126.97
    assert snap.legal_dong_code == "1111010100"

    missing = await repo.get_feature_address_snapshot(
        _Session([None]),  # type: ignore[arg-type]
        "nope",
    )
    assert missing is None


async def test_apply_requires_a_field() -> None:
    with pytest.raises(ValueError, match="최소 1개"):
        await repo.apply_feature_address_override(_Session([]), "f1")  # type: ignore[arg-type]


async def test_apply_partial_coord_raises() -> None:
    with pytest.raises(ValueError, match="lon/lat 둘 다"):
        await repo.apply_feature_address_override(
            _Session([]),  # type: ignore[arg-type]
            "f1",
            lon=126.9,
        )


async def test_apply_missing_feature_returns_none() -> None:
    # lock SELECT → None.
    session = _Session([None])
    result = await repo.apply_feature_address_override(
        session,  # type: ignore[arg-type]
        "missing",
        legal_dong_code="1111010100",
    )
    assert result is None


async def test_apply_full_override_builds_fields_and_overrides() -> None:
    updated = _snap_row(
        address={"road": "새 주소"},
        lon=126.98,
        lat=37.56,
        legal_dong_code="1114010300",
        sigungu_code="11140",
    )
    # lock SELECT, UPDATE RETURNING, then one upsert result per overridden field (4).
    session = _Session([_snap_row(), updated, None, None, None, None])
    result = await repo.apply_feature_address_override(
        session,  # type: ignore[arg-type]
        "f1",
        address={"road": "새 주소"},
        lon=126.98,
        lat=37.56,
        legal_dong_code="1114010300",
        sigungu_code="11140",
        reason="manual",
        operator="op",
    )
    assert result is not None
    assert set(result.overridden_fields) == {
        "address",
        "coord",
        "legal_dong_code",
        "sigungu_code",
    }
    assert result.snapshot.address == {"road": "새 주소"}
    assert result.snapshot.sigungu_code == "11140"

    # lock + update + 4 override upserts.
    assert len(session.calls) == 6
    update_sql = session.calls[1]["sql"]
    assert "UPDATE feature.features SET" in update_sql
    assert "ST_MakePoint" in update_sql
    # 직전 값이 override source_value(jsonb 문자열)에 보존됐는지.
    legal_upsert = next(
        c for c in session.calls[2:] if c["params"]["field_path"] == "legal_dong_code"
    )
    assert json.loads(legal_upsert["params"]["source_value"]) == "1111010100"
    assert legal_upsert["params"]["operator"] == "op"


async def test_snapshot_parses_json_string_address() -> None:
    # address가 jsonb 문자열로 올 때도 dict로 역직렬화.
    session = _Session([_snap_row(address=json.dumps({"road": "문자열 주소"}))])
    snap = await repo.get_feature_address_snapshot(session, "f1")  # type: ignore[arg-type]
    assert snap is not None
    assert snap.address == {"road": "문자열 주소"}


async def test_apply_coord_only_with_existing_coord() -> None:
    updated = _snap_row(lon=127.0, lat=37.0)
    session = _Session([_snap_row(), updated, None])
    result = await repo.apply_feature_address_override(
        session,  # type: ignore[arg-type]
        "f1",
        lon=127.0,
        lat=37.0,
    )
    assert result is not None
    assert result.overridden_fields == ("coord",)
    coord_upsert = session.calls[2]
    assert coord_upsert["params"]["field_path"] == "coord"
    # 직전 좌표(lon/lat 존재)가 source_value에 보존됨.
    assert json.loads(coord_upsert["params"]["source_value"]) == {
        "lon": 126.97,
        "lat": 37.57,
    }


async def test_apply_coord_when_previous_coord_null() -> None:
    # 직전 좌표가 없으면 source_value는 null.
    session = _Session([_snap_row(lon=None, lat=None), _snap_row(lon=127.1, lat=37.1), None])
    result = await repo.apply_feature_address_override(
        session,  # type: ignore[arg-type]
        "f1",
        lon=127.1,
        lat=37.1,
    )
    assert result is not None
    coord_upsert = session.calls[2]
    assert json.loads(coord_upsert["params"]["source_value"]) is None


async def test_apply_sido_and_road_management_no() -> None:
    updated = _snap_row(sido_code="26", road_address_management_no="RM-1")
    session = _Session([_snap_row(), updated, None, None])
    result = await repo.apply_feature_address_override(
        session,  # type: ignore[arg-type]
        "f1",
        sido_code="26",
        road_address_management_no="RM-1",
    )
    assert result is not None
    assert set(result.overridden_fields) == {"sido_code", "road_address_management_no"}
    paths = {c["params"]["field_path"] for c in session.calls[2:]}
    assert paths == {"sido_code", "road_address_management_no"}
