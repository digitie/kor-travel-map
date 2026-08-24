#!/usr/bin/env python3
"""비활성화된 과거 cache-target restore fence 진입점.

`300` 이후에는 검증된 물리 복구·swap 계약이 없다. 이 파일은 과거 host script가
직접 DB에 연결해 복원 대상의 stream을 바꾸던 우회 경로였으므로, 인자·환경·DSN을
해석하기 전에 항상 실패한다.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence


def main(argv: Sequence[str] | None = None) -> int:
    """과거 direct restore DB mutation을 fail-close 한다."""

    del argv
    print(
        "restore cache-target fence is disabled: backup artifacts are audit-only "
        "under the 300 baseline",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
