"""``kortravelmap.infra.feature_identity`` — feature identity 경계 해석 (T-VN-32C, ADR-068).

dual read/write 단계의 identity 규약을 한 곳에 고정한다:

- **정본 키는 ``feature.features.feature_uuid``** (T-VN-32A shadow → 32B dual).
  현행 문자열 ``f_*`` id는 ``feature.feature_aliases``의 legacy alias다.
- **alias 해석은 경계 전용** (ADR-068 결정 3): API path/query가 받은 외부 참조
  문자열은 :func:`resolve_feature_identity` 한 곳에서만 UUID/alias 양쪽으로
  해석하고, 내부 전달·조인은 해석된 정본 키로만 한다. repository 내부에
  alias lookup을 흩뿌리지 않는다.
- **정본 신규 행 generator (T-VN-32C·alembic 0083)** — 신규 행의
  ``feature_uuid``는 **비파생 UUIDv7**이다
  (:func:`candidate_feature_uuid` → :func:`kortravelmap.core.ids.make_feature_uuid`).
  32A/32B의 dual 기간에는 uuid5 파생이 유일 generator였고 그 근거는 KTM/PinVi
  양 저장소 독립 계산·checksum 대조였는데, 2026-08-05 실측으로 checksum이
  일치해 그 전제가 소진됐다 — 이후 이관 검증은 파생 재계산이 아니라 저장값
  기반 merkle 대조 + DB 복합 FK 사본 일치로 한다. 기존 backfill 세대의 파생값은
  영구 보존되며(0082 identity fence) :func:`expected_feature_uuid`는 그 세대의
  **참조 전용**으로 남는다.
- **legacy-only 신규 행 차단의 계약화**: DB 층은 0080 트리거 2종이 이미 원자
  보장한다. 그 위에 repo writer가 ``feature_uuid`` 후보를 명시 INSERT하고,
  RETURNING 관측값이 canonical UUID가 아니거나(legacy-only) 신규 insert인데
  보낸 후보와 다르면(generator 이원화) :class:`FeatureIdentityInvariantError`로
  fail-close한다 (:func:`candidate_feature_uuid` / :func:`verify_feature_uuid`).

32C PR-1(값 전환)이 긋는 범위 경계 (이월 명시):

- 응답의 ``feature_id`` 값 자체는 legacy 유지, ``feature_uuid``는 additive 병행
  노출 — 응답 UUID 전환(PinVi cutover)은 후속 PR 소관이다.
- 내부 FK 체인(source_links/curation/price/weather 등)의 UUID 조인 재작성은
  T-VN-39 소관.
- 0080 fill/alias 트리거 제거(writer 원자 생성으로 완전 대체)는 raw SQL seed
  경로가 남아 있는 동안 하지 않는다 — 0083은 트리거를 유지하되 본문을 app과
  같은 v7 레이아웃(``feature.uuid_generate_v7()``)으로 맞춰 이원화만 막았다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

from kortravelmap.core.ids import feature_uuid_from_legacy, make_feature_uuid

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FeatureIdentity",
    "FeatureIdentityRefError",
    "FeatureIdentityInvariantError",
    "MAX_FEATURE_REF_LENGTH",
    "candidate_feature_uuid",
    "expected_feature_uuid",
    "validate_feature_ref",
    "verify_feature_uuid",
    "resolve_feature_identity",
    "resolve_feature_identities_bulk",
    "get_feature_uuid_map",
    "count_features_missing_identity",
]


MAX_FEATURE_REF_LENGTH: Final[int] = 256
"""경계가 수용하는 feature 참조 문자열 최대 길이.

