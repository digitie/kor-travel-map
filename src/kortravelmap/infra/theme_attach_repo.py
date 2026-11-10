"""``kortravelmap.infra.theme_attach_repo`` — MCST 테마 목록 붙임 적재와 전환 계획 입력(ADR-121).

설계 정본은 ``docs/architecture/place-theme-attributes.md`` §6·§8이다. 판정 규칙은
:mod:`kortravelmap.core.theme_attach` 한 곳에 있고, 이 모듈은 DB에서 후보를 읽고 판정을
적용한다.

apply 모드 행 처리 순서(§6.2):

1. **owner** — 자기 dataset 앵커가 active Feature를 가리키면 기존 ``load_bundle`` 그대로.
2. **sticky** — 그 entity의 기존 ``enrichment`` link가 active Feature를 가리키면 유지.
3. **redirect** — 자기 앵커가 퇴역 Feature를 가리키면 ``ops.feature_merge_history``를 따라
   active 생존자에 ``enrichment`` link. 생존자가 없으면 ``unresolved``(퇴역 Feature를 되살리지
   않는다).
4. **matched** — 붙임 규칙으로 tier 1(비MCST)·tier 2(MCST) Feature에 ``enrichment`` link.
   같은 적재에서 먼저 만든 Feature도 tier 2 후보다.
5. **created** — 아무것도 없으면 ``load_bundle``로 이 목록이 primary인 MCST 장소 Feature.
6. **ambiguous** — link를 만들지 않는다.

source record·entity·head는 모든 상태에서 갱신한다. 새로 link를 걸 때 그 entity의 다른
``enrichment`` link는 지운다(entity당 link ≤ 1). snapshot에 없는 entity의 ``enrichment`` link와
판정은 지운다 — MCST가 primary인 Feature의 부재 처리는 현행과 같다(퇴역하지 않음).

dry_run 모드는 같은 판정을 계산해 개수만 보고하고 현행 ``load_bundles``로 적재한다.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Final, Literal

from sqlalchemy import bindparam, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.types import Float, Integer, Text

from kortravelmap.core.theme_attach import (
    SEARCH_RADIUS_M,
    THEME_ATTACH_RULE_VERSION,
    AttachCandidate,
    PlanFeature,
    decide_attach,
    haversine_m,
)
from kortravelmap.infra.feature_repo import (
    FeatureLoadResult,
    _make_source_entity_key,
    _upsert_source_record_state,
    load_bundles,
    lock_feature_curation_write,
    resolve_active_provider_dataset_id,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from kortravelmap.dto import FeatureBundle
    from kortravelmap.dto.geo_dataset import GeoLoadContext

__all__ = [
    "MCST_PROVIDER",
    "PlanDatasetConfig",
    "ThemeAttachMode",
    "ThemeAttachReport",
    "ThemeAttachSpec",
    "fetch_mcst_plan_features",
    "load_theme_attach_bundles",
]

MCST_PROVIDER: Final[str] = "python-mcst-api"
"""tier를 가르는 provider 이름(ADR-024 canonical)."""

ThemeAttachMode = Literal["dry_run", "apply"]

AttachState = Literal[
    "owner", "matched", "sticky", "redirected", "created", "ambiguous", "unresolved"
]

_MAX_REDIRECT_HOPS: Final[int] = 8


@dataclass(frozen=True, slots=True)
class ThemeAttachSpec:
    """한 dataset의 붙임 설정. infra는 provider를 import하지 않으므로 호출자가 넘긴다."""

    provider: str
    dataset_key: str
    master_category_prefixes: tuple[str, ...] | None


@dataclass(frozen=True)
class ThemeAttachReport:
    """한 dataset 적재의 판정 개수."""

    mode: ThemeAttachMode
    dataset_key: str
    counts: Mapping[str, int] = field(default_factory=dict)
    enrichment_links_removed: int = 0
    decisions_removed: int = 0

    def as_metadata(self) -> dict[str, object]:
        return {
            "theme_attach_mode": self.mode,
            "theme_attach_counts": dict(sorted(self.counts.items())),
            "theme_attach_enrichment_links_removed": self.enrichment_links_removed,
            "theme_attach_decisions_removed": self.decisions_removed,
        }


@dataclass(slots=True)
class _Row:
    bundle: FeatureBundle
    natural_key: str
    entity_key: str
    lonlat: tuple[float, float] | None
    state: AttachState | None = None
    target: str | None = None
    """확정 대상 feature_id. ``pending:<i>``는 같은 적재에서 만들 Feature."""
    evidence: dict[str, object] = field(default_factory=dict)


# ── 조회 SQL ─────────────────────────────────────────────────────────────

_RESOLVE_CLAIMS_SQL = text(
    """
