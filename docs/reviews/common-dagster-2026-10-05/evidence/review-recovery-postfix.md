# Map·PinVi 소비자 FULL postfix 독립 적대 리뷰 — 복구·DB·메모리·격리

- 날짜: 2026-10-05 KST
- 판정: **BLOCK**. 기존 R01–R04는 FIXED, 잔여 R05·R06은 OPEN이다.
- Map base `3b9b49d694c7dd544ec6ed86253f5935bde0f193` → 후보 `72242b1a0c964893778ee7e0ef25e698097e1dfa`.
- PinVi base `07cfef222c56d7e648c81b017aa8ffe4ccd1c386` → 후보 `f93af3248de8243be3c38f7e440eb0e394e84f48`.
- Common `1f8e339c7c79f86f8952b0d4c326ab4dae56bee8`, 변경 없음.
- 고정 manifest SHA256: `b9cb279817421a1ac405bfb05e0cfcf77b27b7841c2db488b65c9072b0aa974c`.

## 독립 검토 범위와 원본 보존

후보를 Linux Git archive로 본인 ext4 작업 공간 `/home/digitie/.cache/recovery-review-map-postfix-72242b1`, `recovery-review-pinvi-postfix-f93af32`에 고정했다. manifest의 **Map 57파일·PinVi 13파일** SHA256와 base부터 후보까지 전체 git diff 파일 집합이 모두 일치한다. 제품·문서 delta 전체를 이전 본인 FULL 리뷰와 연결해 재검토했다. 이전 고정 후보 대비 실제 추가 변경은 Map 8파일·PinVi 4파일이다. Dagster·배치·공통 artifact 등 바뀌지 않은 파일은 hash 일치로 연결했으며 기능 공격은 아래와 같이 다시 실행했다.

Map·PinVi AGENTS/SKILL과 적용 가이드·ADR·관련 정책을 따른 읽기 전용 리뷰다. 제품·기존 설치·외부 DB/서비스·Git index는 수정하지 않았다. 상대 리뷰어 원문은 미열람이며 부모가 수행한 UI/build/CI/mypy 등의 PASS를 본인 수행으로 합산하지 않았다. 기존 BLOCK 원문 `map-pinvi-final-review-recovery.md`(SHA256 `fb4d433b97c344eeac7e500f214ef9d98909984354ab84bda02c3e4bcc0ab58c`)은 그대로 유지한다.

## R01–R04 closure

| finding | 판정 | 독립 확인 |
| --- | --- | --- |
| R01 Map API builder Git 부재 | FIXED | `docker/api.Dockerfile:12` builder apt dependency에 git 추가. 새 Git 직접 의존성을 설치하는 단계와 일치한다. 실제 Docker image build는 NOT_RUN이며 이전 pip ENOENT 재현과 원인 행 변경으로 닫는다. |
| R02 PinVi Hatch 직접 의존성 거부 | FIXED | `apps/api/pyproject.toml:60`의 allow-direct-references 명시. 고정 archive의 실제 `uv build --wheel` 성공과 wheel METADATA의 exact Common [http] Git pin 확인. |
| R03 PinVi 전체 probe 뒤 client 정리 무제한 | FIXED | 실제 기존 timeout 공격을 재실행: 20ms read 예산 + 250ms 협조적 close가 이전 271.18ms 대신 **71.18ms**에 down 반환. 별도 finally 50ms close 예산이 적용된다. |
| R04 Map 손상 repository가 정상 빈 summary | FIXED | 기존 RepositoryConnection nodes:null와 필수 collection:null 두 반례 모두 actual get_summary에서 **status=error**, errors 비어 있지 않음. status=ok가 아니다. |

PinVi wheel SHA256: `59c37d98837d8ca258a3fbfa3c6e82798923b827bb58155900f423d4f824a212`. METADATA는 Common `1f8e339...`의 [http] extra를 직접 요구한다. wheel 빌드는 전체 의존성의 clean install 또는 API image build를 대신하지 않는다.

R03 추가 독립 공격은 원래 `_probe_pinvi_dagster`와 실제 fetch를 사용했다. slow-close가 있는 정상 응답·timeout·ConnectError·외부 cancellation 및 raw OSError close 5개를 검사했다. 정상은 ok, timeout/ConnectError는 down, cancellation은 CancelledError와 본인 cancel marker 그대로 전파된다. 실행 시간은 약 0.7–71ms이며 client는 closed로 표시되고 재사용되지 않는다. 경고는 고정 메시지만 남겨 URL/credential을 노출하지 않는다. OSError close가 정상 body의 검증 결과를 유지하는 것은 요청별 client 폐기라는 소비자 정책과 일치한다. 이것을 OS socket 정리 완료까지 보장한 것으로 해석하지 않는다.

