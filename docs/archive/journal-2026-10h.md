# journal 아카이브 — 2026-10

[현행 기록](../journal.md)에서 docs/tasks-rule.md §8에 따라 완전한 절을 원문 그대로 분리했다. 읽기 전용 이력이다. 상대 링크만 `docs/archive/` 기준으로 다시 썼다.

## 2026-10-24 — 공용 지도 작업면 채택 후보

Feature 지도의 종류 필터에 아이콘을 결합하고 필터·보기 탭·건수/실제 좌표·줌·상세 오버레이를 공통 컴포넌트로 소비한다. Map의 기본 종류·소스·상태 필터와 조회 동작은 보존한다.

후속 UI에서 설명은 제목의 정보 버튼, 상태 필터는 `추가 필터`로 접고 select를 176×30px로 통일했다. 지도 높이를 유지하면서 375px 지도 시작을 651.75→439.25px로 앞당겼다. 다른 화면의 기본 여백·도움말·모바일 메뉴는 유지한다.

main `0b2dc53d0`을 추가 통합하고 두 작업 기록을 양쪽 보존했다. 독립 리뷰의 상세 키보드 포커스 이탈을 수정했다: 진입 포커스·예약 프레임 취소·Escape/닫기 후 마커/지도 탭 복원, point/가격 DOM 마커 Enter·Space 활성화. WSL 타입·frontend 49파일 400건·전체 ESLint PASS. n150 Playwright 1.64.1 지도 E2E 6건(375/1440px 키보드 2건 포함) PASS, 기존 실측·GeoJSON 검증의 레이아웃/worker 계약도 유지한다. Python/API/계약은 최신 main 그대로이며 lock 변화는 없다. [정산](../reports/2026-10-24-shared-map-ui.md). 다음은 통합 담당자의 CI·두 독립 재리뷰이며 자체 운영 빌드·배포는 하지 않는다.

## 2026-10-24 — 가격 추이 프록시 transport T4 정렬(T-STATE-01-T4): 브랜치 `feat/transport-fuel-price-history-t4`

- 원인: #1355 프록시는 transport T4가 확정되기 전 가정 모양(top-level `natural_key`·`generated_at`·`truncated`, 행별
  필수 `collected_at`)을 파싱하고 `product_code`·`since`·`until`로 보내 — transport는 그 질의를 무시하고 정상 응답은 모두
  `upstream_contract`가 됐다. transport 정본: origin/main `9974d25`의 `backend/app/services/export_price_history.py`·
  `docs/map-service-price-history.md`(질의 `product`/`from`/`to`/`limit` 기본 1000·최대 5000/`cursor` ≤4096, 창 기본 30일·
  최대 366일·미래 금지, 응답 `meta{generated_at, source_collected_at, source_status, item_count}`·`station_key`·`items[
  product_code, observed_at, price]`·`next_cursor`·`has_more`, cursor HMAC 서명·첫 페이지부터 15분·수집 revision 고정,
  revision 변경·만료 409, 변조/다른 필터 cursor·창 위반 422, 성공 근거 없음 503 + meta, 휴게소 이력 501, 오류는 problem+json).
- 실측(n150 Map Dagster code-server 컨테이너의 transport env로 읽기 전용 GET, odroid `<prod-host-ip>:12301`): 주유소 하나
  30일 5행(유종 5개, null 가격 3), `source_status=stale`(opinet 수집 10-21 이후 미성공 — 주유소 export 목록은 503),
  `limit=2` 두 페이지 cursor 정상(486자), 변조 cursor 422·다른 product cursor 422·미래 `to` 422·naive `from` 422·없는 키
  404·휴게소 501, gzip·weak ETag·`private, no-cache`. **Map API 컨테이너에는 transport 주소·토큰·플래그 env가 아직 없다**
  (Map service `/v1/service/transport/fuel-stations`도 503 — Valkey 미적재).
