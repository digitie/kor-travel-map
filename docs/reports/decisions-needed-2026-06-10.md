# 의사결정 필요 항목 (2026-06-10 크로스레포 검토)

> **상태 (2026-06-10 2차 갱신)**: **전 항목 종결** — 1차: D-01(b 잠정, 추후 분리) ·
> D-02~05(a) · D-06(수정 승인: `/admin/etl` 유지) · D-08/09(권고안). 2차: D-07(a) ·
> D-10(a, T-066 운영 개시 전 분리) · D-11(a, 익명) · D-12(a, `found`+status) ·
> D-13(확인 — KASI류 고유 ETL만, 중복 없음). 정본 반영: **ADR-050~052(+보강)** +
> tasks **T-217a~g** + CLAUDE.md. 각 항목 하단의 `결정` 줄 참조.
> **근거 상세**: [`service-completeness-review-2026-06-10.md`](service-completeness-review-2026-06-10.md).
> 각 항목에 권고안(★)을 명시한다.

---

## D-01. RustFS 버킷 소유권 — tripmate-agent 미디어의 저장 위치

- **현황**: tripmate-agent가 원본 영상/자막/전사/프레임(무기한 보존)을 krtour-map 소유
  버킷(`RUSTFS_BUCKET_*=krtour-map`, prefix `features/`)에 직접 저장 (tripmate-agent
  `backend/app/core/config.py`). krtour-map의 rustfs는 "선택" 구성요소로 offline upload
  용도(ADR-045).
- **문제**: 백업/restore(krtour `admin/backups`)·수명주기·용량·접근권한 책임이 두 시스템에
  걸쳐 모호. krtour 백업 정책이 타 시스템의 대용량 미디어까지 떠안을 수 있음.
- **옵션**:
  - (a) ★ **버킷 분리**: tripmate-agent 전용 버킷(`tripmate-agent`)으로 이전, krtour는
    필요 시 URL만 참조. 소유권 명확, krtour 백업 범위 불변. 비용: tripmate-agent 설정/마이그레이션.
  - (b) 공유 유지 + 정책 명문화: prefix 단위 소유권·수명주기·백업 제외 규칙을 양 repo ADR로.
  - (c) krtour가 미디어 소유 인수: evidence 미디어를 feature 자산으로 정식 편입. 범위 큼.
- **반영처**: 승인 시 krtour ADR(+`docs/architecture.md` rustfs 절), tripmate-agent ADR·config.
- **결정(2026-06-10)**: ✅ **(b) 잠정 채택 — 공유 유지 + 정책 명문화, 추후 (a) 전용 버킷 분리 예정**.
  → ADR-052 + T-217e. 후속 결정 D-10은 2차에서 종결 (T-066 운영 개시 전 분리).

## D-02. 사용자 장소 제보(FeatureSuggestion) 릴레이 메커니즘

- **현황**: TripMate에 제보 모델·일일 한도(20건)까지 있으나 krtour로 흐르는 공식 경로 없음.
  krtour는 TripMate의 `/v1/admin/*` 직접 호출을 금지 (`docs/tripmate-rest-api.md` §2).
- **옵션**:
  - (a) ★ **krtour에 서비스용 제보 수신 API 신설**: 예 `POST /v1/features/suggestions`
    (ServiceToken, rate-limit). krtour `admin/features/change-requests` 큐로 합류 —
    기존 승인 flow 재사용, R&R 유지. 비용: krtour API+화면 1식.
  - (b) 운영자 수동 릴레이: TripMate admin에서 보고 krtour admin에 수동 입력. 비용 0,
    확장성 없음 — 초기 임시안으로만.
  - (c) TripMate api가 krtour admin API 호출: 관리망 인증 경계 침범 — 비권장.
