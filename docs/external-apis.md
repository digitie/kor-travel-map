# external-apis.md — Provider API 키 발급/호출 정책

본 문서는 본 라이브러리가 의존하는 provider 라이브러리들이 호출하는 외부 API의
발급/호출 정책 reference다. 공공 provider 호출은 `python-*-api` provider
라이브러리에 위임한다(ADR-006). 예외적으로 `kor-travel-concierge-youtube`는 형제 앱
`kor-travel-concierge`의 REST export를 kor-travel-map Dagster가 직접 pull한다(ADR-053).
또한 admin curated feature의 주소/POI 검색은 curation source와 독립된 on-demand 조회라서
kor-travel-map API backend가 Kakao Local, NAVER Search, Google Places API를 직접 호출한다.

본 문서는 운영자/에이전트가 어떤 키를 어디서 발급받고 어디에 두는지 한 곳에서
확인할 수 있도록 한다.

## 1. 키 보관 원칙

- 모든 API 키는 `SecretStr`로 settings에 로드.
- **평문 자격증명을 담은 파일은 전부 권한 600.** `.env`만이 아니다 — 아래 참조.
  systemd `EnvironmentFile` 또는 vault 권장.
- 평문 commit 금지. CI/CD에서는 GitHub Actions secret.
- 로그/Sentry에 절대 노출 안 함.
- 키 회전 시 ADR 추가 (회전 사유, 영향 범위).

### 1.1 ⛔ `.env`만 보면 놓친다 — 같은 비밀을 담은 다른 파일들

이 규정이 오래 `.env`만 지목했고, 그 결과 **같은 비밀을 담은 파일들이 규정 밖에**
있었다. 2026-08-17 n150 실측:

| 대상 | 실태 | 담고 있던 것 |
|---|---|---|
| `docker-compose.yml` | `664` | 하드코딩 기본 DSN **3건** |
| `docker-compose.yml.bak-*` 5개 | `644`/`664` | 자격증명 **7~9건**씩 |
| `pg_dump` 산출물 4개(1.2GB) | `644` | **DB 전체** |

compose가 위험한 것은 `${VAR:-postgresql://user:password@host/db}` 형태로 **기본값에
비밀번호를 박기** 때문이다. `.env`에 override가 있어도 기본값은 파일에 남는다.
dump는 말할 것도 없이 DB 전체(발급 키 해시 포함)다.

전부 `600`(현행 compose는 배포 스크립트가 읽어야 해 `640`), 디렉터리는 `700`으로
좁혔다. **삭제하지 않았다** — 권한 조정은 되돌릴 수 있고, 삭제는 아니다.

**점검 방법** — 이름이 아니라 **내용**으로 찾는다. `.env`라는 이름만 훑으면 위 셋을
전부 놓친다.

```bash
# 대상을 **열거**한다. 목록을 미리 알아야 하면 그게 곧 이름 기반이다.
# 길이 조건도 두지 마라 — 이 표가 근거로 든 `addr:addr`은 비밀번호가 4자라
# `{8,}`로는 안 잡힌다. 돌려도 pinvi만 나오고 나머지가 초록으로 보인다.
find . -type f \\( -name '.env*' -o -name '*.yml' -o -name '*.yaml' \\
                 -o -name '*.dump' -o -name '*.bak*' -o -name '*.backup*' \\) \\
     -not -path './.git/*' -not -path './node_modules/*' -print0 \\
| while IFS= read -r -d '' f; do
    n=$(grep -acE '://[^:/@ ]+:[^@ ]+@' "$f" 2>/dev/null) || n=0
    [ "$n" -gt 0 ] && printf '%s %s (자격증명 %s건)\n' "$(stat -c %a "$f")" "$f" "$n"
  done
```

권한이 `600`이 아닌 줄이 나오면 그게 위반이다(`.env.example` 같은 tracked 예시는
예외로 **명시해** 뺀다 — 조용히 빠지는 예외를 만들지 않는다).

## 2. 환경변수 카탈로그

