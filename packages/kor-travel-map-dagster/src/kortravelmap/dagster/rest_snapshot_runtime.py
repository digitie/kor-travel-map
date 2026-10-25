"""Rest snapshot은 기본 OFF이며 이미지의 실제 설치 inventory만 pin 근거로 쓴다."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

from kortravelmap.infra.provider_snapshot_artifact import SnapshotArtifactPins
from kortravelmap.providers.kor_travel_transport_native import REST_AREA_SCALAR_NORMALIZER_REVISION

from .airport_snapshot_runtime import _RECEIPT, _canonical, installed_airport_inventory


@dataclass(frozen=True)
class RestSnapshotRuntime:
    pins: SnapshotArtifactPins


def load_rest_snapshot_runtime() -> RestSnapshotRuntime | None:
    """기존 build receipt가 전체 설치 파일을 포함한다. 환경 hash를 실행 권위로 받지 않는다."""
    enabled = os.environ.get("KOR_TRAVEL_MAP_REST_SNAPSHOT_ENABLED", "0")
    if enabled == "0":
        return None
    if enabled != "1":
        raise RuntimeError("rest snapshot enabled must be 0 or 1")
    revision = os.environ.get("KOR_TRAVEL_MAP_IMAGE_REVISION", "")
    if not re.fullmatch("[0-9a-f]{40}", revision):
        raise RuntimeError("rest snapshot requires an immutable image revision")
    if _RECEIPT.is_symlink() or not _RECEIPT.is_file() or _RECEIPT.stat().st_size > 2**20:
        raise RuntimeError("rest snapshot build receipt is missing or exceeds its budget")
    inventory = installed_airport_inventory()
    expected = {"version": 1, "code_revision": revision, "inventory": inventory}
    if _RECEIPT.read_bytes() != _canonical(expected):
        raise RuntimeError("rest snapshot installed source differs from the image build receipt")
    return RestSnapshotRuntime(
        SnapshotArtifactPins(
            code_revision=revision,
            sdk_inventory_sha256=hashlib.sha256(_canonical(inventory)).hexdigest(),
            provider="kor-travel-transport",
            dataset_key="transport_rest_areas",
            source_entity_type="rest_area",
            normalizer_revision=REST_AREA_SCALAR_NORMALIZER_REVISION,
            geo_domain="transport-rest-area-geo-v1",
            clock_domain="aware-clock-preserved-v1",
        )
    )
