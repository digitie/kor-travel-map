# adr045-open-decisions.md — ADR-045 독립 프로그램화 의사결정 대기 목록

ADR-045 구현(`docs/adr045-standalone-plan.md`) 전/중에 **사람이 결정해야 하는 열린
질문**. 각 항목: 질문 · 선택지 · (있으면) 권고안 · 차단하는 task · 결정 시 반영처.
결정되면 해당 항목을 ADR-046+ 또는 관련 문서에 박고 여기서 ✅ 처리.

> 우선순위: **차단(BLOCKER)** = 미결 시 구현 불가. **설계** = 구현은 가능하나 방향
> 영향. **운영** = 배포/운영 단계.

## BLOCKER (구현 차단) — **전부 결정됨 (2026-06-01 사용자 확정)**

### D-2 — Dagster metadata DB 레이아웃/부트스트랩 ✅ **결정: (a)**
- 질문: `krtour_map_dagster`를 같은 Postgres container 내 별도 DB로 둘 때
  `DAGSTER_HOME`/storage 설정, 생성·init 순서는?
- **결정: (a) 같은 Postgres container, 별도 DB `krtour_map_dagster`** (ADR-045 §4
  기본값). 기동 순서 = postgres ready → 앱 `alembic upgrade head`(`krtour_map`) →
  `krtour_map_dagster` DB 생성(initdb/entrypoint) → Dagster instance 자체 schema
  자동 생성 → api/dagster 기동. `DAGSTER_HOME`은 컨테이너 볼륨, `dagster.yaml`의
  run/event_log/schedule storage를 `krtour_map_dagster`로.
- 차단 해소: T-208a, T-209b. 반영: `dagster-boundary.md` + docker-compose(T-209a).

### D-6 — feature-update 큐 실행 모델 + cardinality + lock 정책 ✅ **결정: 권고대로**
- **결정**: (1) **request : job = 1 : 1** — 큰 scope는 단일 job 내부 배치 처리
  (`_batched` 패턴 재사용). (2) `run_mode=now` + 동일 scope advisory lock 점유 시
  **HTTP 409 + `retry_after`** (queued fallback 아님). (3) Dagster sensor **폴링
  15초**.
- 차단 해소: T-206b/d, T-208e, T-207a. 반영: `openapi-admin-contract.md §6` +
  plan §2 + `tripmate-rest-api.md`(409 명시).

### D-7 — `/features/{id}` admin↔사용자 응답 분리 ✅ **결정: 분리**
- **결정: 엔드포인트 분리** — `/features/*`(공개, `tripmate-rest-api.md §2` 정제
  필드, 원문/이력 제외) + `/admin/features/*`(source_records 원문 · dedup history ·
  consistency 참조 포함). OpenAPI drift gate도 admin/user 이원(D-3와 연동).
- 차단 해소: T-207e, `tripmate-rest-api.md`. 반영: 두 문서 + OpenAPI.

### D-11 — `sigungu_by_radius` 경계 소스 ✅ **결정: kraddr-geo에 신규 엔드포인트 추가**
- **결정**: 시군구 경계를 krtour-map에 적재하지 않고, **kraddr-geo**(시군구 경계
  polygon `tl_scco_sig` + PostGIS + v2 REST 이미 보유)에 **신규 엔드포인트를 추가**
  하고 krtour-map이 REST로 호출한다. (krtour-map `feature.sigungu_boundaries` 신설
  불필요 → T-205b 취소.)
- **kraddr-geo 신규 엔드포인트 (형제 repo `python-kraddr-geo` 별도 PR)**:
  `POST /v2/regions/within-radius` — 기존 v2(POST+JSON) 패턴.
  - 요청: `{ "lon": 126.978, "lat": 37.5665, "radius_km": 3.0,
    "levels": ["sigungu"] }` (`levels` 기본 `["sigungu"]`, 확장 가능
    `["sido","sigungu","emd"]`).
  - 응답: `{ "center": {...}, "radius_km": 3.0, "sigungu": [ { "code": "11110",
    "name": "종로구", "relation": "contains"|"overlaps" } ] }` (요청 levels별 배열).
  - 구현: `ST_DWithin(geom_5179, ST_Transform(:pt,5179), :radius_m)` 또는
    `ST_Intersects(geom, ST_Buffer(:pt::geography,:m))`. 입력 1회 변환(경계 무효화
    회피). `tl_scco_sig`/`tl_scco_ctprvn`/`tl_scco_emd` 레이어 사용.
- **krtour-map 측**: `resolve_sigungu_by_radius`가 위 엔드포인트를 `KraddrGeoRestClient`
  로 호출 → `code` 목록 → `WHERE sigungu_code = ANY(:codes)`로 feature 조회.
- **🟢 기타 코멘트 (확정)**:
  - **코드 체계 = 동일 (사용자 확인 2026-06-01)**: kraddr-geo `tl_scco_sig.sig_cd`
    (5자리)와 krtour-map `feature.sigungu_code`(5자리)는 **같은 체계**. 별도 매핑·
    변환 불필요 — kraddr-geo 반환 `code`를 그대로 `WHERE sigungu_code = ANY(...)`에
    사용한다.
  - **레벨 범위 = sigungu 우선 (사용자 확인)**: 1차는 `sigungu`만 구현하되 `levels`
    파라미터로 시도(`sido`)·읍면동(`emd`) 확장 여지를 남긴다.
  - **대안 검토 기록**: 기존 `/v2/reverse`에 radius 옵션을 얹는 방안은 "한 점→한
    주소" 의미가 흐려져 채택 안 함 — **신규 엔드포인트가 명확**(사용자 결정:
    엔드포인트 늘려도 됨).
