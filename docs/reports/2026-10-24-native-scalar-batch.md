# A2: 한 sealed attempt의 여러 기존 Feature scalar 원자 적용

기준: 2df9ab03b33c73a55fc893ef0bf62ba6159be41c. 전용 WT는
`/home/digitie/dev/kor-travel-map-native-batch-20261024`, branch는
`codex/native-batch-20261024`다. 한정 구현과 수용 근거를 기록하며 운영/collector 배선0이다.

## API와 입력

- 새 `infra/scoped_provider_batch.py`의 frozen `ProviderScalarRefreshItem(feature_id: UUID,
  bundle: FeatureBundle)`와 `scoped_provider_refresh_batch_input_digest(items, *, dataset_id,
  policy_revision)`를 제안한다. 실제 적용은 `refresh_scoped_provider_scalars_batch`와
  `refresh_exclusive_provider_scalars_batch` 두 entry로 mode를 명시한다.
- 전체 iterable을 최대2730개(floor(기존 manifest8192/최소3항목))까지만 읽는다. 빈 입력,
  중복 canonical UUID/동일 source entity, 다른 dataset·불완전 primary place·미지원
  file/Geo/admin evidence·정책 revision 불일치는 거부한다. 모든 item이 동일한 dataset과
  policy_revision을 공유한다. 기존 단일 helper의 public 서명/digest/receipt 의미는 유지한다.
- UUID 정렬한 전체 `[native-scalar-batch-v1,dataset,revision,[[uuid,bundle],...]]`를 기존
  artifact guard/encoder로 hash한다. 전체 합계1MiB·깊이64 제한을 그대로 적용하며
  item당1MiB를 여러 번 허용하는 계약으로 늘리지 않는다. 원 입력 순서만 달라져도 digest는 같다.
  digest는 mode와 독립이며 실제 sealed attempt의 mode는 적용 때 반드시 별도로 일치 검사한다.

## 한 TX의 순서와 완전 manifest

기존 claim/append(256개씩)/seal을 별도 짧은 TX에서 수행한 뒤 같은 pool1 connection을
순차 재사용하여 새 apply TX를 연다. 새 fetch나 per-item attempt/commit은 없다.
`_arm_deadline`→SH protocol 또는 EX(legacy wait hint 소비 후 정본 global fence)→policy epoch→
`begin_scoped_feature_write`를 정확1회 호출한다. 기존 kernel은 participant dataset→모든
source/head→link→UUID Feature 순으로 sealed manifest 전체를 잠그고 epoch/owner/lease/
head/revision/membership을 재검증한다. regions는 기존 scalar와 같이 빈 배열만 허용한다.

native assert routine는 모든 item에 대해 DML 전에 호출한다. 모든 item의 `feature`와
`feature_membership` dependency 및 모든 실제 source link의 head가 manifest에 존재함을
기존 SECDEF가 검증하므로, 추가로 apply TX에서 현재 item들의 실제 source_entity union 수를
기존 runtime SELECT 권한으로 최대8193개까지만 집계한다. `attempt.expected_members ==
2*item_count + unique_source_entity_count <= 8192`를 요구하면 누락/추가 Feature·membership·
head를 숨길 수 없다(각 dependency unique 제약). ops manifest 표에 새 SELECT 권한이나
새 DDL/accessor는 추가하지 않는다. 모든 item은 다른 source entity여야 하며 기존 single
assert의 source entity가 다른 Feature에도 연결된 경우 거부하는 경계도 유지한다.

그 다음 정렬된 각 item에 기존 source upsert→현재 head 확인→명시 후보 capture→winner
recompute를 적용한다. 기존 helper에서 이 per-item 부분만 private 함수로 추출해 단일/배치가
같은 구현을 사용한다. 모든 item 성공 뒤 전체 input digest와 순서 고정된 `(UUID,current_head)`
목록의 result digest로 `finish_scoped_feature_write`를 정확1회 호출한다. 완료 receipt의
input/dataset/mode/manifest 일치 replay는 source/candidate/winner DML 없이 그대로 반환한다.
이는 이 한정 batch receipt이며 whole provider inventory 성공/retire/root snapshot seal이 아니다.

## 실패와 시험

caller가 transaction을 소유한다. 2번째 item 실패·취소·40001·55P03이면 첫 item까지 모두
rollback해야 한다. 같은 durable 입력(이번 helper가 내구 저장을 제공하는 것은 아님)과
동일 sealed attempt를 fresh TX에서 재시도하며 이미 completed면 동일 receipt·DML0이다.
SH→EX 승격 거부, 짧은 caller timeout/GUC cap·원복은 기존 계약을 그대로 따른다.

