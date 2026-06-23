# ADR-060 — Admin 로그인, frontend proxy, public API key

- 상태: accepted
- 날짜: 2026-06-23

## 맥락

기존 ADR-005/035는 admin UI와 debug REST를 내부망 전제로 두고 코드 레벨 인증을 두지
않았다. 그러나 admin UI가 운영 기능과 외부 노출 API key 발급까지 담당하게 되면서,
브라우저에서 FastAPI를 직접 호출하는 구조는 세션·감사 기록·API key 관리 요구를 만족하기
어렵다.

`kor-travel-geo` PR#399에서 같은 문제를 Next.js admin UI 로그인, HttpOnly 세션 쿠키,
Next API proxy, backend trusted-proxy header, VWorld 호환 public API key로 해결했다.
`kor-travel-map`도 같은 UX와 보안 경계를 따른다.

## 결정

1. Admin frontend는 `admin` 단일 계정으로 로그인한다. 비밀번호 원문은 저장하지 않고
   PBKDF2-SHA256 해시만 gitignored `.env`에 둔다.
2. 세션은 Next.js server-side 코드가 서명한 HttpOnly/SameSite=Strict cookie로 관리한다.
   세션 payload에는 만료 시간, session id, user-agent fingerprint를 넣고 logout 시 process-local
   revocation map에 등록한다.
3. 브라우저의 FastAPI REST 호출은 `/api/proxy` Next BFF를 통한다. BFF는 세션 검증 후
   `X-Kor-Travel-Map-Actor`와 `X-Kor-Travel-Map-Admin-Proxy-Secret`을 FastAPI에 주입한다.
   FastAPI admin router는 secret이 설정된 환경에서 이 헤더와 trusted proxy CIDR을 확인한다.
4. 로그인 시도와 로그아웃은 `ops.admin_auth_events`에 저장하고 admin settings 화면에서 조회한다.
   감사 기록 실패는 로그인 성공/실패 응답을 깨뜨리지 않는 best-effort로 처리한다.
5. Public API key는 `ops.public_api_keys`에 SHA-256 hash와 hint만 저장한다. 원문 key는 생성
   응답에서 한 번만 보여준다. 검증 hot path는 active hash를 process-local TTL cache로 보관하고
   생성/폐기 시 cache를 무효화한다.
6. Public REST surface는 `key` query parameter를 VWorld 호환 32자 영숫자 형식으로 받는다.
   trusted admin proxy 또는 service-token 요청은 key 검증을 우회한다.
7. `kor-travel-geo` v2 호출은 PR#399 이후 `key` query를 붙인다. 현재 운용에서는 VWorld API key와
   같은 값을 쓴다.
8. Login rate-limit/audit의 client IP는 기본적으로 `X-Forwarded-For`/`X-Real-IP`를 신뢰하지
   않는다. reverse proxy가 해당 헤더를 덮어쓰는 배포에서만
   `KOR_TRAVEL_MAP_UI_TRUST_PROXY_HEADERS=true`로 opt-in한다.
9. Username이 맞지 않아도 PBKDF2 password verification을 수행해 timing 차이를 줄인다.

## 결과

- Admin UI는 로그인 전 모든 app/API route를 `/login`으로 보낸다.
- FastAPI secret은 브라우저에 노출되지 않는다.
- DB에는 API key 원문이 남지 않는다.
- 기존 로컬/테스트 하위호환을 위해 `admin_proxy_secret`이 없는 설정에서는 admin gate를 강제하지
  않는다. 실제 운용 `.env`에는 secret을 넣어 프론트 프록시 경계를 활성화한다.
- `kor-travel-geo` 호출 경로(CLI/API/Dagster/live test)는 같은 settings key 추출 규칙을 공유한다.
