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
# 왜 ACL 블록마다 role을 바꾸는가:
#   GRANT/REVOKE는 **객체 소유자만** 할 수 있다. baseline은 전 구간을 한 role
#   (`ktm_feature_schema_owner`)로 돌리는데, ADR-090의 role은 `NOINHERIT`이라
#   membership이 있어도 권한이 승계되지 않는다. 그리고 소유자가 아닌 GRANT는
#   **오류가 아니라 경고 후 무시**다. 그래서 첫 시도는 exit 0으로 조용히 통과하면서
#   routine 10개가 PUBLIC EXECUTE로 남았다(체인 102 → baseline 112). pg_dump가 ACL
#   블록마다 `Owner:` 주석을 달아 주므로 소유자를 기계적으로 유도해 `SET LOCAL ROLE`
#   한다. 그리고 그게 실제로 먹었는지 baseline 끝에서 digest로 **자기검증**한다 —
#   조용히 무시되는 결함은 조용히 잡히지 않는 검사기로 막을 수 없다.
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

# routine ACL의 정규화된 digest. **한 곳에서만 정의한다** — 이 문자열이
#   (a) 빌드 시점의 기대값 계산과 (b) baseline이 적용 후 스스로 확인하는 관측값 계산
# 양쪽에 그대로 들어간다. 손으로 두 번 적으면 "검사기가 검사 대상과 어긋난 채 green"이
# 다시 생긴다.
#
# 정규화 2가지가 load-bearing이다:
#   - aclitem 배열은 GRANT 순서에 따라 요소 순서가 달라진다 → 텍스트로 정렬한다.
#   - `ALTER FUNCTION ... OWNER TO`는 NULL이던 proacl을 **기본값과 동일한 값으로
#     물화**시킨다. 권한은 그대로인데 표현만 달라지는 것이라, 빼지 않으면 의미가 같은
#     두 DB가 어긋난다(체인의 state_procedure_owner routine 17개 중 7개가 이 경우다).
#     `acldefault()`와 같은 항목을 제거한다 — `compare-schema-catalogs.sh`가 쓰는
#     정규화와 같다. 동등성의 정본은 그 오라클이고, 여기 것은 "GRANT가 실제로 먹었나"
#     한 축만 보는 부분집합 검사다.
ROUTINE_ACL_DIGEST_SQL="$(cat <<'SQL'
SELECT encode(sha256(convert_to(coalesce(string_agg(sig || '=' || acl, chr(10) ORDER BY sig), ''), 'UTF8')), 'hex')
  FROM (SELECT n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' AS sig,
               coalesce((SELECT string_agg(entry::text, ',' ORDER BY entry::text)
                           FROM unnest(p.proacl) AS entry
                          WHERE entry::text <> ALL (SELECT default_entry::text
                                                      FROM unnest(pg_catalog.acldefault('f'::"char", p.proowner))
                                                        AS default_entry)), '') AS acl
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname IN ('feature','provider_sync','ops')) s
SQL
)"

