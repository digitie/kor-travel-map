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
기존 전역 fence가 정확히 한 번이고 새 protocol 호출이 없는 원문만 허용하며 첫 BEGIN에
고정 호출 한 줄을 삽입한다. DB의 `pg_get_functiondef`가 내놓은 기존 DDL을 재사용하므로
본문·signature·OUT·search_path·기존 권한을 다시 복제하지 않는다. 정의가 달라졌거나
중복 overload·이미 변경된 모양이면 migration 전체를 거부한다.

명시된 schema/curation 소유자 두 역할에만 기존 protocol routine EXECUTE를 부여하고 정본
runtime ACL reconcile에도 같은 내부 owner 권한을 기록한다. runtime 테이블 DML·새 공개
routine은 없다. DDL은 각 원래 owner로 실행하며 curation owner의 임시 CREATE는 이전 상태가
없었을 때만 회수한다. 마지막 schema owner·기존 timeout을 복구하고 receipt의 허용 head를
제거하지 않은 채 413만 추가한다. 기존 worker가 drain되지 않은 상태에서 적용·활성화하면
안 된다. 새 EX만으로 이미 실행 중인 옛 SQL 본문까지 바꿀 수는 없다.

## 검증과 미완

초기 실제 bootstrap의 SQL literal 종결 오류와 PostgreSQL internal char의 driver 반환형을
수정했다. 후자는 명시적인 `prokind::text` 조회로 정합시켰으며 owner/type 검사 자체를
완화하지 않았다. 실패 로그도 보존했다. 수정 후 실제 전체 bootstrap와 기존 Python fence
5개 검사가 13.85초에 통과했다. 역할 정적 검사 7 passed/1 기존 skipped다.

새 SQL 직접 CALL의 공유→배타 승격 거부·두 세션 실제 대기/전역 fence 선점 금지,
실제 head oracle·metadata, 두 독립 리뷰·정확 CI·최종 수용은 아직 진행 중이다.
기본 scalar OFF·정책 seed0·자동 scoped 수집 배선0을 유지한다. Map 전체 수용 뒤 적용 가능한
복구·자원·reader 개선을 Weather/Transport에 전파하며 Map 전용 모델은 복제하지 않는다.