- 차단 해소: T-206a. 신규 task: T-206a-geo(kraddr-geo 엔드포인트, 별도 repo).

### D-14 — offline upload 파일 저장 위치 ✅ **결정: RustFS 무제한 보존**
- **결정: RustFS 버킷(`krtour-uploads`)에 저장, 보존 만료 없음(무제한)**. 자동
  정리/lifecycle job 두지 않는다(원본 추적·재적재·감사 보존 우선). dev도 RustFS
  (compose 포함, D-5).
- 차단 해소: T-208g. 반영: plan §4(T-208g), 업로드 라우터.

## 설계 (방향 영향)

### D-1 — API 인증/토큰 규약 (설계)
- 질문: 코드에 인증 없음(ADR-005) 유지하되, 운영 인증(Cloudflare SSO / IP allowlist
  / API key header)을 무엇으로? TripMate 서비스 토큰 헤더 이름은?
- 권고: infra 계층(Tunnel SSO + IP allowlist), 헤더는 `X-Krtour-Service-Token`
  pass-through(코드 미검증). 반영: ADR-005 amendment, `tripmate-rest-api.md §1`.

### D-3 — OpenAPI versioning + admin/사용자 schema 이원화 (설계)
- 질문: 패키지 버전 == API 버전? 응답 필드 추가=minor, 제거/의미변경=major? admin
  schema와 사용자 schema를 별도 export + 별도 drift gate로?
- 권고: SemVer(필드 추가 minor / breaking major), schema 이원(admin/user) + 각 drift
  gate. 반영: ADR-031 amendment, T-207g.

### D-4 — TripMate OpenAPI client 생성 시점 (설계)
- 질문: 사용자 API 안정화 전까지 TripMate가 dev에서 직접 호출? client SDK
  (`openapi-typescript`) 생성 시점은?
- 권고: Phase 3 `/features/*` 안정 후 사용자 schema 고정 → client 생성(T-210e).
  그 전엔 TripMate가 httpx로 직접(D-7 형태 기준).

### D-8 — deactivate ↔ provider 재적재 상호작용 (설계, Phase 2/3)
- 질문: feature를 admin이 deactivate(또는 override)했을 때, 다음 provider 적재가
  재활성화하지 않게 하려면? `prevent_provider_reactivation` 플래그를 어디에 두고
  loader가 어떻게 존중?
- 권고: feature/override에 플래그 → loader upsert가 해당 feature status 유지.
  `debug-ui-admin-workflows.md` override 섹션과 정합. 차단: T-207c.

### D-10 — list keyset cursor 구현 (설계)
- 질문: cursor 포맷(opaque token vs JSON), 정렬 동률 tie-break, 대용량 페이지 테스트?
- 권고: opaque base64(정렬키+pk), tie-break는 pk. 반영: T-206b list 함수.

### D-15 — Dagster provider 키 주입 (설계, Phase 4)
- 질문: provider 9종 키를 env/.env/secret manager 중 어디서? 키 누락 시 asset 실패
  vs skip?
- 권고: docker env(`KRTOUR_MAP_<PROVIDER>_*`) → Dagster ConfigurableResource. 키
  누락 시 해당 asset만 실패(전체 run 무중단). 반영: T-208b.

## 운영/후속

### D-5 — RustFS Docker 배치 + 백업 범위 (운영)
- 질문: RustFS를 compose 서비스로 포함? 백업은 `krtour_map`+`krtour_map_dagster`+
  RustFS 묶음? 권고: dev=compose 포함, 운영=외부 S3 호환. 백업 amendment(ADR-040).

### D-9 — `krtour-map-debug-ui` 패키지 rename 시점/이름 (운영)
- 질문: `krtour-map-admin`? `krtour-map-api`? Sprint 5 vs v2.1? npm/Docker 이미지명
  영향. 권고: 역할 분리(라우터 prefix)만 먼저, rename은 ADR-046로 분리(ADR-020 §amend).

### D-12 — React Doctor 게이트 차단성 (운영)
- 질문: blocking(미해결 시 머지 불가) vs advisory? CI 위치(per-PR/주간)? 권고:
  frontend touch PR에서 실행 + 신규 이슈 0 권고(차단은 단계적). 반영: T-209/T-207g.

### D-13 — shadcn/ui ↔ `@krtour/map-marker-react` 공존 (운영)
- 질문: 커스텀 marker를 shadcn registry에 합칠지/분리? 버전 핀? 권고: 분리 유지,
  shadcn 핀 버전. 반영: frontend 셋업 task.

### D-16 — CHANGELOG/release cadence (운영)
- 질문: API schema 변경을 CHANGELOG에 어떻게 추적? lib 버전 ≠ Docker API 버전 분리?
  권고: API 변경은 CHANGELOG `### API` 섹션 + version 태깅(D-3와 연동).

## 충돌 annotation 필요 (ADR/sprint) — plan §7과 동일, 결정과 함께 반영
ADR-003 §후속(client 표현) / ADR-005(인증, D-1) / ADR-011(큐 오참조) / ADR-031
(schema 이원, D-3) / ADR-034(Dagster 주체) / ADR-040(백업 범위, D-5) / SPRINT-5
§2.3·§2.5~2.11 / SPRINT-4 §2.9. → 결정 확정 시 각 ADR amendment + sprint 갱신.