printf '=== routine ACL digest (기대값) ===\n'
ACL_DIGEST="$(docker exec "$CONTAINER" psql -U "$USER_NAME" -d "$DB" -tA -c "$ROUTINE_ACL_DIGEST_SQL" | tr -d '[:space:]')"
[ ${#ACL_DIGEST} -eq 64 ] || die "routine ACL digest를 얻지 못했다: ${ACL_DIGEST:0:32}"
printf '  %s\n' "$ACL_DIGEST"

printf '=== 정규화 ===\n'
python3 - "$RAW" "$OUT_DIR/schema.sql" "$ACL_DIGEST" "$ROUTINE_ACL_DIGEST_SQL" <<'PY'
import pathlib, re, sys

raw = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
out_path = pathlib.Path(sys.argv[2])
acl_digest = sys.argv[3]
acl_digest_sql = sys.argv[4]
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

# 7. ACL 블록을 **그 블록의 소유자로** 실행한다 (파일 상단 주석의 근거 참조).
#    pg_dump는 ACL을 파일 끝에 모아 내므로 "첫 ACL 이후는 전부 ACL"을 전제로 삼되,
#    그 전제를 가정하지 않고 **검사한다** — 깨지면 여기서 선다.
HEADER = re.compile(
    r"^-- Name: (?P<name>.+); Type: (?P<type>[A-Z ]+); Schema: (?P<schema>.+); Owner: (?P<owner>.*)$"
)
ROLE_NAME = re.compile(r"^[a-z_][a-z0-9_]*$")

out: list[str] = []
acl_started = False
expect_close = False
pending_owner: str | None = None
current_role: str | None = None
n_role_switch = 0
for line in text.split("\n"):
    matched = HEADER.match(line)
    if matched:
        block_type = matched.group("type").strip()
        if block_type == "ACL":
            owner = matched.group("owner").strip()
            if not ROLE_NAME.match(owner):
                raise SystemExit(f"ACL 블록 소유자를 읽지 못했다: {line[:90]!r}")
            pending_owner = owner
            expect_close = True
        elif acl_started:
            raise SystemExit(
                "ACL 블록 뒤에 non-ACL 블록이 있다 — role 전환 구간이 파일 끝까지"
                f" 이어진다는 전제가 깨졌다: {line[:90]!r}"
            )
    out.append(line)
    if expect_close and line == "--":
        expect_close = False
        if not acl_started:
            acl_started = True
            out.append("")
            out.append("-- [build-baseline] 아래부터 ACL 구간. 각 블록을 소유자로 실행한다.")
            out.append("-- 트랜잭션 밖에서 돌리면 SET LOCAL이 무효가 되는데, 그 경우 아래")
            out.append("-- current_setting()이 미정의로 터진다 — fail-closed다.")
            out.append("SELECT set_config('ktm.baseline_prior_role', current_user, true);")
        if pending_owner != current_role:
            current_role = pending_owner
            out.append(f"SELECT set_config('role', '{current_role}', true);")
            n_role_switch += 1
        pending_owner = None

if not acl_started:
    raise SystemExit("ACL 블록을 하나도 찾지 못했다 — pg_dump 출력 형식이 바뀌었다")
out.append("")
out.append("SELECT set_config('role', current_setting('ktm.baseline_prior_role'), true);")

# 8. 자기검증. 소유자 아닌 GRANT는 경고만 내고 무시되므로 **적용 성공(exit 0)이
#    ACL 적용의 증거가 되지 못한다.** baseline이 스스로 확인하게 한다.
out.append(
    "\nDO $ktm_acl$\n"
    "DECLARE\n"
    "    observed text;\n"
    f"    expected text := '{acl_digest}';\n"
    "BEGIN\n"
    f"    observed := ({acl_digest_sql});\n"
    "    IF observed IS DISTINCT FROM expected THEN\n"
    "        RAISE EXCEPTION\n"
    "            'baseline routine ACL이 원본과 다르다 (관측 %, 기대 %) — 소유자가 아닌"
    " 세션이 GRANT/REVOKE를 냈을 가능성이 크다', observed, expected\n"
    "            USING ERRCODE = '42501';\n"
    "    END IF;\n"
    "END\n"
    "$ktm_acl$;"
)
text = "\n".join(out)

if not text.endswith("\n"):
    text += "\n"
out_path.write_bytes(text.encode("utf-8"))
print(f"  버전 주석 제거: {dropped['version']}줄")
print(f"  preamble 제거:  {dropped['preamble']}줄")
print(f"  CREATE SCHEMA IF NOT EXISTS 치환: {n_schema}개")
print(f"  ACL role 전환 삽입: {n_role_switch}회")
print(f"  결과: {len(text.splitlines())}줄")
PY

printf '=== seed 데이터 ===\n'
# seed 대상은 **기계로** 고른다. 사람이 목록을 적으면 새 seed가 생겼을 때 조용히
# 빠진다. 대상 DB는 provider 적재 전 상태여야 한다 — 그래야 남아 있는 행이 곧
# 체인이 넣은 것이다. (인수 실행 잔재가 섞인 DB로 뽑으면 그 잔재까지 baseline에
# 들어간다 — 실제로 처음에 그럴 뻔했다.)
SEED_LIST="$(mktemp)"
docker exec "$CONTAINER" psql -U "$USER_NAME" -d "$DB" -tA -c "
DO \$\$
DECLARE r record; c bigint;
BEGIN
    CREATE TEMP TABLE IF NOT EXISTS ktm_seed_rel(rel text);
    FOR r IN SELECT schemaname, tablename FROM pg_tables
             WHERE schemaname IN ('feature','provider_sync','ops')
             ORDER BY schemaname, tablename LOOP
        EXECUTE format('SELECT count(*) FROM %I.%I', r.schemaname, r.tablename) INTO c;
        IF c > 0 THEN
            INSERT INTO ktm_seed_rel VALUES (r.schemaname || '.' || r.tablename);
        END IF;
    END LOOP;
END \$\$;
SELECT rel FROM ktm_seed_rel ORDER BY rel;" 2>/dev/null | grep -E '^[a-z_]+\.[a-z_]+$' > "$SEED_LIST"
printf 'seed 대상 %s개:\n' "$(wc -l < "$SEED_LIST")"
sed 's/^/  /' "$SEED_LIST"

SEED_ARGS=()
while IFS= read -r rel; do SEED_ARGS+=(-t "$rel"); done < "$SEED_LIST"
if [ "${#SEED_ARGS[@]}" -gt 0 ]; then
  # `--column-inserts` 필수 — `COPY ... FROM stdin`은 migration의 SQL 실행 경로로
  # 돌릴 수 없다.
  docker exec "$CONTAINER" pg_dump -U "$USER_NAME" -d "$DB" \
    --data-only --column-inserts --no-owner \
    "${SEED_ARGS[@]}" -f /tmp/ktm-baseline-seed.sql
  docker cp "$CONTAINER":/tmp/ktm-baseline-seed.sql "$OUT_DIR/seed.sql" >/dev/null
  docker exec "$CONTAINER" rm -f /tmp/ktm-baseline-seed.sql
  python3 - "$OUT_DIR/seed.sql" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
lines = [
    line for line in p.read_text(encoding="utf-8").splitlines()
    if not line.startswith(("-- Dumped from database version", "-- Dumped by pg_dump version"))
    and not line.startswith("SELECT pg_catalog.set_config('search_path'")
]
p.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))
print(f"  seed.sql {len(lines)}줄")
PY
fi
rm -f "$SEED_LIST"

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
