# Map·PinVi 소비자 최종 FULL 독립 closure 리뷰 — 복구·DB·메모리·격리

- 날짜: 2026-10-05 KST
- 최종 제품 리뷰 판정: **FULL PASS (Map·PinVi)**. 본인 R01–R06 모두 FIXED이며 이번 직접 공격에서 새 블로커를 발견하지 않았다.
- Map base `3b9b49d694c7dd544ec6ed86253f5935bde0f193` → 후보 `e4e27f76a5ea276febea1f36ad0308aac87ea1d2`.
- PinVi base `07cfef222c56d7e648c81b017aa8ffe4ccd1c386` → 후보 `aa265cf1c3917b9d0e89316d06c35678d23757c2`.
- Common 제품 `1f8e339c7c79f86f8952b0d4c326ab4dae56bee8`, 변경 없음.
- 동일 입력 manifest SHA256: `75c7022815154989e91d83e1b8ac0010aa17cca4cf3e3bb78e8a61f979a8b544`.

## 범위와 독립성

Linux Git archive를 본인 ext4 `/home/digitie/.cache/recovery-review-map-final-e4e27f7`, `recovery-review-pinvi-final-aa265cf`에 만들었다. manifest의 **Map 57파일·PinVi 13파일** SHA256와 base부터 고정 후보까지 전체 delta 경로 집합을 직접 검증했다. 이전 본인 FULL 검토와 연결하여 전체 제품·문서 변경을 재검토했고, 이전 postfix 대비 추가 변경은 Map 6파일·PinVi 3파일임을 hash로 확인했다. Common/UI artifact·Dagster/배치의 불변 경계도 연결했다.

AGENTS/SKILL·관련 runbook·ADR와 Linux CodeGraph 읽기 전용 절차를 따랐다. 제품·사람 dirty checkout·기존 설치·Git index·외부 DB/서비스는 수정하지 않았다. 상대 리뷰어 원문은 읽지 않았다. 부모의 suite/CI/모바일/native-recovery/memory 실행은 본인 PASS에 합산하지 않았다.

이 판정은 고정 제품 delta의 독립 FULL 리뷰다. actual N150 배포·운영 PostgreSQL·live E2E·PR merge 완료 판정이 아니다. 운영 게이트는 별도로 남는다.

## finding closure

| finding | 최종 판정 | 독립 근거 |
| --- | --- | --- |
| R01 Map API builder Git 부재 | FIXED | git을 builder apt dependency에 추가한 행과 새 Common Git 의존성을 설치하는 단계를 확인. 원래 pip ENOENT 재현과 원인 수정 연결. 실제 image build는 NOT_RUN. |
| R02 PinVi Hatch 직접 의존성 거부 | FIXED | allow-direct-references 유지. 이번 exact archive에서 wheel 빌드 성공 및 METADATA의 Common [http] exact Git pin 직접 확인. |
| R03 PinVi client 정리 예산 초과 | FIXED | actual probe/fetch의 정상·timeout·ConnectError·외부 cancellation·raw OSError close 5개 공격을 다시 실행. 별도 close 50ms 예산, 취소 marker·결과 보존 확인. |
| R04 Map 손상 repository가 정상 빈 summary | FIXED | 기존 반례 및 후속 회귀가 error로 fail-closed. 이번 API 전체 테스트에서 malformed collection/row/typename 회귀 통과. 잘못된 repository 행을 제거한다. |
| R05 PinVi typename-only/필수 collection 누락 | FIXED | 이전 두 실제 반례 모두 degraded, repository_count/job_count=null, repositories=[]·recent runs 빈 상태로 반환. 정상 owned empty control은 ok. |
| R06 Map foreign repository identity | FIXED | actual get_summary에서 외부 name/location 모두 error·errors 존재. 정상 expected identity와 빈 collection은 ok. outgoing selector·recent/active hidden tag filter를 같은 probe에서 기록. |

R05의 추가 독립 matrix는 정상 owned empty, foreign name, foreign location, jobs=null, isJob="true", schedules=[false], asset groupName=[] 7개다. 정상 empty만 ok이며 나머지는 degraded와 미확인 count로 반환했다. 원래 null/{} /[] /false 및 typename-only 공격 6개도 모두 degraded다.

R03 matrix에서 정상 close timeout은 약 51.51ms, body deadline 20ms 뒤 close timeout은 약 71.13ms, ConnectError는 약 50.68ms, 외부 cancellation은 약 50.70ms였다. cancellation의 본인 marker 문자열이 그대로 전파되고 요청 client를 재사용하지 않는다. raw OSError close는 정상 body 결과를 유지하되 generic 경고만 기록한다. 협조적 synthetic transport의 aclose를 사용한 경계 공격이며 실제 OS socket 정리 완료 또는 표준 HTTP transport의 장시간 정체를 실증한 것은 아니다.

