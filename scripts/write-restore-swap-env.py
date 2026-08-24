#!/usr/bin/env python3
"""Disabled restore hot-swap environment writer.

The active Map graph is the single `300` baseline and no independently verified
recovery protocol exists. Producing a swap env file would make an old restore
path executable outside the root scripts, so this entry point is intentionally
fail-closed.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path


def write_restore_swap_env(project_root: Path) -> Path:
    """Reject all callers before creating or touching a project file."""

    del project_root
    raise RuntimeError(
        "restore swap is disabled: no verified 300-baseline recovery format is available"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        write_restore_swap_env(args.project_root)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    raise AssertionError("disabled restore swap writer unexpectedly returned")


if __name__ == "__main__":
    raise SystemExit(main())