SELECT input.ordinal::int AS ordinal,
       feature.resolve_provider_feature_id(
           CAST(:provider_dataset_id AS bigint), 'place', input.natural_key
       )::text AS feature_id
  FROM unnest(CAST(:natural_keys AS text[])) WITH ORDINALITY AS input(natural_key, ordinal)
"""
).bindparams(bindparam("natural_keys", type_=ARRAY(Text)))

_FEATURE_STATES_SQL = text(
    """
SELECT CAST(feature_id AS text) AS feature_id, lifecycle_state, publication_state
  FROM feature.features
 WHERE feature_id = ANY(CAST(:feature_ids AS uuid[]))
"""
).bindparams(bindparam("feature_ids", type_=ARRAY(Text)))

_ENTITY_LINKS_SQL = text(
    """
SELECT sl.source_entity_key, CAST(sl.feature_id AS text) AS feature_id, sl.source_role,
       f.lifecycle_state
  FROM provider_sync.source_links AS sl
  JOIN feature.features AS f ON f.feature_id = sl.feature_id
 WHERE sl.source_entity_key = ANY(CAST(:entity_keys AS text[]))
"""
).bindparams(bindparam("entity_keys", type_=ARRAY(Text)))

#: 병합 이력 한 단계. 같은 loser가 여러 번 병합될 일은 없지만 가장 최근 것을 쓴다.
_MERGE_SURVIVOR_SQL = text(
    """
SELECT CAST(h.master_feature_id AS text) AS master_feature_id, f.lifecycle_state
  FROM ops.feature_merge_history AS h
  JOIN feature.features AS f ON f.feature_id = h.master_feature_id
 WHERE h.loser_feature_id = CAST(:feature_id AS uuid)
 ORDER BY h.merged_at DESC
 LIMIT 1
"""
)

#: 후보 조회 — 입력 점은 MATERIALIZED CTE에서 한 번만 5179로 바꾼다. 술어는
#: ``ST_DWithin(f.coord_5179, input.pt, r)``로 열끼리 비교라 색인을 탄다(ADR-012). 술어가
#: 부분 GiST 색인(``idx_features_coord_5179_gist`` — active·published·valid)의 조건을 그대로
#: 담아야 색인을 쓴다. suppressed Feature는 후보가 아니다(공개 projection 밖, 설계 §5.1).
_CANDIDATES_SQL = text(
    """
WITH input AS MATERIALIZED (
    SELECT i.ordinal,
           x_extension.ST_Transform(
               x_extension.ST_SetSRID(x_extension.ST_MakePoint(i.lon, i.lat), 4326), 5179
           ) AS pt
      FROM unnest(
               CAST(:ordinals AS integer[]),
               CAST(:lons AS double precision[]),
               CAST(:lats AS double precision[])
           ) AS i(ordinal, lon, lat)
), near AS (
    SELECT input.ordinal, f.feature_id, f.name, f.category, true AS published,
           x_extension.ST_Distance(f.coord_5179, input.pt) AS distance_m
      FROM input
      JOIN feature.features AS f
        ON x_extension.ST_DWithin(f.coord_5179, input.pt, :radius)
     WHERE f.kind = 'place' AND f.lifecycle_state = 'active'
       AND f.publication_state = 'published' AND f.quality_state = 'valid'
)
SELECT near.ordinal, CAST(near.feature_id AS text) AS feature_id, near.name, near.category,
       near.published, near.distance_m,
       EXISTS (
           SELECT 1
             FROM provider_sync.source_links AS sl
             JOIN provider_sync.source_entities AS se
               ON se.source_entity_key = sl.source_entity_key
             JOIN provider_sync.provider_datasets AS pd
               ON pd.provider_dataset_id = se.provider_dataset_id
            WHERE sl.feature_id = near.feature_id AND sl.source_role = 'primary'
              AND pd.provider <> :mcst_provider
       ) AS has_other_primary,
       EXISTS (
           SELECT 1
             FROM provider_sync.source_links AS sl
             JOIN provider_sync.source_entities AS se
               ON se.source_entity_key = sl.source_entity_key
             JOIN provider_sync.provider_datasets AS pd
               ON pd.provider_dataset_id = se.provider_dataset_id
            WHERE sl.feature_id = near.feature_id AND sl.source_role = 'primary'
              AND pd.provider = :mcst_provider
       ) AS has_mcst_primary
  FROM near
