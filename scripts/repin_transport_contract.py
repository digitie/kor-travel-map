"""kor-travel-transport export 계약(vendored OpenAPI)을 transport의 한 revision으로 다시 핀한다.

ADR-106. Map은 transport ``docs/openapi.json``을 ``contracts/kor-travel-transport/openapi.json``으로
복사해 두고 ``PIN.json``에 그 revision과 SHA-256을 적는다. 이 스크립트가 그 두 값을 한 번에
바꾼다 — 손으로 고치면 파일과 핀이 어긋난다(``tests/unit/test_providers_kor_travel_transport.py``가
잡는다).

transport가 머지된 뒤 **머지 커밋**으로 다시 핀한다(미머지 브랜치 커밋은 force-push로 사라질 수 있다)::

    git -C ../kor-travel-transport fetch origin main
    python scripts/repin_transport_contract.py \
        --transport-repo ../kor-travel-transport --revision origin/main

revision은 transport 저장소에서 ``git rev-parse``로 풀어 40자 SHA로 적는다. 그 revision이
``origin/main``의 조상이 아니면 거부한다(``--allow-unmerged``로만 넘는다 — 개발 중 임시 핀용).
golden fixture(``golden/*.json``)는 바꾸지 않는다. 계약이 바뀌었으면 테스트가 빨개지고, 그때 사람이
golden을 고친다.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_DIR = ROOT / "contracts" / "kor-travel-transport"
OPENAPI = CONTRACT_DIR / "openapi.json"
PIN = CONTRACT_DIR / "PIN.json"


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True
    ).stdout


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--transport-repo", type=Path, required=True, help="kor-travel-transport checkout")
    parser.add_argument("--revision", required=True, help="transport revision (머지 커밋 권장)")
    parser.add_argument(
        "--allow-unmerged",
        action="store_true",
        help="origin/main의 조상이 아닌 revision도 핀한다(개발 중 임시 핀만)",
    )
    args = parser.parse_args(argv)

    pin = json.loads(PIN.read_text(encoding="utf-8"))
    sha = _git(args.transport_repo, "rev-parse", "--verify", f"{args.revision}^{{commit}}").decode().strip()
    merged = subprocess.run(
        ["git", "-C", str(args.transport_repo), "merge-base", "--is-ancestor", sha, "origin/main"],
        check=False,
    ).returncode == 0
    if not merged and not args.allow_unmerged:
        print(f"{sha}는 transport origin/main에 머지되지 않았다 — 머지 커밋으로 핀하라.", file=sys.stderr)
        return 2
    body = _git(args.transport_repo, "show", f"{sha}:{pin['source_path']}")
    digest = hashlib.sha256(body).hexdigest()
    OPENAPI.write_bytes(body)
    pin["transport_revision"] = sha
    pin["openapi_sha256"] = digest
    PIN.write_text(json.dumps(pin, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"pinned {pin['transport_repository']}@{sha} sha256={digest} (merged={merged})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