Malformed/foreign 응답 공격은 정상 Dagster가 protocol 위반 응답을 생성한다는 주장이 아니다. consumer의 fail-closed 경계를 검증한 것이다. 실제 정상 빈 repository를 오류로 취급하지 않는 control도 함께 확인했다.

## 이번 후보에서 직접 실행한 결과

- **Map API 전체 + 관련 Dagster 회귀 1,287 PASS**, 400.69s.
- **Map provider/client/loss/code-location/vnext/production-runner contract 184 PASS**, 5.67s.
- **PinVi probe·vendored Map admin contract 46 PASS**, 6.25s.
- 이번 고정 후보에서 직접 수행한 pytest 합계는 **1,517 PASS**다. 이전 리뷰의 460/468 또는 부모의 실행을 더하지 않았다.
- PinVi actual wheel 빌드 PASS. SHA256 `e8862348c0e0aa886de24e20e75d42eda2a8f9ad3c1ddc47e5ef1a0d4873d524`; METADATA의 Common [http]는 `1f8e339...`에 고정됨.
- 8종 asset의 실제 converter 공격 재실행: 각 301 중복 fixture, batch [100,100,100,1], 생산자 선행 소비 100개 이내, source identity/raw/lineage/실질 payload 비교 통과. 서로 다른 실행의 자동 생성 created_at/updated_at/imported_at 세 필드만 비교에서 정규화했다.
- actual AsyncKorTravelMapClient batch loader + 본인 SQLite(pool1/overflow0): 중복 upsert 1행, 전 배치 뒤 seal 1회, 늦은 iterator 실패 시 선행 write rollback·기존 seal 유지. domain load/capture 함수는 본인 process에서 최소 SQLite adapter로 대체했으므로 실제 PostgreSQL domain SQL을 검증한 것으로 세지 않는다.
- actual Definitions public executor config mapping 재실행: Map 39 resolved jobs 모두 multiprocess max_concurrent=1, loadable Definitions는 defs 하나. 30개 Common-tagged job의 max_runtime/max_retries=0 유지. 이전 실제 Map·PinVi CLI gRPC autoload 성공 증거는 해당 Dagster 소스 byte 일치로 연결하며 이번 두 CLI를 재실행했다고 주장하지 않는다.
- actual localhost HTTP/1.1 + 표준 AsyncHTTPTransport + Map post_graphql 재실행: gzip·과대 Content-Length·JSON array 거부, Accept-Encoding identity, 외부 cancellation 보존 약 **3.13ms**.
- actual Map request middleware의 slow client 정리 약 **50.42ms**, 원래 cancellation 유지.
- 필수 shape·소유 identity·정상 empty·client 정리/실패 전파의 추가 공격에서 새 블로커 없음.

API 패키지의 테스트 fixture가 UUID 해석을 echo resolver로 대체하고 도달 불가 placeholder DSN을 사용하는 범위를 직접 읽었다. 1,287 PASS를 실제 DB UUID/404 경계 검증으로 확대 해석하지 않는다.

## 전체 delta 재검토 결론

Map은 동일 Common Python HTTP/Dagster Git pin과 UI dev.6/tokens bytes를 사용한다. 요청별 HTTP client, 4MiB plain body 상한, 압축 사전 거부, read/정리 예산을 소비자 경계에 적용한다. recent 30과 active 최대 1,000 조회에 repository hidden tag filter를 주입하며 active cap/malformed connection을 건강한 0건으로 숨기지 않는다. Map terminal sample 우선·run-id dedup 계약을 유지한다.

8종 snapshot은 기존 단일 session/transaction을 통해 100개 변환 batch를 적재하고 마지막 seal/curation capture를 수행한다. 원천/lineage/unique-upsert 계약을 유지하며 validation finding spool은 Feature transaction 종료 후 재생한다. converter의 운영 reverse geocoder는 별도 Geo HTTP resource이며 같은 Map SQL engine을 재귀적으로 checkout하는 구조가 아니다. 실제 domain stored procedure·외부 수집은 미실행이다.

