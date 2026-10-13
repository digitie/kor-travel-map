# ADR-110 — geo·transport 피호출자가 odroid로 옮겨도 Map은 n150에 남아 REST만 쓴다 — 값의 자리는 Manager, 장애는 timeout(connect 분리)이다

- 상태: proposed (설계 2026-10-13, Track 2 적대 리뷰 3차 반영본 기준. **미구현** — Map 쪽 task는 `T-MAP-01`(이
  문서)·`T-MAP-02`(connect timeout 분리). 호스트 플립 자체는 Manager·geo·transport 저장소의 일이다)
- 날짜: 2026-10-13
- 결정자: human(승인 대기), Claude
- 관계: **Manager ADR-58**(두 번째 Docker 호스트 odroid — registry `hosts:`·호스트 프로필 Manager·호스트당 Dagster
  plane/PG·target별 host 플립 PR; 값의 **정본**), **geo ADR-070**(geo 스택의 odroid 운영·빈 호스트 풀로드·공개 키
  정책), **transport ADR-014**(transport 스택의 odroid 운영·`--host` 배포·export allow-list), 본 저장소 **ADR-109**(geo
  릴리스 재지오코딩 — 본 ADR이 `GEO_HEAVY_POOL` 유지 근거와 플립 직후 전량 재계획을 amend한다), ADR-046(geo REST
  v2 정본), ADR-105(Map은 weather를 호출하지 않는다 — weather 이전은 본 ADR 범위 밖), ADR-106(transport export),
  ADR-108(MOIS 재개형 적재 — 동시성·run 예산이 장애 모드 계산의 입력)
- 설계 출처(세션 scratchpad, 저장소에 보존되지 않는다): Track 2 설계 최종본 `track2-design-final.md` §2.2·§4·§9·
  §11.2·§14 + fact base `track2-factbase.md` §A2·§A3. **본 ADR 본문이 정본**이다 — 아래 "(설계 §x)"는 출처 표기일
  뿐이고 판단에 필요한 내용(두 선택지·게이트·수치)은 본문에 풀어 적었다. 설계 파일은 scratchpad에만 있어 보존
  여부는 소유자 결정이다(Manager ADR-58 작성 시 첨부 여부). 본 ADR은 그중 **Map 저장소가 책임지는 것**만 적는다.
