# 기존 SQL 직접 진입의 protocol-first 보강

## 발견과 범위

Python `lock_feature_curation_write`의 protocol EX→기존 전역 fence만으로 SQL 직접 호출의
순서까지 보장할 수 없다. 412 head의 기존 전역 fence 호출 9곳 중 private recorder와
activation은 이미 protocol에 먼저 진입한다. 나머지 6개 curation command와
`register_provider_field_shadow_policy`는 SQL 본문의 첫 BEGIN에서 EX에 들어가도록 보강한다.
기존 curation import/per-Feature 잠금·검증보다도 먼저 진입한다.

이 보강은 기존 배타 fallback의 순서 정렬이다. 이 7개를 scoped/shared 쓰기로 바꾸거나
모든 SQL writer 전수 전환을 완료하지 않는다. `feature-write-all` 등 다른 writer와
trigger의 전체 inventory, mixed binary 사전 점검, drain·정책 seed·운영 활성화는 별도다.
운영/공유 DB·컨테이너·스케줄 변경은 0건이다.

## 구현

413은 412의 정확한 7개 이름·owner·procedure·SECURITY DEFINER·PL/pgSQL 형태를 확인한다.
커밋된 412 실제 head oracle에서 고정한 signature·본문 SHA-256도 대조하여 모양만 같은
변경된 본문은 수용하지 않는다.
기존 전역 fence가 정확히 한 번이고 새 protocol 호출이 없는 원문만 허용하며 첫 BEGIN에
고정 호출 한 줄을 삽입한다. DB의 `pg_get_functiondef`가 내놓은 기존 DDL을 재사용하므로
본문·signature·OUT·search_path·기존 권한을 다시 복제하지 않는다. 검사 대상인 본문·signature·
owner/type가 다르거나 중복 overload·이미 변경된 모양이면 migration 전체를 거부한다.
검사하지 않는 기존 procedure 설정은 보존한다.

명시된 schema/curation 소유자 두 역할에만 기존 protocol routine EXECUTE를 부여하고 정본
runtime ACL reconcile에도 같은 내부 owner 권한을 기록한다. runtime 테이블 DML·새 공개
routine은 없다. DDL은 각 원래 owner로 실행하며 curation owner의 임시 CREATE는 이전 상태가
없었을 때만 회수한다. 마지막 schema owner·기존 timeout을 복구하고 receipt의 허용 head를
제거하지 않은 채 413만 추가한다. 기존 worker가 drain되지 않은 상태에서 적용·활성화하면
안 된다. 새 EX만으로 이미 실행 중인 옛 SQL 본문까지 바꿀 수는 없다.

## 검증과 미완

초기 실제 bootstrap의 SQL literal 종결 오류와 PostgreSQL internal char의 driver 반환형을
수정했다. 후자는 명시적인 `prokind::text` 조회로 정합시켰으며 owner/type 검사 자체를
완화하지 않았다. 동적 receipt 문자열은 실제 DDL에는 맞았지만 정본 정적 검사가 새 head를
찾지 못해 명시적인 전체 허용 목록으로 바꿨다. 초기 실패 로그도 보존했다.

최종 단위·실제 PG·기존 Python fence·전체 lint는 **407 passed/6 기존 skipped(56.01초)**다.
7개 직접 CALL마다 공유→배타 승격 거부, 두 세션의 실제 protocol 대기와 차단 PID,
대기 중 기존 전역 fence를 먼저 잡지 않음, 해제 뒤 원래 검증·권한 오류 보존을 확인했다.
공식 실제 head oracle 비교와 metadata 검사는 **2 passed(23.33초)**다. 별도 oracle 기록은
기록 모드의 의도된 skip 1건이며 성공 테스트 수에 더하지 않는다. 이후 migration의
타입 명시만 정리한 뒤 실제 PG/단위 29개를 다시 통과했고 strict mypy·Ruff도 통과했다.

두 독립 리뷰·정확 CI·최종 수용은 아직 진행 중이다. 이 PR의 테스트는 SQL/DB 경계 검증이며
지도 클릭이나 운영 UI 테스트를 대신하지 않는다.
기본 scalar OFF·정책 seed0·자동 scoped 수집 배선0을 유지한다. Map 전체 수용 뒤 적용 가능한
복구·자원·reader 개선을 Weather/Transport에 전파하며 Map 전용 모델은 복제하지 않는다.
