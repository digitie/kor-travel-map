#!/usr/bin/env python3
"""T-VN-41S synthetic snapshot Merkle streaming 메모리/처리량 측정."""

from __future__ import annotations

import argparse
import json
import time
import tracemalloc

from kortravelmap.core.cache_target_stream import (
    SnapshotMerkleAccumulatorV1,
    SnapshotMerkleRowV1,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--items",
        type=int,
        default=1_000_001,
        help="생성할 정렬 synthetic leaf 수(기본 1,000,001)",
    )
    parser.add_argument(
        "--max-traced-mib",
        type=float,
        default=16.0,
        help="tracemalloc peak 허용 상한 MiB(기본 16)",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.items <= 0:
        raise SystemExit("--items는 양수여야 합니다.")
    if args.max_traced_mib <= 0:
        raise SystemExit("--max-traced-mib는 양수여야 합니다.")

    accumulator = SnapshotMerkleAccumulatorV1()
    fingerprint = "a" * 64
    tracemalloc.start()
    started_at = time.perf_counter()
    for index in range(args.items):
        accumulator.add(
            SnapshotMerkleRowV1(
                external_system="tvn41s-benchmark",
                target_key=f"target-{index:09d}",
                state="active",
                source_generation=1,
                source_payload_fingerprint=fingerprint,
            )
        )
    elapsed_seconds = time.perf_counter() - started_at
    _current_bytes, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_mib = peak_bytes / (1024 * 1024)
    result = {
        "elapsed_seconds": elapsed_seconds,
        "items": accumulator.count,
        "items_per_second": accumulator.count / elapsed_seconds,
        "material_bytes": accumulator.material_bytes,
        "merkle_root": accumulator.hexdigest(),
        "traced_peak_mib": peak_mib,
    }
    print(json.dumps(result, sort_keys=True))
    if peak_mib > args.max_traced_mib:
        print(
            "FAIL: traced peak가 허용 상한을 초과했습니다: "
            f"{peak_mib:.3f} > {args.max_traced_mib:.3f} MiB"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
