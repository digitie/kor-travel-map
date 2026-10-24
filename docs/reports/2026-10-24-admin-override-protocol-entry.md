# 전화·주소 override의 protocol 선점

## 문제와 변경 범위

기준은 `271ed151685ac60d5a993c46f5f957c3843efdf6`이다. `set_feature_phones`와
`apply_feature_address_override`는 typed author procedure 전에 Feature를 `FOR UPDATE`로
선점했다. 공유 writer가 protocol SH와 source/link를 먼저 잡는 구조에서, 이 경로가 뒤늦게
EX에 진입하면 Feature 선점과 protocol 대기가 역순이 된다.

두 함수의 첫 Feature 행 잠금 직전에 기존 `lock_feature_curation_write`를 호출한다.
protocol EX → 기존 전역 fence → Feature 순서이며, 잠금 범위·기존 대기 상한·권한·domain
command·override masking·caller commit/rollback 책임은 유지한다. 새 migration·procedure·
설정·자동 수집 배선은 없다. 독립 Feature도 기존 EX fallback으로 직렬화되므로 이 변경을
실제 동시 쓰기 활성화나 성능 개선으로 주장하지 않는다.

## 첫 번째 저장소 호출자까지의 조사

| 경로 | helper 전에 수행하는 동작 | 판정 |
| --- | --- | --- |
| `AsyncKorTravelMapClient.enrich_place_phone` → `apply_place_phone_enrichment` → phone setter | 새 caller TX, 번호 검증, `get_feature_row`의 일반 SELECT | Feature/source 행 선점 없음. 뒤의 source/link upsert도 같은 EX helper를 재사용 |
| `patch_admin_issue` → 주소 override의 두 action | actor-scoped domain command advisory/claim, 일반 issue/address SELECT, 필요한 외부 Geo 조회 | Feature/source 행 선점 없음. override 뒤 이슈 상태를 기록 |

`domain_command_transaction`은 HTTP command의 같은 caller TX를 재사용하며 내부에서 별도
Feature/source 잠금을 선점하지 않는다. phone setter의 system command key는 새 UUID다.
일반 GET의 읽기 정책이나 mutation 권한을 바꾸지 않는다.

임의 외부 Python 사용자가 이 함수 전에 이미 행을 잠근 경우까지 전수 보장하지 않는다.
공유 protocol SH를 이미 가진 caller는 기존 DB 검사대로 `23514`로 거부되며, 전체 TX rollback
후 새로운 배타 계획으로 호출해야 한다. 공유 TX 중간 EX 승격이나 자동 fallback은 없다.
직접 SQL 진입점 전수 전환, M05 보강, 취소 worker 회수는 다른 PR 범위다.

Codegraph는 새 WT에서 미초기화였고 기존 공유 인덱스는 `disk I/O error`였다. 공유 인덱스를
변경하지 않고 `rg`의 전체 Python 호출 검색과 실제 함수·decorator·SQL 본문으로 위 범위를
대조했다. 공개 함수 signature는 바꾸지 않았다.

## 검증

- bounded owned PostGIS의 실제 full bootstrap/runtime ACL을 사용하는 전용 **8 passed,
  14.33초**. 원천·운영·공유 DB 호출은 없다.
- 전화/주소 × 같은/독립 Feature의 4경합: protocol SH 및 Feature 행을 보유한 별도 세션에
  대해 정확한 protocol EX 미승인 잠금과 blocker PID 관계를 확인한다. 독립 Feature는 EX 대기
  중에도 제3세션이 `FOR UPDATE NOWAIT`로 선점 가능해야 한다. 이는 공유 writer의 잠금 모양을
  재현한 시험이며 실제 provider 수집 호출이나 운영 부하 측정은 아니다.
- SH → EX 2회귀: `23514`, 값·revision·override·command ledger hash 불변, 새 TX 정상 재호출.
- caller rollback 2회귀: 실제 author 후 전체 상태·ledger 불변, protocol/기존 fence/행 잠금
  해제 및 새 TX 재호출 확인.
- 기존 주소 단위시험 + 첫 행 잠금 전 helper 순서: **10 passed, 1.13초**.
- 변경 Python 4개 Ruff PASS, strict mypy 제품 2개 PASS, `git diff --check` PASS.
- fixture의 UUID name/label 소유권 검사와 finalizer로 자체 container를 회수한다.
  fixture 제한은 2CPU, memory=memory+swap 1536MiB, PID256이다.

독립 리뷰 2인·정확 CI·추가 HTTP/UI 수용은 아직 별도 gate다. 기존 reader/kernel UI 증거를
이 새 mutation 경로의 UI 검증으로 세지 않는다. 운영 배포·정책 seed·flag 변경은 하지 않았다.