- 설계: cursor는 불투명 전달(Map이 해석·서명하지 않음), 응답 `history.has_more`·`next_cursor`(+ `meta.page` 미러),
  `truncated`=has_more 호환. 이유 enum에 `upstream_unsupported`(501)·`request_rejected`(422)·`upstream_timeout` 추가.
  (처음엔 cursor 요청의 transport 409를 200 + `reason=cursor_expired`로 했다 — 아래 리뷰 반영에서 HTTP 409로 바꿨다.) 파서는
  `station_key` 일치·`item_count`=행 수·`has_more`⇔`next_cursor`·`observed_at` 내림차순을 확인한다. 행별
  `collected_at`·`provider_updated_at`은 nullable(지금 항상 null, 응답 시각으로 채우지 않음). limit은 페이지 전체 행 수.
- OpenAPI: service·admin 재생성, vnext receipt·diff baseline 재핀(service schema_changes 1건). 관리자 `types.ts` 재생성 —
  main frontend CI가 `npm audit`(next critical)에서 먼저 멈춰 #1355의 `/v1/service/transport/*`가 types에 빠져 있었다.
  user OpenAPI·user-client 타입 불변.
- 검사(n150 일회용 python:3.13, CI 설치 레시피): openapi `--check`·ruff·mypy --strict(271 files)·lint-imports 초록.
  첫 head: unit+lint+api+dagster 5,502 passed·26 failed, Valkey 통합 28 passed + 1 Docker API ReadTimeout(재실행 통과).
  **리뷰 반영·리베이스 뒤 최종 head(`553e9f3f`)**: openapi `--check`·ruff·mypy --strict(272 files)·lint-imports 초록,
  unit+lint+api+dagster 5,524 passed·26 failed — 전부 알려진 환경 실패(docker runtime 23·sealed tree 2·smoke settings 1),
  Valkey 통합 28 passed. router 검사 80개(이 PR 추가분 포함).
- PinVi 영향(읽기만, origin/main `3e1e8bc0`): `apps/api/tests/contract/kor-travel-map-openapi-service.json`을 vendor하고
  `test_kor_travel_map_transport_contract.py::_EXPECTED_QUERY`가 price-history query를 `{product_code, since, until,
  limit}`로 핀한다 → 재vendor 시 `cursor` 추가 필요. `PRICE_HISTORY_REASONS`가 옛 6개라 새 이유는 `upstream_contract`로
  접힌다(깨지진 않음). PinVi는 `since`만 보내 30일을 기본 limit 200(이제 전체 행 수)으로 받고 `truncated`를 그대로 쓴다.
- 적대 리뷰 2회 반영(차단 없음): ① 가격은 JSON number/null·유한만(`_decimal` 공통 유한 검사, NaN 상수 거부) — 전엔
  NaN·`1e400`이 응답 직렬화로 갔다. ② transport 503 problem `meta.source_status=failed` → `upstream_no_collection`.
  ③ 보낸 `product`·`from`·`to`와 다른 행은 `upstream_contract`(보내지 않은 끝은 추측하지 않음). ④ 본문 2 MiB 상한
  (Content-Length·스트리밍)·`RecursionError`. ⑤ 소유자 승인으로 cursor 요청의 transport 409를 HTTP 409
  `TRANSPORT_PRICE_HISTORY_CURSOR_EXPIRED`로(`cursor_expired` 이유 제거; 첫 페이지는 늘 200 + 현재가). ⑥ OpenAPI에
  "unavailable·has_more=false는 끝이 아님", 다음 페이지 `product_code` 동일·`since`/`until` 생략 또는 동일(transport
  코드 확인: 창은 cursor에 고정되고 보낸 값은 같아야 하며 product는 생략도 불일치다). ⑦ 운영: Manager compose
  `kor-travel-map-api`(72ee710 1659행~)에 transport 변수 자체가 없어 compose PR이 필요하고, pair 회전 preflight
  (`_PAIR_SURFACE_PATHS`)가 PinVi 재vendor 전 회전을 거부한다 → Map 머지 → PinVi 재vendor → 회전. #1357·#1360·#1362 위로
  리베이스. 두 페이지 검사의 2쪽 행이 요청과 다른 유종(D047)이어서 새 행 검사가 빨갛게 잡았다 — 검사 자료를 고쳤다.