기존 경계 상한(``weather_repo.WEATHER_BATCH_MAX_FEATURE_ID_LENGTH`` = 256)과
정합 — legacy id는 실측 최대 수십 자, canonical UUID는 36자다.
"""

_CANONICAL_UUID_LENGTH: Final[int] = 36
_UUID_HYPHEN_POSITIONS: Final[tuple[int, ...]] = (8, 13, 18, 23)


class FeatureIdentityRefError(ValueError):
    """경계가 받은 feature 참조 문자열이 형식 계약을 위반했다 (HTTP 422 대응)."""


class FeatureIdentityInvariantError(RuntimeError):
    """uuid 없는(또는 비정규·후보와 다른) 신규 feature 행 관측 — fail-close.

    DB 층(0080 트리거 + NOT NULL)이 뚫린 상태로 write가 계속되면 alias-map
    checksum 대조가 조용히 갈라지므로, writer는 갱신을 계속하는 대신 즉시
    실패한다.
    """


@dataclass(frozen=True)
class FeatureIdentity:
    """경계 해석 결과 — legacy 키와 UUID 정본 키 쌍."""

    feature_id: str
    feature_uuid: str


def expected_feature_uuid(feature_id: str) -> str:
    """이 legacy id의 **파생** ``feature_uuid`` (backfill/검증 참조 전용).

    ``uuid5(FEATURE_UUID_NAMESPACE, feature_id)`` — 0080 backfill이 기존 행에
    영구 각인한 값이다. **T-VN-32C 값 전환(0083)부터 신규 행의 정본 generator가
    아니다** — 신규 행은 :func:`candidate_feature_uuid`(비파생 UUIDv7)를 쓴다.
    """
    return str(feature_uuid_from_legacy(feature_id))


def candidate_feature_uuid() -> str:
    """신규 행 INSERT 후보 ``feature_uuid`` — 비파생 UUIDv7 (0083 정본 generator).

    upsert의 ON CONFLICT 경로에서는 이 후보가 **버려지고** 기존 저장값이
    정본으로 남는다(``feature_uuid``는 ON CONFLICT 갱신 대상이 아님 + 0082
    identity fence). 관측 정합은 :func:`verify_feature_uuid`가 맡는다.
    """
    return str(make_feature_uuid())


def verify_feature_uuid(
    feature_id: str,
    observed_feature_uuid: object,
    *,
    sent_feature_uuid: str | None = None,
    inserted: bool | None = None,
) -> str:
    """write 경로가 ``RETURNING``으로 관측한 ``feature_uuid``를 검증한다 (fail-close).

    0083(비파생 generator) 이후의 불변식:

    - 관측값은 **비어 있지 않은 canonical UUID**여야 한다 — legacy-only 행
      (트리거·명시 INSERT 모두 실패) 탐지는 유지된다.
    - ``inserted=True``(``xmax = 0``)이면 관측값은 우리가 보낸 후보와 같아야
      한다 — 트리거/타 경로가 후보를 바꿔치기하면 generator 이원화이므로
      fail-close.
    - ``inserted=False``(conflict-update)면 **기존 저장값이 정본**이다 — 후보와
      달라도 정상(파생 대조는 폐기: 기존 행은 파생값, 신규 행은 비파생값이
      공존하는 세계).

    Parameters
    ----------
    feature_id
        legacy feature id (write 대상 행의 PK — 진단용).
    observed_feature_uuid
        INSERT/UPSERT ``RETURNING``으로 관측한 값 (driver에 따라 str/UUID).
    sent_feature_uuid
        INSERT에 바인드한 후보 (canonical 소문자). ``inserted`` 판정이 가능한
        호출부만 전달한다.
    inserted
        ``RETURNING (xmax = 0)`` 관측값. ``None``이면 insert/update 구분 없이
        canonical 검증만 수행한다.

    Returns
    -------
    str
        canonical 소문자 UUID 문자열 (관측값).

    Raises
    ------
    FeatureIdentityInvariantError
        관측값이 비어 있거나 canonical UUID가 아니거나, 신규 insert의 관측값이
        보낸 후보와 다른 경우.
    """
    observed = str(observed_feature_uuid).lower() if observed_feature_uuid else None
    canonical = _parse_canonical_uuid(observed) if observed else None
    if canonical is None:
        raise FeatureIdentityInvariantError(
            "feature identity invariant 위반 — legacy-only(또는 비정규 uuid) 행 "
            f"관측: feature_id={feature_id!r}, observed={observed!r} "
            "(ADR-068 / T-VN-32C fail-close)."
        )
    if inserted is True and sent_feature_uuid is not None and canonical != sent_feature_uuid:
        raise FeatureIdentityInvariantError(
            "feature identity invariant 위반 — 신규 insert의 관측 uuid가 보낸 "
            f"후보와 다름(generator 이원화): feature_id={feature_id!r}, "
            f"sent={sent_feature_uuid!r}, observed={canonical!r} "
            "(ADR-068 / T-VN-32C fail-close)."
        )
    return canonical


def _parse_canonical_uuid(ref: str) -> str | None:
    """canonical hyphenated UUID 문자열이면 소문자 정규형, 아니면 ``None``.

    ``uuid.UUID``는 hex-only/braced/URN 형태도 수용하지만, 경계는 응답이
    내보내는 canonical 형태(36자, hyphen 위치 고정)만 UUID로 취급한다 — 그 외
    문자열은 전부 opaque alias 후보다 (ADR-068 "opaque string" 계약).
    """
    if len(ref) != _CANONICAL_UUID_LENGTH:
        return None
    if any(ref[pos] != "-" for pos in _UUID_HYPHEN_POSITIONS):
        return None
    try:
        parsed = uuid.UUID(ref)
    except ValueError:
        return None
    return str(parsed)


def validate_feature_ref(ref: str) -> str:
    """경계 참조 문자열의 형식 계약 검증 — 위반 시 :class:`FeatureIdentityRefError`.

    alias canonical CHECK(``alias <> '' AND alias = btrim(alias)``)와 같은
    규칙에 길이 상한을 더한다. 통과한 문자열을 그대로 반환한다.
    """
    if not ref:
        raise FeatureIdentityRefError("feature 참조는 비어 있을 수 없습니다.")
    if ref != ref.strip():
        raise FeatureIdentityRefError(
            "feature 참조는 앞뒤 공백 없이 전달해야 합니다 (canonical alias 계약)."
        )
    if len(ref) > MAX_FEATURE_REF_LENGTH:
        raise FeatureIdentityRefError(
            f"feature 참조는 {MAX_FEATURE_REF_LENGTH}자 이하여야 합니다."
        )
    return ref


# UUID 정본 조회 — features가 정본이고 alias table은 경계 해석 입구다.
# alias 행의 feature_uuid 사본이 아니라 features의 정본 값을 읽는다.
_RESOLVE_BY_UUID_SQL: Final[str] = """
SELECT feature_id, CAST(feature_uuid AS text) AS feature_uuid
FROM feature.features
WHERE feature_uuid = CAST(:feature_uuid AS uuid)
"""

_RESOLVE_BY_ALIAS_SQL: Final[str] = """
SELECT f.feature_id, CAST(f.feature_uuid AS text) AS feature_uuid
FROM feature.feature_aliases AS a
JOIN feature.features AS f
  ON f.feature_id = a.feature_id
