# A4 좁은 Geo stamp SD — 구현 전 SQL 계약

2026-10-25. 정본 d47639e0f51a2539c8edcf02c52aa6ff5263f7ec, 설계 문서1393의40de 기준이다.
제품/DDL/DB/운영 변경0. 구현은 root/W SQL 설계 검토 뒤 작은 PR로 분리한다. J 전용 actual PG
회귀와 T SQL/infra의 소유권을 분리한다. 기존1392/1393 WT는 동결한다.

## 결론: table ACL 회수와 SD 진입점, stamp만 SI 경계

새 private auth 표나 GUC/임시표/session.info/호출 스택 증거는 만들지 않는다. 기존 applying
attempt/TX/manifest는 범위 증거이지만 **SQL이 어느 SD에서 왔는지**를 증명하지 못한다.
따라서 stamp table의 runtime INSERT/UPDATE를 회수하고 SELECT만 남긴다. SQL I/U는 기존
NOLOGIN `ktm_feature_state_procedure_owner` 소유의 검증된 SD 함수만 수행하도록 한다.
이 owner에 stamp SELECT/INSERT/UPDATE만 명시 부여한다. DELETE/TRUNCATE/ownership/새 role/
새 context table/원시 ops 권한의 runtime grant는 추가하지 않는다.

기존 공유 `reject_unsupported_active_scalar_mutation`는 SECURITY DEFINER다. 그 안의
current_user는 항상 trigger owner이므로 caller 판별에 쓸 수 없다. 그 함수 전체의 SECURITY
속성이나 다른 table의 branch는 바꾸지 않는다. stamp에만 아래 event 경계를 적용한다.

- 기존 stamp `trg_scalar_unsupported`: DELETE 이벤트만 기존 SD 함수를 계속 사용한다.
  active stamp DELETE23514/nonactive FK CASCADE 허용이라는 기존 의미를 유지한다.
- 새 `trg_stamp_writer_entry`: INSERT/UPDATE의 SECURITY INVOKER trigger 함수다.
  current_user가 정확 state procedure owner가 아니면42501, 그 외 NEW 반환뿐이다.
  정책 table을 읽지 않고 새 private policy SELECT 권한을 runtime에 열지 않는다.
- SI role 검사는 table ACL·NOLOGIN owner·현재 effective role·모든 해당 owner SD inventory가
  닫혔다는 조건의 보조 경계다. 그 자체가 입력/manifest 승인은 아니고 승인은 SD 본문이 한다.
  canonical service 로그인에는 schemaowner→stateowner SET TRUE 경로가 실제 있다.
  current_user가 service/runtime 그대로인 일반 SQL과, 같은 로그인이 명시 SET ROLE로 owner가 된
  고권한 SQL을 구분한다. 동일 session_user의 호출 의도로 runtime/migrator를 구별하지 않는다.
  명시 owner 역할에서는 직접 stamp DML도 가능한 기존 관리 권한 경계이며 이 설계가 이를
  차단한다고 주장하지 않는다. bootstrap 역할/상속 권한 변경은 범위 밖이고 superuser/명시
  고권한 운영 SQL을 차단하는 sandbox도 아니다.

기존 DELETE 보호를 SI 함수에서 private policy 조회로 복제하면 owner별 EXECUTE 의존권한이
늘거나 FK cascade 경로를 막는다. event 분리는 그 확대 없이 기존 삭제 검증을 그대로 남긴다.
대신 active 설치 trigger는 기존50개에서51개가 된다. I/U나 DELETE 각 행에서 unsupported/entry
검사는 여전히1회씩이다. epoch statement/deferred projection/PK/FK/CHECK는 유지한다.
412 installer의 exact 설치 개수·목록·부분설치 거부를51개로 함께 갱신하고, migration은 현재
0개(OFF) 또는 검증된50개(기존 active)만 허용해 active면 원자 재배선한다. OFF에서는 새 policy
trigger를 설치하지 않고 첫 cutover가 새51개 정본을 설치한다. 수동 trigger disable은 금지다.

## 실제 writer·권한 inventory와 새로 바뀌는 면

J의 `/tmp/map-a4-stamp-acl-independent-inventory.md` 최종SHA
298911cf1b73ef6704d6b1d620d04400d0fb3613ee601bf4c5669a2f4c2632da와 직접 정적 대조했다.

