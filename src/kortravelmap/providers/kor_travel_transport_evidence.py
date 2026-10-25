"""공항 DB snapshot과 최종 converter 입력을 비교하는 비활성 준비 경계.

쓰기/잠금/attempt 생성이나 Geo 호출은 없다. 성공도 이후 kernel 잠금 뒤 DB 재검증을
대신하지 않는다. 입력과 Geo 관측 집합은 await 동안 호출자가 독점 소유한다.
"""

from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from kortravelmap.dto import Address, FeatureBundle, SourceRecord
from kortravelmap.dto.geo_dataset import DatasetRef, GeoApplied, GeoLoadContext
from kortravelmap.infra.exclusive_provider_refresh import (
    ExclusiveProviderSnapshotOptions,
    bounded_full_snapshot,
)
from kortravelmap.infra.feature_repo import (
    _make_source_entity_key,
    _provider_field_patch_payload,
)
from kortravelmap.infra.transport_airport_evidence import (
    AIRPORT_ADDRESS_FIELDS,
    AirportGeoFacts,
)
from kortravelmap.infra.transport_airport_evidence_reader import (
    AirportEvidenceEnvelope,
    read_transport_airport_evidence,
)
from kortravelmap.providers.kor_travel_transport import (
    DATASET_KEY_AIRPORTS,
    KOR_TRAVEL_TRANSPORT_PROVIDER_NAME,
)
from kortravelmap.providers.kor_travel_transport_native import (
    TransportGeoEvidence,
    assess_transport_scalar_refresh,
    rebuild_transport_projection,
)

_OPTIONS = ExclusiveProviderSnapshotOptions(
    KOR_TRAVEL_TRANSPORT_PROVIDER_NAME, DATASET_KEY_AIRPORTS, "airport"
)


@dataclass(frozen=True)
class AirportReobservationPreparation:
    """전체 입력/DB EOF의 비교 진단. upstream EOF나 apply 권한을 표현하지 않는다."""

    eligible: bool
    reason: str
    evidence: AirportEvidenceEnvelope
    input_eof: bool = True

    @property
    def collector_ready(self) -> bool:
        return False

    @property
    def requires_database_reverification(self) -> bool:
        return True


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _source(item: dict[str, Any], row: dict[str, Any]) -> SourceRecord:
    entity = item["source_entity"]
    return SourceRecord(
        provider=_OPTIONS.provider,
        dataset_key=_OPTIONS.dataset_key,
        source_entity_type=_OPTIONS.source_entity_type,
        source_entity_id=entity["source_entity_id"],
        source_record_key=row["source_record_key"],
        raw_payload_hash=row["raw_payload_hash"],
        raw_data=row["raw_data"],
        fetched_at=_instant(row["fetched_at"]),
        imported_at=_instant(row["imported_at"]),
        expires_at=None,
    )


def _geo_context_valid(geo: GeoLoadContext | None) -> bool:
    # 일반 serializer/foreign DTO를 호출하기 전에 실제 class와 관측 집합의 폭을 제한한다.
    if geo is None:
        return True
    if type(geo) is not GeoLoadContext or type(geo.geo_applied) is not GeoApplied:
        return False
    if any(type(flag) is not bool for flag in (geo.geo_applied.reverse, geo.geo_applied.geocode)):
        return False
    if geo.current_dataset is not None and type(geo.current_dataset) is not DatasetRef:
        return False
    observed = geo.observed_data_tokens
    return observed is None or (
        type(observed) in (set, frozenset)
        and len(observed) <= 32
        and all(type(token) is str and len(token) <= 256 for token in observed)
    )


def _geo(item: dict[str, Any], dataset_id: int, geo: GeoLoadContext | None) -> TransportGeoEvidence:
    feature, stamp, record = item["feature"], item["geocode_stamp"], item["current_record"]
    if feature["coord_sql_null"]:
        if geo is not None and (geo.geo_applied.reverse or geo.geo_applied.geocode):
            raise ValueError("unsupported_geo_context")
        if stamp is not None and stamp["reverse_outcome"] != "not_called":
            raise ValueError("unsupported_geo_stamp")
        return TransportGeoEvidence("not_requested")
    if (
        geo is None
        or not geo.geo_applied.reverse
        or geo.geo_applied.geocode
        or geo.current_dataset is None
        or geo.effective_token() is None
        or stamp is None
        or stamp["reverse_outcome"] != "called"
        or stamp["geo_version_token"] != geo.current_dataset.version_token
        or stamp["geo_data_token"] != geo.effective_token()
    ):
        raise ValueError("unproven_geo_reuse")
    address = Address.model_validate(feature["address"])
    facts = AirportGeoFacts(
        dataset_id=dataset_id,
        source_entity_key=item["source_entity"]["source_entity_key"],
        source_record_key=record["source_record_key"],
        raw_payload_hash=record["raw_payload_hash"],
        feature_id=UUID(feature["feature_id"]),
        coordinate_ewkb=feature["geometry_ewkb"],
        address=tuple(getattr(address, key) for key in AIRPORT_ADDRESS_FIELDS),
        geo_version_token=stamp["geo_version_token"],
        geo_data_token=stamp["geo_data_token"],
        reverse_outcome=stamp["reverse_outcome"],
        stamped_at=_instant(stamp["stamped_at"]),
    )
    return TransportGeoEvidence(
        "resolved", facts.geo_version_token, facts.geo_data_token, address, facts.digest()
    )


