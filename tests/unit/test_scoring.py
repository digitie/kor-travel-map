"""``test_scoring`` — Record Linkage scoring (ADR-016, PR#29)."""

from __future__ import annotations

from decimal import Decimal

import pytest

from kortravelmap.core.scoring import (
    SPATIAL_DECAY_METERS,
    THRESHOLD_AUTO,
    THRESHOLD_MANUAL,
    WEIGHT_CATEGORY,
    WEIGHT_NAME,
    WEIGHT_SPATIAL,
    DedupDecision,
    category_similarity,
    classify_decision,
    haversine_meters,
    name_similarity,
    normalize_kr_place_name,
    score_pair,
    spatial_similarity,
)
from kortravelmap.dto import Coordinate

# -- ADR-016 가중치 정합 ----------------------------------------------------


@pytest.mark.unit
def test_weights_sum_to_one() -> None:
    """ADR-016 — 가중치 합은 정확히 1.0."""
    assert abs((WEIGHT_NAME + WEIGHT_SPATIAL + WEIGHT_CATEGORY) - 1.0) < 1e-9


@pytest.mark.unit
def test_thresholds_ordered() -> None:
    """AUTO > MANUAL > 0."""
    assert THRESHOLD_AUTO > THRESHOLD_MANUAL > 0


@pytest.mark.unit
def test_adr_016_values() -> None:
    """ADR-016 SPEC V8 D-14 명세 값 확인 — 변경 시 ADR 동기 필요."""
    assert WEIGHT_NAME == 0.45
    assert WEIGHT_SPATIAL == 0.35
    assert WEIGHT_CATEGORY == 0.20
    assert THRESHOLD_AUTO == 0.85
    assert THRESHOLD_MANUAL == 0.65
    assert SPATIAL_DECAY_METERS == 50.0


# -- normalize_kr_place_name ----------------------------------------------


@pytest.mark.unit
def test_normalize_lowercase() -> None:
    """ASCII는 소문자 + 공백 제거 (한국어 일관)."""
    assert normalize_kr_place_name("Seoul Station") == "seoulstation"


@pytest.mark.unit
def test_normalize_strips_all_whitespace() -> None:
    """한국어 장소명은 공백 변형 흡수 위해 모든 공백 제거."""
    assert normalize_kr_place_name("  서울  시청  ") == "서울시청"
    assert normalize_kr_place_name("서울 특별 시청") == "서울특별시청"


@pytest.mark.unit
def test_normalize_strips_parentheses() -> None:
    """괄호 내용 제거."""
    assert normalize_kr_place_name("서울시청(본관)") == "서울시청"
    assert normalize_kr_place_name("장소[분점]") == "장소"


@pytest.mark.unit
def test_normalize_empty() -> None:
    """빈 문자열은 그대로."""
    assert normalize_kr_place_name("") == ""


# -- name_similarity ------------------------------------------------------


@pytest.mark.unit
def test_name_sim_identical() -> None:
    """같은 이름은 1.0."""
    assert name_similarity("서울시청", "서울시청") == 1.0


@pytest.mark.unit
def test_name_sim_similar_korean() -> None:
    """띄어쓰기 차이는 정규화 후 동일 → 1.0."""
    assert name_similarity("서울 시청", "서울시청") == 1.0


@pytest.mark.unit
def test_name_sim_different() -> None:
    """완전히 다른 이름은 낮은 점수."""
    sim = name_similarity("서울시청", "부산해운대")
    assert 0.0 <= sim <= 0.6  # jaro_winkler는 0이 아닐 수 있음


@pytest.mark.unit
def test_name_sim_empty_returns_zero() -> None:
    """빈 입력은 0.0."""
    assert name_similarity("", "서울시청") == 0.0
    assert name_similarity("서울시청", "") == 0.0


# -- spatial_similarity ---------------------------------------------------


