# Rest432 제한 profile의 작업·실제 수용 초안

기준/권위는 [설계](2026-10-26-rest-snapshot-registration-spec.md)다. 최초 문서 checkpoint의
base65e4943·제품 편집/PG 실행0 기록은 보존한다. 구현은 main `df877690` 위 초안 PR
[#1418](https://github.com/digitie/kor-travel-map/pull/1418)에서 시작했다.

S1–S4의 제한 입력·정적 profile·선택A 원자성은 실제215·quota/GC·복구·공식 schema432/최소ACL로
수용했다. S5의 추가 동일member 등록·read/seal·GC 경합3개와 작은 두profile 계측도 각 범위에서
통과했다. 최종652 CI10개 SUCCESS·같은tree main d7fd 병합·공식432 설치·공개Map7/PinVi6을
확인했다. 이는 아래 시나리오 전체를 새 Rest 물리시험으로 실행했다는 뜻이 아니며
**T-CWRITE-01–09는 모두 미완료**다. 431 결과를 새432 시험으로 재사용하지 않는다.
원실패·세대별 실제값과 남은 수용은 [구현 기록](2026-10-26-rest-snapshot-atomic-implementation.md)에 보존한다.

| 단위 | 산출물 | 함께 닫을 검증 |
| --- | --- | --- |
| S1 입력 권위 | 단일 limit256 Rest current-export-window typed EOF·bounded bytes·원 metadata/context | 215 단일응답,257/has_more/cursor/빈입력/중복/source·clock·stale/잘린body 전부거부; 여러페이지 이어받기0 |
| S2 여섯 정적 경계 | 등록SQL→infra read→client/apply→observation/postprocess→runtime→설치/GC의 정확 Rest 분기 | Airport/Rest 교차domain·DS/entity/pins·root/member·수정bytes/hash 거부; 임의 registry/권한 확대0 |
| S3 실제 원자성/복구 | 선택A coordinator의 load+14/retired+필수 ETL/obs/sync/findings+receipt 한TX; registration/claim/seal은 별도 | 각 응답유실 SDK0·원결과/원clock/generation; seal P_EX/root순서 보존·SH→EX승격0 |
| S4 자원/실제215 | explicit quota 제안과 kernel/capture까지 유한 owned lab | logical/physical 분리, statement3s/lock1s·2730/256KiB/1MiB 불변,215 wholecomplete/retire0·257 whole거부 |
| S5 물리두writer | barrier로 도달점 증명하는 독립 connection/transaction | 아래 pair 목록; 하나의 outerTX 순차호출을 race 수용으로 세지 않음 |
| S6 최종수용 | 새 schema 실제dump·startup/ORM/최소ACL·최종CI·OFF caller/후보UI | 기능 단위 독립2인 적대리뷰·원FAIL보존·정확cleanup; merge/운영활성화는 별도 |

## S1: source와 입력 소유

현재 Transport service_exports의 default500/max1000·요청1개RR·3일window 정본을 먼저
핀한다. 기존 own-service HTTP fetcher `_transport_get`/`_transport_json`과 Map typed parser
`parse_export_page`/`require_current_collection`을 직접 써 단일 bounded 응답의 EOF/collection
metadata와 원body SHA를 보존한다. 별도 TransportSDK 프로젝트를 만들거나 외부 provider
client/facade를 재구현하지 않는다. 상위 source clock/hash와 collection clock을 구분한다.
기존 tuple iterator에서 EOF를 추정하거나 collection 시각만 새generation으로 쓰지 않는다.
착수 당시 SDK/Map exact pin을 기록하며 미확정 migration 번호/계약값을 발명하지 않는다.

## S2–S3: 핵심 pair

선택A에서 coordinator 한 곳만 load/후처리 commit과 connection·정본 lock순서를 소유한다.
profile apply는 명시 session으로 kernel finish/capture/result를 반환하며, pure intent 뒤 같은
session의 begin postprocess SD→rollback_only callback→finish receipt로 이어진다. 외부HTTP/Geo와
registration/claim은 앞 단계, control seal은 durable 원결과 기반 후속 P_EX→L/root/member 단계다.
기존430의 own-TX 메서드를 묶는 것만으로 한TX 수용을 주장하지 않는다. seal까지 한commit은
목표가 아니며 T-CWRITE04의 load/필수후처리 원자성은 실제 증거 뒤에만 닫는다.

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

S3의 공유 topic은 첫 topic DML 전에 trusted TX seam이 `dataset_projection`, `provider_sync`
두 행을 고정 C순으로 선취득하고 누락 시 fail-closed하도록 구현했다. 실제 서로 다른 DS
empty/nonempty 두 writer는 정확 blocker와 양쪽 commit을 확인했다. topic 구간·CPU/RSS
작은 두profile의 CPU ticks/RSS 표본과 client SQL→commit ACK bounds를 기록했다. backend 실제
lock 취득/해제 시각·전체 caller의 교착 부재나 운영 처리량 개선으로 확대하지 않는다.
정본 bump/알림 권위·성공 조건과 최소 ACL은 보존한다.

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
7. 서로 다른 DS의 finding nonempty/empty 두 후처리를 barrier로 교차시켜
   `dataset_projection → provider_sync`와 역순의 실제 wait/cycle을 관측한다. zero-row UPDATE도
   statement trigger가 실행됨을 포함하고 `55P03`/`40P01`을 구분한다. 첫 topic lock부터 commit까지
   작업·대기·직렬화 구간을 측정하며 실제 개선은 실물 뒤 판정한다. J e41110a2/T d693de88은
   소스 가능성만 증명하고 PG 재현0·현재 Airport1DS 운영 deadlock 확정0이다.

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


## 최종 제한 단위와 계속 열린 경계

- 최종652의 coverage owned A215는 wholecomplete/retired0·23비scalar/Geo/policy/head 양clock·
  필수 후처리·별도seal을 통과했다. Bbytes는11건 뒤12번째53000·전체rollback과8MiB/16행을
  확인했다. reader3초/lock1초/wholeTX30초와 capture 상한은 그대로다.
- S5 #1/#5/#6의 새 물리node와 #7 양profile의 정확blocker/양commit은 실제 통과했다.
  #6 GC 경합은 fresh 입력으로 P_EX 대기·backend 종료 후 보존을 검증했고 age/lease/running
  각 보호는 B5와 구분한다. #2/#4는 기존 공통 실제 복구/holder 수용과 Rest SDK0를 carry하며,
  #3은 별도TX의 lateGeo commit 후 whole거부다. sharedFeature 양성 두writer 전수 시험은 아니다.
- 계측은 작은 Airport1/Rest2 합성 입력이다. backend CPU ticks와 RSS4개 표본, client CPU/
  RSS highwater·SQL→commit ACK bounds는 단위가 다르다. 실제 backend lock 시각·215 backend
  CPU/RSS·운영 처리량/CPU/RSS·heap/WAL·실 upstream215 수집은 미측정/미수용이다.
- S6의 exact652 CI10·같은tree d7fd 병합·공식432 committed/7healthy·공개13은 완료했다.
  기존 RUNNING37만 복원하고 STOPPED14·새 profile OFF·설치 env bytes/mode를 유지했다.
  운영 profile 활성화와 전writer/지역·확대·실부하·OSworker/물리wire fault의 상위 수용은 남는다.
  상위 CWRITE9개 체크박스를 완료로 바꾸지 않는다. 기존 실패/미도달 원장은 보존한다.
