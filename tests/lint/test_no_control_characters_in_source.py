"""소스에 제어문자가 섞여 들어오는 것을 막는다.

이 저장소에서 두 번 물렸다. 스크립트로 파일을 고칠 때 heredoc 안의 ``\\b``가
**literal backspace(0x08)** 로 들어가 정규식이 조용히 무력화됐다. 두 번 다 증상은
같았다 — 코드를 읽으면 맞는데 실행하면 매치가 되지 않고, 테스트는 green이라
"가드가 통과했다"로 보인다. 2026-08-12에는 legacy state 차단선의 파일 자동 발견이,
2026-08-13에는 같은 차단선의 보간-alias 규칙이 그렇게 죽어 있었다.

ruff/mypy는 이것을 잡지 못한다 — 문법상으로는 그냥 문자열 안의 한 글자다.
그래서 여기서 바이트로 본다.

탭과 개행은 정상 문자다. 그 외 C0 제어문자와 zero-width/BOM류는 소스에 있을 이유가
없다(문자열 리터럴로 필요하면 ``\\x08`` 같은 escape로 적으면 된다 — escape는
ASCII 문자 4개라 이 검사에 걸리지 않는다).
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCANNED_ROOTS = (
    _ROOT / "src",
    _ROOT / "tests",
    _ROOT / "packages/kor-travel-map-api/src",
    _ROOT / "packages/kor-travel-map-api/tests",
    _ROOT / "packages/kor-travel-map-dagster/src",
    _ROOT / "packages/kor-travel-map-dagster/tests",
    _ROOT / "alembic",
    _ROOT / "scripts",
)
_ALLOWED = frozenset({chr(0x09), chr(0x0A), chr(0x0D)})
# 대상은 **C0 제어문자 + DEL**이다. 이것들은 소스에 있을 이유가 없고, 있으면
# 정규식이나 SQL을 조용히 바꾼다. zero-width/BOM류는 넣지 않는다 — provider 텍스트
# 정규화 코드가 그것을 정당하게 다루고(예: `providers/krheritage.py` 주석),
# 이 저장소가 실제로 물린 부류도 아니다.
#
# 목록을 리터럴이 아니라 `chr()`로 적는 이유는 **이 파일 자신이 검사 대상**이기
# 때문이다. 금지 문자를 그대로 적어 두면 가드가 자기 자신을 위반으로 잡는다.
_FORBIDDEN = frozenset(
    [chr(code) for code in range(0x20) if chr(code) not in _ALLOWED] + [chr(0x7F)]
)


#: `.py`만 훑으면 **모든 fresh DB에서 실행되는 SQL**이 가드 밖에 남는다.
#: `alembic/baseline/*.sql`은 생성기의 heredoc 산출물이고, 이 저장소가 이 가드를 만든
#: 이유(heredoc `\b`가 literal 0x08이 된 사고, 2026-08-12·08-13 2회)와 같은 생산 경로다.
_SCANNED_SUFFIXES = ("*.py", "*.sql")


def _python_sources() -> list[Path]:
    found: list[Path] = []
    for root in _SCANNED_ROOTS:
        if root.exists():
            for pattern in _SCANNED_SUFFIXES:
                found.extend(sorted(root.rglob(pattern)))
    assert found, "스캔 대상을 하나도 찾지 못했다 — 경로가 틀렸다"
    return found


def test_python_sources_have_no_control_characters() -> None:
    offenders: dict[str, list[str]] = {}
    for path in _python_sources():
        text = path.read_text(encoding="utf-8")
        hits = sorted({f"U+{ord(ch):04X}" for ch in text if ch in _FORBIDDEN})
        if hits:
            offenders[str(path.relative_to(_ROOT))] = hits
    assert offenders == {}, (
        "소스에 제어문자가 있다 — 정규식이나 SQL이 조용히 무력화될 수 있다. "
        "문자열로 필요하면 escape(예: \\\\x08)로 적어라."
    )
