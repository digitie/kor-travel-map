# ADR-114 — weather·transport의 현재·예보 상태는 Map이 메모리 DB(Valkey)에 들고, PinVi는 Map REST로 읽는다

- 상태: proposed (소유자 결정 2026-10-23 — 방향 확정, 구현 전. 이행 단계마다 이 문서를 갱신하고 마지막 단계가
  배포되면 accepted로 올린다)
- 날짜: 2026-10-23
- 결정자: 소유자(방향), Claude(문서)
- 관계: **ADR-105를 부분 대체**(weather가 Map에 다시 들어온다 — 단 DB 스키마가 아니라 메모리 DB로), ADR-110(odroid
  피호출자를 Map이 REST로만 쓴다 — 그대로 유지, 이 ADR은 그 위에 "PinVi는 Map을 거친다"를 더한다), ADR-106(transport
  가격 `observed_at`), ADR-109(geo 토큰 규칙), ADR-113(스냅샷 적재 spool)

## 소유자 결정(원문 요지)

- "transport는 map에서 메모리 저장, weather는 과거처럼 다시 map feature로 가져오고 map에서 메모리 저장. pinvi는
  weather/transport feature를 map에서 rest api로 불러오게."
- 과거 데이터는 Map에 남기지 않는다. transport 자체 기능(이력·통계)은 바꾸지 않는다.
- (2026-10-23 추가) "weather는 과거 날씨를 오전·오후 정도의 시간 간격으로 저장. 여행 기간 중 어제보다 추운지
  더운지, 습한지 아닌지 등 비교할 수 있게." → 같은 날 정정 "아침, 점심, 저녁 정도로 저장" — weather만 예외로
  하루 세 구간 요약을 보관한다(결정 1).
- 가격 추이는 Map DB가 아니라 transport에서 직접 읽는다.
- 저장소는 선택지 ②(메모리 DB, Valkey).
- transport가 이미 VWorld로 구한 법정동코드는 Map에서 geo를 다시 부르지 않고 그대로 쓴다(ADR-109 예외 — 아래 결정 6).

## 컨텍스트

- transport 출처 데이터를 PG feature로 적재하면, 가격이 그대로여도 주유소 11.8천 곳 전부에 새 source_record와 가격
  fact가 매일 쌓인다(추정 하루 45~50 MB, 연 17 GB). Map은 transport의 과거 데이터를 쓰지 않는다.
- weather는 ADR-105로 Map에서 빠졌고, PinVi가 odroid weather를 직접 부른다. 이제 PinVi의 날씨·교통 진입점을 Map
  하나로 모은다.
- odroid 실측(2026-10-22): 현재·예보만 세면 weather 약 188만 값(단기예보 약 179만, 초단기·중기 약 6만, 최신 관측·실황
  약 3.2만), transport 약 9만 건(교통량 구간 8,319, 주유소 11,838 / 최신 유가 59,190, 돌발 370, 주차 44, 참조 약
  5천).
- n150 실측(2026-10-22): Intel N150 4코어, 메모리 15.3 GB 중 여유 약 9.5 GB, 디스크 105 GB 남음. Map API는 uvicorn
  1 프로세스이고 적재는 Dagster run 프로세스에서 한다 — **쓰는 프로세스와 읽는 프로세스가 다르다.** 그래서 API 프로세스
  내부 메모리(dict·numpy)는 안 되고, 두 프로세스가 같이 보는 저장소가 필요하다.

## 결정

### 1. 범위

- weather: 현재 관측·실황(최신 1건)과 예보(초단기·단기·중기·외부 provider 예보, **지금 이후 시각만**).
- transport: 주유소·휴게소(위치·최신 유가), 공항, 고속도로 돌발(활성 집합), 고속도로 교통량(구간별 최신), 주차장(최신),
  역·버스터미널·항구 참조.
- 과거 시점 값은 저장하지 않는다. 예보는 시각이 지나면 지운다.
- **예외 — weather 하루 세 구간 요약.** 지점마다 아침(05~11시)·점심(11~17시)·저녁(17~23시) 구간 단위로 기온(최저·최고·평균), 습도(평균),
  강수(합계·유무), 하늘상태·풍속(대표값) 요약을 **최근 14일** 보관한다. 여행 중 "어제보다 춥다/덥다/습하다" 비교용이다.
  요약은 weather가 계산해 내보내고(관측 기준), Map은 받아서 보관만 한다. 14일이 지난 요약은 지운다. 규모는 약
  1,450곳 × 3 × 14일 ≈ 6만 항목으로 메모리 수 MB 수준이다. 보관 기간은 소유자가 바꿀 수 있는 설정값으로 둔다.

### 2. 저장소 — Valkey 단일 인스턴스

- BSD 라이선스인 Valkey(Redis 호환)를 n150에 Manager 관리 컨테이너로 하나 둔다. 외부 포트는 열지 않고 Map API·Map
  Dagster만 접근한다.
