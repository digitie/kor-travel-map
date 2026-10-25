# Rest432 실제 동시 쓰기 구현 원장

## 현재 범위

기준 main은 `df8776903c8ef54fc1e6ad89edfc5c3dd0934aed`다. 431 reader는 제품 CI와
후보 UI를 통과해 main에 반영됐고, 운영 배포도 아래 별도 Manager·공개 UI 절차로 완료했다.
이 문서는 [선택 A 명세](2026-10-26-rest-snapshot-registration-spec.md)와
[작업 목록](2026-10-26-rest-snapshot-registration-tasks.md)의 구현 checkpoint다.
아직 432 완료·운영 활성화·동시 writer 수용을 뜻하지 않는다.

## 단일 transaction 경계

새 client 내부 coordinator는 하나의 READ COMMITTED connection/TX에서 다음을 수행한다.

1. 명시 session을 받는 정본 apply가 잠금 후 evidence를 재검증하고 원 14 counter와 retired를 저장한다.
2. 같은 session에서 미commit 원 입력과 원 결과를 읽고 snapshot·artifact/context SHA·상태를 대조한다.
3. 저장된 bytes로만 후처리 intent와 작업을 준비한다. 새 시계·SDK·HTTP·Geo 호출을 수행하지 않는다.
4. 기존 fenced begin SD, 같은 connection의 rollback_only bound client 작업, finish receipt를 수행한다.
5. outer commit 성공 응답 후에만 완료를 돌려준다. 오류·취소·불명확한 commit 응답을 전파한다.

등록·claim·planning은 별도 단계이고 child/root seal도 기존 P_EX 경로에서 별도로 수행한다.
기존 Airport public own-TX API의 서명과 동작은 유지한다. Airport runner의 prepared 경로는
새 coordinator를 쓰며, 이미 적용된 저장 snapshot 복구는 기존 SDK0 read와 receipt 확인을 따른다.
공유 작업 callback은 내부 코드에서만 구성하고, DB의 fence·domain 검증을 대체하지 않는다.

## 병행 소유권

- Root: coordinator, 기존 postprocess session seam, Airport 연결, asset/definitions/image 배선과 최종 통합.
- J: Rest 정적 SQL profile·migration·typed gateway·session apply·quota/설치 계약.
- T: 기존 service HTTP를 재사용하는 bounded 단일응답·Rest 관측/후처리·runner/runtime.
- W: rollback·응답 유실·두 물리 writer·공유 topic 잠금 시험과 기존 runner 회귀.

원본 dirty worktree는 보존하고 공동 branch에서는 Root만 stage/commit한다. Rest runtime은 기본
OFF다. 입력·wire·reader·quota 한도를 서로 혼동하거나 수용을 위해 자동 확대하지 않는다.

## 확인과 남은 항목

첫 Root checkpoint의 기존 postprocess transaction·Airport plan·backend 회귀는 34 PASS,
Ruff와 해당 5개 source의 strict mypy가 통과했다. 이는 mocked 단위 회귀이며 실제 PG의
전체 rollback·동시성·commit 응답 유실 증거가 아니다.

Rest SQL/collector 연결, 전체 source 통합, 두 독립 적대 리뷰, 실제 격리 PG·두 worker,
새 golden/최소 ACL, 전체 CI와 최종 live/UI가 남았다. 기존 431 후보·운영 시험 결과로
432 시험을 대체하지 않는다. CPU/RSS·잠금 대기와 처리량은 실제 두 writer 시험에서 계량한다.


## 두 번째 통합 전 checkpoint

