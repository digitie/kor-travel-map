"""Retired T-VN-41S soak entry point.

The retired `0200`–`0236` Alembic graph must never be replayed to construct a
measurement database. Historical reports remain in ``docs/reports``; this
former executable is deliberately a fail-closed tombstone.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "T-VN-41S soak runner is retired: historical Alembic replay is unsupported",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
