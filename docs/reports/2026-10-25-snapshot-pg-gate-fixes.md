# 430 전체 PG gate의 원인 수정과 분리된 실제 수용

## 현재 상태

운영 배포는 보류 상태다. 새 제품은 unchanged foreign winner의 불필요한 base INSERT를
제외하는 projector 보완과, 기존 내부 catalog SD 세 개의 제한된 RC finalizer 진입이다.
두 변경은 각각 Root/T 독립 source 리뷰를 거쳤다. 원 CI/owned 실패는 모두 보존하며
분리된 시험을 하나의 전체 PASS로 합산하지 않는다. 공통 conftest·권한·guard·원assert를
완화하지 않았다. Root가 맡은 잔여 원 실패와 최종 합성/전체 CI/운영 수용은 아직 미완이다.

현재 실제 공식430 dump는 `f768e0cbc8f812fbeaa3ea383056c64634e8a96116d4240b1ecfc378d23c05e1`다.
고정4ec590125e6ccbb9d5c8594a7cef0bbefe143bd9 제품으로 canonical application300→430 fresh
bootstrap과 공식 재덤프 비교1PASS26.77초, runtime reconcile 호출0을 확인했다.
Git2518/SDK53 전후·실제9import/raw9 SHA 및 exact CID 부재/UUID0/global scalar0/volume1
부재를 확인했다. 직전 실제87929f98 dump에 세 기존 procedure 정의만 역치환하면 전체
bytes가 같아 ACL/owner/다른 객체의 변경0을 확인했다. 이전 projector 공식dump와도
분리해 기록하며 수작업 golden 생성은 하지 않았다.

## 제품 수정의 정확한 경계

### unchanged foreign winner

정본 recompute→private projector의 INSERT ON CONFLICT는 UPDATE WHERE가 false여도
BEFORE INSERT를 먼저 실행했다. 낮은 순위 provider의 SH 관측이 같은 foreign winner를
재투영하다 own dataset guard23514에 걸렸다. 새430 sidecar는 기존 base의 정확7요소
(provider/entity/record/hash/JSON/geometry/observed_at)가 같으면 INSERT문 자체를 건너뛴다.
실제 변경은 원 UPSERT/WHERE와 Feature projection을 그대로 실행한다. 새 조건과 들여쓰기만
역제거하면 원412 private projector 전체 byte가 같으며 원412 파일은 바꾸지 않았다.

이 보완은 실제 foreign winner 변경을 SH로 허용하지 않는다. 정본 remove policy에서
A name 제거→B winner 선택은 SH23514/rollback 뒤 typed cancel하고, 새 EX attempt로
동일 raw/hash/관측시각을 적용해야 한다. 실제 B winner 출처·A removed 상태·own phones·
원 raw/clock 및 cancelled/completed 상태까지 통과했다. 자동 SH→EX 승격은 추가하지 않았다.
raw base UPDATE는 runtime에 권한이 없어42501로 먼저 거부된다. 따라서 해당 guard probe는
기존 strict 시험과 같은 admin begin→명시 SchemaOwner의 관리 SQL 경계로 분리해
23514/message/rollback을 실제 검증했으며 일반 runtime raw 권한을 늘리지 않았다.

### legacy catalog RC/SER 모순

430 RC finalizer는 기존 SERIALIZABLE 전용 관측/생성 절차를 호출했다. 실제 root SUCCESS와
취소 SUCCESS에서25001이 발생했고, 관측 receipt INSERT의 AFTER trigger가 부르는
concierge 절차에도 같은 문제가 있었다. 처음 직접 CALL만 살펴 이 간접 경계를 놓친
분석은 원 실패와 함께 정정했다.

새 sidecar가 교체하는 기존 CommandOwner SD는 다음 세 개뿐이다.

- `feature.refresh_curated_source_observation(bigint,uuid)`
- `feature.materialize_theme_candidate_generation(uuid,text,uuid,uuid,bigint,text,jsonb)`
- `feature.sync_concierge_theme_catalog(bigint,uuid)`