| 변수 | 사용 provider | 발급처 | 비고 |
|------|--------------|--------|------|
| `KMA_API_KEY` | python-kma-api | 기상청 API허브 (apihub.kma.go.kr) | 무료, 호출 한도 있음 |
| `VISITKOREA_SERVICE_KEY` | python-visitkorea-api | data.go.kr (TourAPI) | URL-encoded |
| `KRHERITAGE_API_KEY` | python-krheritage-api | 국가유산청 OpenAPI | |
| `KRFOREST_API_KEY` | python-krforest-api | 산림청 / 산림청 산악기상 | |
| ~~`KNPS_SERVICE_KEY`~~ | ~~python-knps-api~~ | — | **사용 안 함**. ADR-028 amendment + knps-api PR#4 (keyless). §3.8.1 참조 |
| `KREX_API_KEY` | python-krex-api | 한국도로공사 API | |
| `KHOA_API_KEY` | python-khoa-api | 국립해양조사원 | 해수욕장/해양지수 |
| `AIRKOREA_API_KEY` | python-airkorea-api | 한국환경공단 AirKorea | 대기질 |
| `OPINET_API_KEY` | python-opinet-api | 한국석유공사 OpiNet | 주유소·유가 |
| `DATAGOKR_API_KEY` | python-datagokr-api, data.go.kr-standard | data.go.kr 표준데이터 | 최우선 |
| `DATA_GO_KR_SERVICE_KEY` | 동일 | 동일 | 폴백 1 |
| `PUBLIC_DATA_SERVICE_KEY` | 동일 | 동일 | 폴백 2 |
| `SERVICE_KEY` | 동일 | 동일 | 폴백 3 |
| `KAKAO_LOCAL_REST_API_KEY` | kakao-local-api | Kakao Developers | `Authorization: KakaoAK {KEY}` |
| `KOR_TRAVEL_MAP_KAKAO_LOCAL_REST_API_KEY` | admin curated place search | Kakao Developers | backend 직접 호출용. `scripts/load-env.sh`가 `KAKAO_LOCAL_REST_API_KEY`에서 매핑 |
| `NAVER_SEARCH_CLIENT_ID` | naver-search-api | NAVER Developers | 헤더 `X-Naver-Client-Id` |
| `NAVER_SEARCH_CLIENT_SECRET` | 동일 | 동일 | 헤더 `X-Naver-Client-Secret` |
| `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_ID` / `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_SECRET` | admin curated place search | NAVER Developers | backend 직접 호출용. 짧은 이름에서 매핑 가능 |
| `GOOGLE_PLACES_API_KEY` | google-places-api-new | Google Cloud Console (Places API New) | field mask 필수 |
| `KOR_TRAVEL_MAP_GOOGLE_PLACES_API_KEY` | admin curated place search | Google Cloud Console (Places API New) | backend 직접 호출용. `GOOGLE_PLACES_API_KEY`에서 매핑 가능 |
| `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_BASE_URL` | kor-travel-concierge-youtube | 형제 앱 kor-travel-concierge | base URL, 예: `http://127.0.0.1:12601` |
| `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY` | kor-travel-concierge-youtube | kor-travel-concierge DB `read` scope 키 | `X-API-Key` 헤더로만 전송, static `API_KEYS` 공유 금지 |
| `KOR_TRAVEL_GEO_*` | kor-travel-geo | (로컬 DB 위주, vworld 폴백 키는 kor-travel-geo가 관리) | geo 서비스 자체 설정. 본 라이브러리는 HTTP client만 사용 |
| `KOR_TRAVEL_GEO_VWORLD_API_KEY` | kor-travel-geo (reverse geocoding), 디버그/admin UI frontend (MapLibre/VWorld), PinVi 사용자 UI (ADR-026) | VWorld (vworld.kr) | **공유 키**. 별도 발급 X. ADR-025 + ADR-026 |
| `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY` | kor-travel-map API/Dagster/CLI의 kor-travel-geo v2 호출 | kor-travel-geo public REST v2 | `X-KTG-API-Key` header로만 전송한다. admin trusted-proxy secret/role을 Map에 위임하지 않는다. |
| `KOR_TRAVEL_GEO_API_KEY` | admin UI 컨테이너의 `/api/geo/*` 프록시 | kor-travel-geo public REST v2 | `NEXT_PUBLIC_` 접두가 없는 **유일한 UI server runtime 입력**이다. Manager가 root `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`에서 이 이름으로만 결선하고, 프록시는 browser `key` query를 버린 뒤 `X-KTG-API-Key` header로만 보낸다. 키 교체에 이미지 재빌드는 필요 없다. |

