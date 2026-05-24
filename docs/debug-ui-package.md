# 디버그 UI 패키지

디버그 UI는 코어 패키지에서 분리된 `python-krtour-map-debug-ui` 로컬 개발 도구다. 운영 Admin UI는
TripMate가 소유하며, 이 패키지는 feature ETL/debug fixture 검증을 위한 보조 UI만 제공한다.

## 위치

```text
packages/krtour-map-debug-ui/
  pyproject.toml
  src/krtour_map_debug_ui/
    api.py
    server.py
    py.typed
```

## 실행

```bash
python -m krtour_map_debug_ui.server
```

기본 URL:

- 프론트엔드: `http://localhost:8600`
- 로컬 API: `http://localhost:8601/api/debug`

## 책임

- feature DB 스키마/table 브라우저
- 표준데이터와 notice raw item 미리보기/적재
- `EtlJobSpec`/`DagsterEtlRun` 기반 수동 ETL 실행
- fixture 저장/불러오기/replay 보조
- RustFS 설정 저장과 bucket object 목록 확인
- Kakao map 기반 좌표/marker 디버그

## 비책임

- TripMate 운영 Admin UI
- 인증/인가, 사용자 관리, 배포용 API
- provider wrapper/gateway
- pytest 파일 자동 생성

기본 테스트 경로는 외부 API를 호출하지 않는다. 라이브 호출은 API key 환경변수 또는 debug API payload의
`api_key`가 있을 때 수동으로 수행한다.
