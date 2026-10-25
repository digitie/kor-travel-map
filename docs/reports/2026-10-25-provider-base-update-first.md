# Provider base UPDATE-first 후보(425)

기존 provider materializer의 scalar·geometry 두 루프만 기존 행 UPDATE를 먼저 시도한다.
기존 행은 값이 같아도 provider lineage·base_revision·observed_at·updated_at을 갱신한다.
UPDATE가 행을 찾지 못하면 기존 INSERT ON CONFLICT 문장을 그대로 실행한다.
winner projector와 validator·권한·Feature/source 잠금·notice 최초 시작시각·subtype 반영은 바꾸지 않는다.

새 migration은 기존 procedure의 본문 SHA·인자·owner·SECURITY DEFINER·search_path를 대조한다.
기존 effective CREATE 권한이 없을 때만 정본 임시 GRANT/REVOKE window를 쓰며,
짧은 caller GUC를 유지한다. 424 고정 소스 위에 후보425를 선형으로 연결했다. 원 provider procedure 본문은 그대로다.
직접 public SD의 P-prefix 보강은 별도 작업으로 남긴다.

## 수정 전 영향과 현재 검증

새 migration/sidecar이며 public 시그니처는 같다. codegraph-worktree §7의 신규 파일 예외를 적용했다.
기존 base UPSERT 정적 조사와 실제 context 관측은 원인 후보 근거일 뿐 trigger별 비용 귀속이 아니다.
원 두 UPSERT를 그대로 둔 fallback과 새 UPDATE만 역치환하면 기존 procedure 전체 원문이 일치한다.
초기 head-schema는 부모424였다. 아래 공식425 oracle 정산 전에는 새 덤프를 생성하지 않았다.

migration CREATE·drift·짧은 GUC 단위5 PASS(0.29초), Ruff2파일/mypy1파일을 확인했다.
첫 정적 합집합은 새 unit의 baseline dump 직접 참조 때문에1 FAIL/377 PASS/기존6 skip이었다.
원 로그를 보존하고 fake catalog fixture로 격리해 baseline을 현행 계약으로 쓰지 않도록 고쳤다.
수정 뒤 같은 정적·단위 합집합은378 PASS/기존6 skip(29.76초)다. 앞5개와 중복 합산하지 않는다.
위 정적 검사 시점에는 실제 PG·API·비용·전체 CI가 미실행이었다. 두 독립 소스 리뷰 뒤
기존/부재·값동일·geometry/null·notice·모든 kind·override 보존·revision/clock·잘못된 source/registry
오류순서·owner concurrent insert fallback·전체 rollback을 검증한다.
현재 Feature lock은 정본 caller를 직렬화하지만 고권한 raw writer의 부재 증명이 아니므로
atomic UPSERT fallback을 제거하지 않는다. source/값 검증이나 deferred guard를 끄지 않는다.

성능 개선이나 SH collector 완료, 운영 활성화는 주장하지 않는다.

## 실제 시험 source 계획

전용 owned scalar fixture에서 synthetic SourceRecord/hash/key·실제 source/link·5kind를 심는다.
외부 SDK 실행이나 collector 경로를 검증한 것으로 세지 않는다. 새15개는5kind의 부재 fallback 뒤
동일값 UPDATE·lineage/revision/clock/geometry,5개 오류 전체 rollback, 허용 null, notice first-probe,
operator override 보존, exact owner-first blocker PID와 commit 후 갱신, 실제 catalog/body/ACL이다.
updated_at >= observed_at는 existing UPDATE에만 검사하고, absent INSERT는 원 DEFAULT now()를 보존한다.

경합 시험은 고권한 owner가 먼저 base를 넣어 FK KEY SHARE를 보유하고 provider Feature UPDATE가
그 exact PID에 막힘을 확인한다. owner commit 뒤 existing UPDATE가 실행되며 이를 동시 fallback
성공이라고 부르지 않는다. 늦은 raw owner INSERT의 FK/unique cycle은 옛 UPSERT에도 가능하다.
부재 fallback 실행과 원 UPSERT byte 보존은 증명하되 권한·constraint 우회로 경합을 만들지 않는다.

