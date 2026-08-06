# ADR-084: kind별 typed subtype 분해와 배타 arc

- 상태: accepted
- 날짜: 2026-08-06
- 결정자: human, AI agent

## 컨텍스트

`feature.features`는 7개 kind(place/event/notice/price/weather/route/area)를 한
테이블에 담는 36컬럼 mega-row다. kind별 필드는 `detail` JSONB 안에 있고
(ADR-018이 자유 dict를 금지해 DTO 계층에서 kind↔detail 모델 일치를 강제하지만),
**DB는 그 계약을 전혀 모른다**. 실측으로 드러난 구멍 3가지:

1. **kind가 바뀔 수 있다.** provider upsert의 `kind = EXCLUDED.kind`가
   provider-origin 행의 kind를 조용히 교체할 수 있고, DB에는 이를 막는 제약이
   없다(`ck_features_kind`는 값 집합만 검사).
2. **detail shape이 검증되지 않는다.** admin update 경로의
   `detail = CAST(:detail AS jsonb)`는 kind와 무관한 임의 JSONB를 저장한다 —
   DTO validator를 거치지 않는 경로다.
3. **시간·geometry 불변식이 술어로 흩어져 있다.** notice의 유효기간은
   `detail->>'valid_end_time'` 문자열 파싱(+비-ISO 값 방어용
   `pg_input_is_valid` cast)으로 매 쿼리 재해석되고, route/area의 geometry
   필수 여부는 `kind='area' AND geom IS NULL` 같은 사후 보정 UPDATE로 다뤄진다.

prod 분포(2026-08-05 실측): place 729,972 · event 1,246 · weather 305 ·
notice 145 · price 97 · **route·area 0행**. `detail` 키는 kind별로 완전히
분리돼 있고, `parent_feature_id`·`sibling_group_id`·`geom`은 **사용 0행**이며,
`feature_versions` 731,766행에 **kind 전이 이력 0건**이다.

## 결정

1. **kind별 typed subtype 테이블**을 만든다 —
   `feature_places`/`feature_events`/`feature_notices`/`feature_routes`/
   `feature_areas`. price/weather는 **만들지 않는다**(detail이 비어 있고 값
   정본은 `feature_price_values`/`feature_weather_values`가 이미 소유 — 빈
   테이블은 단일 정본 원칙 위반).
2. **배타 arc를 선언적으로 구현한다**: core에 `UNIQUE (feature_id, kind)`를
   두고, 각 subtype이 `kind` 상수 CHECK + `(feature_id, kind)` 복합 FK로
   core를 참조한다. 여기서 두 성질이 **구조적으로** 따라 나온다 —
   ① 한 feature는 최대 한 subtype에만 존재한다(core kind가 단일 값이므로)
   ② subtype 행이 있는 동안 **core kind 변경이 FK 위반으로 막힌다**.
   ②가 T-VN-35B "혼합 kind row 거부"의 정확한 구현이며, 위 컨텍스트 1의
   구멍을 코드 규율이 아니라 DB 계약으로 닫는다.
3. **identity 사본 일치**는 `(feature_id, feature_uuid)` 복합 FK로 0083
   `feature_aliases`와 같은 규칙을 쓴다. 둘 다 `ON DELETE CASCADE`.
