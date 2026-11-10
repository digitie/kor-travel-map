"""``kortravelmap.core.theme_attach`` — 붙임 규칙 theme-attach-v1(ADR-121 §5)."""

from __future__ import annotations

import pytest

from kortravelmap.core.theme_attach import (
    AttachCandidate,
    PlanFeature,
    decide_attach,
    haversine_m,
    normalize_place_name,
    plan_existing_features,
    trigram_similarity,
)


def _c(
    fid: str,
    name: str,
    d: float,
    *,
    tier: int = 1,
    category: str = "01040100",
    published: bool = True,
) -> AttachCandidate:
    return AttachCandidate(
        feature_id=fid,
        name=name,
        category=category,
        distance_m=d,
        tier=tier,  # type: ignore[arg-type]
        published=published,
    )


# ── 정규화 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "core", "branch"),
    [
        ("국립중앙박물관", "국립중앙박물관", None),
        ("(주)교보문고 광화문점", "교보문고", "광화문점"),
        ("주식회사 알라딘 중고서점", "알라딘중고서점", None),
        ("홍콩반점", "홍콩반점", None),
        ("스타벅스(강남점)", "스타벅스", "강남점"),
        ("본점", "본점", None),
        ("Café  Lumière!", "cafélumière", None),
    ],
)
def test_normalize_place_name(raw: str, core: str, branch: str | None) -> None:
    normalized = normalize_place_name(raw)
    assert normalized.core == core
    assert normalized.branch == branch


def test_trigram_similarity_matches_pg_trgm_definition() -> None:
    # pg_trgm: similarity('abc','abc') = 1, 서로 다른 낱말은 0.
    assert trigram_similarity("abc", "abc") == 1.0
    assert trigram_similarity("abc", "xyz") == 0.0
    # "  abc " → {"  a"," ab","abc","bc "}, "  abd " → {"  a"," ab","abd","bd "}: 2/6.
    assert trigram_similarity("abc", "abd") == pytest.approx(2 / 6)
    assert trigram_similarity("", "abc") == 0.0


def test_haversine_one_degree_latitude() -> None:
    assert haversine_m(127.0, 37.0, 127.0, 38.0) == pytest.approx(111_195, rel=1e-3)


# ── 채택 경계 ────────────────────────────────────────────────────────────


def test_accepts_close_and_similar() -> None:
    decision = decide_attach(
        "국립중앙박물관", [_c("m1", "국립중앙박물관", 40)], master_category_prefixes=None
    )
    assert (decision.state, decision.target_feature_id, decision.tier) == ("matched", "m1", 1)


def test_rejects_beyond_150m_even_if_identical() -> None:
    decision = decide_attach(
        "국립중앙박물관", [_c("m1", "국립중앙박물관", 151)], master_category_prefixes=None
    )
    assert decision.state == "none"


def test_mid_distance_needs_high_score() -> None:
    # 100m에서는 s ≥ 0.8이 필요하다 — 한 글자 다른 짧은 이름은 떨어진다.
    weak = decide_attach("가나다라", [_c("m1", "가나다마", 100)], master_category_prefixes=None)
    assert weak.state == "none"
    strong = decide_attach(
        "서울시립미술관", [_c("m1", "서울시립미술관", 100)], master_category_prefixes=None
    )
    assert strong.state == "matched"


def test_branch_mismatch_is_rejected() -> None:
    decision = decide_attach(
        "스타벅스(강남점)",
        [_c("m1", "스타벅스(역삼점)", 10, category="02020101")],
        master_category_prefixes=None,
    )
    assert decision.state == "none"


def test_generic_name_needs_30m_and_near_exact() -> None:
    far = decide_attach("공영주차장", [_c("m1", "공영주차장", 40)], master_category_prefixes=None)
    assert far.state == "none"
    near = decide_attach("공영주차장", [_c("m1", "공영주차장", 20)], master_category_prefixes=None)
    assert near.state == "matched"


