"""ADR115 후보 수집과 명시 scoped scalar 투영. 정책 미설정은 SQL0회다."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto.provider_field_presence import ProviderFieldPresence

_SHADOW_SCOPES_INFO_KEY: Final[str] = "kortravelmap.provider_field_shadow_scopes"
_SHADOW_REVISION_INFO_KEY: Final[str] = "kortravelmap.provider_field_shadow_revision"
_RECORD_SQL: Final[str] = """
CALL feature.record_provider_field_candidates(
    CAST(:feature_id AS uuid), CAST(:dataset_id AS bigint),
    :entity_key, :record_key, CAST(:policy_revision AS bigint),
    :normalizer_revision, CAST(:presence_proven AS boolean),
    CAST(:values AS jsonb), CAST(:geometry_wkt AS jsonb), NULL, NULL
)
"""

_SCOPED_RECORD_SQL: Final[str] = """
CALL feature.record_scoped_provider_field_candidates(
    CAST(:attempt_id AS uuid), CAST(:feature_id AS uuid), CAST(:dataset_id AS bigint),
    :entity_key, :record_key, CAST(:policy_revision AS bigint),
    :normalizer_revision, CAST(:presence_proven AS boolean),
    CAST(:values AS jsonb), CAST(:geometry_wkt AS jsonb), NULL, NULL
)
"""


@dataclass(frozen=True)
class CandidateShadowCoverage:
    field_count: int
    unresolved_count: int


def arm_provider_field_shadow(
    session: AsyncSession,
    revision: int | None,
    scopes: frozenset[tuple[str, str]] = frozenset(),
) -> None:
    """선택한 shadow 정책 revision만 transaction에 배선한다. 기본 None은 SQL0회다."""
    if revision is not None and (type(revision) is not int or revision < 1):
        raise ValueError("shadow policy revision은 양의 정수여야 합니다.")
    session.info[_SHADOW_REVISION_INFO_KEY] = revision
    session.info[_SHADOW_SCOPES_INFO_KEY] = scopes


def provider_field_shadow_enabled(
    session: AsyncSession, *, provider: str, dataset_key: str
) -> bool:
    info = getattr(session, "info", None)
    return (
        isinstance(info, dict)
        and info.get(_SHADOW_REVISION_INFO_KEY) is not None
        and (provider, dataset_key) in info.get(_SHADOW_SCOPES_INFO_KEY, frozenset())
    )


async def capture_provider_field_candidates(
    session: AsyncSession,
    *,
    feature_id: str,
    dataset_id: int,
    entity_key: str,
    record_key: str,
    values: str,
    geometry_wkt: str,
    presence: ProviderFieldPresence | None,
    attempt_id: str | None = None,
) -> CandidateShadowCoverage | None:
    """이미 같은 전역 fence 아래 물화한 typed patch의 source별 shadow를 기록한다.

    정책 미설정이면 DB를 읽지 않는다. 원천 presence 증거가 없으면 모든 선언 필드가
    unresolved이며, 별도 enable gate가 이를 승인 coverage로 간주해서는 안 된다.
    """
    revision = session.info.get(_SHADOW_REVISION_INFO_KEY)
    if revision is None:
        if attempt_id is not None:
            raise ValueError("scoped capture에는 명시적으로 선택한 정책이 필요합니다.")
        return None
    scalar = json.loads(values)
    geometry = json.loads(geometry_wkt)
    if presence is not None:
        unknown = presence.supplied_fields - (scalar.keys() | geometry.keys())
        if unknown:
            raise ValueError(
                "supplied field가 typed patch에 없습니다: " + ",".join(sorted(unknown))
            )
        scalar = {key: value for key, value in scalar.items() if key in presence.supplied_fields}
        geometry = {
            key: value for key, value in geometry.items() if key in presence.supplied_fields
        }
    else:
        scalar, geometry = {}, {}
    row = (
        (
            await session.execute(
                text(_RECORD_SQL if attempt_id is None else _SCOPED_RECORD_SQL),
                {
                    "attempt_id": attempt_id,
                    "feature_id": feature_id,
                    "dataset_id": dataset_id,
                    "entity_key": entity_key,
                    "record_key": record_key,
                    "policy_revision": revision,
                    "normalizer_revision": presence.normalizer_revision if presence else None,
                    "presence_proven": presence is not None,
                    "values": json.dumps(scalar, ensure_ascii=False),
                    "geometry_wkt": json.dumps(geometry, ensure_ascii=False),
                },
            )
        )
        .mappings()
        .one()
    )
    return CandidateShadowCoverage(int(row["o_field_count"]), int(row["o_unresolved_count"]))


async def lock_provider_field_policy_epoch(session: AsyncSession) -> None:
    """kernel gate 뒤, begin의 dataset/source/Feature 잠금 전에 epoch에 진입한다."""
    await session.execute(text("SELECT feature.lock_provider_field_policy_epoch()"))


async def recompute_provider_field_candidates(
    session: AsyncSession, *, attempt_id: str, feature_id: str, policy_revision: int
) -> None:
    """같은 applying TX의 완결 manifest 안에서만 활성 scalar winner를 물화한다."""
    if type(policy_revision) is not int or policy_revision < 1:
        raise ValueError("정책 revision은 양의 정수여야 합니다.")
    await session.execute(
        text("""CALL feature.recompute_provider_field_candidates(
            CAST(:attempt AS uuid),CAST(:feature AS uuid),CAST(:revision AS bigint))"""),
        {"attempt": attempt_id, "feature": feature_id, "revision": policy_revision},
    )
