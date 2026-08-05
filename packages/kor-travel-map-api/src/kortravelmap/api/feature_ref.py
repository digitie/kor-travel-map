"""``kortravelmap.api.feature_ref`` — feature 경로 참조의 경계 해석 (T-VN-32B).

ADR-068 결정 3: alias lookup은 경계 전용이다. 모든 ``/{feature_id}`` 경로
handler는 본 모듈의 :func:`resolve_feature_ref_or_error` 를 **첫 줄**에서
호출해 legacy ``f_*`` alias·canonical UUID 양쪽 참조를 정본 키 쌍으로 해석하고,
이후 내부 조회·조인은 해석된 키로만 한다. 라우터마다 해석 로직을 재구현하지
않는다(단일 경계 메커니즘).

- 형식 오류(빈 문자열/공백 패딩/길이 초과) → HTTP 422
- 어느 쪽으로도 해석 불가 → HTTP 404 (원본 참조 문자열을 메시지에 되돌려준다)
- 해석 성공은 ``feature.features`` 행 존재를 함의한다(alias FK/정본 조회) —
  handler가 별도의 존재 확인 쿼리를 반복할 필요가 없다.

auth 의존성보다 뒤(handler 본문)에서 실행되므로 인증 실패 경로에서 DB 해석이
선행되지 않는다(FastAPI 의존성 평가 순서에 의존하지 않는 설계).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import HTTPException, status
from kortravelmap.infra import feature_identity

if TYPE_CHECKING:
    from collections.abc import Sequence

    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["resolve_feature_ref_or_error", "resolve_write_feature_refs_or_error"]


async def resolve_feature_ref_or_error(
    session: AsyncSession,
    ref: str,
) -> feature_identity.FeatureIdentity:
    """경로 참조를 정본 키 쌍으로 해석 — 실패는 HTTP 오류로 변환한다."""
    try:
        identity = await feature_identity.resolve_feature_identity(session, ref)
    except feature_identity.FeatureIdentityRefError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    if identity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"feature 없음: {ref!r}",
        )
    return identity


async def resolve_write_feature_refs_or_error(
    session: AsyncSession,
    refs: Sequence[str],
    *,
    field_name: str = "feature_ids",
) -> dict[str, feature_identity.FeatureIdentity]:
    """write/scope 입력 참조 목록을 정본 키 쌍으로 일괄 해석한다 (T-VN-32C PR-2).

    read 응답 ``feature_id`` 값이 UUID로 전환되면 클라이언트가 그 값을 write
    body로 되돌린다 — 여기서 legacy 정본 키로 해석하지 않으면 UUID 문자열이
    legacy FK 컬럼에 조용히 오염된다(적대 리뷰/조사 4 §보강 R4). write 표면은
    **미해석 참조를 거부**하는 것이 안전 기본값이다:

    - 형식 오류 → 422 (단건 경계와 동일 계약)
    - 해석 불가 참조 존재 → 422 + 문제 참조 목록 (fail-close)

    무시-허용 표면(예: 관측성 스코프)은 호출 대신
    :func:`kortravelmap.infra.feature_identity.resolve_feature_identities_bulk`
    를 직접 쓰고 miss를 자체 계약으로 처리한다.
    """
    try:
        resolved = await feature_identity.resolve_feature_identities_bulk(session, refs)
    except feature_identity.FeatureIdentityRefError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        ) from exc
    unresolved = [ref for ref in refs if ref not in resolved]
    if unresolved:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "FEATURE_REF_UNRESOLVED",
                "message": f"{field_name}에 해석할 수 없는 feature 참조가 있습니다.",
                "details": {"unresolved": unresolved[:20]},
            },
        )
    return resolved
