# 공항 snapshot 후처리의 원자적 저장과 제한된 정리

## 구현 범위

- 등록된 원 입력·관측·적용 결과에서 후처리 intent를 다시 검증한다. 기존 발견사항 저장, 원 counter와 수집 시각의 sync cursor, stale 발견사항 정리를 한 READ COMMITTED transaction에 결합한다.
- SQL begin은 실제 완료된 적용과 현재 executor fence를 확인한다. finish는 같은 transaction marker, 실제 authoritative 관측·발견사항 수와 원 cursor를 확인한 뒤 receipt를 저장한다. callback 실패·취소는 전체 rollback하고 commit 응답이 불명확하면 성공을 반환하거나 효과를 자동 재실행하지 않는다. 다음 시도는 SDK0 조회로 저장 상태를 먼저 확인해야 한다.
- 더 최신의 실제 snapshot 적용, authoritative 후처리, 원 source 집합 변경, 더 최신 sync cursor가 있으면 원 관측의 후처리를 거부한다. 단순 세대 예약 후 실패한 새 run은 기존 적용을 대체하지 않는다. 전체 finding 필드 지문과 정확 clock 표현은 정본 Python decoder가 검사하며 SQL은 저장 소속·실제 효과를 따로 대조한다.
- 종결된 root/child, Dagster 종결 확인, 만료된 lease와 마지막 변경 후 7일 경과를 모두 만족하는 임시 snapshot만 한 번에 최대16개 정리한다. 전역 protocol EX 후 전역0→dataset 정렬 순으로 quota를 잠그고 ledger를 함께 반환한다. 활성·미정산 입력 및 원천/Feature/가격/날씨 이력은 대상이 아니다.

## 확인과 남은 조건

전용 transaction/backend 순수 회귀10개가 통과했다. 같은 connection 결합, 부분 실패·취소 rollback, 저장 receipt replay와 commit 응답 손실을 확인했다. Ruff와 제품 Python4파일 mypy도 통과했다. 이 결과는 실제 PostgreSQL 효과나 운영 검증을 대체하지 않는다.

새 SQL은 전체430 migration·명시 ACL·실제 scheduled caller와 함께 합성해야 하며 단독 설치하지 않는다. 실제 PG의 stale executor/새 적용/실패 세대/권한/후처리 atomicity/정리 ledger 시험, 두 적대 리뷰, 전체 CI·live UI 및 운영 배포는 아직 남아 있다. 임시 quota는 메모리·CPU 실측 튜닝 결과가 아니다.

## 실제 설치본 pin

Docker Dagster image의 설치 완료 후 root 소유 receipt를 생성한다. Map·Dagster와 DTO/직렬화/HTTP/DB/실행에 직접 참여하는 명시10종 distribution의 실제 Python/native 파일 SHA와 설치 버전, Python patch 버전을 고정한다. 총8,192파일/64MiB를 넘으면 거부한다. 운영 runtime은 기본 비활성이며 `KOR_TRAVEL_MAP_AIRPORT_SNAPSHOT_ENABLED=1`일 때만 immutable image revision과 설치 파일을 receipt와 대조한다. 외부 공항 SDK는 이 경로에서 사용하지 않는다.

설치 버전이 같아도 Python/native 파일이 바뀌면 pin을 거부하며, development/missing revision과 비정본 receipt도 거부한다. 이 경계의 순수 회귀9개가 통과했다. 실제 image build/파일 수·크기·검증 시간 측정은 아직 남아 있다. 기본 비활성은 기존 등록 입력의 재수집 허가가 아니며 caller가 등록 존재를 먼저 확인해야 한다.

독립 소스 리뷰에서 begin/finish의 receipt byte identity를 transaction marker만으로는 고정하지 못하는 경계를 확인했다. begin에서 receipt SHA도 저장하고 finish가 같은 SHA를 확인하도록 보강했다. 두 marker는 함께 설정·해제하며 실제 PG 반례 검증은 남아 있다. 공항 codec은 표준 JSON을 사용하므로 설치 inventory는 미사용 msgpack 대신 실제 Dagster 공통 실행 코드인 kor-travel-common을 포함한다.

같은 리뷰의 추가 대조에서 NULL txid/유효 intent SHA 조합이 SQL CHECK의 UNKNOWN으로 허용되는 저장 계약 문제를 확인했다. txid의 명시 IS NOT NULL 조건을 추가했다. 기존 finish의 DISTINCT FROM 거부는 유지하며 실제 제약 검증은 전체430 시험에 포함한다.

별도 리뷰에서 일반 deadline setter가 기존의 더 짧은 lock timeout을 늘릴 수 있는 경계를 확인했다. 기존 일반 setter의 동작은 유지하고 새 복구 경로에는 서버 기존값·호출자 deadline·고정 cap 중 최솟값만 적용하는 제한 함수를 연결했다. 실제 preapply에는 설치된 strict guard의 정확 inventory를 DML 전에 확인하는 shared helper를 연결한다. 이 helper 설치는 전체430의 소유다.

전체430 정본 fixture를 사용하는 실제 apply→후처리 통합 시험3개를 추가했다. sync 실제 쓰기 뒤 fault의 전체 rollback/재시도/원 receipt replay, begin/finish receipt 교체와 불완전 marker CHECK, 기존200ms/100ms 서버 cap 보존을 검증할 소스다. 현재 수집·실행은 아직 하지 않았다. provider namespace 문서에도 저장 snapshot 적용 모듈을 추가해 목록 누락 검사를3 PASS로 확인했다.

전체430 합성 뒤 PostgreSQL 통합 소스3개가 정상 수집됐다(실행 결과와 별개). API 취소 경로가 provider root의 SUCCESS를 정산할 때 남아 있던 SERIALIZABLE 한 곳도 새 finalization 계약에 맞춰 READ COMMITTED로 맞췄다. 기존 정산·전이·타임라인 검사는 유지한다.

실제 owned 첫 설치는 asyncpg의 multi-command 거부로 본체에 도달하지 못했고 wrapper를 정본 scanner 기반 단일 문장 실행으로 수정했다. 두 번째 시험은 정본300→430 설치·service LOGIN까지 성공했고 GUC 보존1 PASS/후처리 준비2 FAIL이었다. 원인은 시험 fixture의 Geo Stats 누락·frozenset 관측 집합과 이미 활성화된 동일 공항을 재seed한 것이었다. 실제 원 관측 Stats/builtinset을 연결하고 초기 EX 적재를 module당 한 번만 실행하도록 시험을 보완했다. 제품 guard·원 단언은 유지하며 후처리 본체의 실제 통과는 아직 주장하지 않는다.

세 번째 실제 시험은 startup/private ACL·GUC2 PASS/ORM·후처리 준비3 FAIL이었다. ORM의 자동 CHECK 이름2개를 실제 catalog에 맞추며 검사 자체는 유지한다. 실제 native 적용이 runtime에서 private428 capture를 직접 호출한 권한 오류도 확인했다. private 권한을 확대하지 않고 자기 snapshot/fence/완료 kernel/현재 apply TX를 검증한 후 작은 count/hash만 반환하는 typed SD를 추가했다. 공유430의 명시 owner/ACL/startup 목록 연결 뒤 실제 재검증한다. 실패 뒤에는 시험이 소유한 ready plan만 취소해 다음 사례를 가리는 연쇄 실패도 방지한다.