| 현재 실제 경로 | 현재 의미 | 새 계약 |
| --- | --- | --- |
| stamp repo `_UPSERT_STAMPS_SQL`→`upsert_stamps` | unique mapping을 INSERT ON CONFLICT, now(), 같은 TX | Python 서명 유지·SD legacy EX bulk 호출로 SQL만 이동 |
| `feature_repo.load_bundle:3584` | 단일 stamp | 같은 SD를 소비 |
| `feature_repo.load_bundles:3749` | chunk aggregate stamp | 같은 SD/같은 TX, 전체 count 유지 |
| 기존 SD 직접 stamp writer | head 전수에서0 | 새 legacy EX/SH 함수만 추가 |
| `purge_manual_feature` 등 Feature 삭제 | FK CASCADE로 stamp 삭제 가능 | 기존 DELETE guard/권한·cascade 보존 |
| Geo release/reuse/stale/coverage | SELECT | 변경0 |
| public field registry 동적 SD | target_relation에 stamp 없음 | stamp 우회 통로로 열지 않음 |

현재 runtime ACL은 SELECT/INSERT/UPDATE다. 모든 직접 I/U가 이미 ACL로 차단됐다는 설명은
부정확하다. 새 변경은 nonactive에도 직접 I/U를 닫는 강화이며, startup reconciliation의
`_FEATURE_TABLE_PRIVILEGES`도 SELECT만으로 바꿔야 한다. migration REVOKE만으로 끝내면 다음
reconcile이 권한을 되살린다. db.py boundary preflight와 exact ACL/owner/routine inventory,
receipt forward head·graph·head oracle·기존300 handoff/frozen schema 분기도 함께 검증한다.

**기본 OFF0은 SH planning/새 scope 시도0이다.** legacy SQL은 직접 INSERT에서 SD EX로 바뀌므로
role/검증/잠금과 내부 SQL 비용이 바뀐다. 모든 SQL 무변경/비용0이라고 쓰지 않는다. default OFF
전체 수집 의미 동등과 추가 비용은 아래 실제 전후 회귀·측정의 필수 gate다.

## 공개 SD 서명과 좁은 grant 제안

새 routine 이름은 초안이며 migration 번호는 아직 할당하지 않는다.

```sql
-- 기존 Python upsert_stamps의 동일 SQL 기능. 신설 SD, schema-qualified relations만 사용.
feature.upsert_provider_geocode_stamps_ex(
  p_feature_ids uuid[], p_outcomes text[], p_version_token text, p_data_token text
) RETURNS bigint

-- apply begin 뒤, 첫 source DML 전: bounded 전체 old stamp를 잠금/재검증만 한다.
feature.lock_scoped_provider_geocode_stamps(
  p_attempt uuid, p_owner uuid, p_manifest_digest text,
  p_input_digest text, p_targets jsonb
) RETURNS bigint

-- 모든 실제 source/candidate/winner 적용 뒤: 같은 stamp를 now()로만 재관측한다.
feature.reobserve_scoped_provider_geocode_stamps(
  p_attempt uuid, p_owner uuid, p_manifest_digest text,
  p_input_digest text, p_targets jsonb
) RETURNS bigint
```

세 함수는 LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog, owner는 기존
state procedure owner다. PUBLIC revoke, canonical runtime EXECUTE만 허용한다. 공통 검증 helper를
private로 추출하면 runtime EXECUTE0이고 내부 같은 owner만 사용한다. 공유 schema CREATE를
넓히지 않고 정본 role window에서 생성/원복한다. caller TX를 commit/rollback하거나 SET ROLE로
변경하지 않는다. current_user를 SD caller provenance로 쓰지 않는다.

runtime은 SELECT를 유지하지만 UPDATE 회수 뒤 SELECT FOR UPDATE도 직접 할 수 없다. 그래서
첫 source DML 전에 SD lock-preflight가 필요하다. SH writer가 후에 자체 잠금·검증을 반복해도
안전하도록 하고, 사전 호출 사실을 GUC나 bool로 권한 처리하지 않는다. preflight와 writer 두 번의
단일 batch 왕복이며 target당 client 왕복은 없다. before SQL의 입력도 MAX+1/총1MiB 검사다.

## SH 공통 검증과 lock 순서

`p_targets`는 정확한 object key만 있는1..2730개 배열이다. 각 item은 canonical Feature UUID,
primary entity key, 입력 source_record_key, active policy revision, 기대 old stamp의 version/data/
outcome/stamped_at이다. token regex/outcome/aware timestamptz·UUID·길이·duplicate Feature/entity와
unknown key를 DML 전에 검증한다. 이 evidence와 전체 원순서 bundle/Geo/retire/options를 포함한
전체 입력 합계1MiB/depth64를 유지한다. evidence만 별도로1MiB를 더 허용하지 않는다.

1. existing protocol의 정확2int SH가 현재 backend에 granted이고 EX는 없는지 확인한다. SH/EX
   mode를 실제 lock과 attempt.exclusive_protocol=false로 모두 확인한다. gate 없는 호출/EX로
   위장한 SH/ready·completed·cancelled는23514다. 이 함수가 begin을 대신 실행하지 않는다.