기존 SER 진입과 모든 권한/domain/검증/실본문은 보존했다. RC는 현재DB/currentPID의
실제 granted P EX와 L을 모두 이미 보유할 때만 추가 허용한다. 새 lock 취득/승격0이다.
generation은 `provider_full_snapshot`만 RC이며 `rule_reconcile`은 원 SER을 유지한다.
새 signature/EXEC/role/table 권한0이며 owner/security/search_path는 그대로다.

정본 finalizer는 fresh P→L 뒤 immutable child seal와 actual capture를 전부 대조한 후
이 내부 경로를 호출한다. held predicate는 기존 dispatcher와 같은 관측이다. pg_locks로
session/xact의 과거 취득 순서를 attest하지 않는다. first-party helper가 xact P/L을
재취득하는 정본 경로와 기존 관리 owner의 한계를 구분한다. 별도 token/GUC 우회는 없다.
공식429 dump893e61의 정확 세 정의를 출처와 함께 frozen fixture에 고정했으며 새 조건을
역제거하면 각각 전체 bytes가 같다.

## catalog finalizer 내부의 한정 closure

실제 공식430 dump87929f98에서 project-owned qualified CALL/PERFORM/함수표현식과 각
직접 DML 관계의 모든 trigger를 재귀 대조했다. 경계는24 routine/9 DML관계/15 trigger
edge이며 미해석 unqualified project routine 호출이나 dynamic EXECUTE는 없었다.
SER 요구는 위 세 SD뿐이고, 나머지 isolation 검사는 기존 RC finalizer/member dispatcher/
tracking prefix다. 이는 해당 내부 경계의 source 대조이며 전체 repo writer 의미 보증이 아니다.

정확 간접 edge는 관측→`ops.curation_source_observation_receipts` INSERT→
`trg_curation_source_observation_sync_concierge`→
`feature.sync_concierge_catalog_after_observation`→concierge sync→generation이다.
관측은 curated_sources도 UPDATE한다. generation은 generation/observation/candidate/
transition4관계를, concierge는 theme/rule2관계를 변경한다. 전체 edge·정확 trigger DDL·
각 정의 SHA·isolation 줄은 `map430-catalog-finalizer-source-closure-r1.json`
(SHA dad8d88e3183ec5e32b735cdb8eef56fb70aed855af11275229e90e7c2fdaa7a)에 보존했다.

## 원 시험 callsite의 계약 정렬

- canonical 관리자 tree cleanup은 첫 raw tracking UPDATE 전에 정본 P EX→L을 취득한다.
  같은 helper를 쓰는 reconcile의 finally가 본체를23514로 덮던 연쇄를 제거했다.
- tracking 정상 finalizer와 TVN40의 동일TX ensure→seal/terminal reconcile/직접 finalizer는
  RC로 정렬했다. leaf만의 SER과 admin command의 SER, 별도 SER 조기거부는 유지했다.
- tracking의430 변경 세 body만 실제 공식 golden 전체본문에 대조하고 나머지는424 inverse다.
- registered old finish 부정 fixture는 claim 전에3s/900ms를 명시하고 원6개 부정을 유지했다.
- reset fixture는 해당 case가 새로 생성한 `reset-plan:` ready attempt만 typed cancel한다.
- source-only old RR 부정은 exact EX seed로 history를 별도 준비한 뒤 old RR snapshot→
  외부 cutover→명시 P EX→원 head UPDATE로 실행한다. 원40001/head불변 단언은 그대로다.
  이를 fresh first-party 성공으로 부르지 않는다.
- provider root를 직접 만드는 owned admin seed와 raw 권한 부정은 필요한 prefix를
  먼저 취득해 원42501/23514 의미 검사까지 도달시킨다. 기대값 삭제/blanket 권한 추가0이다.

