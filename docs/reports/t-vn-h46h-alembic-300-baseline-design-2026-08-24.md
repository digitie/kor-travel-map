# T-VN-H46H — Alembic `300` baseline과 fresh-only 재구축 설계

작성일: 2026-08-24
최종 결정 갱신: 2026-08-25

## 결정

현재 Map application schema를 Alembic active graph의 유일한 root/head `300`으로
재정본화한다. `0200_schema_baseline`부터 `0236_tvn41s_compaction_drained`까지의 과거
migration source는 실행 graph와 production image 밖의 byte-pinned retired archive로만
보존한다.

기존 DB의 `0236 → 300` stamp나 in-place upgrade는 지원하지 않는다. n150을 포함한 배포
환경은 Docker Manager의 승인된 `ktdctl pinvi-pair rebuild-pinned --confirm` transaction으로
application DB, Dagster metadata DB, PinVi DB를 파기·재생성하고 고정 candidate를 fresh-only로
적용한다. 과거 revision downgrade·restore·replay와 수동 `public.alembic_version` 편집도
지원하지 않는다.

이 문서는 2026-08-24 초안의 비파기 handoff 결정을 대체한다. 과거 handoff source와 rehearsal은
감사 자료일 뿐 실행 authority가 아니며 current candidate image에 executable로 포함하지 않는다.

## 범위

- application active Alembic graph를 단일 root/head `300`으로 축소한다.
- final role·membership·ACL·extension·schema·seed 계약을 fresh bootstrap에 봉인한다.
- API와 Dagster candidate를 동일 Map commit/tree 및 immutable image ID에 결박한다.
- application root/finalize와 Dagster storage migration의 응답 유실을 DB-atomic receipt로
  수렴시킨다.
- Docker Manager manifest v6/journal v8과 Map C7 host attestation v4를 exact 결선한다.
- n150에서 고정 release candidate를 destructive fresh rebuild하고 login과 live UI E2E를
  검증한다.

## 비범위

- 기존 DB의 in-place stamp·upgrade
- 과거 revision으로 downgrade 또는 stamp-back
- dump/PITR/volume 교체를 이용한 rollback이나 release gate
- n150 DB나 backup clone을 baseline 생성 source로 사용하는 행위
- 일반 API/Dagster startup의 schema 자동 수리
- Map 작업 중인 변경 가능한 PinVi source를 candidate에 포함하는 행위

## baseline 생성과 정적 계약

baseline은 provider 적재, live fixture, acceptance 잔재가 없는 격리 fresh `0236` reference에서
한 번 생성한다. 생성 결과는 review 가능한 SQL과 canonical receipt SQL로 저장하며 런타임이
reference DB에 의존하지 않게 한다.

candidate에는 다음을 포함한다.

- `alembic/versions/300_schema_baseline.py`
- application catalog, seed, source/destination Alembic facet, runtime invariant SQL
- final role bootstrap과 exact application contract
- application fresh root/finalize one-shot
- mutation entrypoint가 없는 root-owned `0444` DB contract module

candidate에는 다음을 포함하지 않는다.

- `ktm-application-schema-handoff`
- `0236 → 300` transition writer
- source oracle나 handoff rehearsal을 production proof authority로 실행하는 경로
- 과거 Alembic migration graph

paired builder는 sealed Git archive에서 API와 Dagster image를 함께 만들고, Map commit/tree,
두 image ID, PostgreSQL image ID, Dagster config·launch contract, application contract, build
receipt digest를 exact candidate evidence로 발행한다. 현재 checkout의 mutable 파일이나
caller가 만든 대체 receipt는 허용하지 않는다.

## destructive fresh transaction

Docker Manager는 host-global mutation lock과 immutable candidate attestation 뒤 다음 순서로만
진행한다.

1. 외부 Geo·Concierge·RustFS prerequisite를 mutation 전에 읽기 전용으로 확인한다.
2. stale one-shot container를 제거하고 부재를 확인한다.
3. Map/PinVi PostgreSQL image와 candidate source/image를 고정한다.
4. 세 DB를 파기·재생성한다.
5. application DB를 만들고 final role bootstrap을 적용한다.
6. restricted migrator로 fresh root `300`을 한 transaction에 적용하고 DB-atomic operation
   receipt를 확정한다.