## 2.1 과거 동일 값 오염 실측 (2026-08-14, 운영 정본 아님)

자격증명 하나가 provider별·저장소별 이름으로 갈라져 여러 곳에 복제돼 있다. 아래는
로컬 `F:\dev` 전체의 `.env`/`.env.local`/`.env.production`을 값의 sha256 앞 8자로
묶은 **당시 사고 조사 실측**이다. 값은 싣지 않는다. 이 표는 현재 허용 별칭 목록이
아니다. 특히 `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`는 H46F에서 폐기됐으며 build arg,
browser bundle, query credential로 다시 결선하면 안 된다. 현재 Map 소비자 키 정본은
root `KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`이고, UI에는 server runtime
`KOR_TRAVEL_GEO_API_KEY`로만 격리 전달한다.

| 자격증명 | sha8 | 별칭 수 | 파일 수 | 별칭 |
|---|---|---|---|---|
| data.go.kr 서비스 키 | `dad00595` | 18 | 18 | `DATA_GOKR_SERVICE_KEY`, `DATA_GO_KR_SERVICE_KEY`, `IIAC_SERVICE_KEY`, `KAC_SERVICE_KEY`, `KASI_SERVICE_KEY`, `KEX_GO_API_KEY`, `KMA_SERVICE_KEY`, `KTO_SERVICE_KEY`, `KTO_DATA_GO_KR_SERVICE_KEY`, `TRIPMATE_DATA_GO_SERVICE_KEY`, `KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY`, `KRTOUR_MAP_KREX_GO_API_KEY`, `KRTOUR_MAP_ADMIN_{AIRKOREA,DATAGOKR,KMA,KREX,KRFOREST,VISITKOREA}_SERVICE_KEY` |
| VWorld 키 | `e9caf390` | 14 | 15 | `VWORLD_API_KEY`, `VWORLD_SERVICE_KEY`, `VITE_VWORLD_API_KEY`, `NEXT_PUBLIC_VWORLD_API_KEY`, `NEXT_PUBLIC_VWORLD_SERVICE_KEY`, `KTG_VWORLD_API_KEY`, `KRADDR_GEO_VWORLD_API_KEY`, `PINVI_VWORLD_API_KEY`, `KOR_TRAVEL_GEO_VWORLD_API_KEY`, `KOR_TRAVEL_MAP_API_VWORLD_API_KEY`, `KOR_TRAVEL_GEO_V2_API_KEY`, **`KOR_TRAVEL_MAP_KOR_TRAVEL_GEO_API_KEY`**, **`NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`** |
| OpiNet 키 | `dfc07838` | 4 | 3 | `OPINET_API_KEY`, `TRIPMATE_OPINET_API_KEY`, `KRTOUR_MAP_OPINET_API_KEY`, `KRTOUR_MAP_ADMIN_OPINET_SERVICE_KEY` |

**굵게 표시한 두 이름은 당시 geo 소비자 키 자리에 VWorld 키 값이 들어 있던 오염
기록이다.** 둘 중 `NEXT_PUBLIC_KOR_TRAVEL_GEO_API_KEY`는 현재 폐기된 이름이다. geo는 그
값을 `401 E0401`("VWorld 호환 인증키가 유효하지 않습니다")로 거절하고, `preflight()`는
존재·길이만 보므로 실패가 첫 요청 시점까지 미뤄진다. 2026-08-13 prod 사고가 정확히
이것이었고, 로컬 `.env`들에는 아직 그대로 있다. 두 자격증명은 성격이 다르다 — VWorld
키는 **geo가 상류 VWorld로 나갈 때**, geo 소비자 키는 **map이 geo에 인증할 때** 쓴다.

