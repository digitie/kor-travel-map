"""offline upload load Dagster job unit test."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from krtour.map.infra.feature_repo import FeatureLoadResult
from krtour.map.infra.jobs_repo import ImportJob
from krtour.map.infra.offline_upload_repo import OfflineUpload
from krtour.map.offline_upload import OfflineUploadLoadResult

from krtour.map_dagster.offline_uploads import offline_upload_load_job

pytestmark = pytest.mark.filterwarnings(
    "ignore:Parameter `owners` of initializer `SensorDefinition.__init__`"
    ".*:dagster_shared.utils.warnings.BetaWarning"
)

_KST = timezone(timedelta(hours=9))
_NOW = datetime(2026, 6, 3, 14, 0, tzinfo=_KST)


class _Store:
    pass


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def run_offline_upload_load_job(
        self,
        upload_id: str,
        *,
        store: object,
        dagster_run_id: str | None = None,
        address_resolver: object | None = None,
        reverse_geocoder: object | None = None,
    ) -> OfflineUploadLoadResult:
        self.calls.append(
            {
                "upload_id": upload_id,
                "store": store,
                "dagster_run_id": dagster_run_id,
                "address_resolver": address_resolver,
                "reverse_geocoder": reverse_geocoder,
            }
        )
        return OfflineUploadLoadResult(
            acquired=True,
            upload=_upload(upload_id),
            job=_job(),
            load=FeatureLoadResult(
                bundles_total=2,
                features_inserted=2,
                source_records_inserted=2,
                source_links_inserted=2,
            ),
            bytes_read=123,
            checksum_sha256="a" * 64,
            parsed_format="jsonl",
        )


class _LockBusyClient(_Client):
    async def run_offline_upload_load_job(
        self,
        upload_id: str,
        *,
        store: object,
        dagster_run_id: str | None = None,
        address_resolver: object | None = None,
        reverse_geocoder: object | None = None,
    ) -> OfflineUploadLoadResult:
        self.calls.append(
            {
                "upload_id": upload_id,
                "store": store,
                "dagster_run_id": dagster_run_id,
                "address_resolver": address_resolver,
                "reverse_geocoder": reverse_geocoder,
            }
        )
        return OfflineUploadLoadResult(
            acquired=False,
            upload=_upload(upload_id),
            error_message="offline upload load advisory lock busy",
        )


def test_offline_upload_load_job_executes_client() -> None:
    client = _Client()
    store = _Store()

    result = offline_upload_load_job.execute_in_process(
        run_config={
            "ops": {
                "load_offline_upload": {
                    "config": {"upload_id": "00000000-0000-0000-0000-000000000001"}
                }
            }
        },
        resources={"krtour_map_client": client, "offline_upload_store": store},
    )

    assert result.success
    assert client.calls[0]["upload_id"] == "00000000-0000-0000-0000-000000000001"
    assert client.calls[0]["store"] is store
    assert client.calls[0]["dagster_run_id"]

    output = result.output_for_node("load_offline_upload")
    assert output["job_status"] == "done"
    assert output["bundles_total"] == 2
    assert output["features_inserted"] == 2


def test_offline_upload_load_job_fails_on_lock_busy_skip() -> None:
    client = _LockBusyClient()
    store = _Store()

    result = offline_upload_load_job.execute_in_process(
        run_config={
            "ops": {
                "load_offline_upload": {
                    "config": {"upload_id": "00000000-0000-0000-0000-000000000001"}
                }
            }
        },
        resources={"krtour_map_client": client, "offline_upload_store": store},
        raise_on_error=False,
    )

    assert result.success is False
    assert client.calls


def _upload(upload_id: str) -> OfflineUpload:
    return OfflineUpload(
        upload_id=upload_id,
        provider="offline-test-provider",
        dataset_key="offline_jsonl",
        sync_scope="default",
        original_filename="features.jsonl",
        storage_backend="rustfs",
        storage_key=f"offline/{upload_id}/features.jsonl",
        byte_size=123,
        checksum_sha256="a" * 64,
        detected_format="jsonl",
        detected_encoding="utf-8",
        status="loaded",
        validation_job_id=None,
        load_job_id="10000000-0000-0000-0000-000000000001",
        created_by="pytest",
        created_at=_NOW,
        updated_at=_NOW,
    )


def _job() -> ImportJob:
    return ImportJob(
        job_id="10000000-0000-0000-0000-000000000001",
        kind="offline_upload_load",
        payload={},
        status="done",
        progress=100,
        current_stage=None,
        source_checksum="a" * 64,
        error_message=None,
    )
