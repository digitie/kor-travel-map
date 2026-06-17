# ADR-005: 디버그 REST API는 인증 없음, 내부망 전용

- **상태**: accepted (위치 부분은 ADR-020에서 superseded — 디버그 REST는 별도
  패키지 `kor-travel-map-admin`에 둠. 인증 없음 + 내부망 전용 정책은 ADR-035
  amendment에서 "프로덕션 admin/관리 라우터로도 운영 가능"으로 확장 — 인증/
  네트워크 보호는 앱 코드 밖 infra(reverse proxy/SSO 게이트웨이) 책임이라는
  근본 원칙은 그대로)
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: 라이브러리는 자체 FastAPI 라우터(`kortravelmap.api`)를 옵션으로
  노출한다. 목적은 디버그 UI 백엔드 + 향후 내부 활용. 외부 경계는 OpenAPI이며,
  외부 소비자는 이 API를 HTTP로 호출할 뿐 라이브러리에 의존하지 않는다.
- **결정**: 디버그 API에 인증 키, JWT, OAuth 등 어떤 인증 로직도 추가하지
  않는다. 내부망(localhost, WSL, 사내망) 사용을 전제로 한다.
- **Amendment (2026-06-02, ADR-045 D-1)**: ADR-045로 API가 외부에도 서비스되지만
  **코드에 인증 로직을 추가하지 않는 원칙은 유지**한다. 운영 인증은 **infra 계층**
  (reverse proxy SSO + IP allowlist)이 책임진다. 앱은 인증을 검증하지 않고
  "인증된 요청만 도달"을 가정하며(로그/감사만), 미인증 요청은 reverse proxy에서
  차단한다.
- **Amendment (2026-06-08, D-1 "B안" defense-in-depth)**: 운영 인증의 **1차 책임은
  여전히 infra 계층**이나, 그 위에 **얇은 앱 레벨 방어를 옵션으로** 더한다(네트워크를
  무조건 신뢰하지 않기 위함). `map_admin/auth.py`:
  - `service_token`(`KOR_TRAVEL_MAP_API_SERVICE_TOKEN`, opt-in) 설정 시 **service read
    엔드포인트 `POST /features/batch`**에서 `X-Kor-Travel-Map-Service-Token`을 **상수시간 비교**로
    검증(불일치/누락 → 401). 미설정이면 강제하지 않음(intranet/dev 하위호환). **공용 read
    surface(`/features` GET·`/categories`·`/providers`)는 브라우저 admin UI도 쓰므로 앱 토큰을
    강제하지 않는다**(operator는 proxy SSO). (batch는 소비자 중립 경로 `/features/batch`로
    일반화되며 route-level gate.)
  - `admin_destructive_enabled=False`(kill-switch) 시 파괴적 `/admin` 작업
    (restore/swap/deactivate/POI delete) 차단(403).
  - `APIKeyHeader`를 통해 OpenAPI `securitySchemes.ServiceToken`이 선언되고
    `POST /features/batch` operation에 `security`가 기록된다(계약 문서화, API 리뷰 P1 해소).
- **근거**:
  - `kor-travel-geo` ADR-013과 동일 패턴 (디버그 UI 내부망 전용).
  - 라이브러리 코드/응답에 인증 로직이 침투하지 않음 → 코드 단순.
  - 외부 노출이 필요해지면 네트워크 계층(reverse proxy SSO 게이트웨이,
    IP allowlist)에서 보호.
- **결과 (긍정)**: 라이브러리 코드 단순화, 디버그 UI 개발 가속.
- **결과 (부정)**: 운영자가 잘못 외부에 노출하면 데이터 유출 위험.
  → 배포 가이드에서 `127.0.0.1` 바인드를 default로 강제.
- **후속**: `KOR_TRAVEL_MAP_DEBUG_API_HOST=127.0.0.1` default. 0.0.0.0 바인드 시
  경고 로그.