2. policy epoch SH 획득/현재 revision 확인. 같은 TX applying status와 apply_txid=txid_current,
   p_owner·manifest/input digest 일치 및 regions=[]를 확인한다. owner/scope/epoch/lease는 정본
   `ops._locked_scoped_feature_write_attempt`를 owner 내부에서 재사용한다. applying+sameTX의 기존
   lease 예외는 유지한다. 새 live backend rowlock을 lease만으로 회수한다고 주장하지 않는다.
3. manifest의 Feature UUID 집합이 p_targets와 정확히 같아야 한다. 모든 target에 기존
   assert_scoped_candidate_write/assert_scoped_provider_scalar_target를 호출하고, 실제 관련
   source distinct union을8193 sentinel로 제한해 모든 dependency 존재와 expected_members=2N+M,
   실제 sealed count/manifest digest를 검증한다. 새 raw ops SELECT 권한을 runtime에 주지 않는다.
4. dataset participant→source entity/head→link→Feature 순서는 begin이 먼저 잠갔다. 이 함수는
   다른 source/Feature를 뒤늦게 추가하지 않는다. 그 뒤 stamp를 Feature UUID 순으로 FOR UPDATE,
   모든 행 존재/입력 target과 실제 Feature·kind/place·primary/current/unexpired source 일치 검증.
