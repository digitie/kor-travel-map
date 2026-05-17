from __future__ import annotations

from pathlib import Path

import pytest

from krtour_map.fixtures import load_fixture, replay_fixture
from tests.runners import RUNNERS

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def all_fixture_files() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*/*.json"))


@pytest.mark.parametrize(
    "fixture_path",
    all_fixture_files(),
    ids=lambda path: f"{path.parent.name}/{path.stem}",
)
def test_generated_fixtures(fixture_path: Path) -> None:
    replay_fixture(load_fixture(fixture_path), RUNNERS)