## 열린 새 반례

### R05 — P2 / PinVi typename-only repository를 정상 빈 snapshot으로 수용

경로: `apps/api/app/services/admin_etl.py:749–772,792–821`.

실제 `_fetch_pinvi_dagster_snapshot`에 정상 server_info/recent/active 응답과 함께 아래 repository를 넣었다.

1. `{"__typename":"Repository"}`
2. `{"__typename":"Repository","name":"__repository__","location":{"name":"pinvi.etl.definitions"}}`

두 경우 모두 필수 jobs/schedules/sensors/assetNodes가 없는데도 **status=ok**, “server_info/live snapshot 정상”, repository_count=1, job_count=0을 반환했다. parser가 기본 빈 collection과 unknown identity를 만들고 마지막 검증은 typename만 확인한다. 같은 probe의 null/{} /[] /False 입력은 degraded로 차단된다. 이 정상 상태의 빈 결과가 공통 패널의 마지막 정상 snapshot을 대체할 수 있다.

권고: 필수 repository name/location·collection 및 내부 row shape를 검증하고 손상 응답은 degraded로 반환한다. selector와 identity 일치도 확인한다. 이는 기존 parser 잔여 결함이며 이번 HTTP 전송 수정이 새로 만든 회귀라고 주장하지 않는다.

직접 증거: `pinvi-probe_malformed_repository.py`, `pinvi-malformed-repository-evidence.json`. 정상 Dagster가 이런 protocol 위반 응답을 생성한다는 주장이 아니라 consumer의 malformed 응답 경계 공격이다.

### R06 — P2 / Map repository 소유 identity가 달라도 정상 summary

경로: `packages/kor-travel-map-api/src/kortravelmap/api/dagster_query_service.py:179–213,353–357`.

필수 collection이 정상인 Repository에서 name만 foreign_repository로, 또는 location.name만 foreign.definitions로 바꾼 actual get_summary 응답을 각각 검사했다. 두 경우 모두 **status=ok/errors=[]**였다. outgoing selector는 정확히 __repository__@kortravelmap.dagster.definitions이며 recent/active run filter도 해당 hidden repository tag로 제한됨을 같은 probe에서 기록했다. 정상 expected identity + 빈 collection control도 ok였다.

따라서 요청 scope는 올바르지만 응답 identity 불일치를 차단하지 않는다. R04의 shape 수정이 ownership 일치까지 닫은 것은 아니다. 권고: 설정된 selector의 repositoryName/repositoryLocationName과 응답을 비교하며 정상 owned empty는 허용한다. 정상 서버의 필터가 외부 프로젝트를 실제로 누설한다고 주장하지 않는다.

직접 증거: `map-probe_repository_identity.py`, `map-repository-identity-evidence.json`. 부모가 후속 identity 변경을 알렸지만 그 후속 SHA의 실행 결과는 이 원문 판정에 포함하지 않았다.

## 직접 실행한 회귀와 제품 delta 평가