- 재리뷰 반영(head `58352857` 기준): F1 — httpx `aiter_bytes`는 gzip 조각을 통째로 풀어(64 KiB → 67 MB) 2 MiB 상한이
  뚫렸다 → 요청 `Accept-Encoding: identity`, `aiter_raw`로 붙이기 전 상한, gzip이 와도 출력 상한 `zlib`. N1 — 깨진·잘린
  gzip·모르는 인코딩·`DecodingError`는 `upstream_contract`. N2 — 상태 코드 먼저, 200만 전체·503만 64 KiB, 그 밖은 본문을
  읽지 않아 큰 오류 본문도 상태로(cursor 409 유지). N3 — 200의 `source_status=failed`는 계약 위반, 공개 enum `ok|stale`.
  검사 대역 함정: `httpx.Response(content=…)`는 생성 때 미리 읽혀(gzip이면 그 자리에서 풀어) `aiter_raw`가
  `StreamConsumed`를 낸다 — 원문 stream(`httpx.ByteStream`)으로 다시 싸는 `_mock`을 두었다. #1368 위로 리베이스.

## 2026-10-24 — geo 재시도에 ReadError·WriteError 추가: 브랜치 `fix/geo-retry-readerror`

- 등산로 run `18c4c1d7`(22:12Z)이 선조회 중 `GeoRequestError: transport 실패: ReadError` 한 번으로 두 시도(1h24m·37m)를 잃었다
  (keep-alive 연결이 요청 도중 끊김). #1357 일시 장애 재시도는 ReadTimeout·RemoteProtocolError만 다시 보냈다 —
  ReadError·WriteError도 적재 client(opt-in)에서 총 3회까지 다시 보낸다. 연결 수립 실패는 여전히 제외.

## 2026-10-24 — ADR115 shadow 실제 수집 연결: 명시 scope·MCST 이름

- revision+provider/dataset allowlist가 모두 있을 때만 기존 native TX 안에서 shadow를 기록한다. 실제 MCST 이름만 supplied로 선언하며 Geo/파생값/DTO null은 추측하지 않는다.
- 기본OFF/정책seed0/운영0. 기존 Feature ID/effective/전역 잠금 의미를 유지한다. [연결·실패·미완 gate](../reports/2026-10-24-provider-field-shadow-hook.md).
- 실제client PG/기존MCST·대기 집중검증을 진행하며 CI/두 리뷰/HTTPUI는 별도 수용한다. 전체 membership/winner/Geo/scope 분할은 미완이다.

## 2026-10-24 — ADR115 T-CWRITE-02: 불변 정책과 shadow 후보 기반

- 전체 CI의 ORM metadata/runtime preflight 누락을 보완했다. shadow CHECK/FK/index를 metadata에 정합화하고 recorder 정확 signature만 허용한다. 정책 등록/직접 DML 차단과 경고 검사는 유지하며 실패한 테스트 engine 회수도 검증한다.

- 완결 fieldset을 원자 등록하는 불변 정책 header와 source별 typed shadow recorder/ACL을410에 추가한다. 등록은 global-first이며 RR에서 새 revision이 보이지 않으면 실패한다.
- 실제 native 수집 hook/settings는 별도 후속으로 분리했다. 공개 winner/effective/전역 잠금 범위는 유지하며 기본OFF/운영0이다. [범위·교착/RR·미완 gate](../reports/2026-10-24-provider-field-shadow.md).
- 정책/전체 membership·Geo·winner 활성·scope/epoch/manifest와 최종 CI/두 리뷰·HTTP/UI 수용은 미완이다. 첫 기반 단위를 전체 동시 쓰기 완료로 세지 않는다.

## 2026-10-24 — ADR115 선행: 같은 transaction fence 재진입 SQL 절감

- 실제 root session/connection transaction·오류 stamp가 유효한 동안만 전역 fence를 재사용한다. savepoint 획득은 캐시하지 않는다. 전역 충돌 범위·병합 의미는 유지한다.
- 기존 집중27/새 실제PG10 PASS, 변경 Ruff/strict mypy PASS. [범위·실패 규약·검증 한계](../reports/2026-10-24-curation-fence-reentry.md).
- T-CWRITE-01 전체 기준선 및02~09는 미완이다. 다음은 두 독립 리뷰·CI·실제 HTTP/UI 수용 후 후보/winner와 scope gate의 작은 코드 단위를 이어간다. 운영 미배포.