추가로 기존 명시 EX full-refresh20 회귀를 현재425 bootstrap에서 그대로 실행해 active policy,
epoch 및 deferred projection·부재/기존 base를 대조한다. 새15개와 기존20개의 실제 실행 결과는
두 독립 시험 source 리뷰와 별도 CPU 승인 뒤 기록한다. 원 clock/정책·guard를 끄지 않는다.

허용 geometry null은 SQL NULL과 JSON null을 SQL boolean 두 개로 구분한다.
잘못된 source record와 등록되지 않은 field를 함께 주고 source provenance 오류가 먼저 나며
전체 상태가 rollback되는 반례를 추가했다.

## 첫 실제 실행과 fixture 수정

첫 owned425 실행은15개 중 catalog/body/owner·ACL1 PASS, fixture 호출13 FAIL과 setup1 ERROR
(15.186초)였다. keyword-only `_make_source_entity_key`를 positional로 호출했고,
`record_property` fixture가 기본 xunit2에서 warning-as-error를 냈다. 원 로그/XML을 보존했다.
source key는 정본 네 keyword 인자로 호출하고, blocker/waiter PID는 `request.node.user_properties`에
남기도록 테스트만 수정했다. warning filter·제품 SQL·권한은 바꾸지 않았다.
정확 CID·UUID·scalar label·익명 volume 부재를 확인하고 CPU 슬롯을 반환했다.
실패 실행의 source/SDK 사후 검사는 완료되지 않았으며, UPDATE-first 동작·비용 효과는 아직 미판정이다.
새 소스/기동 binding의 두 리뷰와 CPU 승인 전 재실행하지 않는다.

PG 없이 정본 helper8곳의 signature binding·실제 SourceRecord/key 구성을 대조했다.
기본 xunit2·기존 warning 정책으로 순수1 PASS(7.79초), XML의 두 PID property 보존,
실제15개 collect/Ruff를 확인했다. 이 검사는 실제15개 재실행을 대신하지 않는다.

## 수정 후 실제15개 결과

수정한 fixture의 owned PG 재실행은15 PASS/실패·오류·skip0(XML14.129초, 전체23.013초)였다.
5kind의 부재 fallback·동일값 UPDATE와 lineage/revision/clock/geometry, JSON null 구분,
notice/override 보존, 잘못된 source 오류 우선과 rollback, owner-first 정확 PID 경합,
실제425 procedure 본문·owner/ACL·서비스 역할을 확인했다. 늦은 INSERT 경합 증명은 아니다.
Git2384개·SDK53개 전후와 실제 import9개를 대조했으며 SDK 실행으로 세지 않는다.
정확 CID·UUID·scalar label·익명 volume 부재를 확인했다. 첫 실패는 성공과 합산하지 않는다.

기존 활성 정책 EX20·공식425 oracle·비용·최종 CI는 아직 미완이다. 424 고정 소스 위로
migration을 선형화했고 후속 실제 검증은 아직 대기하며, 이15개 성공만으로 성능이나 collector 완료를 주장하지 않는다.

## 424 부모 통합

424의 고정14417 소스·공식 부모 oracle·tracking prefix를 보존했다. 새425 migration의
선행 revision과 receipt 허용 head에424를 넣고 graph만 선형화했다. UPDATE-first SQL과
실제15개 시험 본문은 그대로며, 앞15개는 통합 전78e 소스의 결과다. 새 부모에서의
활성 정책20·공식425 oracle·전체 CI를 수행한 것으로 승계하지 않는다.

통합 뒤 migration·tracking prefix·squash boundary·DB/runtime 권한·operation 계약 순수 합집합은
130 PASS(7.43초)였다. 통합 source의 새 PG 결과는 아직 없으며 부모 oracle424를425로
간주하지 않는다.
## 424 최종 문서 부모 통합

최종424 ab696과 최신 main 문서·424의 격리 회귀 정산을 상속했다. 앞14417 이후의 변경은
부모 문서이며425 제품 SQL·migration·실제15개 시험 본문은 d47과 같다. journal/resume는
425의 짧은 기존 prefix와 부모 전체 suffix를 보존했다. 이 통합에서 PG를 추가 실행하지 않았으며,
공식425 oracle·활성 EX20·비용 harness는 이 고정 소스에 새로 결박한 뒤 별도 두 리뷰를 받는다.

## 최종424 위 공식425 oracle과 활성 EX18

