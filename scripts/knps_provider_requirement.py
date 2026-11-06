"""CI와 로컬 게이트가 같은 KNPS geo 핀을 설치하도록 선언 한 개를 출력한다."""

from __future__ import annotations

import tomllib
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    with (root / "pyproject.toml").open("rb") as source:
        project = tomllib.load(source)
    providers = project["project"]["optional-dependencies"]["providers"]
    matches = [
        requirement
        for requirement in providers
        if requirement.startswith("python-knps-api[geo] @ ")
    ]
    if len(matches) != 1:
        raise SystemExit("expected one pinned KNPS geo provider requirement")
    print(matches[0])


if __name__ == "__main__":
    main()