"""
).bindparams(
    bindparam("ordinals", type_=ARRAY(Integer)),
    bindparam("lons", type_=ARRAY(Float)),
    bindparam("lats", type_=ARRAY(Float)),
)

_UPSERT_LINK_BY_ENTITY_SQL = text(
    """
INSERT INTO provider_sync.source_links (
    feature_id, source_entity_key, source_role, match_method, confidence
) VALUES (
    CAST(:feature_id AS uuid), :source_entity_key, 'enrichment', :match_method, :confidence
)
ON CONFLICT (feature_id, source_entity_key) DO UPDATE SET
    match_method = EXCLUDED.match_method,
    confidence = EXCLUDED.confidence
"""
)

#: 같은 entity의 **다른** enrichment link를 지운다(entity당 link ≤ 1). primary는 건드리지 않는다.
_DELETE_OTHER_ENRICHMENT_SQL = text(
    """
DELETE FROM provider_sync.source_links
 WHERE source_entity_key = :source_entity_key
   AND source_role = 'enrichment'
   AND (CAST(:keep_feature_id AS uuid) IS NULL OR feature_id <> CAST(:keep_feature_id AS uuid))
"""
)

_DELETE_ABSENT_ENRICHMENT_SQL = text(
    """
DELETE FROM provider_sync.source_links AS sl
 USING provider_sync.source_entities AS se
 WHERE se.source_entity_key = sl.source_entity_key
   AND se.provider_dataset_id = :provider_dataset_id
   AND sl.source_role = 'enrichment'
   AND NOT (se.source_entity_id = ANY(CAST(:entity_ids AS text[])))
RETURNING sl.source_entity_key
"""
).bindparams(bindparam("entity_ids", type_=ARRAY(Text)))

_DELETE_ABSENT_DECISIONS_SQL = text(
    """
DELETE FROM provider_sync.theme_attach_decisions
 WHERE provider_dataset_id = :provider_dataset_id
   AND NOT (natural_key = ANY(CAST(:natural_keys AS text[])))
RETURNING natural_key
"""
).bindparams(bindparam("natural_keys", type_=ARRAY(Text)))

_UPSERT_DECISIONS_SQL = text(
    """
INSERT INTO provider_sync.theme_attach_decisions (
    provider_dataset_id, natural_key, state, target_feature_id, rule_version, evidence,
    decided_at
)
SELECT CAST(:provider_dataset_id AS bigint), d.natural_key, d.state,
       CAST(d.target_feature_id AS uuid), :rule_version, d.evidence, now()
  FROM jsonb_to_recordset(CAST(:rows AS jsonb))
       AS d(natural_key text, state text, target_feature_id text, evidence jsonb)
ON CONFLICT (provider_dataset_id, natural_key) DO UPDATE SET
    state = EXCLUDED.state,
    target_feature_id = EXCLUDED.target_feature_id,
    rule_version = EXCLUDED.rule_version,
    evidence = EXCLUDED.evidence,
    decided_at = EXCLUDED.decided_at