def _matches_base(bundle: FeatureBundle, item: dict[str, Any]) -> bool:
    values = json.loads(
        _provider_field_patch_payload(
            bundle.feature, feature_uuid=item["feature"]["feature_id"], parent_feature_id=None
        )[0]
    )
    coord = bundle.feature.coord
    ewkb = (
        None
        if coord is None
        else struct.pack("<BIIdd", 1, 0x20000001, 4326, float(coord.lon), float(coord.lat)).hex()
    )
    for row in item["non_name_base"]:
        path = row["field_path"]
        if path == "core.coord":
            if row["geometry_ewkb"] != ewkb or row["value_geometry_sql_null"] != (ewkb is None):
                return False
            if row["value_json"] is not None or row["value_json_sql_null"] != (ewkb is not None):
                return False
        elif (
            row["value_json"] != values[path]
            or row["value_json_sql_null"]
            or not row["value_geometry_sql_null"]
        ):
            return False
    return True


async def prepare_transport_airport_reobservation(
    session: AsyncSession,
    bundles: Iterable[FeatureBundle],
    *,
    dataset_id: int,
    geo: GeoLoadContext | None = None,
) -> AirportReobservationPreparation:
    """전체 최종 입력을 예산 검사한 뒤 같은 RR/read-only snapshot의 DB EOF와 비교한다.

    known 입력/Geo/의미 불일치는 거부 진단이며 SQL 오류·취소·timeout은 그대로 전파한다.
    DB 이후 입력이나 Geo 관측 집합을 변경하면 결과를 재사용할 수 없다.
    """
    if not _geo_context_valid(geo):
        raise ValueError("invalid canonical airport Geo context")
    ordered = bounded_full_snapshot(
        bundles, options=_OPTIONS, geo=geo, retire_geometryless_areas=True
    )
    async with asyncio.timeout(3):
        evidence = await read_transport_airport_evidence(session, dataset_id)
        return await assess_transport_airport_reobservation_evidence(ordered, evidence, geo=geo)


async def assess_transport_airport_reobservation_evidence(
    bundles: Iterable[FeatureBundle],
    evidence: AirportEvidenceEnvelope,
    *,
    geo: GeoLoadContext | None = None,
) -> AirportReobservationPreparation:
    """실제 입력과 주어진 정본 DB evidence의 의미를 다시 대조한다. DB/SDK/Geo I/O는 없다.

    apply는 잠금 뒤 fresh SD를 decode한 evidence와 실제 저장 입력을 함께 이 경계로 보낸다.
    과거 preparation의 eligible 플래그를 다른 artifact의 쓰기 권위로 재사용하지 않는다.
    """
    if not _geo_context_valid(geo) or type(evidence) is not AirportEvidenceEnvelope:
        raise ValueError("invalid canonical airport assessment context")
    dataset_id = evidence.dataset_id
    ordered = bounded_full_snapshot(
        bundles, options=_OPTIONS, geo=geo, retire_geometryless_areas=True
    )
    async with asyncio.timeout(3):
        if not evidence.evidence_complete:
            assert evidence.reason is not None
            return AirportReobservationPreparation(False, evidence.reason.value, evidence)
        incoming = {
            _make_source_entity_key(
                provider=b.source_record.provider,
                dataset_key=b.source_record.dataset_key,
                source_entity_type=b.source_record.source_entity_type,
                source_entity_id=b.source_record.source_entity_id,
            ): b
            for b in ordered
        }
        if set(incoming) != {
            cast("dict[str, Any]", i["source_entity"])["source_entity_key"] for i in evidence.items
        }:
            return AirportReobservationPreparation(False, "whole_scope_mismatch", evidence)
        for raw_item in evidence.items:
            item: dict[str, Any] = dict(raw_item)
            current = incoming[item["source_entity"]["source_entity_key"]]
            try:
                bound_geo = _geo(item, dataset_id, geo)
                base = await rebuild_transport_projection(
                    _source(item, item["base_record"]), geo=bound_geo
                )
                name = await rebuild_transport_projection(
                    _source(item, item["name_value_record"]), geo=bound_geo
                )
                if not _matches_base(base, item):
                    return AirportReobservationPreparation(
                        False, "stored_base_meaning_mismatch", evidence
                    )
                if (
                    name.feature.name != item["name_base"]["value_json"]
                    or name.feature.name != item["name_candidate"]["value_json"]
                ):
                    return AirportReobservationPreparation(
                        False, "stored_name_meaning_mismatch", evidence
                    )
                # 이름 R2와 현재 R3가 같은 raw여도 R1의 비이름 의미를 바꿀 권한은 없다.
                if not _matches_base(name, item):
                    return AirportReobservationPreparation(
                        False, "stored_nonname_history_mismatch", evidence
                    )
                previous = _source(item, item["current_record"])
                stored_current = await rebuild_transport_projection(previous, geo=bound_geo)
                if not _matches_base(stored_current, item):
                    return AirportReobservationPreparation(
                        False, "stored_nonname_history_mismatch", evidence
                    )
            except (ValueError, KeyError, TypeError):
                return AirportReobservationPreparation(
                    False, "stored_projection_unsupported", evidence
                )
            diagnostic = await assess_transport_scalar_refresh(
                previous,
                current,
                previous_normalizer_revision=item["policy"]["normalizer_revision"],
                previous_geo=bound_geo,
                current_geo=bound_geo,
            )
            if not diagnostic.eligible:
                return AirportReobservationPreparation(False, diagnostic.reason, evidence)
        return AirportReobservationPreparation(True, "unchanged_reobservation", evidence)
