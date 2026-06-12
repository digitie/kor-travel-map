"""MOIS Phase A LOCALDATA 소스 DB sync 단위 테스트 (T-RV-04b)."""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pytest
from dagster import build_op_context
from kortravelmap.providers.mois import PROMOTED_SERVICE_SLUGS
from kortravelmap.settings import KorTravelMapSettings

from kortravelmap.dagster.mois_source_sync import (
    MoisSourceSyncSummary,
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
    calls: dict[str, Any] = {}

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
        calls["sync"] = {
            "session": session,
            "client": client,
            "service_slugs": slugs,
            "org_code": org_code,
            "batch_size": batch_size,
            "commit": commit,
        }
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
    assert calls["sync"]["service_slugs"] == expected_slugs
    assert summary.service_slugs == expected_slugs
    # Phase A는 commit=True로 소스 DB에 영속화한다.
    assert calls["sync"]["commit"] is True
    assert calls["sync"]["org_code"] is None
    # provider sync 결과 count가 그대로 복사된다.
    assert summary.scanned_count == 10
    assert summary.upserted_count == 8
    assert summary.open_count == 6
    assert summary.closed_count == 2
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
    assert calls["sync"]["service_slugs"] == ("bars_and_clubs", "restaurants")
    assert summary.service_slugs == ("bars_and_clubs", "restaurants")
    assert calls["sync"]["org_code"] == "6110000"
    assert calls["sync"]["batch_size"] == 250


def test_sync_creates_parent_directory(
    tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _install_fake_mois(monkeypatch)
    nested = tmp_path / "missing" / "dir" / "mois.sqlite"
    settings = KorTravelMapSettings(mois_source_db_path=str(nested))

    sync_mois_source_db(settings)

    assert nested.parent.is_dir()


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

    assert metadata["open_count"] == 6
    assert metadata["upserted_count"] == 8
    assert metadata["service_slug_count"] == len(PROMOTED_SERVICE_SLUGS)
    assert metadata["db_path"] == str(db_file)
    assert calls["sync"]["commit"] is True
