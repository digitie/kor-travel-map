"""``kortravelmap.core.theme_attach`` — MCST 테마 목록 행을 장소 Feature에 붙이는 규칙(ADR-121).

설계 정본은 ``docs/architecture/place-theme-attributes.md`` §5다. 이 모듈이 규칙
``theme-attach-v1``의 **유일한 구현**이다 — SQL은 거리 150m 안의 후보만 가져오고, 이름
정규화·점수·채택·동점 판정은 여기서만 한다. ``core/scoring.py``의 Jaro-Winkler(dedup용)와는
다른 척도이며 섞어 쓰지 않는다.

규칙 요약:

- 이름 정규화 :func:`normalize_place_name` — NFKC·소문자·법인 표기 제거, **공백으로 떨어진**
  끝 지점 토큰(``강남점``·``본점``)과 괄호 안 내용은 지점 토큰으로 떼어 둔다(붙어 있는 ``서점``·
  ``반점``은 건드리지 않는다), 남은 이름에서 공백·구두점 제거.
- 점수 :func:`trigram_similarity` — pg_trgm ``similarity``와 같은 정의(앞 공백 둘·뒤 공백 하나를
  붙인 trigram 집합의 Jaccard).
- 채택: ``d ≤ 50m ∧ s ≥ 0.6`` 또는 ``d ≤ 150m ∧ s ≥ 0.8``. 일반명은 ``d ≤ 30m ∧ s ≥ 0.9``만.
- 양쪽 지점 토큰이 다르면 후보에서 버린다.
- tier 1(비MCST master)이 하나라도 채택되면 tier 2(MCST)는 보지 않는다. tier 1의 1·2위가
  다른 Feature이고 점수 차 < 0.05면 ``ambiguous``(tier 2 동점은 같은 장소의 다른 목록이라 다툼이
  아니다). 채택된 suppressed 후보가 있으면 ``ambiguous``.

ADR-002(core 순수 함수) — DB·provider 의존 없음.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

__all__ = [
    "ACCEPT_RULES",
    "AMBIGUITY_MARGIN",
    "GENERIC_PLACE_NAMES",
    "SEARCH_RADIUS_M",
    "THEME_ATTACH_RULE_VERSION",
    "AttachCandidate",
    "AttachDecision",
    "NormalizedName",
    "PlanAction",
    "PlanEntry",
    "PlanFeature",
    "accepts",
    "category_compatible",
    "decide_attach",
    "haversine_m",
    "normalize_place_name",
    "plan_existing_features",
    "trigram_similarity",
]

THEME_ATTACH_RULE_VERSION: Final[str] = "theme-attach-v1"
"""규칙 버전. 임계값·정규화가 바뀌면 올리고 전 행을 재판정한다."""

SEARCH_RADIUS_M: Final[float] = 150.0
"""후보 조회 반경 — 가장 넓은 채택 규칙의 거리와 같아야 한다(더 넓은 규칙은 조회 밖이라 죽는다)."""

ACCEPT_RULES: Final[tuple[tuple[float, float], ...]] = ((50.0, 0.6), (150.0, 0.8))
"""(최대 거리 m, 최소 이름 점수). 하나라도 만족하면 채택."""

GENERIC_ACCEPT: Final[tuple[float, float]] = (30.0, 0.9)
"""일반명은 이 규칙만 — 같은 이름의 다른 시설이 흔하다."""

AMBIGUITY_MARGIN: Final[float] = 0.05
"""같은 tier 1·2위가 다른 Feature이고 점수 차가 이보다 작으면 판단하지 않는다."""

GENERIC_PLACE_NAMES: Final[frozenset[str]] = frozenset(
    {
        "공영주차장",
        "주차장",
        "관광안내소",
        "관광안내센터",
        "안내소",
        "화장실",
        "공중화장실",
        "매표소",
        "휴게소",
        "버스정류장",
        "정류장",
        "편의점",
        "약국",
        "동물병원",
        "카페",
        "식당",
        "놀이터",
        "어린이놀이터",
        "공원",
        "체육관",
        "도서관",
        "주민센터",
        "행정복지센터",
    }
)
"""정규화 이름이 이 집합에 들면 일반명이다(§5.2). 값은 정규화된 형태(공백 없음)다."""

_CORPORATE_MARKERS: Final[re.Pattern[str]] = re.compile(
    r"\(\s*(?:주|유|재|사|합)\s*\)|주식회사|유한회사|유한책임회사|재단법인|사단법인|합자회사|합명회사"
)
_PAREN: Final[re.Pattern[str]] = re.compile(r"[(\[{（［]([^)\]}）］]*)[)\]}）］]")
_TRAILING_BRANCH: Final[re.Pattern[str]] = re.compile(r"\s+(\S*점)$")

#: ``점``으로 끝나지만 지점이 아니라 업종 낱말인 것 — 이 낱말로 끝나는 토큰은 떼지 않는다
#: (``알라딘 중고서점``의 ``중고서점``은 이름의 일부다).
_NOT_BRANCH_SUFFIXES: Final[tuple[str, ...]] = (
    "서점",
    "반점",
    "상점",
    "매점",
    "편의점",
    "주점",
    "정육점",
    "잡화점",
    "백화점",
    "할인점",
    "전문점",
    "음식점",
    "판매점",
    "대리점",
    "제과점",
    "문구점",
    "소매점",
    "책점",
)
_NON_WORD: Final[re.Pattern[str]] = re.compile(r"[^\w]|_", re.UNICODE)


@dataclass(frozen=True, slots=True)
class NormalizedName:
    """정규화 이름과 떼어 둔 지점 토큰."""

    core: str
    branch: str | None


def _compact(text: str) -> str:
    return _NON_WORD.sub("", text)


def normalize_place_name(name: str) -> NormalizedName:
    """장소 이름 → (비교용 이름, 지점 토큰). 결정적·순수."""

    text = unicodedata.normalize("NFKC", name).lower().strip()
    text = _CORPORATE_MARKERS.sub(" ", text)
    branches: list[str] = []
    for match in _PAREN.finditer(text):
        inner = _compact(match.group(1))
        if inner:
            branches.append(inner)
    text = _PAREN.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    trailing = _TRAILING_BRANCH.search(text)
    if trailing is not None and not trailing.group(1).endswith(_NOT_BRANCH_SUFFIXES):
        head = text[: trailing.start()].strip()
        # 앞에 이름이 남을 때만 뗀다 — "본점" 하나뿐인 이름을 비우지 않는다.
        if _compact(head):
            branches.append(_compact(trailing.group(1)))
            text = head
    core = _compact(text)
    if not core:
        # 괄호만 있는 이름 — 괄호 안이 곧 이름이다.
        core = "".join(branches)
        branches = []
    branch = "|".join(sorted(set(branches))) if branches else None
    return NormalizedName(core=core, branch=branch)


def _trigrams(word: str) -> frozenset[str]:
    padded = f"  {word} "
    return frozenset(padded[i : i + 3] for i in range(len(padded) - 2))


def trigram_similarity(a: str, b: str) -> float:
    """pg_trgm ``similarity``와 같은 정의(공백 없는 한 낱말 기준)."""

    if not a or not b:
        return 0.0
    ta, tb = _trigrams(a), _trigrams(b)
    union = len(ta | tb)
    return len(ta & tb) / union if union else 0.0


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """두 경위도 사이 거리(m). 같은 적재에서 막 만든 Feature처럼 DB 밖 후보에 쓴다."""

    r = 6_371_008.8
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(h)))


def accepts(distance_m: float, score: float, *, generic: bool) -> bool:
    """채택 규칙(§5.2)."""

    if generic:
        max_d, min_s = GENERIC_ACCEPT
        return distance_m <= max_d and score >= min_s
    return any(distance_m <= max_d and score >= min_s for max_d, min_s in ACCEPT_RULES)


def category_compatible(category: str, prefixes: Sequence[str] | None) -> bool:
    """tier 1 master 분류 호환. ``None``이면 제한 없음."""

    if prefixes is None:
        return True
    return any(category.startswith(prefix) for prefix in prefixes)


@dataclass(frozen=True, slots=True)
class AttachCandidate:
    """거리 안에 든 후보 Feature 하나."""

    feature_id: str
    name: str
    category: str
    distance_m: float
    tier: Literal[1, 2]
    published: bool = True


@dataclass(frozen=True, slots=True)
class AttachDecision:
    """한 행의 판정."""

    state: Literal["matched", "ambiguous", "none"]
    target_feature_id: str | None
    tier: int | None
    evidence: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class _Scored:
    candidate: AttachCandidate
    score: float


def decide_attach(
    name: str,
    candidates: Iterable[AttachCandidate],
    *,
    master_category_prefixes: Sequence[str] | None,
    exclude_feature_ids: frozenset[str] = frozenset(),
) -> AttachDecision:
    """행 이름과 거리 후보로 판정한다(§5).

    ``exclude_feature_ids``는 자기 자신 같은 후보를 빼는 데 쓴다(계획기).
    """

    own = normalize_place_name(name)
    generic = own.core in GENERIC_PLACE_NAMES
    accepted: list[_Scored] = []
    for candidate in candidates:
        if candidate.feature_id in exclude_feature_ids:
            continue
        if candidate.tier == 1 and not category_compatible(
            candidate.category, master_category_prefixes
        ):
            continue
        other = normalize_place_name(candidate.name)
        if own.branch is not None and other.branch is not None and own.branch != other.branch:
            continue
        score = trigram_similarity(own.core, other.core)
        if accepts(candidate.distance_m, score, generic=generic):
            accepted.append(_Scored(candidate, score))

    evidence_top = [
        {
            "feature_id": item.candidate.feature_id,
            "tier": item.candidate.tier,
            "distance_m": round(item.candidate.distance_m, 1),
            "score": round(item.score, 4),
            "published": item.candidate.published,
        }
        for item in sorted(
            accepted, key=lambda s: (s.candidate.tier, -s.score, s.candidate.distance_m)
        )[:3]
    ]
    evidence: dict[str, object] = {"name_core": own.core, "accepted": evidence_top}

    for tier in (1, 2):
        in_tier = [item for item in accepted if item.candidate.tier == tier]
        if not in_tier:
            continue
        if any(not item.candidate.published for item in in_tier):
            return AttachDecision("ambiguous", None, tier, {**evidence, "reason": "suppressed"})
        ranked = sorted(
            in_tier,
            key=lambda s: (-s.score, s.candidate.distance_m, s.candidate.feature_id),
        )
        best = ranked[0]
        runner = next(
            (s for s in ranked[1:] if s.candidate.feature_id != best.candidate.feature_id),
            None,
        )
        # tier 2(MCST끼리)의 동점은 다툼이 아니다 — 같은 장소가 여러 목록에 있는 것이고 전환 계획이
        # 그 묶음을 하나로 접는다(2026-11-10 R2 dry-run: tier 2 동점이 ambiguous의 3/4이었다).
        if tier == 1 and runner is not None and best.score - runner.score < AMBIGUITY_MARGIN:
            return AttachDecision("ambiguous", None, tier, {**evidence, "reason": "tie"})
        return AttachDecision("matched", best.candidate.feature_id, tier, evidence)
    return AttachDecision("none", None, None, evidence)


# ── 기존 MCST Feature 전환 계획(§8.1) ──────────────────────────────────────

PlanAction = Literal["retire", "attach", "collapse", "keep", "ambiguous"]


@dataclass(frozen=True, slots=True)
class PlanFeature:
    """계획 대상 MCST Feature 하나와 그 거리 후보."""

    feature_id: str
    dataset_key: str
    name: str
    created_at: str
    place_list: bool
    """장소 목록(속성 목록이 아닌 것)의 Feature면 참 — collapse 생존자 우선순위."""
    pet_business: bool
    master_category_prefixes: tuple[str, ...] | None
    candidates: tuple[AttachCandidate, ...]


@dataclass(frozen=True, slots=True)
class PlanEntry:
    feature_id: str
    dataset_key: str
    action: PlanAction
    target_feature_id: str | None
    evidence: Mapping[str, object]


def plan_existing_features(features: Sequence[PlanFeature]) -> list[PlanEntry]:
    """운영 MCST Feature 전부의 전환 action을 정한다(§8.1). 결정적·순수.

    1. 반려 업종 → ``retire``.
    2. 나머지는 :func:`decide_attach` — tier 1 채택 → ``attach``, 다툼 → ``ambiguous``.
       tier 2 후보에서는 ``retire``될 Feature를 뺀다.
    3. tier 2 채택은 간선이다. 간선의 상대가 ``attach``면 같은 master로 ``attach``,
       ``ambiguous``면 ``ambiguous``. 남은 간선으로 묶음(union-find)을 만들고 생존자
       (장소 목록 > 속성 목록, ``created_at``, ``feature_id`` 순)만 ``keep``, 나머지는 ``collapse``.
    """

    by_id = {feature.feature_id: feature for feature in features}
    retire = frozenset(f.feature_id for f in features if f.pet_business)
    entries: dict[str, PlanEntry] = {}
    edges: dict[str, str] = {}
    evidences: dict[str, Mapping[str, object]] = {}
    for feature in features:
        if feature.feature_id in retire:
            entries[feature.feature_id] = PlanEntry(
                feature.feature_id, feature.dataset_key, "retire", None, {"reason": "pet_business"}
            )
            continue
        decision = decide_attach(
            feature.name,
            feature.candidates,
            master_category_prefixes=feature.master_category_prefixes,
            exclude_feature_ids=retire | {feature.feature_id},
        )
        evidences[feature.feature_id] = decision.evidence
        if decision.state == "ambiguous":
            entries[feature.feature_id] = PlanEntry(
                feature.feature_id, feature.dataset_key, "ambiguous", None, decision.evidence
            )
        elif decision.state == "matched" and decision.tier == 1:
            entries[feature.feature_id] = PlanEntry(
                feature.feature_id,
                feature.dataset_key,
                "attach",
                decision.target_feature_id,
                decision.evidence,
            )
        elif decision.state == "matched" and decision.target_feature_id in by_id:
            edges[feature.feature_id] = decision.target_feature_id

    # tier 2 간선 — 상대가 이미 정해졌으면 그 결과를 따른다(연쇄는 고정점까지).
    changed = True
    while changed:
        changed = False
        for source, target in list(edges.items()):
            settled = entries.get(target)
            if settled is None or settled.action not in ("attach", "ambiguous"):
                continue
            feature = by_id[source]
            entries[source] = PlanEntry(
                source,
                feature.dataset_key,
                settled.action,
                settled.target_feature_id,
                {**evidences.get(source, {}), "via": target},
            )
            del edges[source]
            changed = True

    parent: dict[str, str] = {}

    def find(node: str) -> str:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for source, target in edges.items():
        root_a, root_b = find(source), find(target)
        if root_a != root_b:
            parent[root_a] = root_b

    groups: dict[str, list[str]] = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)
    for members in groups.values():
        survivor = min(
            members,
            key=lambda fid: (not by_id[fid].place_list, by_id[fid].created_at, fid),
        )
        for member in members:
            if member in entries:
                continue
            feature = by_id[member]
            if member == survivor:
                entries[member] = PlanEntry(
                    member, feature.dataset_key, "keep", None, evidences.get(member, {})
                )
            else:
                entries[member] = PlanEntry(
                    member,
                    feature.dataset_key,
                    "collapse",
                    survivor,
                    evidences.get(member, {}),
                )
    for feature in features:
        if feature.feature_id not in entries:
            entries[feature.feature_id] = PlanEntry(
                feature.feature_id,
                feature.dataset_key,
                "keep",
                None,
                evidences.get(feature.feature_id, {}),
            )
    return [entries[feature.feature_id] for feature in features]