- `maxmemory` 1 GB, `maxmemory-policy noeviction`(조용히 지우지 않고 쓰기를 실패시킨다). 예상 사용량은 0.2~0.5 GB.
- 지속성: RDB 스냅샷과 AOF(`everysec`). 재시작하면 디스크에서 복원한다. 백업 대상은 아니다 — 원천(weather·transport)에서
  다시 받을 수 있다.
- 키는 값마다가 아니라 묶음 단위로 둔다(예: 지점×provider 하나에 예보 배열 하나, 주유소 하나에 위치+최신 유가). 근처
  검색은 Valkey GEO 인덱스로 한다. 세부 키 설계는 구현 PR에서 정하고 이 문서에 적는다.

### 3. 쓰기 — Map Dagster 적재 job

- weather·transport의 service API에서 받아 Valkey에 **세대 단위로 원자 교체**한다(새 세대 키를 다 쓴 뒤 포인터를 바꾼다).
  도중에 실패하면 이전 세대가 그대로 보인다.
- 원천이 빈 목록이나 비정상적으로 작은 집합을 주면 교체하지 않는다(2026-10-23 KREX 빈 응답으로 돌발 106건이 한 번에
  닫힌 사례).
- 각 세대에 원천의 수집 시각·Map 반영 시각을 함께 둔다(신선도).

### 4. 읽기 — Map REST

- Map API가 Valkey에서 읽어 weather·transport feature를 REST로 제공한다. 식별자는 기존 `make_feature_id` 규칙을 그대로
  써서 안정적으로 유지한다.
- 가격 추이(이력)는 Map이 저장하지 않고, 요청 시 transport에서 직접 읽어 전달한다. transport가 응답하지 않으면 현재가는
  그대로 주고 추이만 "없음"으로 준다.
- Valkey가 응답하지 않으면 해당 엔드포인트만 503이고 나머지 Map 기능에는 영향이 없다.

### 5. PinVi

- PinVi는 weather·transport 데이터를 Map REST로만 읽는다. odroid weather를 직접 부르던 경로는 이행이 끝나면 지운다.
- Map admin OpenAPI가 바뀌면 PinVi 재vendor가 필요하다.

### 6. transport의 VWorld 법정동코드 사용 (ADR-109 예외)

- transport export에 실린 VWorld 기반 법정동코드·주소를 Map이 그대로 쓰고, 이 데이터에 대해 geo를 다시 부르지 않는다.
  ADR-109의 "geo 데이터 토큰이 같을 때만 payload 행정코드를 믿는다"는 규칙의 예외다.
- 적용 전에 VWorld 코드와 geo 코드의 일치율과 feature_id가 바뀌는 건수를 재서 이 문서에 적는다.

### 7. 기존 PG의 transport feature

- 지금 PG에 있는 transport 출처 feature(주유소·휴게소·유가·돌발·공항 dataset)는 Valkey 경로가 배포되면 퇴역한다.
  퇴역 방법과 시점은 이행 PR에서 정한다. 그 전까지는 현재 적재를 유지한다.

## 결과 — 잃는 것

- Map에서 transport의 과거 시점 조회는 할 수 없다(가격 추이만 transport를 통해 제공한다). weather는 하루 세 구간(아침·점심·저녁) 요약
  14일만 있고 그보다 세밀하거나 오래된 과거는 없다.
- Map 장애가 PinVi의 날씨·교통 표시까지 멈춘다(지금 같은 n150에 있어 위험 증가는 작다).
- 운영할 구성요소가 하나(Valkey) 는다.

## 기각한 대안

- **API 프로세스 내부 메모리**: 적재 프로세스와 읽기 프로세스가 달라 공유가 안 되고, 재시작 때마다 예보를 39~90분 다시
  모아야 한다.
- **PG 최신 상태 표**: 단순하지만 소유자가 메모리 DB를 택했다.
- **DuckDB·SQLite 메모리 모드**: 프로세스별이라 내부 메모리와 같은 문제.
- **transport 출처 데이터를 PG feature로 두고 최신만 남기기(정리 방식)**: 2026-10-23 착수했다가 이 결정으로 중단했다
  (브랜치 `feat/transport-latest-only`, 참고용). 그 설계 리뷰에서 나온 두 함정 — seal 직전이 아닌 곳에서 정리하면 seal
  대조가 깨진다, runtime 역할은 증거 표를 읽지 못한다 — 은 이 ADR의 구현에서도 피할 것.

## 이행 순서

1. weather·transport 저장소에 Map용 API 추가(별도 작업, codex)
2. Manager: Valkey 서비스 추가(n150)
3. Map: Valkey 적재 job·REST·가격 추이 프록시
4. PinVi: Map REST로 전환, odroid weather 직접 호출 제거
5. Map: 기존 PG transport feature 퇴역

## 열린 결정

- Valkey 키 설계와 GEO 인덱스 범위
- weather에서 Map이 들고 있을 provider·항목의 범위
- 기존 PG transport feature 퇴역 시점과 방법