def _coord(lon: str, lat: str) -> Coordinate:
    return Coordinate(lon=Decimal(lon), lat=Decimal(lat))


@pytest.mark.unit
def test_spatial_sim_same_point() -> None:
    """동일 좌표는 1.0."""
    c = _coord("126.97", "37.57")
    assert spatial_similarity(c, c) == 1.0


@pytest.mark.unit
def test_spatial_sim_decays_with_distance() -> None:
    """거리 증가 시 점수 감소 (exp decay)."""
    c1 = _coord("126.97", "37.57")
    c_near = _coord("126.9701", "37.5701")  # ~10m
    c_far = _coord("126.9800", "37.5800")  # ~1km

    sim_near = spatial_similarity(c1, c_near)
    sim_far = spatial_similarity(c1, c_far)
    assert sim_near > sim_far
    # 1km는 사실상 0 (exp(-1000/50) ≈ 2e-9).
    assert sim_far < 0.01


@pytest.mark.unit
def test_spatial_sim_50m_decay_check() -> None:
    """50m에서 sim ≈ 1/e ≈ 0.37 (ADR-016 정의 검증)."""
    c1 = _coord("126.97000", "37.57000")
    # 위도 1° ≈ 111km, 경도 1° ≈ 88km (37.5°N)
    # 50m ≈ 0.00045° (위도)
    c_50m = _coord("126.97000", "37.57045")
    sim = spatial_similarity(c1, c_50m)
    # exp(-1) ≈ 0.368. 위도 변환 오차 감안 ±0.05.
    assert 0.30 < sim < 0.45


@pytest.mark.unit
def test_spatial_sim_none_returns_zero() -> None:
    """None 좌표는 0."""
    c = _coord("126.97", "37.57")
    assert spatial_similarity(None, c) == 0.0
    assert spatial_similarity(c, None) == 0.0
    assert spatial_similarity(None, None) == 0.0


# -- haversine_meters -----------------------------------------------------


@pytest.mark.unit
def test_haversine_seoul_busan() -> None:
    """서울-부산 직선 ≈ 325km (UTM-K 측정과 동일 범위)."""
    seoul = _coord("126.9784", "37.5666")
    busan = _coord("129.0756", "35.1796")
    d_m = haversine_meters(seoul, busan)
    # 320~335km 범위 (test_crs와 동일 기준).
    assert 320_000 < d_m < 335_000


@pytest.mark.unit
def test_haversine_zero_for_same_point() -> None:
    c = _coord("126.97", "37.57")
    assert haversine_meters(c, c) == 0.0


# -- category_similarity --------------------------------------------------


@pytest.mark.unit
def test_category_sim_identical() -> None:
    assert category_similarity({"01020101"}, {"01020101"}) == 1.0


@pytest.mark.unit
def test_category_sim_jaccard() -> None:
    """Jaccard = |A∩B| / |A∪B|."""
    # |∩|=1, |∪|=2 → 0.5
    assert category_similarity({"a", "b"}, {"a"}) == 0.5
    # |∩|=1, |∪|=3 → 1/3
    assert category_similarity({"a", "b"}, {"a", "c"}) == pytest.approx(1 / 3)


@pytest.mark.unit
def test_category_sim_empty_returns_zero() -> None:
    assert category_similarity(set(), {"a"}) == 0.0
    assert category_similarity({"a"}, set()) == 0.0
    assert category_similarity(None, {"a"}) == 0.0


# -- score_pair (종합) ----------------------------------------------------


@pytest.mark.unit
def test_score_pair_identical_is_one() -> None:
    """모든 차원 완전 일치 → 1.0."""
    c = _coord("126.97", "37.57")
    s = score_pair(
        name_a="서울시청", name_b="서울시청",
        coord_a=c, coord_b=c,
        cat_a={"01020101"}, cat_b={"01020101"},
    )
    assert s == 1.0