4. **subtype이 단일 정본이다 — core `detail` JSONB를 제거한다.** shadow
   병행(이중 쓰기 + drift 관측)은 호환성을 위해 복잡도를 사는 거래인데, 그
   복잡도가 정확히 이 ADR이 없애려던 문제(값이 두 곳에 있고 DB가 계약을
   모른다)를 재생산한다. 응답이 요구하는 `detail`은 **뷰
   `feature.features_detailed`가 subtype에서 조립**한다 — 조립 규칙이 한
   곳에만 존재하고, writer는 subtype에만 쓰며, drift라는 개념 자체가
   사라진다. `geom`도 같은 이유로 core에서 제거하고 뷰가 제공한다.
   read 경로는 `FROM feature.features`를 이 뷰로 바꾸면 종전과 같은 모양을
   얻는다.

   **무손실 실증**(prod 복원본 731,765행): 조립된 `detail`이 원본과
   place 729,972 · event 1,246 · price 97 · weather 305 = **731,620행 md5
   바이트 동일**(kind별 전수 집계 해시). notice 145행도
   `valid_start_time` **145/145 바이트 동일**이고, 아래 정규화가 걸린
   `valid_end_time` 98행만 표기가 바뀐다. 이 대조가 실제로 결함 3건을
   잡았다 — `jsonb_strip_nulls`가 중첩 payload의 정당한 null을 지우던 것,
   `EventDetail.sigungu_code` 컬럼 누락, 그리고 아래 세션 의존성.
   조립 규칙은 "원본 바이트 동등"을 회귀 테스트로 고정한다.

   **세션 TimeZone 의존성 제거**: `to_jsonb(timestamptz)`의 문자열은 세션
   `TimeZone` GUC에 의존한다 — 실측으로 같은 notice 행이 `Asia/Seoul`
   세션에서 `...T17:35:24+09:00`, `UTC` 세션에서 `...T08:35:24+00:00`,
   `America/New_York`에서 `...T04:35:24-04:00`으로 나왔다. 서버 설정이 다른
   인스턴스가 같은 공지에 다른 문자열을 돌려주는 셈이다. 뷰가 KST 고정
   렌더(`to_char … AT TIME ZONE 'Asia/Seoul'`, 마이크로초 0이면 생략)를
   쓰게 해 세션 비의존으로 만들고, SKILL.md 규칙 17(모든 datetime은 KST
   aware)과도 일치시킨다.

   **의도적 정규화 1건**: notice의 `valid_end_time`은 종전에
   `"2026-08-05 10:00:10.823154+00"`(Postgres 스타일 — DB lifecycle CTE가
   쓴 값)과 `"...+09:00"`(KST ISO — Python writer가 쓴 값)가 **혼재**했다.
   실측 분포: `valid_start_time` 145/145 KST ISO, `valid_end_time` 98/98
   Postgres 스타일(나머지 47은 NULL). 같은 필드가 writer에 따라 다른 표기를
   갖던 결함이며, typed `timestamptz` 승격 + 위 KST 고정 렌더로 한 표기로
   통일된다(같은 순간, 표기만 정규화).
5. **geometry 정본은 route/area subtype으로 이동**하고 core `geom`을 제거한다.
   subtype에서 타입이 정확해진다(route=`MULTILINESTRING`, area=`MULTIPOLYGON`,
   둘 다 NOT NULL) — "geometry가 필수인 kind"와 "없어야 하는 kind"가 술어가
   아니라 테이블 구조로 갈린다. 조회는 `features_detailed` 뷰가 제공하는
   `geom` 컬럼을 쓰고, bbox 후보 술어처럼 **플랜이 중요한 hot path**만
   subtype을 직접 UNION ALL한다(뷰 컬럼을 술어에 쓰면 Hash Left Join 2단으로
   퇴화함을 EXPLAIN으로 실측 — 술어는 subtype GiST를 타야 한다).
   prod route/area가 0행이라 이관 비용과 회귀 위험이 모두 0이다.
6. **point subtype은 만들지 않는다** — `coord` 3컬럼은 core에 남긴다.
   coord는 4개 kind가 공유해 kind 상수 CHECK를 걸 수 없고(배타 arc 파괴),
   place의 96.6%·event의 82%가 non-null이라 거의 모든 read가 조인을 강제당하며,
   `idx_features_coord_gist` 기반 bbox/nearby 술어가 조인 너머로 밀려 성능
   위험이 커진다. T-VN-35A의 "point subtype 분리"는 이 근거로 "core 유지 +
   geometry 계약 강화"로 재해석한다.
7. **`parent_feature_id`·`sibling_group_id`는 core 유지** — prod 사용 0행이고,
   place도 장래 부모를 가질 수 있어 route/area 전용으로 내릴 근거가 없다.
   T-VN-35C의 "parent/sibling 관계" 요구는 이 판단으로 종결한다.
8. **kind별 category CHECK 승격은 하지 않는다** — 실측상 category prefix가
   kind별로 겹친다(place `01–06`, event `01`, price `06`, weather `06·99`,
   notice `99`). core CHECK를 유지한다.

## 근거

- 배타 arc는 PostgreSQL의 표준 typed-subtype 패턴이고, "kind 불변"이라는
  값비싼 불변식을 **부수적으로 공짜로** 얻는다. 트리거로 같은 것을 하려면
  `session_replication_role=replica` 우회 창구가 남는다(0083에서 같은 이유로
  절차적 보장을 선언적 제약으로 바꾼 선례).
- 단일 정본은 롤백 가능성을 잃지 않는다 — downgrade가 뷰와 같은 식으로 core
  컬럼을 역조립하므로 무손실 복귀가 되고, 그 등가성은 md5 전수 대조로 이미
  증명됐다. shadow가 주는 이점(reader만 되돌리기)보다 이중 쓰기·drift 관측이
  항구적으로 지우는 비용이 크다.
- 73만행 backfill이 **11.1초**로 실측돼(prod 복원본, FK 2.9s·인덱스 0.3s 별도)
  api-entrypoint healthcheck 창(220s)에 여유가 크다 — 단계 분할이나 수동
  선실행 같은 복잡도를 살 이유가 없다.

