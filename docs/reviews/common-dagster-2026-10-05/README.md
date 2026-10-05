# Map·PinVi 공통 Dagster 검증

<!-- latest-runtime-status -->
## 2026-10-06 — 최종 tick·C7 후보 검증 상태

최종 제품 소스는 Common `a960bdb114d99a2ac1b9608a77b240635806e551`, Map `1a3c4673790f51daa1a2f5ccf803d4e31673bad6`, PinVi `0058369c778f8c3357ee393e12e3447d7975cc1f`이다. 전체113파일 [고정 manifest](evidence/reviewed-ticks-c7-manifest.json)를 두 독립 리뷰어가 검토했으며 [복구·DB·메모리 FULL PASS](evidence/review-ticks-c7-full-recovery.md)와 [UI·인증·빌드 FULL PASS](evidence/review-ticks-c7-full-ui.md)를 받았다. 원래 C7 vendor 누락 BLOCK과 후속 수정 판정을 각각 보존한다.

이전 `1ba6/0058` 보호된 재구축은 실제 [성공 receipt](evidence/rebuild-builtin-retry1-success.json)와 [설치 코드·여섯 서비스 attestation](evidence/operating-runtime-attestation.json)를 확보했다. 같은 실제 Map Dagster 이미지의 격리된 native 실행에서 실패·worker crash·장기 정체의 종료, 동시 정상 job, 수동 재시도 성공과 자동 run monitoring을 [확인](evidence/native-operating-evidence.json)했다. 공유 운영 DB/worker 강제 종료 시험은 아니다. 이 native 이미지의 Common/Dagster Python bytes는 최종 후보와 같으며 API tick query와 C7 Dockerfile의 새 bytes를 검증한 증거로 확대하지 않는다.

최종 C7 exact Git archive 빌드와 여섯 서비스 pair 재구축은 실제 완료했다. 새 [재구축 receipt](evidence/rebuild-ticks-success.json)와 [설치 코드·서비스 attestation](evidence/operating-runtime-ticks-attestation.json)을 독립 리뷰어가 직접 확인했다. native fault 시험은 이전 이미지에서 실행했으며, 새 Map Dagster 이미지의 버전과 관련 코드 bytes가 같다는 별도 [상속 증거](evidence/native-final-byte-inheritance.json)를 확보했다. 새 이미지에 fault 시험을 다시 실행했다는 뜻은 아니다.

후속 UI 첫 시도는 PinVi 테스트 target404로 중단됐다. 운영 설정의 canonical 주소로 private 입력을 바로잡은 새 [실제 UI 실행](evidence/ui-operating-ticks-retry1-evidence.json)에서 Chromium/Firefox×Map/PinVi 네 사례가 통과했다. 실제 로그인·Secure HttpOnly 세션·실행 상세 identity·조회 실패 뒤 마지막 정상 화면 유지/복구·390px 모바일 문서 폭/키보드 내부 스크롤을 확인했다. Map은 실제 UI 로그아웃200, PinVi는 기존 버튼이 없어 실제 API 테스트 세션 정리204를 확인했다. 브라우저 summary 요청만 중단했으며 공유 서비스/worker를 종료한 시험은 아니다. [독립 영수증·8개 화면 검토](evidence/ui-ticks-retry1-actual-visual-review-ui.md)와 [8개 캡처](evidence/ui-ticks-retry1-screenshots/capture-manifest.json)를 보존했다.

ACL40건과 [새 D1/D2 실제 수용](evidence/chain16-ticks-retry3-operating-evidence.json)이 통과했다. D1 11건 PASS, D2의 새 실행 영수증·실제 API/C7 image identity·정상 mode/attempt0 validator를 확인했다. 소유 fixture만 feature1·field override7 삭제했고 잔존0, ACTIVE/BLOCKED 없음이다. [테스트 ESM 이미지의 실제 추가 layer](evidence/c7-esm-ticks-retry3-proof.json)는 frontend package.json의 type=module 한 키만 포함하며 제품 코드113과 운영 이미지6개는 바뀌지 않았다. 두 [실행 하니스 리뷰 A](evidence/chain-ticks-retry3-overlay-review-recovery.md)·[B](evidence/c7-esm-retry3-final-review-ui.md)가 동일 기준을 확인했다. 최초 후속 영수증 수집기는 canonical validator가 생성한 validation.json을 복사본에서 제외하지 못해 [재검증에 실패](evidence/chain-ticks-retry3-collector-negative.json)했다. 두 [수집 절차 보강 리뷰 A](evidence/chain-ticks-retry3-validation-closure-review-recovery.md)·[B](evidence/chain-ticks-retry3-validation-closure-review-ui.md) 후 실제 재검증은 원본 metadata/전체 bytes를 유지하며 새 validation 출력이 원본과 byte-identical임을 확인했다. D1/D2 실행 실패와 구분한다.

