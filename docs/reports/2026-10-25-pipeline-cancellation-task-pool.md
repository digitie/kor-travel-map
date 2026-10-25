# 실제 API task 취소 뒤 coordinator·pool 반환 시험

## 범위와 현재 상태

부모는 `5ed45f1f3dc8eb55511c8d85b61e83e9d660dfed`다. 새 독립 integration 시험과
문서만 추가하며 API/SQL/권한/owner·lease 계약은 바꾸지 않는다. 현재 실제 PG는
실행하지 않았다. 소스 두 독립 리뷰와 고정 owned 실행기·CPU 승인을 받은 뒤 한 번
실행한다. 새 파일만 추가하고 기존 심볼 signature가 같으므로 Codegraph 영향도 평가의
신규 파일 예외를 적용한다. DTO/OpenAPI/운영/collector 변경은 없다.

## 기존 증거와 다른 단일 경로

기존 `test_exclusive_provider_full_refresh.py`의 repeated-cancel 시험은 source Python
중단·정리 재취소와 lease takeover를 확인한다. kernel의 실제 backend 대기는 새 link를
commit한 뒤40001 재계획을 확인한다. 기존 API503 감사는 SQL lock timeout55P03 뒤 새 요청을
확인했다. 이번 시험은 실제 API coordinator가 session K를 보유하고 다른 backend의 P SH를
기다리는 동안 HTTP 요청 task 자체를 취소하는 한 경계다. 세 시험의 성공을 합산하지 않는다.

## 새 시험의 관측과 기대

- 실제 service LOGIN과 pool1/max_overflow0, 정본 preflight·ASGI app/인증/handler/repo/SD를
  사용한다. 고유 lab engine과 외부 HTTP transport만 결박하고 handler·응답·잠금 함수를
  대체하지 않는다. queued unpaired job은 외부 HTTP를 요청하면 실패한다.
- 독립 holder는 실제 P SH를 보유한다. observer는 고유 root의 실제 K advisory key와
  pg_locks의 P ExclusiveLock 대기행, pg_blocking_pids의 정확 holder PID를 함께 확인한다.
  request는 K만 보유해야 하며 fake pause·잠금 호출 카운터를 대기 증거로 쓰지 않는다.
- 그 뒤 요청 task를 취소한다. SQL timeout 응답을 성공으로 바꾸지 않으며 CancelledError와
  task 종료, 원 job·취소 attempt0을 확인한다. holder를 놓기 전 pool이 반환됐는지 확인한다.
- 이전·실제 대기·다음 checkout·replay 뒤 실제 PID 집합 각각에서 모든 advisory lock0을
  확인한다. 합법적 재연결을 허용하며 같은 PID를 강제하지 않는다. 따라서 P/L/K도 남지 않는다.
- holder 종료 뒤 별도 새 HTTP 요청200과 replay200, 정확 attempt1·동일 완료 detail을 확인한다.
  원 요청의 자동 재실행이나 결과14개 추측 복구는 없다. commit 응답 유실은 이번 범위가 아니다.

## 상한과 아직 미완

시험35초, 대기 관측1.5초·observer statement1초/lock250ms, 요청 task 종료3초·holder 해제 전 task 정리2초·최종 engine 정리3초의
협력적 상한을 둔다. 고유 PG 실행은 별도 검토된 외부 process deadline 및2CPU/1536MiB/PID256/
loopback·정확 CID/UUID/볼륨 정리로 제한한다. 임의 상한 확대·실패 재해석·자동 재시도는 없다.

수집/정적 검사와 실제 실행은 구분한다. 이 시험은 provider SUCCESS, 실제 Uvicorn/운영,
commit 응답 유실·물리 driver 강제사망의 전수 수용이나 RC/strict SH 활성화 증거가 아니다.
실제 실패가 나오면 원로그/XML/정리를 보존하고 제품 수정 필요성을 별도로 검토한다.

초기 고정 소스 검증은 새 시험1개 수집2.69초·문서18 PASS1.18초·Ruff PASS다.
수집은 실제 시험 PASS가 아니며 실제 PG/취소 응답/잠금 반환은 미검증이다.