@pytest.mark.unit
def test_score_pair_completely_different_is_low() -> None:
    """모든 차원 불일치 + 먼 좌표 → 낮은 점수."""
    c1 = _coord("126.97", "37.57")  # 서울
    c2 = _coord("129.08", "35.18")  # 부산
    s = score_pair(
        name_a="서울시청", name_b="부산해운대",
        coord_a=c1, coord_b=c2,
        cat_a={"01020101"}, cat_b={"02020101"},
    )
    assert s < THRESHOLD_MANUAL


@pytest.mark.unit
def test_score_pair_no_coords_only_name_category() -> None:
    """좌표 없으면 name + category로만 계산 (spatial=0)."""
    s = score_pair(
        name_a="서울시청", name_b="서울시청",
        coord_a=None, coord_b=None,
        cat_a={"01020101"}, cat_b={"01020101"},
    )
    # 1.0 * 0.45 + 0 * 0.35 + 1.0 * 0.20 = 0.65
    assert s == pytest.approx(0.65)


# -- classify_decision ----------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (1.00, DedupDecision.AUTO_MERGE),
        (0.85, DedupDecision.AUTO_MERGE),  # 경계는 AUTO
        (0.84, DedupDecision.MANUAL_REVIEW),
        (0.70, DedupDecision.MANUAL_REVIEW),
        (0.65, DedupDecision.MANUAL_REVIEW),  # 경계는 MANUAL
        (0.64, DedupDecision.KEEP_SEPARATE),
        (0.30, DedupDecision.KEEP_SEPARATE),
        (0.00, DedupDecision.KEEP_SEPARATE),
    ],
)
def test_classify_decision_thresholds(score: float, expected: str) -> None:
    assert classify_decision(score) == expected


@pytest.mark.unit
def test_decision_constants_unique() -> None:
    """DedupDecision 3 상수가 서로 다른 값."""
    assert len({
        DedupDecision.AUTO_MERGE,
        DedupDecision.MANUAL_REVIEW,
        DedupDecision.KEEP_SEPARATE,
    }) == 3


# -- normalize_kr_place_name 엣지 회귀 (I 영역 확장) --------------------------
#
# provider raw 장소명은 한국어 + 전각 + 영문 + 한자 + 괄호 + 숫자가 자주
# 혼재. 한 두 패턴이라도 빠지면 dedup name_similarity가 false-negative.


@pytest.mark.unit
def test_normalize_fullwidth_ascii_to_halfwidth() -> None:
    """NFKC: 전각 영문/숫자 → 반각. 동일 가게의 영문 표기 흡수."""
    # "ＳＴＡＲＢＵＣＫＳ" (전각) → "starbucks" (반각 + lower)
    assert normalize_kr_place_name("ＳＴＡＲＢＵＣＫＳ") == "starbucks"


@pytest.mark.unit
def test_normalize_fullwidth_digits_normalized() -> None:
    """전각 숫자 (０-９) → 반각."""
    # "지점１" → "지점1"
    assert normalize_kr_place_name("지점１") == "지점1"
    assert normalize_kr_place_name("１２３") == "123"


@pytest.mark.unit
def test_normalize_korean_english_mix() -> None:
    """한국어 + 영문 mix — 공백 제거 + 소문자."""
    assert normalize_kr_place_name("서울 Hotel 신라") == "서울hotel신라"
    assert normalize_kr_place_name("SK 주유소") == "sk주유소"


@pytest.mark.unit
def test_normalize_multiple_parens() -> None:
    """괄호가 여러 개 — 모두 제거."""
    assert normalize_kr_place_name("장소(분점)(서울)") == "장소"
    assert normalize_kr_place_name("[a]장소[b]") == "장소"


@pytest.mark.unit
def test_normalize_mixed_paren_types() -> None:
    """소괄호 + 대괄호 mix."""
    assert normalize_kr_place_name("장소(주)[지점1]") == "장소"