"""
)


# ── 공통 판정 ────────────────────────────────────────────────────────────


def _lonlat(bundle: FeatureBundle) -> tuple[float, float] | None:
    coord = bundle.feature.coord
    if coord is None:
        return None
    return float(coord.lon), float(coord.lat)


async def _candidates(
    session: AsyncSession, rows: Sequence[tuple[int, tuple[float, float]]]
) -> dict[int, list[AttachCandidate]]:
    out: dict[int, list[AttachCandidate]] = {}
    if not rows:
        return out
    result = await session.execute(
        _CANDIDATES_SQL,
        {
            "ordinals": [ordinal for ordinal, _ in rows],
            "lons": [lonlat[0] for _, lonlat in rows],
            "lats": [lonlat[1] for _, lonlat in rows],
            "radius": SEARCH_RADIUS_M,
            "mcst_provider": MCST_PROVIDER,
        },
    )
    for record in result.mappings():
        tier: Literal[1, 2] = (
            2 if record["has_mcst_primary"] and not record["has_other_primary"] else 1
        )
        out.setdefault(int(record["ordinal"]), []).append(
            AttachCandidate(
                feature_id=str(record["feature_id"]),
                name=str(record["name"]),
                category=str(record["category"]),
                distance_m=float(record["distance_m"]),
                tier=tier,
                published=bool(record["published"]),
            )
        )
    return out


async def _merge_survivor(session: AsyncSession, feature_id: str) -> str | None:
    current = feature_id
    for _ in range(_MAX_REDIRECT_HOPS):
        row = (
            await session.execute(_MERGE_SURVIVOR_SQL, {"feature_id": current})
        ).mappings().one_or_none()
        if row is None:
            return None
        current = str(row["master_feature_id"])
        if row["lifecycle_state"] == "active":
            return current
    return None


async def _decide_rows(
    session: AsyncSession,
    rows: list[_Row],
    *,
    provider_dataset_id: int,
    spec: ThemeAttachSpec,
) -> None:
    """행마다 상태·대상을 정한다(쓰기 없음). ``pending:<i>``는 같은 적재에서 만들 Feature."""

    natural_keys = [row.natural_key for row in rows]
    claims: dict[int, str | None] = {}
    if rows:
        for record in (
            await session.execute(
                _RESOLVE_CLAIMS_SQL,
                {"provider_dataset_id": provider_dataset_id, "natural_keys": natural_keys},
            )
        ).mappings():
            claims[int(record["ordinal"]) - 1] = (
                None if record["feature_id"] is None else str(record["feature_id"])
            )
    claimed_ids = sorted({fid for fid in claims.values() if fid is not None})
    lifecycle: dict[str, str] = {}
    if claimed_ids:
        for record in (
            await session.execute(_FEATURE_STATES_SQL, {"feature_ids": claimed_ids})
        ).mappings():
            lifecycle[str(record["feature_id"])] = str(record["lifecycle_state"])
    links: dict[str, list[tuple[str, str, str]]] = {}
    if rows:
        for record in (
            await session.execute(
                _ENTITY_LINKS_SQL, {"entity_keys": [row.entity_key for row in rows]}
            )
        ).mappings():
            links.setdefault(str(record["source_entity_key"]), []).append(
                (str(record["feature_id"]), str(record["source_role"]),
                 str(record["lifecycle_state"]))
            )

    needs_match: list[int] = []
    for index, row in enumerate(rows):
        claim = claims.get(index)
        if claim is not None and lifecycle.get(claim) == "active":
            row.state, row.target = "owner", claim
            continue
        sticky = next(
            (
                fid
                for fid, role, state in links.get(row.entity_key, [])
                if role == "enrichment" and state == "active"
            ),
            None,
        )
        if sticky is not None:
            row.state, row.target = "sticky", sticky
            continue
        if claim is not None:
            survivor = await _merge_survivor(session, claim)
            if survivor is not None:
                row.state, row.target = "redirected", survivor
                row.evidence = {"retired_claim": claim}
            else:
                row.state = "unresolved"
                row.evidence = {"retired_claim": claim}
            continue
        needs_match.append(index)

    located = [(index, rows[index].lonlat) for index in needs_match if rows[index].lonlat]
    candidates = await _candidates(
        session, [(index, lonlat) for index, lonlat in located if lonlat is not None]
    )
    created: list[tuple[str, str, tuple[float, float] | None]] = []
    for index in needs_match:
        row = rows[index]
        pool = list(candidates.get(index, []))
        if row.lonlat is not None:
            for pending_id, pending_name, pending_lonlat in created:
                if pending_lonlat is None:
                    continue
                distance = haversine_m(*row.lonlat, *pending_lonlat)
                if distance <= SEARCH_RADIUS_M:
                    pool.append(
                        AttachCandidate(
                            feature_id=pending_id,
                            name=pending_name,
                            category="",
                            distance_m=distance,
                            tier=2,
                        )
                    )
        decision = decide_attach(
            row.bundle.feature.name,
            pool,
            master_category_prefixes=spec.master_category_prefixes,
        )
        row.evidence = dict(decision.evidence)
        if decision.state == "matched":
            row.state, row.target = "matched", decision.target_feature_id
        elif decision.state == "ambiguous":
            row.state = "ambiguous"
        else:
            row.state, row.target = "created", f"pending:{index}"
            created.append((row.target, row.bundle.feature.name, row.lonlat))


async def load_theme_attach_bundles(
    session: AsyncSession,
    bundles: Sequence[FeatureBundle],
    *,
    spec: ThemeAttachSpec,
    mode: ThemeAttachMode,
    geo: GeoLoadContext | None = None,
) -> tuple[FeatureLoadResult, ThemeAttachReport]:
    """MCST 한 dataset의 snapshot을 붙임 규칙으로 적재한다. 호출자가 transaction을 소유한다."""

    await lock_feature_curation_write(session)
    provider_dataset_id = await resolve_active_provider_dataset_id(
        session, provider=spec.provider, dataset_key=spec.dataset_key
    )
    rows = [
        _Row(
            bundle=bundle,
            natural_key=str(bundle.feature.provider_natural_key),
            entity_key=_make_source_entity_key(
                provider=bundle.source_record.provider,
                dataset_key=bundle.source_record.dataset_key,
                source_entity_type=bundle.source_record.source_entity_type,
                source_entity_id=bundle.source_record.source_entity_id,
            ),
            lonlat=_lonlat(bundle),
        )
        for bundle in bundles
    ]
    await _decide_rows(session, rows, provider_dataset_id=provider_dataset_id, spec=spec)
    counts = Counter(str(row.state) for row in rows)

    if mode == "dry_run":
        loaded = await load_bundles(session, bundles, geo=geo)
        return loaded, ThemeAttachReport(mode="dry_run", dataset_key=spec.dataset_key,
                                         counts=dict(counts))

    # apply — Feature를 소유하는 행(owner·created)은 기존 적재 그대로, 한 번에(geo chunk 유지).
    owning = [row for row in rows if row.state in ("owner", "created")]
    loaded = await load_bundles(session, [row.bundle for row in owning], geo=geo)
    resolved: dict[str, str] = {}
    created_rows = [row for row in rows if row.state == "created"]
    if created_rows:
        for record in (
            await session.execute(
                _RESOLVE_CLAIMS_SQL,
                {
                    "provider_dataset_id": provider_dataset_id,
                    "natural_keys": [row.natural_key for row in created_rows],
                },
            )
        ).mappings():
            row = created_rows[int(record["ordinal"]) - 1]
            if record["feature_id"] is None:
                raise RuntimeError(
                    f"{spec.dataset_key}: 생성 직후 identity claim이 없다 ({row.natural_key!r})"
                )
            resolved[str(row.target)] = str(record["feature_id"])
            row.target = str(record["feature_id"])

    for row in rows:
        if row.state in ("owner", "created"):
            continue
        state = await _upsert_source_record_state(session, row.bundle.source_record)
        entity_key = state.source_entity_key
        if row.state in ("matched", "sticky", "redirected"):
            assert row.target is not None
            target = resolved.get(row.target, row.target)
            row.target = target
            await session.execute(
                _UPSERT_LINK_BY_ENTITY_SQL,
                {
                    "feature_id": target,
                    "source_entity_key": entity_key,
                    "match_method": f"theme_attach:{row.state}",
                    "confidence": 90,
                },
            )
            await session.execute(
                _DELETE_OTHER_ENRICHMENT_SQL,
                {"source_entity_key": entity_key, "keep_feature_id": target},
            )
        else:
            await session.execute(
                _DELETE_OTHER_ENRICHMENT_SQL,
                {"source_entity_key": entity_key, "keep_feature_id": None},
            )

    entity_ids = sorted({row.bundle.source_record.source_entity_id for row in rows})
    removed_links = len(
        (
            await session.execute(
                _DELETE_ABSENT_ENRICHMENT_SQL,
                {"provider_dataset_id": provider_dataset_id, "entity_ids": entity_ids},
            )
        ).all()
    )
    removed_decisions = len(
        (
            await session.execute(
                _DELETE_ABSENT_DECISIONS_SQL,
                {
                    "provider_dataset_id": provider_dataset_id,
                    "natural_keys": sorted({row.natural_key for row in rows}),
                },
            )
        ).all()
    )
    if rows:
        payload = {
            row.natural_key: {
                "natural_key": row.natural_key,
                "state": row.state,
                "target_feature_id": row.target,
                "evidence": row.evidence,
            }
            for row in rows
        }
        await session.execute(
            _UPSERT_DECISIONS_SQL,
            {
                "provider_dataset_id": provider_dataset_id,
                "rule_version": THEME_ATTACH_RULE_VERSION,
                "rows": json.dumps(list(payload.values()), ensure_ascii=False, default=str),
            },
        )
    return loaded, ThemeAttachReport(
        mode="apply",
        dataset_key=spec.dataset_key,
        counts=dict(counts),
        enrichment_links_removed=removed_links,
        decisions_removed=removed_decisions,
    )


# ── 전환 계획 입력(§8.1, 읽기 전용) ──────────────────────────────────────

_PLAN_FEATURES_SQL = text(
    """
