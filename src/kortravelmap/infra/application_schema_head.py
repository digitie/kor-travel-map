"""application schema head의 단일 정본.

## 왜 필요한가

배포 계약은 "설치된 DB가 **정확히 기대한 revision**인가"를 여러 지점에서 확인한다.
그 자체는 옳은 설계다. 문제는 기대값이 **파일마다 하드코딩된 리터럴**이었다는 것이다 —
한때 `300`이라는 같은 값의 사본이 여섯 벌 있었고, 서로 일치한다는 것을 **아무것도
강제하지 않았다.** 실제로 `301`을 얹자 fresh installer가
`installed active Alembic graph head is not exactly 300`으로 거절했다.

(그 사본을 들고 있던 파일 대부분은 ADR-101에서 삭제됐다. 남은 소비자는 런타임 기동
검사와 Manager의 배포 계약이고, 둘 다 아래의 파생값을 쓴다.)

여기서 head를 **파생값**으로 만든다. 정본은 `_application_migration_graph.json`이고,
그것은 `scripts/generate_application_migration_graph.py`가 `alembic/versions/`에서
생성하며 `--check`와 squash 경계 테스트가 최신성을 강제한다.

## 무엇을 바꾸지 않는가

- **guard의 엄격함**: "정확히 기대한 head"라는 성질은 그대로다. 기대값의 출처만
  리터럴에서 graph로 바뀐다.
- **baseline root**: sidecar가 재현하는 baseline root는 "현재 head"가 아니라
  graph의 좌표다. ``BASELINE_ROOT_REVISION``으로 이름을 따로 준다 — 지금은 그 둘이
  같은 값이지만(revision이 하나뿐이므로), 뜻이 다르므로 이름도 다르게 둔다.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Final

_GRAPH_PATH: Final = Path(__file__).resolve().parent.parent / "_application_migration_graph.json"

BASELINE_ROOT_REVISION: Final = "400"
"""active graph의 유일한 root.

`300`~`313` 열네 개를 접은 단일 baseline이다. migration이 더 쌓여도 이 값은 바뀌지
않는다 — root는 하나이고 그것이 `400`이다.
"""


class ApplicationSchemaHeadError(RuntimeError):
    """head를 확정할 수 없다 — 조용히 추측하지 않는다."""


@lru_cache(maxsize=1)
def application_schema_head() -> str:
    """active migration graph의 **유일한** head revision.

    head가 0개이거나 2개 이상이면 배포 기대값을 정의할 수 없으므로 실패한다. 분기된
    graph에서 "아무 head나" 고르면 설치본과 attestation이 어긋난 채 통과할 수 있다.
    """
    try:
        payload = json.loads(_GRAPH_PATH.read_text(encoding="utf-8"))
    except OSError as exc:  # pragma: no cover - 배포 이미지 손상
        raise ApplicationSchemaHeadError(
            f"application migration graph를 읽을 수 없다: {_GRAPH_PATH}"
        ) from exc

    revisions = payload.get("revisions")
    if not isinstance(revisions, list) or not revisions:
        raise ApplicationSchemaHeadError("application migration graph에 revision이 없다")

    declared = {str(entry["revision"]) for entry in revisions}
    referenced = {
        str(parent)
        for entry in revisions
        for parent in entry.get("down_revision") or ()
    }
    heads = sorted(declared - referenced)
    if len(heads) != 1:
        raise ApplicationSchemaHeadError(
            f"active migration graph는 단일 head여야 한다: {heads}"
        )

    roots = sorted(
        str(entry["revision"]) for entry in revisions if not entry.get("down_revision")
    )
    if roots != [BASELINE_ROOT_REVISION]:
        raise ApplicationSchemaHeadError(
            f"active migration graph의 root는 {BASELINE_ROOT_REVISION} 하나여야 한다: {roots}"
        )
    return heads[0]
