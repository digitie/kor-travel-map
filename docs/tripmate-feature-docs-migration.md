# TripMate feature 문서 이관

TripMate에 있던 feature 중심 문서는 이 라이브러리로 이관한다. TripMate 문서는 사용자, 여행계획, POI, API, Admin, 운영 runbook만 남기고 feature 세부 계약은 이 저장소를 표준으로 링크한다.

## 이관 대상

| TripMate 문서 | 이 라이브러리 표준 문서 |
| --- | --- |
| `docs/architecture/map-feature-schema.md` | [Feature 모델 기준](feature-model.md), [Postgres 스키마 기준](postgres-schema.md) |
| `docs/architecture/krtour-map-library.md` | [TripMate 통합 가이드](tripmate-integration.md), [아키텍처](architecture.md) |
| `docs/architecture/provider-library-direct-use.md` | [Provider 계약](provider-contract.md) |
| `docs/architecture/weather-air-quality-schema.md`의 feature weather 섹션 | [날씨 feature 정규화](weather-feature-normalization.md) |
| `docs/architecture/kraddr-base-boundary.md` | [python-kraddr-base 자료형 사용 기준](kraddr-base-types.md) |
| `docs/architecture/dagster-krtour-map-boundary.md` | [Dagster 경계](dagster-boundary.md) |
| `docs/architecture/krtour-map-db-initialization.md` | [Feature DB 초기화](feature-db-initialization.md) |
| `docs/architecture/outdoor-feature-db.md` | [산림·등산 feature ETL](outdoor-feature-etl.md) |
| TripMate feature/ETL 문서 작성 규칙 | [Feature 문서 작성 가이드](feature-docs-guide.md) |

## TripMate에 남길 내용

- 사용자, 세션, 권한, 여행계획, POI product schema
- 사용자가 저장한 일정/POI snapshot 정책
- API route, request/response, 인증/인가
- Admin 화면과 운영 runbook
- Dagster process 실행, schedule, resource 주입, 운영 알림

## TripMate에서 제거할 내용

- feature DTO 상세 재정의
- feature/source/weather/price DB table/column 중복 정의
- provider별 adapter/wrapper/gateway 생성 지침
- `map_feature_weather_values` 같은 TripMate 복제 table 설명
- fixture마다 pytest 파일을 생성한다는 설명

새 feature 계약이 필요하면 TripMate 문서에 먼저 임시 설계를 두지 않고 이 라이브러리의 코드와 문서를 먼저 수정한다.
