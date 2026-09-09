"""``kortravelmap.infra.feature_identity`` — feature identity 경계 해석 (T-VN-32C, ADR-068).

dual read/write 단계의 identity 규약을 한 곳에 고정한다:

- **정본 키는 ``feature.features.feature_id``** (uuid). T-VN-32A shadow →
  32B dual을 거쳐, T-VN-39/alembic 309 재키가 shadow ``feature_uuid``의 값을
  ``feature_id``로 승계(text → uuid)하고 shadow 컬럼 13개를 DROP했다 — 이제
  ``feature_uuid`` 컬럼은 어느 표에도 없다.
  legacy 문자열 ``f_*`` id의 **해석 입구**는 ``feature.feature_aliases.alias``
  하나다. 값 자체는 증거로도 남는다 — 309 ``_EVIDENCE_RENAME``가
  ``feature.manual_feature_purge_records.legacy_feature_id``와
  ``ops.tvn36_legacy_freeze_preflight_manifest.legacy_feature_id``를 text로
  일부러 보존한다(개명은 legacy 문자열을 값이 아니라 이름으로 못 박기 위한 것).
- **alias 해석은 경계 전용** (ADR-068 결정 3): API path/query가 받은 외부 참조
  문자열은 :func:`resolve_feature_identity` 한 곳에서만 UUID/alias 양쪽으로
  해석하고, 내부 전달·조인은 해석된 정본 키로만 한다. repository 내부에
  alias lookup을 흩뿌리지 않는다.
- **정본 신규 행 generator (T-VN-32C·alembic 0083)** — 신규 행의 정본 키
  ``feature.features.feature_id``는 **비파생 UUIDv7**이다
  (:func:`candidate_feature_uuid` → :func:`kortravelmap.core.ids.make_feature_uuid`).
  309 뒤로 그 후보를 **누가 만드는지는 경로마다 다르다**: manual 3형제는 payload의
  ``feature_id``를 그대로 claim에 넣으므로 이 함수가 여전히 원천이고, provider
  경로는 ``feature.create_provider_feature_with_initial_state``가
  ``provider_sync.provider_feature_identities`` claim 안에서
  ``feature.uuid_generate_v7()``으로 직접 만든다(ADR-098) — 그 경로의 writer는
  자기 후보를 ``sent_feature_uuid``로 보내면 안 된다.
  32A/32B의 dual 기간에는 uuid5 파생이 유일 generator였고 그 근거는 KTM/PinVi
  양 저장소 독립 계산·checksum 대조였는데, 2026-08-05 실측으로 checksum이
  일치해 그 전제가 소진됐다 — 이후 이관 검증은 파생 재계산이 아니라 저장값
  기반 merkle 대조 + DB 복합 FK 사본 일치로 한다. 기존 backfill 세대의 파생값은
  영구 보존되며(0082 identity fence) :func:`expected_feature_uuid`는 그 세대의
  **참조 전용**으로 남는다.
- **정본 키 결측 차단의 계약화**: 309가 0080 fill 트리거를 영구 제거해 DB 층의
  자동 채움이 사라졌고, 남은 DB 보장은 ``pk_features PRIMARY KEY (feature_id)``의
  NOT NULL뿐이다. 그래서 repo writer가 정본 키(``feature_id``) 후보를 명시
  INSERT하고, RETURNING 관측값이 canonical UUID가 아니거나 신규 insert인데 보낸
  후보와 다르면(generator 이원화) :class:`FeatureIdentityInvariantError`로
  fail-close한다 (:func:`candidate_feature_uuid` / :func:`verify_feature_uuid`).

32C PR-1(값 전환)이 그었던 범위 경계는 **309가 셋 다 넘었다**:

- **응답 컬럼 이름은 그대로고 값이 uuid가 됐다.** 309 ``_VIEW_RECREATE``가
  ``feature.public_features``를 ``SELECT core.feature_id,
  CAST(core.feature_id AS text) AS feature_uuid``로 재생성한다 — 26열의 이름·순서는
  소비자 계약(INV-34C-04)이라 고정이고, ``feature_id`` 슬롯에 담기는 **값**이
  legacy ``f_*``에서 canonical uuid로 바뀌었다. 두 슬롯은 이제 같은 값의
  uuid/text 표기다.
- 내부 FK 체인(source_links/curation/price/weather 등)의 UUID 조인 재작성은 309
  ``_RETYPE_REST`` + ``_FK_RECREATE``가 끝냈다.
- **0080 fill/alias 트리거 2종은 영구 제거됐다.** 309 ``_TRIGGER_DROP``이
  ``trg_features_feature_uuid_fill``·``trg_features_legacy_alias``를 내리고
  사이드카 ``_309_fill_features_feature_uuid.sql``/
  ``_309_ensure_features_legacy_alias.sql``이 ``DROP FUNCTION``까지 낸다.
  ``_TRIGGER_RECREATE``는 그 둘을 되살리지 않는다 — 정본 키 생성도 legacy alias
  삽입도 이제 **writer 책임**이다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import text

from kortravelmap.core.ids import feature_uuid_from_legacy, make_feature_uuid

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "FeatureIdentity",
    "FeatureIdentityAnchorError",
    "FeatureIdentityRefError",
    "FeatureIdentityInvariantError",
    "MAX_FEATURE_REF_LENGTH",
    "candidate_feature_uuid",
    "expected_feature_uuid",
    "validate_feature_ref",
    "verify_feature_uuid",
    "resolve_feature_identity",
    "resolve_feature_identities_bulk",
    "resolved_uuid_or_none",
    "legacy_id_for_filter",
    "is_canonical_uuid_ref",
    "feature_uuid_in_use",
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


class FeatureIdentityAnchorError(RuntimeError):
    """provider identity 앵커와 loader가 계산한 Feature identity가 어긋났다.

    **T-VN-39 착지선.** 재키 후 ``feature.features.feature_id``는 UUIDv7이 되므로,
    오늘 멱등을 지탱하는 ``ON CONFLICT (feature_id)``의 결정적 축이 사라진다. 대체
    앵커는 ``(provider_dataset_id, feature_kind, natural_key)``이고, T-VN-39가
    ``provider_sync.provider_feature_identities``로 착지시킨다.

    **앵커 축을 두 번 틀렸고 두 번 다 실측이 잡았다.** 2026-09-08에
    ``source_links``의 ``source_role='primary'``를 축으로 잡아 UNIQUE를 심었다가 통합
    17건이 빨개졌다(identity 이행 중에는 구·신 Feature가 둘 다 primary다). 되돌린 뒤
    2026-09-09 조사가 **축 자체가 틀렸다**는 것을 보였다 — opinet은 한 주유소(natural
    key 1개)가 제품코드마다 다른 source entity를 갖고, 그 가격들이 **같은 price anchor
    feature에 누적**된다. entity를 축으로 삼으면 제품코드가 늘 때마다 Feature가 갈라진다.

    ``make_feature_id`` 입력에서 ADR-068 결정 2가 배제하라고 한 ``bjd_code``·
    ``category``만 뺀 것이 올바른 축이다.
    """


class FeatureIdentityInvariantError(RuntimeError):
    """uuid 없는(또는 비정규·후보와 다른) 신규 feature 행 관측 — fail-close.

    309가 0080 트리거를 지운 뒤 **정본 키 결측**을 막는 DB 층 보장은
    ``pk_features``의 NOT NULL 하나다(값 **변경**은 309 ``_TRIGGER_RECREATE``가
    되살리는 ``trg_features_identity_fence``가 계속 봉인한다). 결측이 뚫린 상태로
    write가 계속되면 alias-map checksum 대조가 조용히 갈라지므로, writer는
    갱신을 계속하는 대신 즉시 실패한다.
    """


@dataclass(frozen=True)
class FeatureIdentity:
    """경계 해석 결과 — 정본 키 하나의 두 표기.

    309 재키 뒤 두 필드는 모두 ``features.feature_id``(uuid)에서 나오므로 같은
    canonical uuid를 담는다. 필드 이름 ``feature_id``/``feature_uuid``는 바깥
    계약(DTO·응답 키)이라 그대로 유지한다 — 바뀐 것은 값의 출처뿐이다.
    """

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
    """신규 행 INSERT 후보 정본 키 ``feature_id`` — 비파생 UUIDv7 (0083 정본 generator).

    upsert의 ON CONFLICT 경로에서는 이 후보가 **버려지고** 기존 저장값이
    정본으로 남는다(``feature_id``는 ON CONFLICT 갱신 대상이 아님 + 0082
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
    """write 경로가 ``RETURNING``으로 관측한 정본 키(``feature_id``)를 검증한다 (fail-close).

    0083(비파생 generator) 이후의 불변식:

    - 관측값은 **비어 있지 않은 canonical UUID**여야 한다. 309 뒤로 ``feature_id``
      컬럼 자체가 uuid라 legacy 문자열은 저장이 불가능하므로, 이 축이 실제로 잡는
      것은 관측 결측(``RETURNING`` 행 없음 / ``None``)과 비정규 표기다.
    - ``inserted=True``(``xmax = 0``)이면 관측값은 우리가 보낸 후보와 같아야
      한다 — 후보를 바꿔치기하는 경로가 있으면 generator 이원화이므로
      fail-close. 309가 fill 트리거를 지운 뒤 그 자리는 identity claim을 쥔
      프로시저(provider/manual)가 갖는다.
    - ``inserted=False``(conflict-update)면 **기존 저장값이 정본**이다 — 후보와
      달라도 정상(파생 대조는 폐기: 기존 행은 파생값, 신규 행은 비파생값이
      공존하는 세계).

    Parameters
    ----------
    feature_id
        예외 메시지에만 쓰는 진단용 식별자. 309 재키 뒤 write 대상 행의 PK는
        uuid ``feature_id``(``pk_features``)이고 legacy ``f_*``는 PK가 아니라
        ``feature_aliases.alias``다 — 호출부가 어느 쪽을 넘기든 검증에는 쓰이지
        않는다.
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
# 309 재키 뒤 alias 행에는 uuid 사본이 없다(shadow DROP) — 정본은
# ``features.feature_id``(uuid) 하나이고, 출력 별칭 ``feature_uuid``는 유지한다.
_RESOLVE_BY_UUID_SQL: Final[str] = """
SELECT feature_id, CAST(feature_id AS text) AS feature_uuid
FROM feature.features
WHERE feature_id = CAST(:feature_uuid AS uuid)
"""

_RESOLVE_BY_ALIAS_SQL: Final[str] = """
SELECT f.feature_id, CAST(f.feature_id AS text) AS feature_uuid
FROM feature.feature_aliases AS a
JOIN feature.features AS f
  ON f.feature_id = a.feature_id
WHERE a.alias = :alias
"""

_FEATURE_UUID_MAP_SQL: Final[str] = """
SELECT feature_id, CAST(feature_id AS text) AS feature_uuid
FROM feature.features
WHERE feature_id = ANY(CAST(:feature_ids AS uuid[]))
"""

# INV-068-01(**주소가 있어야 하는 Feature만** 등록부에 있다 — ADR-098 결정 6의
# 재정의)과 정본 키 결측을 현행 스키마에서 관측한다. 309 재키 뒤 축마다 **보장의
# 출처가 다르다**:
#   missing_uuid         ``pk_features PRIMARY KEY (feature_id)``의 NOT NULL —
#                        구조상 0.
#   missing_alias        **features 전수가 아니라 provider claim 기준이다.**
#                        ``feature_aliases``는 "모든 Feature의 두 번째 이름"이 아니라
#                        **바깥에서 이 Feature를 가리킨 적이 있는 주소의 등록부**이고,
#                        재키 뒤 주소를 발급하는 주체는 둘뿐이다 — 이전 세대가 실제로
#                        발행했던 ``f_*``를 옮겨 싣는 backfill과 provider 생성 경로
#                        ``create_provider_feature_with_initial_state``. 그래서 이
#                        축은 ``provider_sync.provider_feature_identities`` claim 중
#                        legacy alias가 등록부에 없는 것만 센다.
#                        **admin 수동·요청 승인·큐레이션·core 경로가 만든 Feature에
#                        alias가 없는 것은 정상이라 이 축에 잡히지 않는다** — provider
#                        ``f_*``는 ``sha1(bjd|kind|category|source_type|natural_key)``라
#                        제3자가 Map을 본 적 없어도 계산해 들고 오는 주소지만, manual
#                        ``f_*``는 ``sha1(…|manual::{서버가 방금 발급한 UUIDv7})``라
#                        정본 키의 순수 함수여서 밖에서 계산할 수 없고 드리프트하지도
#                        않는다(발급할 이득이 원리적으로 없다).
#                        DB 보장은 없다 — 309가 ``trg_features_legacy_alias``와
#                        ``feature.ensure_features_legacy_alias()``를 영구 제거했다.
#                        0이 아니면 provider writer가 alias를 안 넣었다는 뜻이다.
#   alias_pair_mismatch  조인 등식 ``a.feature_id = f.feature_id``의 자기검증이라
#                        구조상 0. shadow 사본이 있던 세계(0083)에서는 사본 불일치
#                        관측이었는데 309가 alias 쪽 사본 컬럼을 지웠다.
#   orphan_alias         309가 재생성한 ``fk_feature_aliases_feature``가 막는다.
# 출력 4축은 호출자 계약이라 자리를 유지한다 (적대 리뷰 1 H3의 원래 축).
_MISSING_IDENTITY_SQL: Final[str] = """
SELECT
    count(*) FILTER (WHERE f.feature_id IS NULL) AS missing_uuid,
    (
        SELECT count(*)
        FROM provider_sync.provider_feature_identities AS claim
        LEFT JOIN feature.feature_aliases AS pa
               ON pa.feature_id = claim.feature_id
              AND pa.alias_kind = 'legacy_feature_id'
        WHERE pa.alias IS NULL
    ) AS missing_alias,
    count(*) FILTER (
        WHERE a.alias IS NOT NULL
          AND a.feature_id IS DISTINCT FROM f.feature_id
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

    1. canonical UUID 형태(36자 hyphenated)면 ``features.feature_id`` 정본
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
    """정본 키 목록 → ``{feature_id: feature_uuid}`` map (존재 확인 + 표기 정규화).

    309 재키 뒤 ``_FEATURE_UUID_MAP_SQL``의 WHERE가 ``uuid[]`` 바인드라 **입력은
    canonical uuid 문자열이어야 한다** — legacy ``f_*``를 넘기면 DB가 uuid 파싱에서
    거부한다(그 부류는 :func:`resolve_feature_identities_bulk`가 alias로 해석하는
    입력이다). 두 슬롯이 같은 ``features.feature_id``에서 나오므로 반환은 존재하는
    키에 대한 항등 사상이고, 실질 쓸모는 존재 확인과 canonical 소문자 정규화다.
    복잡한 조회 SQL(예: weather batch)을 재작성하지 않고 응답의 ``feature_uuid``
    슬롯을 채울 때 그대로 쓴다. 존재하지 않는 키는 결과에서 빠진다.
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
SELECT feature_id, CAST(feature_id AS text) AS feature_uuid
FROM feature.features
WHERE feature_id = ANY(CAST(:feature_uuids AS uuid[]))
"""

_RESOLVE_BULK_BY_ALIAS_SQL: Final[str] = """
SELECT a.alias, f.feature_id, CAST(f.feature_id AS text) AS feature_uuid
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


def resolved_uuid_or_none(
    ref: str, resolved: Mapping[str, FeatureIdentity]
) -> str | None:
    """해석된 정본 키(uuid 문자열)를 돌려주고, 없으면 ``None``.

    **왜 ``None``인가.** 309 재키 뒤 batch/CSV 조회 표면의 **대상 열이 전부
    uuid**다. 미해석 참조를 원문 문자열 그대로 바인드에 흘리면 DB가
    ``CAST(... AS uuid)``에서 22P02로 멎고, 그 실패는 그 항목 하나가 아니라
    **요청 전체**를 죽인다 — 한 줄의 오타가 나머지 정상 항목의 결과까지 지운다.
    표면이 약속한 per-item 격리(잘못된 항목만 "찾을 수 없음"으로 떨어진다)를
    지키는 유일한 방법이 uuid로 풀 수 없는 참조를 ``NULL``로 바꿔 넘기는
    것이라, 라우터는 대상 열 바인드마다 이 헬퍼를 통과시킨다.

    ``resolved``는 :func:`resolve_feature_identities_bulk`의 결과다. 거기서
    miss한 참조라도 **canonical UUID 문자열 자체**는 그대로 통과시킨다 —
    uuid로 캐스팅되므로 22P02를 내지 않고, 존재하지 않는 정본 키에 대한 조회는
    빈 결과가 되어 "존재하지 않는 참조"와 동등한 semantics가 된다
    (:func:`legacy_id_for_filter`가 필터 표면에서 쓰는 것과 같은 규율).
    """
    identity = resolved.get(ref)
    if identity is not None:
        return identity.feature_id
    return _parse_canonical_uuid(ref)


def is_canonical_uuid_ref(ref: str) -> bool:
    """참조 문자열이 canonical UUID(lowercase hyphenated 36자) 형태인지 판별."""
    return _parse_canonical_uuid(ref) is not None


_FEATURE_UUID_EXISTS_SQL: Final[str] = """
SELECT EXISTS (
    SELECT 1 FROM feature.features WHERE feature_id = CAST(:feature_uuid AS uuid)
) AS in_use
"""


async def feature_uuid_in_use(session: AsyncSession, value: str) -> bool:
    """값이 어떤 feature의 정본 키와 충돌하는지 검사 (T-VN-32C W3 가드).

    UUID 타입 입력 컬럼(예: sibling_group_id)에 응답에서 복사한 feature UUID를
    붙여넣는 오염을 형식 검증이 못 막으므로, 정본 UUID와의 충돌을 명시
    거부하는 데 쓴다. canonical UUID 형태가 아니면 항상 ``False``.
    """
    if _parse_canonical_uuid(value) is None:
        return False
    row = (
        await session.execute(text(_FEATURE_UUID_EXISTS_SQL), {"feature_uuid": value})
    ).mappings().one()
    return bool(row["in_use"])


async def legacy_id_for_filter(session: AsyncSession, ref: str | None) -> str | None:
    """조회 필터 값을 정본 키(uuid) 표기로 정규화한다 (T-VN-32C PR-2).

    이름은 경계 이름이라 유지한다. 재키 뒤 돌려주는 값은 legacy ``f_*``가 아니라
    ``features.feature_id``(uuid)이고, canonical UUID 입력에는 사실상 항등이며
    UUID 표기의 **alias**만 그것이 가리키는 정본 키로 바뀐다.

    운영자가 응답에서 복사한 UUID를 필터/검색어로 붙여넣는 경로용. canonical
    UUID 형태가 아니면 원문 그대로(추가 왕복 없음), UUID 형태인데 해석
    miss거나 형식 계약 위반이면 역시 원문 유지 — 필터의 "결과 없음" 계약은
    존재하지 않는 legacy id와 동일하게 동작해야 한다(fail-open이 아니라
    동등 semantics).
    """
    if ref is None or _parse_canonical_uuid(ref) is None:
        return ref
    try:
        identity = await resolve_feature_identity(session, ref)
    except FeatureIdentityRefError:
        return ref
    return identity.feature_id if identity is not None else ref


async def count_features_missing_identity(
    session: AsyncSession,
) -> tuple[int, int, int, int]:
    """(uuid 결측, 주소 결측, alias 쌍 불일치, orphan alias) — 정상 ``(0,0,0,0)``.

    freeze INV-068-01의 현행 스키마 판이다. 회귀 테스트와 운영 점검이 사용하고,
    0이 아니면 write 경로를 계속 신뢰하지 말고 fail-close해야 한다
    (:class:`FeatureIdentityInvariantError`의 사전 관측판). **둘째 축이 세는 것은
    "alias 없는 Feature"가 아니라 "주소가 있어야 하는데 등록부에 없는
    Feature"다** (ADR-098 결정 6) — 모집단은 ``feature.features`` 전수가 아니라
    ``provider_sync.provider_feature_identities`` claim이고, admin 수동·요청
    승인·큐레이션·core 경로가 만든 Feature는 alias가 없는 것이 **정상 상태**라
    결손으로 세지 않는다. 그 축은 309가 ``trg_features_legacy_alias``를 지운 뒤로
    DB 보장이 아니라 writer 보장이므로, 0이 아니면 DB가 아니라 alias를 안 넣은
    provider writer를 봐야 한다. 셋째 축(사본
    불일치)은 alias 쪽 uuid 사본이 있던 세계의 관측이었고, 309가 그 컬럼을 지워
    지금은 조인 등식의 자기검증(구조상 0)으로만 남는다 — 축을 빼면 호출자의
    4-튜플 계약이 깨지므로 자리는 유지한다. 넷째 축(부모 없는 orphan alias —
    replica-mode DELETE 잔재, 재판정 M7)은 309가 재생성한
    ``fk_feature_aliases_feature``가 막는 계열의 보상 관측이다.
    """
    row = (await session.execute(text(_MISSING_IDENTITY_SQL))).mappings().one()
    return (
        int(row["missing_uuid"]),
        int(row["missing_alias"]),
        int(row["alias_pair_mismatch"]),
        int(row["orphan_alias"]),
    )
