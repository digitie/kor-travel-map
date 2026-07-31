"""Feature link 승인 근거(``match_basis``)의 단일 정의.

`0072`가 link provenance 축을 도입하면서 "이 승인을 믿어도 되는가"의 판정이 **두 곳에
서로 다른 모양으로** 생겼다:

- 공개 표면(`curation_repo._trusted_link_sql`)은 **denylist** — `<> 'legacy_unattributed'`
- merge 재타게팅(`merge_repo._MOVE_CURATION_ITEMS_SQL`)은 **whitelist** — 3값 열거

값이 하나 늘 때마다 denylist는 자동으로 믿고 whitelist는 조용히 뒤처진다. 그러면 공개
표면이 노출하는 link를 merge가 `revoked`로 끊는다 — 어느 쪽도 오류를 내지 않으므로
증상이 "링크가 언젠가 사라짐"으로만 나타난다. 그래서 판정을 여기 한 곳에 둔다.

두 곳 모두 **whitelist**로 맞춘다. 모르는 근거를 기본 신뢰하는 denylist보다 fail-close이고,
`0072`가 세운 원칙("근거 없는 link는 공개하지 않는다")과 같은 방향이다.
"""

from __future__ import annotations

from typing import Final

#: 근거를 복구할 수 없어 `0072`가 이관한 값. 어떤 경로에서도 공개 승인 근거가 아니다.
UNATTRIBUTED_LINK_BASIS: Final[str] = "legacy_unattributed"

#: 공개 노출과 merge 재타게팅이 함께 신뢰하는 승인 근거.
#:
#: - ``csv_explicit_feature_id`` — import CSV가 feature_id를 직접 지정
#: - ``admin_review``            — 운영자 검토 승인
#: - ``forward_recovery``        — merge가 승자에게 이어붙인 결정
#: - ``source_rule``             — provider source record + 선택 rule로 재구성되는 근거
#:                                 (`0073`, T-VN-H40)
#:
#: DB CHECK ``ck_curation_link_decisions_basis``와 짝을 이룬다. 값을 늘릴 때는
#: 마이그레이션의 CHECK와 이 집합을 함께 고친다 — 한쪽만 고치면
#: `tests/unit/test_curation_link_basis.py`가 잡는다.
TRUSTED_LINK_BASES: Final[frozenset[str]] = frozenset(
    {
        "csv_explicit_feature_id",
        "admin_review",
        "forward_recovery",
        "source_rule",
    }
)

#: DB CHECK가 허용하는 전체 값.
ALL_LINK_BASES: Final[frozenset[str]] = TRUSTED_LINK_BASES | {UNATTRIBUTED_LINK_BASIS}


def trusted_basis_sql(column: str) -> str:
    """``column``이 신뢰 가능한 근거인지 판정하는 SQL 술어를 만든다.

    값은 이 모듈이 소유하는 리터럴뿐이므로 SQL 주입 경로가 없다.
    """
    values = ", ".join(f"'{basis}'" for basis in sorted(TRUSTED_LINK_BASES))
    return f"{column} IN ({values})"
