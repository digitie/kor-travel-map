"""이미지 안에서 생성·검증한 실제 설치 inventory로 공항 snapshot pin을 구성한다."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from kortravelmap.infra.provider_snapshot_artifact import SnapshotArtifactPins
from kortravelmap.providers.kor_travel_transport_native import AIRPORT_NAME_NORMALIZER_REVISION

# Airport는 Transport HTTP와 Map converter를 사용한다. 외부 공항 SDK는 사용하지 않는다.
# DTO/직렬화/HTTP/DB/실행에 직접 참여하는 설치본만 한 번 검증한다.
_DISTRIBUTIONS = (
    "kor-travel-map",
    "kor-travel-map-dagster",
    "dagster",
    "pydantic",
    "pydantic-core",
    "httpx",
    "httpcore",
    "kor-travel-common",
    "SQLAlchemy",
    "asyncpg",
)
_RECEIPT = Path("/opt/dagster/airport-snapshot-runtime.json")
_MAX_FILES = 8192
_MAX_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class AirportSnapshotRuntime:
    pins: SnapshotArtifactPins


def installed_airport_inventory() -> dict[str, object]:
    """실제 파일 내용을 읽는다. 버전 문자열이나 환경변수 hash를 출처로 간주하지 않는다."""
    packages: dict[str, object] = {}
    count = size = 0
    for name in _DISTRIBUTIONS:
        dist = importlib.metadata.distribution(name)
        files = dist.files
        if files is None:
            raise RuntimeError("snapshot inventory requires installed distribution file lists")
        sources: dict[str, str] = {}
        for relative in sorted(files, key=str):
            if relative.suffix not in {".py", ".so", ".pyd"}:
                continue
            # RECORD의 entrypoint ../bin은 실행 계약에 포함하지 않는다.
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError("snapshot source path must stay within its installation")
            source = Path(str(dist.locate_file(relative)))
            if source.is_symlink() or not source.is_file():
                raise RuntimeError("snapshot inventory requires regular installed source files")
            length = source.stat().st_size
            count += 1
            size += length
            if count > _MAX_FILES or size > _MAX_BYTES:
                raise RuntimeError("snapshot installed source inventory exceeds its budget")
            raw = source.read_bytes()
            if len(raw) != length:
                raise RuntimeError("snapshot installed source changed while reading")
            sources[str(relative)] = hashlib.sha256(raw).hexdigest()
        if not sources:
            raise RuntimeError("snapshot distribution has no verifiable source files")
        packages[name] = {"version": dist.version, "files": sources}
    return {"version": 1, "python": list(sys.version_info[:3]), "packages": packages}


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()


def write_airport_runtime_receipt(path: Path = _RECEIPT) -> None:
    """Docker build의 설치 완료 뒤, root 소유 image layer에만 생성한다."""
    revision = os.environ.get("KOR_TRAVEL_MAP_IMAGE_REVISION", "")
    if not re.fullmatch("[0-9a-f]{40}", revision):
        # development image도 기존 EX 경로로 빌드할 수 있다. snapshot opt-in은 실패한다.
        return
    value = {"version": 1, "code_revision": revision, "inventory": installed_airport_inventory()}
    with path.open("xb") as target:
        target.write(_canonical(value))
    path.chmod(0o444)


def load_airport_snapshot_runtime() -> AirportSnapshotRuntime | None:
    enabled = os.environ.get("KOR_TRAVEL_MAP_AIRPORT_SNAPSHOT_ENABLED", "0")
    if enabled == "0":
        return None
    if enabled != "1":
        raise RuntimeError("airport snapshot enabled must be 0 or 1")
    revision = os.environ.get("KOR_TRAVEL_MAP_IMAGE_REVISION", "")
    if not re.fullmatch("[0-9a-f]{40}", revision):
        raise RuntimeError("airport snapshot requires an immutable image revision")
    if _RECEIPT.is_symlink() or not _RECEIPT.is_file() or _RECEIPT.stat().st_size > 2**20:
        raise RuntimeError("airport snapshot build receipt is missing or exceeds its budget")
    receipt = _RECEIPT.read_bytes()
    inventory = installed_airport_inventory()
    expected = {"version": 1, "code_revision": revision, "inventory": inventory}
    if receipt != _canonical(expected):
        raise RuntimeError("airport snapshot installed source differs from the image build receipt")
    return AirportSnapshotRuntime(
        SnapshotArtifactPins(
            code_revision=revision,
            sdk_inventory_sha256=hashlib.sha256(_canonical(inventory)).hexdigest(),
            provider="kor-travel-transport",
            dataset_key="transport_airports",
            source_entity_type="airport",
            normalizer_revision=AIRPORT_NAME_NORMALIZER_REVISION,
            geo_domain="transport-airport-geo-v1",
            clock_domain="aware-clock-preserved-v1",
        )
    )
