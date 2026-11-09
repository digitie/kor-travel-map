"""dedup 상한 가지치기는 판정을 바꾸지 않는다(#1459).

``core.dedup``은 이름 유사도를 부르기 전에 "이름이 완전히 같아도 수동 검토 임계값에 못
미치는" 쌍을 거른다. 같은 입력을 ``score_pair``/``classify_decision``으로 전수 판정한 결과와
후보 집합이 같아야 한다 — 가지치기일 뿐 판정 규칙이 아니다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal

import pytest

from kortravelmap.core.dedup import find_dedup_candidates
from kortravelmap.core.scoring import DedupDecision, classify_decision, score_pair
from kortravelmap.dto import Coordinate

pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _F:
    feature_id: str
    name: str
    coord: Coordinate | None
    category: str
    kind: str = "place"
    detail: object = None


def _features(seed: int, prefix: str) -> list[_F]:
    rng = random.Random(seed)
    names = ["부산타워", "부산 타워", "광안대교", "광안리해수욕장", "용두산공원", "타워"]
    cats = ["01050300", "01000000", "01050100"]
    out: list[_F] = []
    for n in range(60):
        # 0~400 m 안에 몰아 공간 점수가 고르게 퍼지게 한다.
        lat = Decimal("35.1") + Decimal(rng.randint(0, 400)) / Decimal(111_000)
        coord = None if n % 17 == 0 else Coordinate(lon=Decimal("129.03"), lat=lat)
        out.append(_F(f"{prefix}{n}", rng.choice(names), coord, rng.choice(cats)))
    return out


def test_pruned_candidates_equal_the_brute_force_decision() -> None:
    left, right = _features(1, "a"), _features(2, "b")
    expected = set()
    for a in left:
        for b in right:
            score = score_pair(
                name_a=a.name,
                name_b=b.name,
                coord_a=a.coord,
                coord_b=b.coord,
                cat_a={a.category},
                cat_b={b.category},
            )
            if classify_decision(score) != DedupDecision.KEEP_SEPARATE:
                expected.add((a.feature_id, b.feature_id))
    got = {(c.feature_id_a, c.feature_id_b) for c in find_dedup_candidates(left, right)}
    assert expected  # 표본이 실제로 후보를 낸다(공허한 동치가 아니다)
    assert got == expected