앞선 D1 두 번은 host dependency 누락과 Common의 import 전용 ESM export를 CommonJS로 읽는 수집 실패였다. 로그인·브라우저 전의 실패와 D2 미실행은 [첫 기록](evidence/chain-ticks-operating-negative.json)·[다음 기록](evidence/chain-ticks-retry1-operating-negative.json)에 그대로 보존했다. 별도 테스트 이미지 검사도 Docker Id를 config SHA로 가정해 한 번 중단됐고 [그 실패](evidence/chain-ticks-retry2-operating-negative.json)를 보존한다. Docker29의 OCI index/manifest/config/layer digest chain을 검증하도록 수정했다. 실제 제품 재구축·UI4건·D1/D2를 완료했으며 최종 문서 포함 CI와 PR merge가 다음 gate다. 아래 문단은 이전 시점의 이력이며 현재 판정은 이 절을 따른다.
<!-- /latest-runtime-status -->

## 2026-10-06 — 현재 운영 재시도 상태

[네 번째 실제 재구축](evidence/rebuild-builtin-fourth-negative.json)은 PinVi ETL의 고정 uv0.11.21 이미지 metadata를 GHCR에서 찾지 못해 실패했다. 앞선 다섯 이미지 빌드는 완료됐으나 운영 반영 성공은 아니다. 기존 배포 원장과 여섯 서비스는 정상으로 유지됐다. [실패 독립 확인](evidence/review-builtin-operating-build.md)과 [이후 실제 builder 호스트의 같은 index·amd64 metadata 정상 조회](evidence/builtin-uv-registry-read.json)를 구분한다. registry 응답 실패의 단일 근본원인은 확정하지 않았다.

[설치된 재시도 계약](evidence/review-retry-admission-recovery.md)은 같은 고정 Map1ba6/PinVi0058 pair와 원장을 유지한 새 output/ordinal 실행을 허용한다. 새 사전 점검 FAIL0/WARN0 뒤 pair 회전·제품 수정·원장 삭제 없이 다섯 번째 보호된 재구축을 시작했으며 현재 RUNNING이다. 최종 실제 rebuild 성공·fresh deployed ID·설치 소스·native·브라우저·D1/D2·merge는 아직 미완료다. 아래 NOT_RUN/RUNNING은 각 원문 작성 시점의 기록이다.

수집 하니스의 [별도 초기 BLOCK](evidence/review-two-collectors-block.md)과 [후속 정적 PASS](evidence/review-collectors-postfix-ui.md)는 보존했다. 같은 attestation bytes와 실제 deploy transaction, 새 UI UUID/container/source/capture SHA 연결과 다운로드 staging 정리·원자적 승격을 보강했다. 이는 제품 FULL PASS나 실제 실행 성공을 대신하지 않는다.


현재 고정 소스는 Map 1ba6ef4c52f64200e3bc3e9a4fee1dd5f8d4e77e, PinVi 0058369c778f8c3357ee393e12e3447d7975cc1f, Common a960bdb114d99a2ac1b9608a77b240635806e551이다. PinVi API·ETL의 syntax header만 builtin frontend로 변경했으며 Python·UI·lock·DTO·COPY·provenance는 이전 제품과 byte 동일하다. 두 독립 FULL 소스 리뷰는 PASS이고 현재 정확 후보 CI는 Common8·Map10·PinVi 제품9 SUCCESS다. Draft Aggregate CI gate는 SKIPPED이며 PASS로 집계하지 않는다. 새 PinVi005 후보의 운영 재구축·전환·실제 live E2E는 NOT_RUN이고 merge도 아직 미완료다. 아래 과거 진행 문구/실패/로컬 결과를 새 runtime 성공으로 승격하지 않는다.

## 2026-10-06 — 현재 builtin source 증거

