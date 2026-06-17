# ADR-020: 디버그/admin UI는 별도 Python 패키지 (`kor-travel-map-admin`)

- **상태**: accepted (ADR-005의 위치 부분을 supersede. ADR-035 amendment에서
  "프로덕션 admin/관리/유지보수 UI"로 운영 범위 확장 — 패키지 분리 결정은
  유지. ADR-045에서 Docker 독립 프로그램의 API/admin UI 패키지로 운영 범위 확장)
- **Amendment (2026-06-01, ADR-045 D-9)**: 패키지를 `kor-travel-map-admin` →
  **`kor-travel-map-admin`** 으로 rename(Python namespace `kortravelmap_debug_ui` →
  `kortravelmap.api`, settings env prefix `KOR_TRAVEL_MAP_DEBUG_UI_` →
  `KOR_TRAVEL_MAP_API_`, frontend `kor-travel-map-admin-frontend`, openapi.json 경로
  이동). 역할이 "debug UI"를 넘어 admin/API 프로그램으로 확장된 것을 이름에 반영.
  라우터 prefix(`/debug` vs `/admin`·`/ops`·`/features`)는 그대로. 이 ADR 본문의
  옛 이름 표기는 새 이름으로 갱신됨.
- **날짜**: 2026-05-24
- **결정자**: 사용자
- **컨텍스트**: ADR-005에서 디버그 REST API를 본 라이브러리(`kortravelmap.api`)
  안에 옵션으로 두는 것으로 설계했다. 하지만 다음 문제가 있다:
  - 본 라이브러리(`kor-travel-map`)가 FastAPI/Uvicorn 의존을 짊어진다.
    TripMate는 이미 자체 FastAPI를 가지고 있어 본 라이브러리에서 FastAPI를
    가져올 필요가 없다.
  - 함수 라이브러리(ADR-003)와 HTTP 서버가 같은 패키지에 섞이면 책임 경계가
    흐려진다.
  - 디버그 UI를 별도 배포/실행하기 어렵다 (라이브러리 import만 해도 FastAPI
    코드가 딸려 옴).
  - `kor-travel-geo`는 `kor-travel-geo-ui`를 별도 Node.js 패키지로 분리 운영
    중이다. 동일 패턴으로 일관성 확보.
- **결정**:
  - 디버그 REST API와 디버그 UI(있다면)를 별도 Python 패키지
    `kor-travel-map-admin`로 분리.
  - 본 저장소 내 `packages/kor-travel-map-admin/` 디렉토리에 패키지 소스를 둔다
    (monorepo 레이아웃, v1 동일).
  - 본 라이브러리(`kor-travel-map`)에서는 FastAPI/Uvicorn 의존성 제거.
    `[api]` extra 폐기. `src/kortravelmap/`에 `api/` 폴더 두지 않음.
  - `kor-travel-map-admin` 패키지가 `kor-travel-map`을 의존하고
    `AsyncKorTravelMapClient`를 함수 호출로 사용한다.
  - 디버그 REST는 인증 없음, 내부망 전용 (ADR-005 인증 정책 그대로 유지).
- **근거**:
  - 함수 라이브러리와 HTTP 서버의 책임 분리.
  - 본 라이브러리 의존성 최소화 (FastAPI 등 미포함).
  - kor-travel-geo와 동일한 모노레포 + 별도 패키지 패턴.
  - TripMate는 본 라이브러리만 import — 디버그 UI 코드/의존성에 영향받지 않음.
- **결과 (긍정)**:
  - 본 라이브러리 install footprint 축소.
  - 디버그 UI 자체적으로 버전 관리 / 배포 가능.
  - 디버그 UI에 Streamlit, Next.js bridge, 임의 frontend 도입이 본 라이브러리에
    영향 없음.
- **결과 (부정)**:
  - 패키지 2개 관리 부담 (pyproject 2개).
  - 디버그 UI는 본 라이브러리 버전을 따라가야 함 — release 동기 필요.
- **후속**:
  - `pyproject.toml`에서 `[api]` extra 제거.
  - `packages/kor-travel-map-api/pyproject.toml` 신규.
  - `docs/architecture/architecture.md`, `docs/architecture/backend-package.md`, `docs/architecture/debug-ui-package.md`
    갱신/신규.
  - `import-linter` 계약에서 `kortravelmap.api` 제거.
