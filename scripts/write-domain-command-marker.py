#!/usr/bin/env python3
"""Host backup 생성 script용 durable domain command marker writer."""

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
    backup_artifact_output_proof,
    write_domain_command_marker,
)


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--backup-root", type=Path, required=True)
    parser.add_argument("--command-id", type=int, required=True)
    parser.add_argument("--operation", required=True)
    parser.add_argument("--marker-key", required=True)
    parser.add_argument("--effect-kind", choices=("create",), required=True)
    parser.add_argument("--effect-state", required=True)
    parser.add_argument("--backup-id", required=True)
    parser.add_argument("--input-digest", required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)
    proof = backup_artifact_output_proof(args.backup_root, args.backup_id)
    write_domain_command_marker(
        args.backup_root,
        command_id=args.command_id,
        operation=args.operation,
        marker_key=args.marker_key,
        effect_kind=args.effect_kind,
        effect_state=args.effect_state,
        backup_id=args.backup_id,
        input_digest=args.input_digest,
        output_proof=proof,
    )
    return os.EX_OK


if __name__ == "__main__":
    raise SystemExit(main())
