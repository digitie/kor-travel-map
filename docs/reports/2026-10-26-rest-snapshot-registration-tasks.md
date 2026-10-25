# Rest432 제한 profile의 작업·실제 수용 초안

기준/권위는 [설계 초안](2026-10-26-rest-snapshot-registration-spec.md)이다. base65e4943,
제품 편집/번호 migration 예약/PG·운영 실행0이며 담당 소유권은 구현 착수 때 Root가 나눈다.
현재 표의 상태는 전부 **미착수**이고431 실제215 reader 수용을 아래 완료로 재사용하지 않는다.

| 단위 | 산출물 | 함께 닫을 검증 |
| --- | --- | --- |
| S1 입력 권위 | 단일 limit256 Rest current-export-window typed EOF·bounded bytes·원 metadata/context | 215 단일응답,257/has_more/cursor/빈입력/중복/source·clock·stale/잘린body 전부거부; 여러페이지 이어받기0 |
| S2 여섯 정적 경계 | 등록SQL→infra read→client/apply→observation/postprocess→runtime→설치/GC의 정확 Rest 분기 | Airport/Rest 교차domain·DS/entity/pins·root/member·수정bytes/hash 거부; 임의 registry/권한 확대0 |
| S3 실제 원자성/복구 | 한정 TX 경계의 apply/result·후처리proof·seal 및 SDK0 freshread | commit 응답유실 각지점 재개0SDK·원14+retired/fullfindinghash·원clock/generation; 전체1commit 여부 별도 결정 |
| S4 자원/실제215 | explicit quota 제안과 kernel/capture까지 유한 owned lab | logical/physical 분리, statement3s/lock1s·2730/256KiB/1MiB 불변,215 wholecomplete/retire0·257 whole거부 |
| S5 물리두writer | barrier로 도달점 증명하는 독립 connection/transaction | 아래 pair 목록; 하나의 outerTX 순차호출을 race 수용으로 세지 않음 |
| S6 최종수용 | 새 schema 실제dump·startup/ORM/최소ACL·최종CI·OFF caller/후보UI | 기능 단위 독립2인 적대리뷰·원FAIL보존·정확cleanup; merge/운영활성화는 별도 |

## S1: source와 입력 소유

현재 Transport service_exports의 default500/max1000·요청1개RR·3일window 정본을 먼저
핀한다. publicSDK가 EOF/collection metadata를 typed하게 전달하지 못하면 SDK 계약을 먼저
해결하고 Map에서 재구현하지 않는다. 상위 source clock/hash와 collection clock을 구분한다.
기존 tuple iterator에서 EOF를 추정하거나 collection 시각만 새generation으로 쓰지 않는다.
착수 당시 SDK/Map exact pin을 기록하며 미확정 migration 번호/계약값을 발명하지 않는다.

## S2–S3: 핵심 pair

- **등록 동일/이상**: 동일member+동일input은 snapshot 동일/createdFalse/nonceNone/no renew,
  다른 root·context·pins·artifact/native hash는 거부. source215를 quota rows215로 세지 않는다.
- **잠금 전후**: 저장bytes는 같아도 DB membership/head/policy/Geo token/non-scalar가 바뀌면
  apply 전 거부/정확rollback. empty/deferred를 EX bootstrap이나 absence-retire로 낮추지 않는다.
- **정상 전체**: 정본215·2scalar+비scalar23 비교→SH begin/apply/kernel finish/result14+retired0→
  후처리 전체finding/sync/receipt→seal. 사용자-visible 결과와 저장 original count 모두 대조한다.
- **부분 실패**: apply DML 뒤 result 저장 전, 후처리 sync 뒤 finding 전·후 및 receipt 전,
  seal 응답유실을 각기 fault로 나눈다. 한TX 밖의 이미commit 효과는 rollback됐다고 쓰지 않는다.
- **lease/plan**: current applying의 reset/다른fence는 거부; expiredready→typedreset→새uniqueattempt.
  이전token/취소·완료 attempt 재사용·binding 없는 임의oldcancelled success를 허용하지 않는다.
- **완료 재개**: child/root done+정확SUCCESS만 기존 readonly noop/원receipt 반환, failed/cancelled,
  cancelrequested/격리·더새authoritative적용·미래cursor는 거부. 이미postprocessed callback0.
- **GC**: 7일terminal·expiredlease·정확reservation만 반환, active/unsealed·ledger부족 거부,
  limit/정렬/rollback·원jobs 불변·Airport quota/자료/caller 비간섭을 같이 확인한다.

## S5: 두 물리 writer 필수 시나리오

1. 두worker가 같은member를 처음 등록: ownscope 직렬화 뒤 정확immutable1개·quota한번·nonce는
   최초created만; 다른input을 성공중복으로 위장하지 않는다.
2. workerA livefence/applying 보유 중 Bclaim/reset: 정확55P03/40001 등 정본거부,
   Arollback/만료 후 B새fence 성공·A의 지연result/postprocess/seal 거부.
3. A의 잠금 전 진단 뒤 B가 같은Feature Geo/base/policy를 실제commit: A가 fresh검증에서
   whole거부·partial DML0. 서로독립DS overlap과 disjointDS도 나눠 lock순서·불필요대기 관측.
4. Aapply commit/응답유실 뒤 B가 claim: SDK0 freshstatus/result 읽고 재DML0·원counter/receipt.
   이전prepared/binding을claim 후 쓰던 race 회귀도 유지한다.
5. A후처리 또는seal commit이 B의 이전read/claim 사이 완료: exactchild/rootproof로 원결과복구,
   취소/격리를 같은SQLSTATE라는 이유로 완료처리하지 않는다.
6. exactownbackend death/취소 중 부분TX rollback→poolcheckedout0/다음SELECT1·원receipt재시도,
   active/unsealed GC 동시시도 거부. global cleanup·다른PID terminate0.

각 시험은 barrier·backend PID/starttime·실제wait/commit 순서와 두 connection을 기록한다.
예상lockwait는 finite timeout으로 종료하고 수량/guard/기대값을 줄이지 않는다. 단독CPU2/
RAM1536MiB/PID256 기본 owned donor와 exactCID/UUID/volume정리를 재사용하며, seed를 포함한
phase150/parent160/cleanup15 안 fit 여부를 별도 기록한다. 변경필요가 입증되기 전 cap확대0.
SQL/backendCPU/RSS 지점·client codec/왕복·logicalbytes/WAL은 섞지 않는다.

## 구현 착수·병합 조건

1415의 정확CI·candidateUI·merge가 먼저다.432는 먼저 source 작은checkpoint와 초안PR,
독립2인 적대리뷰/실제 양·음성/복구·원자성·최종schema/CI를 하나의 수용 단위로 닫는다.
공통 함수 시그니처를 바꾸기 전에 codegraph 영향도를 확인하며 단순 helper만 별도활성화하지 않는다.
W/T의 운영·수집 opt-in은 계속OFF이고 기존 Airport baseline을 확대하지 않는다.