실제 위험은 키 자체가 아니라 **사본 수**다(회전 판정은 `docs/tasks.md` T-VN-H46E).
회전하려면 위 표의 모든 이름을 동시에 바꿔야 하고, 하나라도 빠지면 그 서비스만 조용히
죽는다. 표를 갱신할 때는 추정하지 말고 값의 sha8로 다시 묶을 것 — 셸 `cut`+`tr -d`로
값을 뽑으면 따옴표 처리에서 오염돼 해시가 달라진다(실제로 그렇게 오판했다).

## 3. provider별 발급 절차 (요약)

### 3.1 기상청 (KMA)

1. https://apihub.kma.go.kr 가입
2. "마이페이지" → "API 키 발급" → 본 프로젝트용 키 생성
3. `KMA_API_KEY` 환경변수에 저장
4. 사용 API: 단기예보(VilageFcstInfoService), 초단기실황, 중기예보, 특보

### 3.2 TourAPI (VisitKorea)

1. https://www.data.go.kr 가입
2. "TourAPI" 검색 → 활용 신청 → 자동 승인
3. 발급된 ServiceKey는 **URL-encoded** 형태와 **decoded** 형태 모두 받음.
   provider 라이브러리는 decoded를 권장.
4. `VISITKOREA_SERVICE_KEY` 환경변수에 decoded 형태 저장.

### 3.3 국가유산청 (krheritage)

1. https://www.khs.go.kr API 신청 (홈페이지에서 OpenAPI 항목 확인)
2. `KRHERITAGE_API_KEY` 환경변수

### 3.4 OpiNet

1. https://www.opinet.co.kr/api 가입 + 활용 신청
2. `OPINET_API_KEY` 환경변수
3. 호출 한도 — 분당 60회 정도 (provider 라이브러리에서 token bucket).

### 3.5 도로공사 (krex)

1. data.go.kr에서 "한국도로공사" 검색 → API 활용 신청
2. `KREX_API_KEY` 환경변수

### 3.6 국립해양조사원 (KHOA)

1. http://www.khoa.go.kr/api 활용 신청
2. `KHOA_API_KEY` 환경변수

### 3.7 AirKorea

1. data.go.kr "한국환경공단 에어코리아" 검색
2. `AIRKOREA_API_KEY` 환경변수

### 3.8 산림청 (krforest)

1. data.go.kr "산림청" 검색 — 여러 dataset (휴양림, 산악기상 등)
2. `KRFOREST_API_KEY` 환경변수

### 3.8.1 국립공원공단 (KNPS, `python-knps-api`) — **keyless (auth 불필요)**

ADR-028 amendment 2026-05-25 + knps-api PR#3/#4: 인증 ServiceKey 사용 안 함.
data.go.kr 직접 다운로드 URL (atchFileId + fileDetailSn + insertDataPrcus)로
모든 14건 file dataset 접근.

1. **활용 신청 불필요** — data.go.kr 파일데이터는 별도 인증 없이 다운로드 가능
   (`https://www.data.go.kr/cmm/cmm/fileDownload.do?...`). knps-api가 URL을
   카탈로그에 박아 둠.
2. **환경변수 없음** — `KNPS_SERVICE_KEY` / `DATA_GO_KR_SERVICE_KEY` 모두
   사용 안 함. `KnpsClient()` 생성 시 인증 인자 없음.
3. 사용 dataset: 공원경계(SHP)/탐방로/탐방안내소/위험지역/기상관측시설/화장실/
   문화자원/야영장/대피소/시설도로/특별보호구역 (공간 데이터 11건) +
   기초/탐방객 통계 (timeseries 2건, feature 본문 X) + 메타 카탈로그 1건.
   자세히는 `docs/etl/knps-feature-etl.md` (ADR-028 amendment §H).
