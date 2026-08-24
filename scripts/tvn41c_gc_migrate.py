"""Retired T-VN-41C migration helper.

It intentionally cannot build a database by executing the retired migration
chain. Use the active fresh-`300` bootstrap for any future measurement design.
"""

from __future__ import annotations

import sys


def main() -> int:
    print(
        "T-VN-41C migration helper is retired: historical Alembic replay is unsupported",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
