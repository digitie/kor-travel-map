"""application schema head의 단일 정본.

## 왜 필요한가

배포 계약은 "설치된 DB가 **정확히 기대한 revision**인가"를 여러 지점에서 확인한다 —
static contract, fresh installer, finalize, final permit. 그 자체는 옳은 설계다.
문제는 기대값이 **파일마다 하드코딩된 리터럴**이었다는 것이다.

    docker/application-schema-contract.py       _HEAD = "300"
    docker/application-schema-fresh-300.py      _DESTINATION_HEAD = "300"
    docker/application-schema-fresh-finalize.py _DESTINATION_HEAD = "300"
    docker/application-schema-final-permit.py   versions != ("300",)  등 3곳

같은 값의 사본 여섯이 서로 일치한다는 것을 **아무것도 강제하지 않았고**, migration을
하나 더하려면 여섯 곳을 한꺼번에 고쳐야 했다. 실제로 `301`을 얹자 fresh installer가
`installed active Alembic graph head is not exactly 300`으로 거절했다.

여기서 head를 **파생값**으로 만든다. 정본은 `_application_migration_graph.json`이고,
그것은 `scripts/generate_application_migration_graph.py`가 `alembic/versions/`에서
생성하며 `--check`와 squash 경계 테스트가 최신성을 강제한다.

## 무엇을 바꾸지 않는가

- **guard의 엄격함**: "정확히 기대한 head"라는 성질은 그대로다. 기대값의 출처만
  리터럴에서 graph로 바뀐다.
- **baseline root `300`**: `0236 → 300` handoff의 목적지와 sidecar가 재현하는 baseline은
  영원히 `300`이다. 그것은 "현재 head"가 아니라 역사적 좌표이므로 여기서 다루지 않는다.
  ``BASELINE_ROOT_REVISION``으로 이름을 따로 준다.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Final

_GRAPH_PATH: Final = Path(__file__).resolve().parent.parent / "_application_migration_graph.json"

BASELINE_ROOT_REVISION: Final = "300"
"""active graph의 유일한 root.

`0200`~`0236`을 대체한 단일 baseline이며 `0236 → 300` handoff의 stamp 목적지다.
migration이 더 쌓여도 이 값은 바뀌지 않는다 — root는 하나이고 그것이 `300`이다.
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