- **반영처**: krtour ADR + rest-api.md + tasks, TripMate TM-13.
- **결정(2026-06-10) — 최종**: 옵션 (a)의 "신규 수신 API 신설"은 같은 날 2차 재독에서
  **superseded(기각)** — 취지(승인분 자동 전송)는 **기존 `/v1/admin/features*` change
  API(#317)** 승인으로 충족한다 (아래 2차 보정, ADR-051 보정본). T-217c = 신규 API
  구현이 아니라 **잔여 합의 5건 확정**. 후속 결정 D-11은 2차에서 종결(익명 —
  TripMate 측 참조 ID만).
- **보정(2026-06-10, 사용자 확인)**: 본 항목의 "공식 경로 없음"은 과대 기술 — 설계는
  **2단 검토**(TripMate 사용자 요청 → TripMate admin 1차 검토 `/admin/feature-requests`
  → krtour-map admin 최종 반영)로 이미 존재하며(`docs/tripmate-rest-api.md` §2),
  실제 갭은 **TripMate admin 승인분 → krtour-map 자동 전송 구간**이다.
- **2차 보정(2026-06-10, 재독)**: 그 전송 구간조차 **이미 설계·구현돼 있었다** —
  krtour PR #317(K-15)의 admin feature change API(`/v1/admin/features*` +
  change-requests 큐)가 정확히 이 용도로 신설됐고, TripMate DEC-05(2026-06-08 확정)
  + T-179/T-180이 이를 호출하는 계획을 보유(`docs/integrations/krtour-map-rest-api.md`
  §2.8/2.9). 따라서 **신규 수신 API(`POST /v1/features/suggestions`) 신설안은 중복으로
  철회** — ADR-051은 기존 change API를 전송 구간으로 승인 + 잔여 합의 5건
  (review_mode/idempotency/출처 태깅/admin 인증/closure) 확정으로 재정의(T-217c).
  부수 발견: TripMate 측 "admin base = 9012" 가정은 오류(9012는 admin UI, admin
  API는 9011 `/v1/admin/*`) — TripMate 정정 대상.

## D-03. tripmate-agent 후보 철회(reject/tombstone)의 krtour 라이프사이클 처리

- **현황**: krtour provider 변환부가 `operation != upsert`를 건너뜀
  (`src/krtour/map/providers/tripmate_agent.py:76,87`) → 검수 철회된 후보가 krtour
  feature로 영구 잔존. export 계약에는 `reject`/`tombstone`이 정의돼 있음
  (tripmate-agent `docs/youtube-feature-pipeline-plan.md` §7.2).
- **옵션**:
  - (a) ★ **inactive 전환 구현**: MOIS Step C(폐업→inactive)와 동형으로
    reject/tombstone → 해당 feature deactivate(+사유 기록). 계약 의미 완결.
  - (b) 1단계 가시화 → 2단계 자동화: 우선 skip 건수를 WARN/admin 이슈로 노출, 자동
    deactivate는 후속. (a)보다 빨리 출하 가능.
  - (c) 현행 유지(영구 잔존) — 데이터 품질상 비권장.
- **반영처**: krtour 코드+tasks(신규 T-2xx), ADR-049 보강.
- **결정(2026-06-10)**: ✅ **(a) 채택** → ADR-050 #4 + T-217b. 후속 결정 D-12는
  2차에서 종결 (`found`+status 노출).

## D-04. tripmate-agent export 계약의 정본 위치

- **현황**: 계약 전문(스키마·cursor·operation)이 tripmate-agent
  `docs/youtube-feature-pipeline-plan.md` §7 — **계획 문서**에만 존재. krtour 측은
  ADR-049 + fetcher 코드. 계획 문서는 완료 후 동결되는 성격이라 정본으로 부적합.
- **옵션**:
  - (a) ★ **tripmate-agent에 독립 계약 문서 신설**(예 `docs/krtour-export-api.md`)을
    정본으로, krtour `docs/rest-api.md`(또는 external-apis.md)에서 링크+소비 요약.
    공급자 repo가 정본을 갖는 기존 관행(ADR-044 "정합성 1차 책임=공급 라이브러리")과 일치.
  - (b) krtour 측 문서를 정본으로: 소비자가 정본을 갖는 역전 — 비권장.
- **반영처**: tripmate-agent 문서(해당 repo에 전달 완료 — `docs/cross-repo-consistency-actions-2026-06-10.md`), krtour 문서 링크.
- **결정(2026-06-10)**: ✅ **(a) 채택** → ADR-050 #2. 추가로 사용자 보정: export 경로에
  downstream 이름을 넣지 않는다(`/api/v1/features/*`) → ADR-050 #1 + T-217a.

## D-05. YouTube 발 후보 feature의 사용자 노출 정책

- **현황**: export는 검수 상태와 `confidence_score`를 포함하지만, krtour→TripMate 경로에서
  "어떤 상태의 후보까지 일반 사용자에게 보일지" 정책이 없음. 현재는 적재되면 공공데이터
  feature와 동급 노출.
- **옵션**:
  - (a) ★ **검수 통과(matched/user_corrected)만 export** — tripmate-agent export 쿼리에서
    필터(이미 needs_review 제외라면 명문화만). + TripMate UI에 출처 배지(TM-08).
  - (b) 전부 노출 + confidence 배지로 구분: 데이터 풍부하나 품질 리스크.
  - (c) krtour에서 별도 kind/검색 가중치로 격리: 복잡도 대비 이득 불명.
- **반영처**: tripmate-agent export 명세, krtour ADR-049 보강, TripMate UX 기획.
- **결정(2026-06-10)**: ✅ **(a) 채택 — 검수 통과만 export** → ADR-050 #3, tripmate-agent TA-03.