4. 호출 한도 — `KnpsClient(max_rps=5.0)` 기본 (data.go.kr 정책 보수치).
   `KnpsClient(max_rps=10.0)` 등으로 조정 가능.
5. (이전) `knps_access_restrictions`/`knps_fire_alerts` notice API는 knps-api
   PR#3에서 source 삭제 — 산림청 (`python-krforest-api`) / 소방청 source로
   이전 (별도 후속 ADR).

### 3.9 Kakao Local

1. https://developers.kakao.com 앱 생성
2. REST API 키 발급
3. provider library 호환 키는 `KAKAO_LOCAL_REST_API_KEY`, admin curated place search 직접 호출은
   `KOR_TRAVEL_MAP_KAKAO_LOCAL_REST_API_KEY` 환경변수에 저장한다.
4. `scripts/load-env.sh`/`docker-compose.yml`은 짧은 이름을 `KOR_TRAVEL_MAP_*`로 매핑한다.
5. 호출: `Authorization: KakaoAK {KEY}` 헤더

### 3.10 NAVER Search

1. https://developers.naver.com/apps 앱 등록
2. "검색" API 활성화
3. Client ID, Client Secret 발급
4. provider library 호환 키는 `NAVER_SEARCH_CLIENT_ID`, `NAVER_SEARCH_CLIENT_SECRET`, admin curated
   place search 직접 호출은 `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_ID`,
   `KOR_TRAVEL_MAP_NAVER_SEARCH_CLIENT_SECRET` 환경변수에 저장한다.
5. `scripts/load-env.sh`/`docker-compose.yml`은 짧은 이름을 `KOR_TRAVEL_MAP_*`로 매핑한다.

### 3.11 Google Places API (New)

1. Google Cloud Console → 프로젝트 생성 → "Places API (New)" 활성화
2. API 키 생성 (제한 권장: HTTP referrer 또는 IP)
3. provider library 호환 키는 `GOOGLE_PLACES_API_KEY`, admin curated place search 직접 호출은
   `KOR_TRAVEL_MAP_GOOGLE_PLACES_API_KEY` 환경변수에 저장한다.
4. `scripts/load-env.sh`/`docker-compose.yml`은 짧은 이름을 `KOR_TRAVEL_MAP_*`로 매핑한다.
5. 호출 시 **Field Mask 필수** (`X-Goog-FieldMask`) — 전화번호만 받으려면
   `places.id,places.displayName,places.formattedAddress,places.nationalPhoneNumber`
6. 비용 발생 가능 — 호출 빈도 관리

### 3.12 data.go.kr 표준데이터

표준데이터 5종은 별도 provider 라이브러리 없이 `kortravelmap.standard_data`의
내부 bounded asyncio client에서 처리한다. (코드 작성 단계에서 v1과 동일 패턴
재구현)

API 키 우선순위:

1. `DATAGOKR_API_KEY`
2. `DATA_GO_KR_SERVICE_KEY`
3. `PUBLIC_DATA_SERVICE_KEY`
4. `SERVICE_KEY`

### 3.13 kor-travel-concierge YouTube 후보 export

1. kor-travel-concierge가 `/api/v1/features/snapshot`과
   `/api/v1/features/changes`를 제공해야 한다(구 `kor-travel-concierge` 프로젝트명 변경,
   ADR-053).
2. kor-travel-map Dagster는 `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_BASE_URL`을 host root로 받고,
   path는 fetcher가 `/api/v1/features/{snapshot|changes}`로 붙인다.
3. `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_API_KEY`는 kor-travel-concierge에서 외부 소비자용으로
   발급한 DB `read` scope 키여야 한다. static `API_KEYS`는 BFF/operator용 admin credential이므로
   공유하지 않는다. 키는 `?key=` query가 아니라 `X-API-Key` 헤더로만 전송한다.
