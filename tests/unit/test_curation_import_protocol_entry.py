"""옛 h35 import와 기존 helper caller에는 새 protocol SQL을 요구하지 않는다."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from kortravelmap.infra import curation_repo as repo
from tests.unit.test_curation_repo import (
    _COLLECTION_ID,
    _SOURCE_ID,
    _THEME_ID,
    _FakeResult,
    _FakeSession,
    _resolved_row,
)


class _H35Session(_FakeSession):
    async def execute(self, statement, params=None):
        # 옛 DB에 존재하지 않는 새 ops 함수를 부르면 비즈니스 분기 진입 전에 실패한다.
        assert "ops.lock_scoped_feature_write_protocol" not in str(statement)
        return await super().execute(statement, params)


async def test_h35_import_keeps_old_advisory_and_natural_dataset_branch(monkeypatch):
    foundations = AsyncMock(side_effect=[_SOURCE_ID, _COLLECTION_ID])
    monkeypatch.setattr(repo, "_upsert_id_with_fallback", foundations)
    provenance = AsyncMock(return_value=("00000000-0000-4000-8000-000000000090", ()))
    monkeypatch.setattr(repo, "_record_import_provenance", provenance)
    session = _H35Session(
        _FakeResult(),
        _FakeResult(),
        _FakeResult(),
        _FakeResult(),
        _FakeResult(),
        _FakeResult(scalar=_THEME_ID),
        _FakeResult(),
        _FakeResult(rows=[]),
        _FakeResult(scalar=0),
        _FakeResult(rows=[dict(inserted=0, updated=0)]),
    )
    row = _resolved_row(
        provider_dataset_id=None,
        frozen_h35_dataset=("python-mcst-api", "tourism-100"),
        feature_id=None,
    )
    result = await repo.import_curation_rows(session, rows=(row,), frozen_h35_schema=True)
    assert result["rows"] == result["collections"] == 1
    assert result["inserted"] == result["updated"] == result["removed"] == 0
    assert "pg_advisory_xact_lock" in session.calls[0][0]
    # 실제 upsert_theme도 공유 helper의 옛 advisory를 그대로 호출했다.
    assert "pg_advisory_xact_lock" in session.calls[4][0]
    source_call = foundations.await_args_list[0].kwargs
    assert source_call["upsert_sql"] == repo._FROZEN_H35_UPSERT_SOURCE_SQL
    assert source_call["params"]["provider"] == "python-mcst-api"
    assert source_call["params"]["dataset_key"] == "tourism-100"
    assert "provider_dataset_id" not in source_call["params"]
    session.assert_exhausted()


async def test_create_collection_keeps_existing_advisory_without_new_protocol(monkeypatch):
    session = _H35Session(_FakeResult())

    # 첫 SQL 경계만 관측한 뒤 멈춘다. DB 생성 성공으로 계산하지 않는다.
    async def stop_after_boundary(*args, **kwargs):
        raise RuntimeError("observed collection boundary")

    monkeypatch.setattr(repo, "_lock_collection_keys", stop_after_boundary)
    with pytest.raises(RuntimeError, match="observed collection boundary"):
        await repo.create_curation_collection(
            session,
            collection_key="h35:collection",
            theme_id=_THEME_ID,
            source_id=None,
            title="h35 collection",
        )
    assert len(session.calls) == 1
    assert "pg_advisory_xact_lock" in session.calls[0][0]
    session.assert_exhausted()


async def test_empty_normal_import_has_no_protocol_or_write_boundary(monkeypatch):
    monkeypatch.setattr(
        repo,
        "_record_import_provenance",
        AsyncMock(return_value=("00000000-0000-4000-8000-000000000090", ())),
    )
    session = _FakeSession()
    result = await repo.import_curation_rows(session, rows=())
    assert result["rows"] == result["collections"] == 0
    assert session.calls == []
