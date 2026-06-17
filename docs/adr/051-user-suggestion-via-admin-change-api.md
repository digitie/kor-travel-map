# ADR-051: TripMate 사용자 feature 제안의 kor-travel-map 반영은 기존 admin feature change API를 전송 구간으로 쓴다

### 상태

Accepted (2026-06-10) — `docs/reports/decisions-needed-2026-06-10.md` D-02.
같은 날 2차 재독에서 **신규 수신 endpoint 신설안을 철회**하고 기존 설계 승인으로 보정
(아래 배경 참조).

### 배경

설계된 흐름은 **2단 검토**다: TripMate 사용자가 feature 추가/수정/삭제를 요청
(`app.feature_suggestions`, TripMate T-177 완료) → **TripMate admin이 1차 검토**
(`/admin/feature-requests` 큐, TripMate T-179) → 승인분을 kor-travel-map에 전달 →
**kor-travel-map에서 반영**. 이 마지막 구간을 위해 kor-travel-map은 이미 PR #317(K-15)로
**admin feature change API**(`POST/PATCH/DELETE /v1/admin/features*` +
`change-requests` 검수 큐, `require_admin_destructive_enabled` + 서비스 토큰)를
신설했고, TripMate는 admin 전용 client(T-180)로 이를 호출하는 계획을 확정했다
(TripMate DEC-05, 2026-06-08; `docs/integrations/kor-travel-map-rest-api.md` §2.8/§2.9).

1차 검토 보고서가 이 구간을 "공식 경로 없음"으로 보고 별도 수신 API
(`POST /v1/features/suggestions`)를 제안했으나, 이는 **기존 #317 설계와 기능 중복**
이다 — 철회한다.

### 결정

- **신규 수신 endpoint를 만들지 않는다.** TripMate admin 1차 승인분의 전송 구간은
  기존 **`/v1/admin/features*` feature change API**(#317)다.
- 2단 검토 유지: TripMate admin 1차 검토 → kor-travel-map `change-requests` 큐
  (`KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE`에 따라 kor-travel-map 운영자 최종
  승인 또는 immediate 적용).
- TripMate↔kor-travel-map **잔여 합의 5건**(TripMate 문서 §7에 질의로 등재됨)을 kor-travel-map이
  확정·문서화한다 (T-217c 재정의):
  1. review_mode — TripMate 출처 요청의 이중 검수 여부 (`require_review` vs `immediate`).
  2. `idempotency_key` 멱등성 — 같은 제안 재시도 시 동일 feature_id 보장.
  3. 출처 태깅 — TripMate `suggestion_id` 추적 필드 방식.
  4. admin 인증 — TripMate admin client의 `/v1/admin/*` 호출 토큰/경로. **주의**:
     admin API는 **12701 `/v1/admin/*`**이다 (12705는 admin UI — TripMate 문서의
    "admin base 12705" 가정은 오류, TripMate 측 정정 대상).
  5. closure 표현 — 영구 폐업 = soft `DELETE` vs `deactivate` 권장안.

### 결과

- T-217c 재정의: 신규 API 구현이 아니라 **합의 5건 확정 + `docs/architecture/rest-api.md`·
  `docs/architecture/tripmate-rest-api.md` 반영 + change-requests 큐에 TripMate 출처 식별 표시**.
- 출처 태깅의 사용자 식별 정보 범위 확정(D-11, 2026-06-10): **익명** — TripMate 측
  불투명 참조 ID(suggestion_id)만 싣고 kor-travel-map은 개인정보를 저장하지 않는다.
  역추적이 필요하면 TripMate admin에서 수행한다 (PIPA 부담 비전이).
- 거절/반려의 역방향 통지(kor-travel-map 최종 거절 → TripMate `feature_suggestions`
  상태 갱신)는 TripMate가 `request_id`/state 폴링으로 처리(기존 설계) — 별도 push 불요.
- **잔여 합의 5건 확정 (2026-06-11, T-217c — 코드 실측 기반, 소비 계약은
  `docs/architecture/tripmate-rest-api.md` §"사용자 제안 연동 합의"):**
  1. **review_mode**: 기본 `require_review` 유지 — TripMate 1차 검수가 있어도
     kor-travel-map admin이 최종 반영 권한을 갖는 2단 검토가 설계 의도다. 운영 합의로
     `KOR_TRAVEL_MAP_API_FEATURE_CHANGE_REVIEW_MODE=immediate` 전환 가능(전역 설정).
  2. **idempotency_key 멱등**: `feature_id` 미지정 create에서
     `make_feature_id(source_type="user_request",
     source_natural_key=idempotency_key)`로 **결정적 feature_id**를 생성한다 —
     같은 key 재시도 = 같은 feature_id(upsert 충돌 정책은 version 1 모델, #317).
     TripMate는 `idempotency_key=suggestion_id` 사용을 권장.
  3. **출처 태깅**: 전용 필드 없이 기존 필드 컨벤션 — `operator: "tripmate-admin"`
     고정 + `reason` 머리에 `[suggestion:<suggestion_id>]` prefix. change-requests
     큐(API/admin UI)가 reason을 표시하므로 추가 코드 없이 출처 식별 가능(D-11 익명).
  4. **admin 인증**: admin API는 **12701 `/v1/admin/*`**(12705는 admin UI). 코드 인증은
     `admin_destructive_enabled` kill-switch뿐이고 호출자 인증은 인프라 계층(SSO/IP
     allowlist, ADR-005 모델) — TripMate admin client는 관리망 경로로 12701에 도달해야
     한다.
  5. **closure**: 영구 폐업/사용자 삭제 = **soft `DELETE`**(`user_deleted_*` 계열 —
     provider 재적재 부활 차단, #332) / 일시 중단·운영 비활성 =
     `POST .../deactivate`(`status='inactive'`, provider 폐업과 동일 표현,
     read에서 `found`+status 노출 — D-12).
