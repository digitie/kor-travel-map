# Pinvi #668 — 결과 미확정 Feature 명령의 안전한 조정

## 문제와 소유 경계

Pinvi는 correction/delete 승인의 payload·If-Match·명령 키를 먼저 저장하지만 Map의 응답을 잃으면 거절/삭제가 계속 막힌다. Map만 명령 원장과 mutation을 소유하므로 Pinvi가 직접 DB를 읽거나 dispatch를 추측해 비우지 않는다.

GET으로 기록 없음만 확인한 뒤 dispatch를 지우면 늦게 도착한 옛 요청이 실행될 수 있다. 단순 조회가 아닌 기존 actor·operation·Idempotency-Key의 advisory 잠금 아래 부재를 영구 확정해야 한다.

## 설계 범위

- 기존 admin Feature PATCH/DELETE 두 command만 대상으로 한다. 기존 admin frontend 인증 context의 actor를 사용하며 임의 actor나 일반 domain command를 대신 조회/중단하지 않는다.
- 요청은 원래 feature_id·typed body·If-Match·명령 키와 조정 사유를 보낸다. 원래 명령의 canonical fingerprint를 같은 규칙으로 계산하고 다른 입력에 대한 결과를 소비하지 않는다.
- 같은 잠금 아래 terminal 결과가 있으면 그대로 확인하고, claim만 있으면 pending을 유지한다. 기존 결과를 덮어쓰거나 외부 실행 여부를 추측하지 않는다.
- claim도 없으면 기존 명령 원장에 영구 중단 결과를 커밋한다. 이후 도착한 같은 키의 원래 명령은 mutation을 실행하지 못해야 한다. 응답 유실 뒤 조정 재시도도 같은 결론을 돌려준다.
- 새 작업을 같은 키로 다시 보내지 않는다. Pinvi 후속 PR이 기존 dispatch의 request_id 키를 호환해서 읽고, 해제 뒤의 새 승인에는 별도 attempt 키를 영속화한다.
- 원장 조회/중단의 원자적 DB 쿼리는 infra, typed 조정과 HTTP/인증은 별도 API 패키지에 둔다. Pinvi 모델을 Map에 추가하지 않는다. 새 운영 스위치나 운영 실행은 없다.

## 검증 계획

실제 PostgreSQL에서 부재 중단/응답 유실 재시도, terminal 성공 회수, claim-only 보존, 다른 actor/operation/fingerprint 격리, 지연된 옛 명령과 조정의 양방향 경합을 확인한다. API 권한·payload/receipt 계약과 기존 command 동작을 함께 검사한다. OpenAPI·정적 write registry·baseline/pending 문서를 정합화한다.

초안 PR을 먼저 만들고 자주 commit/push한다. WSL 검증·실제 HTTP 경계·두 독립 전문 적대 리뷰·정확 최종 HEAD의 CI 후 Map PR을 일반 merge한다. Map owner merge 전에 Pinvi draft PR683의 SDK/schema/UI·감사·새 attempt 키를 로컬 owner에 연결해 실제 UI까지 검증한다. Map PR1451을 먼저 merge하고 Pinvi는 정확 merged owner OpenAPI를 vendor한 뒤 최종 검증·리뷰·CI를 거쳐 merge한다. 최종 prod 적용·시험은 Claude Code 담당이며 이 작업에서는 운영 접근/배포/시험을 하지 않는다.

## 직전 완료

Pinvi #667은 PR681로 cb3b2f6에 병합했다. 정확 최종35f84c8에 두 독립 리뷰 무차단·CI15 SUCCESS, 최신main 통합 WSL 단위1975/관련155·웹389·실제UI7/RustFS물리3을 확인했다. #643 체크를 갱신했고 남은6개는668/650/636/637/638/641이다. #671/#672는 다른 Code가 완료했다.

## 지문 호환의 보완

초기 전문 리뷰에서 v1 PATCH가 생략 필드와 명시 NULL을 같은 지문으로 만드는 기존 결함을 발견했고 단위 실패로 확인했다. PATCH만 v2로 전환하여 typed body의 exclude_unset=True를 사용하되 NULL/False/0/빈 배열은 보존한다. 다른 명령의 v1은 유지한다.

기존 actor/operation/key 잠금·UNIQUE를 그대로 두고 begin/preflight가 지문 비교보다 먼저 버전을 확인한다. v1 PATCH의 필드 존재 여부를 원장으로 복원할 수 없으므로 LEGACY_FINGERPRINT_UNVERIFIABLE은 해제 증거가 아니며 원장/Pinvi dispatch를 보존한다. 기존 v1을 v2로 재표기하지 않는다. 부재 키는 새 버전 원장으로 영구 중단하여 옛 binary의 늦은 요청도 차단한다.

expected_actor는 권한 선택이 아니라 인증 context 일치 assertion이다. 불일치면 원장 접근 전에 종료하며, 소비자는 저장된 원래 actor와 응답 actor가 일치해야만 해제/확정한다.

## 중간 검증 (2026-11-05)

WSL API 전체 1,601개, root 단위 전체 3,279개, 실제 PostgreSQL/auth/HTTP·원장 33개를 통과했다. 그래프 누락을 지적한 전문 리뷰의 P1을 재현한 뒤 437 packaged migration graph를 재생성하여 18개로 확인했다. 계약·artifact 39개와 문서·registry 등 수정 gate 53개도 통과했다. 실제 Feature runtime 변경·쌍방 UI와 최종 두 리뷰·정확 HEAD CI는 이어서 수행한다.

## 실제 runtime·UI 증거

정본 runtime 역할의 실제 Feature PATCH/DELETE 4개가 통과했다. Map86034cb·Pinvi d54b78f를 실제 HTTP·로그인·Chromium으로 연결해 UI9개를 통과했고 owner DB에서 수정2·폐쇄1·보존4·봉인2를 별도로 대조했다. 제품 응답 mock은 없고 소유 HTTP proxy가 전송 전/커밋 후 유실만 주입했다. 세부 SHA·로그 hash·한계는 [검증 증거](../reviews/feature-command-reconciliation-wsl-live.json)에 기록했다. consumer 후속 확인창 snapshot 수정의 UI 재검증은 Pinvi 최종 증거로 남긴다.

## 전체 CI의 head 오라클 보완

정확 f5a7215에서 Python3.11/3.12/3.13·API1601·Dagster937 및 프론트/린트/OpenAPI/Docker는 통과했다. 전체 PostGIS는1650pass14skip1fail이며 실패는 현행 head 오라클 미갱신 한 건이다. 봉인 baseline은 수정하지 않고 실제 fresh DB의 정본 generator로 alembic/head-schema.sql 두 줄(head437·지문1/2 허용)만 갱신했다. 재생성 모드의 skip1은 검증 통과로 세지 않았으며 이후 모드 없이 metadata 전체4pass, 오라클을 소비하는 전체 단위/정적3658pass5skip을 확인했다.

제품 API는 f5a7215 이후 같고 최신 쌍방 실제UI10(Map f5a7215/Pinvi6aad6ad, 봉인 응답 유실 포함)을 확인했다. 최종 owner candidate의 계약으로 Pinvi 검증을 병행 준비한다. owner를 먼저 두 재리뷰·최종 전체CI 뒤 병합하고, Pinvi 병합 전에는 실제 merge의 admin OpenAPI와 source/vendored 바이트·제품 지문 일치를 확인한다. 최종 판정과 merge 증거는 PR 댓글에 기록하여 문서만 바뀐 commit의 불필요한 재핀을 피한다.
