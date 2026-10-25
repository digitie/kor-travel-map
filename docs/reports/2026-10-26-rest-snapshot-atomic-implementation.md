# Rest432 실제 동시 쓰기 구현 원장

## 현재 범위

기준 main은 `df8776903c8ef54fc1e6ad89edfc5c3dd0934aed`다. 431 reader는 제품 CI와
후보 UI를 통과해 main에 반영됐고, 운영 배포는 별도 Manager 절차로 진행 중이다.
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