def test_category_prefix_filters_tier1_only() -> None:
    master = _c("m1", "책방오늘", 10, category="02010000")
    tier2 = _c("x2", "책방오늘", 10, tier=2, category="00000000")
    decision = decide_attach("책방오늘", [master, tier2], master_category_prefixes=("0104",))
    assert (decision.state, decision.target_feature_id, decision.tier) == ("matched", "x2", 2)


def test_tier1_beats_tier2() -> None:
    decision = decide_attach(
        "수성유원지",
        [_c("x2", "수성유원지", 5, tier=2), _c("m1", "수성유원지", 40)],
        master_category_prefixes=None,
    )
    assert (decision.target_feature_id, decision.tier) == ("m1", 1)


def test_tie_between_two_masters_is_ambiguous() -> None:
    decision = decide_attach(
        "한국민속촌",
        [_c("m1", "한국민속촌", 30), _c("m2", "한국민속촌", 35)],
        master_category_prefixes=None,
    )
    assert decision.state == "ambiguous"


def test_suppressed_master_makes_ambiguous() -> None:
    decision = decide_attach(
        "한국민속촌", [_c("m1", "한국민속촌", 30, published=False)], master_category_prefixes=None
    )
    assert decision.state == "ambiguous"


def test_exclude_self() -> None:
    decision = decide_attach(
        "가",
        [_c("self", "가", 0, tier=2)],
        master_category_prefixes=None,
        exclude_feature_ids=frozenset({"self"}),
    )
    assert decision.state == "none"


# ── 전환 계획 ────────────────────────────────────────────────────────────


def _pf(
    fid: str,
    *,
    dataset: str = "mcst_barrier_free_places_csv",
    name: str = "수성유원지",
    created: str = "2026-01-01",
    place_list: bool = False,
    pet_business: bool = False,
    candidates: tuple[AttachCandidate, ...] = (),
) -> PlanFeature:
    return PlanFeature(
        feature_id=fid,
        dataset_key=dataset,
        name=name,
        created_at=created,
        place_list=place_list,
        pet_business=pet_business,
        master_category_prefixes=None,
        candidates=candidates,
    )


def test_plan_retire_attach_collapse_keep() -> None:
    features = [
        _pf("pet", pet_business=True, name="행복동물병원"),
        _pf("a", candidates=(_c("M", "수성유원지", 20),)),
        _pf(
            "b",
            dataset="mcst_family_infant_culture_facilities_csv",
            name="대구미술관",
            created="2026-02-01",
            candidates=(_c("c", "대구미술관", 5, tier=2),),
        ),
        _pf(
            "c",
            dataset="mcst_media_famous_places_csv",
            name="대구미술관",
            created="2026-03-01",
            place_list=True,
            candidates=(_c("b", "대구미술관", 5, tier=2),),
        ),
        _pf("lonely", name="어딘가"),
    ]
    plan = {entry.feature_id: entry for entry in plan_existing_features(features)}
    assert plan["pet"].action == "retire"
    assert (plan["a"].action, plan["a"].target_feature_id) == ("attach", "M")
    # 장소 목록 Feature가 생존자다(생성이 늦어도).
    assert (plan["c"].action, plan["c"].target_feature_id) == ("keep", None)
    assert (plan["b"].action, plan["b"].target_feature_id) == ("collapse", "c")
    assert plan["lonely"].action == "keep"


def test_plan_tier2_edge_to_attaching_feature_follows_master() -> None:
    features = [
        _pf("a", candidates=(_c("M", "수성유원지", 20),)),
        _pf("b", candidates=(_c("a", "수성유원지", 5, tier=2),)),
    ]
    plan = {entry.feature_id: entry for entry in plan_existing_features(features)}
    assert (plan["b"].action, plan["b"].target_feature_id) == ("attach", "M")


def test_plan_does_not_collapse_into_retiring_pet_business() -> None:
    features = [
        _pf("pet", pet_business=True, name="해피펫"),
        _pf("x", name="해피펫", candidates=(_c("pet", "해피펫", 3, tier=2),)),
    ]
    plan = {entry.feature_id: entry for entry in plan_existing_features(features)}
    assert plan["x"].action == "keep"
