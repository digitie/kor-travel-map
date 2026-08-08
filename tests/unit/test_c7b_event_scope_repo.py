"""0057 typed event scope/cursor repository 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast

import pytest
from sqlalchemy import CheckConstraint

from kortravelmap.infra import ops_repo
from kortravelmap.infra.models import ImportJobEventRow, ImportJobRow
from kortravelmap.infra.ops_repo import (
    OpsCursorFilterMismatch,
    list_ops_import_job_events,
)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _Session:
    def __init__(self, *rows: list[Any]) -> None:
        self._rows = list(rows)
        self.statements: list[str] = []

    async def execute(self, statement: Any, _params: dict[str, Any]) -> _Result:
        self.statements.append(str(statement))
        return _Result(self._rows.pop(0))


def _event(event_id: str, *, at: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        event_id=event_id,
        job_id="57000000-0000-4000-8000-000000000001",
        import_job_dataset_id="57000000-0000-4000-8000-0000000000a1",
        provider_dataset_id=7,
        operation_key="fixture_refresh",
        feature_id=None,
        stage="loading",
        level="info",
        code="load.progress",
        message="progress",
        payload={},
        occurred_at=at,
    )


@pytest.mark.unit
async def test_exact_scope_uses_typed_event_column_before_cursor_and_limit() -> None:
    at = datetime(2026, 7, 18, tzinfo=UTC)
    session = _Session(
        [
            _event("57000000-0000-4000-8000-000000000001", at=at),
            _event("57000000-0000-4000-8000-000000000002", at=at),
        ]
    )
    page = await list_ops_import_job_events(
        cast(Any, session),
        provider_dataset_id=7,
        sync_scope="dataset_wide",
        limit=1,
    )
    assert page.next_cursor is not None
    sql = session.statements[0]
    # scope는 event에 비정규화돼 있던 열이 아니라 membership에서 읽는다
    # (T-VN-33: 같은 사실을 두 곳에 적지 않는다). 위치 보증은 그대로다 —
    # cursor/LIMIT 이전 WHERE에 있어야 페이지가 scope 밖 행으로 채워지지 않는다.
    assert "member.sync_scope = CAST(:sync_scope AS text)" in sql
    assert "event.sync_scope" not in sql
    assert "event.provider" not in sql
    assert "ops.feature_update_requests" not in sql
    assert "JOIN ops.import_jobs" not in sql
    assert (
        sql.index("member.sync_scope = CAST(:sync_scope AS text)")
        < sql.index("ORDER BY")
        < sql.index("LIMIT")
    )
    # per-member top-N을 합쳐 페이지를 만든다. 안쪽 LIMIT은 member에 묶인
    # correlated scan 안에 있어야 하고(그래야 scope 밖 event를 볼 수 없다),
    # scope 밖에서 event를 다시 끌어오는 join이 없어야 한다.
    assert "CROSS JOIN LATERAL" in sql
    assert (
        sql.index("event.import_job_dataset_id = scope_member.import_job_dataset_id")
        < sql.index("LIMIT :limit")
    )


@pytest.mark.unit
async def test_event_cursor_is_bound_to_all_filters() -> None:
    at = datetime(2026, 7, 18, tzinfo=UTC)
    first = _Session(
        [
            _event("57000000-0000-4000-8000-000000000001", at=at),
            _event("57000000-0000-4000-8000-000000000002", at=at),
        ]
    )
    page = await list_ops_import_job_events(
        cast(Any, first),
        level="info",
        provider_dataset_id=7,
        sync_scope="dataset_wide",
        limit=1,
    )
    assert page.next_cursor is not None

    mismatch = _Session()
    with pytest.raises(OpsCursorFilterMismatch, match="filter mismatch"):
        await list_ops_import_job_events(
            cast(Any, mismatch),
            level="error",
            provider_dataset_id=7,
            sync_scope="dataset_wide",
            limit=1,
            cursor=page.next_cursor,
        )
    assert mismatch.statements == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("at", "key"),
    [
        (datetime(2026, 7, 18, tzinfo=UTC), "not-a-uuid"),
        (datetime(2026, 7, 18), "57000000-0000-4000-8000-000000000001"),
    ],
)
async def test_event_cursor_rejects_invalid_keyset_before_query(
    at: datetime,
    key: str,
) -> None:
    # cursor filter 집합은 아래 호출과 **정확히 같아야** 한다 — 어긋나면 keyset 검사
    # 전에 filter mismatch로 먼저 걸려 이 테스트의 의도(잘못된 keyset을 쿼리 전에
    # 거부)를 검증하지 못한다. membership triple이 filter에 들어가므로 operation_key도
    # 포함한다.
    filters = {
        "job_id": None,
        "level": None,
        "provider_dataset_id": "7",
        "sync_scope": "dataset_wide",
        "operation_key": None,
    }
    cursor = ops_repo._encode_bound_cursor(
        "import_job_events",
        at=at,
        key=key,
        filters=filters,
    )
    session = _Session()

    with pytest.raises(ValueError, match="invalid import_job_events cursor"):
        await list_ops_import_job_events(
            cast(Any, session),
            provider_dataset_id=7,
            sync_scope="dataset_wide",
            cursor=cursor,
        )
    assert session.statements == []


@pytest.mark.unit
@pytest.mark.parametrize("sync_scope", ["default", " external_system:x", "other"])
async def test_event_scope_rejects_noncanonical_value(sync_scope: str) -> None:
    session = _Session()
    with pytest.raises(ValueError, match="sync_scope|external_system"):
        await list_ops_import_job_events(
            cast(Any, session),
            provider_dataset_id=7,
            sync_scope=sync_scope,
        )
    assert session.statements == []


@pytest.mark.unit
def test_exact_scope_index_predicate_matches_repository_query() -> None:
    sql = ops_repo._list_import_job_events_sql(
        job_id=None,
        level=None,
        provider_dataset_id=7,
        sync_scope="dataset_wide",
        operation_key="fixture_refresh",
        cursor_occurred_at=None,
    )
    for predicate in (
        "member.provider_dataset_id = CAST(:provider_dataset_id AS bigint)",
        "member.sync_scope = CAST(:sync_scope AS text)",
        # membership identity는 triple이다 — operation 축까지 member 절 안에 있어야
        # 형제 operation의 event가 섞이지 않고, member 축 index 경계도 유지된다.
        "member.operation_key = CAST(:operation_key AS text)",
        "event.quarantined_at IS NULL",
    ):
        assert predicate in sql


@pytest.mark.unit
def test_scope_page_filters_stay_inside_the_member_bounded_scan() -> None:
    """scope 조회의 event 쪽 술어는 전부 member correlated scan 안에 있어야 한다.

    ``idx_import_job_events_member_time``은 member 마다
    ``(occurred_at DESC, event_id DESC)``로 정렬돼 있고 ``level``을 INCLUDE로
    갖는다. level·cursor 술어가 그 scan 밖으로 새어나가면 member 별 상위
    ``limit``을 못 자르고 scope 전체를 모아 정렬하게 된다 — 인덱스가 있어도
    읽는 양이 페이지 크기가 아니라 scope 크기에 비례한다.
    """

    sql = ops_repo._list_import_job_events_sql(
        job_id=None,
        level="error",
        provider_dataset_id=7,
        sync_scope="dataset_wide",
        operation_key="fixture_refresh",
        cursor_occurred_at=datetime(2026, 7, 18, tzinfo=UTC),
    )
    lateral_at = sql.index("CROSS JOIN LATERAL")
    page_cut_at = sql.rindex("LIMIT :limit")
    for predicate in (
        "event.level = CAST(:level AS text)",
        "(event.occurred_at, event.event_id) < ",
        "event.quarantined_at IS NULL",
    ):
        assert lateral_at < sql.index(predicate) < page_cut_at


@pytest.mark.unit
def test_event_scope_columns_are_not_denormalized_onto_the_event() -> None:
    """0057의 비정규화 3열은 T-VN-33에서 membership으로 흡수됐다.

    ``provider``/``dataset_key``/``sync_scope``를 event에 사본으로 들고 있으면
    membership과 어긋날 수 있고, 그걸 막던 것이 ``ck_import_job_events_*_pair``와
    trigger였다. 사본을 없애면 정합성 문제 자체가 사라지므로 그 방어물도 함께
    사라지는 것이 맞다 — 여기서는 **되살아나지 않는지**를 지킨다.
    """

    event_columns = set(ImportJobEventRow.__table__.columns.keys())
    assert not (event_columns & {"provider", "dataset_key", "sync_scope"})
    assert "import_job_dataset_id" in event_columns

    constraint_names = {
        item.name
        for item in ImportJobEventRow.__table__.constraints
        if isinstance(item, CheckConstraint)
    }
    assert "ck_import_job_events_provider_dataset_pair" not in constraint_names
    assert "ck_import_job_events_sync_scope" not in constraint_names

    indexes = {index.name: index for index in ImportJobEventRow.__table__.indexes}
    assert "idx_import_job_events_provider_dataset_scope_time" not in indexes
    # scope 조회는 membership을 거치므로 timeline 인덱스도 membership 축이다.
    member_index = indexes["idx_import_job_events_member_time"]
    assert tuple(str(expr) for expr in member_index.expressions) == (
        "import_job_events.import_job_dataset_id",
        "occurred_at DESC",
        "event_id DESC",
    )
    # cursor가 ``(occurred_at, event_id)`` keyset이므로 tiebreaker까지 인덱스에
    # 있어야 정렬이 인덱스로 해결된다. 부분 술어는 질의 술어와 같아야 한다.
    predicate = str(member_index.dialect_options["postgresql"]["where"])
    assert "quarantined_at IS NULL" in predicate
    assert "import_job_dataset_id IS NOT NULL" in predicate
    # ``level``은 key가 아니라 INCLUDE여야 한다. key로 올리면 keyset 정렬이
    # 깨지고, 빼면 level filter가 member 마다 heap을 때린다.
    assert list(member_index.dialect_options["postgresql"]["include"]) == ["level"]


@pytest.mark.unit
def test_import_job_scope_moves_to_the_dataset_member() -> None:
    """job 자체는 scope를 갖지 않는다 — 대상은 member 행이다."""

    job_columns = set(ImportJobRow.__table__.columns.keys())
    assert not (job_columns & {"provider", "dataset_key", "sync_scope"})