- Map API/Dagster focused **245 PASS**, 57.60s.
- Map provider/client/loss/code-location/vnext/production-runner contract focused **184 PASS**, 5.86s.
- PinVi probe/vendored Map admin contract focused **39 PASS**, 5.79s.
- 이번 postfix에서 직접 실행한 pytest 합계 **468 PASS**. 이전 460 및 부모 suite를 더하지 않았다.
- 8종 snapshot converter 공격 재실행: 각 301개 중복 fixture, batch [100,100,100,1], 생산자 선행 소비 100개 이내, source identity 안정. 이전 full-list 변환과의 비교에서 자동 생성 created_at/updated_at/imported_at 세 필드만 정규화했다. raw/lineage/실질 payload는 비교 대상이다.
- actual AsyncKorTravelMapClient batch loader + 본인 SQLite pool1/overflow0: 중복 upsert 1행, 모든 배치 후 seal 1회, 후반 실패 시 이전 batch write rollback·기존 seal 유지 재확인. domain load/capture SQL은 최소 SQLite adapter로 대체했으므로 PostgreSQL 도메인 SQL 실증은 아니다.
- Map 실제 Definitions public config mapping을 다시 실행: 39 resolved jobs 모두 multiprocess max_concurrent=1, 유일한 loadable Definitions는 defs. Common tag의 30 jobs는 runtime/max_retries=0 정책을 유지한다. 이전 실제 Map·PinVi CLI gRPC autoload 성공 증거는 Dagster 소스 byte 일치로 연결한다. 이번에는 두 CLI를 다시 실행하지 않았다.
- 실제 localhost HTTP/1.1 + 표준 AsyncHTTPTransport + Map post_graphql 재실행: gzip/과대 Content-Length/JSON array 거부, identity 요청 헤더, CancelledError 보존 약 **2.34ms**.
- 실제 Map middleware slow client 정리 및 cancellation 재실행: 약 **50.51ms**, 원예외 유지.
- Map Docker deps에 기존 고정 UI/tokens vendor directory를 복사한다. package-lock의 local tarball 경로와 일치하며 artifact bytes는 이전 고정 dev.6/tokens와 동일하다.
- 새 Common panel은 선택 run만 기존 DagsterRunDetail을 렌더링한다. runId key로 상세 cursor 상태를 재설정하며 기존 page_size=50·event cursor 경계를 연결한다. 소스와 추가 테스트 계약을 직접 읽었다. 본인 UI test/build/browser 실행은 NOT_RUN이며 부모 UI 390 PASS를 본인 실행으로 세지 않는다.
- API summary endpoint의 관리자 route policy, 생성 OpenAPI/TS 타입, PinVi vendored OpenAPI digest/pin·M05 provenance와 새 Common Git 의존성을 전체 delta에서 검토했다. postfix는 OpenAPI bytes를 바꾸지 않아 PinVi의 원천 spec commit acde와 최신 후보 spec bytes가 동일하다.
- Dagster resource/FileRegistry/dedup/preflight engine은 각 pool1/overflow0, statement_timeout 600000/lock_timeout 30000이다. 기존 단일-session transaction 호출에 맞으며 global DB 연결 1개를 보장한다는 주장은 하지 않는다. 재시도 0/lease·canonical operation 경계는 유지하고 쓰기 run을 새 identity로 자동 복제하지 않는다.
- 문서와 ADR는 paired rebuild/live/merge를 pending으로 유지한다. shared Manager daemon의 전역 run·queue·monitor 정책은 consumer YAML 변경과 구분한다. 영구 active run의 coalescing 해제는 monitor의 terminal 확정과 기존 복구 절차라는 운영 전제다.

## 명령·증거·미실행 경계

모든 명령은 WSL Ubuntu-26.04, TMPDIR=/home/digitie/.cache, 본인 immutable Common/소비자 archive src를 명시한 PYTHONPATH로 실행했다. Map interpreter는 `/home/digitie/.cache/map-common-recovery-venv/bin/python`, PinVi API는 기존 `apps/api/.venv/bin/python` 읽기 재사용이다.

실행 명령은 이전 원문의 같은 focused pytest 목록을 새 archive cwd에서 재실행했고, `uv build --wheel --out-dir ../../independent-wheel-output` 및 보존된 `probe_snapshot.py`, `probe_executor.py`, `probe_http_consumer.py`, `probe_client_cleanup.py`, `probe_cleanup_matrix.py`, `probe_malformed_repository.py`, `probe_repository_identity.py`를 직접 실행했다. 제품 수정 없이 재현할 수 있도록 probe source/log/JSON을 함께 보존했다.

**NOT_RUN:** actual PostgreSQL/PostGIS 도메인 SQL·stored procedures·curation reconciliation, 실제 provider 수집, N150 guarded paired rebuild/live E2E, 전체 저장소 suite, fresh 전체 dependency install/Docker image build, UI/browser/build, 운영 RSS·worker kill·shared daemon 재설정. malicious cancellation-suppressing transport의 hard kill과 표준 AsyncHTTPTransport의 장시간 client-close 정체도 검증하지 않았다.

원본 manifest·본인 probes/log/JSON·실제 wheel **26파일**을 `.playwright-mcp/map-pinvi-consumer-postfix-review-recovery-evidence/`에 byte 그대로 보존했다. preservation-manifest.json SHA256:

`ee399b8720bec0723a06ab1431b41537c7ec7a8c7517eeabba8bdc90027b4af1`.

기존 네 결함의 closure와 새 잔여 결함을 혼동하지 않는다. 이 고정 후보는 R05·R06으로 BLOCK이며 다음 immutable 전체 후보에서 직접 closure를 검증해야 한다.
