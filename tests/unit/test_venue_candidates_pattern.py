"""장소 이름 조각 → ILIKE 패턴(#1468 D)."""

from __future__ import annotations

import pytest

from kortravelmap.infra.venue_candidates_repo import venue_name_pattern


@pytest.mark.parametrize(
    ("name", "pattern"),
    [
        ("진주성", "%진주성%"),
        ("수덕사 근역성보관", "%수덕사%근역성보관%"),
        ("100%_한옥\\마을", "%100\\%\\_한옥\\\\마을%"),
        ("성", None),
        ("(사)", None),
    ],
)
def test_venue_name_pattern(name: str, pattern: str | None) -> None:
    assert venue_name_pattern(name) == pattern
