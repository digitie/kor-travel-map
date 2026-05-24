# Feature 문서 작성 가이드

이 문서는 feature/ETL 문서를 추가하거나 고칠 때 맞출 공통 구조다. TripMate 문서는 사용자,
여행계획, POI, API serving, Admin 운영만 남기고 feature/source/weather/price 계약은 이 저장소를
표준으로 둔다.

## 문서 언어 정책

이 저장소의 문서는 한국어를 기본 언어로 작성한다. 제목, 설명 문장, 표의 설명 컬럼은 한국어로
유지한다. 다만 Python 모듈명, class/function 이름, DB table/column, provider 공식 명칭,
API endpoint, HTTP header, enum 값, 환경변수, 코드 예시는 원문 식별자를 그대로 둔다.

새 문서를 추가하거나 기존 문서를 보강할 때도 같은 기준을 따른다. 영어 표현이 필요한 경우에는
공식 API 명칭이나 코드 식별자인지 먼저 확인하고, 설명 문장은 한국어로 풀어쓴다.

## 문서 색인

| 범위 | 표준 문서 |
| --- | --- |
| 공통 feature DTO/저장 계약 | `feature-model.md`, `postgres-schema.md` |
| provider 직접 사용 원칙 | `provider-contract.md` |
| 주소/좌표 보강 | `address-geocoding.md`, `kraddr-base-types.md` |
| 파일/이미지 저장 | `feature-files-rustfs.md` |
| Dagster 실행 경계 | `dagster-boundary.md` |
| fixture/debug 흐름 | `debug-fixture-workflow.md`, `debug-ui-package.md` |
| TripMate 이관 상태 | `tripmate-feature-docs-migration.md`, `tripmate-integration.md` |

## ETL 문서 공통 형식

새 ETL 문서는 아래 순서를 기본으로 쓴다.

1. `문서 정보`: provider, dataset key, feature kind, source type, 갱신 주기, 코드 entrypoint
2. `범위`: 이 라이브러리와 provider 라이브러리, TripMate가 각각 맡는 책임
3. `Provider 경계`: public client/model 직접 사용 기준과 wrapper/adapter 금지
4. `Dataset 매핑`: dataset key, source natural key, feature kind/detail table/source role
5. `주소/좌표`: `python-kraddr-base` DTO, `python-kraddr-geo` reverse geocoding, match report 기준
6. `파일`: RustFS 적재 대상과 `FeatureFileSource` 매핑
7. `DB 적재`: collect/load 함수, transaction owner, prune/delete 정책
8. `Dagster`: exported `EtlJobSpec`, schedule tag, env enable 조건
9. `검증`: unit/fixture/live test 구분, 외부 API 호출 조건
10. `후속 보강`: provider 라이브러리에서 먼저 안정화할 endpoint/model/pagination/raw payload TODO

문서마다 같은 의미를 다른 이름으로 쓰지 않는다. 예를 들어 source id는 `source_entity_id`,
feature 종류는 `Feature.kind`, provider 수집 단위는 `dataset_key`, 원천 역할은 `SourceRole`로 쓴다.

## Feature 문서 공통 형식

kind별 feature 문서는 아래 정보를 빠뜨리지 않는다.

| 항목 | 작성 기준 |
| --- | --- |
| 사용자 의미 | 지도에서 왜 feature인지, content/POI와 어떻게 다른지 |
| DTO/table | `Feature`, kind별 detail DTO/table, weather/price/file 관계 |
| ID/source | 결정적 id 구성, natural key, source role |
| 주소/좌표 | 좌표 유무, reverse geocoding, 법정동코드 확정/검토 기준 |
| 보존/삭제 | 종료/폐업/취소/갱신 시 feature status 또는 delete 기준 |
| 노출 | marker icon/color, category, 목록/지도 조회 주의점 |

## TripMate 문서 처리

TripMate에서 feature 세부 table, source role, provider alias, weather/price context를 다시 정의하지
않는다. TripMate 문서에는 다음만 남긴다.

- 이 저장소 표준 문서 링크
- TripMate가 실제 사용하는 service/resource 이름
- API response 조립, 인증/인가, 사용자 저장 snapshot 정책
- 운영 runbook과 배포/알림 절차

TripMate에 새 feature 설계를 먼저 적지 않는다. 필요한 계약은 이 저장소의 코드와 문서를 먼저
수정하고, TripMate 문서는 링크나 사용 지점만 업데이트한다.