## D-06. TripMate admin 표면 축소 범위

- **현황**: TripMate `/admin/features` 편집 placeholder, `/admin/category-mapping`,
  `/admin/etl`·`/admin/seed`·`/admin/reset` placeholder — feature 쓰기·카테고리 정본은
  krtour 책임.
- **권고(★)**: 검토 보고서 §2.3대로 read-only+릴레이로 축소, placeholder 제거,
  category-mapping은 `GET /v1/categories` 뷰로 대체. (TripMate TM-12)
- **반영처**: TripMate 백로그/문서.
- **결정(2026-06-10)**: ✅ **수정 승인** — `/admin/features` 편집 축소·category-mapping
  정리는 권고대로 진행하되, **TripMate는 자체 ETL 관리 로직이 있으므로 `/admin/etl`은
  유지**한다(제거 대상에서 제외). **후속 확인 필요**: 유지하는 "자체 ETL"과 krtour
  T-210c(`apps/etl` 레거시 Dagster 이관/삭제)의 경계 (D-13 참조).

## D-07. krtour provider 동기화 대시보드 신설

- **현황**: `GET /v1/providers/{provider}/last-sync` 단건만. 20+ provider×dataset의
  신선도/실패 한눈 보기 부재 (검토 §3.2 A-2).
- **옵션**: (a) ★ 목록 API(`GET /v1/providers` + last-sync/최근 실패 요약) + admin 화면 1식
  (b) Dagster 페이지에 신선도 칼럼 추가로 갈음 (c) 보류.
- **반영처**: krtour tasks(신규), rest-api.md.
- **결정(2026-06-10, 2차)**: ✅ **(a) 채택** → T-217g (목록 API + admin 화면).

## D-08. 3-시스템 envelope/에러 형식의 의도적 차이 명문화

- **현황**: krtour `{data,meta}`+RFC7807 / tripmate-agent export `{items,has_more,next_cursor}`
  무-envelope / TripMate 자체 `Envelope`. 통일 시도는 비용 대비 이득이 없다고 판단.
- **권고(★)**: 통일하지 않되, cross-repo 연동 정본 문서(uplift-plan KR-04)에 "표면별
  형식과 이유" 표 1개로 고정해 향후 "왜 다르지" 재논의 방지. 인증 방식 이원화(C-9:
  `X-Krtour-Service-Token` vs `X-API-Key`)도 같은 표에 명시.
- **반영처**: krtour 연동 정본 문서.
- **결정(2026-06-10)**: ✅ **권고안 채택** → T-217d (`docs/integration-map.md` + 분기 audit runbook).

## D-09. TripMate v0.1.0 출시 게이트 재평가 (TripMate DEC-06)

- **현황**: TripMate가 "snapshot-only 출시 vs krtour 연동 대기"를 저울질했으나 전제
  (krtour HTTP 미존재)가 노후. krtour는 준비 완료, 남은 것은 TripMate 배선(TM-01~06).
- **권고(★)**: "연동 후 출시"로 재평가. 배선 작업량은 외부 의존 없는 TripMate 내부
  작업뿐이다. (최종 결정은 TripMate repo에서)
- **반영처**: TripMate DEC-06/백로그.
- **결정(2026-06-10)**: ✅ **권고안 채택** — "연동 후 출시"로 재평가. TripMate 측 반영은
  `tripmate-side-actions-2026-06-10.md` TM-04(DEC-06 재평가)·TM-06(배선)으로 이관.

---

## 2026-06-10 결정에서 파생된 추가 의사결정 (2차 결정 완료)

> 1차 결정(D-01~09) 처리 중 식별된 후속 결정.
> **2026-06-10 2차 결정 완료**: D-10~12 권고안 채택, D-13 사용자 확인(중복 없음 —
> KASI류 고유 ETL만 관리). 각 항목 하단 `결정` 줄 참조. **전 항목 종결**.

### D-10. RustFS 전용 버킷 분리의 시점/트리거 (D-01 후속)

- D-01을 (b) 잠정으로 채택하며 "추후 분리"가 확정됨 — 언제/무엇을 트리거로 분리할지 미정.
- **옵션**: (a) ★ T-066 운영 개시(실데이터 pull 시작) 전 분리 — 운영 데이터가 쌓이기 전이
  마이그레이션 비용 최소 (b) 용량/객체수 임계 도달 시 (c) 별도 스프린트에서 일괄.
- **반영처**: ADR-052 보강, tripmate-agent config 기본값 변경 + 마이그레이션 계획.
- **결정(2026-06-10, 2차)**: ✅ **(a) 채택 — T-066 운영 개시 전 분리** → ADR-052 보강,
  T-217e, tripmate-agent TA-04.