@pytest.mark.unit
def test_normalize_newline_tab_whitespace_removed() -> None:
    """탭/newline도 공백 — 전부 제거."""
    assert normalize_kr_place_name("서울\n시청") == "서울시청"
    assert normalize_kr_place_name("서울\t시청") == "서울시청"
    assert normalize_kr_place_name("서울\r\n시청") == "서울시청"


@pytest.mark.unit
def test_normalize_only_whitespace_returns_empty() -> None:
    """공백만 → 빈 문자열."""
    assert normalize_kr_place_name("   ") == ""
    assert normalize_kr_place_name("\t\n  ") == ""


@pytest.mark.unit
def test_normalize_hanja_preserved_via_nfkc() -> None:
    """한자(漢字)는 NFKC 후 그대로 보존 — 같은 한자 → name_sim 1.0."""
    # NFKC는 한자 그대로 둠 (호환 분해 대상 아님).
    norm = normalize_kr_place_name("景福宮")
    assert norm == "景福宮"
    # 동일 입력 → name_sim 1.0.
    assert name_similarity("景福宮", "景福宮") == 1.0


@pytest.mark.unit
def test_normalize_punctuation_preserved() -> None:
    """점/콤마 등 일반 punct는 공백·괄호와 달리 보존 — 식별성 유지."""
    # 점은 안 지움 (단, NFKC + lower만 적용).
    assert normalize_kr_place_name("S.K.주유소") == "s.k.주유소"
    # 콤마.
    assert "," in normalize_kr_place_name("a,b")


@pytest.mark.unit
def test_normalize_unbalanced_paren_still_handled() -> None:
    """짝 안 맞는 괄호 — 정규식은 균형 잡힌 쌍만 제거 — 짝 없으면 그대로 둠."""
    # ")만 있는 경우 — 패턴 매치 안 됨.
    assert normalize_kr_place_name("장소)") == "장소)"


@pytest.mark.unit
def test_name_sim_korean_english_normalized() -> None:
    """전각/반각 영문 mix — 정규화 후 동일이면 1.0."""
    # 같은 가게의 다른 표기.
    assert name_similarity("서울Hotel", "서울ＨＯＴＥＬ") == pytest.approx(1.0, abs=0.01)


@pytest.mark.unit
def test_name_sim_jaro_winkler_partial_overlap() -> None:
    """jaro_winkler는 부분 일치도 점수 — "불국사" vs "불국사터" 같은 변형."""
    sim = name_similarity("불국사", "불국사터")
    # 완전 일치 아니지만 prefix 같아 jaro_winkler 보너스로 높은 점수.
    assert 0.85 < sim < 1.0


@pytest.mark.unit
def test_name_sim_one_empty_after_normalize_zero() -> None:
    """정규화 후 한쪽이 비면 0."""
    # 괄호만 — 정규화 후 빈 문자열.
    assert name_similarity("(주)", "서울시청") == 0.0
    # 공백만 — 정규화 후 빈 문자열.
    assert name_similarity("   ", "서울시청") == 0.0


# ── master 선정 (ADR-016 병합 시) ────────────────────────────────────────

from datetime import UTC, datetime  # noqa: E402

from kortravelmap.core.scoring import (  # noqa: E402
    DEFAULT_SOURCE_PRIORITY,
    MasterCandidate,
    select_master,
    source_priority,
)

_T0 = datetime(2026, 1, 1, tzinfo=UTC)
_T1 = datetime(2026, 6, 1, tzinfo=UTC)


@pytest.mark.unit
def test_source_priority_known_and_default() -> None:
    # 행안부(mois)가 TourAPI(visitkorea)보다 높음 (ADR-016).
    assert source_priority("python-mois-api") > source_priority(
        "python-visitkorea-api"
    )
    # 미등록 provider → 기본값.
    assert source_priority("python-unknown-api") == DEFAULT_SOURCE_PRIORITY
    # 사용자 등록(provider 부재) → 0.
    assert source_priority(None) == 0
    assert source_priority("") == 0