SELECT DISTINCT ON (f.feature_id)
       CAST(f.feature_id AS text) AS feature_id, pd.dataset_key, f.name, f.created_at,
       se.source_entity_type, sr.raw_data ->> 'CATEGORY2' AS category2
  FROM feature.features AS f
  JOIN provider_sync.source_links AS sl
    ON sl.feature_id = f.feature_id AND sl.source_role = 'primary'
  JOIN provider_sync.source_entities AS se ON se.source_entity_key = sl.source_entity_key
  JOIN provider_sync.provider_datasets AS pd
    ON pd.provider_dataset_id = se.provider_dataset_id
  LEFT JOIN provider_sync.source_entity_heads AS h ON h.source_entity_key = se.source_entity_key
  LEFT JOIN provider_sync.source_records AS sr
    ON sr.source_record_key = h.current_source_record_key
 WHERE f.kind = 'place' AND f.lifecycle_state = 'active'
   AND pd.provider = :mcst_provider
 ORDER BY f.feature_id, sl.created_at
"""
)

#: 계획 후보쌍 — MCST Feature마다 150m 안의 공개 place. 두 열 모두 ``coord_5179``라 변환이
#: 없고, 상대 쪽 술어가 부분 GiST 색인 조건(active·published·valid)을 그대로 담아 색인을 탄다
#: (2026-11-10: ``publication_state IN (...)``로 넓혔더니 색인을 못 써 88k×270k 비교로 30분 넘게
#: 돌았다). 원문 이름 trigram 0.2 미만은 정규화 뒤에도 채택 문턱(0.6)에 못 미치므로
#: 쌍 수를 줄이려고 미리 거른다.
_PLAN_PAIRS_SQL = text(
    """
