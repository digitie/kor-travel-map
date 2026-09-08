"""manual Feature hard purge의 타입 있는 호출부 (T-VN-H49, migration 306).

## 이것은 UI 버튼이 아니다

purge는 **운영 명령**이다. 잘못 만든 것·중복·품질 문제는 `retire`가 담당한다 — 그쪽은
행을 남기고 되돌릴 수 있다. purge는 **행이 존재하면 안 되는 경우**로 한정한다:
법적 삭제 요구, 개인정보, 되돌릴 수 없이 잘못 만들어진 것. UI 버튼으로 열면 `retire`가
맡아야 할 일이 이쪽으로 샌다(소유자 판정 2026-09-08).

그래서 여기에는 라우트가 없다. 호출자는 `admin.manual-feature.purge.v1` command를 연
운영 스크립트이고, 권한은 전용 procedure owner가 갖는다.

## 두 동기가 정반대를 원한다

- `mistaken_creation` — 지운 뒤 **같은 자리에 제대로 다시 만들** 수 있어야 한다. 그래서
  보통 `release_identity=True`로 exact 예약을 놓는다. 그리고 payload를 담는다.
- `erasure_required` — 같은 것이 **다시 만들어지면 안 된다.** 그래서 보통 예약을 쥔다.
  그리고 payload를 담지 **않는다** — 담으면 삭제의 목적이 무너진다.

기본값을 두지 않고 호출자가 의도를 말하게 한다.

## 왜 자기 복구점을 들고 다니나

소유자가 건 순서는 "되돌릴 수 없는 삭제 경로를 restore proof보다 먼저 열 수 없다"였다.
M05-2 C·D단계가 증명한 것은 **복원 메커니즘**이지 복원할 대상이 있다는 것이 아니다 —
`map_application`은 어느 주기 백업에도 없고(T-VN-H43 보류) restore/swap은 300 baseline
정책으로 닫혀 있다. 그래서 purge가 지우기 전에 cascade로 사라질 행을 전부 담는다.
DB 수준 restore가 열리기를 기다리지 않아도 되는 이유가 이것이다.

ADR 참조: ADR-002 async-only · ADR-004 raw SQL ``text()`` · ADR-093
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "ManualFeaturePurgeBlocked",
    "ManualFeaturePurgeNotManual",
    "ManualFeaturePurgeOutcome",
    "ManualFeaturePurgeValidationError",
    "PURGE_OPERATION",
    "purge_manual_feature",
]

#: 프로시저가 command에 요구하는 operation. 값이 갈리면 프로시저가 거부한다.
PURGE_OPERATION: Final[str] = "admin.manual-feature.purge.v1"

_REASON_CODES: Final[frozenset[str]] = frozenset(
    {"mistaken_creation", "erasure_required"}
)


class ManualFeaturePurgeBlocked(ValueError):
    """불변 증거가 이 Feature의 identity를 인용하고 있어 지울 수 없다 — 409.

    `theme_feature_candidates`·`feature_reference_reconciliation_events`·
    `manual_provider_dedup_cases`가 `ON DELETE RESTRICT`로 참조한다. 그 셋이 막는 것은
    **맞다** — purge가 뚫으면 M05 evidence가 dangling이 된다.
    """


class ManualFeaturePurgeNotManual(ValueError):
    """대상이 manual origin이 아니거나 아예 없다 — 404/409."""


class ManualFeaturePurgeValidationError(ValueError):
    """요청 자체가 성립하지 않는다(reason_code·actor·command) — 422."""


@dataclass(frozen=True)
class ManualFeaturePurgeOutcome:
    """purge 영수증.

    `outcome`이 `already_purged`면 이미 처리된 것을 다시 부른 것이다 — 프로시저가
    멱등이므로 오류가 아니다. 그때 담긴 수치는 **원래 purge의 것**이다.
    """

    purge_id: str
    outcome: str
    captured_relation_count: int
    captured_row_count: int

    @property
    def already_purged(self) -> bool:
        return self.outcome == "already_purged"


#: constraint 이름 → 도메인 오류. **분류를 잊는 것이 기본값이면 안 된다** —
#: `_raise_purge_error`가 매핑에 없는 23514를 raw로 다시 던지고,
#: `tests/lint/test_manual_feature_purge_mapping.py`가 프로시저가 raise하는 이름 전부가
#: 여기 있는지 fail-close로 지킨다. 같은 부류의 누락이 admin state 경로에서 두 번
#: catch-all 500을 냈다(2026-08-12, 2026-09-08).
_PURGE_ERROR_BY_CONSTRAINT: Final[dict[str, type[ValueError]]] = {
    "ck_manual_feature_purge_command": ManualFeaturePurgeValidationError,
    "ck_manual_feature_purge_not_manual": ManualFeaturePurgeNotManual,
    "ck_manual_feature_purge_evidence_bound": ManualFeaturePurgeBlocked,
    # fence가 승인 없는 DELETE를 막을 때. 이 경로로는 나오지 않아야 정상이지만,
    # 나오면 그것은 "프로시저 밖에서 지우려 했다"는 뜻이라 conflict가 맞다.
    "ck_manual_feature_purge_unauthorised": ManualFeaturePurgeBlocked,
}

_CALL_PURGE: Final[str] = """
CALL feature.purge_manual_feature(
  CAST(:feature_uuid AS uuid), CAST(:reason_code AS text),
  CAST(:release_identity AS boolean), CAST(:actor AS text),
  CAST(:command_id AS bigint),
  NULL::uuid, NULL::text, NULL::integer, NULL::integer
)
"""


def _constraint_name(error: DBAPIError) -> str | None:
    """asyncpg는 constraint 이름을 ``orig``가 아니라 그 ``__cause__``에 둔다.

    ``orig``만 보면 이름이 **항상 None**이라 매핑 전체가 죽은 코드가 된다 — 이 저장소가
    2026-08-12에 정확히 그렇게 겪었다.
    """

    candidate: BaseException | None = error.orig
    while candidate is not None:
        name = getattr(candidate, "constraint_name", None)
        if isinstance(name, str) and name:
            return name
        candidate = candidate.__cause__
    return None


def _raise_purge_error(error: DBAPIError) -> None:
    """DB contract를 도메인 오류로 보존한다. 모르는 것은 **그대로 던진다.**"""

    sqlstate = getattr(error.orig, "sqlstate", None)
    if sqlstate not in {"23514", "42501"}:
        raise error
    mapped = _PURGE_ERROR_BY_CONSTRAINT.get(_constraint_name(error) or "")
    if mapped is None:
        raise error
    raise mapped(str(error.orig)) from error


async def purge_manual_feature(
    session: AsyncSession,
    *,
    feature_uuid: str,
    reason_code: str,
    release_identity: bool,
    actor: str,
    command_id: int,
) -> ManualFeaturePurgeOutcome:
    """manual Feature를 감사되는 명령으로 지운다.

    `release_identity`에 기본값을 두지 않는다 — 두 동기가 정반대를 원하므로 호출자가
    의도를 말해야 한다(모듈 docstring 참조).
    """

    if reason_code not in _REASON_CODES:
        raise ManualFeaturePurgeValidationError(
            f"reason_code는 {sorted(_REASON_CODES)} 중 하나여야 한다: {reason_code!r}"
        )
    if not actor.strip():
        raise ManualFeaturePurgeValidationError("purge에는 authenticated actor가 필요하다")

    try:
        row = (
            await session.execute(
                text(_CALL_PURGE),
                {
                    "feature_uuid": feature_uuid,
                    "reason_code": reason_code,
                    "release_identity": release_identity,
                    "actor": actor,
                    "command_id": command_id,
                },
            )
        ).mappings().one()
    except DBAPIError as error:
        _raise_purge_error(error)
        raise

    return ManualFeaturePurgeOutcome(
        purge_id=str(row["o_purge_id"]),
        outcome=str(row["o_outcome"]),
        captured_relation_count=int(row["o_captured_relation_count"]),
        captured_row_count=int(row["o_captured_row_count"]),
    )