DB engine pool1/overflow0, SQL statement 600000ms/lock 30000ms는 각 engine의 상한이다. 공유 instance 전역 DB 연결 수를 1개로 보장한다는 뜻이 아니다. runtime tag와 **run 자동 복제 retry 0**는 canonical operation/lease/claim 소유권을 유지한다. 기존 asset의 step RetryPolicy(max_retries=3)는 이번 변경에서 그대로이며 run retry 0을 step retry 0이라고 주장하지 않는다. native retry·monitor·공유 queue 정책은 실제 공유 Manager daemon 경계에서 확인해야 한다. 저장소 UNKNOWN을 성공으로 승격하거나 새 UUID로 쓰기를 복제하지 않는다.

관리자 summary endpoint의 route policy·OpenAPI·TS 생성 계약과 PinVi의 vendored Map spec/hash·M05 provenance를 전체 delta에서 확인했다. 최신 Map OpenAPI bytes가 원래 spec pin acde의 bytes와 동일하므로 원천 spec provenance를 근거 없이 바꾸지 않는다. 로그인·메뉴는 Common 표현을 소비하면서 기존 API RBAC/cookie 경계를 유지한다.

선택 run의 기존 실패 상세/event cursor page_size=50을 연결한다. 최종 UI delta는 검색으로 행이 숨겨져도 상세에 해당 job/run/status/runtime cap을 명시하고, runId key로 상세 cursor 상태를 구분한다. 부모 UI 결과를 읽어 본인 실행으로 세지 않고 소스와 회귀 테스트 계약을 검토했다. 본인 UI test/build/browser는 NOT_RUN이다.

문서/ADR의 pending paired rebuild/live/merge·공유 daemon 소유 경계·실측 RSS 미주장은 적절하다. 영구 active run의 해제는 monitor가 terminal로 확정하고 기존 복구 절차가 진행되는 운영 전제다. 부모가 별도 native recovery probe를 수행했다는 전달은 본인 실행 근거로 포함하지 않았다.

## 실행 명령과 NOT_RUN

WSL Ubuntu-26.04, TMPDIR=/home/digitie/.cache, 본인 immutable Common/소비자 archive src를 명시한 PYTHONPATH를 사용했다. Map은 `/home/digitie/.cache/map-common-recovery-venv/bin/python`, PinVi API는 기존 `.venv/bin/python`을 읽기 재사용했다.

이번 주요 pytest:
```bash
python -m pytest -q packages/kor-travel-map-api/tests \
  packages/kor-travel-map-dagster/tests/test_snapshot_batching.py \
  packages/kor-travel-map-dagster/tests/test_etl.py \
  packages/kor-travel-map-dagster/tests/test_resources.py \
  packages/kor-travel-map-dagster/tests/test_asset_deps.py

python -m pytest -q tests/unit/test_admin_etl_dagster_probe.py \
  tests/unit/test_kor_travel_map_admin_contract.py
```

Map core 12파일 목록은 이전 원문의 동일 provider/client/loss/contract 목록을 이번 archive에서 재실행했다. actual wheel은 PinVi apps/api cwd의 `uv build --wheel --out-dir ../../independent-wheel-output`이다. 본인 probe source와 결과 JSON을 함께 보존했다.

**NOT_RUN:** actual PostgreSQL/PostGIS domain SQL·seal/curation procedures, 실제 provider/Geo 호출, N150 guarded paired rebuild/live UI/E2E, 전체 monorepo suite, fresh 전체 dependency install/Docker image build, UI/browser/build, 운영 RSS·worker kill·shared production daemon 동작. malicious cancellation-suppressing transport hard kill·표준 transport 장시간 client-close 정체도 미검증이다.

## 원문과 증거 보존

이전 두 원문의 bytes/hash 불변을 다시 확인했다.

- 최초 BLOCK 원문: `map-pinvi-final-review-recovery.md`, SHA256 `fb4d433b97c344eeac7e500f214ef9d98909984354ab84bda02c3e4bcc0ab58c`.
- postfix BLOCK 원문: `map-pinvi-postfix-review-recovery.md`, SHA256 `8ed2bc7f78ec0dee76c36d02b9fb002870acfd6a29b6dd24a5371188d09fbd14`.

이번 원본 manifest·본인 probes/log/JSON·실제 wheel **27파일**을 Weather `.playwright-mcp/map-pinvi-consumer-final-review-recovery-evidence/`에 byte 그대로 보존했다. preservation-manifest.json SHA256:

`62426dc728b81d2d5a2cd8ca8e7ffd222a1ce8b26292aa18953ba422371202a9`.

이 고정 제품에 대한 본인 독립 FULL 판정은 PASS다. 배포/실제 PG/live/최종 CI/merge 결과는 이 리뷰를 근거로 별도 완료해야 한다.