WITH mcst AS MATERIALIZED (
    SELECT DISTINCT f.feature_id, f.name, f.coord_5179
      FROM feature.features AS f
      JOIN provider_sync.source_links AS sl
        ON sl.feature_id = f.feature_id AND sl.source_role = 'primary'
      JOIN provider_sync.source_entities AS se ON se.source_entity_key = sl.source_entity_key
      JOIN provider_sync.provider_datasets AS pd
        ON pd.provider_dataset_id = se.provider_dataset_id
     WHERE f.kind = 'place' AND f.lifecycle_state = 'active' AND f.coord_5179 IS NOT NULL
       AND pd.provider = :mcst_provider
), pairs AS (
    SELECT m.feature_id AS mcst_id, o.feature_id AS other_id, o.name, o.category,
           o.publication_state = 'published' AS published,
           x_extension.ST_Distance(o.coord_5179, m.coord_5179) AS distance_m
      FROM mcst AS m
      JOIN feature.features AS o
        ON x_extension.ST_DWithin(o.coord_5179, m.coord_5179, :radius)
       AND o.feature_id <> m.feature_id
     WHERE o.kind = 'place' AND o.lifecycle_state = 'active'
       AND o.publication_state = 'published' AND o.quality_state = 'valid'
       AND x_extension.similarity(o.name, m.name) >= 0.2
)
SELECT CAST(p.mcst_id AS text) AS mcst_id, CAST(p.other_id AS text) AS other_id, p.name,
       p.category, p.published, p.distance_m,
       EXISTS (
           SELECT 1
             FROM provider_sync.source_links AS sl
             JOIN provider_sync.source_entities AS se
               ON se.source_entity_key = sl.source_entity_key
             JOIN provider_sync.provider_datasets AS pd
               ON pd.provider_dataset_id = se.provider_dataset_id
            WHERE sl.feature_id = p.other_id AND sl.source_role = 'primary'
              AND pd.provider <> :mcst_provider
       ) AS has_other_primary,
       EXISTS (
           SELECT 1
             FROM provider_sync.source_links AS sl
             JOIN provider_sync.source_entities AS se
               ON se.source_entity_key = sl.source_entity_key
             JOIN provider_sync.provider_datasets AS pd
               ON pd.provider_dataset_id = se.provider_dataset_id
            WHERE sl.feature_id = p.other_id AND sl.source_role = 'primary'
              AND pd.provider = :mcst_provider
       ) AS has_mcst_primary
  FROM pairs AS p
