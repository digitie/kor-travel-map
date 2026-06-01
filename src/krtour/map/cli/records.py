"""``krtour.map.cli.records`` — CLI ``import`` 명령용 NDJSON 레코드 소스.

ADR-006상 본 라이브러리는 provider(``python-mois-api`` 등)를 **런타임 import하지
않는다**. 따라서 ``krtour-map import``는 provider 라이브러리가 외부에서 export한
**provider-neutral NDJSON 파일**(한 줄당 JSON object 1건)을 읽어 structural record로
주입한다 — provider model이 아니라 dict → Protocol 만족 래퍼.

NDJSON 계약
-----------
각 줄은 ``MoisLicensePlaceRecord`` Protocol 필드 이름을 key로 갖는 JSON object다
(``providers.mois.MoisLicensePlaceRecord`` 참조). 누락 key는 ``None``으로 취급한다.
JSON에 date 타입이 없으므로 ``license_date``/``designation_date``는 ISO 문자열
(``YYYY-MM-DD`` 또는 ``YYYY-MM-DDThh:mm:ss``)로 직렬화돼 있다고 가정하고 ``date``로
파싱한다. 좌표/카운트/면적은 JSON number, ``is_open``은 JSON bool 그대로 쓴다.

ADR 참조
--------
- ADR-002 — async-only(상위 CLI). 본 모듈 자체는 동기 파일 I/O(streaming 한 줄씩).
- ADR-006 — provider 라이브러리 미import. 파일은 provider-neutral.
"""

from __future__ import annotations

import json
from datetime import date
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

__all__ = ["MoisLicenseJsonRecord", "iter_mois_license_records"]

# JSON엔 date 타입이 없어 ISO 문자열로 직렬화된 필드만 ``date``로 역파싱한다.
_DATE_FIELDS: Final[frozenset[str]] = frozenset(
    {"license_date", "designation_date"}
)


class MoisLicenseJsonRecord:
    """NDJSON 한 줄(dict) → ``MoisLicensePlaceRecord`` Protocol 만족 래퍼.

    Protocol 필드는 ``@property``로 선언돼 있으나 structural typing이므로 동명
    attribute(여기선 ``__getattr__`` 동적 제공)로 충족된다. 누락 key는 ``None``,
    date 필드는 ISO 문자열 → ``date``로 변환한다.
    """

    __slots__ = ("_data",)

    def __init__(self, data: Mapping[str, Any]) -> None:
        self._data = data

    def __getattr__(self, name: str) -> Any:
        # ``__getattr__``은 일반 lookup 실패 시에만 호출된다(``_data``는 slot이라
        # 여기 안 옴). 내부/dunder 이름은 AttributeError로 — 재귀/오작동 방지.
        if name.startswith("_"):
            raise AttributeError(name)
        value = self._data.get(name)
        if value is not None and name in _DATE_FIELDS:
            return _parse_iso_date(value)
        return value

    def __repr__(self) -> str:
        mng = self._data.get("mng_no")
        slug = self._data.get("service_slug")
        return f"MoisLicenseJsonRecord(service_slug={slug!r}, mng_no={mng!r})"


def _parse_iso_date(value: Any) -> date | None:
    """ISO 문자열(``YYYY-MM-DD`` 또는 datetime) → ``date``. 실패 시 ``None``."""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return date.fromisoformat(text[:10])
        except ValueError:
            return None
    return None


def iter_mois_license_records(path: Path) -> Iterator[MoisLicenseJsonRecord]:
    """NDJSON 파일을 lazy하게 한 줄씩 ``MoisLicenseJsonRecord``로 yield한다.

    대용량 snapshot을 메모리 바운드로 처리하기 위해 streaming(한 줄씩)으로 읽는다 —
    ``sync_mois_license_features_bulk``의 ``_batched``가 다시 배치로 끊는다. 빈 줄은
    건너뛴다. JSON 파싱 실패 시 줄 번호를 포함한 ``ValueError``를 던진다.

    Parameters
    ----------
    path
        NDJSON 파일 경로(UTF-8, BOM 허용). 한 줄당 JSON object 1건.

    Yields
    ------
    MoisLicenseJsonRecord
        ``MoisLicensePlaceRecord`` Protocol을 만족하는 래퍼.
    """
    with path.open("r", encoding="utf-8-sig") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"{path}:{line_no}: NDJSON 파싱 실패 — {exc}"
                ) from exc
            if not isinstance(data, dict):
                raise ValueError(
                    f"{path}:{line_no}: 각 줄은 JSON object여야 함 "
                    f"(got {type(data).__name__})."
                )
            yield MoisLicenseJsonRecord(data)