실제 owned PostGIS(2CPU/1.5GiB)에서 같은 dataset의2개 canonical Feature·policy1로
SH/EX 동등·2번째 source 실제 DML 후 예외 rollback→fresh retry→완료 replay0DML,
다른 mode/owner·stale head/membership/누락 manifest·정확 gate blocker PID·pool1 순차TX를
검증한다. 가능하면 pinned SDK public DTO→기존 국가유산 converter→legacy seed/canonical
claim→명시 lab policy cutover 경로를 별도 case로 추가하되 실제 collector 성공으로 세지 않는다.
기존 single SH/EX 및 artifact18회귀를 함께 실행한다. node/byte/depth/duplicate/순서 검사는
단위에서 DB 진입 전 거부한다. 마지막 exact CI/독립2리뷰/실UI는 별도 gate다.

## 남은 범위

A1 이름/지원 외 불변 진단은 caller 책임이며 배치 entry가 이를 collector 자동 승인으로
바꾸지 않는다. 실제 fetch artifact 영속화·Geo/link/create/file/retire·whole-TX seal·운영
policy seed/enable은 A3 후속이다. 기존 전체 SQL writer/운영 동시쓰기 완료도 주장하지 않는다.

## 설계 검토 후의 명시 경계

- root/W가 count 폐포 논리를 확인했다. 실제 sealed row count/owner/manifest는 기존
  seal/begin에서 검증하며 completed에서도 input/dataset/mode/manifest/owner와 3N~8192
  member 경계를 검사한다. completed 이후 현재 membership을 다시 쓰거나 재완료하지 않는다.
- batch entry 전체(prevalidation부터 finish까지)를 고정30s asyncio.timeout으로 감싼다.
  이는 동기 Python CPU를 선점하지 않는 협력적 deadline이며, caller의 commit/rollback을
  포함하지 않는다. 기존 single의 계약·statement30s/lock1s cap은 그대로다.
- frozen Item은 중첩 bundle/raw/list 불변성을 보장하지 않는다. caller는 claim용 digest를
  준비하는 때부터 apply의 await 종료까지 입력을 독점 소유하고 다른 task에 공유/변경하지
  않아야 한다. 적용 전 변경은 input digest 불일치로 거부한다. 일반 deepcopy/JSON roundtrip의
  타입·serializer 의미 변경은 추가하지 않는다. 내구 artifact/worker 인계는 여전히 A3다.
- regions[]는 dataset scope FOR UPDATE이고 dataset owner1이므로 같은 dataset의2개 항목은
  원자 batch 증거다. same-dataset 병렬 쓰기의 증거가 아니다. max2730/총1MiB는 실제 fetch
  max5000 수집에 일반 배선할 수 없으며 초과 입력은 DML 전에 거부하고 기존 성공 집합을 유지한다.

## 초기 구현 checkpoint(acd90d5 당시)

새 batch entry와 기존 single의 private per-item apply 추출을 구현했다. 기존 single public
서명·digest·result receipt와 SQL/ACL/DDL은 바꾸지 않는다. 이 단계의 unit16개는 순서 고정,
중복 identity·dataset/빈 입력·MAX+1 즉시 종료·총예산이 per-item hash보다 먼저 실행되는
거부와 기존 artifact 반례를 포함한다. Ruff·strict mypy2는 통과했다. 실제 PG 원자성/시간초과/
권한·정확 CI·코드 두 적대리뷰·실UI는 아직 실행/수용 전이다. 설계 두 검토를 코드 승인으로
세지 않으며 기본 OFF·운영0·새 fetch0·collector 미배선이다.

## 최종 로컬 수용

최종 집중은 **146 PASS/52.11초**다. 새 batch 실제PG20·신규 unit10과 부모의
native/EX/artifact18·A1/고정 SDK98을 같은 실행에서 확인했다. 서로 앞선 17PG/21.96초나
초기16unit 수치와 더하지 않는다. SDK는 pyproject 정본 pin
`e1b346f70dd90f68247776fe14ad39b0a90db763`과 의존성을 기존 고유 `/tmp` target에서
읽었고 공유 venv를 수정하지 않았다. 기본 CI에 선택 SDK가 없으면 해당 SDK case만 명시
skip이며, 이를 실제 실행 성공으로 세지 않는다.