"""
)


@dataclass(frozen=True, slots=True)
class PlanDatasetConfig:
    """계획기가 dataset마다 알아야 하는 것(provider 메타에서 호출자가 만든다)."""

    master_category_prefixes: tuple[str, ...] | None
    attribute_list: bool
    pet_business: frozenset[str] = frozenset()
    """이 dataset에서 ``retire``할 ``CATEGORY2`` 값(반려동물 목록만)."""


async def fetch_mcst_plan_features(
    session: AsyncSession, *, datasets: Mapping[str, PlanDatasetConfig]
) -> list[PlanFeature]:
    """운영 MCST active Feature와 그 거리 후보를 읽는다(읽기 전용)."""

    import re

    params: dict[str, Any] = {"mcst_provider": MCST_PROVIDER, "radius": SEARCH_RADIUS_M}
    features = (await session.execute(_PLAN_FEATURES_SQL, params)).mappings().all()
    pairs: dict[str, list[AttachCandidate]] = {}
    for record in (await session.execute(_PLAN_PAIRS_SQL, params)).mappings():
        tier: Literal[1, 2] = (
            2 if record["has_mcst_primary"] and not record["has_other_primary"] else 1
        )
        pairs.setdefault(str(record["mcst_id"]), []).append(
            AttachCandidate(
                feature_id=str(record["other_id"]),
                name=str(record["name"]),
                category=str(record["category"]),
                distance_m=float(record["distance_m"]),
                tier=tier,
                published=bool(record["published"]),
            )
        )
    out: list[PlanFeature] = []
    for record in features:
        dataset_key = str(record["dataset_key"])
        config = datasets.get(dataset_key)
        if config is None:
            continue
        category2 = re.sub(r"\s+", "", str(record["category2"] or ""))
        created_at = record["created_at"]
        out.append(
            PlanFeature(
                feature_id=str(record["feature_id"]),
                dataset_key=dataset_key,
                name=str(record["name"]),
                created_at=(
                    created_at.isoformat() if isinstance(created_at, datetime) else str(created_at)
                ),
                place_list=not config.attribute_list,
                pet_business=category2 in config.pet_business,
                master_category_prefixes=config.master_category_prefixes,
                candidates=tuple(pairs.get(str(record["feature_id"]), ())),
            )
        )
    return out
