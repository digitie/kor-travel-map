"""``AdminEvidence`` — 행정구역 판정의 두 축을 **병합 전에** 보존한다 (T-VN-H28B).

문제
----
provider 변환기는 provider payload의 행정코드와 좌표 reverse 결과를 하나의 ``Address``로
병합한다. 병합 규칙이 payload 우선이라 ``Address``만 보면 어떤 값이 어느 출처인지 알 수 없고,
검증 단계에는 "좌표가 주장 주소와 같은 행정구역인가"를 물을 축이 남지 않는다.

실측(``docs/reports/concierge-address-mismatch-evidence-2026-07-29.md``)에서 이 정보 손실의
대가가 확인됐다 — 남은 유일한 "독립" 쌍인 *geo 유도 이름 ↔ provider 주소 문자열*로 판정한
결과 drop 380건이 **전부 오탐**이었고 진짜 불일치는 0건이었다. 권위 있는 코드 축은 같은
객체 안에 있었는데도 쓰이지 못했다.

계약
----
- ``obs_code``는 **오직** 좌표 reverse 결과의 법정동코드다. payload 값으로 덮어쓰기 **전**
  값이어야 한다. 좌표가 없거나 reverse가 실패하면 ``None``.
- ``claim_code``는 **provider payload가 스스로 선언한** 법정동 계열 코드다. provider 고유
  코드(VisitKorea ``areaCode``, MOIS ``opn_authority_code`` 등)는 여기 넣지 않는다 —
  법정동 체계가 아니라서 접두 비교가 성립하지 않는다.
- 둘 중 하나라도 없으면 교차검증은 **성립하지 않는다**. 그 경우 "통과"가 아니라
  "증거 없음"으로 다뤄야 한다(``evidence_grade``).

이 DTO를 채우지 않은 provider는 ``None``으로 남고, 검증은 그 provider에 대해 침묵한다.
침묵을 통과로 착각하지 않도록 커버리지는 metadata에 별도로 집계된다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["AdminEvidence", "AdminClaimKind", "EvidenceGrade"]

AdminClaimKind = Literal["bjd", "emd", "sigungu", "sido"]
"""``claim_code``의 정밀도. 접두 비교 자리수를 정한다 (bjd 10 / emd 8 / sigungu 5 / sido 2)."""

EvidenceGrade = Literal["dual", "claim_only", "obs_only", "none"]
"""교차검증 가능성 등급. ``dual``만 코드 대 코드 판정이 가능하다."""


class AdminEvidence(BaseModel):
    """행정구역 판정용 원시 증거 2축 (병합 전 보존)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    obs_code: str | None = Field(
        default=None,
        description=(
            "좌표 reverse가 낸 법정동코드 10자리. payload 코드로 덮어쓰기 전 값이어야 한다."
        ),
    )
    claim_code: str | None = Field(
        default=None,
        description="provider payload가 선언한 법정동 계열 코드 (provider 고유 코드 금지).",
    )
    claim_kind: AdminClaimKind | None = Field(
        default=None,
        description="``claim_code``의 정밀도. 접두 비교 자리수를 정한다.",
    )

    @property
    def grade(self) -> EvidenceGrade:
        """교차검증 가능성. ``dual``일 때만 코드 대 코드 판정이 성립한다."""
        if self.obs_code and self.claim_code:
            return "dual"
        if self.claim_code:
            return "claim_only"
        if self.obs_code:
            return "obs_only"
        return "none"