[현재 immutable manifest](evidence/manifest-builtin.json)의 SHA256은 954edf0fe117091c4d39c9fbe1e4d797981c73ade359f74eaeb0d67184dbe866이며 전체111개 파일이다. 두 최신 원문은 [복구 FULL 연속 PASS](evidence/review-recovery-builtin.md)·[UI/인증/계약 FULL 연속 PASS](evidence/review-ui-builtin.md)다. JSON raw/original_sha256은 원본 bytes를 보존하고 display_sha256은 trailing whitespace만 정규화한 읽기 사본의 별도 hash다.

정확 source CI receipts: [Common8 SUCCESS](evidence/common-builtin-exact-ci.json), [Map10 SUCCESS](evidence/map-builtin-exact-ci.json), [PinVi 제품9 SUCCESS](evidence/pinvi-builtin-exact-ci.json). Draft aggregate 및 reminder/staleness SKIPPED는 성공 숫자에 포함하지 않는다. 작성자의 [API·provenance87 PASS·64.84초](evidence/root-pinvi-builtin-api-provenance87.log)와 [ETL version10 PASS·0.55초](evidence/root-pinvi-builtin-etl-version10.log)는 별도 실행이며 리뷰어/이전102 실행과 합산하지 않는다.

[세 번째 운영 rebuild 실패](evidence/rebuild-markers-third-negative.json)는 이전 markers pair의 결과로 그대로 보존한다. 현재005 source의 builtin header 선택이 host frontend gRPC 오류의 근본원인을 확정하거나 runtime 성공을 증명하지 않는다. 외부 BUILDKIT_SYNTAX override와 builder 버전은 실제 빌드 증거에서 확인해야 한다. **새005 운영 재구축/live는 NOT_RUN**이다. [보존 metadata](evidence/builtin-source-archive.json)는 원문·receipt·테스트 범위를 분리한다.

첫 운영 재구축은 [후보 Compose PinVi API 빌드 실패](evidence/rebuild-attempt1.json)였다. Docker frontend gRPC 종료를 확인했고 기존 여섯 서비스와 이전 generation은 정상으로 보존했다. 다음 재시도는 호스트 부하 때문에 사전 점검에서 차단되어 시작되지 않았으며, 부하가 내려가 새 사전 점검을 통과한 뒤 동일 원장 pair로 보호된 retry1을 시작했다. 원장을 다시 회전하거나 제품을 바꾸지 않았다. 단위 service의 exit0은 최종 rebuild 성공으로 집계하지 않는다. [retry1의 최종 결과도 PinVi ETL frontend 빌드 실패](evidence/rebuild-retry1.json)다. API와 digest 고정 web 빌드는 통과했지만 운영 generation은 바뀌지 않았다. API·ETL의 첫 parser 지시자를 기존 web과 동일한 digest로 고정했고 [관련 계약 102 PASS](evidence/root-pinvi-frontend-contract102.log)·[정확 새 후보 제품 CI 9 PASS](evidence/pinvi-frontend-exact-ci.json)를 확인했다. 이는 parser 재현성 보강이며 gRPC 종료의 단일 근본원인을 확정하지 않는다. 실제 새 pair 전환·live는 아직 미완료다. 두 리뷰어의 별도 [검사 하니스 리뷰·판정 보강](evidence/harness-audit.json)은 제품 FULL 리뷰와 구분하며, 실제 실행 결과를 대신하지 않는다.

[건강 점검 보강 후 동일 immutable manifest](evidence/manifest-health.json)의 SHA256은 `8400965df8171f1159fa9c6695024e6582e56d9d41f3adaa1beae00d3ed7b06d`다. Common 기준 `7dc1d6dda955b9b836cb3f24d6fd5bcd37fabe52`, Map 최신 main 기준 `a46d7b92c0e727805348e20d60fe188592e16477`, PinVi 기준 `07cfef222c56d7e648c81b017aa8ffe4ccd1c386` 대비 Common35/Map61/PinVi15 전체 111파일을 두 리뷰어가 별도 archive에서 검토한다. UI/token 산출물은 기존 dev.6의 byte-exact 복사이며 재pack하지 않았다.

두 관점의 원래 BLOCK과 중간 BLOCK을 최종 PASS에 소급하지 않는다. 원문은 각 `.json`의 `raw` UTF-8 bytes와 `original_sha256`으로 보존하고 읽기용 `.md`의 trailing whitespace만 정규화했다. Markdown의 현재 SHA는 `display_sha256`으로 별도 기록한다.

