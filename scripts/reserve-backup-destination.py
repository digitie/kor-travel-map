#!/usr/bin/env python3
"""Backup command destination을 durable command identity에 예약한다."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from kortravelmap.infra.domain_command_marker import (  # noqa: E402
    reserve_backup_destination,
)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--command-id", type=int, required=True)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--input-digest", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    reserve_backup_destination(
        args.backup_root,
        command_id=args.command_id,
        backup_id=args.backup_id,
        input_digest=args.input_digest,
    )
    return os.EX_OK


if __name__ == "__main__":
    raise SystemExit(main())
