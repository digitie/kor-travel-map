"""``krtour.map.core.types`` — KST aware datetime helper re-export.

본 모듈은 ``krtour.map.dto._time``의 ``KST`` / ``kst_now``를 그대로 re-export
한다. 정의는 ``dto/_time.py``에 있다 (의존 방향 보존: ``dto → core → infra``,
core는 dto를 import 가능하나 그 반대는 import-linter 위반 — ADR-002).

호출 측은 본 모듈 또는 ``krtour.map.core`` package re-export를 통해 사용:

    from krtour.map.core import KST, kst_now

ADR 참조
--------
- ADR-002 — 의존 방향 (dto → core → infra → providers → client → cli).
- ADR-019 — 모든 datetime은 KST aware.

PR#22에서 import-linter 활성화 시 ``dto/feature.py`` → ``core.kst_now``
역행 import를 감지 → 정의를 ``dto/_time.py``로 이전. 본 모듈은 호환성 shim.
"""

from __future__ import annotations

from krtour.map.dto._time import KST, kst_now

__all__ = ["KST", "kst_now"]
