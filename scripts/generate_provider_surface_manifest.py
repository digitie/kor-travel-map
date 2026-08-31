"""provider 표면 manifest 생성 — Protocol 적합성 게이트의 입력.

Map은 ADR-006에 따라 provider를 wrapper 없이 쓰고, 런타임에는
``importlib.import_module()`` + ``cast(Any, ...)``로 지연 로드한다. 그래서 provider
모델과 본 저장소 ``Protocol``의 결박은 정적 검사(mypy / import-linter)에 전혀 잡히지
않는다. 게다가 provider 라이브러리는 ``[project.optional-dependencies] providers``
extra라 CI(``pip install -e ".[dev]"``)에 설치조차 되지 않는다.

본 스크립트는 **핀된 exact SHA의 provider 소스**에서 클래스별 공개 멤버 집합을 추출해
``src/kortravelmap/providers/_provider_surface.json``으로 굳힌다. 그러면 CI는 네트워크
없이, provider 설치 없이도 Protocol ↔ 실모델 적합성을 검사할 수 있다.

manifest는 provider별 핀 SHA를 함께 기록하고 검사 측이 ``pyproject.toml``의 핀과
대조한다. 따라서 **핀만 올리고 manifest를 재생성하지 않으면 게이트가 실패한다** —
manifest가 조용히 낡을 수 없다.

사용::

    python scripts/generate_provider_surface_manifest.py            # 재생성
    python scripts/generate_provider_surface_manifest.py --check    # 최신 여부만 확인
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "src" / "kortravelmap" / "providers" / "_provider_surface.json"
SIBLING_ROOT = REPO_ROOT.parent
"""형제 provider 체크아웃 위치 (ADR-044 — 로컬 우선 조회)."""

PROVIDER_PACKAGES: Mapping[str, str] = {
    "python-airkorea-api": "airkorea",
    "python-datagokr-api": "datagokr",
    "python-khoa-api": "khoa",
    "python-kma-api": "kma",
    "python-knps-api": "knps",
    "python-krairport-api": "krairport",
    "python-krex-api": "krex",
    "python-krforest-api": "krforest",
    "python-krheritage-api": "krheritage",
    "python-mois-api": "mois",
    "python-opinet-api": "opinet",
    "python-visitkorea-api": "visitkorea",
}
"""핀 이름 → import 패키지 이름. ``Protocol`` 결박이 있는 provider만 넣는다."""

PROVIDERS_WITHOUT_PROTOCOLS: Mapping[str, str] = {
    "python-mcst-api": (
        "``providers/mcst.py``는 typed 모델이 아니라 CSV row(``Mapping[str, Any]``)를 "
        "받는다. 결박할 ``Protocol``이 없으므로 표면 대조 대상이 아니다 — 이 경계의 "
        "취약점은 모델 속성이 아니라 CSV 컬럼 이름이다."
    ),
}
"""핀은 있으나 ``Protocol`` 결박이 없어 표면을 뽑지 않는 provider와 그 사유.