고정826의 별도 공식 fresh bootstrap·dump·반복 비교는1 PASS/27.094초였다. 부모424의1642개
object block 중1640개가 원문 일치했고, 남은 두 block은 provider procedure의 정본8344→704a
본문과 receipt의425 literal뿐이었다. procedure의 본문 밖 signature/owner/SEC/search_path와
405개 ACL/default ACL block은 전부 같았다. 그 감사 덤프를 공식 head-schema425로 채택했다.

같은826의 기존 full-refresh 모듈은 실제18 PASS/25.008초/skip0였다. 감사 wrapper가 예상20을
검사해 pytest 뒤 실패했으므로 원 runner/result의 FAIL과 로그/XML을 그대로 보존한다. 기존1398의
20개는 다른 scoped-provider-batch 모듈이며 EX18에 두 개가 빠진 것이 아니다. collection18 nodeID와
실제 XML18개를 전수 대조했다. 원 assert 뒤 미실행된 사후 검증은 별도 읽기 검사로 보완했다.
source-before2390개 Git blob/mode·현재826 clean·SDK53개·실제 import9개·pycache 부재가 일치했고,
정확 CID·UUID·scalar label·익명 volume1개 부재를 다시 확인했다. 같은18개 PG를 다시 실행하지 않았다.

공식 oracle과 EX18은 별도 fresh fixture 실행이며 앞78e의15개와 합산하지 않는다. 기존30초 cap·
source/epoch/deferred guard를 유지했다. 이 oracle/EX18 정산 시점에는 비용 A/B와 최종 정확 CI가 미완이었다. 이후의
정확 SHA별 두 리뷰·CI와 후속 수용은 PR 본문/감사 원장으로 구분한다. SH 수집완료·운영활성화는 미완이다.

## 기존 base100의 제한된 A/B 비용

고정826 source의 같은 owned425 DB에서 old8344/new704a procedure만 바꿔 synthetic native100 기존 base를 ABBAAB로 각3회 측정했다. context423·prefix424/권한·정책·30초 cap과 원54 trial은 같다. stamp insert 표기를 provider base 부재 INSERT로 해석하지 않는다.

| 구간 | A 원 UPSERT | B UPDATE-first | 관측 감소 |
| --- | ---: | ---: | ---: |
| apply PG CPU(core-ms) | 11762.246 | 8064.825 | 31.43% |
| deferred PG CPU(core-ms) | 5134.287 | 4835.039 | 5.83% |
| 각 trial apply+deferred PG CPU(core-ms) | 16896.533 | 12773.819 | 24.40% |
| 각 trial apply+deferred wall(ms) | 17558.286 | 13596.693 | 22.56% |

합계는 각 trial 두 비중첩 구간을 먼저 더한 뒤 중앙값을 구했다. contained stamp 시간이나 중앙값끼리 중복합산하지 않았다.
실제6회 rollback·fresh cancel·같은pool1 role/GUC복원·원425 definition7305… exact/OID/owner/ACL 복원을 확인했다. Git2390/SDK53 전후와 실import, 정확CID/UUID/global/익명volume1 부재를 확인했고 전체132.195초/180초 이내였다.

물리 dead tuple/cache·attempt 누적이 다른 같은 DB 순차3표본이며 전체 release 비교가 아니다. 원54의 내부 계측 overhead가 남아 있고 apply+deferred는 planning/cancel/commit·실제 collector/SDK·네트워크를 포함하지 않는다. RSS는 Python process의 관측 snapshot이며 peak가 아니다. ARM이나 운영전체 CPU 개선율로 확장하지 않는다.

원 facts SHA는 1de6e42aa8fbab085e02c73795b1bbf80f3cfa87c2f215df03cd0f2aa5f6f224이며,
두 독립 사실 대조·최종 정확 CI와 후속 수용은 PR 본문/감사 원장에서 확인한다. 추가 재실행0.

## 최종 CI 부모 합성

J424의76d 시험 수정5파일과 main d417의 Place projection 예산 helper를 상속했다.
425 SQL·migration·전용15개 시험·공식425 oracle은 앞 비용 정산 소스와 같다. 공용 journal/resume는
425의 짧은 prefix 뒤에 J76d(최신 main 포함)의 전체 suffix를 보존했다. 부모의 원 CI 실패 기록도
그대로 남겼으며 이 통합에서 PG를 추가 실행하지 않았다. 새 정확 head의 전체 CI는 별도 세대로 확인한다.
