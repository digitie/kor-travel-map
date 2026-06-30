"""MOIS Phase A LOCALDATA 소스 DB sync 단위 테스트 (T-RV-04b)."""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from types import ModuleType
from typing import Any, cast

import pytest
from dagster import build_op_context
from kortravelmap.providers.mois import PROMOTED_SERVICE_SLUGS
from kortravelmap.settings import KorTravelMapSettings

from kortravelmap.dagster.mois_source_sync import (
    MoisSourceSyncSummary,
    ensure_mois_source_db_fresh,
    mois_localdata_source_sync_op,
    sync_mois_source_db,
)
from kortravelmap.dagster.provider_fetchers import ProviderCredentialMissing

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)


class _FakeSyncResult:
    def __init__(self, service_slugs: tuple[str, ...]) -> None:
        self.service_slugs = service_slugs
        self.sync_kind = "localdata_full"
        self.scanned_count = 10
        self.upserted_count = 8
        self.open_count = 6
        self.closed_count = 2
        self.unknown_status_count = 0


class _FakeFileClient:
    instances: list[_FakeFileClient] = []

    def __init__(self, **_kwargs: Any) -> None:
        self.closed = False
        _FakeFileClient.instances.append(self)

    def close(self) -> None:
        self.closed = True


def _install_fake_mois(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    _FakeFileClient.instances = []
    calls: dict[str, Any] = {"sync_calls": []}

    def _create_sqlite_schema(engine: Any, **_kwargs: Any) -> bool:
        calls["schema_engine"] = engine
        return True

    def _sync_localdata_source_db(
        session: Any,
        client: Any,
        *,
        service_slugs: Any,
        org_code: str | None = None,
        batch_size: int = 1000,
        sync_kind: str = "localdata_full",
        commit: bool = False,
    ) -> _FakeSyncResult:
        slugs = tuple(service_slugs)
        call = {
            "session": session,
            "client": client,
            "service_slugs": slugs,
            "org_code": org_code,
            "batch_size": batch_size,
            "commit": commit,
        }
        calls["sync"] = call
        calls["sync_calls"].append(call)
        return _FakeSyncResult(slugs)

    module = ModuleType("mois")
    module.__dict__["create_sqlite_schema"] = _create_sqlite_schema
    module.__dict__["LocalDataFileClient"] = _FakeFileClient
    module.__dict__["sync_localdata_source_db"] = _sync_localdata_source_db
    monkeypatch.setitem(sys.modules, "mois", module)
    return calls


def test_sync_raises_when_db_path_unset() -> None:
    settings = KorTravelMapSettings(mois_source_db_path=None)

    with pytest.raises(ProviderCredentialMissing):
        sync_mois_source_db(settings)


def test_sync_uses_promoted_slugs_commits_and_closes(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_mois(monkeypatch)
    db_file = tmp_path / "mois-source.sqlite"
    settings = KorTravelMapSettings(mois_source_db_path=str(db_file))

    summary = sync_mois_source_db(settings)

    assert isinstance(summary, MoisSourceSyncSummary)
    # 기본 service_slugs는 PROMOTED_SERVICE_SLUGS 전체를 정렬해 쓴다.
    expected_slugs = tuple(sorted(PROMOTED_SERVICE_SLUGS))
    assert [call["service_slugs"] for call in calls["sync_calls"]] == [
        (slug,) for slug in expected_slugs
    ]
    assert summary.service_slugs == expected_slugs
    # Phase A는 업종별 commit=True로 영속화해 SQLite WAL을 주기적으로 줄인다.
    assert all(call["commit"] is True for call in calls["sync_calls"])
    assert all(call["org_code"] is None for call in calls["sync_calls"])
    # provider sync 결과 count를 업종별로 합산한다.
    assert summary.scanned_count == 10 * len(expected_slugs)
    assert summary.upserted_count == 8 * len(expected_slugs)
    assert summary.open_count == 6 * len(expected_slugs)
    assert summary.closed_count == 2 * len(expected_slugs)
    assert summary.unknown_status_count == 0
    assert summary.db_path == str(db_file)
    # file client는 finally에서 닫힌다.
    assert len(_FakeFileClient.instances) == 1
    assert _FakeFileClient.instances[0].closed is True


def test_sync_passes_custom_slugs_org_and_batch(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_mois(monkeypatch)
    settings = KorTravelMapSettings(mois_source_db_path=str(tmp_path / "src.sqlite"))

    summary = sync_mois_source_db(
        settings,
        service_slugs=["restaurants", "bars_and_clubs"],
        org_code="6110000",
        batch_size=250,
    )

    # 명시 slug도 정렬해서 전달한다.
    assert [call["service_slugs"] for call in calls["sync_calls"]] == [
        ("bars_and_clubs",),
        ("restaurants",),
    ]
    assert summary.service_slugs == ("bars_and_clubs", "restaurants")
    assert all(call["org_code"] == "6110000" for call in calls["sync_calls"])
    assert all(call["batch_size"] == 250 for call in calls["sync_calls"])


def test_sync_creates_parent_directory(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_mois(monkeypatch)
    nested = tmp_path / "missing" / "dir" / "mois.sqlite"
    settings = KorTravelMapSettings(mois_source_db_path=str(nested))

    sync_mois_source_db(settings)

    assert nested.parent.is_dir()


def test_checkpoint_runs_after_each_slug_and_once_at_end(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#614 회귀 가드: WAL checkpoint가 슬러그별 + 마지막에 호출되는지 구조적으로 단언.

    슬러그당 checkpoint 줄을 지우거나 위치를 옮기면 이 테스트가 깨진다(기존 테스트는
    전부 green으로 남아 회귀가 보이지 않았다)."""
    import kortravelmap.dagster.mois_source_sync as mod

    calls = _install_fake_mois(monkeypatch)
    settings = KorTravelMapSettings(mois_source_db_path=str(tmp_path / "ck.sqlite"))

    # checkpoint 호출 시점의 누적 sync 호출 수를 기록 → sync와 interleave 검증.
    sync_counts_at_checkpoint: list[int] = []

    def _spy(engine: Any) -> None:
        sync_counts_at_checkpoint.append(len(calls["sync_calls"]))

    monkeypatch.setattr(mod, "_checkpoint_sqlite_wal", _spy)

    sync_mois_source_db(settings, service_slugs=["c", "a", "b"])

    # 슬러그 3개 → 슬러그별 3회 + outer finally 1회 = 4회.
    # sync 직후마다 호출되므로 누적 sync 수는 [1, 2, 3, 3](마지막은 전체 완료 후).
    assert sync_counts_at_checkpoint == [1, 2, 3, 3]


def test_sync_raises_on_empty_explicit_slugs(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """명시적 빈 slug 목록은 fail-fast(ValueError) — 조용한 no-op 회귀 방지."""
    _install_fake_mois(monkeypatch)
    settings = KorTravelMapSettings(mois_source_db_path=str(tmp_path / "empty.sqlite"))

    with pytest.raises(ValueError, match="at least one slug"):
        sync_mois_source_db(settings, service_slugs=[])


def test_checkpoint_is_noop_for_non_sqlite_engine() -> None:
    """비-sqlite dialect면 connect()도 건드리지 않고 즉시 반환한다(early-return)."""
    from kortravelmap.dagster.mois_source_sync import _checkpoint_sqlite_wal

    class _Dialect:
        name = "postgresql"

    class _Engine:
        dialect = _Dialect()

        def connect(self) -> Any:  # pragma: no cover - 호출되면 실패
            raise AssertionError("non-sqlite engine은 checkpoint에서 connect되면 안 된다")

    # 예외 없이 조용히 반환해야 한다.
    _checkpoint_sqlite_wal(cast("Any", _Engine()))


def test_op_runs_sync_and_emits_metadata(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _install_fake_mois(monkeypatch)
    db_file = tmp_path / "op-source.sqlite"
    monkeypatch.setenv("KOR_TRAVEL_MAP_MOIS_SOURCE_DB_PATH", str(db_file))

    context = build_op_context(
        config={"service_slugs": [], "org_code": None, "batch_size": 1000}
    )
    metadata = mois_localdata_source_sync_op(context)

    assert metadata["open_count"] == 6 * len(PROMOTED_SERVICE_SLUGS)
    assert metadata["upserted_count"] == 8 * len(PROMOTED_SERVICE_SLUGS)
    assert metadata["service_slug_count"] == len(PROMOTED_SERVICE_SLUGS)
    assert metadata["db_path"] == str(db_file)
    assert all(call["commit"] is True for call in calls["sync_calls"])


# -- ensure_mois_source_db_fresh: freshness 게이트(#617 리뷰) --------------------

_SQLITE_HEADER = b"SQLite format 3\x00"


def _stub_sync(monkeypatch: pytest.MonkeyPatch, *, creates: Any = None) -> dict[str, int]:
    """``sync_mois_source_db``를 호출 카운터 stub으로 치환한다(게이트만 검증)."""
    calls = {"n": 0}

    def _spy(_settings: Any, **_kwargs: Any) -> MoisSourceSyncSummary:
        calls["n"] += 1
        if creates is not None:
            creates.write_bytes(_SQLITE_HEADER)
        return MoisSourceSyncSummary(
            db_path="x",
            service_slugs=("a",),
            sync_kind="localdata_full",
            scanned_count=0,
            upserted_count=0,
            open_count=0,
            closed_count=0,
            unknown_status_count=0,
        )

    monkeypatch.setattr(
        "kortravelmap.dagster.mois_source_sync.sync_mois_source_db", _spy
    )
    return calls


def _write_marker(db_file: Any, *, hours_ago: float = 0.0) -> None:
    stamp = datetime.now(UTC) - timedelta(hours=hours_ago)
    (db_file.parent / (db_file.name + ".synced")).write_text(
        stamp.isoformat(), encoding="utf-8"
    )


def test_ensure_skips_sync_when_db_fresh(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "mois.sqlite"
    db_file.write_bytes(_SQLITE_HEADER)
    _write_marker(db_file, hours_ago=1.0)
    settings = KorTravelMapSettings(
        mois_source_db_path=str(db_file), mois_source_sync_ttl_hours=24
    )
    calls = _stub_sync(monkeypatch)
    assert ensure_mois_source_db_fresh(settings) is None
    assert calls["n"] == 0  # fresh → Phase A sync 생략


def test_ensure_syncs_when_missing_then_skips_within_ttl(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "mois.sqlite"
    settings = KorTravelMapSettings(
        mois_source_db_path=str(db_file), mois_source_sync_ttl_hours=24
    )
    calls = _stub_sync(monkeypatch, creates=db_file)
    # 1) DB 없음 → sync 1회 + 마커 기록
    assert ensure_mois_source_db_fresh(settings) is not None
    assert calls["n"] == 1
    assert (db_file.parent / (db_file.name + ".synced")).exists()
    # 2) TTL 이내 재호출 → fresh → 재sync 없음(센서가 매번 큐잉해도 전국 sync 안 함)
    assert ensure_mois_source_db_fresh(settings) is None
    assert calls["n"] == 1


def test_ensure_syncs_when_marker_stale(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_file = tmp_path / "mois.sqlite"
    db_file.write_bytes(_SQLITE_HEADER)
    _write_marker(db_file, hours_ago=48.0)
    settings = KorTravelMapSettings(
        mois_source_db_path=str(db_file), mois_source_sync_ttl_hours=24
    )
    calls = _stub_sync(monkeypatch)
    assert ensure_mois_source_db_fresh(settings) is not None
    assert calls["n"] == 1  # 마커 stale → 재sync