WHERE a.alias = :alias
"""

_FEATURE_UUID_MAP_SQL: Final[str] = """
SELECT feature_id, CAST(feature_uuid AS text) AS feature_uuid
FROM feature.features
WHERE feature_id = ANY(CAST(:feature_ids AS text[]))
"""

# INV-068-01(모든 feature는 alias ≥ 1)과 uuid 결측을 현행 스키마에서 관측한다.
# feature_uuid는 NOT NULL이라 정상 세계에서 셋 다 0이다 — 0이 아니면 DB 층
# 보장이 뚫린 것이므로 호출자는 fail-close한다. alias_pair_mismatch는 0083의
# 비파생 세계에서 새로 열리는 결함 계열(replica-mode orphan alias + 재-INSERT
# → 사본 불일치 — FK는 child DML에서만 검사)의 보상 관측이다 (적대 리뷰 1 H3).
_MISSING_IDENTITY_SQL: Final[str] = """
SELECT
    count(*) FILTER (WHERE f.feature_uuid IS NULL) AS missing_uuid,
    count(*) FILTER (WHERE a.alias IS NULL) AS missing_alias,
    count(*) FILTER (
        WHERE a.alias IS NOT NULL
          AND a.feature_uuid IS DISTINCT FROM f.feature_uuid
    ) AS alias_pair_mismatch,
    (
        SELECT count(*)
        FROM feature.feature_aliases AS orphan
        LEFT JOIN feature.features AS parent
          ON parent.feature_id = orphan.feature_id
        WHERE parent.feature_id IS NULL
    ) AS orphan_alias
