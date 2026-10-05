# Common Dagster 적용과 장애 복구

Map은 공통 Python `RecoveryPolicy`와 `bounded_request`, 공통 UI 로그인·메뉴·Dagster 대시보드를 사용한다. 공통 [구현 가이드](https://github.com/digitie/kor-travel-common/blob/1f8e339c7c79f86f8952b0d4c326ab4dae56bee8/docs/runbooks/dagster-adoption.md)가 Python 계약의 정본이다. 앱의 DB·인증·쓰기 정합성은 Map이 소유한다.

- GraphQL 조회는 plain 응답 4 MiB와 전체 10초 상한을 갖고 압축 응답을 읽기 전에 거부한다. 요청별 HTTP client를 종료 시 폐기하므로 실패·취소된 연결을 다른 요청에 재사용하지 않는다. client 정리는 별도의 50 ms 예산이다.
- 최근 30개와 별도의 활성 실행 최대 1,000개를 조회한다. 두 조회 모두 `DagsterUrls.runs_filter()`가 Map code location 태그를 주입한다. 활성 상한 도달·잘못된 응답은 정상 0건으로 바꾸지 않고 오류 상태로 표시한다. 같은 run의 terminal 상태가 활성 샘플보다 우선한다.
- UI는 마지막 정상 스냅샷을 유지하면서 현재 갱신 실패를 표시한다. 알려진 `dagster/max_runtime`에만 정체 의심 기준을 적용한다. 비밀·tick의 오류 원문은 공통 패널로 넘기지 않는다.
- asset executor의 step 동시성은 1이며 Dagster DB engine은 연결 1개·추가 연결 0개다. SQL 실행 10분·lock 대기 30초 상한을 둔다. 운영 shared daemon의 전역 정책은 Manager 소유이며 이 저장소가 임의로 변경하지 않는다.
- snapshot 8종은 원천 레코드와 변환 bundle을 100개씩 소비한다. 기존 `load_feature_bundle_batches`의 단일 transaction·최종 봉인·curation reconciliation을 유지한다. 실패하면 봉인과 sync 성공을 남기지 않는다. 특수 가격·삭제·중복 합성 계약은 기존 처리 경로를 유지한다.

## 실패와 중단 복구

쓰기 job은 `dagster/max_runtime`(기본 6시간, 기존 job별 상한 우선)을 갖고 자동 run 복제 재시도는 0이다. 이미 생성한 operation/snapshot identity를 새 run으로 복제하지 않는다. 운영 run monitoring이 시간 초과·worker 장애를 terminal 상태로 바꾼 뒤, 기존 canonical update request의 세대·lease·idempotency와 schedule command recovery 절차로 재시도한다. 저장소 조회 실패 시 새로운 쓰기를 발사하지 않는 fail-closed 동작을 유지한다.

파이프라인 화면에서 오류 run과 canonical 요청 상태를 함께 확인한다. 결과 불명 schedule command는 운영자가 원격 결과를 확인하고 기존 claim 해제 경로로 복구한다. 새 UUID를 임의로 만들거나 journal·DB 상태를 직접 덮어쓰지 않는다. 배포 재구축은 [인계 절차](../handoff/2026-10-05-shared-dagster-handoff.md)의 사전 점검·paired rotation·guarded rebuild·D1/D2 검증을 따른다.

## 고정 의존성과 검증 경계

Python API `[http]`와 Dagster `[dagster]`는 Common `1f8e339c7c79f86f8952b0d4c326ab4dae56bee8`에 고정한다. UI dev.6와 tokens 산출물은 [출처 기록](../third-party-common.md)의 동일 bytes를 사용한다. 메모리 개선은 유한 배치·응답·연결·동시성 구조에 대한 계약이다. 전체 운영 RSS 감소 수치는 실제 측정 전에는 주장하지 않는다. 후보 리뷰·재구축·live 결과는 [검증 기록](../reviews/common-dagster-2026-10-05/README.md)에 별도로 기록한다.
