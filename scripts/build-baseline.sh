#!/usr/bin/env bash
# alembic squash baseline 생성기. **손으로 쓰지 않는다** — 기계 생성 + 기계 정규화다.
#
# 왜 손으로 안 쓰는가:
#   0001~0104 체인이 만드는 카탈로그는 relation 108개 + routine 112개 + 제약/인덱스
#   수백 개다. 손으로 옮기면 빠뜨린 것을 아무도 모른다. 이 저장소가 2026-08-13에만
#   세 번 겪은 결함이 전부 "사본이 원본과 조용히 어긋남"이었다.
#
# 왜 3 스키마로 좁히는가:
#   role / schema / extension은 **체인 밖 bootstrap이 정본**이다
#   (`docker/postgres-role-bootstrap.sh`, `tests/integration/_tvn34_migration_bootstrap.py`).
#   baseline이 그것까지 재현하려 들면 손으로 옮겨야 하는 prologue가 생기고, 그게
#   이 작업의 최대 위험 표면이 된다. 스코프를 좁히면 그 표면이 통째로 사라진다.
#
# 왜 owner/ACL을 살리는가:
#   ADR-090의 소유권 분리(schema owner / state procedure owner / audit writer)가
#   보안 경계 본체다. `--no-owner`로 지우면 baseline이 그 경계를 재현하지 못한다.
#
# 사용:
#   scripts/build-baseline.sh <container> <db> [--admin-user U] [--out DIR]
set -euo pipefail

die() { printf 'build-baseline: %s\n' "$1" >&2; exit 1; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
OUT_DIR="$SCRIPT_DIR/../alembic/baseline"
ADMIN_USER=""
ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --admin-user) ADMIN_USER="${2:?--admin-user needs a value}"; shift 2 ;;
    --out) OUT_DIR="${2:?--out needs a value}"; shift 2 ;;
    -*) die "알 수 없는 옵션: $1" ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
CONTAINER="${ARGS[0]:?container required}"
DB="${ARGS[1]:?db required}"
USER_NAME="${ADMIN_USER:-postgres}"

mkdir -p "$OUT_DIR"
RAW="$(mktemp)"; trap 'rm -f "$RAW"' EXIT

printf '=== pg_dump --schema-only (feature / provider_sync / ops) ===\n'
docker exec "$CONTAINER" pg_dump -U "$USER_NAME" -d "$DB" \
  --schema-only \
  -n feature -n provider_sync -n ops \
  --exclude-table=public.alembic_version \
  -f /tmp/ktm-baseline-raw.sql
docker cp "$CONTAINER":/tmp/ktm-baseline-raw.sql "$RAW" >/dev/null
docker exec "$CONTAINER" rm -f /tmp/ktm-baseline-raw.sql
printf '원본: %s줄\n' "$(wc -l < "$RAW")"

printf '=== 정규화 ===\n'
python3 - "$RAW" "$OUT_DIR/schema.sql" <<'PY'
import pathlib, re, sys

raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
out_path = pathlib.Path(sys.argv[2])
lines = raw.splitlines()
kept, dropped = [], {"version": 0, "preamble": 0}

# 4. preamble에서 **search_path 고정만** 버린다. alembic/env.py가 트랜잭션 안에서
#    search_path를 세우므로 dump의 `set_config('search_path','')`가 그걸 덮으면 안 된다.
#
#    ⚠️ 나머지 `SET`은 남긴다. 특히 `SET check_function_bodies = false`는
#    **load-bearing**이다 — pg_dump는 함수를 테이블보다 먼저 낼 수 있고, 그때 본문이
#    참조하는 relation이 아직 없으면 컴파일이 실패한다. 처음에 preamble을 통째로
#    버렸다가 정확히 그 오류를 만났다
#    (`ERROR: relation "feature.features" does not exist / compilation of PL/pgSQL
#    function "apply_provider_feature_field_patch"`).
PREAMBLE = re.compile(
    r"^SELECT pg_catalog\.set_config\('search_path'"
)
for line in lines:
    # 6. psql 메타명령은 제거가 아니라 **거부**한다. pg_dump 판올림으로 `\restrict`
    #    같은 것이 유입되면 조용히 지워지는 대신 빌드가 서야 한다.
    if line.startswith("\\"):
        raise SystemExit(f"psql 메타명령이 dump에 있다 — 정규화 규칙을 갱신하라: {line[:60]!r}")
    # 3. 판올림마다 바뀌는 버전 주석 2줄
    if line.startswith("-- Dumped from database version") or line.startswith("-- Dumped by pg_dump version"):
        dropped["version"] += 1
        continue
    if PREAMBLE.match(line):
        dropped["preamble"] += 1
        continue
    kept.append(line)

text = "\n".join(kept)

# 5. CREATE SCHEMA -> IF NOT EXISTS. bootstrap이 먼저 만들어 두므로 충돌하면 안 된다.
text, n_schema = re.subn(
    r"^CREATE SCHEMA (feature|provider_sync|ops);$",
    r"CREATE SCHEMA IF NOT EXISTS \1;",
    text,
    flags=re.MULTILINE,
)
if n_schema != 3:
    raise SystemExit(f"CREATE SCHEMA 3개를 기대했는데 {n_schema}개를 바꿨다")

if not text.endswith("\n"):
    text += "\n"
out_path.write_bytes(text.encode("utf-8"))
print(f"  버전 주석 제거: {dropped['version']}줄")
print(f"  preamble 제거:  {dropped['preamble']}줄")
print(f"  CREATE SCHEMA IF NOT EXISTS 치환: {n_schema}개")
print(f"  결과: {len(text.splitlines())}줄")
PY

printf '=== 결정론 확인 (같은 DB에서 두 번 뽑아 동일한가) ===\n'
RAW2="$(mktemp)"
docker exec "$CONTAINER" pg_dump -U "$USER_NAME" -d "$DB" --schema-only \
  -n feature -n provider_sync -n ops --exclude-table=public.alembic_version \
  -f /tmp/ktm-baseline-raw2.sql
docker cp "$CONTAINER":/tmp/ktm-baseline-raw2.sql "$RAW2" >/dev/null
docker exec "$CONTAINER" rm -f /tmp/ktm-baseline-raw2.sql
if diff -q <(grep -v '^-- Dumped' "$RAW") <(grep -v '^-- Dumped' "$RAW2") >/dev/null; then
  printf '  결정론 OK\n'
else
  printf '  경고: 같은 DB에서 두 dump가 다르다 — baseline이 재현 가능하지 않다\n'
  diff <(grep -v '^-- Dumped' "$RAW") <(grep -v '^-- Dumped' "$RAW2") | head -5
fi
rm -f "$RAW2"

printf '\nbaseline: %s (%s줄, sha256 %s)\n' \
  "$OUT_DIR/schema.sql" \
  "$(wc -l < "$OUT_DIR/schema.sql")" \
  "$(sha256sum < "$OUT_DIR/schema.sql" | cut -c1-16)"