@pytest.mark.unit
def test_select_master_coord_beats_no_coord() -> None:
    a = MasterCandidate("f_a", has_coord=False, updated_at=_T1, provider="python-mois-api")
    b = MasterCandidate("f_b", has_coord=True, updated_at=_T0, provider=None)
    # 좌표 보유가 1순위 — b가 master (updated_at/우선순위는 a가 높아도 무시).
    assert select_master(a, b) == ("f_b", "f_a")


@pytest.mark.unit
def test_select_master_source_priority_beats_recency() -> None:
    # #1468: 원천 우선순위가 updated_at보다 앞이다. updated_at은 적재 시각이라 거의 항상
    # 달라서, 그것이 앞이면 나중에 적재된 테마 목록(MCST)이 원장(MOIS)을 이긴다.
    a = MasterCandidate("f_a", has_coord=True, updated_at=_T1, provider="python-mcst-api")
    b = MasterCandidate("f_b", has_coord=True, updated_at=_T0, provider="python-mois-api")
    assert select_master(a, b) == ("f_b", "f_a")
    user = MasterCandidate("f_u", has_coord=True, updated_at=_T1, provider=None)
    assert select_master(user, b) == ("f_b", "f_u")


@pytest.mark.unit
def test_select_master_recency_breaks_priority_tie() -> None:
    a = MasterCandidate("f_a", has_coord=True, updated_at=_T1, provider="python-mois-api")
    b = MasterCandidate("f_b", has_coord=True, updated_at=_T0, provider="python-mois-api")
    # 좌표·원천 동률 — 최신(updated_at) a가 master.
    assert select_master(a, b) == ("f_a", "f_b")


@pytest.mark.unit
def test_source_priority_ranks_sources_added_in_1468() -> None:
    # 셋 다 표에 없어 미등록 기본(10)으로 떨어지던 원천이다.
    standard = source_priority("data.go.kr-standard")
    mcst = source_priority("python-mcst-api")
    youtube = source_priority("kor-travel-concierge-youtube")
    assert standard == source_priority("python-datagokr-api")
    assert source_priority("python-mois-api") > standard > source_priority("python-visitkorea-api")
    assert source_priority("python-visitkorea-api") > mcst > DEFAULT_SOURCE_PRIORITY
    assert DEFAULT_SOURCE_PRIORITY > youtube > source_priority(None)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("master", "loser"),
    [
        # 문화유산은 국가유산청이 원장(KNPS 문화자원보다 위, 둘 다 provider 값은 45).
        (
            ("python-krheritage-api", "krheritage_heritage_features"),
            ("python-knps-api", "knps_cultural_resources"),
        ),
        # 같은 이름의 휴양림·수목원은 휴양림(같은 산림청 provider 안).
        (
            ("python-krforest-api", "krforest_recreation_forests"),
            ("python-krforest-api", "krforest_arboretums"),
        ),
        # 국립공원 안 탐방로는 KNPS가 원장.
        (
            ("python-knps-api", "knps_trails"),
            ("python-krforest-api", "krforest_mountain_trails"),
        ),
        # 캠핑장·음식점: MOIS가 MCST 테마 목록보다 위. 박물관: 표준데이터가 MCST보다 위.
        (("python-mois-api", "mois_license_features_bulk"), ("python-mcst-api", "x")),
        (("data.go.kr-standard", "datagokr_museums"), ("python-mcst-api", "x")),
        # KNPS 야영장 ↔ MCST 캠핑장 목록.
        (("python-knps-api", "knps_campgrounds"), ("python-mcst-api", "x")),
    ],
)
def test_select_master_dataset_rules_for_1468_pairs(
    master: tuple[str, str], loser: tuple[str, str]
) -> None:
    # 패배 쪽이 더 최근에 적재돼도(_T1) 원천이 정한다.
    m = MasterCandidate("f_z", has_coord=True, updated_at=_T0, provider=master[0],
                        dataset_key=master[1])
    lo = MasterCandidate("f_a", has_coord=True, updated_at=_T1, provider=loser[0],
                         dataset_key=loser[1])
    assert select_master(m, lo) == ("f_z", "f_a")
    assert select_master(lo, m) == ("f_z", "f_a")