**빠뜨린 것과 면제한 것을 구분하기 위해 존재한다.** 이 표가 없으면 새 provider를
핀하면서 ``PROVIDER_PACKAGES``에 넣는 것을 잊어도 게이트가 아무 말도 하지 않는다 —
실제로 ``python-mcst-api``가 그렇게 12/13만 검사받는 상태였다.
"""

_PIN_RE = re.compile(
    r'"(?P<dist>python-[a-z0-9-]+)\s*@\s*git\+https://github\.com/digitie/'
    r"(?P<repo>[a-z0-9-]+)\.git@(?P<sha>[0-9a-f]{40})\""
)


class SourceUnavailableError(RuntimeError):
    """핀된 소스를 읽을 수 없다 — manifest가 낡았다는 뜻이 **아니다.**

    이 둘을 구분하지 않으면 호출자가 "확인할 수 없었다"와 "어긋났다"를 같은 실패로
    보게 된다. 전자를 후자로 읽으면 게이트가 시끄러워져 무시되고, 후자를 전자로
    읽으면 조작이 통과한다. exit code로 구분한다 — 2는 "확인 불가", 1은 "어긋남".
    """


class ManifestError(RuntimeError):
    """manifest 생성이 불가능한 상태 — 조용히 넘어가지 않는다."""


def read_pins(pyproject_text: str) -> dict[str, str]:
    """``pyproject.toml`` 원문에서 provider 핀 SHA를 읽는다.

    주석 처리된 핀(``# "python-kasi-api @ ..."``)은 선언이 아니므로 제외한다.
    """
    pins: dict[str, str] = {}
    for line in pyproject_text.splitlines():
        if line.lstrip().startswith("#"):
            continue
        match = _PIN_RE.search(line)
        if match is None:
            continue
        pins[match.group("dist")] = match.group("sha")
    return pins


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise ManifestError(
            f"git {' '.join(args)} 실패 ({repo.name}): {result.stderr.strip()[:400]}"
        )
    return result.stdout


def _public_members(node: ast.ClassDef) -> set[str]:
    """클래스 본문이 직접 선언하는 공개 멤버 이름.

    pydantic field(``AnnAssign``), dataclass field, plain assignment, method,
    ``@property``를 모두 같은 이름 공간으로 본다 — ``Protocol``이 요구하는 것은
    "속성 접근이 성립하는가"이지 선언 형태가 아니다.
    """
    members: set[str] = set()
    for statement in node.body:
        if isinstance(statement, ast.Assign):
            for assign_target in statement.targets:
                if isinstance(assign_target, ast.Name) and not assign_target.id.startswith("_"):
                    members.add(assign_target.id)
            continue
        target: str | None = None
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            target = statement.target.id
        elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
            target = statement.name
        if target is not None and not target.startswith("_"):
            members.add(target)
    return members


def _base_names(node: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
        elif isinstance(base, ast.Subscript):  # ``Generic[T]`` 등
            inner = base.value
            if isinstance(inner, ast.Name):
                names.append(inner.id)
            elif isinstance(inner, ast.Attribute):
                names.append(inner.attr)
    return names


def collect_package_surface(repo: Path, sha: str, package: str) -> dict[str, dict[str, object]]:
    """핀된 SHA에서 패키지의 클래스별 표면을 뽑는다 (패키지 내 상속 평탄화 포함)."""
    listing = _git(repo, "ls-tree", "-r", "--name-only", sha, f"src/{package}/")
    paths = [line for line in listing.splitlines() if line.endswith(".py")]
    if not paths:
        raise ManifestError(f"{repo.name}@{sha[:8]}에 src/{package}/*.py가 없다")

    direct: dict[str, tuple[str, set[str], list[str]]] = {}
    for path in sorted(paths):
        source = _git(repo, "show", f"{sha}:{path}")
        try:
            tree = ast.parse(source)
        except SyntaxError as exc:  # pragma: no cover - provider 소스 손상
            raise ManifestError(f"{path} 파싱 실패: {exc}") from exc
        module = ".".join(Path(path).relative_to("src").with_suffix("").parts)
        if module.endswith(".__init__"):
            module = module[: -len(".__init__")]
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                direct[node.name] = (module, _public_members(node), _base_names(node))

    # 같은 패키지 안의 상속만 평탄화한다. 외부 base(pydantic ``BaseModel`` 등)는
    # 이름으로 남겨 manifest가 "무엇을 펴지 못했는지" 스스로 밝히게 한다.
    resolved: dict[str, dict[str, object]] = {}
    for name, (module, members, bases) in direct.items():
        flattened = set(members)
        unresolved: list[str] = []
        pending = list(bases)
        seen: set[str] = {name}
        while pending:
            base = pending.pop()
            if base in seen:
                continue
            seen.add(base)
            if base in direct:
                flattened |= direct[base][1]
                pending.extend(direct[base][2])
            else:
                unresolved.append(base)
        resolved[f"{module}.{name}"] = {
            "members": sorted(flattened),
            "external_bases": sorted(set(unresolved)),
        }
    return resolved


def build_manifest() -> dict[str, object]:
    """핀된 SHA 기준 provider 표면 manifest를 만든다."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    pins = read_pins(pyproject)
    missing = sorted(set(PROVIDER_PACKAGES) - set(pins))
    if missing:
        raise ManifestError("PROVIDER_PACKAGES에 있으나 pyproject 핀이 없다: " + ", ".join(missing))
    undeclared = sorted(set(pins) - set(PROVIDER_PACKAGES) - set(PROVIDERS_WITHOUT_PROTOCOLS))
    if undeclared:
        raise ManifestError(
            "pyproject에 핀이 있으나 표면 추출 대상인지 선언되지 않은 provider다 — "
            "``Protocol`` 결박이 있으면 PROVIDER_PACKAGES에, 없으면 사유와 함께 "
            "PROVIDERS_WITHOUT_PROTOCOLS에 넣을 것: " + ", ".join(undeclared)
        )

    providers: dict[str, object] = {}
    for dist, package in sorted(PROVIDER_PACKAGES.items()):
        repo = SIBLING_ROOT / dist
        if not (repo / ".git").exists():
            raise SourceUnavailableError(
                f"형제 체크아웃이 없다: {repo} (ADR-044 — 로컬 우선 조회가 전제다)"
            )
        sha = pins[dist]
        providers[dist] = {
            "package": package,
            "pinned_sha": sha,
            "classes": collect_package_surface(repo, sha, package),
        }
    return {
        "version": 1,
        "generated_by": "scripts/generate_provider_surface_manifest.py",
        "providers": providers,
        "providers_without_protocols": dict(sorted(PROVIDERS_WITHOUT_PROTOCOLS.items())),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="provider 표면 manifest 생성/확인")
    parser.add_argument(
        "--check",
        action="store_true",
        help="재생성하지 않고 현재 manifest가 최신인지만 확인한다 (다르면 exit 1)",
    )
    args = parser.parse_args(argv)

    try:
        manifest = build_manifest()
    except SourceUnavailableError as exc:
        # exit 2 = "확인할 수 없었다". 호출자(lint 게이트)가 "어긋났다"(exit 1)와
        # 구분해 건너뛸 수 있어야 한다.
        print(f"provider 소스를 읽을 수 없다: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    if args.check:
        if not MANIFEST_PATH.exists():
            print(f"manifest 없음: {MANIFEST_PATH}", file=sys.stderr)
            return 1
        if MANIFEST_PATH.read_text(encoding="utf-8") != rendered:
            print(
                "provider 표면 manifest가 낡았다 — "
                "`python scripts/generate_provider_surface_manifest.py`로 재생성할 것",
                file=sys.stderr,
            )
            return 1
        print("provider 표면 manifest 최신")
        return 0

    MANIFEST_PATH.write_text(rendered, encoding="utf-8")
    providers = manifest["providers"]
    assert isinstance(providers, dict)
    total = sum(len(entry["classes"]) for entry in providers.values())
    print(
        f"{MANIFEST_PATH.relative_to(REPO_ROOT)} 생성 — "
        f"provider {len(PROVIDER_PACKAGES)}개, 클래스 {total}개"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
