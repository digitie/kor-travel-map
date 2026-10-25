# 동일 실행 복구의 원래 반환값 보존 조각

기준619a6d4f1의 별도 branch에서 신규 module/unit/이 보고서만 추가했다. 기존 symbol이나
signature를 바꾸지 않아 AGENTS.md의 신규 파일 Codegraph 생략 조건에 해당한다. DB 저장,
권한, lease, actual apply와 SDK0 후속 재개, child/root 완료를 연결한 구현은 아직 아니다.
단독 PR·배포/활성화는 하지 않고 전체 동시 쓰기·복구 단위에 합성한다.

## 보존 계약

`FeatureLoadResult`의 적재6·capture2·Geo6 전체14필드와, 별도 원래 반환값인 `retired`를
빠짐없이 canonical ASCII JSON bytes로 보존한다. 과거 적재 카운트를 현재 DB에서 다시 계산하거나,
완료 kernel attempt의 capture2만으로 원래 결과를 채우지 않는다. `retired`도 기본0을 발명하지
않고 명시로 받는다. 명시 domain/version과 정확한 키만 지원한다.

카운트는 bool/float/string/null 없이 PG bigint 범위의 0 이상 정수다. 전체 snapshot의 causal
capture count와 64자리 소문자 hex hash는 필수다. 입력14필드가 향후 바뀌면 기존 결과 codec의
계약을 명시 변경해야 하며, source unit가 필드 누락을 검출한다. 기존 일반 loader의 capture-null
결과를 이 복구 형식으로 암묵 전환하지 않는다.

출력/입력은4096B로 제한한다. 모든 숫자를 PG bigint 최댓값으로 둔 최악 입력도1024B보다 작다.
decode는 raw bytes/ASCII/크기/두 object 모양을 JSON parse 전에 확인하므로 깊은 임의 구조를
만들지 않는다. 중복키·부분/extra·비정규 공백·미지원 version/domain·coercion을 거부하고,
복원값을 재인코딩한 전체 bytes까지 같아야 한다.

## 권위와 미완 경계

이 bytes 자체는 출처·무변조 또는 적용 완료 증명이 아니다. 후속 private control이 실제
root/child/member와 artifact/code/SDK/clock/domain, kernel attempt/owner/manifest 및 실행 fence에
결박하고, source 변경·kernel finish와 **같은 TX**에 결과를 저장해야 한다. DB raw DML 권한을
일반 runtime에 열어 이 형식을 신뢰하는 구현은 허용하지 않는다. 그 연결과 SQL 검증은 미완이다.

원래14필드+retired 복원은 `DagsterFeatureLoadResult`의 validation/observation receipt나
finding/sync 후속 처리 완료가 아니다. commit 이후 worker가 죽은 경우 원래 입력/관측 시계로
미완 단계를 재개하고 exact child/root 정산까지 연결하는 별도 경계를 건너뛰지 않는다.

## 확인

순수 unit120 PASS/1.36초, Ruff 통과다. 최초 Ruff2개는 새 시험 긴 줄, mypy1개는 새 dict의
value 타입 추론 문제였으며 수정 후 mypy1파일 통과했다. 실제 PG/운영/복구 실패 주입은0이다.
두 독립 source review와 전체 합성 CI를 아직 수행하지 않았다.