## 2026-10-24 — 수집 CI 선행 Next 보안 게이트 복구

- Next 및 직접 ESLint 플러그인을 최소 수정 버전 16.4.1로 pin했다. npm12 배포
  audit의 critical 1건이 0건으로 줄었다. 기존 dev moderate2/high6은 변경하지 않았다.
- 기존 정본 OpenAPI와 생성물 drift를 공식 기존 generator로 정합화했다. admin395/marker4
  단위·타입·lint·실제Sharp변환·production build PASS. 독립 리뷰/CI는 진행 중이며 운영 변경은 없다.
  상세: [검증 기록](../reports/2026-10-24-next-security-gate.md).

## 2026-10-24 — 멈춤 진단 오탐 정정: 브랜치 `fix/stall-watchdog-progress`

- #1357 배포 뒤 MCST run `c0f91a7c` **성공**(12:04Z 시작, 9,634초): geo 호출 36,905건(reverse 35,852·region 1,053),
  저장값 재사용 skipped=45,930·geocoded=53,276·fallback=21. 이전 실패(6시간 상한)·멈춤 해소.
- 그러나 watchdog이 15분마다 "I/O 없이 멈춤"을 남겼다(스택은 진행 중인 prefetch task). 원인: `/proc/self/io`의
  `rchar`/`wchar`는 소켓 송수신을 세지 않는다. 수정: geo 왕복·상류 요청·SQLAlchemy 문장이 `core.activity`를 표시하고
  watchdog이 그것도 진척으로 본다. 경고는 run당 한 번. 이어서 등산로 적재 시작.

## 2026-10-24 — 여섯 프로젝트 npm 보안·버전 정합

