# T-230 큐레이션 CSV·다중 관측 구현 계획

## 목표

한 물리 장소에 연결된 provider 현재 관측과 여러 큐레이션 회차를 REST, admin 지도,
목록 상세 패널, Feature 상세에서 빠짐없이 제공한다. 공식 큐레이션 목록은 repo CSV와
운영 DB에 같은 import 계약으로 적재한다.

## 기준선

2026-07-13 prod 읽기 전용 실측:

- Feature 1,028,923건
- SourceRecord 1,084,392건, SourceLink 1,084,476건
- 2개 이상 source link를 가진 Feature 9,163건, 최대 39건
- 동일 좌표 Feature group 164,833개, 최대 358건
- active 큐레이션 2,924건
- 여러 큐레이션이 연결된 Feature 980건, 최대 3건

따라서 다중성은 예외가 아니라 기본 계약이다.

## 작업 순서

1. ADR-063에 따라 source entity/current record와 curation collection/item schema를
   migration한다.
2. 기존 source record/link와 curated row를 새 구조로 무손실 변환하고 merge 로직을
   함께 갱신한다.
3. Feature aggregate와 collection/group REST를 구현하고 OpenAPI/admin/user 타입을
   재생성한다.
4. 전용 CSV parser, preview, 원자적 authoritative replace, template 다운로드를 구현한다.
5. admin UI에 수동 collection/item 생성과 CSV preview/import를 추가한다.
6. 일반 Feature와 큐레이션 지도·목록·상세에 모든 관측/membership을 표시한다.
7. 공식 출처에서 seed CSV를 만들고 prod 기존 Feature에 매칭한다.
8. 전체 게이트와 n150 prod 실데이터 live UI E2E를 수행한다.
9. 별도 적대적 리뷰에서 누락·성능·원자성·보안 지적을 반영한 뒤 PR/CI/merge한다.

## 공식 seed 범위

- 한국관광 100선: 공식 문체부/한국관광공사 발표 회차별 목록
- 국가유산 방문 캠페인: 공식 방문코스와 거점 membership
- 수목원·정원 스탬프투어: 한국수목원정원관리원 공식 운영기관
- 등대 스탬프투어: 해양수산부/등대와바다 공식 시즌별 대상지

CSV는 원래 collection membership을 보존한다. 같은 거점이 여러 코스나 회차에 있으면
중복 제거하지 않고 서로 다른 collection item으로 저장한다.

## 검증 기준

- 같은 Feature의 한국관광 100선 서로 다른 회차가 동시에 반환된다.
- 같은 Feature의 MOIS/MCST 현재 관측이 동시에 반환되고 과거 version은 이력 API에만
  나타난다.
- 동일 좌표의 서로 다른 Feature는 겹친 마커 선택 목록에 모두 남는다.
- CSV 형식 오류는 commit을 막는다. 0건/복수 후보는 공식 item을 미연결 상태로
  보존한다. 삭제·연결 변경은 replace로 반영되고 동일 파일 재업로드는 변경 0건으로 끝난다.
- repo CSV manifest 행 수, DB item 수, API 반환 수가 일치한다.
- list/bbox query는 aggregate 이전에 page 대상 key를 제한하며 필요한 B-tree/GiST
  인덱스를 사용한다.
- n150 live E2E는 mock이나 빈 데이터 skip 없이 실제 seed와 중복 회차 Feature를
  단언한다.

## 결과 (2026-07-13)

- Alembic `0044_source_entities`와 `0045_curation_collections`, REST/OpenAPI/admin UI,
  CSV parser/template/import, 공식 CSV 5종, 등대 category를 구현했다.
- 별도 backend/API 적대적 리뷰에서 동시 upsert, A→B→A current pointer, 실제 removal 집계,
  hidden/deleted 공개 누출, nullable PATCH, UUID·enum·CSV MIME, downgrade guard를 보강했고
  남은 HIGH/MEDIUM 지적은 0건이다.
- 로컬 게이트는 비통합 Python 1,761 passed(1 skipped), PostGIS 286 passed,
  frontend Vitest 62 passed, route-mocked Playwright 35 passed다. CI 단위 coverage는
  1,255 passed·전체 80.44%이고 `curation_repo.py`는 99.55%다.
- n150 prod는 검증된 747MB 사전 dump 뒤 Alembic 0045로 올렸다. 공개 로그인 GET/POST 200,
  Set-Cookie, 오답 401과 map 서비스 기동/health를 확인했다.
- 실제 적재는 collection 19개·membership 486개다. 기존 Feature 연결 225개, 미연결 261개,
  한국관광 두 회차 중첩 Feature 40개이며 지정 Feature의 서로 다른 provider 관측 2개와 각 이력
  API를 확인했다.
- 같은 공식 CSV를 다시 preview한 결과 5종 모두 `inserted=0`, `updated=0`, `removed=0`이었다.
  prod live Playwright 4건이 CSV 반영, 등대 category, admin 상세, 지도 marker, 테이블,
  Feature 상세, REST 다중 관측/회차를 실제 데이터로 통과했다.