@pytest.mark.unit
def test_dataset_priority_falls_back_to_provider() -> None:
    assert source_priority("python-knps-api", "knps_trails") == source_priority("python-knps-api")
    assert source_priority("python-knps-api", None) == source_priority("python-knps-api")
    assert source_priority("python-knps-api", "knps_cultural_resources") < source_priority(
        "python-krheritage-api", "krheritage_heritage_features"
    )


@pytest.mark.unit
def test_select_master_source_priority_with_equal_recency() -> None:
    a = MasterCandidate("f_a", has_coord=True, updated_at=_T0, provider="python-visitkorea-api")
    b = MasterCandidate("f_b", has_coord=True, updated_at=_T0, provider="python-mois-api")
    # 좌표·updated_at 동률 — 원천 우선순위 높은 mois(b)가 master.
    assert select_master(a, b) == ("f_b", "f_a")


@pytest.mark.unit
def test_select_master_full_tie_lexicographic() -> None:
    a = MasterCandidate("f_b", has_coord=True, updated_at=_T0, provider="python-mois-api")
    b = MasterCandidate("f_a", has_coord=True, updated_at=_T0, provider="python-mois-api")
    # 완전 동률 — feature_id 사전순 작은 f_a가 master (결정적).
    assert select_master(a, b) == ("f_a", "f_b")
    # 인자 순서 무관.
    assert select_master(b, a) == ("f_a", "f_b")


@pytest.mark.unit
def test_master_source_prefers_highest_priority_primary_link() -> None:
    # 병합을 흡수한 Feature는 primary link가 여럿이다 — 순서가 아니라 원천 순위로 고른다.
    from kortravelmap.infra.merge_repo import _best_source

    assert _best_source(
        ["python-mcst-api", "python-mois-api", "python-visitkorea-api"],
        ["mcst_x", "mois_license_features_bulk", "visitkorea_tourist_attractions"],
        [True, True, False],
    ) == ("python-mois-api", "mois_license_features_bulk")
    # primary가 없으면 전체에서, 아무것도 없으면 사용자 등록(None).
    assert _best_source(["python-mcst-api"], ["mcst_x"], [False]) == ("python-mcst-api", "mcst_x")
    assert _best_source([], [], []) == (None, None)
    # 동률은 SQL이 준 순서의 앞쪽.
    assert _best_source(
        ["python-knps-api", "python-krheritage-api"], ["knps_trails", "h"], [True, True]
    ) == ("python-knps-api", "knps_trails")

@pytest.mark.unit
def test_select_master_recreation_forest_beats_mois_lodging() -> None:
    # 소유자 결정(2026-11-10): 휴양림 ↔ MOIS 숙박 쌍은 휴양림이 master다. MOIS가 더 최근이어도.
    forest = MasterCandidate("f_z", has_coord=True, updated_at=_T0,
                             provider="python-krforest-api",
                             dataset_key="krforest_recreation_forests")
    mois = MasterCandidate("f_a", has_coord=True, updated_at=_T1, provider="python-mois-api",
                           dataset_key="mois_license_features_bulk")
    assert select_master(forest, mois) == ("f_z", "f_a")
    assert select_master(mois, forest) == ("f_z", "f_a")
    # 같은 이름의 수목원 쌍도 여전히 휴양림이 master다.
    arboretum = MasterCandidate("f_b", has_coord=True, updated_at=_T1,
                                provider="python-krforest-api", dataset_key="krforest_arboretums")
    assert select_master(arboretum, forest) == ("f_z", "f_b")