### D-11. 제보 수신 API 페이로드의 사용자 식별 정보 범위 (D-02 후속, PIPA)

- TripMate 제보가 krtour change-requests 큐로 넘어올 때 개인정보를 어디까지 싣는가.
- **옵션**: (a) ★ 익명 — TripMate 측 불투명 참조 ID(suggestion_id)만 싣고, 필요 시
  TripMate admin에서 역추적 (krtour에 개인정보 비저장 — PIPA 부담 없음)
  (b) 최소 식별(닉네임 등) 포함 — krtour 측 표시 편의 ↔ 개인정보 처리 범위 확장.
- **반영처**: ADR-051 보강, T-217c 설계.
- **결정(2026-06-10, 2차)**: ✅ **(a) 채택 — 익명, TripMate 측 참조 ID만** → ADR-051
  결과 절 보강, T-217c.

### D-12. inactive 전환된 feature의 소비자 응답 정책 (D-03 후속)

- reject/tombstone으로 inactive가 된 feature를 TripMate가 batch/단건 조회할 때:
- **옵션**: (a) ★ `found`에 포함하되 status(inactive)를 노출 — TripMate가 POI에
  "더 이상 유효하지 않은 장소" 표시 가능, snapshot fallback과도 자연 결합
  (b) `missing` 처리 — 단순하나 "삭제됨"과 "철회됨"을 구분 못 해 사용자 혼란.
- 기존 krtour deactivate(`POST /v1/admin/features/{id}/deactivate`)된 feature의 read
  응답 정책과 **일관**해야 함 — 현행 정책 확인 후 동일하게.
- **반영처**: ADR-050 #4 보강, T-217b 설계, TripMate TM-06 매핑.
- **결정(2026-06-10, 2차)**: ✅ **(a) 채택 — `found` 포함 + status 노출** (기존 admin
  deactivate read 정책과 일관 검증 포함) → ADR-050 결과 절 보강, T-217b.

### D-13. TripMate "자체 ETL"의 범위 vs krtour T-210c (D-06 후속, 확인 사항)

- D-06에서 `/admin/etl` 유지가 결정됨. 한편 krtour T-210c는 "TripMate `apps/etl`
  레거시 Dagster(구 krtour 함수 직접 호출 모델 잔재) 이관/삭제"를 외부 추적 중.
- **확인 필요**: 유지할 "자체 ETL 관리 로직"이 ① TripMate 고유 데이터 잡(예: trip
  통계, 이메일 큐 등)이라면 → T-210c(krtour 잔재 삭제)와 양립, `/admin/etl`은 고유
  잡 관제 화면으로 유지 ② 구 `apps/etl`의 krtour 적재 잡까지 포함이라면 → ADR-045
  (krtour Dagster 소유)와 충돌하므로 범위 재협의.
- **반영처**: TripMate TM-12 보강, krtour T-210c 비고.
- **결정(2026-06-10, 2차)**: ✅ **사용자 확인 — ① 해당 (중복 없음)**. TripMate 자체
  ETL은 KASI(일출/일몰)류 **TripMate 고유 데이터 잡만** 관리하며 krtour-map 적재와
  무관. `/admin/etl`은 고유 잡 관제 화면으로 유지, T-210c(구 krtour 적재 레거시
  이관/삭제)와 양립 — 충돌 없음.

---

### 처리 현황 요약 (2026-06-10)

| 결정 | 결과 | 정본 반영 |
|---|---|---|
| D-01 | (b) 잠정 채택, 추후 분리 | ADR-052, T-217e |
| D-02 | (a) → 2차 보정: 신규 API 철회, 기존 #317 change API 승인 | ADR-051(보정), T-217c(합의 5건) |
| D-03 | (a) | ADR-050 #4, T-217b |
| D-04 | (a) + 경로 중립화 보정 | ADR-050 #1·#2, T-217a |
| D-05 | (a) | ADR-050 #3, tripmate-agent TA-03 |
| D-06 | 수정 승인 (`/admin/etl` 유지) | TripMate TM-12 보강 |
| D-07 | (a) 채택 (2차) | T-217g |
| D-08 | 권고안 | T-217d |
| D-09 | 권고안 | TripMate TM-04/06 |
| D-10 | (a) T-066 운영 개시 전 분리 (2차) | ADR-052 보강, T-217e, TA-04 |
| D-11 | (a) 익명 참조 ID만 (2차) | ADR-051 보강, T-217c |
| D-12 | (a) `found`+status 노출 (2차) | ADR-050 보강, T-217b |
| D-13 | 확인 완료 — 중복 없음, KASI류 고유 ETL만 (2차) | TripMate TM-12 |

**전 항목 종결 (2026-06-10).** 잔여 의사결정 없음 — 이후 신규 결정은 별도 문서/ADR로.