- 표기: LAN 주소 리터럴은 적지 않는다 — 저장소 `scripts/check_prod_redaction.py`(#508, `lint.yml`·pre-commit)가
  committed docs의 사설 IP를 거부한다. 호스트는 이름(`n150`·`odroid`)으로 쓰고 실제 주소는 Manager root `.env`·
  registry(ADR-58 계획)에만 있다. 교차 저장소 ADR 번호(Manager ADR-58·geo ADR-070·transport ADR-014)는 고정 번호이고
  각 저장소의 **병렬 PR에 작성돼 있으나 아직 main에 머지되지 않았다**(2026-10-13 로컬 체크아웃 기준 — Manager
  `docs/decisions.md` ADR-58 절, geo `docs/adr/070-odroid-host-and-empty-host-full-load.md`, transport
  `docs/adr/014-odroid-host-and-deploy-host-flag.md`; 각 origin/main에는 없다). 본문의 "(proposed, 미머지)" 표식은 그
  저장소가 머지한 뒤 "후속"의 accepted 전환 항목과 같은 자리에서 걷는다.

## 컨텍스트

Map의 두 피호출자 geo(12501)·transport(14001)가 n150에서 odroid로 옮겨진다(소유자 지시 — 포트·URL·컨테이너명·
compose 프로젝트명은 n150과 **동일**, 호스트(LAN 주소)만 n150 → odroid; 설계 §4.2, 점유 포트 충돌 0 §4.6).
Map·PinVi·concierge는 n150에 남는다. Map이 오늘 그 둘을 어떻게 부르는지가 바뀌는 것의 전부다.

1. **값의 자리는 Map 저장소가 아니다.** 운영 Map이 읽는 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_BASE_URL`은 Manager compose가
   root `.env`의 `KOR_TRAVEL_MAP_DOCKER_GEO_BASE_URL`에서 주입하고 기본값은 `http://127.0.0.1:12501`이다 — **같은
   기본값이 Map 서비스 4곳**(`kor-travel-map-api`·`-dagster-code-server`·`-dagster`·`-dagster-daemon`; Manager
   `docker-compose.yml:1582,1723,1813,1920`@08a515e)에 복제돼 있어 플립 PR은 **키 이름으로 4곳을 함께** 바꾼다
   (Manager ADR-58 R2의 "4곳"). transport는 code-server 1곳뿐이다 — `KOR_TRAVEL_MAP_KOR_TRAVEL_TRANSPORT_BASE_URL`·
   `_SERVICE_TOKEN`(`:1732-1733`@08a515e, 기본 `http://127.0.0.1:14001`). Manager origin/main은 이미 그 뒤(`094d3976`,
   compose +14/−3)라 같은 키가 geo `:1582,1727,1819,1926`·transport `:1736-1737`에 있다 — Manager 플립 PR 작성 시
   **키 이름으로** 재확인한다. Map 코드의 설정 필드는 `src/kortravelmap/settings.py:150`(geo base)·`:509-519`(transport
   base — "n150은 같은 호스트의 `http://127.0.0.1:14001`" 설명 포함)이고, 저장소의 `.env.example:198`·`:234`는
   **standalone 스택** 값이다. 오늘 Manager registry(`config/docker-targets.yml`@08a515e)에는 `hosts:` 필드가 없다 —
   Manager ADR-58 R2(proposed, 미머지)가 이 기본값을 registry `hosts:`에서 파생한 **커밋된 파생물**로 만들고, 그 뒤에는
   URL의 자리가 그 파생 기본값뿐이라 root `.env`의 URL 재정의는 `targets validate`가 **거부**한다(`.env`에는 키·토큰만
   남는다 — T-MGR-01c 수용 기준). 즉 "오늘 = compose 기본값 + root `.env`", "ADR-58 R2 뒤 = 파생 기본값만"이고, 그때
   `.env`에 URL을 적어 validate가 거부하는 것은 Manager 결함이 아니라 설계다.
2. **Map UI BFF는 재빌드가 필요 없다.** `/api/geo` 프록시의 geo origin은 런타임 `KOR_TRAVEL_GEO_INTERNAL_URL` →
   `NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL` → `http://127.0.0.1:12501` 순이다
   (`packages/kor-travel-map-admin/frontend/src/app/api/geo/[...path]/route.ts:3-6`). 빌드 인자
   `NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL`(`docker/frontend.Dockerfile:57`, ENV `:62`)은 Manager compose가
   `${KTDM_PROD_URL_GEO_API:-…}`(**공개 host**)로 넣으므로(Manager compose `:1616,1634`) 호스트 이전으로 바뀌는
   값이 아니다 — 설계 §14-10의 두 선택지(공개 host 유지 = 변경 0 / LAN 직결 런타임 env 추가) 어느 쪽도 이미지를 다시
   만들지 않는다.
3. **오늘 장애는 RST, 내일 장애는 timeout이다.** 같은 호스트의 피호출자가 죽으면 커널이 연결 거부를 즉시 돌려준다.
   odroid가 꺼지거나 링크가 끊기면 SYN이 응답 없이 timeout까지 간다 — Map geo 호출의 설정은 단일 timeout 10 s
   (`settings.py:159-164`, connect/read 분리 없음)이지만 실제 client 생성 지점은 **8곳**이고 모양이 셋이다(head
   `f7affea8`): (a) settings를 읽어 `httpx.AsyncClient(timeout=<float>)`로 만드는 4곳 —
   `packages/kor-travel-map-dagster/src/kortravelmap/dagster/resources.py:1073-1076`,
   `packages/kor-travel-map-api/src/kortravelmap/api/app.py:709-712`, `api/feature_update_service.py:527`,
   `api/routers/offline_uploads.py:1482`; (b) **timeout 인자가 없는** 2곳(httpx 기본 connect/read 5 s) —
   `api/routers/admin_issues.py:276`·`:306`(admin 이슈 액션의 정/역지오코딩); (c) `timeout=10.0` **하드코딩**(settings를
   읽지 않는다) 2곳 — `packages/kor-travel-map-dagster/src/kortravelmap/dagster/offline_uploads.py:50-53`,
   `src/kortravelmap/cli/main.py:447`. transport는 30 s(`settings.py:537-542`; `dagster/provider_fetchers.py:357-361,431,455`
   3곳, 전부 settings를 읽는다). MOIS 재개형 적재는 geo를 동시성 2로 부르고(`:364-374`) run 예산이 14,400 s(`:388-`)라,
   피호출자가 **없는** 상태에서는 호출마다 10 s를 다 쓰고 나서야 실패한다.
4. **geo 공개 키는 오늘도 대조된다 — 호스트 이전으로 키 검증의 의미는 바뀌지 않는다.** geo 공개 키 검사가
   면제하는 "신뢰 클라이언트"는 loopback peer가 아니라 **admin 프록시 컨텍스트**다: geo
   `src/kortravelgeo/api/public_api_key.py:55,70` `_trusted_public_client` → `security.py:154-170`
   `resolve_request_context`(@02a3c2e)는 신뢰 CIDR peer **그리고** `X-KTG-Admin-Proxy-Secret` 일치 **그리고**
   actor/roles 헤더가 모두 있을 때만 non-None이다. Map 클라이언트는 `X-KTG-API-Key`만 보내므로
   (`src/kortravelmap/geocoding.py:1289`) 면제 대상이 아니고, 운영 Map의 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`는
   loopback에서도 대조돼 왔다 — 저장소 안 증거는 2026-08-13 prod 사고(VWorld 키가 결선돼 geo가 `401 E0401`로 거부;
   `settings.py:168-171`, `docs/archive/journal-2026-08b.md:18-30`)다. 설계 §9.1 키 행·§5.6 ⑥의 "검증된 적
   없다/면제 소멸" 전제는 **틀렸다**(2차 리뷰 정정 — geo ADR-070·§14-21 작성자에게 전달). 남는 실제 위험은 하나다:
   geo 빈 호스트 **풀로드**(drop 뒤 재적재)로 `public_api_keys`가 비면(설계 §11.4) Map이 든 발급 키가 무효가 된다.
   `kor_travel_geo_preflight_required`(`settings.py:165-176`)는 키 거부를 기동 fail-close로, geo 미도달을
   fail-open으로 다룬다 — 재적재 뒤 첫 기동에서 그 차이가 드러난다.
5. **transport export는 peer 주소로 닫혀 있다.** `SERVICE_EXPORT_ALLOWED_CLIENTS_CSV`(기본 loopback, `Host` header는
   보지 않는다 — `settings.py:514-518`, `docs/integration-map.md` §3 transport 행)에 n150 주소가 없으면 404로 경로를
   숨긴다. Map code-server는 n150 host network에서 돌므로 odroid가 보는 peer는 n150의 LAN 주소다. uvicorn 기본
   `forwarded-allow-ips=127.0.0.1`이라 XFF로는 바꿀 수 없다(설계 §4.4).
6. **Track 1(ADR-109)이 같은 경로를 쓴다.** 릴리스 센서의 `POST /v2/dataset/version` 폴링(≤5분)과 릴리스마다의 전
   장소 reverse 재호출(`GEO_HEAVY_POOL` 직렬)은 모두 geo base URL과 공개 키 경로를 탄다. `GEO_HEAVY_POOL`의 현재
   근거는 "n150 단일 회전 디스크 IO 대기"다(`dagster/assets.py:184-220` docstring; `mois_geocode_concurrency` 기본 2의
   설명도 같은 이유 `settings.py:364-374`).
7. **odroid의 오늘(FB §A3, 2026-10-13 03:4xZ).** WSL에서 직접 ssh 가능, NOPASSWD sudo·docker 그룹·NTP 수동 동기(시계
   2026) **완료**; timesyncd 부팅 순서 사이클의 영속화(drop-in)·`docker compose` v2/buildx 설치·호스트 방화벽·fstab
   bind·swapfile은 **미완**. 이전 순서는 transport → weather → geo(설계 §3.7·§11.2)이고 geo는 메모리 예산 조건
   (설계 §3.2 조건 3, §14-12)을 통과할 때만 간다 — 미달이면 geo는 n150 잔류이고 본 ADR의 geo 절은 발효하지 않는다.

## 결정

### 1. Map 저장소는 값을 바꾸지 않는다 — 정본은 Manager(오늘은 compose 기본값 + root `.env`, ADR-58 R2 뒤에는 registry `hosts:` 파생 기본값만 — `.env`의 URL 재정의는 validate가 거부)

geo·transport의 운영 origin은 **오늘** Manager compose의 리터럴 기본값(geo 4곳 `:1582,1723,1813,1920`·transport 1곳
`:1732`@08a515e — 컨텍스트 1) + root `.env`가 정하고, Manager ADR-58 R2(proposed, 미머지) 뒤에는 그 기본값이 registry
`hosts:`에서 파생한 커밋 파생물이 되며 root `.env`의 URL 재정의는 `targets validate`가 거부한다. 호스트 플립은
**그 저장소의 플립 PR + n150 `ensure map` — Map target 전 서비스 재생성**(옛 URL/키를 든 컨테이너 0개가 게이트:
`docker inspect`로 env 대조; 08-13 사고처럼 api만 재생성하면 dagster/daemon이 옛 값을 든 채 남는다 — 결정 4 (a)·결정
7과 같은 문장)이고, Map 저장소에는 코드·compose·`.env` 변경이 없다. `.env.example:198`·`:234`는 standalone 값임을 주석으로만 밝힌다(T-MAP-02의 코드 PR에 싣는다 — 본 문서 PR은
`.env.example`을 건드리지 않는다). Map 문서는 주소를 복제하지 않고 "Manager가 정본"이라고 가리킨다(단일 정본 원칙).

### 2. UI는 재빌드하지 않는다 — BFF 경로는 소유자 결정(§14-10)

`NEXT_PUBLIC_KOR_TRAVEL_GEO_BASE_URL` 빌드 인자는 공개 host라 변경 0이다(컨텍스트 2). BFF `/api/geo`가 LAN 직결을
원하면 Manager compose map-ui에 런타임 `KOR_TRAVEL_GEO_INTERNAL_URL=http://<odroid LAN 주소>:12501`을 **추가**하면
되고(route.ts의 우선순위가 이미 그렇다), 공개 host를 유지하면 HAProxy backend만 odroid로 바뀐다. 어느 쪽이든 Map
저장소 변경은 없다 — 열린 결정 1.

### 3. 장애 의미의 변화는 connect timeout 분리로 받는다 — T-MAP-02(코드, 후속)

geo·transport client의 단일 float timeout을 `httpx.Timeout(<기존 *_timeout_seconds>, connect=<x>_connect_timeout_seconds)`
로 바꾼다 — 첫 위치 인자가 기본값으로 read·write·pool을 덮고 `connect=`만 따로 둔다(**write/pool은 read와 같은 값**:
기존 단일 timeout의 의미 보존). `httpx.Timeout(connect=…, read=…)`처럼 둘만 주는 꼴은 쓰지 않는다 — 저장소 환경
httpx 0.28.1에서 `ValueError: httpx.Timeout must either include a default, or set all four parameters explicitly`로
죽는다(3차 리뷰에서 실행 확인; 설계 §13 T-MAP-02·§9.1의 `Timeout(connect=2, read=10)` 표기는 그 오류다). 연결
거부·무응답 호스트는 2 s 안에 예외, 느린 응답의 read 상한은 그대로(geo 10 s·transport 30 s). 대상은 컨텍스트 3의
client 생성 지점 **전부(geo 8곳·transport 3곳)**이고, 모양이 다른 (b)(c) — `admin_issues.py:276,306`의 timeout 부재,
`dagster/offline_uploads.py:50-53`·`cli/main.py:447`의 `10.0` 하드코딩 — 도 같은 팩토리로 settings를 읽게 바꾼다
(오늘 그 네 곳은 `kor_travel_geo_timeout_seconds`를 무시한다). 팩토리는 **하나씩**: geo는 `src/kortravelmap/geocoding.py`
(api·dagster·cli가 이미 import하는 모듈; httpx는 TYPE_CHECKING-only import 규약이라 — `pyproject.toml:59-60` — 함수
안 지역 import로)에 `geo_http_timeout(settings) -> httpx.Timeout`, transport는 `dagster/provider_fetchers.py:194`
`_transport_connection` 옆. 값은 설정 필드 `kor_travel_geo_connect_timeout_seconds`·
`kor_travel_transport_connect_timeout_seconds`(env `KOR_TRAVEL_MAP_KOR_TRAVEL_{GEO,TRANSPORT}_CONNECT_TIMEOUT_SECONDS`,
기본 2.0)로 둔다. 적용 범위는 개수 세기나 이름이 아니라 효과로 결박한다 — geo/transport client 생성의 `timeout=`
값이 팩토리 호출(`geo_http_timeout(`/`transport_http_timeout(`)이 아니면(리터럴·부재·settings float 직접 전달 모두)
lint가 빨갛다(T-MAP-02; 오늘의 (a) 4곳처럼 `timeout=settings.kor_travel_geo_timeout_seconds`를 넘기는 모양은 connect
분리 없이 초록이 되므로 이름 결박으로는 부족하다). 효과 기준: odroid 전원 off drill에서 MOIS run이 예산(14,400 s)의
**10 % 안에** FAILURE로 끝난다(설계 §11.3 — 배포 뒤 검증 행이지 T-MAP-02 종결 조건은 아니다, 결정 7). 유도: MOIS
적재는 chunk(500행, `packages/kor-travel-map-dagster/src/kortravelmap/dagster/mois_chunked_load.py:93`)마다 prefetch
(동시성 2)를 먼저 돌리는데 prefetch는 예외를 삼키고(`src/kortravelmap/geocoding.py:430-432` `prefetch_failures`)
변환의 실시간 재조회(`:438-445` `observe`)는 `GeoRequestError`를 그대로 전파한다 — `mois_chunked_load.py`·
`providers/mois.py`에 그것을 잡는 except가 없으므로 run은 **첫 chunk에서** FAILURE다(ADR-108 §3a-2의 degraded
규칙은 '빈 답'의 비율이지 전송 실패가 아니라 여기 관여하지 않는다). 시간 상한 ≈ 500행 ÷ 동시성 2 × connect 2 s +
실시간 1회 ≈ **≤ 502 s < 1,440 s**(예산 10 %); T-MAP-02 전(호출당 10 s)에는 같은 식이 ≈ 2,502 s로 10 %를 **넘는다** —
drill이 T-MAP-02 배포 뒤의 검증 행인 이유다. 회로차단은
Map에 두지 않는다 — Map 호출은 배치(Dagster run·admin 액션)라 run 실패가 곧 신호이고, 요청 경로에서 사용자를
기다리게 하는 PinVi(T-PNV-02)와 다르다. 필요가 드러나면 열린 결정 4.

transport 돌발 집합의 ±30 min 시계 검사(`src/kortravelmap/providers/kor_travel_transport.py:104`
`INCIDENT_SET_MAX_AGE`, `require_fresh_incident_set` `:435-452`)는 **fail-closed 그대로** 둔다 — odroid 시계가 틀리면
(FB §A3: 시계는 2026-10-13 수동 동기로 맞췄으나 timesyncd 부팅 순서 사이클의 drop-in이 미완이라 재부팅 뒤 재발 가능)
Map이 그것을 `TransportExportNotCurrent`로 잡는 것이 맞다.

### 4. geo 공개 키 — 이전으로 바뀌는 것은 없다; 위험은 geo 재적재의 키 소실뿐

키는 오늘도 대조되므로(컨텍스트 4) 호스트 플립 자체는 Map의 키 정책을 바꾸지 않는다. Map이 플립 절차(결정 7)에
요구하는 것은 둘이다. (a) geo 재적재(빈 호스트 풀로드·drop 뒤 재적재) 때마다 `public_api_keys`가 비므로 Map 소비자
키를 **재발급**하고 Manager root `.env`의 `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`에 재적용한 뒤 n150 `ensure map`으로
Map 컨테이너 **전부**를 재생성하고(08-13 사고는 api만 재생성해 dagster/daemon이 옛 키를 든 채 남았다 —
`docs/archive/journal-2026-08b.md`) 키 경로 200을 확인한다 — 플립 9단계의 **필수** 항목이고 소유는 Manager/geo 플립
PR 절차(외부 추적)다. (b) `kor_travel_geo_preflight_required`가 켜져 있으면 키 거부가 API 기동 자체를 막는다는 점을
절차에 적는다 — 결함이 아니라 설계된 fail-close다. geo의 VWorld 공용 키 폴백(geo `public_api_key.py:65` — 발급 키가
0개일 때만 켜진다)은 Map 쪽에서 **채택 불가**다: Map은 T-VN-H46B/C(#979)로 VWorld 키가 geo 소비자 키로 흐르는 통로를
전부 끊고 가드를 세웠고(`tests/unit/test_geo_key_provenance.py:493,506`,
`tests/integration/test_compose_geo_key_resolution.py:143`, `tests/unit/test_deploy_automation.py:382`), 08-13 사고가
바로 그 구성이었다. 정책 자체는 geo ADR-070(설계 §14-21) 소관 — 열린 결정 3.

### 5. transport export allow-list에 n150이 들어간다 — transport ADR-014의 일

`SERVICE_EXPORT_ALLOWED_CLIENTS_CSV += <n150 LAN 주소>/32`는 transport 운영 env 파일의 변경이다 — 오늘 그 파일은
`.env.server14`(transport `README.md:123-124`; `.env.server14.example`이 시작점)이고, `.env.prod`는 transport ADR-014
(proposed, 미머지)가 **개명하기로 한 계획 이름**이다(플립 전 운영자가 `.env.prod`를 찾지 않도록 둘 다 적는다). Map은 요구
사항만 적고(peer = Map code-server의 LAN 주소; XFF 불가) 토큰·base URL 외 아무것도 보내지 않는다. 전환 게이트:
n150 transport backend가 **stop인 상태에서** Map export 1회 성공(설계 §11.2 단계 5).

### 6. ADR-109 amend — `GEO_HEAVY_POOL` 근거와 플립 직후 전량 재계획

- `GEO_HEAVY_POOL`(instance 전역 1)은 **유지**하되 근거를 'n150 디스크 대기'에서 **'odroid geo CPU 보호'**로 바꾼다
  (A55 ×4 1.8 GHz, 실측 FB §A2; 설계 §9.3-2). `assets.py:184` docstring과 `mois_geocode_concurrency` 설명(`settings.py:
  364-374`)의 갱신은 T-MAP-02 코드 PR에 싣는다. pool 술어·동시성 값은 바꾸지 않는다.
- 센서·재지오코딩 호출은 LAN 키 경로를 탄다. 추정: RTT 9.7 ms(FB §A) × 35,754행 ≈ +6 min, geo CPU ×3(가정)이면
  전량 재지오코딩 ≈ **2.5 h+**(loopback p50 하한 ≈51 min 대비). `/v2/reverse` n150→odroid p50/p95 실측은 geo 플립
  단계(8b)에 포함한다.
- odroid 빈 호스트 **풀로드**는 새 `data_token`을 만들므로 Map URL을 odroid로 돌리는 순간(단계 9) 릴리스 센서
  (T-GR-05, 배포돼 있을 때)가 전량 재계획을 만든다. **수용을 추천한다**(설계 §14-19 — 소유자 결정 대기, 열린 결정 2):
  새 소스로 적재했으면 재지오코딩이 정확성상 옳다. 수용(추천)을 고르면 단계 9는 geo `mv_refresh` 완료 **다음 날**,
  geo 야간 job 창 밖에서 실행하고 운영자 UI의 계획 skip은 쓰지 않는다. 수용하지 않으면 운영자 UI skip이 그 자리이고,
  n150 dump **복원**이면 토큰이 같아 재계획 자체가 0이다(적재 방식은 geo ADR-070 몫).

### 7. 전환 절차에서 Map이 하는 일(설계 §11.2 발췌)

| 단계 | Map 쪽 | 게이트(효과) |
|---|---|---|
| 1 | Manager T-MGR-01b가 compose의 `map-api → geo-api` depends_on 간선을 지운다(R7) → n150 `ensure map` | `ensure map`·`ensure pinvi` 성공 |
| 2~4b(외부: Manager·transport·OPS — Map은 효과만 확인) | odroid 초기화(설계 §11.1 순서: NTP 사이클 해소·동기 → root 방식 → 잔여 envelope → 디스크 B안·swapfile → compose v2/buildx + cgroup 효과 → 폐기 → 방화벽 → Manager 설치 → NTP drop-in ⑤) → odroid plane/PG(3) → transport 플립 PR + n150 재설치 + n150 transport cs stop(4a) → odroid `deploy-prod.sh --host` + plane healthy(4b). Map 저장소 변경 없음 | **단계 5의 선행 조건** — odroid plane healthy ∧ `sudo -n ktdctl targets validate --json`의 transport.host == odroid ∧ odroid `timedatectl` `System clock synchronized: yes`(NTP drop-in은 §11.1-2 ⑤ — 재부팅 2회 PASS 전이면 재부팅 뒤 시계가 돌아가 Map이 `TransportExportNotCurrent`로 fail-closed할 수 있다, 결정 3). 셋이 PASS일 때만 5로 — 그 전에 `ensure map`을 돌리면 transport URL이 아직 아무것도 듣지 않는 odroid로 향한다 |
| 5 | transport 플립 뒤 n150 `ensure map` — Map target **전 서비스** 재생성(compose 기본값이 바뀐 파생물이지 `.env` 편집이 아니다) | 옛 transport URL을 든 Map 컨테이너 0개(`docker inspect` env 대조); n150 transport backend stop 상태에서 Map export 1회 성공; odroid access log peer = n150 LAN 주소 |
| 8a/8b(외부: Manager·geo — §3.2 메모리 조건 통과 시만) | geo 플립 PR + n150 재설치 + n150 geo cs stop(8a) → odroid 소스 반입·`ensure geo`·풀로드(또는 dump 복원)·`mv_refresh`·키 정책 적용(8b). Map 저장소 변경 없음 | **단계 9의 선행 조건** — odroid plane healthy ∧ `/v2/reverse` smoke ∧ 풀로드 run SUCCESS·`mv_refresh` 완료 ∧ 키 정책 적용 완료(열린 결정 3 — 발급 키면 Map 소비자 키 재발급까지) |
| 9-전(선택) | geo 플립 PR **전**, n150 geo-api가 살아 있을 때 n150에서 `curl --interface <n150 LAN 주소> http://<n150 LAN 주소>:12501/v2/reverse …`(키 헤더 포함) smoke — 키는 오늘도 대조되므로(컨텍스트 4) "면제 아님"을 확인하는 게 아니라 LAN 인터페이스 경유 경로를 미리 한 번 보는 것뿐이다. geo-api가 n150 LAN 인터페이스에서 들리는 이유는 host network + `KTG_API_HOST: 0.0.0.0`(Manager compose `:1089`@08a515e; `ports:`는 host 모드에서 무시된다, compose 머리말 `:3-5`) | 200. 401이면 Map 키 자체가 무효(재발급 — 결정 4 (a)) |
| 9 | geo 플립 뒤(mv_refresh 다음 날) n150 `ensure map` — Map target **전 서비스** 재생성, 풀로드였으면 root `.env` geo 키 재발급·재적용(결정 4 (a)), BFF 경로(결정 2) | 옛 geo URL/키를 든 Map 컨테이너 0개(`docker inspect` env 대조); n150 geo-api stop 상태에서 Map geocode e2e **키 경로 200**; Track 1 효과는 **분기** — 풀로드 + 수용(열린 결정 2)이고 T-GR-05 센서가 배포돼 있으면 센서 계획 1건 생성 / dump 복원이면 계획 **0건이 정답** / 센서 미배포면 해당 없음(토큰 변화만 `POST /v2/dataset/version`으로 기록) |
| drill | odroid 전원 off(T-MAP-02 배포 뒤 검증 행 — 측정 시각·배포 generation 기록; T-MAP-02 종결 조건은 아니다) | MOIS run이 예산 10 % 안에 FAILURE |
| 11 | n150 해체 뒤 | `ensure map` 성공, n150에 geo/transport 컨테이너 0개 |

단계 5·9는 consumer URL 전환이므로 단계 11 전까지 "n150 Manager 옛 sha 재설치 + n150 cs 재start"가 가능한 상태를
유지한다(롤백 설계는 비범위 — 재배포만). 긴 단계는 ssh timeout 밖에서(tmux/nohup).

## 근거

- **단일 정본.** 주소를 Map 문서·`.env.example`·CLAUDE.md에 복제하면 Manager 플립 PR마다 네 곳이 어긋난다. Map은
  "값의 자리"만 가리킨다(소유자 원칙: 복제 대신 포인터).
- **단순성·과결박 금지.** Map 쪽 코드 변경은 connect timeout 분리 하나다. 호스트 검사·IP 핀·헬스 폴링을 Map에 더하지
  않는다 — 호스트가 맞는지는 Manager `targets validate`와 효과 게이트(키 경로 200·export 성공·peer 로그)가 본다.
- **fail-closed 유지.** transport 시계 검사·geo preflight fail-close는 LAN 전환에서 더 가치가 커진다 — 완화하지 않는다.
- **Track 1과 분리.** ADR-109의 결정은 바뀌지 않는다. 바뀌는 것은 pool의 **이유**와 첫 플립 직후 비용(전량 재계획)뿐이다.

## 결과

긍정 — Map 저장소 변경 최소(코드 T 하나), 재빌드 0, 계약 핀 0(`docs/integration-map.md` §4 geocoding 행 — 핀 금지
유지). n150에서
geo/weather/transport가 빠지면 Map code-server의 디스크 대기 timeout 사망이 줄어든다(설계 §3.6).

부정·한계 — (1) odroid 다운은 RST가 아니라 timeout이다. T-MAP-02 전에는 MOIS run이 호출마다 10 s를 소모하고, 그
뒤에도 2 s × 호출 수만큼은 쓴다. (2) 전환 창에 geo/transport 수집·조회 공백이 생긴다(이중 수집 금지, 설계 §14-13).
(3) geo 풀로드 뒤 첫 플립은 전량 재지오코딩(≈2.5 h+ 추정)을 부른다(수용 시). (4) DHCP 임대 변경으로 odroid의 LAN
주소가 바뀌면 n150 consumer(Map 포함 — PinVi·concierge·HAProxy backend도)가 조용히 끊긴다(설계 §4.5 — OPNsense 예약은
소유자 결정 §14-20; 호스트 생사 신호는 Manager 관측 스택 몫 — `up{host="odroid"}`는 Manager ADR-58 파생물
**계획**이고 오늘 Manager `config/prometheus/prometheus.yml`에는 `host` 라벨이 없다). (5) 본 ADR의 geo 절은 geo가 실제로
odroid로 가는 경우에만 발효한다 — n150 잔류면 transport 절만 남는다.

## 후속

- **T-MAP-01**(이 문서 PR): ADR-110·README·`integration-map.md`·CLAUDE.md·ADR-109 역포인터·원장. 머지로 끝.
- **T-MAP-02**(코드): connect timeout 분리 + 팩토리 lint + `.env.example` standalone 주석 + `GEO_HEAVY_POOL`·
  `mois_geocode_concurrency`·transport base URL 설명 문구. 선행 T-GR-00-LEDGER, 배포는 transport 플립(4a) 전.
- **외부**(Map 저장소 밖, 외부 추적): Manager ADR-58·T-MGR-01b/01c 플립 PR, geo ADR-070(키 재발급 절차 포함),
  transport ADR-014(allow-list) — 셋 다 proposed·병렬 PR 미머지. 설계 §9.1 키 행·§5.6 ⑥의 정정과 §13 T-MAP-02·§9.1의
  `httpx.Timeout` 표기 오류(결정 3)는 geo ADR-070·Manager ADR-58 작성자에게 전달한다.
- **표식 교체(세 시점)**: ① 교차 ADR의 "(proposed, 미머지)"는 그 저장소가 머지할 때; ② "오늘 = compose 기본값 +
  root `.env`" 문구(컨텍스트 1·결정 1·`integration-map.md` §1/§2·CLAUDE.md)는 Manager ADR-58 R2가 적용돼 `.env` URL
  재정의가 validate에서 거부되기 시작할 때 "registry `hosts:` 파생 기본값만"으로; ③ **accepted 전환**은 전환 절차 단계
  11(n150에 geo/transport 컨테이너 0개, `ensure map` 성공) 뒤 — 그때 "계획" 표식(README·`integration-map.md`·CLAUDE.md)을
  걷고 ADR-109 `amended by` 줄을 "적용됨"으로 바꾼다.

## 열린 결정 (소유자)

1. **UI BFF 경로(§14-10)**: 공개 host 유지(HAProxy만 변경) vs Manager compose map-ui에 `KOR_TRAVEL_GEO_INTERNAL_URL`
   런타임 env 추가(LAN 직결). 설계는 둘을 추천 없이 나열한다(작성자 추천: 변경 0인 전자). Map 저장소 변경은 둘 다 없다.
2. **geo 초기 적재 방식(§14-8, geo ADR-070 소관)과 풀로드 시 재계획 처리(§14-19)가 Map 비용을 정한다**: 풀로드 →
   전량 재계획 **수용(추천)** vs 운영자 UI skip / dump 복원 → 재계획 0. 수용이면 단계 9를 mv_refresh 다음 날 야간 창
   밖에서(결정 6).
3. **geo 공개 키 정책(§14-21, geo ADR-070 소관)**: 설계는 (가) VWorld 폴백 유지 vs (나) 소비자별 발급을 나열한다.
   **Map 기준 (가)는 채택 불가**다(결정 4 — #979 가드 `test_geo_key_provenance`·`test_compose_geo_key_resolution`과
   충돌하고, geo DB에 발급 키가 하나라도 있으면 폴백이 꺼지므로 '변경 0'이 아니라 '발급 키 전부 폐기'를 뜻한다).
   Map 기준 유일한 경로는 (나) 발급 키 + 재적재 뒤 재발급·재적용 절차(결정 4 (a)) — 추천 없음, geo ADR-070 결정
   대기. 키 검증 자체는 오늘도 이뤄지므로(컨텍스트 4) 이 결정은 이전 시점이 아니라 **재적재 시점**의 일이다.
4. **회로차단**: Map에는 두지 않는다(결정 3). 전원 off drill에서 MOIS 외 경로(admin 이슈 액션·offline upload)의
   지연이 문제로 드러나면 재검토.
5. **task 접두사 `T-MAP-`**: 임시다(`tasks-rule.md` §3 묶음 prefix). 옛 `T-MAP-VWORLD-*`와 번호 체계가 다르므로
   소유자가 `T-NNN` 정식화를 원하면 `T-MAP-01`·`02`를 재번호한다.
6. **T-MAP-02 착수 순서**: 설계 §13은 MGR-01a~d·02~05 → (TRN/WEA/GEO) → (MAP/PNV/CNC) → OPS 순서다. 본 ADR은 Map의
   connect 분리가 Manager·Track 1 변경과 **코드 의존이 없다**고 보고 병렬 착수를 **제안**한다(소유자 확인 항목 —
   본문에서 확정하지 않는다). 제안의 조건: (ㄱ) 선행은 T-GR-00-LEDGER(journal 분리 — journal이 상한 225,280 B에
   ≈1.3 KB 안쪽이라 어느 코드 PR의 journal 항목도 `test_every_docs_markdown_stays_within_readable_limit`를 넘긴다),
   (ㄴ) `src/kortravelmap/geocoding.py`를 T-GR-01(ADR-109 `dataset_version()`, acceptance §T-GR-01)과 공유하므로
   둘 중 늦은 PR이 리베이스, (ㄷ) 배포는 transport 플립(4a) 전.
