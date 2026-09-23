# ADR-100: DB LOGIN role를 3개에서 1개로 통합한다

- **상태**: accepted
- **날짜**: 2026-09-21
- **결정자**: 사용자 + Claude
- **관련**: ADR-090(부분 supersede), ADR-046/070(PinVi 공용 instance 전환 및 geo 패턴 채택 — 이번 결정의 직접 계기)

## 컨텍스트

이 저장소의 vNext 우선순위는 **정확성 → 단일 정본/설계적 우월성 → 단순성 → 보안 →
확장성 → 실측 성능 → 호환성** 순으로 개정됐다(2026-09-21, CLAUDE.md/AGENTS.md). 단순성이
보안보다 위로 올라오면서, 같은 세션에서 이미 PinVi의 M05 다중 role 모델(4 role: schema
owner/migration owner/migrator/app user)을 폐기하고 geo/concierge/weather와 같은 단일
scoped app role 패턴으로 교체했다(kor-travel-docker-manager PR #382, PinVi PR #563).

ADR-090은 Map의 DB LOGIN 경계를 세 축으로 나눴다: `ktm_feature_migrator`(스키마 DDL,
`ktm_feature_schema_owner`로 `SET` 전용 접근), `ktm_feature_api_runtime`(API 서버가 쓰는
런타임 계정), `ktm_feature_dagster_runtime`(Dagster가 쓰는 런타임 계정). 이 분리는 두 가지
목적을 가졌다 — 하나는 ADR-090 §2가 명시하는 절차/트리거 강제 경계 자체(런타임은
`SECURITY DEFINER` procedure를 통해서만 상태/audit 테이블에 쓴다)이고, 다른 하나는 그
안에서 "이 쓰기가 API 서버에서 왔는지 Dagster에서 왔는지"까지 `session_user` 문자열
비교로 구분하는 **부가적인 출처(provenance) 세분화**다.

셋으로 나뉜 LOGIN 계정은 Manager(`kor-travel-docker-manager`)의 배포 표면도 3배로 만든다
— 별도 비밀번호 3개, DSN 3개, compose env 6줄, 자격증명 rotation·재발급 경로 3갈래. PinVi가
이미 겪었듯 half-cutover(한쪽만 옮기고 다른 쪽을 놓치는) 결함은 이 축의 개수에 비례한다.

## 결정

1. `ktm_feature_migrator` / `ktm_feature_api_runtime` / `ktm_feature_dagster_runtime` 세
   LOGIN role을 단일 LOGIN role **`ktm_feature_service`**로 통합한다. 이 role은 기존 세
   role이 각각 가졌던 membership을 합집합으로 받는다:
   - `ktm_feature_schema_owner` — `ADMIN FALSE, INHERIT FALSE, SET TRUE` (migrator가 갖던
     것과 동일한 SET-전용 DDL 창. 평상시 런타임 세션은 schema owner 권한을 자동 상속하지
     않는다 — 마이그레이션만 명시적으로 `SET ROLE`한다.)
   - `ktm_feature_runtime` — `ADMIN FALSE, INHERIT TRUE, SET FALSE` (api_runtime/
     dagster_runtime이 이미 공유하던 상속 경로, 변경 없음.)
   - api_runtime 전용이던 executor role 6개 + dagster_runtime 전용이던 executor role 3개를
     모두 `INHERIT TRUE`로 받는다(양쪽이 하던 일을 한 연결이 다 할 수 있게 됨).
2. **ADR-090 §2의 절차·트리거 강제 경계 자체는 바뀌지 않는다.** 18개 NOLOGIN role(schema
   owner, 도메인별 procedure owner, audit writer 등), 97개 `SECURITY DEFINER`
   procedure/function, 180개 trigger는 모두 그대로 유지한다. 런타임이 상태/audit 테이블에
   직접 DML할 수 없고 procedure를 통해서만 쓸 수 있다는 원칙은 유지된다.
3. **명시적으로 버리는 것**: procedure 본문 내부의 `session_user = 'ktm_feature_api_runtime'`
   / `= 'ktm_feature_dagster_runtime'` 비교(약 20여 개 procedure)와 이를 저장하는 CHECK
   제약 하나가 "API 서버가 쓴 것"과 "Dagster가 쓴 것"을 구분하던 유일한 신호였다. 통합
   이후 이 둘은 항상 같은 `session_user`(`ktm_feature_service`)로 관측되므로, 이 구분은
   영구히 사라진다. 과거에 기록된 audit row의 구분은 보존되지만(그 시점엔 실제로 다른
   계정이었으므로), 통합 이후 신규 row는 이 축을 더 이상 제공하지 않는다.
4. (ADR-101에서 superseded — `300`~`313`을 `400` 하나로 접으면서 `schema.sql`이
   head 덤프로 다시 생성됐고 `build-baseline.sh`는 삭제됐다. 아래는 당시 결정의
   기록이다.) 변경은 `alembic/baseline/schema.sql`을 재생성하지 않고, 그 위에 얹는
   새 migration (`313_...`)의 `CREATE OR REPLACE FUNCTION`/`ALTER TABLE ... DROP/ADD
   CONSTRAINT`로 적용한다 — 300 이후 모든 migration(301~312)이 이미 쓰는 패턴과 동일하다. `schema.sql`은
   `scripts/build-baseline.sh`가 격리된 0236 참조 DB에서 기계 생성하는 봉인 artifact이며,
   이번 변경은 그 artifact가 캡처한 **과거** 상태를 다시 만들 필요가 없는, 정상적인
   **전진(forward-only) 스키마 진화**다.
5. `docker/postgres-role-bootstrap.sh`(Map repo)와 `kor-travel-map-db-role-bootstrap`
   service(Manager repo `docker-compose.yml`)를 role 3개 생성에서 `ktm_feature_service` 1개
   생성으로 고친다. Manager의 `KOR_TRAVEL_MAP_MIGRATOR_PG_DSN` /
   `KOR_TRAVEL_MAP_API_RUNTIME_PG_DSN` / `KOR_TRAVEL_MAP_DAGSTER_RUNTIME_PG_DSN` 세 env var는
   단일 `KOR_TRAVEL_MAP_PG_DSN`(이미 alias로 존재)으로 수렴한다.

## 근거

세션 전반에 걸쳐 이미 결정된 우선순위 재배열(단순성이 보안보다 위)을 PinVi에 이어 Map
LOGIN 경계에도 일관되게 적용한다. procedure/trigger가 강제하는 **1차 보안 경계**(런타임이
procedure를 우회해 직접 DML할 수 없다는 것)는 이 결정의 범위 밖이며 그대로 보존된다 —
버리는 것은 그 경계 **안**에서만 존재하던 2차적 세분화(호출 주체가 API인지 Dagster인지)와,
그것을 지키기 위해 배포 표면에 떠 있던 3-계정 관리 비용이다.

## 결과

- **긍정**: Manager 배포 표면에서 role 관련 자격증명이 3조 → 1조로 줄어든다. PinVi가
  half-cutover로 5번 겪은 것과 같은 종류의 결함(한 축만 옮기고 다른 축을 놓치는 것) 표면이
  1/3로 줄어든다.
- **부정**: audit 기록에서 "API 서버가 만든 변경"과 "Dagster가 만든 변경"을 구분할 수 없게
  된다. 이 구분이 향후 운영/디버깅에 필요해지면, 절차 인자로 명시적 caller tag를 넘기는
  방식(연결 정체성이 아니라 애플리케이션 계층의 명시적 선언)으로 다시 만들어야 한다 — DB
  LOGIN 정체성에 암묵적으로 얹는 방식으로는 돌아가지 않는다.
- **후속**: `313_...` migration이 영향받는 procedure를 `CREATE OR REPLACE`하고 CHECK
  제약을 갱신한다. `src/kortravelmap/infra/{db.py,runtime_privileges.py,models.py}`의
  role별 분기와 Manager `backend/src/kor_travel_docker_manager/services/{c6c_deployment.py,
  database_runtime.py,map_application_300_candidate.py}`가 같은 PR 계열에서 뒤따른다.

## 기존 결정과의 관계

ADR-090은 **superseded by ADR-100 (LOGIN role 분리만 — schema/procedure owner 분리,
SECURITY DEFINER 강제, audit trigger 강제는 그대로 유지)**. ADR-090 §2가 규정한 절차 기반
쓰기 강제·감사 trigger·NOLOGIN role 계층은 이 ADR이 건드리지 않는 범위로 명시적으로 남는다.