| 단계 | 복구·DB·메모리 | UI·인증·소비 계약 |
| --- | --- | --- |
| 원래 후보 acde/640 | [BLOCK](evidence/review-recovery-original.md) | [BLOCK](evidence/review-ui-original.md) |
| 중간 후보 72242/f93 | [BLOCK](evidence/review-recovery-postfix.md) | [BLOCK](evidence/review-ui-postfix.md) |
| 기능 후보 e4e27/aa265 | [FULL PASS](evidence/review-recovery-final.md) | [FULL PASS](evidence/review-ui-final.md) |
| fixture 정렬 24de4/aa265 | [FULL 연속 PASS](evidence/review-recovery-integration.md) | [FULL 연속 PASS](evidence/review-ui-integration.md) |
| 최신 main c4d62/aa265 | [FULL 연속 PASS](evidence/review-recovery-latest.md) | [FULL 연속 PASS](evidence/review-ui-latest.md) |
| frontend 고정 c4d62/2a36e | [FULL 연속 PASS](evidence/review-recovery-frontend.md) | [FULL 연속 PASS](evidence/review-ui-frontend.md) |
| standalone main 5ba33/2a36e | [FULL 연속 PASS](evidence/review-recovery-standalone.md) | [BLOCK: 빈 reply 건강 오인](evidence/review-ui-standalone.md) |
| 경량 health e0b5/6a54/2a36e | [BLOCK: nested metadata 타입](evidence/review-recovery-health.md) | [FULL 연속 PASS](evidence/review-ui-health.md) |
| metadata profile 99d8/b972/2a36e | [BLOCK: reserved map marker](evidence/review-recovery-health-schema.md) | [BLOCK: reserved map marker](evidence/review-ui-health-schema.md) |
| reserved marker a960/1ba6/2a36e | [FULL 연속 PASS](evidence/review-recovery-health-markers.md) | [FULL 연속 PASS](evidence/review-ui-health-markers.md) |

Map의 이전 exact CI는 glibc 1,137 PASS/1 FAIL/12 SKIP, Alpine 1,130 PASS/2 FAIL/18 SKIP이었다. Alpine의 추가 실패는 기존 공개 index EXPLAIN의 exact index 선택 단언으로, 운영 코드 변경과 무관하며 최종 동일 후보의 실제 CI는 [Alpine 1,132 PASS/18 SKIP·glibc 1,138 PASS/12 SKIP](evidence/map-exact-ci.json)으로 모두 통과했다. 두 lane에서 공통으로 실패한 schedule projection은 앱 전역 client를 주입하던 통합 fixture가 새 요청 단위 정책 뒤 실제 연결로 빠진 동일 원인이다. 두 fixture를 요청마다 새 모의 client로 바꿔 실제 middleware 정리를 유지하고 기존 assertion 310개를 보존·정상 schedule assertion 한 개를 추가했다. [관련 실제 PostGIS 22 PASS](evidence/root-map-integration-fixture22.log)를 확인했다. 이후 최신 main의 인계·resume 문서만 merge했다. 운영 Python/UI/Docker/spec은 기능 후보와 byte 동일하며 두 리뷰어가 전체 manifest 및 직접 실패·취소 검증의 재사용 범위를 명시했다.

최신 main #1304의 standalone code-server start·자식 로딩 probe를 merge했고 두 리뷰어가 source를 다시 검토했다. 한 리뷰어의 정상/load error/deadline 검증은 PASS였으나 다른 리뷰어는 실제 protobuf 빈 reply와 `{}`가 healthy로 통과하는 P2를 재현했다. 이 서로 다른 판정 원문은 보존하며 PASS로 합치지 않는다. Map은 새 Common의 설치된 생성 protobuf 기반 경량 점검을 채택하고 API·Dagster dependency pin을 동일하게 맞췄다. [Common 전체 120 PASS](evidence/root-common-health-python120.log)는 신규 actual wire/loopback/cap/channel 정리/no-Dagster-import 25개를 포함한다. [Map 관련 381 PASS](evidence/root-map-health-adoption-contract381.log)와 이후 [정확 CLI·봉인 10 PASS](evidence/root-map-health-cli-seal10.log)를 구분한다. 새 고정 111파일 독립 리뷰·실제 pair 전환/live는 진행 중이다.

