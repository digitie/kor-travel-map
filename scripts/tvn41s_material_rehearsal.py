"""Retired T-VN-41S rehearsal entry point.

The active application graph has only the `300` root. This tombstone prevents
old milestone code from recreating a historical database for a rehearsal.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "T-VN-41S rehearsal runner is retired: historical Alembic replay is unsupported",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