FROM feature.features AS f
LEFT JOIN feature.feature_aliases AS a
  ON a.feature_id = f.feature_id
 AND a.alias_kind = 'legacy_feature_id'
"""


async def resolve_feature_identity(
    session: AsyncSession, ref: str
) -> FeatureIdentity | None:
    """경계가 받은 참조(legacy alias 또는 canonical UUID)를 정본 키 쌍으로 해석.

    해석 규칙 (결정적 우선순위):

    1. canonical UUID 형태(36자 hyphenated)면 ``features.feature_uuid`` 정본
       조회를 먼저 시도한다.
    2. 그 외(또는 1이 miss면) ``feature_aliases`` alias 조회로 해석한다 —
       legacy id는 임의 문자열일 수 있으므로 UUID처럼 보이는 alias도 놓치지
       않는다.

    Parameters
    ----------
    session
        AsyncSession.
    ref
        API path/query에서 받은 외부 참조 문자열.

    Returns
    -------
    FeatureIdentity | None
        해석 성공 시 정본 키 쌍, 어느 쪽으로도 해석 불가면 ``None`` (HTTP 404).

    Raises
    ------
    FeatureIdentityRefError
        형식 계약 위반 (빈 문자열/공백 패딩/길이 초과 — HTTP 422).
    """
    validate_feature_ref(ref)
    canonical_uuid = _parse_canonical_uuid(ref)
    if canonical_uuid is not None:
        row = (
            (
                await session.execute(
                    text(_RESOLVE_BY_UUID_SQL), {"feature_uuid": canonical_uuid}
                )
            )
            .mappings()
            .first()
        )
        if row is not None:
            return FeatureIdentity(
                feature_id=str(row["feature_id"]),
                feature_uuid=str(row["feature_uuid"]),
            )
    row = (
        (await session.execute(text(_RESOLVE_BY_ALIAS_SQL), {"alias": ref}))
        .mappings()
        .first()
    )
    if row is None:
        return None
    return FeatureIdentity(
        feature_id=str(row["feature_id"]),
        feature_uuid=str(row["feature_uuid"]),
    )


async def get_feature_uuid_map(
    session: AsyncSession, feature_ids: Sequence[str]
) -> dict[str, str]:
    """legacy id 목록 → ``feature_uuid`` 정본 map (additive 병행 노출용).

    복잡한 조회 SQL(예: weather batch)을 재작성하지 않고 응답에 ``feature_uuid``
    를 병행 노출할 때 사용한다. 존재하지 않는 id는 결과에서 빠진다.
    """
    normalized = [feature_id for feature_id in feature_ids if feature_id]
    if not normalized:
        return {}
    rows = (
        (
            await session.execute(
                text(_FEATURE_UUID_MAP_SQL), {"feature_ids": normalized}
            )
        )
        .mappings()
        .all()
    )
    return {str(row["feature_id"]): str(row["feature_uuid"]) for row in rows}


_RESOLVE_BULK_BY_UUID_SQL: Final[str] = """
SELECT feature_id, CAST(feature_uuid AS text) AS feature_uuid
FROM feature.features
WHERE feature_uuid = ANY(CAST(:feature_uuids AS uuid[]))
"""

_RESOLVE_BULK_BY_ALIAS_SQL: Final[str] = """
SELECT a.alias, f.feature_id, CAST(f.feature_uuid AS text) AS feature_uuid
FROM feature.feature_aliases AS a
JOIN feature.features AS f
  ON f.feature_id = a.feature_id