5. 계획 old stamp의 version/data/outcome/**stamped_at**을 모두 IS NOT DISTINCT FROM으로 대조한다.
   now()로 관측할 새 시간은 caller 입력으로 받지 않는다. missing·동시 stamp-only 교체는40001,
   새 token/outcome/Feature 재부착은23514로 source DML 전에 거부한다. SQL 함수가 live Geo 호출이
   실제 발생했는지 증명한다고 부르지는 않는다. DB 권한은 검증된 범위의 동일값 재관측뿐이다.

preflight는 여기서 count 반환/쓰기0이다. kernel이 확보한 모든 lock과 stamp lock은 같은 apply
TX 끝까지 유지한다. normalizer/지원 외 projection 및 dataset retire0은 별도 wrapper 검증이고,
이 stamp 함수가 그 의미를 대신 승인하지 않는다. first PR에서는 기존 name-only active fields만
허용하고 provider 원문 projection과 operator effective를 분리한다.

writer는 위 검증을 다시 수행하고 **actual accepted current head가 각 입력 record key와 같은지**
추가 확인한다. source DML 전 preflight에서는 아직 새 record가 head가 아닐 수 있으므로 이 equality를
조기에 요구하지 않는다. sealed manifest의 old head key와 쓰기 후 current key를 잘못 같게 요구하지도
않는다. 동일 raw/current key의 재관측은 허용하고, 옛 입력이 현재 head를 반환한 경우에는 전체
rollback/fresh replan이다. 기존 public scalar 반환 의미는 바꾸지 않는다.

전체 target 검증이 모두 끝난 뒤 한 UPDATE로 `stamped_at=now()`만 바꾼다. INSERT/DELETE·ID/
version/data/outcome 변경은 이 경로에 없다. UPDATE rowcount가 N과 다르면 실패해 전체 rollback한다.
source/candidate/winner와 stamp 갱신 후 같은 TX capture→attempt finish, 후속 SERIALIZABLE
child/root는 기존 별도 TX다. 현재 curation count/hash에는 stamp가 없으므로 이 함수 결과가
후속 semantic seal의 stamp 검증 증거라고 주장하지 않는다. Geo 결과는 attempt domain에만 결합한다.

## legacy EX SD의 동등 의미

기존 helper/loader가 획득하는 protocol EX→global curation fence 순서를 SD 첫 entry에서도
확인/재진입한다. 417의 EX 재진입 fast path를 사용하고, caller가 SH이면 stamp/Feature 행을
추가로 잠그기 전에23514로 거부한다. 기존 Python legacy fence의 유한 대기 힌트·긴 collection
상한을 SH의1s/30s로 조용히 축소하지 않는다. caller의 더 짧은 cap을 SD가 늘리지도 않는다.
기존 scoped EX caller의 shortcap은 그대로 유지한다. SD가 임의15분 힌트를 설치하지 않는다.

epoch SH→필요한 Feature UUID 정렬→stamp 순서다. active 대상은 입력 UUID와 active policy를 한 bulk SELECT로 교차해 먼저 좁힌다.
기본 OFF/noactive이면 이 조회 결과가0이며 각 N개 target에 context 함수를 호출하지 않는다.
active Feature에만 기존 `_exclusive_provider_refresh_context`의 applyingEX/sameTX/manifest/target/
primary closure를 빠짐없이 검증한다. 같은 applying attempt의 완전 closure를 함수 한 호출 안에서
공통 검증한다면 각 target membership/revision/primary 일치도 반드시 대조하고, 다른 TX에 살아남는
권한 cache나 session.info 증거로 대체하지 않는다. 초기 구현이 active별 기존 context를 호출하면
반복 CPU/SQL 비용을 실측해 기록하고 조용히 비용0으로 표시하지 않는다. broad EX만으로 active stamp를 덮지 않는다. nonactive는 원래 기능 그대로 신규 stamp,
기존 token/outcome 교체를 허용한다. 원래 table CHECK/FK의 실패/전체 rollback을 유지한다.

현재 Python의 current=None/data_token=None/empty outcomes는 SQL0/return0을 유지한다. unique
mapping과 배열 길이 일치, now()의 transaction timestamp, ON CONFLICT update, 기존 전체 return
count/같은 TX semantics를 보존한다. SH2730/1MiB를 legacy 전체 수집 cap으로 전파하지 않는다.
큰 stamp 입력을 내부 순차 batch로 나눌 필요가 있으면 **같은 TX**에서 모두 적용/count합계이며
중간 commit0이고 now()도 같아야 한다. 기존 size를 새 임의 cap으로 잘라 성공하지 않는다.

기본 OFF의 client roundtrip은 기존 stamp INSERT1개 대신 SD bulk1개다. 내부 gate/활성 target
조회/SD role 비용은 달라진다. 기존 단일/aggregate·noactive0·수천행과 active 다수에서 실제 context 호출 수·SQL statement 수,
query latency·CPU/RSS를 전후 대조한다. 단순 no-op이나 임의 benchmark 숫자로 비용0을 주장하지 않는다.

## 실제 반증·호환 수용과 작업 분할

T는 migration/role ACL/세 SD·SI trigger/installer/head graph/runtime preflight와 stamp repo SQL
배선만 소유한다. J는 신규 integration file의 실제 ACL/경합/원자성 회귀를 소유한다. 기존 scalar,
A3 full EX/client/SDK/worker 옵션의 배선 확대는 다음 작은 PR이다. 이 authority foundation만으로
SH collector 완주라고 표시하지 않는다.

| 실제 반례 | 기대 |
| --- | --- |
| current_user=service/runtime인 일반 direct I/U/D/TRUNCATE, 유효 SH·EX·위조 GUC/동일timestamp 포함 | 42501, ACL 재조정2회 뒤도 I/U 재개방0 |
| 동일 canonical service의 명시 schemaowner→stateowner SET ROLE, 별도 SD/registry | 명시 owner는 기존 고권한 경계로 별도 검증·일반 역할42501과 구분/registry stamp 거부 |
| valid applying SH + exact old stamp + 전체 closure | preflight DML0→실 source/candidate 후 timestamp만 재관측 |
| wrong owner/TX/mode/epoch/manifest·Feature/source 누락/추가/다른DS/shared entity | 첫 DML 전23514/40001, 전체 rollback |
| stamp missing/값·stamped_at 하나 교체·새token/outcome/unknownkey/중복·초과 | first source DML 전 reject/부분갱신0 |
| accepted head≠input record, completed/cancelled attempt로 writer 직접 호출 | source·stamp·capture·finish 거짓 성공0 |
| second stamp/source DML 실패·취소/반복취소·실 process kill | 모든 source/candidate/winner/stamp/attempt rollback, 동일artifact fresh retry |
| 두 독립 dataset SH preflight/apply overlap | 정확 PID/xid/SH·global EX없음, 같은Feature는 행잠금직렬화 |
| legacy EX와 SH 양방향·SH→legacy 함수 | 정확 gate blocker/23514, 자동 EX 승격0 |
| legacy 신규/업데이트/nulltoken/empty/대량>2730·slice경계 | 이전 count/token/outcome/now()/rollback 의미 동등 |
| old finite longwait·짧은 lock/statement cap·GUC baseline/pool1 | 기존 상한보존/55P03·57014·fresh retry, owner/role leak0 |
| Feature purge FK cascade·active stamp DELETE | nonactive 정상정리/active23514, DELETE grant0 |
| policy OFF/최초 cutover/기존active50·부분 trigger설치 | OFF 새scope0, 첫51/50→51 원자변환, 불완전설치거부 |
| canonical 300 handoff/head migration/metadata/reconcile/oracle/DB privilege preflight | 원300불변·새head와권한일치/forward-only |

처음 실패 원본은 보존한다. 승인된 owned2CPU/1.5GiB PG만 사용하며 정확 CID cleanup/다른 작업자
리소스 불변을 확인한다. 이 설계 단계에서는 실제 PG/성능/운영 실행0이다. 두 SQL 설계 리뷰 뒤
구현하고, foundation 실제 회귀·source2리뷰·정확CI·필요 UI 수용 뒤 다음 SH collector 배선을 진행한다.