## 결과

- alembic `0084`(배타 arc UNIQUE + place subtype + backfill) →
  `0085`(event·notice subtype + 시간/severity CHECK 승격) → `0086`(route·area
  subtype + **core `detail`·`geom` DROP** + `features_detailed` 조립 뷰 +
  `public_features` 재정의). 세 revision 모두 단일 트랜잭션이다.
  downgrade는 뷰와 같은 식으로 core 컬럼을 **역조립**해 무손실 복귀한다.
- notice read 필터의 `detail->>'valid_end_time'` 파싱과 `pg_input_is_valid`
  방어 cast가 typed `timestamptz` 비교로 대체된다 — T-VN-35D의 최대 실익.
- merge 경로에 **master/loser kind 동일성 검사**를 신설한다(현재 부재 —
  cross-kind 병합이 repo 계층에서 가능했다). subtype 도입 후에는 무결성을
  직접 깨므로 fail-close가 필수다.
- 응답 계약은 무변경이다 — 35D는 내부 조회 축 전환이며 openapi 3종 스냅샷의
  바이트 동일이 CI에서 자동 판정한다.
- 배포는 migration 동반이므로 NEW-5 규약을 따른다: api 먼저, **dagster/daemon
  이미지 재빌드 의무**(구세대 러닝 컨테이너는 다음 재시작에서 stale 판정).
  **선행 조건**: 배포 orchestrator의 `KOR_TRAVEL_MAP_MIGRATION_EXPECTED_HEAD`를
  `0086_route_area_subtypes`로 올려야 한다. 이 값은 저장소 compose가 아니라
  orchestrator `.env`가 갖고(`docs/runbooks/docker-app.md`), api-entrypoint는
  이미지 head와 다르면 **DB를 건드리기 전에** 기동을 거부한다 — 안 올리면 api가
  exit 1이고 `depends_on: api service_healthy`인 dagster/daemon도 뜨지 않는다.
- **이관 불가 행은 조용히 건너뛰지 않고 fail-close한다.** 0084~0086은 각각
  선점검을 돌려 위반 행의 `feature_id`와 함께 멈춘다 — 필수 detail 키 결측,
  geometry 없는 route/area, route/area 아닌 kind의 geometry, subtype geometry
  타입으로 cast 불가한 값, `starts_on > ends_on`. 근거: 건너뛴 행은 곧 오는
  `DROP COLUMN detail`로 **복구 불가능하게** 사라진다(downgrade도 subtype에서
  역조립하므로 되살릴 수 없다). 실패는 되돌릴 수 있고 소실은 되돌릴 수 없으며,
  NOT NULL이 대신 내는 진단은 어느 행인지 말해주지 않는다.
- **죽은 인덱스 2종은 이관하지 않는다.** `idx_features_yt_channel_id`/
  `_playlist_id`(ADR-061)는 식이 `detail #>> '{kor_travel_concierge,…}'`인데 그
  경로에 값이 있는 행이 prod에 **0건**이다(실제 위치는 `detail.payload.…`,
  1,481행). 경로를 고쳐도 쓰이지 않는다 — 이 값을 술어로 읽는 유일한 질의인
  curation `detail_selector`는 경로가 런타임 값이라 어떤 고정 식 인덱스도 매칭될
  수 없다. 73만 행에 쓰기 비용만 남는다.
- **geometry는 route/area 전용이자 필수**임을 `Feature` DTO에도 넣는다. 종전엔
  산문으로만 그랬고 DTO는 아무 kind에나 `geom`을 받았다 — 이제 담을 곳이 없으므로
  구성 시점에 거부한다. admin 요청 모델의 `geom` 필드는 **제거**한다(받아서
  payload에 넣기까지 했지만 적용 단계에서 쓰이지 않던 필드다).
- **detail 계약 판정은 write 경계 한 곳(`feature_subtype.subtype_params`)이
  갖는다.** kind DTO로 검증·정규화하므로 필수 필드 기본값도 거기서 채워진다.
  HTTP 경계는 접수 시점 422를 위해 같은 판정을 미리 한 번 더 돌리되 값을 고치지
  않는다 — 종전 구현은 정규화 결과를 `object.__setattr__`로 되꽂아
  `model_dump(exclude_unset=True)`에서 통째로 빠뜨렸다(즉 한 번도 반영되지 않았다).
  계약 위반은 `SubtypeDetailError` → **422**다; 500으로 새면 이미 접수된 change
  request가 승인 시점마다 터져 영구히 적용 불가가 된다.