4. `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_FEATURE_SYNC_ENDPOINT=changes|snapshot`
   (기본 `changes` — cursor 없이 시작하면 후보당 1행 ledger 전체를 재생해 철회 전파까지
   포함한 full sync가 된다. `snapshot`은 active upsert만 반환해 reject/tombstone이
   미전파 — 일회성 초기 적재 검증용),
   `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_FEATURE_CURSOR`(설정 시 그 sequence 이후만
   재생 — full 재생·철회 backfill은 이 값 **미설정**이 전제이므로 배포 전 운영 env
   부재를 확인한다),
   `KOR_TRAVEL_MAP_KOR_TRAVEL_CONCIERGE_FEATURE_PAGE_SIZE`로 pull을 조정한다.
5. 회전은 Concierge scope migration 검증 → 새 `read` 키 발급 → kor-travel-map secret 교체·
   Dagster 재시작 → snapshot/changes 다중 page와 cursor 불변식·같은 키의 내부/write 403 확인
   순서로 한다. 구 static 키가 BFF와 공유됐다면 BFF/operator admin 키를 overlap 방식으로 먼저
   교체·검증한 뒤 구 static 키를 제거한다. 키 값·길이·digest는 문서·로그에 남기지 않는다.
   cursor는 opaque하므로 크기를 비교하지 않는다. `has_more=true`면 새 `next_cursor`를 그대로
   다음 요청에 쓰고, `has_more=false`면 non-null cursor여도 종료하며 빈 최종 page의 입력 cursor
   echo를 허용한다. 각 모드에서 export ID 중복 없이 2 page 이상을 소비해야 합격이다.

### 3.14 문화체육관광부 (MCST, `python-mcst-api`)

