# 큐레이션 import의 protocol-first 진입

## 문제와 실제 재현

기준 `bbf1b17e7f49b10b9e2ab4c5da51bb3b024a80d6`에서 정본 M03 preview plan 생성·claim·전체 `import_curation_rows`와 유효한 direct manual command를 SERIALIZABLE runtime role로 실행했다. 제3 세션이 collection-key advisory를 보유한 동안 import A는 import advisory를 선점하고, direct manual B는 SQL413 protocol EX를 선점했다. 제3 세션을 해제하면 A는 B의 protocol을, B는 A의 import advisory를 기다려 실제 `40P01`이 발생했다. 낮은 잠금 helper만 부른 재현이 아니다.

최종 수정 전 R4는 실제 PG 1 passed/15.69초다. A PID117·B PID120 사이 `pg_blocking_pids` 상호 의존과 `pg_locks`를 함께 확인했다. protocol은 `(1369104691,115,objsubid=2)` EX, import advisory는 `hashtextextended('kortravelmap:curation-import',0)`의 objsubid1이다. B가 `40P01`, A는 manual child1개를 정상 생성했으며 두 TX 모두 rollback했다. 초기 R1의 pytest 설정 누락·R2의 CSV row_number1 fixture 실패는 이 재현의 성공 수에 합산하지 않는다. R3와 R4는 별도 실행이다.

## 최소 변경과 폐포

normal-head의 비어 있지 않은 import는 첫 import advisory 직전에 `SELECT ops.lock_scoped_feature_write_protocol(true)` 한 문장을 실행한다. 그 뒤 collection/Feature 잠금·plan·child·권한·rollback 계약은 그대로다. 기존 Python protocol helper는 명시 TX를 요구하므로 기존 autobegin 계약을 바꾸지 않도록 사용하지 않았다.

공유 `_lock_curation_write_boundary`는 바꾸지 않는다. 다른 직접 caller인 `create_curation_collection`과 `upsert_curation_theme`에도 새 protocol을 추가하지 않는다. 이 둘은 현행 자체 흐름에서 이후 Feature protocol로 재진입하지 않는다. API의 import-plan claim은 plan/command를 선점하나 revision-vector의 Feature 조회는 일반 SELECT이며, actual child SQL과 공유되는 역순 행 잠금은 확인되지 않았다.

`frozen_h35_schema`는 새 ops 함수가 없는 옛0063~0079 DB 경로다. 해당 분기는 기존 advisory·자연키 SQL을 보존한다. 단위 sentinel로 새 함수를 호출하지 않는 실제 분기를 검사하며, 옛 DB 전체 replay를 실행한 증거로 세지 않는다. 빈 import도 새 gate를 호출하지 않는다.

## 검증 checkpoint

- 수정 뒤 실제 PG4 passed/16.46초: whole import/direct manual 양방향, 정확 protocol EX/key/PID/blocker·후발 import의 advisory 미선점, SH 승격 `23514`, 잠금 대기 `55P03` 뒤 rollback 및 같은 plan 재시도.
- 기존 curation 단위73 passed. 추가 h35/빈 import/기존 collection 경계 포함76 passed/1.03초. 최초 신규 collection 단위의 필수 source_id 누락1FAIL은 수정 후 통과했으며 제품 실패가 아니다.
- 2CPU·1536MiB·PID256의 자체 UUID PostGIS만 사용했다. 추가 기존 M03 회귀·보안/정적 검사·독립2리뷰·정확CI는 후속 수용이다.

## 한계

기본 OFF·정책 seed0·운영 변경0이다. 새 identity 생성 SQL 전체 폐포·다른 writer·직접 SQL entry 전수·Geo 및 Weather/Transport 전파 완료가 아니다. 옛 Python import와 새 SQL binary가 섞이면 기존 역순이 남으므로 활성화 전에 관련 writer drain이 필요하다. 이 시험은 성능 개선율이나 운영 동시성 수용을 주장하지 않는다.

수정 전 로그·기계 proof·실패 원본은 로컬 audit `2026-10-24-operations/map-curation-import-cycle-before-r*.log` 및 `*-proof.json`에 별도 보존했다. 최종 proof SHA256은 `30e9491dc0e47cf0e8b234f030bd852f51005c30ae7dd352a3872ab41ee8b530`다.