경량 health e0b5의 한 독립 리뷰는 정상·빈 reply·deadline을 통과했으나 다른 리뷰는 null/미등록 pointer와 executable/entry point의 잘못된 타입이 실제 Dagster 역직렬화에서는 거부되어도 경량 설치 CLI에서는 정상으로 판정되는 P2를 재현했다. 양쪽 원문과 판정은 보존했다. 새 Common 99d8는 표준 module/file/package pointer와 nullable metadata 타입을 검사하며 stateful/custom typed metadata·미등록 필드는 fail-closed한다. 지원 범위는 Common 가이드 §10에 명시했다. [schema 변경 후 전체139 PASS](evidence/root-common-schema-python139.log)와 이후 실제 isolated CLI7건을 포함한 [health51 PASS](evidence/root-common-schema-cli-health51.log)는 서로 다른 실행이며 합산하지 않는다. [새 고정 manifest](evidence/manifest-health-schema.json)의 SHA256은 `b7c34eaffadfa3d4b58e435a9c4be9c36df7780c8fa339a476ae89be470e09cc`이며 전체111파일 두 독립 재리뷰·현재 CI·실제 재구축/live는 진행 중이다.

99d8 고정 후보의 전체 [146 PASS](evidence/root-common-schema-frozen-python146.log) 뒤 두 독립 리뷰 모두 metadata dictionary의 예약 serdes 키 우회를 P2로 재현했다. 새 Common a960는 versions/pointer map의 다섯 marker를 거부하며 정상 Map default repository 이름 `__repository__`는 허용한다. [새 전체 Python160 PASS](evidence/root-common-markers-python160.log), [health65 PASS](evidence/root-common-markers-health65.log)와 clean wheel/core-only 설치를 확인했다. Map의 pin 변경 직전 [동일 runtime 계약287 PASS](evidence/root-map-schema-runtime287.log)는 이전 b972 실행 증거이며 새 pin의 현재 CI·두 리뷰·실제 운영 gate와 구분한다. [현재 고정 manifest](evidence/manifest-health-markers.json)는 `3a001debb93c6656ca99bcaecea7ddcc083cdc2f6520168ca01963e3a1683a13`이며 전체111파일이다. 새 독립 리뷰·현재 CI·운영 재구축/live는 진행 중이다.

현재 a960/1ba6/2a36의 두 독립 FULL 리뷰가 PASS이며 metadata 타입·reserved marker P2는 모두 닫혔다. 복구 리뷰어는 별도 archive에서 전체160과 Map 봉인10을 직접 검증했고, 실제 own 설치 CLI23사례를 확인했다. UI 리뷰어는 health65와 실제 CLI26사례를 확인했다. 건강 검사65는 전체160의 부분집합이고 작성자·리뷰어 실행 수치는 합산하지 않는다. [Common 정확 후보 CI8 PASS](evidence/common-markers-exact-ci.json)와 [PinVi 제품 CI9 PASS](evidence/pinvi-markers-exact-ci.json)를 보존한다. [Map 현재 정확 CI10 PASS](evidence/map-markers-exact-ci.json)와 [두 PostGIS lane](evidence/map-markers-integration-ci-counts.json)도 통과했다. 보호된 paired 재구축은 진행 중이며 실제 runtime/live 성공은 아직 확정하지 않았다.

원래 findings의 수정은 API builder Git·frontend frozen vendor COPY, Hatch direct reference 허용, response/client 별도 정리 예산, 손상 collection과 repository 소속 fail-closed, 선택한 run의 기존 실패 원인/event cursor 조회, 검색 뒤 상세 job/run identity·상태·시간 상한 표시에 해당한다. 쓰기 run을 새 identity로 자동 복제하지 않고 기존 operation/lease/claim 복구 계약을 유지한다.

작성자 검증과 리뷰어 실행 수치는 합산하지 않는다. 로컬 전체 PostGIS의 첫 실행은 검증용 venv의 SQLAlchemy 2.1.3에서 기존 `Result.tuples()` 경고로 3 FAIL/1,129 PASS/18 SKIP이었다. 저장소 Docker/CI의 `docker/constraints-dagster.txt`(Dagster 1.13.24·SQLAlchemy 2.0.54)에 검증 환경을 정렬한 전체 재실행은 [1,132 PASS/18 SKIP](evidence/root-map-pinned-integration1132.log)이며 이전 실패를 PASS로 소급하지 않는다. 기존 공개 index EXPLAIN도 이번 실제 PostGIS 실행에서 통과했다. 최종 API 1,236 PASS([원문](evidence/root-map-api1236.log)), UI 391 PASS([원문](evidence/root-map-ui391.log)), PinVi probe 38 PASS([원문](evidence/root-pinvi-probe38.log)), strict Map 96/PinVi 247, production Next build·React Doctor 0 diagnostics가 통과했다. 초기 Map 전체 4,199 PASS/4 FAIL/25 SKIP, 이후 package 1,929 PASS/2 FAIL/3 SKIP은 fixture·계약 검사·upstream Beta warning 경계의 실패로 별도 남겼고 focused closure 및 전체 API/정확한 CI로 다시 확인한다. 첫 CI Docker Git/vendor 누락, Hatch clean metadata 실패와 수정 뒤 성공도 같은 숫자로 합산하지 않는다.