- 이 저장소의 기존 프론트엔드/공용 테스트 399개와 타입·린트·빌드 PASS. [버전·예외·검증 범위](../npm-security-alignment-2026-10-24.md).
- Popper 사전 리뷰 P1: Playwright 이미지와 세 실행 helper의 이전 digest 불일치를 수정했다. Docker FROM·버전·digest 길이·helper 동등성 회귀 검사를 보강했고 관련 55개 테스트가 통과했다. James 사전 리뷰의 추가 결함은 없었다.
- 직접/전이 npm 의존성과 잠금 파일을 갱신하고 여섯 프로젝트의 공통 버전을 맞췄다.
- 호환성 예외·미수정 상류 권고·검증 범위는 [정합 기록](../npm-security-alignment-2026-10-24.md)을 따른다.
- 소스·잠금 파일 정합과 WSL 검증을 완료했다. 최종 CI·두 독립 확인·N150 후보 UI 게이트와 머지 상태는 [PR](https://github.com/digitie/kor-travel-map/pull/1368)에서 정산하며 통과 확인 전 머지하지 않는다.

## 2026-10-23 — MCST 6시간 상한·멈춤: 브랜치 `fix/mcst-geo-stall`

- prod: MCST run(06:02Z 시작)이 3.5시간 이벤트 0건. step 프로세스 생존, `/proc/<pid>/io` rchar 60초 불변, geo·DB 소켓
  대기 요청 없음, Map DB 비-idle 세션 없음, py-spy main thread는 이벤트 루프 `select`에서 idle → 소유자 승인으로 취소.
  py-spy는 coroutine 스택을 못 보여 멈춘 줄은 미규명.
- 재현(같은 code-server 컨테이너, DB 쓰기 없음): 수집 14초(13 dataset·104,301행·실패 0). 변환은 순차 역지오코딩 초당
  약 4.6건 → 6시간 초과 예상. 445초에 `/v2/regions/within-radius` 504 한 번으로 종료(odroid load 15~17, transport
  code-server 134%·공용 PG 97%·root chrome).
- 수정: 재사용 helper 선조회 동시성(기본 2), 적재 geo client 일시 장애 총 3회 재시도(opt-in, 논리 요청당 1회 계수),
  적재 step I/O 정지 900초 시 task 스택 WARNING. 적대 리뷰 2회 — 반영: watchdog이 자기 읽기로 영원히 안 울리던 결함
  (HIGH), 재시도 범위를 API까지 넓힌 것(opt-in으로 축소), 시도마다 계수(분모 부풀림), 캐시 크기, 로그 실패 격리.
  받아들인 것: 동시 geo 부하 증가·재시도 증폭(env로 1), 토큰 없는 run은 순차. 리뷰가 든 등산로 seal jsonb 천장은 #1256(ADR-099 1단계, 행별 digest)로 이미 해소.

## 2026-10-23 — geo 부하 줄이기 0단계(ADR-116, T-GEOLOAD-00): 브랜치 `feat/skip-geocode-unchanged`

- 소유자 결정(2026-10-23): ADR-108의 "payload가 같은 행은 지오코딩하지 않는다"를 비-MOIS 적재 전부로 넓힌다. prod는
  주차장 17,045 좌표에 run마다 reverse 17,638회·MCST 22~28k·등산로 약 57k를 불러 odroid geo가 ReadTimeout을 냈다.
- prod 읽기 전용 실측(공용 PG `kor_travel_map`, READ ONLY transaction): 비-MOIS dataset별 좌표 있는 active·스탬프
  `called`·현재 토큰 수, 직전 적재들 사이 payload가 바뀐 기존 행(주차장 878/17,795 ≈ 5%, 박물관 24, 축제 51, 관광지 9,
  MCST 세계음식점 8), 6자리 좌표를 나눠 쓰는 행(주차장 1,176, 국가유산 920, MCST 504), 주소 열 override 0건. MCST 13개 중
  적재된 것은 1개, 등산로는 미적재(seal 천장) — 그 dataset들은 첫 성공 적재 뒤부터 준다.
- 설계: 역지오코더는 좌표만 받아 record를 모른다 → 공통 helper가 변환을 두 번 돌린다(빈 답 pass 0으로 identity·payload
  hash·좌표 → fence 없는 조회 → 좌표 표 → 저장값/실제 geo를 섞은 pass 1 → 사후 확인). 조건은 `load_bundle`이 주소 열을
  쓰지 않을 조건과 같다(head payload hash·스탬프 `called`+현재 토큰·좌표 float8 일치·active·주소 override 없음).
- 설계 적대 리뷰 1회(HIGH 0·MED 4·LOW 6), 코드 적대 리뷰 2회(A: HIGH 0·MED 1·LOW 6, B: HIGH 0·MED 2·LOW 6) — 반영과
  받아들인 것은 ADR-116 끝 두 절. 주요 반영: 재시도 답 기억, 옛 저장 jsonb fallback, DTO key 대신 hash 비교, 안전망
  `disabled`·조회 실패 `lookup_failed` 계수, 조회 savepoint 격리, `MATERIALIZED` 입력, 재사용 뒤 현재 geo 데이터셋 재관측
  (run 도중 릴리스), helper 우회 lint.
- 검사(n150 일회용 python:3.13 컨테이너, CI 설치 레시피): ruff·lint-imports·mypy --strict(core·dagster) 초록. unit+lint+dagster
  4,174 passed — 실패 29건은 main `e9d0e53c` 기준선과 같은 환경 실패(docker runtime 23·sealed tree 2·tick window 3·
  smoke settings 1). 통합 66 passed(새 `test_geo_reuse_load_path` 8건 — 조회 술어 6·실제 client spool(연결 1개, Dagster runtime
  login)·큐 결합 client — + 기존 geo 릴리스·spool fence·스탬프·dagster ETL). 처음 돌렸을 때 통합이 빨갛던 원인은 검사 자료가
  같은 좌표를 나눠 쓴 것(저장 원문 주소가 갈려 설계대로 재사용 제외)과 bundle 비교에 생성 시각 필드가 섞인 것이었다.
- 변이 검사 17개 중 16개 빨강(술어 4·안전망·답 기억·토큰·evidence·옛 저장값·사후 확인·검증·재관측·lint). 공유 좌표 두 변이
  (M5·M6)는 처음에 초록이었다 — 사후 확인이 재시도로 덮어 결과가 같았다. 변환 횟수를 세게 고쳐 빨강. pass 1 evidence
  사후 확인(M17)은 그것을 만드는 provider가 없어 대상 검사 없음(잠재 방어).
- prod 읽기 전용 `EXPLAIN (ANALYZE, BUFFERS)`(`plan_cache_mode=force_generic_plan`, 주차장 1,000행 입력): `resolved`
  MATERIALIZED에서 출발해 features·heads·records·stamps 모두 PK 인덱스 nested loop, 재사용 질의 부분 약 80 ms.
- 원장: acceptance §T-GR-01·T-GR-02를 도구로 아카이브(체크박스 111건 보존, 216,928 → 208,855 bytes) 뒤 §T-GEOLOAD-00 추가.

## 2026-10-23 — ADR-114 1단계: transport 현재 상태 Valkey·service REST: 브랜치 `feat/adr114-valkey-transport`

- 설계: ADR-114에 "구현 설계 — 1단계"(D1~D7)를 적었다 — 데이터셋 5개, 세대 키(`ktm:state:v1:{ds}:{gen}:{meta,items,ids,geo,lookup}`)
  와 포인터(`current`·`previous`·`recent_counts`·`lock`), Lua 한 번의 compare-and-set + 개수 검사 교체, build TTL·grace TTL,
  최근 6세대 최대·절대 하한 기준 비정상 집합 거부, 세대별 신선도, service REST·가격 추이 프록시. id는
  `make_feature_id(bjd_code=None)`(VWorld 블록이 와도 바뀌지 않게).
- 설계 적대 리뷰 1회: HIGH 4(같은 id 행이 개수 검사를 영구 실패시킴, BYBOX 폭을 중심 위도로 재면 모서리 누락, 스키마 버전
  교체 뒤 옛 키 잔존, 개수 검사가 교체 밖) · MED 6 · LOW 5 — 가격 추이 플래그 제거 의견 외 전부 반영(ADR 절 끝).
- 구현: `infra/valkey_state.py`·`dto/transport_state.py`·`providers/kor_travel_transport_state.py`·Dagster
  `transport_state.py`(job·schedule 5쌍, 기본 STOPPED)·API `routers/service_transport.py`·`transport_state_service.py`.
  의존성 `redis>=7,<8`(이미지 핀 7.4.1). transport fetcher에 `on_collected_at`. 기존 PG transport 적재는 그대로.
- 코드 적대 리뷰 2회(ADR-114 "코드 리뷰" 절): 1차 HIGH 1(override 한 번으로 거부가 끝나지 않음)·MED 3·LOW 8, 2차 HIGH 0·
  MED 4·LOW 9 — 하한 추정치 실측(배포 시 acceptance) 외 전부 반영.
- OpenAPI: service·admin 재생성(user 불변), vnext `openapi-diff-v1`·`consumer-rollout-v1` receipt 재핀 — **PinVi admin·
  service 재vendor 필요**.
- 검사(n150 일회용 컨테이너, CI 세션 경계): unit·api·dagster·integration 초록(남은 실패는 main `bc5ab503` 기준선과 같은
  환경 실패 — docker runtime 23·sealed tree 2·bootstrap 19·docker ledger 2). 새 통합 검사는 Manager와 같은 digest의
  Valkey 9.0으로 돈다. 변이 검사: 핵심 가드 15개(CAS·개수 대조·PERSIST·grace·최근 최대·빈 집합·cursor 세대·NX 잠금·
  응답 유실 정리·bbox 폭·절대 하한·옛 버전만 정리·override 초기화·세대 재확인) 전부 빨강.
- Manager #544(Valkey) 머지 확인: run worker는 code-server 자식이라 URL을 상속한다. Map API에는 transport 주소·토큰이
  없어 가격 추이는 그 env 전까지 `not_configured`.
- 원장: acceptance §T-GR-05·T-GR-06을 도구로 아카이브(체크박스 100건 보존). `tasks.md`의 번호 없는 outage 보류 항목이
  T-CWRITE-09 본문으로 세어져 main CI가 빨갰다 — entry 앞으로 옮겼다.
- 배포 의존: Manager Map Valkey 서비스 PR(`feat/map-valkey`, 포트 12704, `KOR_TRAVEL_MAP_VALKEY_URL`), API에 transport
  주소·토큰, transport `price-history` export(브랜치 `feat/service-price-history`) 배포 뒤 플래그 켜기.

## 2026-10-23 — ADR-115 실제 동시 쓰기 설계·작업 원장

- 근거: main `cdd2614007a86e8627949cd1176c61eb14c0ce3e`. 단순 dataset별 advisory 교체로는
  공유 Feature·source/link 역순 잠금·root/candidate seal·과거 lock table 고갈 문제가 해결되지 않음을 반영했다.
- 문서: dataset/지역 scope와 Feature 행 충돌 분리, 결정적 provider 후보 winner, override/retire/merge,
  manifest 재검증·epoch fencing·SERIALIZABLE root·호환 gate·원자적 snapshot·롤백·실측 수용을 작성했다.
- 원장: T-CWRITE-01~09 및 각 acceptance를 등록했다. Map 코딩은 진행 중 Weather·Transport 작업 뒤다.
- 독립 적대 리뷰 반영: partial head carry-forward의 값 원문/검증 head 분리, 전체 활성 후보 복원,
  원자적 정책 활성화, 지역 누락과 전역 소실 구분, 다중 SELECT snapshot, Geo 그룹 winner/stamp
  lineage를 설계·해당 acceptance에 함께 보강했다. ADR 색인의 다음 번호를 처음 115로 맞췄고, 아래 main 동기화에서 116으로 갱신했다.
- 재리뷰 반영: 배타 fallback/flag OFF는 잠금만 전역화하며 active 후보/winner 의미를 유지한다.
  직접 base legacy writer는 DB 거부하거나 scope policy cutover를 차단하고 A winner/B fallback/OFF
  fixture를 T-CWRITE-03·04·09에 명시했다. gate만으로 의미 안전성을 주장하던 문장을 제거했다.
- main `952ceb659`(PR #1352, Valkey 설계 문서)와 merge 충돌을 해결하며 선점된 ADR-114를
  보존하고 본 설계를 ADR-115/다음 후보 116으로 변경했다. main의 기능 코드 변경은 0이며
  PG 잔존/퇴역 writer와 별도 Valkey 세대 경계를 설계·T-CWRITE-01 수용 조건에 명시했다.
  후속 main `beec86812`(#1353)의 Weather 반나절 요약 문서도 추가 merge해 보존했다.
- 검증: 문서/코드 근거·링크·원장 정합만 점검한다. 사용자 지시대로 CI를 실행하거나 기다리지 않는다.
  실제 코드·schema·서비스 변경과 성능 실측은 아직 없으며 문서 PR 완료와 구분한다.

## 2026-10-22 — T-LOAD-LOCK-WAIT 2안(ADR-113): 스트리밍 snapshot은 다 받은 뒤 짧게 쓴다: 브랜치 `fix/short-curation-lock-hold`

- 원인(1안 PR 실측): `load_feature_bundle_batches`가 transaction을 먼저 열고 stream을 당겨, 첫 batch가 잡은
  `feature-curation-write`를 나머지 fetch·역지오코딩 내내 쥐었다(주차장 run `71f21b6a` 9,141초+, 대부분 `idle in transaction`).
- 수정: stream을 DB session 없이 끝까지 받아 pickle spool(임시 파일, 메모리는 batch 하나)에 쌓고, 그 뒤 쓰기 transaction
  하나로 같은 batch·같은 순서로 쓰고 같은 transaction에서 seal을 읽는다. 받기 실패는 transaction을 열지 않는다. client 한
  곳이라 Dagster asset 8개와 큐 경로가 함께 고쳐진다. 쓰기 시간·spool 크기는 INFO 로그.
- 설계 리뷰(적대 1회): H1 쓰기 단계 근거 → 실측·로그·재적재 300초 재검토 조건, H2 `provider_run_lock` 표 오류 → 고치고
  같은 dataset 동시 실행 비용을 결정 5로 받아들임, M1 쓰기 재시도 안 함(결정 6), M2 큐 경로 executor transaction은 받는
  동안 `idle in transaction`으로 남음(결정 4·tasks 기록), M3 geo 토큰은 run 전체 관측으로 판정(단위 검사).
- 실측(n150 일회용 PostGIS, 축제 3,000건): 첫 적재 32.4건/초, 재적재 140건/초 → 주차장 1.9만 건 쓰기 약 580초(첫 적재)·
  약 135초(재적재). 그 밖 7개 dataset은 1분 안쪽.
- 검사(n150 일회용 컨테이너): 단위 7(사건 순서·실패 시 transaction 없음·빈 stream seal·geo 토큰·메모리·실 bundle 왕복·spool), 통합 2(받기가 멈춘
  동안 다른 연결이 fence를 2초 안에 잡고 그 연결이 쥐는 동안 쓰기는 기다림·seal = commit된 image seal, 큐 결합 client).
  변이(stream을 transaction 안으로 되돌림): 관련 5건 전부 빨강(통합은 다른 writer 55P03 → 대기 timeout, 큐는 fence 보유).
- 코드 리뷰(적대 2회): HIGH 없음. MED — 로그가 fence 대기까지 보유로 셌다(→ fence를 먼저 잡고 대기·보유 분리, 실패도 기록),
  쓰기가 fence 아래라는 단언이 느린 runner에서 거짓 초록일 수 있다(→ `pg_locks` 미부여 대기 확인). LOW — 메모리 주장
  weakref 검사, 실제 bundle spool 왕복, 실패를 55P03으로 드러냄, tasks 항목 길이, journal 분리.
- 문서 한도: acceptance §T-GR-04를 도구로 아카이브(체크박스 53건 보존, 214,915 → 205,558 bytes). journal 2026-09-28~29
  6건을 `archive/journal-2026-09g.md`로(본문 바이트 보존 — 옮긴 줄 블록이 아카이브에 그대로 있고 live에 없음을 스크립트로 확인).

## 2026-10-22 — T-LOAD-LOCK-WAIT 1안: 적재가 fence를 길게 기다린다: 브랜치 `fix/load-curation-lock-wait`

- 증상: n150에서 동시 적재 다섯(seoul_bookstores·krforest_arboretums·standard_tourist_attractions·krforest_dulle_trails·
  visitkorea_enrichment)이 `feature-curation-write`를 Dagster 엔진 `lock_timeout=30000` 안에 못 얻어 55P03으로 3회 재시도 끝에
  실패했다. 매 재시도가 fetch·역지오코딩(약 5분)을 다시 하고 30초 만에 죽는다.
- 1안(소유자 결정): client 적재 transaction의 **첫 fence 획득 한 문장만** `lock_timeout`을 900초(env, 0=끔)로, 필요하면
  `statement_timeout`을 +60초로, `client_connection_check_interval`을 10초로 `SET LOCAL`하고 직후 되돌린다. 늘리기만 한다.
  무장 대상은 단위 검사의 분류표가 정본이다(적재 12개 무장, 정리·관리·offline upload·MOIS CLI 11개 비무장).
- 적대 리뷰 2명: HIGH 없음. MED — FIFO 잠금 줄이라 적재가 이어 잡으면 단건 writer·root 완결의 틈이 준다(문서화),
  900초는 아래 실측 보유를 못 덮는다(문서화), 무장 범위 검사가 둘뿐(→ 분류표). LOW 반영: 실패 로그, 연결 확인, 통합 holder 회수.
- 2안 입력(읽기 전용 실측, 공용 PG `pg_locks`·Dagster event log): 07:11~ 표본에서 fence 보유자는
  `standard_parking_lots`(run `71f21b6a`) — transaction 06:06:05 시작, 80분 넘게 `idle in transaction`. 스트리밍 snapshot
  경로(`_load_snapshot_batches` → `load_feature_bundle_batches`)가 100건 batch마다 upstream fetch와 역지오코딩을 **열린
  transaction 안에서** 한다(batch 사이 공백 최대 85초, DB 쓰기는 몇 초). 같은 경로가 8개 asset. 그 동안
  `finalize_provider_curation_root`가 30초마다 fence에서 55P03. 2안은 fetch·지오코딩을 transaction 밖으로 빼고 쓰기만 짧게.
- 검사(n150 일회용 컨테이너): 새 단위·통합 초록(40초 holder: 무장 성공·끈 쪽 30초 55P03·5초 writer 5초), api 1251·dagster 826·
  관련 통합 23 초록, mypy·lint-imports 초록. 변이 검사와 unit 세션 main 대조는 PR 본문.
- 문서 한도: acceptance §T-GR-03을 아카이브로 옮겼다(도구 검산 53건 보존).