1. 파일데이터 CSV 13 dataset은 **키 불요**(keyless) — `FileDataClient`가
   다운로드 페이지(culture.go.kr `filedatDtl.do` / data.go.kr `fileData.do`)를
   스크레이핑해 최신 CSV를 받는다(provider #6/#7/#11, T-220 재배선 #395 + T-223b).
   구 KCISA
   OpenAPI(`CultureOpenApiClient`)/ODCloud(`DataGoFileApiClient`) 경로는 폐기
   — KCISA OpenAPI는 공인 DNS 미해석 + KCISA 전용 발급키 필요(provider #6).
2. dataset당 1 run 상한은 `KOR_TRAVEL_MAP_MCST_MAX_ITEMS_PER_DATASET`(기본 50000
   — 실측 최대 24,537행의 약 2배 여유).
3. dataset 카탈로그(slug/다운로드 페이지)는 `python-mcst-api` `catalog.py`가
   정본 — krtour 측 메타표는 `kortravelmap.providers.mcst.MCST_FILE_DATASETS`
   (적재 13), 제외 3종 사유는 `MCST_EXCLUDED_FILE_DATASETS`.

## 4. 호출 정책 (provider 라이브러리가 책임)

공공 provider는 본 라이브러리가 직접 호출하지 않고 provider 라이브러리가 다음을
지켜야 한다(각 provider 저장소의 ADR로 박혀 있어야 함). `kor-travel-concierge-youtube`
REST export는 ADR-053 예외로, kor-travel-map Dagster fetcher가 같은 timeout/secret
마스킹 원칙을 따른다.

- `httpx.AsyncClient`로 호출 (`requests` 동기 금지).
- `tenacity` 재시도: 5xx/timeout만 3회 지수 backoff. 4xx 즉시 실패.
- 회로차단: 실패율 임계 초과 시 일정 시간 차단.
- 타임아웃: `httpx.Timeout(connect=2, read=8)` 권장.
- 인증: `SecretStr`로 settings에서 로드. 헤더에만 사용, URL/로그 금지.
- 호출 로그: structlog JSON 한 줄 — `{provider, endpoint, status, latency_ms,
  request_id}`.
- 쿼터: provider별 token bucket 또는 leaky bucket.

본 라이브러리는 provider client 호출 횟수만 `ops.api_call_log` 테이블에 기록
(옵션, `log_api_calls=True`).

## 5. 호출 빈도 제어

본 라이브러리에서 강제 가능한 추가 제어:

- `Dagster ConcurrencyConfig` (PinVi 측)으로 same API resource pool
  `max_concurrent=1` (SPEC V8 K-2).
- bulk 적재 시 page 단위 sleep (provider 라이브러리에서).
- `ProviderSyncState.next_run_after`로 다음 호출 시각 박음 — Dagster scheduler가
  이 값을 존중.

## 6. 키 회전 절차

1. 새 키 발급
2. `.env` (또는 vault)에서 새 키로 교체
3. 운영 노드에서 컨테이너 재시작
4. 기존 키 무효화 (provider 콘솔)
5. journal.md + ADR (회전 사유, 영향 범위)

## 7. provider 응답 변경 대응

provider API spec이 변경되면:
1. `python-*-api` 라이브러리에서 typed model 변경 + minor version
2. 본 라이브러리의 `providers/<name>.py` 변환 함수 조정 + fixture 추가
3. `SourceRecord.raw_payload_hash` 변경 → 새 row 생성 → schema drift 자동
   감지
4. `data_integrity_violations`에 `violation_type='schema_drift_detected'`
   기록 (옵션)
5. ADR (큰 변경이면)

## 8. 비용 관리

대부분의 한국 공공 API는 무료. 유료/한도 있는 것만:

- **Google Places API (New)**: 호출당 비용. Place phone enrichment는 candidate
  3개 미만으로 제한 (`PLACE_PHONE_MAX_CANDIDATES=3`).
- **VWorld API** (MapLibre GL + VWorld raster tile): 본 라이브러리
  디버그 UI frontend **및 PinVi 사용자 UI** (ADR-026)가 사용. 키는
  `kor-travel-geo` ADR-019의 `KOR_TRAVEL_GEO_VWORLD_API_KEY`를 **공유 사용**
  (ADR-025 사용자 보강 2026-05-25). 별도 발급 금지. frontend는 **Next.js**
  (ADR-025 2차 보강) 규약상 `NEXT_PUBLIC_VWORLD_API_KEY`로 노출 — 값은
  동일 출처. `kor-travel-geo` public REST v2 호출에는 geo가 Map consumer에 별도로
  발급한 값을 UI server runtime `KOR_TRAVEL_GEO_API_KEY`에 넣고 BFF가
  `X-KTG-API-Key` header로 전달한다. VWorld provider key나 browser query fallback은
  금지하며 HTTP referrer 제한을 권장한다.
- **Kakao Maps JS SDK**: **미사용** (ADR-026 — PinVi 사용자 UI도
  VWorld/MapLibre 계열로 통일, SPEC V8 v8_3 supersede). 본 항목은 reference로
  유지하되 비용/한도 모니터링 대상이 아니다.
- **OpiNet**: 분당 한도 — token bucket으로 보호.

## 9. 운영 모니터링

`ops.api_call_log`로 호출 추세 추적:

```sql
-- provider별 최근 1시간 호출 수와 평균 지연
SELECT provider,
       count(*) AS calls,
       avg(latency_ms) AS avg_ms,
       max(latency_ms) AS max_ms,
       sum(CASE WHEN status >= 500 THEN 1 ELSE 0 END) AS error_5xx
FROM ops.api_call_log
WHERE occurred_at >= now() - interval '1 hour'
GROUP BY provider
ORDER BY calls DESC;
```

Grafana 패널에 노출 (PinVi 측). 5xx 비율 임계 초과 시 알림.

## 10. 호출 안 함 (테스트 기본)

`tests/unit`, `tests/integration`, `tests/fixtures`는 **외부 API를 호출하지
않는다**. provider 응답은 fixture로 녹화 (`tests/fixtures/<provider>/*.json`)
하거나 VCR.py로 cassette.

라이브 호출이 필요한 시나리오:
- 디버그 UI에서 "라이브 호출" 옵션 (개발자 명시 트리거)
- nightly canary (kor-travel-map Dagster `provider_canary` asset)
- 운영 ETL

위 시나리오는 모두 provider 라이브러리에서 직접 호출하고, 본 라이브러리는
받은 결과만 변환한다.
