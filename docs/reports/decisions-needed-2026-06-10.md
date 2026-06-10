# 의사결정 필요 항목 (2026-06-10 크로스레포 검토)

> **상태**: 의사결정 대기 — 사용자 검토 후 승인된 항목만 각 정본(ADR/decisions.md 등)에
> 반영한다. 어느 것도 아직 정본에 반영하지 않았다.
> **근거 상세**: [`service-completeness-review-2026-06-10.md`](service-completeness-review-2026-06-10.md).
> 각 항목에 권고안(★)을 명시한다. 승인 시 krtour-map은 ADR-049 다음 번호(**ADR-050~**)로 기록.

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

## D-06. TripMate admin 표면 축소 범위

- **현황**: TripMate `/admin/features` 편집 placeholder, `/admin/category-mapping`,
  `/admin/etl`·`/admin/seed`·`/admin/reset` placeholder — feature 쓰기·카테고리 정본은
  krtour 책임.
- **권고(★)**: 검토 보고서 §2.3대로 read-only+릴레이로 축소, placeholder 제거,
  category-mapping은 `GET /v1/categories` 뷰로 대체. (TripMate TM-12)
- **반영처**: TripMate 백로그/문서.

## D-07. krtour provider 동기화 대시보드 신설

- **현황**: `GET /v1/providers/{provider}/last-sync` 단건만. 20+ provider×dataset의
  신선도/실패 한눈 보기 부재 (검토 §3.2 A-2).
- **옵션**: (a) ★ 목록 API(`GET /v1/providers` + last-sync/최근 실패 요약) + admin 화면 1식
  (b) Dagster 페이지에 신선도 칼럼 추가로 갈음 (c) 보류.
- **반영처**: krtour tasks(신규), rest-api.md.

## D-08. 3-시스템 envelope/에러 형식의 의도적 차이 명문화

- **현황**: krtour `{data,meta}`+RFC7807 / tripmate-agent export `{items,has_more,next_cursor}`
  무-envelope / TripMate 자체 `Envelope`. 통일 시도는 비용 대비 이득이 없다고 판단.
- **권고(★)**: 통일하지 않되, cross-repo 연동 정본 문서(uplift-plan KR-04)에 "표면별
  형식과 이유" 표 1개로 고정해 향후 "왜 다르지" 재논의 방지. 인증 방식 이원화(C-9:
  `X-Krtour-Service-Token` vs `X-API-Key`)도 같은 표에 명시.
- **반영처**: krtour 연동 정본 문서.

## D-09. TripMate v0.1.0 출시 게이트 재평가 (TripMate DEC-06)

- **현황**: TripMate가 "snapshot-only 출시 vs krtour 연동 대기"를 저울질했으나 전제
  (krtour HTTP 미존재)가 노후. krtour는 준비 완료, 남은 것은 TripMate 배선(TM-01~06).
- **권고(★)**: "연동 후 출시"로 재평가. 배선 작업량은 외부 의존 없는 TripMate 내부
  작업뿐이다. (최종 결정은 TripMate repo에서)
- **반영처**: TripMate DEC-06/백로그.

---

### 승인 후 처리 순서 제안

D-01·D-03·D-04(경계 확정) → D-02·D-05(데이터 유입 정책) → D-06·D-07(표면 정리) →
D-08(명문화) → D-09(출시 게이트). 승인된 항목은 krtour-map은 ADR-050~ + 해당 정본,
TripMate/tripmate-agent는 각 repo 결정 문서에 반영한다.
