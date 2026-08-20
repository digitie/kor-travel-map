"""T-VN-40C static zero gate — 제거된 식별자가 **살아 있는 참조**로 남지 않았는지.

`contracts/vnext/t-vn-40c-removal-manifest-v1.json`의 `static_zero_gate`가 정본이다. 이
테스트는 그 정의를 저장소 안에서 실행 가능하게 만든다 — 스크립트로만 존재하는 gate는
아무도 돌리지 않으면 아무 것도 지키지 않는다.

두 종류의 잔존을 구분한다.

* **live reference** — 식별자가 존재하는 것처럼 쓰인 자리. 0이어야 한다.
* **tombstone prose** — "그건 40C에서 지웠다"라고 말하는 문장. 제거 문서라면 당연히
  있어야 하고, 아래 `_TOMBSTONE_PROSE`에 파일·식별자·사유로 열거한다. 열거되지 않은
  새 언급은 실패한다.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]
_MANIFEST = _ROOT / "contracts/vnext/t-vn-40c-removal-manifest-v1.json"

# manifest `active_scopes`. `docs/*.md (current)`에서 manifest `allowed_locations`가
# 지목한 이력 문서(journal/tasks/tasks-done/resume)는 제외한다.
_SCOPE_DIRS = (
    "src",
    "packages/kor-travel-map-api/src",
    "packages/kor-travel-map-dagster/src",
    "packages/kor-travel-map-user-client/src",
    "packages/kor-travel-map-admin/frontend/src",
    "packages/kor-travel-map-admin/frontend/e2e",
    "docs/architecture",
    "docs/runbooks",
)
_HISTORY_DOCS = {"journal.md", "tasks.md", "tasks-done.md", "resume.md"}

# (경로, 식별자) -> 사유. 이 조합의 hit만 tombstone prose로 허용한다.
_TOMBSTONE_PROSE: dict[tuple[str, str], str] = {
    ("docs/curated-features.md", "feature.curated_features"): "현행 문서 머리말의 제거 고지",
    ("docs/curated-features.md", "/v1/curated-features"): "현행 문서 머리말의 제거 고지",
    ("docs/curated-features.md", "/admin/curated-features"): "§6에서 삭제된 admin 라우트 명시",
    ("docs/architecture/data-model.md", "feature.curated_features"): "§1.2 제거 고지",
    (
        "docs/architecture/data-model.md",
        "curated_feature_detail_snapshots",
    ): "§1.2 제거 고지",
    ("docs/architecture/data-model.md", "legacy_projection_id"): "전환기 서술의 과거형 기록",
    ("docs/architecture/rest-api.md", "/v1/curated-features"): "§2.4.3 제거 고지",
    (
        "docs/architecture/openapi-admin-contract.md",
        "/v1/curated-features",
    ): "§8.2 제거 고지",
    (
        "docs/architecture/openapi-admin-contract.md",
        "/v1/admin/features/curated",
    ): "§8.2 제거 고지",
    ("docs/deploy.md", "legacy_projection_id"): "2026-08-18 실행 기록(당시 사실)",
}


def _identifiers() -> list[str]:
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    return list(manifest["static_zero_gate"]["identifiers"])


def _scanned_files() -> list[Path]:
    files: list[Path] = []
    for rel in _SCOPE_DIRS:
        base = _ROOT / rel
        assert base.is_dir(), f"static_zero_gate scope가 없다: {rel}"
        files.extend(p for p in base.rglob("*") if p.is_file())
    files.extend(
        p for p in (_ROOT / "docs").glob("*.md") if p.name not in _HISTORY_DOCS
    )
    return [p for p in files if p.suffix in {".py", ".ts", ".tsx", ".md", ".sql", ".json"}]


def _hits(identifier: str) -> list[tuple[str, int, str]]:
    # manifest 주석대로 경로형 식별자는 정규식이 아니다. `\w`가 든 것만 정규식으로 본다.
    is_regex = "\\" in identifier
    matcher = re.compile(identifier) if is_regex else None
    out: list[tuple[str, int, str]] = []
    for path in _scanned_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if not is_regex and identifier not in text:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            found = matcher.search(line) if matcher else (identifier in line)
            if found:
                out.append((path.relative_to(_ROOT).as_posix(), i, line.strip()))
    return out


def test_gate_identifier_set_is_not_empty() -> None:
    """빈 목록이면 아래 검사가 자명하게 통과한다."""
    identifiers = _identifiers()
    assert len(identifiers) >= 10, identifiers
    assert "feature.curated_features" in identifiers


def test_scanned_corpus_is_not_empty() -> None:
    """scope 경로가 어긋나면 0건이 나와도 아무 것도 안 지킨다."""
    files = _scanned_files()
    assert len(files) > 200, len(files)


def test_no_live_reference_to_removed_identifiers() -> None:
    """제거된 식별자는 tombstone prose 허용 목록 밖에서 나타나지 않는다."""
    unexpected: list[str] = []
    for identifier in _identifiers():
        for rel, lineno, line in _hits(identifier):
            if (rel, identifier) in _TOMBSTONE_PROSE:
                continue
            unexpected.append(f"{rel}:{lineno} [{identifier}] {line[:110]}")
    assert not unexpected, (
        "T-VN-40C가 지운 식별자가 살아 있는 참조로 남았다. 코드면 제거하고, 문서의 제거 "
        "고지라면 이 파일 `_TOMBSTONE_PROSE`에 사유와 함께 등록한다:\n"
        + "\n".join(unexpected)
    )


def test_tombstone_prose_allowlist_has_no_stale_entry() -> None:
    """허용 목록이 실제로 존재하는 hit만 담는다 — 죽은 예외는 gate를 느슨하게 만든다."""
    identifiers = set(_identifiers())
    stale: list[str] = []
    for (rel, identifier), reason in _TOMBSTONE_PROSE.items():
        assert identifier in identifiers, f"gate 목록에 없는 식별자를 허용했다: {identifier}"
        if not any(hit_rel == rel for hit_rel, _, _ in _hits(identifier)):
            stale.append(f"{rel} [{identifier}] — {reason}")
    assert not stale, "이제 등장하지 않는 tombstone 예외:\n" + "\n".join(stale)