초안 PR은 [#1418](https://github.com/digitie/kor-travel-map/pull/1418)이다. 기존 transaction/
plan/backend 34개와 새 coordinator·runner 65개를 합친 99개가 3.31초에 통과했다.
definitions/assets/resources 기존 43개는 3.97초, lazy capture resource 1개는 1.88초에 통과했다.
이 143개는 서로 다른 단위/구성 시험이며 실제 PG 수용과 구분한다.

처음 새 runner 시험은 아직 작성되지 않은 runtime 모듈 import에서 중단됐다. 의존 모듈을
연결한 뒤 위 시험을 통과했으며 원 실패 로그는 보존했다. 초기 Docker 배선에 추가했던
별도 Rest receipt 생성 호출은 제거했다. 기존 receipt가 전체 설치 파일을 지문으로 가지므로
Rest도 이를 검증해 재사용하며, 별도 receipt나 미구현 함수를 만들지 않는다.

실제 PG 시험 초안에는 5단계별 일반 오류/취소 후 18개 상태표 전체 rollback, 성공 commit 뒤
응답 경계 오류와 원 receipt 재사용을 넣었다. 빈 finding만으로 행 저장 rollback을 수용하지
않도록 실제 converter의 warning과 이전 stale finding을 구성했다. 현재는 소스·collect 단계다.
Rest 전체215·서로 다른 DS의 두 physical writer와 공유 topic 대기는 별도로 남아 있다.

공개 UI 13개 시험은 배포할 Map `df877690`·PinVi `9ebb588a`로 source pin만 정렬했다.
Root/T가 원 시험 세 파일과 허용 치환 외 전체 동일함을 검산했다. 배포의 실제 revision431,
컨테이너7개·권한·고정 버전 확인 전에는 실행하지 않는다. 이 준비를 운영 PASS로 표현하지 않는다.


## 배포 설정의 기본 비활성 계약

code-server Compose에 `KOR_TRAVEL_MAP_AIRPORT_SNAPSHOT_ENABLED`와
`KOR_TRAVEL_MAP_REST_SNAPSHOT_ENABLED`를 각각 기본 `0`으로 전달한다. 예제 env에도 명시한다.
이 변경은 기존 Airport와 새 Rest 모두를 OFF로 유지하며 실제 운영 설정을 바꾸지 않는다.
`1`은 검증된 immutable image의 전체 설치 receipt·정확 DS quota가 준비된 환경에서만 쓴다.
API/UI에는 이 opt-in을 주입하지 않으며 child/root seal까지 한 TX라고 표현하지 않는다.


## 431 운영 배포 정산

Map `df8776903c8ef54fc1e6ad89edfc5c3dd0934aed`·PinVi
`9ebb588ae425e5b09b613f0fed69b94eb1f34592`를 공식 Manager `0889d3b4`로 배포했다.
transaction `04684955-7490-4e95-9d61-91aa7da75ced`는 1872.74초에 committed,
실제 DB431/Pin0102·컨테이너7개 healthy·고정소스/권한/원root env 일치를 확인했다.

공개 UI UUID `1bc9d1efb9954683a8e9e107bdcf566c`는50.277초에13개 모두 통과했다.
새 두 session의 login/logout·보호401·browser process0/profile삭제·자원한도와 원env 불변을
검산했다. 이전 공개3FAIL·원 미확인 잔류session의 경계는 보존한다. 기존37개 RUNNING만
복원했고 새 기능 활성화는0이며 PinViWeatherOFF를 유지했다. 복원 뒤 fresh431/7healthy도 정상이다.

배포 전 Map·PinVi backup의 scratch복원은 verified다. Map은 동일revision에도 catalog
소유권·ACL 차이가 있다는 비차단경고를 보존하며 exactcatalog 복원 성공이라고 표현하지 않는다.
이 배포 완료는432의 실제215 apply/원자성·두writer·최종CI/live 완료와 별개다.
원장 `map431-root-operating-public13-restoration-closure-r1.json`과 각각의 실제 receipt를 구분한다.


## 세 번째 checkpoint: 실제 DB 시험 전 소스 검증

원자적 TX 안의 Rest fresh reader는 외부 30초 설정을 그대로 받지 않고 기존의 더 짧은
값을 보존하면서 statement 3초·lock 1초로 제한한다. 정상 읽기 후에는 원 설정을 돌리고,
SQL 오류·취소는 추가 SQL 없이 원 오류를 전파해 전체 TX를 rollback한다. 최초 반례
5개 실패를 보존했고 수정 후 44개가 통과했다. 두 명이 변경을 독립 검토했다.

Rest quota는 활성 정본 dataset에만 8MiB·16개로 초기화하며 global/Airport 한도와
사용량은 바꾸지 않는다. 215개 owned fixture의 논리 예약량은 최대 744,944바이트였다.
이는 실제 HTTP·PG 처리 속도나 프로세스 RSS가 아니다. fresh migration의 원 quota를
시험 준비 코드가 덮어쓰기 전에 읽어 검증하고, canonical installer로 strict guard를
설치한 뒤 새 runtime RO TX에서 33개와 inventory=true를 검증하도록 fixture를 보강했다.

통합 순수 회귀는 350개가 10.50초에 통과했다. core/Dagster strict mypy 244개 source와
실제 CI 경로의 Ruff도 통과했다. 저장소 전체 Ruff에는 변경하지 않은 docs/handoff 및
scripts의 기존 7개 오류가 남는다. 이를 실제 CI 경로 통과와 구분하며 원 로그를 보존한다.

현재 실제 432 PG 시험은 아직 0회다. 다음은 원자성 11개와 strict guard·원 quota 검증,
이후 Rest215·쿼터/GC·서로 다른 dataset 두 physical writer 시험이다. 새 golden/최소 ACL,
현재 커밋의 전체 CI·최종 live/UI와 배포도 남아 있으며 소스 리뷰 통과로 대체하지 않는다.


## 실제 원자성 11개와 공식 schema432 수용

커밋 `cb04509d`의 실제 owned PG 시험 11개가 통과했다(console 20.73초, XML 20.246초).
5단계별 오류/취소 후 18개 상태표의 rollback과 동일 plan 재실행, 성공 commit 뒤 응답 경계
유실의 SDK0 복구를 확인했다. seed 전 원 quota3행·사용량0 및 strict guard33/inventory
단언도 실제 통과했다. 물리 wire 유실·Rest215·두 writer·쿼터 소진/GC 수용은 별개로 남는다.
정확 CID/UUID/global label0·볼륨1개 부재를 재확인했고 원 실행/SDK/source 지문을 보존했다.

package migration graph 누락은 별도 검사에서 1실패·28통과로 드러났다. 정본 생성기로
기존 entry를 모두 보존한 채432→431 한 entry만 추가했고29개가1.25초에 통과했다. 두 명의
독립 검토 뒤 `c8836817`에 반영했다. 원 실패와 이전 실제 시험의 graph431 사실을 보존한다.

`c8836817`의 별도 fresh 공식 bootstrap→head→dump→정본 재덤프 비교는1개가27.459초에
통과했다(wrapper34.994초). runtime reconcile과 strict 자동 설치는0이다. 새 schema 지문은
`a55cf046257b5c4edda3e5c1a4abee8e0b3cb256d08d88fbffcca6450f060eb3`이며 실제 bytes를
`alembic/head-schema.sql`에 복사했다. 새 helper FUNCTION/ACL2개와 기존4함수/receipt TABLE
5개 변경 외 전체 블록이 보존되며 역치환하면 원431 전체 bytes와 일치한다. quota INSERT는
schema-only dump에 포함되지 않는다. 실제 startup ACL/metadata2개와 후속215·동시성,
최종 CI/live/UI 및 배포가 남아 있어 아직 완료나 운영 활성화로 표시하지 않는다.
