# ADR-035: 디버그/관리 REST API는 프로덕션 환경에서도 admin/유지보수 UI로 운영

- **상태**: accepted (PR#33, 2026-05-27) — 'debug-ui' 범위 표현 일부는 ADR-045로 supersede(운영 모델 = Docker 독립 프로그램 + admin OpenAPI 연동).
- **날짜**: 2026-05-27
- **결정자**: 사용자

### 컨텍스트

ADR-005/ADR-020에서 `kor-travel-map-admin` 패키지는 "디버그 + 내부망 전용 + 인증
없음"으로 정의되었다. 운영 단계에 들어가면서 다음 요구가 등장:

- 운영자가 적재 jobs / dedup queue / consistency reports / RustFS 사용량 등을
  **실시간으로 보고 손볼** UI가 필요.
- 외부 소비 앱에 admin 화면을 별도로 만들 만큼 트래픽이 없음 — `kor-travel-map-
  debug-ui` 패키지를 그대로 admin UI로 활용하는 게 자연.
- 단, 인증 키는 본 패키지 코드 안에 박지 않는다 (ADR-005 원칙 유지). 네트워크
  계층(Cloudflare Tunnel + SSO 게이트웨이 / IP allowlist)에서 보호.

### 결정

- `kor-travel-map-admin` 패키지의 운영 범위를 **"디버그 + 내부망 전용"에서 "디버그
  + admin/유지보수/프로덕션 운영"으로 확장**.
- 인증/접근 제어는 여전히 코드 외부 (Cloudflare Tunnel / SSO / IP allowlist).
  패키지 자체에 인증 로직 추가 금지(ADR-005 §SKILL DO NOT #14 그대로).
- 프로덕션에서 노출되는 라우터 prefix는 `/admin/...` 또는 `/ops/...`로 분리해
  디버그용(`/debug/...`)과 시각적으로 구분.
- 운영 라우터는 **읽기 우선** + 쓰기는 explicit confirmation 필수(예: rerun
  job, manual dedup decision). delete/purge는 별도 ADR.

### 근거

- 별도 admin 앱을 만들면 인증·DB 연결·이슈 디버깅이 모두 중복.
- 디버그 패키지에 admin 라우터를 더하면 한 코드베이스가 됨 — 발견된 버그가
  운영에 즉시 반영.
- 인증을 코드에서 떼어내면 패키지 자체가 가볍고, 인프라 보안 정책 변경 시 코드
  수정 불필요.

### 결과 (긍정)

- 운영자/개발자가 같은 UI에서 같은 데이터를 봄 → 일관성.
- 운영 라우터가 patch/post 빈도가 낮아 부담 적음.

### 결과 (부정)

- 운영용 admin UI는 결국 인증이 필요한데, 인프라 계층에 의존하면 PC 개발자가
  로컬에서 실수로 외부 노출하면 위험 → README/Settings에 경고 + `KOR_TRAVEL_MAP_
  DEBUG_UI_HOST` 기본 `127.0.0.1` 강제 유지.

### 후속

- `docs/architecture/debug-ui-package.md` §"운영 라우터" 추가 — `/admin/jobs`, `/admin/dedup-
  review`, `/ops/consistency`, `/ops/rustfs-usage` 등 prefix 분리.
- `docs/adr/README.md` ADR-005/020 supersede note 추가 (본 PR에서 동시).
- `packages/kor-travel-map-admin/README.md` "프로덕션 admin 가이드" 절 추가.
