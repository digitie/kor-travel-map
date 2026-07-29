"""``AdminEvidence`` — 행정구역 판정의 원시 증거를 **병합 전에** 보존한다 (T-VN-H28B).

두 축은 성격이 전혀 다르다. 섞으면 안 된다.

독립 축 — ``claim_text`` ↔ ``obs_sigungu_names``
------------------------------------------------
provider가 **사람이 쓴 주소 문자열**로 주장하는 위치와, 좌표를 역지오코딩해 얻은 행정구역
이름. 두 값의 출처가 진짜로 다르므로 "좌표가 주소와 다른 곳을 가리키는가"를 물을 수 있는
**유일한** 축이다.

staleness 축 — ``claim_code`` ↔ ``obs_code``
---------------------------------------------
provider payload가 실어 보낸 행정코드와 지금 역지오코딩한 행정코드. **이것은 위치 검증이
아니다.** 최소 kor-travel-concierge에서는 payload 코드 자체가 같은 kor-travel-geo
``POST /v2/reverse``를 같은 좌표로 호출해 만들어 캐시한 값이다
(``kor-travel-concierge`` ``backend/ktc/etl/admin_region_service.py`` ``fetch_admin_region``).
같은 함수를 같은 입력으로 두 번 부른 셈이라 일치는 당연하고, 불일치는 위치 오류가 아니라
**producer가 캐시한 코드가 낡았다**는 뜻이다(해당 producer는 코드가 이미 있으면 갱신하지
않는다). 그래서 이 축은 staleness 검출로만 쓰고, 위치 판정 근거로 쓰지 않는다.

이 구분을 문서에 박아 두는 이유
--------------------------------
T-VN-H28B 1차 구현은 staleness 축을 "권위 있는 교차검증"으로 오인해 독립 축을 삭제했다.
적대 리뷰가 그것이 자기 자신과의 비교임을 밝혀 폐기했다. 같은 실수를 반복하지 않도록
계약을 여기에 명시한다.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["AdminEvidence", "AdminClaimKind", "EvidenceGrade"]

AdminClaimKind = Literal["bjd", "emd", "sigungu", "sido"]
"""``claim_code``의 정밀도. 접두 비교 자리수를 정한다 (bjd 10 / emd 8 / sigungu 5 / sido 2)."""

EvidenceGrade = Literal["dual", "claim_only", "obs_only", "none", "unarmed"]
"""증거 등급.

- ``dual`` — staleness 대조 가능(양쪽 코드 존재)
- ``claim_only`` / ``obs_only`` / ``none`` — 대조 불가
- ``unarmed`` — provider가 ``AdminEvidence``를 아예 채우지 않음

``unarmed``는 bundle에 ``admin_evidence``가 없을 때 집계 쪽에서 쓰는 값이라 이 모델의
``grade``는 반환하지 않지만, 소비자가 표현할 수 있어야 하므로 Literal에 포함한다.
"""

_CLAIM_LENGTH: dict[str, int] = {"bjd": 10, "emd": 8, "sigungu": 5, "sido": 2}


class AdminEvidence(BaseModel):
    """행정구역 판정용 원시 증거 (병합 전 보존)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    obs_code: str | None = Field(
        default=None,
        description=(
            "좌표 reverse가 낸 법정동코드 10자리. payload 코드로 덮어쓰기 전 값이어야 한다. "
            "좌표가 없거나 reverse가 실패하면 ``None`` — 이 값이 ``None``인지로 reverse 실패를 "
            "판정한다(payload가 코드를 실어 주면 ``Address.bjd_code``로는 판정할 수 없다)."
        ),
    )
    obs_sigungu_names: tuple[str, ...] = Field(
        default=(),
        description=(
            "좌표 reverse **후보 전체**의 시군구명. 경계 좌표는 인접 시군구가 함께 나오므로, "
            "1순위만 보고 불일치로 몰지 않기 위해 집합으로 보존한다."
        ),
    )
    claim_code: str | None = Field(
        default=None,
        description=(
            "provider payload가 실어 보낸 법정동 계열 코드. **위치 주장이 아니라 캐시된 값**일 "
            "수 있다(모듈 docstring 참조). provider 고유 코드는 넣지 않는다."
        ),
    )
    claim_kind: AdminClaimKind | None = Field(
        default=None, description="``claim_code``의 정밀도."
    )
    reverse_attempted: bool = Field(
        default=False,
        description=(
            "좌표 reverse를 **시도**했는가. ``obs_code``가 비어 있어도 '시도했는데 결과가 "
            "없음'과 'geocoder 자체가 결선되지 않음'은 완전히 다른 상태다 — 전자만 "
            "``reverse_geocode_failed``다."
        ),
    )
    claim_text: str | None = Field(
        default=None,
        description=(
            "provider **원천** 주소 문자열. geo에서 유래한 값을 넣으면 독립성이 사라져 "
            "자기 자신과 비교하게 된다 — 반드시 provider payload의 문자열만 넣는다."
        ),
    )

    @field_validator("obs_code", "claim_code")
    @classmethod
    def _digits_only(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.isdigit() or not 2 <= len(value) <= 10:
            raise ValueError(
                f"행정코드는 2~10자리 숫자여야 함 (provider 고유 코드 금지), got {value!r}."
            )
        return value

    @model_validator(mode="after")
    def _claim_kind_matches_length(self) -> AdminEvidence:
        """``claim_kind``와 ``claim_code`` 길이가 어긋나면 비교 자리수가 조용히 줄어든다."""
        if self.claim_code is None:
            return self
        if self.claim_kind is None:
            raise ValueError("claim_code가 있으면 claim_kind도 있어야 한다.")
        expected = _CLAIM_LENGTH[self.claim_kind]
        if len(self.claim_code) != expected:
            raise ValueError(
                f"claim_kind={self.claim_kind!r}는 {expected}자리를 기대하는데 "
                f"claim_code 길이가 {len(self.claim_code)}이다."
            )
        return self

    @property
    def grade(self) -> EvidenceGrade:
        """**staleness 축**의 대조 가능성. 위치 검증 가능성이 아니다."""
        if self.obs_code and self.claim_code:
            return "dual"
        if self.claim_code:
            return "claim_only"
        if self.obs_code:
            return "obs_only"
        return "none"
