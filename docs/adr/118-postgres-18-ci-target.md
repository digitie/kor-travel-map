# ADR-118 — DB 기준을 PostgreSQL 18 + PostGIS 3.6으로 올리고, CI는 공용 instance digest 한 lane에서 돈다 (ADR-007·ADR-103 부분 대체)

- 상태: proposed (2026-10-28)
- 날짜: 2026-10-28
- 결정자: human(공용 PG 16→18 업그레이드, Map 병행 작업 지시), Claude(설계·구현)
- 관계: **ADR-007**의 "DB: PostgreSQL 16 + PostGIS 3.5"를 대체한다(나머지 스택은 그대로).
  **ADR-103**의 "CI `integration`은 `lane: alpine`·`lane: glibc` 두 leg"를 대체한다(공용 instance·collation 결정은
  그대로). Manager #562(공용 PG pg_upgrade 16→18, 2026-10-27).

## 컨텍스트

n150 공용 instance(`kor-travel-shared-postgres`)가 2026-10-27 `pg_upgrade --link`로 PostgreSQL 16.9 → **18.6**,
PostGIS 3.5.2 → **3.6.4**로 올랐다. 이미지는 Manager `docker-compose.yml`의
`postgis/postgis:18-3.6@sha256:4a43e3c3…`이다. prod Map은 업그레이드된 DB에서 정상이다.

그런데 Map CI는 PG16 이미지 두 개(alpine `dc17b064…`, glibc `8b33190b…`)에서만 돌았다. **빈 DB 재구축과 catalog를
들여다보는 migration은 PG18에서 검증된 적이 없었다.** PG18로 처음 돌리자 fresh 설치가 첫 migration에서 멈췄다:

- `400_schema_baseline`의 final guard가 `public.alembic_version`을 정확히 닫으면서 PG16 catalog 모양을 숫자로 박았다.
  PG17부터 `pg_attribute.attstattarget` 기본값은 `-1`이 아니라 `NULL`이고, table 소유자 기본 권한에 `MAINTAIN`이 더해져
  ACL 항목이 7+1이 아니라 8+1개이며, PG18은 `NOT NULL`도 `pg_constraint`에 contype `'n'` 행으로 둔다.
- head 오라클(`alembic/head-schema.sql`)은 `pg_dump` 16 출력이다. 18은 `SET transaction_timeout`을 더하고, 기본 이름이 아닌
  NOT NULL constraint 이름을 적는다.
- 이미 고친 것: `pg_database.daticulocale` → `datlocale`(PG17 개명, #1429).

## 결정

1. **DB 기준은 PostgreSQL 18 + PostGIS 3.6이다.** prod(공용 instance)·CI·standalone compose가 같은 major다.
2. **CI 통합 suite는 lane 하나 — 공용 instance가 실제로 도는 digest**(`postgis/postgis@sha256:4a43e3c3…`, glibc,
   `en_US.utf8`)에서 돈다. PG16 alpine·glibc 두 lane은 없앤다. 정본은 `tests/integration/_postgis_image.py`의
   `SHARED_GLIBC_POSTGIS_IMAGE`이고 `ci.yml`·`postgis-only.yml` matrix가 그 사본이다(`tests/unit/test_ci_workflows.py`).
   - alpine lane을 없애면 musl(바이트 순서와 같은 default collation)을 더는 보지 않는다. prod는 glibc이고, `COLLATE "C"`
     회귀 탐지기는 glibc에서만 판별력이 있으므로 잃는 판별력은 없다.
   - 다음 major 이행 때는 matrix에 이행 lane을 잠시 더한다(`KTM_TEST_POSTGIS_IMAGE`는 그대로 digest만 받는다).
3. **catalog를 읽는 코드는 major를 숫자로 박지 않는다.** 비교 대상이 major마다 바뀌면 그 major의 기본값에서 유도한다
   (`acldefault('r', owner)`로 소유자 몫, `COALESCE(attstattarget, -1)`, contype `'n'` 분리). 비용이 싸면 16에서도
   맞게 둔다 — 롤백 리허설과 다른 저장소의 16 instance에서 같은 SQL을 읽을 수 있다.
4. **standalone compose도 18이다.** `postgres` 서비스는 같은 digest, one-shot client는 `postgres:18-alpine`이다. PG18
   공식 이미지는 PGDATA가 `/var/lib/postgresql/18/docker`라 volume을 `/var/lib/postgresql`에 붙인다. PG16 volume은
   이어 쓸 수 없다 — standalone 사용자는 새 volume으로 다시 만든다(prod는 Manager가 pg_upgrade로 이미 옮겼다).
5. PG16에서 뽑은 오라클(`alembic/head-schema.sql`, `contracts/vnext/target-schema-fingerprints-v1.json`, 이미지별
   ACL digest)은 PG18에서 다시 뽑는다. 정규화 규칙은 넓히지 않는다 — 걷어낼 것을 늘리면 오라클이 그만큼 눈을 감는다.

## 결과

- 긍정: CI가 prod와 같은 major·PostGIS·collation에서 fresh 재구축을 매 PR 증명한다. lane이 하나라 CI 시간이 준다.
- 부정: PG16에서 돌던 것을 CI가 더는 보지 않는다. 16으로 되돌리는 롤백(Manager가 PGDATA 16을 보존하는 동안)은 CI 근거가
  없다 — 그때는 이행 lane을 다시 더해 확인한다.
- 부정: 공용 instance digest는 여전히 Manager 핀의 사본이고 두 저장소 사이에 drift 검출기가 없다(ADR-103과 같다).
  Manager가 이미지를 올리면 이 값과 workflow를 같은 묶음으로 바꾼다.

## 이 저장소에서 바뀐 것

- `tests/integration/_postgis_image.py` 기본값 = 공용 PG18 digest, `ALPINE_POSTGIS_IMAGE` 삭제.
- `.github/workflows/ci.yml`·`postgis-only.yml` matrix = `lane: pg18` 하나. 필수 check 이름은
  `pytest integration (PostGIS, pg18)`(`docs/runbooks/branch-protection.md`).
- `alembic/versions/400_schema_baseline.py` final guard를 major 무관으로(위 결정 3). 이미 적용된 prod DB에는 영향 없다 —
  fresh 설치 때만 돈다.
- `docker-compose.yml` postgres·one-shot client 이미지와 volume 경로.
- 오라클 재생성(결정 5).
