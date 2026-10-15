# journal 아카이브 — 2026-09-20 ~ 2026-09-25

> live `docs/journal.md`에서 분리한 과거 기록(docs/tasks-rule.md §8). 읽기 전용 이력이다.

## 2026-09-25 — ADR-069 code-server 분리: PinVi 활성화 + Map 전환(#1264/#397), 재구축 두 자리 수리

**PinVi.** dagster-code-server + webserver(`-w workspace.yaml`) + daemon을 n150에
처음 기동했다. Manager의 compose 주석이 이미 원인을 적어 두고 있었다 — "이
서비스가 없어서 PinVi Dagster는 한 번도 job을 실행한 적이 없다." 활성화
직후 schedule/sensor 0개 자동 기동을 확인하고 안전하게 마쳤다.

**Map.** 같은 패턴(weather/geo/transport/PinVi와 동일)으로 Map도 code-server를
분리했다 — `dagster-code-server`가 유일한 `dagster api grpc` 프로세스이고
webserver/daemon은 `workspace.yaml`로 grpc 접속만 한다. 저장소 두 곳에 걸친
작업(Map #1264, Manager #397)이라 각자 "등록" 누락이 있었다:

1. **SQLAlchemy 2.1.0이 그날 나왔다.** `sqlalchemy>=2.0` 무상한이 mypy
   --strict를 15개 무관한 ORM 조회부 파일에서 26건 깨뜨렸다 — Map #1264와
   무관한 base 자체의 환경 drift(어제 그린이던 커밋이 오늘 그대로 빨갛다).
   `>=2.0,<2.1`로 고정(#1265)해서 닫았다.
2. **C7 attestation 개수 하나.** `dagster-code-server`가 7번째 `build:`
   서비스라 `KOR_TRAVEL_MAP_GIT_COMMIT` 카운트가 6→7로 바뀌어야 했다.
3. **Manager `compose_service.py`의 별도 레지스트리.** `c6c_deployment.py`의
   candidate-protected-value allowlist(#397에서 이미 갱신)와는 **다른**
   자리 — `_validate_map_source_protected_scalar_tree`가 Map 자신의
   compose에서 `KOR_TRAVEL_MAP_DAGSTER_PROFILE`이 나올 수 있는 정확한
   `(service, env-var)` 경로를 고정 목록으로 들고 있다. `dagster-code-server`가
   webserver의 env 블록을 통째로 복사해 이 변수도 들고 왔는데 목록엔 없었다
   — 이 파일 자신의 테스트 주석이 그대로 인용하는 PinVi #356/#358과 같은
   부류다. Manager #398로 등록(+ 해당 테스트 세 개도 함께)했다.

**재구축이 두 번 막혔고, 봉인이 매번 한 단어였다.** launcher(`--json`)는
`{"status":"failed","classification":"prejournal_failure","stage":"..."}` 한
줄만 남긴다 — `/root/rebuild-diag.sh`(9월 12일 사고의 산물)를 그대로 복제해
같은 lock FD를 넘기고 `--json` 없이 재현해서만 원문을 회수했다(첫 번째는
`candidate_contract`/`ComposeCandidateContractError`, 두 번째는 `v6 execution
lifecycle`이 이전 실패를 pinset 단위가 아니라 **(pinset, Manager revision)
조합** 단위로 terminal 취급해 막은 것 — Manager를 고쳐도 같은 pinset을 다시
쓰면 여전히 막힌다. 탈출구는 새 커밋(새 pinset)뿐이라 이 저널 커밋 자체가
그 새 pinset이다.

**끝난 상태 (진행 중).** Map #1264 + Manager #397/#398 전부 머지, n150
Manager는 `6452a4c…`로 재설치·프론트엔드 재빌드까지 완료. 재구축은 이 커밋의
새 pinset으로 재시도 예정 — 결과는 다음 저널/resume 항목.

## 2026-09-24 — prod 전 사이클 GREEN. Map 400 + PinVi 단일 role 둘 다 실사용으로 처음 섰다

어제 (5)에서 남긴 "빌드 영수증 축 빠짐"부터 시작해 Manager 쪽을 세 PR로 닫았다
(#391 직접 buildx build, #392 postgres image id sha256 해석, #393 resume이
재현 안 되는 buildx를 다시 빌드하지 않고 journal을 그대로 씀). 그런데 재구축이
Map 쪽을 다 통과하고 나서 **PinVi 쪽에서 연쇄로 네 번 더 막혔다** — 전부 같은
모양이다: **ADR-46(PinVi M05 다중 role 폐기 → geo와 같은 단일 scoped role)이
인프라 쪽은 다 고쳤는데, 그 인프라가 떠받치던 자리 몇 개를 안 고쳤다.**

**1. pinvi DB owner가 frozen contract와 달랐다.** 공용 control-plane
instance(`kor-travel-shared-postgres`)의 `pinvi` DB가 `pinvi_application_runtime`이
아니라 `shared_admin` 소유였다 — db-init 스크립트가 실제로는 이미 고쳐져 있었는데
(role 먼저 만들고 `createdb -O`), **그 고쳐진 스크립트가 한 번도 다시 안
돌아서** 고치기 전 실행의 산출물이 그대로 남아 있었다(initdb 인자처럼
"생성 시점에만 적용"되는 부류의 함정). `ALTER DATABASE pinvi OWNER TO`로
직접 고쳤다 — DB가 비어 있어(테이블 0개) 데이터 리스크는 없었다.

**2. Map 쪽 `ktm_*` role 19개 정본과 실측이 어긋났다.** live에 21개가
있었는데 그중 `ktm_feature_api_runtime`/`ktm_feature_dagster_runtime`/
`ktm_feature_migrator` 셋은 rev 400 baseline 어디에도 없는 옛 역할 분리의
잔재였고, `ktm_feature_service`(baseline이 요구하는 19번째)는 없었다.
셋을 지우고(스크래치 DB 두 곳의 잔여 ACL만 `DROP OWNED BY`로 먼저 걷어냄)
하나를 만들어 정본과 맞췄다.

**3. PinVi 0101 migration의 fresh 경로가 요구하는 catalog-lock fence 함수가
없었다.** `pinvi_internal.acquire_fresh_0101_database_fence()`는
`pg_authid`/`pg_database`를 ACCESS EXCLUSIVE로 잠그는 SECURITY DEFINER
함수다 — scoped app role은 자기 database를 소유해도 이 catalog 잠금 권한은
가질 수 없다(catalog는 database 소유물이 아니라 cluster 전역이다). ADR-46이
이 함수를 세우던 `bootstrap-pinvi-runtime-role.sh`를 통째로 버리면서 이 한
함수도 같이 버렸는데, 나머지 아홉과 달리 이건 role 분리와 무관하게 fresh
install마다 여전히 필요했다. Manager에 `_ensure_pinvi_fresh_migration_fence`를
추가해 매 rebuild마다 다시 세운다(destructive reset이 매번
`pinvi_internal` schema를 지운다) — kor-travel-docker-manager #394.

**4. PinVi 0101 자신이 자기 migrator 권한을 스스로 거둬가고 있었다.**
`_grant_fresh_runtime_app_privileges` 직후 `_revoke_runtime_alembic_version_privileges`를
무조건 불렀는데, 단일 role 배포에서는 그 대상이 **지금 이 migration을 돌리는
바로 그 connection**이다 — alembic이 트랜잭션 끝에 내부적으로 같은 role로
`alembic_version`을 UPDATE해서 head를 기록하는데 그 직전에 자기 권한을
잘라 "permission denied for table alembic_version"으로 0100+0101 전체가
롤백됐다. legacy 다중 role 배포(managed-but-fresh, `migration_owner`/
`migrator_login`이 설정된 경우)는 여전히 필요해서 — 완전히 지웠다가
`test_0101_can_use_a_separate_nonruntime_migration_owner`가 깨져서 한 번
더 좁혔다 — 두 role이 하나도 안 설정된 진짜 단일 role 경우에만 건너뛴다
(PinVi #564).

**소스 원장(P본)에는 이미 답이 있었다.** #564의 진짜 수정은 PinVi
`origin/main`에 6주 전(8월 5일 pin 대비 9월 21일 merge)에 이미 올라 있었다
— pin이 낡아서 못 쓰고 있었을 뿐이다. `_activate_m05_migration_owner`
자체에 "ADR-46/070: 공용 control-plane은 M05 owner/migrator 분리를
완전히 버린다"는 주석과 함께 단일 role 우회 경로가 이미 있었다. 매번 막힌
자리를 직접 replay(`alembic upgrade head`를 sealed CLI 밖에서 직접
호출)로 실측하지 않았다면 이 넷 중 어느 것도 진짜 원인에 닿지 못했을
것이다 — CLI는 매번 `{"error_code":"...","phase":"..."}` 한 줄만 준다.

**끝난 상태.** pinset `fa6f624e5b06…`(map `f5703bc6…` + pinvi `b60cc8cd…`),
map schema head `400`, dagster head `29b539ebc72a`, pinvi head
`20260917_0102`, 일곱 서비스(map-api/ui/dagster/dagster-daemon,
pinvi-api/web/dagster) 전부 healthy. `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를
`312_route_geometry_sidecar` → `400`으로 재구축 **후에** 바꿨다. Manager는
`#394`까지 trusted install로 반영하고 `pin rebind-execution`으로
provenance를 맞췄다.

**PR 목록.** kor-travel-docker-manager #391/#392/#393/#394, pinvi #563(선행,
과거 세션)/#564.

## 2026-09-23 (5) — prod 사이클을 돌렸고, 내 ADR-101 작업이 한 축을 빠뜨린 것을 알았다

두 PR을 머지한 뒤 전 사이클을 기동했다. 세 가지를 배웠고, 셋째가 남은 일이다.

**1. 설치본이 여섯 머지 뒤처져 있었다.** chain17은 Manager revision을 `/opt`의
설치 매니페스트에서 읽는다. 거기 있던 것은 `2dc633dd`(#381 머지 시점)로 ADR-100도
ADR-101도 없었다. 그대로 돌렸다면 옛 compose가 새 Map 이미지에서 삭제된 실행파일을
불렀을 것이다. 사용자 1회 허가를 받아 trusted installer로 `e4d4fa55`를 설치했다.

**2. `.env`에 ADR-100 자격증명 쌍이 없었다.** 재구축이 `prejournal_failure` /
stage `prebuild_snapshot`으로 죽었고 그 한 단어가 남긴 전부였다. 원인은
`KOR_TRAVEL_MAP_SERVICE_PASSWORD`와 `KOR_TRAVEL_MAP_PG_DSN` 부재 — 새 compose가
`${X:?...}`로 요구하므로 해석 단계에서 막힌 것이다.

왜 비어 있었나가 핵심이다. M05를 폐기하면서 **Manager가 `.env`에 role 자격증명을
심던 경로가 사라졌다**(`compose_service.py`의 `prewrite_admission` 주석). 그 전까지는
Manager가 넣었으므로 운영자가 신경 쓸 일이 아니었고, 사라진 뒤에도 runbook이 그
책임을 이어받지 못했다. 이제 적었다(Manager #390).

**3. 내 ADR-101 Manager 작업이 빌드 영수증 축을 빠뜨렸다.** 자격증명을 넣자
재구축이 다음 단계인 `application_builder`에서 죽었다. ADR-101은 Map에서
`scripts/build-application-300-paired-candidate.sh`를 지웠는데(ADR 문서가 명시한다)
Manager의 소비자는 그대로다. 같은 뿌리에서 `DagsterStorageCandidate`도
`paired_candidate_build_receipt_sha256`을 계속 싣는데 Map은 이제 그 필드를 받지
않는다.

내가 범위로 잡았던 (C)(D)(E)는 영수증·fence·phase 기계였고, **빌드 영수증은 다른
축인데 같은 ADR이 지운 것**이었다. 지우는 쪽(Map)과 읽는 쪽(Manager)을 파일 단위로
대조했어야 했다 — ADR 문서 17행이 지운 파일을 이미 열거하고 있었다.

prod는 더 나빠지지 않았다: 두 실패 모두 저널 전이라 후보가 해제됐고 새 pinset에
journal이 없다. 회전은 끝났으므로 재시도는 rebuild 단계부터다.

## 2026-09-23 (4) — 두 ADR을 한 사이클에 머지했다

순서가 계약이었다: **Manager 먼저**(#389 → `e4d4fa5`), 그다음 Map(#1259 →
`eb4882aa4`). Manager의 `docker-compose.yml`이 Map 이미지에서 지워진 실행파일 둘을
절대경로로 부르고 있었고, 그 자리가 fresh DB 복구 경로다 — Map만 머지하면 지금
outage의 복구 경로가 깨진 채로 남는다.

Map PR은 최신 커밋 기준 9개 체크 전부 SUCCESS였다(PostGIS 통합 포함). Manager는 두
체크 전부 SUCCESS.

합계 **−45,343줄**(Map 218 files −39,935, Manager 15 files −5,408).

**남은 것은 prod 복구 사이클 하나다.** 직전 pinset `3705983b`의 journal은
`cancel_probe_finalized`에서 영구 고착이고 탈출구는 새 커밋인데, 이 두 머지가 바로
그것이다.

## 2026-09-23 (3) — 봉인의 건너편을 접었다: 아홉 phase가 한 번의 관측으로

ADR-101이 Map에서 지운 두 실행파일의 **소비자**는 Manager였다. 그 쪽에서 무엇이
사라졌는지 세어 보니, Map에서 지운 것보다 컸다 — 13 files, −4,922줄.

**무엇이 있었는가.** Manager는 삭제된 두 one-shot이 stdout으로 뱉는 JSON 영수증을
파싱했고, 그들에게 root 소유 writer fence를 깔아 주었고, 그 과정을 아홉 개의 durable
phase(`fresh_root_plan_ready` … `application_permit_ready`)로 쪼갰다. 각 phase는
operation plan을 들고 있었고, 그 plan은 "어느 저널 세대에서 썼는가"를 sha256으로
결박했다. 중간에 죽으면 `recover` / `probe-missing` 인자로 같은 실행파일을 다시 불러
"영수증이 있는가 / 없는가"를 되물었다.

**그 전부가 한 가지를 위한 것이었다** — 영수증 파일을 안전하게 재개하기. 파일이
사라지면서 결박할 대상도 사라졌다.

**대신 들어온 것.** one-shot이 끝나면 Manager가 **자기 admin 자격으로**
`public.alembic_version`을 읽는다. 값이 후보 head와 다르면 거부하고, 같으면 저널에
`application_schema_head`로 적는다. 옛 경로에서 "스키마가 올라갔다"의 근거는 결국
"쉘 명령이 0으로 끝났다"였고, 영수증은 그 명령 자신이 쓴 것이라 독립 증거가 아니었다.

**잃지 않은 것.** "이미 끝난 것을 다시 돌리지 않는다"는 여전히 계약이다. 다만 성질이
바뀌었다 — 옛 계약은 "durable intent 이후 **절대** 재실행하지 않는다"였고, 그것은
재실행이 **위험했기 때문에** 필요했다. `alembic upgrade head`는 이미 head면 무연산이고
`runtime_privileges`는 재조정이므로 지금은 안전하다. 그래도 `application_schema_ready`
에서 재개할 때 one-shot 명령이 호출 목록에 **없어야** 한다는 단언은 남겼다. 없으면
phase 자체가 의미를 잃는다.

**두 번 밟은 사고, 둘 다 조용한 종류.**

1. `volumes:` 키만 지웠더니 그 아래 bind mount 세 줄이 앞 `command:` 목록에 흡수돼
   **Prometheus CLI 플래그로 둔갑**했다. YAML은 유효하고 `safe_load`는 통과한다.
   찾은 방법은 단언이 아니라 비교였다 — HEAD 문서와 지금 문서를 service×key로 대조해
   "prometheus.volumes: 3 → None"을 뽑았다.
2. 앵커 구간으로 헬퍼 12개를 지우며 같은 구간에 있던 `_discard_application_300_receipt`
   (빌드 영수증 — 다른 축이다)를 함께 지웠다. 클래스 안에서 메서드 하나를 지우려고 끝
   경계를 `\n\n\n`으로 잡았다가 뒤따르는 세 메서드를 함께 날린 것도 같은 형태다.
   AST로 HEAD와 최상위 이름 집합을 대조하는 검사를 따로 돌려 잡았다.

**이 저장소가 함께 바뀐 자리.** `scripts/lib/c7_prod_attestation.py`가 prod 저널을
Manager와 같은 강도로 재검증하므로 증거 모양의 사본을 들고 있었다 — 새 모양으로 옮겼다.
`scripts/run-tvn34c-n150-fresh-live-e2e.sh`는 final permit 마운트의 존재를 요구하다가
이제 부재를 요구한다.

**게이트.** Manager backend 1,947 passed (n150 CI-parity), ruff 0.16.4 clean. 남은
둘은 이 변경과 무관하다 — `test_compose_ensure_build_command`는 손대지 않은 main에서도
빨갛고, `test_canonical_compose_readiness_matches_real_runtime`은 30초 docker compose
timeout이다(직전 회차에서 같은 코드로 통과).

## 2026-09-23 (2) — 트리거 85개를 지우려다, 내 실측이 정반대로 읽힌 것을 알았다

전수조사가 187개 트리거 중 85개를 "막는 동작을 할 수 있는 principal이 없다"며 삭제
후보로 올렸다. 나는 그 근거를 카탈로그로 확인했다고 보고했다. **확인이 아니라 오독이었다.**
적대 검증이 여섯 그룹을 전부 반박했다 — 삭제 가능한 트리거는 **0개**다.

**무엇을 쟀는가.** `aclexplode`로 124개 표의 TRUNCATE grantee를 뽑았더니
`ktm_feature_schema_owner` 하나였다. 그건 그 124개 표 **전부의 소유자**다. 나는 이것을
"소유자 기본 항목이지 부여가 아니다 → 아무도 TRUNCATE를 못 한다"로 읽었다.

**정반대다.** 소유자야말로 TRUNCATE를 할 수 있는 주체이고, **소유자에게선 REVOKE가
불가능하다.** 그래서 REVOKE가 아니라 트리거를 쓴 것이다. 그리고 그 소유자는 닿을 수 있는
자리에 있다 — `docker/postgres-role-bootstrap.sh:683`이 유일한 운영 LOGIN
`ktm_feature_service`에게 `SET TRUE`를 주고, `alembic/env.py`는 **모든 마이그레이션에서**
`SET ROLE ktm_feature_schema_owner`를 켠다. revision 400 자신이 그 세션 안에서 돈다.

**증거는 CI에 이미 있었다.** `tests/integration/_db_cleanup.py`가 `_no_truncate` 트리거를
**끄고 나서** TRUNCATE를 실행하고, 그게 **성공한다.** 권한이 없다면 트리거를 꺼도 똑같이
`permission denied`로 죽어야 한다. 성공한다는 것이 곧 "principal이 TRUNCATE를 갖고 있고
트리거가 유일한 방벽"이라는 실행 가능한 증명이다. 나는 그 파일을 blast-radius 목록으로만
읽고, **그것이 답이라는 것**을 보지 못했다.

**저장소가 이미 답해 뒀다.** `tests/integration/test_tvn41s_material_fences.py:147`:
"UPDATE fence만 시험하면 나중에 TRUNCATE trigger 둘을 떨어뜨려도 `pytest -q`와
`alembic check`가 모두 초록이다(적대 리뷰 지적)." 그 테스트는 정확히 이번 삭제를 잡으려고
쓰였다. 그리고 `ENABLE ALWAYS` 다섯 줄은 `session_replication_role = replica` 한 줄로
우회하는 행위자가 **있다**는 전제 위에서만 뜻이 있다 — 아무도 못 한다면 쓸 이유가 없는
구문이다.

**교훈은 이미 쓰여 있던 것이다** — 탐지기는 효과에, 그리고 맞는 층에 결박한다. 나는
카탈로그 층(`aclexplode`)에 결박했고, 그 층은 소유자 암묵 권한도 `SET ROLE` 도달성도
superuser 우회도 **구조적으로 보지 못한다.** 효과 층(트리거를 끄면 TRUNCATE가 되는가)에
결박했다면 첫 질문에서 끝났다.

지울 것이 없다는 것은 나쁜 소식이 아니다. 이 트리거들은 과잉 구현이 아니라 소유자를
제약할 수 있는 **유일한** 수단이고, 지웠다면 `TRUNCATE feature.features CASCADE`가
거부에서 전량 삭제로 **ACL 한 글자 안 바뀐 채** 조용히 바뀌었을 것이다.

## 2026-09-23 — 열네 revision을 하나로 접고, 그 체인을 지키던 장치를 같이 걷어냈다

활성 Alembic graph가 revision **하나**가 됐다. `400_schema_baseline.py`가 head
`pg_dump`와 seed를 적용하고 `down_revision = None`이다. revision 14개와 사이드카
111개가 사라졌고, 그 체인을 감시하던 장치가 함께 사라졌다 — 266개 파일,
**-54,018 / +2,349**.

**접을 수 있었던 이유.** 긴 migration 체인이 사는 값은 하나다 — 돌고 있는 DB를 그
자리에서 앞으로 옮길 수 있다는 것. 이 저장소는 돌고 있지 않고 데이터 보존도 요구하지
않으므로 그 값에 사는 사람이 없는데, 비용은 계속 쌓였다. 같은 사실(role graph·ACL·
procedure 본문)이 열네 revision에 흩어져 어긋날 자리가 열네 군데였다.
`runtime_privileges.py`의 조건부 ACL 세 덩어리는 전부 "이 조정기가 두 스키마 상태에서
돈다"는 사정 하나에서 나왔다.

**봉인.** receipt 사슬은 `0236 → 300` 이관이 원본을 건드리지 않았음을 증명하려고
만들었다. 이관이 끝나 증명할 원본이 없고, 남은 것은 빌드 시점 해시와 배포 시점 해시가
같은지 확인하는 파일 다발이었다. 그것이 막은 사고는 없다. 막은 것은 있다 — seed의
`route.geom` 행이 312가 지운 컬럼을 가리키는데 봉인 때문에 **고칠 수 없었다.**

**permit이 지키던 성질은 세 술어로 옮겼다.** `application-schema-final-permit.py`
721줄, root 소유 mount, 서명 파일이 결국 지킨 것은 하나다 — 런타임이 자기 이미지와
다른 스키마의 DB에 붙지 않는다. 런타임 privilege preflight가 이제 그것을 잰다:
적용된 head가 이미지의 head와 같은가, `public.alembic_version`을 읽을 수 있는가,
그리고 **쓸 수는 없는가**(셋째가 없으면 스키마 대신 head를 고쳐 첫째를 통과할 수
있다). 셋을 따로따로 뒤집어 각각 빨개지는 것을 확인했다.

**사이드카는 손으로 만들지 않았다.** 빈 DB를 `313`까지 올려 두 번 떠서 같은지 본
다음 정규화했다. 정규화는 정확히 네 가지 — 매 덤프마다 바뀌는 토큰·버전 주석,
`search_path` 고정(env.py가 트랜잭션 안에서 세운다), `CREATE SCHEMA IF NOT EXISTS`,
그리고 **ACL 블록마다 소유자로 role 전환.** 마지막 것이 load-bearing이다: GRANT는
소유자만 낼 수 있고 ADR-090 role은 NOINHERIT이며, 소유자 아닌 GRANT는 오류가 아니라
경고 후 무시다 — exit 0이 적용의 증거가 되지 못한다.

같은 런에서 head 오라클도 다시 떴는데 커밋돼 있던 파일과 **바이트 동일**했다. 덤프
파이프라인이 기존 오라클을 재현한다는 확인이다.

**대상이 빈 검사 다섯.** role을 바꿔 가며 DDL을 내는 migration을 감시하는 게이트들은
덤프 하나를 적용하는 revision 앞에서 대상이 0이 된다. 하한을 낮추지 않고 — 그러면
"본 것에 하한을 건다"가 무너진다 — 이유와 함께 skip하고 두 번째 revision이 붙는 순간
다시 활성화되게 했다. `test_receipt_head_check_covers_the_graph_head.py`가 이미 쓰던
형태다.

유도형 검사 둘은 **더 나은 오라클로** 옮겼다. purge 제약 분류와 `match_basis` CHECK는
이제 migration의 중간 문자열이 아니라 head 덤프를 읽는다 — DB가 실제로 들고 있는
것에 한 칸 가깝다.

`_OPTIONAL_ROUTINES`는 비웠다. `test_db_procedure_signatures_exist_in_head.py`가
"baseline root에 없는 인벤토리 루틴: []"로 실측했기 때문이다. 이름을 남겨 두면 루틴이
**정말로** 사라지는 날 조용히 건너뛴다.

정본은 ADR-101.

## 2026-09-20 — geometry 한 컬럼이 이사했는데, 그것을 가리키던 자리가 열여섯 곳 남아 있었다

`312_route_geometry_sidecar`가 `feature.feature_routes.geom`을
`feature.feature_route_geometries`로 옮겼다(ADR-099 2단계). 컬럼 하나를 옮기는
변경인데, **그 컬럼을 가리키던 선언이 옛 자리에 얼어 있는 것**이 이 작업의 거의
전부였다. 터진 순서대로:

1. `public_features` 뷰가 컬럼을 참조해 `DROP COLUMN`이 막혔다 — 뷰 교체를 앞으로.
2. `sync_subtype_public_ready`를 스키마 소유자 창에서 바꾸려다
   `must be owner of function`. 롤이 NOINHERIT라 멤버십만으로는 안 된다.
3. 권한 조정기의 fail-close fence — 선언 없는 relation은 거부한다. 300에서도 도는
   조정기라 새 relation의 GRANT는 `to_regclass` 조건부여야 했다.
4. ORM 메타데이터 drift — 표를 만들었으면 모델도 만들어야 한다.
5. plpgsql 프로시저 **셋**이 여전히 `feature_routes.geom`에 쓴다. plpgsql 본문은
   `pg_depend`를 만들지 않아 `DROP COLUMN`이 막지 않는다 — **첫 route 적재**에서
   42703으로 죽는다(적대 리뷰가 blocker로 잡았다).
6. 새 relation에 `derive_subtype_public_ready` 트리거가 없어 `public_ready`가
   영원히 false. route가 **오류 없이** 공개 bbox에서 0건이 된다. provider 적재는
   core 3축을 바꾸는 UPDATE를 내지 않으므로 AFTER 트리거만으로는 안 채워진다.
7. 프로시저 사이드카를 `ALTER PROCEDURE`에서 잘랐는데 그 문자열이 `DO` 블록
   **안에** 있어 달러 인용이 깨졌다 — 통합 **1,096건 오류**. 달러 인용 인식
   분할기로 교체.
8. 세 프로시저는 `ktm_feature_state_procedure_owner` 소유의 SECURITY DEFINER인데
   그 롤의 geometry 권한이 옛 자리에 있었다 — `permission denied for table
   feature_route_geometries`.
9. GiST 인덱스 이름·적재 SQL·권한 단언에 결박된 검사 **여덟 자리**.
10. `test_runtime_subtype_acl_excludes_public_ready`가 없는 컬럼의 권한을 물어
    42703. 관계 이름이 SQL 파라미터 뒤에 숨어 있어 이름 검색으로는 안 보였다.
11. 내 사이드카 테스트가 COMMIT한 행을 안 치워 다른 모듈 셋의 "빈 기준선" 전제를
    깼다(`test_status_repo`, `test_sibling_dedup`).
12. `current_theme_candidate_snapshot`도 `to_jsonb(route)`를 읽는다 — 봉인만
    메우면 `candidate_input_hash`가 geometry 변경을 **조용히** 못 본다.
13. 그 함수가 SECURITY DEFINER로 도는 `ktm_curation_command_owner`의 SELECT.
14. override field-path 레지스트리가 없는 컬럼을 가리키고 CHECK가 새 relation을
    금지. 같은 CHECK를 ORM도 선언하고 있어 한 쪽만 넓히니 카탈로그 대조가 잡았다.
15. 무결성 관측 두 축이 새 relation을 안 셌다. `geom NOT NULL`이 COMMIT 시점
    DEFERRABLE FK로 약해졌으므로 복구 세션이 그 창을 지난다.
16. head 오라클이 낡아, 그것을 정본으로 읽는 lint **열한 개**가 "루틴이
    `feature_routes.geom`을 쓴다"는 없는 세계를 보고 있었다.

**그래서 이름을 옮기는 대신 모델에서 유도하게 바꿨다.**
`GEOMETRY_RELATIONS`/`EXTERNAL_GEOMETRY_KINDS`가 단일 정본이고, 검사·관측·권한·
파라미터가 거기서 나온다. 다음 이사(area)는 dict 값 하나를 바꾸는 일이어야 한다.

### 고치려다 배포 허가 사슬에 부딪힌 것 하나

override field-path 레지스트리를 새 relation으로 옮겼더니 `application_300_fresh_*`
두 건이 **결정적으로** 깨졌다 — `fresh finalize seed receipt does not match
baseline`. `ops.feature_override_field_paths`의 전 행이 rev 300 seed 영수증으로
봉인돼 있고 배포 허가 사슬 셋이 그 해시를 게이트로 쓴다. `target_relation`은 그
해시에 들어가는 컬럼이다.

catalog 쪽은 `_sealed_destination_catalog`가 같은 문제를 이미 겪고 "head 너머에서는
봉인값이 기대값이 아니다"로 풀어 두었는데, seed 쪽에는 그 처리가 없다. 봉인을 다시
뜨려면 살아 있는 0236 컨테이너가 필요하고 그건 막혀 있다.

`minor` 발견 하나 때문에 배포 허가 사슬을 재설계하는 것은 맞바꿈이 나쁘다. 되돌리고
`T-VN-SEED-RECEIPT-HEADAWARE`로 등록했다. 다만 간극을 **예외 목록이 아니라 단언으로**
못 박았다 — 봉인이 풀려 레지스트리를 옮길 수 있게 되면 그 검사가 먼저 빨개진다.
예외는 조용히 늘어나지만 단언은 조용히 늘어나지 않는다.

### 검사도 같은 병을 앓고 있었다

역할 창 lint 셋이 전부 `_migration("309")`에 결박돼 312의 창 넷을 한 문장도 보지
않았고, 롤 유지 lint는 AST만 봐서 312를 **3문장**으로 읽었다(실제 42문장). 둘 다
번호·형태 대신 "있는 것 전부"를 보게 넓혔다.

넓히니 302·304가 거짓 양성으로 올라왔다 — **소유자는 문장열 위에서 움직인다.**
새 `CREATE`는 만든 롤을 소유자로 만들고, `SET ROLE` 이전 구간은 관리 롤로 돈다.
그 모델을 옮겨 적으니 예외 목록 없이 정확해졌다.

그리고 돌연변이 실험이 하나를 더 찾았다 — 롤 유지 lint가 **주석 붙은 `SET ROLE`을
못 봤다.** 문장 분할기는 `;`만 보고 자르므로 주석이 문장 앞에 붙어 오고, 사이드카의
**여는** 창은 거의 언제나 설명 블록 뒤에 온다. 검사는 닫는 쪽만 보고 있었다.
이웃 모듈은 같은 함정을 `_sql_head`로 이미 막고 있었는데, 그 교훈이 옆 파일로
건너오지 않았다.