7. 별도 fence의 finalize가 source catalog를 검증하고 final ACL·destination catalog·receipt를
   한 transaction에서 확정한다.
8. application final permit과 Dagster metadata permit을 root-owned read-only mount로 발행한다.
9. Dagster 세 storage를 session advisory lock 아래 migrate/reindex하고 exact catalog와 v3
   receipt를 확정한다.
10. Map runtime, PinVi schema/API, cancel probe, 일곱 runtime을 명시 순서와 `--no-deps`로
    기동·검증한다.
11. manifest v6과 journal v8을 commit한다.

application root와 finalize의 operation ID는 rebuild journal transaction ID 및 writer-fence
transaction ID와 분리한다. 응답 유실 시 같은 operation ID의 append-only DB receipt를 먼저
read-only recover한다. finalize receipt가 없을 때는 같은 DB advisory lock 뒤 exact pre-state를
증명하는 typed `probe-missing`이 성공한 경우에만 fence를 갱신해 재실행한다. raw head `300`,
stderr 문자열 또는 단순 exit code만으로 성공·재실행을 추론하지 않는다.

Dagster는 receipt 없는 final head를 성공으로 승격하지 않는다. 세 storage의 exact table·column·
index·필수 migration marker를 대조하며 장기 runtime은 `should_autocreate_tables: false`로
무영수증 DDL을 수행하지 않는다.

## runtime과 attestation

API entrypoint는 raw `300`과 exact contract만 정상 startup으로 허용한다. `0236`이나 알 수 없는
revision은 어떤 stamp/upgrade도 실행하지 않고 승인된 destructive fresh rebuild만 안내한다.

manifest v6은 일곱 runtime image, Map/PinVi source revision, 세 schema head, pinset, application
`300` paired candidate evidence를 고정한다. journal v8은 candidate 전체, application create/final
DB identity, root/finalize operation plan과 result, application/metadata permit, Dagster metadata
DB/role identity, cancel probe와 committed phase를 고정한다. 구 v5/v7 문서는 호환 입력이 아니다.

C7 verifier는 root-owned manifest/journal/host attestation을 읽고 다음을 mutation 전에 exact
대조한다.

- manifest candidate와 journal candidate의 전체 동등
- candidate evidence의 generation/journal 중복 결박
- application/Dagster DB identity와 canonical digest
- root/finalize result 및 application/metadata permit digest
- 세 schema head와 pinset
- 일곱 running container의 immutable image ID, command, environment, OCI source revision
- Map UI admin password hash의 비어 있지 않은 runtime 전달
- Map API 전용 cursor secret과 다른 credential의 분리
- finalized cancel probe

## n150 완료 조건

Map과 Manager PR은 다음 조건을 모두 만족하기 전 Draft를 유지한다.

1. 최신 `main`에 rebase하고 두 저장소 CI가 green이다.
2. 두 전문 적대 리뷰어가 exact final commit pair에서 P0/P1=0을 확인한다.
3. 고정 Map/PinVi release candidate로 `rebuild-pinned --confirm`을 실행한다.
4. manifest v6/journal v8, 세 DB identity/head, 일곱 image를 exact 검증한다.
5. UI login POST가 `200 + Set-Cookie`, 잘못된 credential이 `401`임을 확인한다.
6. protected route, logout 뒤 재차단, Admin Feature main/recovery, PinVi paired acceptance와
   WebSocket 안정성을 live UI E2E로 확인한다.
7. API-owned pending request, fixture row/FK, transient container, raw browser artifact와
   credential residue가 0이다.
8. redacted hash/count evidence만 남기고 비밀·URL·host identity를 커밋하지 않는다.

백업·복구점은 위 조건이 아니며 rollback 경로를 제공하지 않는다. 실패 시 DB를 과거 revision으로
되돌리지 않고 새 forward-fix candidate를 만들어 transaction을 다시 수행한다.
