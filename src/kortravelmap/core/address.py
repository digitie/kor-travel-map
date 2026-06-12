"""``kortravelmap.core.address`` — 한국 주소/행정코드 정규화 + 파싱 helper.

ADR-041 (2026-05-27) — `python-kraddr-base` 흡수 결과. kraddr-base의
주소/도메인 utility 중 본 라이브러리에서 사용하는 함수만 가져옴. ``Place
Coordinate``는 명시적 제외 (ADR-041 — 좌표 DTO는 `kortravelmap.dto.coordinate
.Coordinate` 단일 source).

본 모듈은 dto만 import (ADR-001 의존 방향). 외부 의존 X — stdlib + re만.

함수 매핑 (kraddr-base 원본 → 본 lib)
------------------------------------
| kraddr-base                     | 본 lib                                |
|---------------------------------|---------------------------------------|
| `Address`                       | `kortravelmap.dto.Address` (보강됨)    |
| `LegalAddress` / `RoadAddress`  | `Address` 한 모델로 통합 (필드 분리) |
| `AddressRegion`                 | `Address.sido_name`/`sigungu_name` 등 |
| `normalize_bjd_code(s)`         | `normalize_bjd_code`                  |
| `parse_bjd_code(s)`             | `parse_bjd_code` → `BjdParts`         |
| `is_valid_bjd_code(s)`          | `is_valid_bjd_code`                   |
| `extract_sigungu(s)`            | `extract_sigungu_code`                |
| `extract_sido(s)`               | `extract_sido_code`                   |
| `clean_phone_number(s)`         | `normalize_phone_number`              |
| `normalize_korean_text(s)`      | `normalize_korean_text`               |
| `PlaceCoordinate`               | **제외** (ADR-041)                    |
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final, NamedTuple

__all__ = [
    "BjdParts",
    "normalize_bjd_code",
    "parse_bjd_code",
    "is_valid_bjd_code",
    "extract_sigungu_code",
    "extract_sido_code",
    "normalize_phone_number",
    "normalize_korean_text",
]


# ── 법정동 코드 — 10자리 숫자 (시도2 + 시군구3 + 읍면동3 + 리2) ──────────

_BJD_DIGIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{10}$")


class BjdParts(NamedTuple):
    """``parse_bjd_code``의 반환 — 시도/시군구/읍면동/리로 분해된 4-tuple.

    예: ``"1156010100"`` → ``BjdParts(sido='11', sigungu='560', eupmyeondong=
    '101', ri='00')``.

    조합 helper:
    - ``sido_code()``: 2자리.
    - ``sigungu_code()``: 5자리(시도2 + 시군구3).
    - ``eupmyeondong_code()``: 8자리.
    """

    sido: str
    """시·도 코드 (2자리). 예: '11' = 서울특별시."""

    sigungu: str
    """시·군·구 코드 (3자리, 시도 내 식별). sigungu_code 5자리의 후반부."""

    eupmyeondong: str
    """읍·면·동 코드 (3자리)."""

    ri: str
    """리 코드 (2자리). 동 단위만 있는 도시 지역은 '00'."""

    def sido_code(self) -> str:
        return self.sido

    def sigungu_code(self) -> str:
        return self.sido + self.sigungu

    def eupmyeondong_code(self) -> str:
        return self.sido + self.sigungu + self.eupmyeondong

    def to_bjd_code(self) -> str:
        return self.sido + self.sigungu + self.eupmyeondong + self.ri


def normalize_bjd_code(value: str | int | None) -> str | None:
    """법정동 코드 정규화.

    - ``None``/빈 문자열 → ``None``.
    - ``int`` 입력 → 10자리 zero-pad string.
    - 좌우 공백 + 내부 비숫자 문자 제거 (provider raw에서 흔한 dash/dot 흡수).
    - 9자리 입력 (구 일부 provider) → 앞에 0 padding으로 10자리.
    - 그래도 10자리 숫자 아닌 경우 ``ValueError``.

    Parameters
    ----------
    value
        provider raw 법정동 코드. ``str`` / ``int`` / ``None``.

    Returns
    -------
    str | None
        10자리 숫자 또는 ``None``.

    Raises
    ------
    ValueError
        normalize 후에도 10자리 숫자가 안 되는 경우.

    Examples
    --------
    >>> normalize_bjd_code("1156010100")
    '1156010100'
    >>> normalize_bjd_code(" 11-560-101-00 ")
    '1156010100'
    >>> normalize_bjd_code(1156010100)
    '1156010100'
    >>> normalize_bjd_code("156010100")  # 9자리 → 0 padding
    '0156010100'
    >>> normalize_bjd_code(None)
    >>> normalize_bjd_code("")
    """
    if value is None:
        return None
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"법정동 코드는 음수일 수 없음, got {value!r}.")
        candidate = f"{value:010d}"
    else:
        # str: 좌우 공백 제거 + 모든 비숫자 제거 (dash/dot/space 흡수).
        candidate = re.sub(r"\D", "", str(value).strip())
    if not candidate:
        return None
    # 9자리 → 0 padding (구 행안부 표 일부).
    if len(candidate) == 9:
        candidate = "0" + candidate
    if not _BJD_DIGIT_PATTERN.match(candidate):
        raise ValueError(
            f"법정동 코드는 10자리 숫자여야 함, normalize 결과 {candidate!r} (입력 {value!r})."
        )
    return candidate


def is_valid_bjd_code(value: str | None) -> bool:
    """``normalize_bjd_code``로 정규화 가능 + 10자리 숫자면 True (raise 없음)."""
    if value is None:
        return False
    try:
        return normalize_bjd_code(value) is not None
    except ValueError:
        return False


def parse_bjd_code(value: str | int) -> BjdParts:
    """법정동 코드를 4-tuple로 분해 (``BjdParts``).

    내부적으로 ``normalize_bjd_code``를 호출해 정규화 후 분해.
    """
    normalized = normalize_bjd_code(value)
    if normalized is None:
        raise ValueError(f"빈 법정동 코드 — parse 불가, 입력 {value!r}.")
    return BjdParts(
        sido=normalized[:2],
        sigungu=normalized[2:5],
        eupmyeondong=normalized[5:8],
        ri=normalized[8:10],
    )


def extract_sigungu_code(bjd_code: str | int | None) -> str | None:
    """법정동 코드에서 시·군·구 코드 5자리 추출. ``None`` 가능."""
    normalized = normalize_bjd_code(bjd_code)
    if normalized is None:
        return None
    return normalized[:5]


def extract_sido_code(bjd_code: str | int | None) -> str | None:
    """법정동 코드에서 시·도 코드 2자리 추출. ``None`` 가능."""
    normalized = normalize_bjd_code(bjd_code)
    if normalized is None:
        return None
    return normalized[:2]


# ── 전화번호 정규화 ────────────────────────────────────────────────────────

_PHONE_DIGIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"\D")
"""숫자가 아닌 모든 문자."""


def normalize_phone_number(value: str | None) -> str | None:
    """한국 전화번호 표준 표기로 정규화.

    - 숫자만 추출 후 자릿수에 따라 dash 삽입.
    - 9자리(02 지역 7자리) — `02-XXX-XXXX`
    - 10자리(02 지역 8자리 / 지역번호 3자리 + 가입자 7자리) —
      `02-XXXX-XXXX` 또는 `0XX-XXX-XXXX`
    - 11자리(휴대폰 010 / 지역 4-4 등) — `0XX-XXXX-XXXX`
    - 위 범위 아니면 normalize 불가 → 원본 좌우 공백 제거 후 그대로 반환.

    Parameters
    ----------
    value
        provider raw 전화번호. ``None`` / 빈 문자열은 ``None``.

    Returns
    -------
    str | None
        dash 포함 표기 (예: '02-2670-3114') 또는 ``None``.

    Examples
    --------
    >>> normalize_phone_number("02-2670-3114")
    '02-2670-3114'
    >>> normalize_phone_number("0226703114")
    '02-2670-3114'
    >>> normalize_phone_number("01012345678")
    '010-1234-5678'
    >>> normalize_phone_number(None)
    >>> normalize_phone_number("")
    >>> normalize_phone_number("internal-ext-203")
    'internal-ext-203'
    """
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    digits = _PHONE_DIGIT_PATTERN.sub("", stripped)
    if not digits:
        return stripped  # 숫자 1개도 없으면 normalize 불가 — 원본 반환.

    # 02 지역 (서울) — 9자리 또는 10자리.
    if digits.startswith("02"):
        if len(digits) == 9:
            return f"02-{digits[2:5]}-{digits[5:]}"
        if len(digits) == 10:
            return f"02-{digits[2:6]}-{digits[6:]}"

    # 휴대폰 / 일반 지역번호 — 10자리(3-3-4) 또는 11자리(3-4-4).
    if len(digits) == 10:
        return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"
    if len(digits) == 11:
        return f"{digits[:3]}-{digits[3:7]}-{digits[7:]}"

    # 그 외 — normalize 패턴 없음. 원본 좌우 공백만 제거.
    return stripped


# ── 한국어 텍스트 정규화 ────────────────────────────────────────────────

_MULTI_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")


def normalize_korean_text(value: str | None) -> str | None:
    """한국어 텍스트 NFKC + 좌우 공백 제거 + 다중 공백 1개로 축약.

    provider raw에서 흔한 전각 공백 / 다중 공백 / NFC vs NFD 불일치를 흡수.
    검색/dedup 정합성을 위해 ``Feature.name`` / `Address.road` 등 적재 직전
    사용.

    Parameters
    ----------
    value
        raw 한국어 텍스트. ``None`` / 빈 문자열은 ``None``.

    Returns
    -------
    str | None
        정규화된 문자열 또는 ``None`` (빈 결과 시).

    Examples
    --------
    >>> normalize_korean_text("  서울   특별시  ")
    '서울 특별시'
    >>> normalize_korean_text("서울　특별시")  # 전각 공백
    '서울 특별시'
    >>> normalize_korean_text(None)
    >>> normalize_korean_text("   ")
    """
    if value is None:
        return None
    result = unicodedata.normalize("NFKC", value).strip()
    if not result:
        return None
    return _MULTI_WHITESPACE.sub(" ", result)