새 PG는2CPU/1.5GiB·PIDs256의 소유 PostGIS를 정본 bootstrap/head418·runtime ACL reconcile
후 사용했다. 실제 runtime role에서 legacy `feature_repo.load_bundles`를 호출해
서버발급 canonical UUID/claim/alias를 얻은 뒤 소유 fixture에서만 policy1을 명시 cutover했다.
Feature/claim 직접 INSERT로 이 단계를 대신하지 않았다. `_seed_bundles(admin,runtime,old,new)`는
다음 A3 실험에서 재사용할 준비 seam이다. 실제 public `HeritageDetail`→기존 converter의
국가유산2개를 이 seam으로 적재/claim한 뒤 이름 변화 진단과 batch를 검증했다. 외부 HTTP0,
Geo 미요청·whole asset `_load`/syncsuccess/retire/seal·운영 증거는 아니다.

새 실제PG20개의 범위는 다음과 같다.

- 같은 dataset의2개 canonical Feature를 SH/EX로 모두 갱신하고 finish1회·completed의
  source/candidate/winner/finish 재호출0을 확인했다. completed여도 다른 owner/input/
  manifest/mode는 거부한다. 같은 그룹의 SH 뒤 EX 재적용도 head/candidate/clock/result
  digest가 같았다. dataset row FOR UPDATE·active owner1 제약상 same-dataset 병렬 증거가 아니다.
- 두 번째 실제 source DML 직후 RuntimeError/CancelledError·대기를 넣은2s deadline에서
  첫 Feature/source/candidate까지 전부 rollback됐다. 2s는 시험 전용 budget이며 제품은30s다.
  같은 artifact/plan을 fresh TX에서 복구하고 기존 single18 회귀도 유지했다.
- 추가/누락 Feature·누락 head·실제로 읽었던 옛 head가 남은 plan은 DML 전에 거부했다.
  1s lease 후 실제1.1s 경과→새 epoch의 정상 batch commit 뒤 늦은 옛 attempt는40001이다.
  잘못된 mode/owner도 거부했다. 현재 source/membership union을 DISTINCT+LIMIT8193으로
  읽고 전체 assert 뒤에만 정확 member count를 비교한다.
- pool_size1/max_overflow0에서 read/claim commit→fresh apply가 같은 physical PID를
  순차 재사용하고 local timeout GUC를 원복했다. 해당 dataset scope의 실제 blocker PID와
  transactionid 대기를 관찰해 source DML0에서 기다림을 확인했다. EX는 armed/unarmed 모두
  caller25ms lock cap을 유지해55P03 뒤 같은 artifact를 복구했다.
- 전체1MiB/최대2730 초과는 source DML0이고 이미 완료된 성공 집합을 보존했다. 적용 전
  입력 이름 변경도 sealed input digest 불일치로 거부했다. 중첩 DTO를 await 중 바꾸는
  다른 task에 대한 방어를 보장하지 않으며 caller의 독점 소유 전제는 그대로다.

## 원 실패와 미완료

첫 신규 fixture는 dataset을 사전 선언하지 않아 legacy loader에서 **2 FAIL/13.71초**였다
(`/tmp/map-native-batch-a2-pg-first.log`). 소유 lab catalog만 선언해 보완한 뒤 기본 SH/EX
2 PASS/14.18초를 확인했다. 다음 실행은 **14 PASS/2 FAIL/20.68초**였다
(`/tmp/map-native-batch-a2-pg-full-r1.log`). 하나는 누락 manifest의 의도된 조기 ValueError를
DB 오류로 기대한 시험 문제였고, 다른 하나는 active source head만 바꿔 commit하려던
fixture가 기존 deferred candidate guard23514에 거부된 정상 동작이었다. 제품/guard를
완화하지 않고 실제 정상 batch commit 뒤 옛 head가 남은 plan과 lease/epoch takeover로
stale 반례를 구성했다. 원로그는 삭제/성공으로 치환하지 않는다.

코드 두 독립 FULL 리뷰·정확 CI·fresh 실HTTP/UI는 이 로컬 실행과 별도 수용 gate다.
초안 base는 선행1390 branch이며 미발행 CI를 성공으로 세지 않는다. active policy의
지원 외 필드 변화·주소/좌표/category/link/신규 identity/file/retire·whole-TX snapshot seal,
실제 collector 배선/내구 artifact·운영 활성화는 A3 이후다. 기본 OFF·운영0을 유지한다.

## 최종 정적 gate

최종 Ruff·strict mypy2·import4를 통과했다. 전체 lint/archive는377 PASS·기존6skip/29.80초,
소유 scalar fixture 잔존0을 확인했다. codegraph는 전용 WT만 초기화/sync했고 기존 single의
impact4와 추출 후 private apply의 impact5를 기록했다. 다른 module의`native._apply_provider_scalar`
경유는 동적 alias라 graph만으로 완결하지 않고 batch의 실제 callsite도 직접 대조했다.