[메모리 비교](evidence/memory-allocation.json)는 동일 lazy synthetic 5,000건·raw 8KiB에서 전체 list의 Python 최고 할당 42,325,367 bytes, 100건 batch 1,701,991 bytes를 확인했다. [재현](evidence/memory-allocation-probe.py)의 대상 자산 코드는 최종 제품과 동일하다. provider 자체 내부 buffer·변환기 전체·PG·프로세스 RSS 측정은 아니다. 실제 snapshot 적재는 기존 단일 transaction·완료 후 한 번 봉인을 유지한다.

[건강 점검 import 메모리](evidence/health-import-memory.json)는 같은 Linux Python/Dagster1.13.24의 fresh process 각 3건에서 경량 import+합성 정상 reply decode 최고 RSS 36,904–36,992 KiB, 전체 Dagster import 68,452–68,576 KiB였다. 실제 운영 컨테이너 RSS·live RPC workload·provider/PG 메모리 비교는 아니다.

[현재 건강 점검 import 메모리](evidence/health-markers-import-memory.json)는 같은 조건의 a960 source에서 경량 점검 36,976–37,092 KiB, 전체 Dagster 68,360–68,596 KiB다. 이전 e0 측정은 별도로 보존했고 두 수치 모두 운영 컨테이너/live workload 측정은 아니다.

[native 장애·복구](evidence/native-recovery.json)는 별도 로컬 SQLite, 실제 gRPC DefaultRunLauncher/multiprocess worker, Dagster 1.13.25로 실행했다. [원문](evidence/root-native-recovery.log)과 [probe](evidence/native-recovery-probe.py)를 보존했다. op 예외·step 프로세스 exit9는 FAILURE 후 동일 job 수동 재실행 SUCCESS. 60초 sleep run은 10초 runtime tag를 native monitor가 확인해 FAILURE로 종료했고, 동시 정상 run과 뒤 수동 재실행은 SUCCESS이며 active coalescing은 해제됐다. 종료에는 launcher의 정리 대기도 포함되므로 10초 정확 종료를 주장하지 않는다. monitor 함수는 probe가 호출했으며 실제 공유 production daemon·Dagster 1.13.24·업무 PG·provider 수집·운영 worker kill 검증으로 집계하지 않는다.

probe의 실제 실행/하니스 검토 원문은 각 `.py.source.json`의 `raw`와 SHA256으로 보존했다. 읽기용 `.py`만 import/줄바꿈을 정리했으며 context 경계·증거 파일 정리는 원문을 유지한다. 운영 probe를 바꾸거나 이전 실행을 새 실행으로 집계한 것이 아니다.

후속 gate는 sanctioned pair rotation/guarded rebuild의 성공·schema/source/image 확인, 실제 로그인 POST200+cookie·공통 로그인/메뉴/Dagster 패널·Chromium/Firefox desktop/mobile·D1/D2 및 PinVi operating live, exact CI green, Common→Map→PinVi PR merge다. 기존 vNext consumer receipt의 pending은 이번 결과만으로 근거 없이 완료로 승격하지 않는다.

### 2026-10-06 builtin 수정 전 운영 재구축

[세 번째 실제 재구축](evidence/rebuild-markers-third-negative.json)은 ETL의 digest 고정 외부 frontend가 종료되어 실패했다. 앞선 5개 이미지 빌드는 완료됐으나 운영 반영/live 성공은 아니다. 기존 6개 서비스와 generation은 유지됐다. API/ETL의 불필요한 외부 frontend를 제거한 PinVi `0058369c` 수정의 새 운영 재구축은 아직 NOT_RUN이다. 이전 본문의 RUNNING은 해당 시점 진행 기록이며 최종 결과는 이 실패 기록이다.