WHERE a.alias = ANY(CAST(:aliases AS text[]))
"""


async def resolve_feature_identities_bulk(
    session: AsyncSession, refs: Sequence[str]
) -> dict[str, FeatureIdentity]:
    """여러 외부 참조를 고정 왕복 2회로 정본 키 쌍에 해석한다 (T-VN-32C PR-2).

    write/scope 입력이 목록으로 받은 참조(legacy alias·canonical UUID 혼재
    가능)를 :func:`resolve_feature_identity`와 **같은 우선순위**(UUID 정본
    조회 → alias 조회 fallback)로 일괄 해석한다. 해석 불가 참조는 결과 dict
    에서 빠진다 — 호출자가 miss를 어떻게 처리할지(422/무시)는 표면 계약이다.

    형식 계약 위반(빈 문자열/공백 패딩/길이 초과)은 단건과 동일하게
    :class:`FeatureIdentityRefError`를 던진다.
    """
    resolved: dict[str, FeatureIdentity] = {}
    unique_refs: list[str] = []
    seen: set[str] = set()
    for ref in refs:
        validate_feature_ref(ref)
        if ref not in seen:
            seen.add(ref)
            unique_refs.append(ref)
    if not unique_refs:
        return resolved
    uuid_refs = {
        ref: canonical
        for ref in unique_refs
        if (canonical := _parse_canonical_uuid(ref)) is not None
    }
    if uuid_refs:
        rows = (
            (
                await session.execute(
                    text(_RESOLVE_BULK_BY_UUID_SQL),
                    {"feature_uuids": list(uuid_refs.values())},
                )
            )
            .mappings()
            .all()
        )
        by_uuid = {
            str(row["feature_uuid"]): FeatureIdentity(
                feature_id=str(row["feature_id"]),
                feature_uuid=str(row["feature_uuid"]),
            )
            for row in rows
        }
        for ref, canonical in uuid_refs.items():
            identity = by_uuid.get(canonical)
            if identity is not None:
                resolved[ref] = identity
    # UUID 정본 조회가 miss한 UUID형 참조도 alias fallback에 포함한다 —
    # legacy id는 임의 문자열이라 UUID처럼 보이는 alias가 있을 수 있다
    # (단건 해석 규칙 2와 동일).
    alias_refs = [ref for ref in unique_refs if ref not in resolved]
    if alias_refs:
        rows = (
            (
                await session.execute(
                    text(_RESOLVE_BULK_BY_ALIAS_SQL), {"aliases": alias_refs}
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            resolved[str(row["alias"])] = FeatureIdentity(
                feature_id=str(row["feature_id"]),
                feature_uuid=str(row["feature_uuid"]),
            )
    return resolved


async def count_features_missing_identity(
    session: AsyncSession,
) -> tuple[int, int, int, int]:
    """(uuid 결측, alias 결측, alias 쌍 불일치, orphan alias) — 정상 ``(0,0,0,0)``.

    freeze INV-068-01의 현행 스키마 판(post-backfill)이다. 회귀 테스트와
    운영 점검이 사용하고, 0이 아니면 write 경로를 계속 신뢰하지 말고
    fail-close해야 한다 (:class:`FeatureIdentityInvariantError`의 사전 관측판).
    셋째 축(사본 불일치)·넷째 축(부모 없는 orphan alias — replica-mode DELETE
    잔재이자 0083 FK 추가가 실패하는 유일 시나리오, 재판정 M7)은 비파생
    세계의 신규 결함 계열 보상 관측이다 — 0083 배포 사전 점검 쿼리와 동일 축.
    """
    row = (await session.execute(text(_MISSING_IDENTITY_SQL))).mappings().one()
    return (
        int(row["missing_uuid"]),
        int(row["missing_alias"]),
        int(row["alias_pair_mismatch"]),
        int(row["orphan_alias"]),
    )