## 실제 검증의 세대별 기록

| 고정 source·실행 | 원 결과 | 범위/후속 |
| --- | --- | --- |
| 7f40 glibc CI |118FAIL/1768PASS/23SKIP/30ERROR,978.50s| 원148 node 보존 |
| 7f40 Alpine CI |118FAIL/1762PASS/29SKIP/30ERROR,1269.76s| 동일148 node 보존 |
| 2471 owned64 |61PASS/3FAIL,34.15s| 새 scalar3 SQL 닫는 quote 누락, 본체 전42601 |
| 9c4f 새3 |1PASS/2FAIL,19.33s| no-op positive PASS; finally cancel 상한 누락 |
| 1b008 남은2 |1PASS/1FAIL,17.62s| SH rollback→fresh EX handoff PASS; raw base 권한42501 |
| 603065 관리1 |1PASS,16.72s| SchemaOwner guard23514/원본불변 PASS |
| 603065 공식1 |1PASS,54.22s| 실제 projector golden87929f98, 반복 비교 |
| e807 원4모듈77 |72PASS/5FAIL,43.80s| canonical45/reconcile12 모두 PASS; 제품 모순3/fixture2 |
| 9b1 신규11+원실패5 |14PASS/2FAIL,35.99s| 새 prefix 부정11/원 root·cancel SUCCESS PASS; 간접 sync/archived replay 잔여 |
| 4ec 신규concierge5+잔여2 |7PASS,31.13s| trigger 경로/archived replay 원 단언까지 PASS |
| 4ec 최종 공식1 |1PASS,26.77s| 세 기존 SD만 변경한 실제 golden, 반복 비교 |

각 실행의 CID/UUID/global label/owned volume 정리를 확인했다. 실패 runner는 성공 분기의
postcheck에 도달하지 않았다. 첫64의 Git2514/SDK53/실19import는 별도 실제 postcheck로
보충했고 이를 원 runner PASS로 부르지 않는다. 성공7은 Git2518/SDK53 전후/실22import와
원raw8 SHA/XML7 skip0를 확인했다. 7 수용 원장 SHA는
`f9b9002c31d114b1b9dd4dd9aa63764d468d88e70fe704edc291fa192d153158`다.
최종 공식 수용 원장 SHA는
`c7fa6f689126a3d6fc4dffca15874dd7df6b1a63121cfb10c1121ad47762e41e`다.
분리된61/1/1/1 또는72/14/7을 하나의64/77 전체 PASS라고 합산하지 않는다.

정적 검증은 schema+catalog30 unit PASS1.88초, Ruff PASS, 전체 tests/unit3813PASS/
0skip101.60초와 tests/lint373PASS/기존6SKIP41.00초다. 첫 전체unit은3800PASS/13FAIL
120.92초였고 새WT의 `@next/env` 의존성 부재로 판정문에 도달하지 못한 원로그/XML을
보존했다. root package.json/package-lock.json이 byte동일한 기존 Node22.22.2 캐시를
임시 symlink로 읽기 재사용했으며 npm/설치/제품 변경0이다. 성공 뒤 직접 만든 링크만
제거해 새 dependency나 untracked 파일을 커밋하지 않았다. source checkout 부재 등의 기존 skip 사유도 원로그에 보존했다.
원 Ruff/fixture/원 CI 실패를 덮지 않았다. 실제 generic/외부 provider 전체 수용, Root 잔여
원 실패, 최신 합성 source의 전체 CI/운영 재배포와 실제 일정 재개는 아직 별도 gate다.
운영 DB/서비스/instigator 설정은 이 작업에서 바꾸지 않았다.

원 glibc log SHA: `89f14fecf6522541a947e78024fc9f050cacecdb742eb48d32a6f51cb0018fc0`.
원148 node inventory SHA: `d9ae88e8360872d8962b55b9e785be69acb6b62db069532e798932cf3d77d737`.
