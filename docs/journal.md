## 2026-11-28 — 등산 코스 적재와 구간 은퇴를 한 transaction으로(완료 seal 불일치 수정)

- 증상: ADR-128(#1569) 뒤 `feature_route_krforest_mountain_trails_job`·`feature_geometry_knps_records`(knps_trails)가 구간
  은퇴가 있는 첫 run마다 child 완료에서 `provider load input changed before child completion`으로 실패(prod krforest
  57,033건·knps 609건 은퇴 run, 은퇴 0건인 재시도만 통과).
- 원인: 코스 적재 transaction 끝에서 잡은 seal 기대값(은퇴 전)을 run 결과로 넘기고, 구간 은퇴는 별도 transaction으로
  commit했다. 완료 seal은 입력 집합 해시(lifecycle·publication 포함)를 다시 계산하므로 어긋난다.
- 수정: `load_authoritative_feature_snapshot(superseded=SupersededSourceEntities(...))` — 코스 적재·코스 부재 은퇴·구간 은퇴·
  seal 캡처가 한 transaction. 은퇴 수는 `FeatureLoadResult.superseded_retired`. 은퇴 실패 시 코스도 rollback돼 중간 상태가
  없다. ADR-128 개정 절. sync 성공 기록 순서(완료 seal 전)는 다른 적재와 같은 기존 계약이라 그대로 둔다(PR 본문에 근거).
- 시험: integration(실제 asset→client→tracked finish·seal, 구간 3건 은퇴 → child done·receipt=결과 seal) — 수정 전
  assets.py로 돌리면 prod와 같은 CheckViolation으로 실패함을 확인. dagster 단위(snapshot 1회·superseded 전달·실패 시 sync 없음).

## 2026-11-28 — kor-travel-common 최신 채택(py 0.1.0.dev3·ui 0.2.8·tokens 0.1.9)

- Python 핀 f1faf56(dev2) → aefdc86(tag `py-v0.1.0.dev3`, common registry canonical ref와 같은 SHA). 추가분은
  `kortravelcommon.dagster_ops`(공용 Dagster 실행 상태·제어 계약)뿐이라 Map 코드 변경 없음.
- admin UI: common #98 catalog(73761c5)의 main pack(e131a1e, artifact SHA256 대조 일치)을 vendor하고 guard·common-ref를
  73761c5로 올렸다. 0.2.8은 수집 파이프라인 export 추가(additive), toast는 Map이 쓰지 않아 받지 않는다.

## 2026-11-28 — geo 연결 수립 즉시 거부(ConnectError)도 일시 장애로 다시 보낸다

- prod 등산로 적재(`feature_route_krforest_mountain_trails_job`)가 시도 1(96분, geo 호출 14,637건)·시도 2(3시간 8분,
  34,690건)를 각각 `ConnectError` **단 1건**으로 잃었다. 시도 3은 6시간 상한 안에 끝날 수 없어 취소했다. geo readyz는
  정상(pool 사용률 0)이었다.
- 기존 적재 재시도(`transient_attempts=3`)는 "연결 실패 = 호스트 다운 → 매 시도가 connect 상한만 기다린다"는 이유로
  `ConnectError`를 뺐다. 그러나 상한을 다 쓴 수립은 httpx에서 `ConnectTimeout`(별개 클래스)이고, `ConnectError`는 상한 안에
  실패로 끝난 수립(거부·경로 없음·DNS·TLS)이다. 이제 `ConnectError`는 **10 s·20 s** 뒤 다시 보내고(geo 재기동 하나를 넘기는
  30 s 창 — 2 s·4 s로는 재기동을 못 넘긴다), `ConnectTimeout`·`PoolTimeout`은 여전히 한 번에 끝낸다. 기본(API·admin,
  `transient_attempts=1`)은 그대로다. ADR-116 재시도 절에 개정 줄을 더했다(소유자 승인 범위 확대 — 보고).
- 원인이 미규명이다(예외 클래스명만 남았다). 그래서 다시 보낸 시도를 `GeoCallStats.retries`(`endpoint:원인`, 원인 =
  클래스명+errno 또는 상태 코드)로 세어 run 로그 요약·`geo_retries_total` metadata에 싣고, transport 실패 메시지에도
  errno를 붙였다(URL·키 없음). 재시도로 성공한 일시 장애가 더는 흔적 없이 사라지지 않는다.
- 적대 리뷰 2인(재시도 의미·httpx 계층 / 운영 부하·충분성): 결함 없음. 지적(주석 과장·ADR/settings 문구 drift·재시도
  가시성·6 s 창 부족)을 모두 반영했다.
- 시험: ConnectError 3회·ConnectTimeout/PoolTimeout 1회, 원인별 재시도 계수·errno·backoff 길이.

## 2026-11-27 — 소유자 결정 4건 기록·journal/acceptance 다음 경계 분리

- writer-drain restore(#1558 뒤 남은 결함, 2026-11-25 절): restore가 pause 때 멈춘 sensor를 Dagster 1.13 `startSensor`로
  다시 켤 뿐 sensor마다 이전 상태·cursor를 복원(코드 기본 RUNNING이면 `reset*`)하지 않는다. 소유자 결정: 지금은 고치지 않고
  백로그에만 둔다 — `T-WRITER-DRAIN-RESTORE`(tasks.md, 해제 조건은 acceptance 같은 ID).
- 공용 PG role 연결 상한 overcommit: role별 연결 상한의 합이 instance 용량을 넘는다(Dagster 공용 role 60, 비-superuser
  용량 97). 소유자 결정: 그대로 두고 관찰한다.
- `EXPORT_SOURCE_INCONSISTENT` 재시도: 현재 동작(2026-11-24 절 — 상태 job 다음 tick, 반복되면 경보)을 유지한다.
- Map `main` ruleset 필수 check(2026-11-27 설정): `pytest (Python 3.11)`·`(3.12)`·`(3.13)`·`pytest integration (PostGIS,
  pg18)`·`pytest fixture replay`. 문서만 바꾼 PR도 이 check가 통과해야 머지된다.
- journal이 224,568 B로 §8 상한 225,280 B에 닿아 2026-11-02~12의 완전한 절 59개를
  [journal-2026-11a.md](archive/journal-2026-11a.md)(43,713 B)로 원문 그대로 옮겼다. 상대 링크 5개만 `../`로 재기준화했고,
  역변환한 본문이 원래 구간 43,448 B와 바이트 일치함을 확인했다. live에는 제목 stub을 남기고 인덱스 표에 행을 더했다.
- `tasks-acceptance.md`도 225,258 B라 새 절이 들어가지 않았다. 닫힌 절 `T-VN-39-D2-FIXTURE`·`T-GR-00`을
  `scripts/archive_task_ledger_section.py --apply`로 옮겼다(체크박스 222건 다중집합 보존 검산 통과, 225,258 → 219,794 B).
  같은 도구는 `T-MAP-02`(상대 링크)·`T-FE-MOCK-FLAKE`(fence 경계)를 거절했다.
- 코드·OpenAPI·migration 변경 없음.

## 2026-11-27 — TourAPI 상세 op 점진 백필: 소개·이미지·반려동물·무장애 (ADR-126, PR 2/2)

- 원천: TourAPI `detailIntro2`(유형마다 접미사가 다른 이용시간·휴무·주차·주차요금·요금·할인·예약·문의·반려동물 한 줄),
  `detailImage2`(추가 이미지 + `cpyrhtDivCd`), `detailPetTour2`, 무장애 `KorWithService2/detailWithTour2`. 전부
  `python-visitkorea-api` 핀 `151ef90`에 있다(ADR-006 — wrapper 없음, hub `call("with", "detailWithTour2")`).
- op마다 하루 예산이 설정값이다(기본 900, env `KOR_TRAVEL_MAP_VISITKOREA_DETAIL_{INTRO,IMAGE,PET,ACCESSIBILITY}_DAILY_BUDGET`).
  받은 값은 `raw_data["tourapi_detail_ops"][op] = {modified_time, data}`(원천 키 중 쓰는 것만)로 남아 다음 run·replay가
  잇는다. 상세 없는 행의 raw_data는 이 기능 전과 같다(payload hash 불변).
- 우선순위: 새 읽기 `read_detail_priority_scores`(큐레이션 포함 +10, 검색 인지도 0~9) → 낡은 것 → 관광타입 12→14→28 →
  contentid. prod 읽기 전용(2026-11-27): TourAPI 18,894건 모두 인지도 ≥1, 큐레이션 포함 0건, 질의 1.5 s(Dagster 역할로
  읽기 가능). PinVi 여행 일정의 장소별 신호는 Map에 없다. 점수를 못 읽으면 경고 후 계속.
- 낡은 op 값은 다시 받을 때까지 보인다(그 op은 우선 다시 받는다). 한 op의 한도·인증 정지가 다른 op을 막지 않는다.
  replay·step 재시도는 받지 않는다. 기존 `detailCommon2`(overview) 경로는 건드리지 않았다(다른 에이전트가 채움률 11%
  원인 조사 중).
- 적대 리뷰 반영·조정(2026-11-27): 하루 상한을 **KST 날짜별 장부**(Dagster instance KV, 호출 전 예약 — 큐 runner·재실행·
  실패 run도 센다)로 지킨다. 무장애·반려동물은 그 서비스 `areaBasedList2` 목록에 든 contentid만 묻는다(목록 실패면 그 op만
  이번 run 쉼). current 원본은 한 번만 읽고 못 읽으면 멈춘다(fail-closed). op 첫 실패를 로그. TourAPI `overview`·대표 이미지도
  `visitor_info.description`·`images[0]`에 싣는다(평면 키는 기존 소비자용으로 유지) — 다음 run에 관광지 feature 대부분이
  한 번 갱신된다. `주차요금`은 `parking_fee`로 분리.
- overview 채움 조사(별건, PinVi #809) 요청 반영: `detailCommon2` run 예산 관광지 600→**850**·축제 300→**50**(축제는 새·수정
  하루 4~6건), 하루 상한 900 — 셋 다 env로 덮을 수 있다(`KOR_TRAVEL_MAP_VISITKOREA_DETAIL_COMMON_{DAILY,ATTRACTION,FESTIVAL}_BUDGET`,
  빈 값 = 코드 기본값). `detailCommon2`도 같은 날짜 장부를 쓴다. env는 Manager compose code-server에 배선(Manager PR).
- 축제: 공개 상세가 벗기는 `payload`의 소개·대표 이미지를 `visitor_info`로 typed 투영(읽기만, 저장 불변). 투영은
  `row_revision`을 바꾸지 않으므로 event ETag에 투영 판(`event-visitor-info-v1`)을 섞는다(배포 전 304 캐시 방지).
- 적대 리뷰 2차: 큐 runner의 직접 context(instance 없음)는 장부가 없어 상세를 받지 않는다(fail-closed). 반려동물 상세도
  목록과 같은 `KorPetTourService2`에서 받는다(활용신청·쿼터·contentid 일치). 서비스 목록은 제목순(`arrange=A`). 축제 소개는
  정리본 그대로(재정리 시 꺾쇠 소실). 휴양림 raw 새 키도 값이 있을 때만. 공개 `visitor_info` 설명에 축제 포함 → OpenAPI·
  types·계약 지문 재고정.
- 시험: unit `test_tourapi_detail_ops.py`(plan·merge·변환), dagster `test_visitkorea_detail_ops.py`(op별 필드·한도 독립·
  우선순위·replay/재시도 0·설정 예산), integration `test_place_visitor_info.py`(jsonb 왕복·current 원본 읽기·점수).

## 2026-11-27 — place 방문 안내 typed 모델 + 국가유산 설명문·박물관·휴양림 필드 + 공개 API typed (ADR-126, PR 1/2)

- 근거: 상세 콘텐츠 소스 조사(2026-11-27, 소유자 "권장안 대로" — 3·4·5순위). PinVi 상세에 이용시간·휴무·주차·요금·
  이미지·무장애·반려동물이 없었다. 국가유산 `SearchKindOpenapiDt` `content`는 Map이 이미 건마다 부르면서 버렸고, 박물관·
  휴양림 표준데이터의 관람시간·요금·소개·입장료·주요시설도 변환기가 버렸다.
- 설계: `dto.PlaceVisitorInfo`(typed, `extra="forbid"`)를 `facility_info["visitor_info"]`에 두고 `PlaceDetail` validator가
  검증·정규화한다 — DB 컬럼·protocol 함수·migration 불변. 원문 그대로(태그·공백만 정리). 이미지는 이미지마다
  `ContentLicense`(공공누리 0~4, 3·4는 `derivatives_allowed=false`), 유형 모르는 이미지는 담지 않는다.
- 국가유산: 설명문만 담는다(출처 "국가유산청, www.khs.go.kr"). 이미지 API `imageNuri`(`B/F`·`D/F`, 2026-11-27 실호출)의
  공공누리 대응을 국가유산청 문서로 확인하지 못해 이미지는 담지 않는다(fail-closed) — provider에도 typed `images()`가 없다.
- 박물관: 평일·공휴일 관람시간(`HH:MM` 한 줄 원문 — 요일 구간 `business_hours`로 바꾸지 않는다)·휴관·관람료(성인·청소년·
  어린이 숫자)·소개·교통·시설. 휴양림: 입장료·주요시설·수용인원·숙박 여부. 원천 필드는 `raw_data`에 이름 그대로(replay).
- 공개 API: `GET /v1/features/{id}`에 `visitor_info: PlaceVisitorInfo | null`, 같은 값은 `detail.facility_info`에서 뺀다.
  OpenAPI 재생성 + admin frontend·user-client types 재생성. TourAPI 상세 op 백필은 PR 2/2.
- 시험: `tests/unit/test_place_visitor_info.py`(DTO·국가유산), 박물관·휴양림 변환, API `test_feature_visitor_info.py`.
- 적대 리뷰 2인(데이터·라이선스 / API 계약) 1차 반영: 박물관 raw의 새 키는 값이 있을 때만(옛 원본 replay hash 유지 —
  아니면 다음 월간 fetch까지 `ReplayPayloadDrift`), "없음"은 자리표시로 지우지 않음(연중무휴·주차 없음), 국가유산 설명문은
  provider 정리본 그대로(재정리하면 `<삼국유사>` 꺾쇠 소실), 금액 칸 전부 0 + 요금 원문이면 숫자 버림, `00:00~00:00`·`24:xx`
  시각 거름, `ContentLicense.kogl_type` 필수(이미지 전용), `pet_allowed`→`pet_note`, `parking_fee` 분리, 관리자 ETL fixture
  dataclass에 새 필드, user-client alias export, openapi-diff baseline·T-VN-40 pending receipt 지문 재고정(pending 유지),
  공통 정리 함수는 `core/visitor_text.py`로.

## 2026-11-27 — 등산로 구간을 코스로 묶는다(ADR-128)

- 근거(prod 읽기 전용): route 57,690건 = 산림청 등산로 57,047 + KNPS 617 + 둘레길 26, 거리·소요시간·난이도·시종점 이름 0%.
  한 행은 구간이다(산림청 중앙 233 m). 그런데 원천 raw에는 산림청 `PMNTN_LT`(km, geometry와 비율 1.000)·`PMNTN_UPPL`/`GODN`
  (분)·`PMNTN_DFFL`(쉬움/중간/어려움)·`MNTN_CODE`·`PMNTN_NM`, KNPS `코스ID`·`탐방코스(한글)`·`시작점_ID`/`종점_ID`·거리·
  가는/오는시간·난이도(척도 문서 없음)가 있었다 — 변환이 버렸다.
- 구현: `core.route_course`(10 m snap → union/linemerge → 50 m 미만 지선 제거 → path/loop/network, 본선 우선·정점 순서 =
  진행 방향), `providers._route_course`(코스 bundle, `coord`=출발점), `mountain_trail_courses_to_bundles`(산·노선명 연결 성분,
  출발 = 산 구간망 중심에서 가장 먼 말단), `knps_trail_courses_to_bundles`(공원사무소·코스명, 출발 = 노드 그래프 시작),
  Dagster 두 자산이 코스를 싣고 구간을 은퇴. 공개 목록·상세에 `route` 요약(`length_m`·`duration_minutes`·`duration_basis`·
  `difficulty`·`shape`·`start`/`end`). 구간 route 변환도 원천 거리·상행·난이도를 싣는다.
- 함께 고친 결함: field ledger가 `Decimal`을 JSON 문자열로 써 numeric field(`route.total_distance_meters`·
  `area.area_square_meters`)가 처음 non-null이 되는 순간 `base JSON value does not match registry type`으로 적재가 죽었다.
- 발견: KNPS 8구간 geometry가 원천 거리의 수십~수백 배(공원 전체를 훑는 단일 선) → 가드로 코스 선에서 뺐다
  (`T-KNPS-TRAIL-GEOM`). 둘레길 DBF는 원천에서 이중 인코딩·바이트 유실이라 이름 복구 불가.
- 실측(prod 원천 전량 → provider 함수): 산림청 14,252코스(p50 1.0 km, ≥1 km 50%), KNPS 186코스(p50 3.3 km). migration 없음,
  OpenAPI(user·admin) 추가만.
- 다음: `T-HIKE-COURSE`(운영 재적재), PinVi 일정 추가 PR.

## 2026-11-27 — 공개 containing-areas API(이 장소는 어느 국립공원·보호지역 안인가)

- `GET /v1/features/{feature_id}/containing-areas`·`GET /v1/features/containing-areas?lon&lat` — `contained-features`의
  역방향. `feature.feature_areas` 부분 GiST(`public_ready`) + `&&` + `ST_Covers`(4326, `ST_Transform` 없음), 작은 면 먼저,
  `area_kind` 반복 필터, `page_size` 1~50, area 자신 제외, 공개 membership은 `public_features` 조인. 공개 상세에 `area_kind`·
  `route_type` 사본 필드.
- OpenAPI user·full 재생성(service 불변), admin·user-client 타입 재생성, openapi-diff baseline·consumer-rollout pending receipt 갱신.
- 시험: 통합(중첩 정렬·종류 필터·자기 제외·경계 점·바깥 점·은퇴 면 제외·EXPLAIN GiST 사용/변환 없음), 라우터(대표점 전달·
  좌표 없음 422·범위/종류/상한 422·상세 typed 필드). 데이터 정확성은 앞 PR(국립공원 경계 재원천화)의 재적재가 전제다 —
  재적재 전 prod에선 버퍼 면(공식의 2~4.8배)을 그대로 답한다.

## 2026-11-27 — 국립공원 경계 재원천화(3 km 버퍼 → 한국보호지역 국립공원 행)·면 수리

- 근거: prod 읽기 전용 감사 — `national_park` 21건이 공식 면적의 2~4.8배(북한산 240.9 km² vs 76.9, 경주 659.6 vs 136.6·한
  덩어리, 지리산 978.3 vs 483.0), 23곳 중 한려해상·태안해안 없음, `protected_area` 401건 중 14건 `Ring Self-intersection`.
- 원인(원천): 15017313 ZIP 레이어가 `공원경계버퍼/BSI_NPK_BBNDR`이고 `.shp.xml` 처리 이력이 `Buffer … "3 Kilometers" FULL
  ROUND`다. 파싱(투영·ring·hole)은 정확했다 — 원본 면적이 저장 면적과 같다. 누락 2곳은 centroid가 바다라 역지오가 법정동을
  못 줘 strict 검증에서 빠졌다(prod geo 실측).
- 수정: knps-api PR#22(핀 `59fb5b0`) — 한국보호지역 SHP `.cpg` UTF-8, source_id `WDPA_PID`, 이름 `ORIG_NAME`, 공원경계가 버퍼임을
  카탈로그에 명시. Map — `knps_park_boundaries`에 `unloaded_reason`(돌리면 빈 snapshot으로 버퍼 면 은퇴), 국립공원은
  `knps_protected_areas`의 `DESIG_ENG='National Park'` 22행 + 2023-12-31 승격 팔공산(2016 스냅샷의 도립공원 행,
  `KNPS_NATIONAL_PARK_PROMOTIONS`)을 `national_park`/`01020101`로 싣는다. 국립공원 행만 역지오 후보점(centroid →
  representative_point → part별 → 바깥 ring 꼭짓점, `core.geometry.area_anchor_points`)을 차례로 묻고 첫 법정동 점을 대표점으로
  쓴다(일반 보호지역은 centroid 1회 — 해상 보호구역이 빈 답 가드를 넘지 않게). 면은 `normalize_geometry`에서 `make_valid` 후
  면 조각만 남긴다(`repair_area_geometry`, valid 입력은 그대로). KNPS area dataset 적재는 snapshot 부재 은퇴를 켠다.
- 검증: 실제 포털 파일 두 개 → 일회용 PostGIS(alembic head) 재적재 — 국립공원 23곳 공식 면적 대비 0.948~1.036(오대산 최소·한려해상
  최대), 경주 9 part, 버퍼 23건 retired, active 면 invalid 0, 팔공산은 보호지역에서 빠짐. prod geo로 해상 3곳 후보점 실측(태안 첫
  ring 꼭짓점, 다도해 ring 꼭짓점, 한려해상 representative_point). 보호지역 source_id가 행 hash → WDPA id로 바뀌므로 재적재 시
  옛 보호지역 feature는 snapshot 부재로 은퇴하고 새 id로 다시 선다(설계 우선 — 서비스 전).
- 적대 리뷰 2인 반영: `make_valid(method="structure")`(기본 linework는 겹친 곳을 구멍으로 만든다 — shapely 하한 2.1),
  국립공원 후보점 순회를 변환 밖 `knps_national_park_anchors`로(변환 안에서 돌면 ADR-116 재사용 pass 0이 행 좌표 밖을 물어
  dataset 재사용이 꺼졌다), 싣는 area dataset의 bundle 0건은 은퇴 전 실패, drop 행은 snapshot 부재 은퇴에서 제외
  (`retained_source_entity_ids` — etl 공통, drop→은퇴→재활성 flap 방지). 통합 시험: 버퍼 적재→보호지역→버퍼 빈 snapshot 은퇴→0건 거부.
  drop 행 제외는 의도적으로 etl 공통이다 — TourAPI 관광지·축제 등 drop+retire dataset도 이제 drop 행을 은퇴시키지 않는다(계속
  drop되는 행은 옛 버전이 active로 남는다 — 그 수는 각 asset의 미해석 상한이 묶는다). 잔여: 0건 가드만 있고 직전 active 대비
  감소율 하한은 없다(1건만 남는 붕괴는 못 막음), 국립공원 후보점 사전 조회는 재사용 없이 run마다 23곳을 live로 묻는다(소량).
- 재적재 순서(배포 뒤 소유자): `knps_protected_areas` 먼저(admin "지금 실행" 또는 provider_dataset 큐 요청) → 확인 게이트
  (active national_park 23·invalid 0·drop 목록에 국립공원 없음) → `knps_park_boundaries`는 **provider_dataset 큐 요청**으로
  (schedule이 없어졌고 tag 없는 launchpad run은 commit 뒤 membership 기록에서 red가 된다). OpenAPI·migration 없음.

## 2026-11-27 — 휴게소 먹거리(한국도로공사 메뉴) — 휴게소·고속도로 주유소 상세 (ADR-127)

- 소유자 승인 계획(조사 보고서 2순위, LLM 없음): transport가 KREX 0615(휴게소 코드·상하행)·0502(메뉴)를 하루 한 번 수집해
  `rest-area-food` export로 낸다(transport 2026-11-27, python-krex-api #21). Map은 그것을 받아
  - 휴게소 ↔ KREX 표준 코드를 정규화 이름으로 잇는다(`providers.rest_area_food`). **운영 215곳 모두 연결**(정확 213 + 0615·0502
    코드가 갈린 함양 상하행 2곳 합침), 메뉴가 붙는 곳 213곳. 좌표는 쓰지 않는다(0124 좌표가 290 km 어긋난 행).
  - 메뉴를 결정적으로 요약해(대표·프리미엄·추천, 가격 최저·중앙·최고, 여름·겨울 메뉴, 기준일) 새 Valkey 데이터셋
    `transport.rest_area_food`에 싣고(`transport_state_rest_area_food`, 매일 05:07, 코드 기본 STOPPED),
    `/v1/service/transport/rest-areas/{id}`(`food`)·`/fuel-stations/{id}`(`rest_area_food`)가 준다.
  - 오피넷 주유소 ↔ 휴게소 짝은 적재 job이 주유소 export까지 받아 전체를 한 번에 정하고 일대일로 다듬는다(lookup 키).
    **운영 242곳 중 자동 204곳(84.3%)**, 검토 38곳은 `GET /v1/ops/rest-area-food/review`(operator)에만. 적대 리뷰가 찾은 1차
    규칙의 오짝 6건((상)/(하) 기준 차이 2, 휴게소 지명이 든 근처 일반 주유소 4)은 모두 검토로 내려갔다.
  - PG 휴게소 place는 `facility_info.ex_link`(코드·노선·상하행·근거)와 비어 있던 `highway_name`·`direction`을 채운다.
    PG 적재는 먹거리 export가 없으면 실패한다(출렁임 방지).
- `RestAreaState` 모양은 그대로(키 스키마 버전 유지). OpenAPI(admin·service) 갱신, migration 없음.

## 2026-11-27 — 대표 원천을 쓰기 시점에 유지(ADR-125, alembic 459, T-READ-13)

- 근거(prod 읽기 전용, jit off, #1561 코드를 리터럴로 렌더링): `sort=provider` 첫 페이지 2.7 s(냉 6.5 s, hash 127 MB·정렬
  50 MB), `+provider_dataset_id`(MOIS) 2.0~2.4 s, `sort=name` + 드문 dataset(knps_shelters 22건) **19~44 s**(`lower(name)`
  색인을 걸으며 행마다 대표 원천 LATERAL), 흔한 dataset 9 ms. primary가 둘 이상인 Feature 817건(전부 서로 다른 provider)의
  대표가 "가장 최근 관측" 규칙이라 적재 주기에 따라 바뀌었다(729건이 가장 자주 적재되는 TourAPI).
- 결정(ADR-125): 대표 = 가장 먼저 붙은 primary 연결(`created_at`, `source_entity_key COLLATE "C"`). 규칙 view
  `feature.feature_primary_source_rule` 하나, 사본 `feature.feature_primary_sources`(Feature당 한 행)를 `source_links` 문장
  trigger 셋(transition table, 규칙 열이 바뀐 primary만)·`features` 행 trigger·TRUNCATE trigger가 같은 transaction에서
  맞춘다(`ENABLE ALWAYS`·`SECURITY DEFINER`). 재계산은 사본 행을 `feature_id` 순으로 잠근 뒤 새 문장에서 계산 — 같은 Feature를
  두 transaction이 바꿔도 write skew 없음. 열이 아니라 표인 이유: `row_revision` ETag·`features` 행 잠금·HOT. prod에서
  730건의 대표 provider가 바뀐다(primary 하나인 99.8%는 그대로).
- 읽기: 관리자 목록(키 단계는 사본 색인 keyset·dataset 색인, 꾸밈은 정본 `provider_datasets`), nearby(page 표시·`providers`),
  dedup 검토 둘. 공용 조각 `infra/primary_source.py`. 정합성 검사 F10(ERROR) 추가. OpenAPI 바이트 변화 없음.
- migration 459(한 transaction): 표·view·함수·색인 → trigger 없이 5만 행 조각 backfill(쓰기 안 막음) → trigger(`SHARE ROW
  EXCLUSIVE`, `lock_timeout` 5 s) → 같은 조각으로 따라잡기 → ANALYZE. prod 조각 하나의 규칙 계산 0.29 s(전체를 한 번에 하면
  worker마다 정렬 83 MB 디스크). 쓰기 대기 창 추정 3~6 s. 배포는 Manager one-shot, writer drain 선행.
- 적대 리뷰 2인: ① RR·SERIALIZABLE writer가 lock-only xmax를 지나 옛 snapshot으로 덮는 구멍(재현) → refresh가
  언제나 새 행 버전을 쓴다(+회귀 시험). ② 행 단위 upsert 비용 +2.5 ms/행 → refresh 보통 경로 두 문장으로 +1.1 ms/행.
  ③ 따라잡기가 규칙을 두 번 계산 → 한 번. ④ trigger 생성 잠금 순서가 writer와 반대(교착) → `LOCK TABLE features,
  source_links` 먼저. ⑤ 공개 view `source_raw_data`의 셋째 규칙 사본 → 유지 표로. ANALYZE·receipt는 창 밖으로,
  fillfactor 90.
- 합성 prod 규모(44.2만, 실제 dataset 분포, 로컬 PG18, 통합 시험과 같은 상자): provider asc 7.6 s → 3.9 ms, desc 2.5 ms, 22만
  번째 cursor 5.6 s → 3.0 ms, 드문 dataset + 이름 28.8 s → 2.1 ms, provider + MOIS 3.6 s → 298 ms, name·kind 회귀 없음. F10
  3.2 s·0건. 쓰기(운영 모양 — 연결 하나에 한 문장 upsert): 새 primary +1.1 ms/행, 같은 값 재적재 차이 없음.
- 시험: `tests/integration/test_feature_primary_sources_sync.py`(쓰기 종류별 사본=규칙, data-modifying CTE, replica 역할·런타임
  login, view 술어 push-down, 따라잡기 SQL 복구, 두 transaction 경쟁 2순서), `test_admin_feature_list_sort.py` 규칙·계획 갱신,
  unit SQL 모양·F10 순서. head 오라클·migration graph·runtime 권한 표 갱신.

## 2026-11-27 — 관리자 feature 목록 정렬 지연(kind·provider·issue_count 12~39 s)

- 근거: 2026-11-25 live e2e에서 `GET /v1/admin/features?sort=issue_count`가 "Failed to fetch". API `slow_request`는
  `db_statements=1`·`db_ms`≈전체(18~39 s, PSI io 60~75%). n150 읽기 전용 `EXPLAIN (ANALYZE, BUFFERS)`(유휴): `kind` 18.6 s·
  `provider` 13.2 s·`issue_count` 12.7 s, 버퍼 900만 hit — 부하는 증폭일 뿐 원인은 질의 모양이었다(`name`·`updated_at`은 ms).
- 원인: 표시용 LATERAL(대표 원천 다섯 표 + 이슈 jsonb 집계)이 `base` 안에 있어 정렬 키가 인덱스를 못 타면 필터 통과 feature
  전부(43만)마다 두 LATERAL을 돈 뒤 top-N을 골랐다.
- 수정(`admin_feature_repo._admin_features_sql`): 키 단계(`base`: 필터+`sort_key`) → `page`(keyset·LIMIT) → 꾸밈 단계(LATERAL은
  페이지 행에만). 키 단계에는 쓰는 것만: `issue_count` 정렬·`has_issue`면 건수 LATERAL, `provider_dataset_id`면 대표 원천
  LATERAL, `provider` 정렬이면 대표 원천을 `DISTINCT ON` 집합 선택(같은 FROM·순서 조각 — 마지막 키가 PK라 같은 행). 목록 문장
  동안만 `plan_cache_mode=force_custom_plan`·`jit=off`(T-READ-12 방식) — 같은 연결 6번째부터 generic plan이 `provider`를
  10~13 s로 되돌렸고, `kind` 0.6 s 중 0.5 s가 JIT 컴파일이었다.
- 함께 고친 결함: cursor가 응답의 원문 이름을 싣고 keyset은 `lower(name)`과 비교했다(en_US `'gs25' < 'GS25'`) — prod 실측 같은
  이름 4건이 asc 1건, desc는 같은 행 무한 반복. 이제 cursor는 SQL `sort_key` 값.
- 실측(prod 읽기 전용, 같은 연결 8회): `kind` 0.13 s·`issue_count` 0.55 s·`provider` 2.1 s, `issue_count`+`has_issue`+`kinds`
  29.3→2.7 s. 옛/새 결과 prod 15 조합 3쪽까지 값 동일, 적대 리뷰의 차등 시험 4,320 조합 일치. 잔여(후속 후보): `provider` 정렬은
  hash 노드 ~127 MB를 쓴다 — 대표 원천을 쓰기 경로에서 유지하면 인덱스 keyset이 된다. 드문 `provider_dataset_id` + 이름 정렬 ~3 s,
  `has_issue`의 EXISTS화·`issue_count`의 GROUP BY join화도 후보(종전보다 느린 조합은 없음).
- 시험: `tests/integration/test_admin_feature_list_sort.py`(정렬×방향 page 1·2·3 합=전체, 정렬 순서, 대표 원천 일치, 꾸밈
  LATERAL이 페이지 행만), unit SQL 모양·cursor·plan mode. `test_t212d`의 이름 정렬 gate는 최상위가 아니라 `page`의
  `Limit` 아래에 `Sort`가 없는지 본다. `test_candidate_arms_use_admin_trigram_indexes`는 앞 시험의 rollback
  행으로 autoanalyze가 돈 뒤 다른 B-tree 훑기를 골라 깨졌다 — plain index scan도 끄고 본다. journal 2026-10-14~24 70절을
  `archive/journal-2026-10k.md`로 분리(바이트 단위 재구성 검산, 링크만 재기준화). OpenAPI·migration 없음.

## 2026-11-25 — Map 읽기 전용 live 스펙 drift 정비(운영 최종 e2e 후속)

- 근거: 2026-11-25 n150 운영 최종 e2e(읽기 전용 live 스펙, chain16 D1 방식 — root env에서 D1 6개 키만, 쓰기 스펙 제외,
  workers=1). 코드 회귀는 없고 실패는 전부 테스트 drift였다.
- `features-detail` 31건 404: `_fixtures.ts` `FEATURE_IDS`가 재생성 전 스냅샷. 새 `e2e/live/_live-feature-sample.ts`가 실행
  시점에 `GET /v1/admin/features`(kind별 active·published·valid, 이름순 25건, round-robin)로 표본을 뽑고, 스펙은 slot
  번호(`sample #07`)로 돈다(실제 id는 annotation). 재생성과 무관하다. 상세 상단 바의 옛 `Admin` 링크 → `Feature 목록`
  (상단 바 동작 영역으로 scope — 사이드바에도 같은 이름이 있다).
- 화면 이름 drift(`uploads-backups-poi` 34건·`reviews` 29건): 새 `e2e/live/_admin-nav.ts`가 h1·사이드바 링크를 nav
  정본(`src/lib/admin-nav.ts`)에서 읽는다(`Offline uploads`→`오프라인 업로드`, `POI cache targets`→`POI 캐시 대상`,
  nav `Issues`→`이슈`). issues 필터는 `이슈 검색`·`이슈 심각도 필터`. 리뷰 큐 pager는 keyset CursorPager(첫 페이지·
  다음 페이지만, `마지막 페이지` 없음)라 pager nav 두 벌·버튼 접미 일치로 보고, `다음` 활성은 첫 목록 응답의
  `next_cursor`와 같은지로 본다(데이터 무관). 보강 상세는 `detail` 버튼이 아니라 행 클릭으로 열린다. offline-uploads
  필터는 `provider dataset ID filter`(정수) 한 칸 — 입력이 목록 GET `provider_dataset_id`로 나가는지 본다.
- `features-input-roundtrip`: 정렬 `status` 옵션이 사라져 60초 타임아웃 — 정렬 컬럼을 select의 option에서 런타임에 읽는다.
- `ops-consistency-drilldown-roundtrip`: `provider=`는 #966 이후 router가 받지 않아 조용히 무시됐다 —
  `provider_dataset_id` 드릴다운으로 바꾸고 `provider_dataset_id=0`이 422인지도 본다.
- `features-map`: maplibre-gl 6.17.0 npm tarball은 `dist/maplibre-gl-shared.mjs`를 원래 0바이트로 싣고 worker는 단일
  번들이다(tarball 실측). worker는 비어 있지 않아야 하고, shared는 worker가 참조할 때만 비어 있지 않아야 한다. 클러스터
  클릭은 겹친 클러스터가 포인터를 가로채 타임아웃 — 중심점이 가려지지 않은 클러스터를 고르고, 모두 가려지면 Enter로 활성화.
- 적대 리뷰 2인 반영: 화면 h1은 레이아웃이 pathname으로 그려 오류 경계에서도 남으므로 `expectAdminPageLoaded`가 페이지
  자신의 `admin-shell-content`까지 본다. 정렬 옵션 집합은 OpenAPI `AdminFeatureSort` 전체와 같아야 한다. feature 표본은
  kind별 순차 조회·빈 kind 자리는 다른 kind로 채운다. `isVisible` 분기 race는 `.or()` 대기로, 없는 dataset id는 빈 결과.
- 시험: live 스펙만 바뀌었다(앱 코드·OpenAPI·migration 없음). n150 `~/gate-slot.sh` 읽기 전용 재실행(PR 댓글): 최종
  커밋에서 바뀐 6개 스펙 전부 통과(5·13·114·118·171·259), 첫 커밋 run에서 나머지 7개 스펙도 통과. 첫 run의
  `sort=issue_count` "Failed to fetch"는 n150 PSI io 60~75% 중 admin 목록 정렬 18~39초였던 부하성 지연이다(부하 낮은
  run 2는 통과) — 목록 캡처가 이제 같은 요청의 실패를 메시지에 싣는다.

## 2026-11-25 — writer-drain sensor GraphQL을 Dagster 1.13 스키마에 맞춤

- 근거: n150 webserver(Dagster 1.13.24) introspection(읽기 전용) — `stopSensor(id, jobOriginId, jobSelectorId)` →
  `StopSensorMutationResultOrError`(성공 `StopSensorMutationResult.instigationState`), `startSensor` → `SensorOrError`
  (성공 `Sensor.sensorState`). `SensorState` 타입·`sensorOriginId`/`sensorSelectorId` 인자는 없다. 그래서
  `writer_drain_service.py`의 stop/start sensor 문서는 webserver의 검증 단계에서 거부돼(1.13 webserver는 HTTP 400 →
  `post_graphql`의 `raise_for_status` → `DAGSTER_UNAVAILABLE`로 보인다) drain이 sensor를 멈추지도 되살리지도 못했다
  (2026-11-24 freeze 작업 때 기록만 해 둔 것). schedule·run 문서는 맞았다(`stopRunningSchedule(id, scheduleOriginId,
  scheduleSelectorId)`·`ScheduleStateResult`; InstigationState.id는 `<origin>::<selector>` CompoundID이고 1.13 구현은 `id`를
  우선 쓴다 — n150 Map location 61개 instigator 전부 이 모양).
- 고침: sensor 두 문서와 성공 판정(타입·상태 key)을 (kind, start)별 표 하나로. 문서 모양은 #1541 `dagster-freeze.py`가
  n150에서 성공한 것과 같다.
- 시험: `test_writer_drain_graphql_schema.py` — 모듈 소스의 GraphQL operation 문자열 전부(AST로 수집, 인라인 포함)가
  목록 8개와 같고 설치된 `dagster-graphql` 스키마로 `graphql.validate` 통과, 설치 버전 = `constraints-dagster.txt` 핀
  (n150과 같은 1.13.24), 성공 `__typename`이 결과 union 멤버·상태 key가 `InstigationState`, 문서 selection이 판정 표와
  같은지(alias 없음·성공 fragment 안 `<state key> { status }`). `importorskip`을 쓰지 않아 dagster-graphql이 빠지면 실패한다.
  고치기 전 코드에서 sensor 두 문서가 실패함을 확인. `test_writer_drain_command.py`에 네 mutation의 1.13 응답 모양·변수,
  옛 `SensorState`·오류·STOPPED/RUNNING 불일치·null `instigationState` 거부.
- 적대 리뷰 2인(프로토콜 정확성·시험 가드) 조건부 승인. 프로토콜 리뷰가 임시 Dagster instance에서 이 문서들을 실제
  실행해 확인했다(기본 RUNNING sensor stop, 이미 RUNNING start 멱등, 엉터리 originId여도 `id` 우선).
- **남은 결함(이 PR 밖, 소유자 결정 필요)**: restore가 `was_running` 항목을 무조건 `startSensor`/`startSchedule`로 되살린다.
  저장 상태가 없던 코드 기본 RUNNING(`DECLARED_IN_CODE`)은 pause 때 STOPPED 행이 생기고 restore 뒤 저장된 RUNNING 행이 남아,
  나중에 코드 기본값을 STOPPED로 바꿔도 계속 돈다(freeze 도구는 이 경우 `reset*`을 쓴다). 고치려면 조회·스냅샷·digest에
  `defaultStatus`·`canReset`을 넣어야 해 migration과 receipt 계약(`ktm-cache-target-writer-drain/v1`) 변경이 따른다.
  그 밖에 검증 실패(HTTP 400)가 `DAGSTER_UNAVAILABLE`로 분류되는 것도 후속 후보.
- 다음: API 이미지 회전에 싣는다(writer-drain은 one-shot API image command — Manager 코드에는 아직 호출부가 없다). 운영
  mutation은 실행하지 않았다.

## 2026-11-24 — transport export 계약 정렬(#1542 후속): `EXPORT_SOURCE_INCONSISTENT` 상태 job 다음 tick, 주유소 27.5시간

- 근거: transport `docs/map-service-exports-handoff.md`(transport #277 `67eac73`, ADR-013).
- `EXPORT_SOURCE_INCONSISTENT`: producer 권장("다음 tick, 반복되면 경보")을 Valkey 상태 job에 적용한다 — `upstream_signal`이
  이 class를 명시적으로 미준비로 본다(건너뜀 + 나이 판정). 처음엔 예외를 `retryable=False`로 바꿔 feature 적재도 다음
  tick으로 했으나 적대 리뷰(Medium)를 받아 되돌렸다: 주·월 feature 적재에게 다음 tick은 한 주이고, step 재시도의 마지막
  시도(420초)가 `Retry-After` 300초 뒤에 오는 run 안 기회를 둔다(producer는 대개 풀리지 않는다고 본다) —
  `EXPORT_SOURCE_NOT_CURRENT`와 같은 규칙(job 경계가 정한다). 남은 항목 리뷰에서 README 표 위치·모르는 값 규칙 범위·run tag
  문장·이 문구를 고쳤고, `touch_checked` 실패는 run 색을 정하지 않게(best-effort) 했다.
- `EXPORT_QUERY_TIMEOUT`(11번째 code, T4 전용): Map API T4 프록시가 `upstream_unavailable`로 내리는 것을 시험으로 고정.
  Dagster fetcher(T1~T3)는 받지 않는다(오면 모르는 code).
- `Retry-After`는 힌트: 현재 값(SOURCE_NOT_CURRENT 60~3600초·NO_HISTORY 300/3600초)을 예로만 적고 Map은 범위를 가정하지
  않는다(fetcher docstring·ADR-106).
- ADR-106: 주유소 export stale 24시간 → 27.5시간(8시간 tick 두 번 연속 실패까지 200), Map 경고 임계 18시간과의 관계(export가
  200을 내는 18~27.5시간 구간에도 Map은 원천 나이로 빨간 run). 상태 job 실패 metadata 정본 참조를 `upstream_signal`로 정정.
- transport 세션이 남긴 항목: 바뀌지 않은 집합 건너뛰기(`skipped=unchanged`)에서 `touch_checked`로 확인 시각을 세대 meta에
  남긴다(metadata `checked`; 판정 나이는 원천 시각 기준이라 그대로). 모르는 값 규칙 통일 — 원천 응답·서비스 세대에서 읽는
  값은 key를 언제나 싣고 모르면 `""`·`-1`(`transport_problem_code`·`transport_retry_after_seconds`·
  `transport_retry_after_cap_seconds` 포함), 재지 않은 계측(`transport_http_*`·`transport_server_*`·`upstream_requests_min`)만
  key를 뺀다. dagster README에 상태 job metadata 키 표. run tag 두 개(`skipped=unchanged` 포함)는 #1542에 이미 들어갔다.
- 시험: `test_upstream_signal.py`(inconsistent는 retryable과 상관없이 미준비), `test_transport_state_jobs.py`(unchanged
  `touch_checked`, 모르는 값 ""·-1), API
  `test_service_transport_router.py`(T4 `EXPORT_QUERY_TIMEOUT`). OpenAPI·migration 없음.

## 2026-11-24 — 관리자 프런트 ui 0.2.6(VirtualTable 선택 칸 44px) 채택과 dedup 선택 칸 e2e

- #1547(`f5fdeba`): `@kor-travel/ui` 0.2.5→0.2.6·tokens 0.1.6→0.1.7(common #83 `05d7f91`, main docs run 45141922011
  artifact 14803131043; 세 tgz `sha256sum -c` OK, SRI가 catalog #84 `309b881`과 같음)을 vendor하고 guard·`common-ref`를 `309b881`로 올렸다.
  toast 0.1.6은 Map이 쓰지 않아 받지 않았다. lock은 두 tgz의 version·resolved·integrity와 ui peer(tokens 0.1.7)만 바뀌었다.
  다른 PR이 진행 중이라 그 PR은 vendor·package·guard만 바꿨고, 이 절과 아래 e2e는 뒤따라 넣었다.
- 0.2.6에서 Map 화면에 닿는 것: VirtualTable 선택 칸이 md 미만에서 폭 44px·최소 높이 44px(`h-11`)가 되어 체크박스 터치
  영역(0.2.5의 `max-md:after:-inset-[15px]`)과 칸 폭이 일치한다. Map `DataTable`은 공통 `VirtualTable` 재수출이라
  `/admin/features/dedup-reviews` 행 선택 칸이 그대로 바뀐다(데스크톱 24px 불변). Dialog 제목 `pr-7`은 닫기 버튼을 그릴
  때만인데 Map `DialogContent` wrapper는 `showCloseButton=false`라 변화 없음, AccordionContent `overflow-clip`은 Map이
  Accordion을 쓰지 않아 무관.
- 시험: `dedup-reviews-actions.spec.ts`에 `row select cell touch target @390px/@1440px`를 더했다. 390px은 칸 폭 44px·높이
  44px 이상, 체크박스 중심에서 상하좌우 21px 지점의 `elementFromPoint`가 모두 체크박스, 칸 오른쪽 밖 1px(옆 칸)은 아님, 왼쪽
  21px 지점을 실제로 누르면 행 상세 대화상자가 아니라 "1개 선택됨". 1440px은 칸 폭 24px. #1547 때 n150 사본에서만 돌린
  일회성 probe를 바탕으로, 옆 칸 누수 판정과 실제 클릭을 더해 정식 시험으로 만들었다. n150 `~/gate-slot.sh` mocked 실행 결과는 PR 댓글.
- OpenAPI·마이그레이션 변경 없음. 배포하지 않았다(부모 통합 회전).


## 2026-11-24 — 상태 적재 job: 상류 미준비는 건너뜀·나이로 판정, weather export 읽기 줄 세우기 (감사 §4 #9)

- 근거: 감사 보고서 §1.3 P1·P2·§3 + n150 Dagster(읽기 전용) 재측정. Map 실패 run 389건 중 상한 초과 124건(`weather_state_current`
  97 — 79건이 W5 :41과 겹친 :40 회차). 재시도 원인 `TransportExportNotCurrent` 220·`_WeatherUnavailable` 119·
  `DagsterExecutionInterruptedError` 100(전부 weather 상태 job — retry policy가 있으면 run 상한 취소도 재시도로 넘어간다)·
  ReadTimeout 39·ConnectError 22. 부모 단독 측정: current 전량 23페이지 p50 20.5초/페이지·합 460초 + 경합 503 7회 = 706초,
  Map grouping 0.4초. weather 조사: 페이지마다 전체 scope 상태·승인 선택 재검증(SQL 82문장), 23페이지는 weather
  `MAX_PAGE_SCOPES=128`, "경합" 503은 statement_timeout 5초 초과, :41 W5 동시 읽기가 current 페이지 간격을 2~3배로.
- 새 모듈 `kortravelmap.dagster.upstream_signal`(ADR-114 "2026-11-24 개정"): 상류 미준비(provider 예외 `retryable=True`·무응답
  전송 오류·HTTP 429/5xx)는 `skipped=upstream_not_ready`(세대 유지, step 재시도 없음), weather 200+stale은 교체, 교체 거부·
  transport 0건은 `skipped=refused`. 모든 결과에 `upstream_state`·서비스 세대·`served_age_seconds`·`stale_alert`를 싣고 run tag
  둘을 언제나 쓴다. **run 결과는 서비스 세대 나이가 데이터셋 `max_age`(REST stale 기준)를 넘었는지로 정한다** — 넘으면 재시도 없는
  실패. 상태 op에서 `RetryPolicy`를 뺐다(Valkey 연결 실패만 op가 `RetryRequested`).
- weather: Valkey 공용 자리 `weather.export_read`(동시성 1, `ValkeyStateStore.shared_lease`)로 원천 읽기를 줄 세우고, 발화를
  벌렸다(W5 :41→:05, 단기 :30→:50, 중기 :40→:50). 503 페이지 재시도는 같은 cursor로 7회·대기 합 180초(±20%), 다음
  페이지를 상한 안에 못 끝내면 스스로 멈춘다(`weather_export_too_slow`). `weather_state_current` 상한 480→600초는 weather 수정
  전 임시책(뒤에 되돌림). page size·ETag는 손대지 않았다(weather 쪽 수정 뒤 별도).
- P2: tag 없던 Map job 7개에 `dagster/max_runtime`(cache_target_snapshot_gc 3600, managed_file_scan 3600,
  manual_provider_dedup_detection 3600, consistency_dedup_refresh 10800, full_load_batch_consistency_gate 10800,
  mois_localdata_source_sync 21600, offline_upload_load 21600 — 앞 둘은 표본 부족으로 전역과 같게 명시). 지수 backoff RetryPolicy
  둘(feature 적재·maintenance)에 `Jitter.PLUS_MINUS`(±delay). "lock busy가 SUCCESS로 끝나고 15초 뒤 새 run"은 큐 requeue에
  not-before가 필요해 큐 재시도 작업과 겹치므로 이 PR에서 뺐다.
- 적대 리뷰 2인(Dagster 의미·운영 안전) 반영: 미준비도 나이 기준으로 빨갛게(설정 오류가 영영 초록이 되지 않게), httpx 분류 축소
  (scheme 없는 주소는 실패), 계약 위반이 재시도 가능한 원인보다 우선, tag 항상 기록, 기준 = 읽기 `max_age`, 고정 간격 단발 재시도엔
  jitter 제외, GC 상한 3600.
- transport #265(`30aed17`, ADR-013 2026-11-24 개정) 반영: 전국 활성 돌발 0건은 transport가 성공으로 게시하지 않고 export가
  503 — Map은 상류 미준비로 건너뛴다. `transport.highway_incidents` guard의 "기준 미만이면 0건 허용"을 없애고 절대 하한 1건을
  방어선으로 남겼다(옛 transport·계약 위반의 200 + 0건은 거부 → 나이 규칙).
- **소유자 결정(2026-11-24) "나이 기준 혼합"과 #1549 합침**: run 결과 기준을 읽기 `max_age`에서 job spec 경고 임계
  (transport settings — 주유소 18시간·휴게소 유가 9시간·돌발 20분·휴게소·공항 2일, 원천 수집 시각 기준; weather spec 2시간~2일,
  Map 적재 시각 기준 — weather `source_collected_at`이 지역 관측망 등 가장 늦은 원천에 끌려가서다. 표는 ADR-114 개정 절)로
  바꿨다. transport 세션 PR #1549(transport export 503 code 분류·HTTP 층 재시도·바뀌지 않은 주유소 집합 건너뛰기·요청 계측)를 이
  PR로 가져와 같은 자리(`transport_state.py` fetch 실패 처리)를 하나의 의미로 맞췄다 — `TransportSourceNotCurrent` 4종·
  `TransportExportBusy`(대기 상한 초과 포함)·`EXPORT_SOURCE_INCONSISTENT`·code 없는 503은 상태 job에서 상류 미준비(건너뜀)로,
  `EXPORT_DISABLED`·`EXPORT_TOO_LARGE`는 재시도 없는 실패로. 그 PR의 `outcome=skipped_upstream_not_current` 실패 경로는 걷었다.
  feature 적재 asset 쪽 분류는 #1549 그대로다.
- 시험: `test_upstream_signal.py`(새), `test_transport_state_jobs.py`·`test_weather_state_jobs.py`·`test_weather_forecast_delta_jobs.py`·
  `test_definitions.py`(모든 job run 상한, 비-feature schedule 다음 tick 전 회수), integration `test_valkey_{transport,weather}_state.py`
  (거부·나이, 공용 자리 동시성·갱신·대기). OpenAPI·migration 없음. 관리자 화면 변화 없음(e2e 대상 아님).

## 2026-11-24 — 공용 run 큐 우선순위 `dagster/priority`(수집 실패 감사 §2.6 #9·§4 #13)

- 배경: 감사 §2.6 #9 — 공용 Dagster 큐에 `dagster/priority`가 없어 10분 고속도로 돌발·30분 weather 현재 상태가
  매월 적재·GC와 같은 FIFO 줄에 섰다. 소유자 결정(2026-11-24)으로 두 plane 공통 규칙이 생겼다(정본: Manager
  `docs/dagster-tenant-fairness.md`): 10 = 1시간 미만 정기 수집·상태 적재, 5 = 1시간 이상·하루 미만 정기 수집,
  0 = 하루 이상·정리·유지보수·검증·수동. 참고 구현은 transport `JOB_PRIORITIES`.
- 구현: `kortravelmap.dagster.run_priority.JOB_RUN_PRIORITIES` 한 표(job 51개 전부 명시)와 `run_priority_tags()`.
  각 모듈의 job 정의 tag(또는 job 공통 tag 상수)에 펼쳐 넣었다 — Dagster가 schedule·sensor `RunRequest`·GraphQL
  `launchRun` tag를 job 정의 tag 위에 덮어 run tag를 만들므로 모든 실행 경로에 실린다. 표에 없는 job은 code
  location 로드에서 `KeyError`. 탐침(`map_run_heartbeat`)은 상대 import 금지(탐침 lint) 때문에 값을 직접 적는다.
  schedule tag로도 쓰이는 공통 상수(maintenance·file scan·dedup·MOIS 원천)에는 넣지 않고 job 정의에서만 펼친다 —
  공용 규칙이 "RunRequest가 같은 key를 덮어쓰지 않게"다.
- 분류(코드 cron 기준): 10 — `transport_state_highway_incidents`(10분)·`weather_state_current`(:25·:40). 5 —
  transport 유가 둘(매시), weather 초단기·일 요약(매시)·단기·외부(3시간)·중기(하루 4회), 산사태 notice(하루 6회).
  0 — 매일 이상 feature 적재 28개·MOIS 원천 동기화, 매일 상태 적재(휴게소·공항·weather 위치), 매시 GC·6시간 file scan(정리),
  큐 worker·offline upload·batch gate·dedup·completion·탐침. 큐 worker(PinVi cache target·관리자 갱신)는 규칙 표에
  없는 대화형 요청이라 0으로 두고 소유자 결정을 기다린다.
- 시험 `packages/kor-travel-map-dagster/tests/test_run_priority.py`: 정의된 job 집합 = 표, 모든 job 정의 tag =
  표 값 ∈ {0,5,10}, 수집 job의 표 값 = 코드 cron 평균 간격에서 따로 유도한 규칙 값, 비수집 job = 0, 모든 schedule
  tick(coalescing 포함)·큐·MOIS 이어 달리기 요청을 daemon의 run tag 합성(`{**job.run_tags, **request.tags}`,
  Dagster 1.13.24 소스 확인)에 넣은 값 확인, 모든 schedule·sensor 요청(큐·MOIS 이어 달리기 실제 판정 함수·completion)에
  key가 없는지, key를 손으로 적는 모듈이 표·탐침 둘뿐인지(정적). 표·job tag·요청 tag·cron을 일부러 틀린 변이 9종이 모두 빨강(리뷰어 재실행).
- 적대 리뷰 2인(분류·실행 경로 / 시험·tag 상호작용·문서): rebase 충돌 표식이 문서 3곳에 남은 것, geo 릴리스 sensor의
  `RunRequest` 덮어쓰기가 Manager 정본 §3("RunRequest가 같은 key를 덮어쓰지 않게")과 어긋남(덮어쓰기 제거 — 산사태
  재지오코딩 run 1건은 5), schedule tag 상수에 key가 실림, MOIS 원천 동기화가 수집 분류 대조에서 빠짐(cron 상수로 뽑아
  넣음), MOIS·completion 요청 시험이 실제 생성 경로를 안 거침, 수동 실행 의미 문서화, CHANGELOG 효과 과장을 고쳤다.
  completion sweep(산사태 root도 완결)과 탐침을 0으로 둔 판단은 표에 주석으로 남겼다.

## 2026-11-24 — Map Dagster freeze 도구 리뷰 후속 2차(#1552 리뷰)

- 근거 확인: 최신 `origin/main`(1dde1da37)과 열린 #1542·#1548·#1549·#1550·#1551은 `scripts/n150/dagster-freeze.py`를
  건드리지 않는다. 지적 8건 모두 코드로 사실을 확인했다(1·8은 같은 결함).
- rollback 안내(P3 둘): `cmd_freeze`가 webserver 조회를 스냅샷 파일 검사보다 먼저 해, 이미 있는 남의 파일(창 스냅샷)로
  부른 호출이 webserver HTTP 500에 2로 끝나며 그 파일의 unfreeze를 권했다(정상이면 3). 파일 검사(있음·`--resume` 없음
  거부, `--resume`인데 없음 거부, 나이 검사)를 webserver 앞으로 옮기고, `main`도 "호출 전에 없던 파일이거나
  `--resume`"일 때만 `rollback:`을 찍는다. 수정 전 스크립트에 새 시험을 돌려 2(`gave up … HTTP 500`)로 재현했다.
- 상태 run과 회전(P3 둘): `DefaultRunLauncher`의 run worker는 code-server의 자식이라 회전이 돌던 상태 run을 끊고, 끊긴
  run의 Valkey 적재 잠금(`set(nx, ex=ttl)`)은 TTL(상한 + 660초)까지 남는다. #1541 판은 상태 run도 비운 뒤 회전했으니
  회귀다. `freeze --include-state`(상태 schedule도 멈추고 그 run도 기다린다 = #1541 판 동작)를 더해 호스트 회전과 공용
  PG 재생성에 쓰게 했다. 창 안 회전도 회전 전용 파일 + `--include-state`면 상태 schedule만 멈추고 되살려 창과 겹치지
  않는다(시험). 기본 freeze의 마지막 `after:` 줄에 `state_runs=N(기다리지 않음)`을 따로 찍는다.
- 회전 끝 unfreeze(P2): 회전 직후 webserver는 location을 다시 싣기 전까지 `repositoryOrError`에
  `RepositoryNotFoundError`(HTTP 200)를 낸다(dagster_graphql `fetch_repository`, `has_code_location` 거짓). 전송 층은 5xx만
  다시 시도해 unfreeze가 곧바로 2로 끝나고 Map이 얼어 있는 채 남았다. `LocationNotLoaded`로 갈라 unfreeze가
  `--location-wait`(기본 300초)까지 기다리고, 1·2로 끝나 읽히는 스냅샷이 남으면 `retry:` 줄을 찍는다. README에 unfreeze
  종료 코드 규칙(2 다시 돌림·1 확인 뒤 `--accept-missing`·3 나이, 0이 아니면 알린다)을 더했다.
- 문구(P3 둘): "상태 job은 Map PG를 읽지도 쓰지도 않는다"는 틀렸다 — run 프로세스(gRPC 서버가 `spawn`으로 띄운다)가
  정의를 import할 때 `cron_for_schedule`이 `ops.dagster_schedule_overrides`를 읽고, compose가 그것을 필수로 둔다.
  "쓰지 않는다 + import 읽기 하나"로 도구·README·runbook·시험 docstring을 고쳤다. 패키지 시험은 schedule tag와 상태
  모듈 소스(`pg_dsn`·`AsyncKorTravelMapClient` 없음)까지 보고, docstring은 무엇을 보고 무엇을 못 보는지 적는다.
- 가짜 webserver(P3): tick 조회가 질의에 있는 필드만 싣는다. 질의에서 `skipReason`을 지운 돌연변이가 이제
  `test_a_skipped_tick_with_a_reason…`에서 죽는다(전에는 살아남았다).
- 시험: `tests/unit/test_n150_dagster_freeze.py` 55건(+9), `test_freeze_skips_state_jobs.py` 3건 — WSL venv(dagster
  1.13.24). n150 접속·실제 freeze는 하지 않았다.

## 2026-11-24 — Map Dagster freeze 도구 리뷰 후속(#1541)

- 따라잡기 판정(P2): Dagster 1.13 run-status sensor 감싸개(`run_status_sensor_definition.py`)는 사건 하나에 사용자
  함수가 값을 돌려주면 그것을 내고 tick을 끝낸다. `feature_update_request_failure_sensor`는 실패 사건마다
  `SkipReason(message)`를 돌려주므로 그 tick은 SKIPPED(사유 있음)이고 사건 하나를 처리했다. 처리할 사건이 없던 tick은
  감싸개가 아무것도 내지 않아 daemon이 사유 없이 SKIPPED로 남긴다(`_daemon/sensor.py`). 도구는 tick의 `skipReason`을
  함께 읽고 사유 없는 SKIPPED만 센다. feature_operation_* sensor는 `SkipReason`을 내지 않는다(reaction → SUCCESS).
  가짜 webserver 시험으로 먼저 재현했다(사유 있는 SKIPPED 두 번에 FREEZE_OK).
- Valkey 상태 schedule(P2·P3): `weather_state`·`transport_state` 모듈의 job은 `kor_travel_map_client`를 요구하지 않고
  operation tag가 없어(run-status sensor가 panel-only로 지나간다) Map PG에 쓰지 않는다(HTTP export·Valkey만, 정의
  import의 schedule override 읽기는 있다 — 2차 정정).
  freeze가 이 12개를 멈추면 창 동안, 그리고 Dagster가 놓친 tick을 따라잡지 않아 하루 한 번 도는 3개(locations·
  rest_areas·airports)는 unfreeze 뒤 최대 약 24시간 낡았다. 보충 실행(unfreeze가 launchRun) 대신 대상에서 뺐다 — 창 안
  낡음도 없애고 mutation을 늘리지 않는다. 접두어(`STATE_JOB_PREFIXES`)로 schedule을 launcher·이어 하기 거부·FREEZE_OK
  판정에서 빼고, run 대기에서 그 job run을 세지 않는다. 스냅샷은 전부 적어 이전 판 스냅샷도 그대로 되살린다.
  `packages/kor-travel-map-dagster/tests/test_freeze_skips_state_jobs.py`가 접두어 = 상태 job·schedule, 그 job의 PG 경로
  없음을 정의로 대조한다(루트 시험은 경고를 오류로 바꿔 Definitions 로드의 BetaWarning을 억제해야 해서 패키지 시험에 둠).
  열린 #1542(상태 job 상류 신호)도 PG 경로를 더하지 않는다(diff 확인).
- 창 안 회전 안내(P2): 안내대로 회전 전용 파일로 새 도구를 부르면 FREEZE_OK 상태에서 freeze가 "이미 얼어 있다"(3),
  unfreeze가 스냅샷 없음(2)으로 늘 실패했다. 회전 스크립트는 저장소에 없고(호스트 전용), 창 안에서는 창 freeze가 이미
  덮으므로 중첩 freeze가 필요 없다. 그 거부는 얼어 있는 상태를 스냅샷하는 사고를 막는 의도된 안전 장치라 도구가 아니라
  안내를 고쳤다 — "회전의 freeze·unfreeze 단계를 뺀다". 거부 메시지도 그렇게 알린다.
- P3: 자동 회전 스크립트의 종료 코드 규칙(0 회전·3 아무것도 안 바뀜·1/2 스냅샷 있으면 unfreeze로 접기)을 README에
  적고, freeze가 1·2로 끝나면 `rollback:` 두 줄을 찍는다. `--resume`은 스냅샷 RUNNING인 launcher가 다시 켜진 것을
  거부하지 않으므로(prod에서는 Map schedule 대부분이 스냅샷 RUNNING) runbook의 "거부(3)로 알린다"를 고치고 `note:`로
  이름을 남긴다.
- 시험: `tests/unit/test_n150_dagster_freeze.py` 46건(+8), `test_freeze_skips_state_jobs.py` 2건 — 로컬 WSL venv(dagster
  1.13.24). n150 접속·실제 freeze는 하지 않았다.

## 2026-11-24 — 큐 요청 재발행 후속: 상한·종결 후처리·실패 run 표시(#1544 리뷰, PR #1551)

- 배경: #1544(큐 요청 일시 실패 재발행, alembic 456)를 머지 뒤 두 관점으로 리뷰했다. 지적마다 최신 main(#1546 event
  clock slot 포함)에서 코드로 다시 확인했다.
- 실패 run이 SUCCESS로 보이던 것: executor가 결정적 실패를 `failed`로 닫은 뒤 scope/request lock 정리 중 연결이
  끊기면 op는 일시 DB 실패를 받고 재발행을 시도한다. 상태가 이미 종결돼 재발행은 0행이고, op는 `state_changed`로 성공을
  돌려 Dagster run이 SUCCESS, failure sensor 알림이 없었다. 이제 재발행이 0행이면 request를 다시 읽어 이 generation이
  `failed`면 그 오류로 run을 실패시킨다(metadata에 `failure_class`를 싣지 않아 sensor는 닫힌 request를 건드리지 않고
  알림만 보낸다). generation 전진·queued·done이면 종전처럼 성공.
- failure sensor의 재발행 상한: op가 재발행을 기록하지 못하고 죽으면 sensor가 대신 재발행하는데 실패 단계를 몰라 기본
  5회를 썼다(op는 provider 갱신 단계에서 2회). `run_failure_detail`이 op Failure metadata의 `stage`도 꺼내고, sensor가
  op와 같은 `_max_retries_for_stage`로 고른 상한을 `fail_update_request(max_retries=…)`에 넘긴다.
- 종결 후처리: executor 밖 종결(재발행 소진·TerminalizationFailed·RUN_FAILED)의 후처리를 relay `failed` →
  cache target `last_failed_at` → import job event 세 단계로 나눴다. 단계마다 자기 transaction이라 import job event
  쪽 실패(trigger 거부 등)가 relay를 되감지 않는다. `last_failed_at`은 executor 종결과 같이 활성 target(삭제·갱신 끔·
  refresh 끔 제외)에만 찍는다 — 계획이 없으므로 scope key로 고른다(`mark_poi_cache_target_keys_refresh_failed`).
  `poi_cache_targets` 갱신은 alembic 458 전에는 `dataset_projection` live topic 행을 기다릴 수 있어 상태 전이 transaction에
  넣지 않았다.
- 시간 상한: #1546 뒤 event clock은 `SKIP LOCKED` slot이라 리뷰가 짚은 "event clock 30초 × 2" 대기는 더 없다. 다만
  relay stream lock helper가 그 transaction의 `lock_timeout`을 0(무제한)으로 되돌려 relay 뒤 문장의 대기는 묶여 있지
  않았고, 이번에 더한 target 갱신은 live topic 행을 기다릴 수 있다. 최종 형태는 아래 2차 리뷰 항목이다 — 저장소 공용
  `transaction_deadline`·`apply_transaction_limits`(ADR-112)로 묶는다.
- 2차 리뷰(같은 PR, 이 세션의 두 관점 리뷰). 지적 9건 중 아래를 고쳤다.
  - failure sensor 마감: 첫 판은 후처리에만 별도 상수(문장 5초·전체 20초)를 걸었고, 상태 전이는 Dagster 엔진 기본값
    (`lock_timeout` 30초, 재발행 SQL은 `FOR UPDATE OF request, job`으로 행 둘)으로 돌았다. ADR-112는 run-status sensor
    반영을 20초 예산·transaction마다 `lock_timeout` min(5초, 남은 − 4초)로 정했다. 이제 sensor가
    `transaction_deadline(+20초)`과 `asyncio.timeout(+23초)`으로 `fail_update_request` 전체를 감싸고, client는 상태 전이
    transaction마다 `apply_transaction_limits`를 부른다(마감이 없는 op 경로는 그대로).
  - 후처리 상한: 전체 마감은 `transaction_deadline`(호출자 마감이 더 이르면 그쪽), 시도마다 8초 마감에서 ADR-112 규칙
    (문장 5초·lock 4초)을 건다. 문장마다 `statement_timeout`이 새로 걸려 relay처럼 문장이 여럿인 시도는 마감을 넘길 수
    있었다 — 시도를 그 마감에서 `asyncio.timeout`으로 끊는다.
  - 누적 상한: `retry_count`는 launch 실패 재발행도 센다. provider 단계 상한(2회)을 단계별로 따로 셀지 정했다 — 누적에
    건다(따로 세면 열·migration이 필요하고, 이미 재발행을 거듭한 요청을 provider 단계에서 더 미루지 않는 편이 상류
    쿼터에 안전하다). 대신 종결 메시지가 상한만 적어 실제 누적과 어긋났다(`재발행 2회 소진`인데 누적 4회) —
    `재발행 상한 N회 소진(누적 M회): …`로 바꿨다. mocked e2e(`ops-pipeline.spec.ts`)의 provider 단계 + `max_retries: 5`
    조합도 나올 수 없는 값이라 2회로 맞췄다.
  - relay 시험이 빈 성공이었다: 시험 요청에 relay member가 없어 relay 단계가 아무것도 쓰지 않았다. member를 캡처한
    요청(stream·source head·`capture_cache_target_refresh_members_by_keys`)으로 outbox `failed` 행을 단언한다.
  - 456 회전 안내: 점검(`running` 수) 뒤 sensor가 새 요청을 claim하는 틈, 고아 `running` 행, 실패 시 API 미기동이
    빠져 있었다 — freeze → `pg_locks` 확인 → 회전(실패 시 재기동·원복) → unfreeze 순서로 다시 적었다.
  - 주석 정정: 상한 소진·TerminalizationFailed 종결의 COMMIT 응답만 잃은 경우 op가 맞추는 것은 run 상태뿐이고 relay
    `failed`·`last_failed_at`·종결 event는 쓰이지 않는다. 다시 내는 것은 relay 종결 여부를 보는 reconciler 몫이다(남은
    위험). executor 자신이 종결한 경우와 구분하지 않고 다시 내면 `error_code`가 다른 `failed` relay가 하나 더 생긴다.
  - 사실이 아니어서 고치지 않은 것: "failure sensor 평가 한 번이 실패 run 최대 5건을 처리해 5 × 50초"는 이 sensor에
    해당하지 않는다. Dagster run-status sensor는 sensor 함수가 `None`이 아닌 값을 돌려주면 그 run에서 tick을 끝내고
    (`run_status_sensor_definition.py`의 `if sensor_return is not None: … return`), 이 sensor는 언제나 `SkipReason`을
    돌려준다. 평가 한 번은 run 하나다 — 그 불변식을 시험으로 고정했다. 다만 "60초 안" 문구는 위 마감으로 바꿨다.
- 시험: dagster 단위(`failed` generation이면 run 실패·다른 generation이면 성공, sensor 상한 2회·launch 실패 5회,
  stage 추출, sensor가 20초 이하 마감을 건 채 반영, 걸린 반영을 끊고 알림은 보냄, 평가 한 번에 run 하나 —
  `SkipReason` 대신 `None`을 돌려주는 변이에서 빨강 확인). 통합(PostGIS) — claim 뒤 transient_db 2회 재발행 뒤 "재발행
  상한 2회 소진(누적 2회)", launch 실패 3회 뒤 provider 단계 첫 실패에서 "재발행 상한 2회 소진(누적 3회)", 세 종결
  경로의 `last_failed_at`(활성만), member를 캡처한 요청에서 import job event가 실패해도 outbox `failed` 행이 남음(relay
  단계를 빼는 변이에서 빨강), source head를 쥔 동안 relay 시도가 서버 쪽(`statement_timeout`)·client 쪽
  (`asyncio.timeout`) 마감에서 끊기고 다음 단계는 같은 session으로 이어짐, 마감을 건 상태 전이가 request 행 lock을
  2초에 55P03으로 포기함, target 행을 쥔 동안 후처리가 상한 안에서 끝남(상한·마감을 빼는 변이에서 각각 빨강 확인).
  기존 `test_client_orchestration`·`test_feature_update_repo`·`test_feature_update_executor` 70건 통과.
- 반영하지 않은 것: migration 456 lock 실패는 코드 결함이 아니라 회전 절차라 `resume.md` 다음 단계에 순서를 적었다.
  COMMIT 응답 유실 뒤 후처리를 다시 내는 reconciler는 만들지 않았다(위).


## 2026-11-24 — live topic revision을 commit 직전에 올림·10-22 큐 상황 전체 재현(alembic 458)

- 재현(`tests/integration/test_queue_concurrency_1022.py`, 모듈 전용 DB): 긴 큐 적재(KNPS 탐방로 실제 asset — runner 맨
  앞에서 topic 원본 셋을 쓰고 역지오코딩에서 transaction을 연 채 멈춤) 동안 큐 요청 12건(KNPS point 5·geometry 4,
  국가유산 item·행사, 축제 cache target)을 실제 asset·Dagster LOGIN·`lock_timeout` 3초로 실행기 경로에 태운다.
  456: 12건 모두 `INSERT INTO ops.import_job_events` `LockNotAvailableError`(prod 10-22 서명). 457·458 뒤: 12건 모두
  `done`, 긴 transaction을 기다린 backend 0. 남는 대기는 다른 요청끼리의 `feature-curation-write` fence(설계).
- 첫 판은 "live topic 행은 경합 없음"으로 결론냈다가 적대 리뷰가 뒤집었다: 쓰기 중간 `record_override_geo_stale`
  (`data_integrity_violations` INSERT)과 꼬리의 주소 finding이 `dataset_projection` 행을 commit까지 쥔다. finding 1건 적재를
  꼬리에서 멈추면 cache target resolve 문장이 lock timeout(리뷰 실측). fixture가 finding 0건·geo token 없음이라 놓쳤다.
- 458: 원본 statement trigger는 `ops.ops_live_topic_pending(txid, topic)` 표식만 남기고(`ON CONFLICT DO NOTHING`, 행 수
  무관), `DEFERRABLE INITIALLY DEFERRED` constraint trigger가 commit 직전에 topic 이름 순서로 `revision + 1`을 적용한다.
  ADR-065 receipt는 `SET CONSTRAINTS … IMMEDIATE`로 표식을 먼저 적용하고 읽는다(인과 그대로). slot+SUM은 receipt 인과를
  깨므로 쓰지 않았다 — 후보 비교·남는 것은 `data-model.md` §9.13. 값은 statement당이 아니라 topic을 바꾼 commit당 1.
- 시험: 위 재현 2건(변환 단계 hold·주소 finding 있는 쓰기 끝 hold), `test_ops_live_topic_revisions`의 late commit 3건을
  "기다리지 않고 commit마다 1"로 고침, unit receipt 순서, 구조 계약(`test_alembic_upgrade`). head-schema 재생성.
- 재리뷰 반영: 표식의 첫 deferred 발화가 표식을 한 번 줄 맨 뒤로 다시 넣는다(`ready`) — 쓰기 중간에 생긴 표식이 뒤따르는
  completeness 검사(쓰기 행 수만큼) 내내 topic 행을 쥐던 것(리뷰 실측 3초 검사). 시험 추가: deferred 순서(재넣기 제거 변이에서
  빨강), 실제 `get_dataset_projection_revision` receipt 인과, transaction당 topic +1·표식 누수 0. 표식 표 권한은 SELECT·INSERT·DELETE.
- 남은 것: 큰 첫 적재의 쓰기 단계가 fence 900초 상한을 넘을 수 있다(ADR-113 재검토 조건, 별도).


## 2026-11-24 — Map Dagster 전체 freeze 도구·미기동 schedule 6개 활성 반영(수집 실패 감사 §4 #10·#11)

- #10: n150 `~/freeze.py`는 산사태 schedule과 update-request 큐 sensor 둘만 멈춰, PG에 쓰는 나머지 Map
  instigator 약 42개(MOIS·consistency·GC·file scan·feature 적재 schedule)가 운영 창 안에서 그대로 돌았다.
  `scripts/n150/dagster-freeze.py`(표준 라이브러리, host `python3`)로 저장소 정본을 만들었다. `freeze`는 Map
  location의 모든 schedule·sensor 상태·코드 기본값·저장 여부(`canReset`)를 스냅샷(절대 경로, 0600, fsync 뒤 rename)한
  뒤 launcher(schedule·non-run-status sensor)를 멈추고 Map run(repository tag로 좁힘) 0을 기다린다. 그다음
  run-status sensor마다 run 0 뒤 SKIPPED tick(처리할 사건 없음)을 서로 다른 두 시각에 보는지 보고 run을 다시 센다 —
  `feature_operation_success_sensor`는 completion job run을 **낸다**(적대 리뷰 H1). 그 뒤 run-status sensor를 멈추고,
  그 사이 run이 생기면 되살린 채 1로 끝난다. launcher 정지 실패·대기 초과도 run-status sensor를 켜 둔 채 1.
  기존 스냅샷은 `--resume`(24시간 안)일 때만 이어 쓰고, 스냅샷이 RUNNING으로 적지 않은 것이 지금 RUNNING이거나,
  새 스냅샷인데 RUNNING launcher가 0이면(이미 얼어 있음 — 다른 경로로 재실행) 거부한다(3, 리뷰 H2). `unfreeze`는
  스냅샷의 RUNNING만 되살리되(run-status sensor 먼저) 저장 상태가 없던 기본 RUNNING은 `reset`으로(저장된 행이
  코드 기본값을 덮지 않게, 리뷰 M2), STOPPED(MOIS continuation 등)는 그대로, 스냅샷 없거나 비었거나 count가 다르면
  거부, `missing`은 `--accept-missing`으로만 마치고, 성공하면 스냅샷을 `.restored-<UTC>`로 옮긴다. 주소·인증은
  env에서 읽고 출력하지 않는다(잘못된 URL도 원문 없이 2, Basic Auth는 https·loopback에만, redirect 안 따라감).
  PinVi·concierge location은 읽지도 바꾸지도 않는다. mutation 인자·반환형은 n150 Dagster 1.13.24 introspection으로
  확인했다(`stopSensor(jobOriginId, jobSelectorId)`). 같은 introspection으로 보면 `writer_drain_service.py`의
  `stopSensor(id, sensorOriginId, sensorSelectorId)`·`... on SensorState`는 이 버전 스키마와 맞지 않는다(범위 밖, 기록만).
- #11: 미기동 6개(TourAPI 관광지 daily·표준 지역특화거리·전통시장·국가유산 item·concierge YouTube·transport
  주유소)는 `DISABLED_FEATURE_LOAD_SCHEDULES`에 넣을 문서화된 보류 사유가 없었다(관광지·시장·특화거리는
  T-TOURAPI-LOAD·T-MARKET-LOAD의 "켜기"만 남은 상태, 국가유산 item·YouTube는 기록 없음, 주유소 place는 ADR-114의
  "열린 결정"이지 중지 결정이 아님). 소유자 결정으로 부모가 2026-11-24 prod에서 6개를 켰다. 코드 기본 상태는
  저장소 관례대로 STOPPED 그대로 두고 `schedules.py` 주석·`test_prod_enabled_schedules_are_built_but_start_stopped`로
  기록했다. cron은 바꾸지 않았다(prod가 지금 그 값으로 돈다).
- 시험: `tests/unit/test_n150_dagster_freeze.py` 38건(가짜 webserver에 n150 Map location 실제 구성 61개 + PinVi
  location, 6개 RUNNING 포함 스냅샷·복원). n150 읽기 전용 `status`·`freeze --dry-run`·스냅샷 없는 `unfreeze` 거부
  확인(instigator 61·RUNNING 59, 6개 모두 RUNNING, run-status sensor 8개의 tick 조회), 상대 경로 거부. 실제 freeze/unfreeze는
  돌리지 않았다. 적대 리뷰 2인(상태 기계·운영/보안) 지적을 반영했다.

## 2026-11-24 — import job event clock을 slot으로 나눔(감사 §1.2·#1544 남은 구조 문제, alembic 457)

- 근거(n150 Map DB 읽기 전용 조회): 10-22 큐 요청 12건 중 8건이 `LockNotAvailableError` + `INSERT INTO
  ops.import_job_events`로 끝났다. 8건 모두 04:55~05:04Z claim 직후 약 30초(Dagster 엔진 `lock_timeout`)에 실패했고,
  04:47:51~06:04:08Z 76분 동안 refresh transaction을 연 앞 요청(04:47:52Z `job.heartbeat` event를 쓰고 같은 transaction에서
  적재)과 정확히 겹친다. 전역 singleton `ops.import_job_event_clock`의 row lock이 commit까지 남은 탓이다. 공용 PG에
  `pg_stat_statements`는 없고(`log_lock_waits=on`), 컨테이너 로그는 11-23 재시작 이후뿐이라 그 창의 lock wait 로그는 없다.
- 457: `ops.import_job_event_clock_slots`(identity slot). event statement trigger가 다른 transaction이 잡지 않은 가장 작은
  slot을 `FOR UPDATE SKIP LOCKED`로 골라 +1, 모두 잡혀 있으면 새 slot. reader(`/v1/ops/live` `event_clock_revision`)는
  `SUM(revision)` — 의미·값이 종전과 같다(commit된 event statement 수, 옛 값은 slot 1로 이관). guard는 trigger 밖
  INSERT/UPDATE/DELETE/TRUNCATE 거부. migration은 옛 표를 ACCESS EXCLUSIVE로 잡아(1초) 진행 중인 event transaction이
  없을 때만 값을 옮긴다. 후보 비교(sequence·별도 transaction·지연 잡기·job별 행)는 `data-model.md` §9.1.1 event clock.
- 시험: integration `test_import_job_event_clock_slots.py` — 긴 event transaction 중 다른 job event가 `lock_timeout` 2초
  아래서 기다리지 않음(main 456에서는 55P03), late commit·rollback·UPDATE statement 감지, slot 수 상한, guard,
  `ktm_curation_command_owner`의 새 slot, 456→457 이관(진행 중 writer면 lock timeout으로 거부).
- 적대 리뷰 2인 반영: ① migration이 `ktm_feature_runtime`에 새 표 권한을 직접 준다(별도 process인 ACL 조정 전
  창에서 runtime event 기록이 42501로 전부 실패하던 것 — 실측). ② transaction이 처음 고른 slot을 transaction-local
  설정에 기억해 다시 쓴다(긴 transaction이 더 낮은 slot을 계속 쥐어 동시 3개에 slot 5개가 되던 것). ③ guard 시험은
  23514만 받고 TRUNCATE는 소유자로, slot 시험에 `lock_timeout`(회귀 시 10분 hang 대신 2초 실패).
- 남은 것: `ops.ops_live_topic_revisions`(provider_sync·dataset_projection·dagster_schedules)도 같은 singleton 꼴이지만
  432 snapshot 잠금 순서와 ADR-065 causal receipt에 묶여 있어 이번에 바꾸지 않았다. 큐 경로에서는 cache target 요청의
  `poi_cache_targets` 갱신이 그 행을 잡는다.


## 2026-11-24 — 큐 요청 일시 실패 재발행·상한과 실패 원인 기록(감사 §4 #15·§1.3 P1, alembic 456)

- 배경(`docs/reports/2026-11-23-collection-failure-audit.md`): ① 큐 요청은 일시 DB 오류에도 한 번에 `failed`로
  닫혔다(10-22 한꺼번에 넣은 13건이 `import_job_events` INSERT lock timeout으로 실패 — 전역 단일 행
  `import_job_event_clock`을 긴 적재 transaction이 commit까지 쥔다). ② worker run이 claim 전에 실패하면(launch 실패 —
  n150 fd 고갈) failure sensor가 generation만 +1해 15초 뒤 곧바로 새 run을 냈고 상한·backoff가 없었다. ③ 실패 원인이
  Map DB에 남지 않았다 — request는 `ProviderDatasetRefreshFailure: provider refresh asset execution failed` 한 줄(원인은
  `__cause__`에만), operation root는 `{"kind":"dagster_run_terminal","status":"FAILURE"}` 한 줄.
- alembic 456: `ops.feature_update_requests.retry_count`(≥0)·`next_dispatch_at`. 큐 peek은 `next_dispatch_at <= now()`인
  것만 집는다. 재발행 SQL은 claim 전 `queued`(+run 없음) 또는 그 run의 `running`을 같은 문장에서 queued·generation+1·
  retry_count+1·`next_dispatch_at = now() + min(30분, 60초 × 2^n) × [0.5, 1.0)`로 돌린다. 상한(`FEATURE_UPDATE_MAX_RETRIES`=5,
  약 31분)을 넘으면 같은 상태 술어에서 `failed`로 닫는다(claim 전 `queued`도 — 종전 `finish_update_request`는 running만
  닫아 launch 실패 request가 영원히 재발행됐다). `advance_update_request_generation_after_pre_start_failure`는 지웠다.
- executor: 실패를 `infra/failure_summary.py`로 요약한다 — SQLSTATE(55P03·40001·40P01·08xxx·57P0x·53300)·
  `connection_invalidated`·asyncpg 연결 예외로 **일시 DB 실패**를 가르고(명시적 `__cause__`·`orig`만 따른다,
  `__context__`는 정리 중의 다른 실패일 수 있어 따르지 않는다), 메시지는 SQL 본문·bind parameter·serviceKey·token·DSN
  비밀번호·Bearer를 걷고 300자로 자른다. 일시 DB 실패면 request를 **종결하지 않고** `FeatureUpdateTransientFailure`(분류·
  실패 단계)를 올린다 — 실패한 phase는 이미 되감겼고, 같은 연결로 terminal 쓰기를 하면 끊긴 연결에선 그것도 실패하고
  lock 경합이면 같은 lock을 다시 기다린다. 결정적 실패는 종전대로 닫되 `error_message`가 가장 안쪽 원인을 덧붙이고
  (`… ← 원인 Type: msg`, 머리는 종전 `Type: msg` 그대로), **모든** 실패가 terminal import job event
  (`FEATURE_UPDATE_EXECUTION_FAILED` 또는 provider의 좁은 code)에 분류·원인 연쇄·실패 단계·Dagster run id를 남긴다.
- Dagster 큐 op: `FeatureUpdateTransientFailure`와 claim 전 일시 DB 실패를 **새 연결로** `reschedule_update_request_after_failure`
  에 넘긴다 — 재발행이면 run SUCCESS + output metadata(`retry_scheduled`·다음 발행 시각), 상한이면 `failed`로 닫고 run
  FAILURE. failure sensor: `RUN_FAILURE` 이벤트의 `first_step_failure_event`에서 실패 step·오류 타입·메시지·가장 안쪽 원인을
  storage를 다시 읽지 않고 꺼내(`dagster/run_failure_detail.py`) 메시지와 payload에 싣는다. claim 전 실패는 backoff 재발행
  (상한), claim 뒤 실패(run이 도중에 죽음)는 재발행하지 않고 `FEATURE_UPDATE_RUN_FAILED`로 닫으며 PinVi relay에도
  `failed`를 낸다(종전에는 relay event가 없었다). 재발행 뒤의 PinVi "running" 재통지는 같은 payload라 replay로 접힌다.
- operation root(`dagster_run_terminal`): FAILURE 상태 sensor 반영 때 `failure_reason`·`failed_step`·`error_type`·`error`·
  `cause`를 더한다(reconcile·completion 경로는 이벤트가 없어 종전 모양). member attempt event(`feature_operation.attempt`)의
  `error`에도 분류·메시지·원인·step·run id를 싣는다(종전 code·type뿐).
- 관리자 화면: 실행 상세 이벤트 목록이 위 code 넷의 payload에서 승인된 필드만(분류·DB 실패 종류·실패 단계·실패 step·
  재발행 n/5·다음 발행·Dagster run) 보여 준다(`components/feature-update-failure-detail.tsx`). API·OpenAPI 변경 없음.
- 남은 구조 문제(이번에 고치지 않음): `import_job_event_clock` 단일 행을 긴 적재 transaction이 쥐는 것 — 재발행은 경합을
  분 단위로 기다려 줄 뿐 원인을 없애지 않는다.
- 시험: unit `tests/unit/test_failure_summary.py`, Dagster `test_run_failure_detail.py`·`test_sensors.py`(재발행·상한·결정적·
  원인 메시지), integration `test_feature_update_transient_retry.py`(backoff·peek 숨김·상한·owner·executor 미종결·terminal
  event·sensor 경로 상한), `test_feature_update_repo.py` 재발행 API로 이관, mocked e2e `ops-pipeline.spec.ts`
  "큐 요청 실패 원인·재발행 일정". head-schema.sql·migration graph·forward-only 목록 갱신.
## 2026-11-24 — 다건 호출 provider 호출 단위 재시도·쿼터 결과 코드 분류(감사 §4 #15·§1.3 P0/P1)

- 배경: `upstream_retry.py`의 설명과 달리 적용처는 KHOA 하나뿐이었다. 국가유산(행사 14달·본체 상세 ~4,000건)·
  산림청 페이지·TourAPI 축제/관광지 페이지·서울 책방·표준데이터 공개 파일·concierge export·MCST slug·MOIS LOCALDATA
  업종은 5xx·timeout 한 번에 asset(또는 op) 전체가 실패했고 step 재시도가 처음부터 다시 돌았다
  (`docs/reports/2026-11-23-collection-failure-audit.md` §1.3 P0).
- 새 판정 `dagster/upstream_transient.py`: HTTP 상태가 있으면 408·425·429·500·502·503·504만 일시 오류(2xx·3xx
  상태는 무시 — visitkorea·krforest가 결과 코드 오류에 200을 싣는다), 없으면 lib 분류(`retryable`,
  `failure_kind` network·server·timeout), 그다음 전송 계층 예외, 분류 속성 없는 lib의 일시 오류 타입 선언
  (datagokr `TransportError`·mois `MoisServerError`·mcst `McstNetworkError`), 마지막으로 명시적 `__cause__`.
  쿼터 소진은 언제나 거절. `Retry-After`(header 초·HTTP-date, `retry_after` 속성)를 읽는다.
- `upstream_retry`: `jitter`(equal jitter, 기본 꺼짐 — 상태 job 시험 결정성 유지), `retry_after`(대기 하한, 120초를
  넘으면 예산을 쓰지 않고 원 예외). 예산은 fetcher(dataset)마다 settings 비례 예산(`provider_upstream_retry_budget_*`,
  hard cap 32)이다 — run 공유 예산을 넓히던 첫 판은 적대 리뷰가 "settings 0으로 끄는 스위치가 먹지 않고 같은 run의
  transport·weather 상한까지 올린다"로 잡아 KHOA가 쓰던 방식으로 되돌렸다.
- 호출 지점 정책 `provider_fetchers.provider_call_with_retry`(ADR-006 — client를 감싸지 않고 public 메서드 하나를
  넘긴다): 시도 2회, 15초 기준 backoff + jitter. 적용: 국가유산 행사 달·목록 페이지·상세, 산림청 페이지(휴양림·
  산사태), TourAPI 축제·관광지 페이지, 서울 책방 페이지(키가 경로라 label에 넣지 않음, `SeoulOpenDataError.
  status_code` 추가), 표준데이터 공개 파일(재시도 단위 = 파일 하나, 행 중복 없음), concierge export 페이지,
  MCST slug(CSV를 다 받은 뒤 내보낸다 — 재시도 때 앞 행 중복 없음), MOIS LOCALDATA 업종(업종마다 한 번 commit,
  실패 시도는 session close가 버리고 upsert는 멱등), KHOA(같은 helper로 수렴). 시도마다 `note_upstream_request`
  (페이지네이터가 첫 시도를 세는 자리는 `count_retries=True`로 재시도만 더 센다). MCST slug 실패의 `retryable`도 같은
  판정을 쓴다. 결정적인 httpx 전송 오류(`UnsupportedProtocol`·`LocalProtocolError`)는 재시도하지 않고, datagokr
  `FILE_METADATA_CHANGED`(받는 중 파일이 바뀜)는 파일 단위로 다시 받는다.
- 쿼터(§1.3 P1): datagokr·krheritage `ApiErrorResponse.code`, mois `MoisError.result_code`가 `22` 또는
  메시지 `LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS`면 일일 쿼터(`quota_exhaustion.RESULT_CODE_QUOTA_ATTRIBUTES`,
  모듈 한정). 핀 SHA 소스로 신호가 이미 예외에 있음을 확인해 provider 수정은 필요 없었다.
- 남김: datagokr fileData(odcloud) `iter_pages`는 provider 안 순회라 호출 단위로 못 끊는다(해당 dataset은 활용신청
  미완으로 꺼져 있다). 단건 호출(knps·산림청 SHP)은 step 재시도로 충분해 두었다.
- 시험: `packages/kor-travel-map-dagster/tests/test_provider_call_retry.py`(분류 표·Retry-After·jitter·예산 공유·
  fetcher 9곳·실물 datagokr/krheritage/mois 예외 계약). OpenAPI·migration 없음.


## 2026-11-23 — R4 전환 계획 제외 옵션: 정밀도 미달 쌍을 계획 파일을 고치지 않고 뺀다

- 배경: R4 준비 계획(읽기 전용, `plan_sha256 3f93a4b7…`)의 표본 판정에서 `barrier_free_places` collapse
  (0.94~0.96 — 한 복합 건물 주소의 다른 시설이 0 m로 접힘)와 `world_restaurants` collapse(0.81~0.92 — 다른
  주소의 체인 지점이 접힘)가 게이트 0.97을 못 넘었다. 계획기·실행기 어느 쪽에도 쌍을 빼는 길이 없었고
  `plan.json`을 손으로 고치는 것은 설계 위반이다.
- `mcst-theme-plan --exclude <dataset>:<action>`(반복). dataset은 dataset_key 또는 slug(`_csv` 생략 가능)로
  받아 dataset_key로 기록한다. 제외된 행은 `keep`으로 다시 쓰지 않고 계획의 `excluded_items`에 원래 action·
  대상·`row_revision` 그대로 남긴다(효과는 `keep`과 같다) — 판정(보고서 `by_dataset`·표본)과 운영 결정
  (`exclusions`)을 섞지 않아 표본 감사가 제외 전후로 같은 숫자를 본다. `exclusions`·`excluded_items`가
  `plan_sha256`에 들어 승인한 sha가 "하지 않을 것"까지 고정한다(아무 행도 빼지 않는 제외도 sha를 바꾼다).
- 실행기: `--exclude`를 다시 받아 계획의 제외와 정확히 같을 때만 돈다(리허설 포함, DB 접근 전 종료 코드 2).
  `load_transition_plan`은 제외 쌍의 행이 `items`에 있거나, 제외에 없는 쌍이 `excluded_items`에 있거나,
  남는 전환이 제외된 Feature를 대상으로 하거나, 같은 Feature가 두 번 있으면 거부한다.
  `execute_transition_batch`도 제외 쌍의 행을 받으면 잠금·쓰기 전에 거부한다(라이브러리 직접 호출 방어).
- sha 정의가 바뀌어 이전 형식 계획 파일은 "옛 형식"으로 거부한다 — 운영 창에서 어차피 새로 뽑는다. 계획은
  여전히 `SET TRANSACTION READ ONLY` 하나이고 제외는 읽은 뒤 메모리에서만 적용한다.
- 시험: unit `tests/unit/test_mcst_theme_plan_exclude.py`(파싱·계획 내용·sha·변조 거부·실행기가 `items`만
  넘김·불일치 거부), integration `test_excluded_pair_is_left_untouched`(실 PostGIS: 제외 행 active·revision
  불변·사건·장부 0, 같은 batch의 attach는 전환). OpenAPI·migration·PinVi 재vendor 없음.

## 2026-11-23 — 관리자 프런트 ui 0.2.5(입력·선택 컨트롤 focus 정본화)와 Map 덧대기 제거

- `@kor-travel/ui` 0.2.4→0.2.5·tokens 0.1.5→0.1.6(common #81 `fe141143`, main CI artifact 14782962353
  ZIP `sha256:065bfbdf…`; sha256·SRI가 catalog #82 `ade7b3eb`와 같음)를 vendor하고 guard·`common-ref`를 `ade7b3eb`로
  올렸다. toast 0.1.5는 Map이 쓰지 않아 받지 않았다. ui·tokens 의존 목록은 그대로이고 ui peer만 tokens 0.1.6이다.
- 공통 0.2.5 Input·NativeSelect·SelectTrigger·Textarea·Checkbox·Switch·Badge 등이 FS-7.8 단일 outline 2px·offset 2px
  (`outline-kt-focus`)를 직접 내고 체크박스 터치 영역이 md 미만 44px가 됐다. Map wrapper(`input`·`native-select`·
  `checkbox`·`textarea`·`form-*`)에는 덧대기가 없었다. 중복이던 두 곳을 지웠다: `badge-variants.ts`의
  `focus-visible:outline-2/offset-2/outline-focus`(공통 Badge가 같은 값), 파이프라인 요청 대화상자 dry-run 원시
  `<input type="checkbox">`의 같은 세 클래스(`@layer base` `:focus-visible`이 같은 값을 그린다).
- 시험: vitest `field-focus.test.tsx`는 Input·NativeSelect·Checkbox·링크 Badge의 focus 클래스가 정확히 세 개이고
  체크박스에 `max-md:after:-inset-[15px]`가 있음을 본다. Playwright `admin-shell.spec.ts`에 `/ops/logs` 입력·선택의
  Tab 포커스 2px outline 하나·ring·테두리 변화 없음 검사를 더했다.
- Map admin OpenAPI 변경 없음, 마이그레이션 없음.

## 2026-11-23 — 파이프라인 필터 e2e 간헐 실패: 화면이 router의 늦은 `searchParams`를 읽었다

- 증상: `ops-pipeline.spec.ts` "필터가 executions 쿼리 파라미터로 전달된다"가 가끔 `running|101|`(sync_scope 없음)로 실패.
  n150 mocked e2e 재현(main `5586635a`, `--repeat-each=20 --retries=0`): workers 2에서 2/20·4/20, workers 4·40회
  (고친 첫 판)에서도 5/40. 실패 화면은 provider 101, scope 칸은 활성인데 비어 있었다 — 입력이 사라졌다.
- 원인: 화면이 필터를 router의 `useSearchParams`에서 읽었다. Next 16은 same-route `history.replaceState/pushState`를
  **transition**으로 router 상태에 옮기므로 ① `searchParams`가 방금 쓴 URL보다 늦고 ② 이어진 쓰기가 따로·늦게 commit되며
  ③ 늦은 commit의 `HistoryUpdater`가 그 시점 canonical URL을 브라우저에 다시 써 `window.location`도 잠깐 되돌린다.
  빠른 입력(상태 → ID → scope)에서 두 경로로 scope를 잃었다. (a) provider blur가 draft를 버리면 낡은 URL의 빈 ID가 렌더돼
  scope 칸이 비활성으로 바뀌어 포커스·입력을 잃었다 — 같은 task에서 입력 → 포커스 이동을 하는 새 시험이 main에서
  **20/20** 실패(blur 직후 provider `""`·scope disabled). (b) URL 기준 사본(ref)이 늦은 commit에 덮여 provider 없는 URL을
  만들면 triple 규칙이 scope를 지웠다. stress trace에서 scope가 실린 요청은 0건이었고, provider가 반영된 뒤 status만 있는
  요청이 다시 나온 run도 있었다(router 상태 자체의 일시 역행).
- 고침: `useOwnedSearchParams`(새 파일) — 화면이 쓴 query를 같은 렌더의 상태로 들고, router commit은 우리 쓰기(중간·순서
  뒤바뀜 포함)면 무시하고 우리가 쓴 적 없는 commit만 외부 이동으로 받는다(popstate는 대기 목록을 비운다). 파이프라인
  화면의 모든 URL 읽기·쓰기가 이것을 쓴다. 중간 시도 둘(location 기준, 쓴 query ref + blur 보존)은 workers 4에서 각각
  3/20·2/40 실패로 부족해 대체했다. 재시도·sleep은 더하지 않았다.
- 검증(n150 `~/gate-slot.sh`, io-guard 통과 뒤): 원 시험 + 새 시험 workers 4·`--repeat-each=40 --retries=0` **80/80**(두 차례),
  ops-pipeline·admin-shell·home-nav 전체 193 passed, static(check-deps·lint·doctor·vitest·type-check·build) PASS. vitest
  `use-owned-search-params.test.ts`가 늦은·뒤바뀐 commit 무시와 외부 commit 수용을 고정한다. **frontend 코드 변경 — 운영
  반영은 다음 회전.** OpenAPI·migration 없음.

## 2026-11-23 — 읽기 성능 원장 정리: T-READ-12 완료·T-READ-06 보류·T-READ-07 스냅샷 정정

- `T-READ-12` 완료: 회전 t1122a(Map `7a44cf94`, api·ui·dagster-code-server 이미지 revision 일치, 배포 코드에
  `force_custom_plan` 확인) 뒤 2026-11-22 02:49Z 조용한 창(공용 Dagster instigator 69개 정지·run 0, 측정 뒤 그대로 복원)에서
  probe `--warmup-per-case 90`·30회로 쟀다(측정 이름 tread1122a). zoom 7 sido 집계 server p50/p95 **185/642 → 158/191 ms**
  (이전 tread1121c). pool 15 연결마다 6번째 실행을 넘긴 뒤에도 p95가 custom plan 범위(147–191 ms)라 연결 나이와 무관하다.
  다른 case는 오차 범위(zoom 14 122/185 → 92/118, 부산 맛집 435/538 → 437/543). acceptance 마지막 항목을 닫고 tasks-done으로 옮겼다.
- `T-READ-06` **기준 미달 보류, 브랜치 보존**: `feat/t-read-06-search-keys`(`8ecb449e`, alembic 455 시절, 미머지)는 순서
  동등(평가 묶음 63개 × 3페이지)을 보였지만 운영 사본 부산 맛집 p50 감소가 −25.7%·−24.9%로 40% 기준 미달이다. main에는
  들어가지 않았으므로 revert할 것이 없고 브랜치는 지우지 않는다. 기준 조정 머지 여부는 소유자 결정 — tasks.md 보류 항목으로 옮겼다.
- `T-READ-07` 정정: 2026-11-19 기록의 "첫 스냅샷 미촬영"은 틀렸다. 첫 스냅샷은 2026-11-18 23:02Z(t1118e)에 읽기 전용으로
  찍었다(`features` heap 397 MB·색인 756 MB, HOT 갱신 0/59,249). 둘째는 2026-12-03 무렵.
- `T-READ-02`는 acceptance 마지막 항목(운영 `slow_request` 줄)이 2026-11-19에 이미 닫혀 있고 tasks-done에 있다 — 바꾼 것 없음.
- journal이 215,784 B로 §8의 200 KB 경계를 넘어 있어 2026-10-24~28의 완전한 절 91개를
  [journal-2026-10j.md](archive/journal-2026-10j.md)로 원문 그대로 옮겼다(상대 링크만 재기준화, 역변환으로 원래 구간과 바이트
  일치 확인). live에는 제목 stub을 남겼다.

## 2026-11-22 — 관리자 nav 라벨 = 페이지 제목(SSR 제목 깜빡임)·페이지 경계 버튼 비활성 사유

- 증상: #1533 뒤 서버 렌더 첫 화면의 상단 바 제목은 nav 정본 라벨이고, hydration 뒤에는 페이지가 `AdminPageTitle`로 등록한
  제목이다. 네 화면이 달라 첫 화면에서 제목이 한 번 바뀌었다(`/` 홈→운영 홈, 수동/provider 판정→수동/provider 중복 판정,
  큐레이션 후보→큐레이션 후보 검토, 캐시 전파→캐시 전파 스트림).
- 고침: nav 라벨을 더 설명적인 페이지 제목에 맞췄다(390px drawer·rail에 한 줄로 들어간다). 단위 시험
  `admin-nav-titles.test.ts`가 nav 21개 항목마다 `page.tsx` metadata 제목과 그 화면 `<AdminShell>`의 정적 `title`이 nav 라벨과
  같은지 소스에서 확인한다(찾지 못하면 실패).
- 페이지 경계 버튼(첫 페이지·이전·다음·마지막 페이지)은 native `disabled`라 왜 안 눌리는지 말하지 못했다. 공용 `PagerButton`을
  `focusableWhenDisabled` + 사유("첫 페이지입니다"/"마지막 페이지입니다", 전체 페이지 수 미상)로 바꿔 모든 `OffsetPager`·
  `CursorPager`에 적용했다. 경계에 닿아도 방금 누른 `다음`이 포커스를 잃지 않는다. Playwright `toBeDisabled()`는
  `aria-disabled`도 비활성으로 읽어 기존 계약은 그대로다.
- 시험: e2e `admin-shell.spec.ts` 네 화면의 SSR HTML h1 = hydration 뒤 h1(파서 삽입부터 MutationObserver로 기록한 제목이
  하나뿐), `ops-pipeline.spec.ts` 타임라인 경계 버튼 `aria-disabled`·접근성 설명·tooltip·포커스 유지. OpenAPI·migration 없음.

## 2026-11-22 — 관리자 셸을 루트 레이아웃으로: drawer 이동 뒤 포커스가 BODY로 떨어지던 결함

- 증상(n150 prod 390px 점검): drawer 메뉴를 클릭·Enter로 이동하면 포커스가 `#main-content`가 아니라 BODY. 클릭 때는 약
  200 ms 동안 옛 화면의 main에 머물다 BODY로 떨어졌다.
- 원인: 페이지 client 24곳이 각자 `<AdminShell>`(공통 `AdminShell` 래퍼)을 그렸고 루트 `layout.tsx`에는 셸이 없었다. 경로가
  바뀌면 셸 트리 전체가 다시 마운트된다. 공통 0.2.4 `useDrawer`의 `returnToMain`은 셸 내부 state라, 옛 셸이 drawer 닫힘
  애니메이션(~200 ms) 뒤 `onCloseAutoFocus`로 **옛** main에 포커스를 주고 곧 그 노드가 사라져 BODY가 된다. 공통 셸은
  레이아웃 배치(`navigationKey` + `AdminPageTitle`)를 이미 지원하므로 공통 릴리스는 필요 없었다.
- 고침: `AdminShellFrame`(공통 셸 + 메뉴·브랜드·로그아웃, `navigationKey={pathname}`, SSR 첫 제목은 nav 정본 영역·라벨)을
  루트 레이아웃에 한 번 둔다. `/login`은 셸 없이. 페이지 `AdminShell`은 props 그대로 `AdminPageTitle`로 제목·설명·동작을
  등록하고 본문 여백·meta 줄만 그린다 — 페이지 파일 24곳은 바꾸지 않았다. design.md에 배치 규칙을 적었다.
- 시험: Playwright `admin-shell.spec.ts` 390px drawer 이동(클릭·Enter) 뒤 애니메이션 종료를 기다려 `expect.poll`로
  `document.activeElement`가 `#main-content`이고 셸 노드가 그대로인지 본다(고치기 전 빨강 확인). vitest는 셸 노드·main이
  경로 변경 사이에 같은 노드인지, `/login`은 셸이 없는지. OpenAPI 변경 없음. 배포하지 않았다.

## 2026-11-21 — 관리자 프런트 소수정 셋: drawer e2e flake·모바일 44px 터치 표적·파이프라인 비활성 사유

- `admin-shell.spec.ts` "mobile: 메뉴 버튼이 좌측 drawer를…"의 간헐 실패는 drawer `slide-in-from-left` 도중 `boundingBox().x`를
  잰 것이다(x<0). `data-state=open` → `getAnimations()` finished → `expect.poll(x)==0`으로 바꿨다(임의 sleep 없음).
- 모바일(md 미만) 상단 바 동작은 라벨이 숨어 32px 아이콘 버튼이었다. 셸 동작 래퍼(`map-shell-actions`)와 icon 크기 Button에
  `max-md:min-h-11 max-md:min-w-11`(44px)을 걸었다 — 데스크톱은 h-8 그대로. 메뉴 버튼·drawer 닫기는 공통 셸이 이미 44px.
- `Button`에 opt-in `focusableWhenDisabled`: 사유(`disabledReason`)가 있는 비활성을 native `disabled` 대신 `aria-disabled`로
  두고(활성화는 onClick에서 막음) hover/focus tooltip + 상시 `aria-describedby`(sr-only 형제)로 사유를 노출한다. 파이프라인
  페이지 동작 버튼(헤더 갱신 요청 생성·요청 dialog·스케줄 명령/cron/claim·실행 취소/run-now)에 적용하고 스케줄 잠금
  사유(`scheduleControlsDisabledReason`)를 채웠다. 다른 화면은 그대로(native disabled + `title`).
- 시험: vitest `button.test.tsx`(icon 크기 min-size·opt-in 의미), Playwright 모바일 44px·데스크톱 32px, 파이프라인 사유
  tooltip/설명(`toHaveAccessibleDescription`). OpenAPI 변경 없음. 배포하지 않았다.

## 2026-11-21 — T-READ-12 저배율 집계가 연결 6번째 실행부터 generic plan으로 뒤집힘

- 증상(운영 읽기 전용 조사): `/v1/features/in-bounds` zoom 7 sido 집계(pg_stat_statements queryid
  -1199203723901693282, API mean 480 ms·stddev 370)가 정상상태 ~630 ms, 꼬리 1–4 s, read_timeout 503 하나.
- 원인: asyncpg는 집계 SQL을 연결마다 prepared statement로 재사용하고 `plan_cache_mode=auto`는 6번째 실행부터
  generic plan을 고려한다. generic plan은 bbox 선택도를 기본값으로 봐(rows=1) `idx_feature_cluster_points_coord_gist`
  직렬 scan을 고른다(685–902 ms). custom plan은 Parallel Seq Scan + HashAggregate(147–191 ms). 세션에서
  `force_custom_plan`이면 146–154 ms, 계획 비용 약 7 ms. harness·tier-1 gate는 매번 `EXPLAIN`으로 계획해 이 전환을
  볼 수 없었다.
- 고침: `_CLUSTER_HASH_AGGREGATE_ON_SQL`/`_OFF_SQL`이 `enable_sort`와 같은 문장에서 `plan_cache_mode`를
  `force_custom_plan`으로 두고(transaction-local) 집계 뒤 직전 값으로 되돌린다. harness·tier-1 gate는 같은 상수를
  import하므로 그대로 따라온다. `scripts/read_path_probe.py`에 case별 warm-up(`--warmup-per-case`, 기본 6 × pool 15 =
  90, 분위에서 제외)을 더해 결과가 연결 나이에 흔들리지 않게 했다.
- 시험(n150 gate-slot, testcontainers pg18): 같은 연결에서 sido 집계 8회 뒤 그 prepared statement의 `generic_plans`가
  0이고 EXPLAIN이 HashAggregate·좌표 GiST 없음(전 kind·point-only 두 변형). 고침을 되돌리면(`force_custom_plan` →
  `auto`) 두 변형 모두 `generic_plans` +3·`custom_plans` +5로 빨개진다 — 시드 840행에서도 운영과 같은 6번째 전환이
  재현된다. 관련 통합·probe unit 19 passed.
- 다른 hot 질의 점검(운영 읽기 전용, 2026-11-21 10:39Z, io-guard 0, pg 18.6, `SET LOCAL ROLE ktm_feature_service`,
  harness viewport의 SQL·인자를 SQL `PREPARE` 뒤 같은 연결에서 auto 8회 + `force_custom_plan` 4회, 중앙값 ms):
  sido point-only 108 → **953**(6~8회 1,519·953·620, 강제 custom 114), sido 전 kind 222 → **654**(강제 172) — 고친 대상.
  items in-bounds(같은 `_FEATURES_IN_BBOX_SQL`)는 6번째부터 generic(Nested Loop, `idx_features_coord_gist`)을 고르지만
  갈린다 — 서울 zoom 14 500건은 172 → 83(generic이 더 빠름), 서울 밀집 200건은 52 → 79(6번째 1회 536). 같은 prepared
  statement를 두 화면이 나눠 쓰므로 강제하면 한쪽이 손해라 **고치지 않았다**. 100 km nearby(14/12/11)·카페(146/172/149)·
  부산 맛집(407/429/423)·서울 맛집(166/166/166)은 generic을 한 번도 고르지 않았다(custom 비용이 더 낮다).
- OpenAPI·migration 변화 없음. 배포하지 않았다(부모 통합 회전).

## 2026-11-21 — 관리자 프런트 ui 0.2.4(TabsTrigger focus 정본화)와 Map 탭 override 제거

- `@kor-travel/ui` 0.2.3→0.2.4·tokens 0.1.4→0.1.5(common #79, main pack `9691080c`, docs run 44882394234 artifact
  14698374408; sha256·SRI가 catalog #80과 같음)를 vendor하고 guard·`common-ref`를 `c3f8e6a1`로 올렸다. toast 0.1.4는
  Map이 쓰지 않아 받지 않았다(0.2.3 채택 때와 같음). ui·tokens 의존 목록은 그대로이고 ui peer만 tokens 0.1.5다.
- 공통 0.2.4 TabsTrigger focus가 FS-7.8 단일 outline 2px·offset 2px(`outline-kt-focus`)가 되어 Map
  `components/ui/tabs.tsx`의 0.2.3용 덧대기(`focus-visible:border-transparent`·`ring-0`·`outline-focus`·전환 좁히기)를
  지우고 공통 Tabs를 그대로 다시 내보낸다.
- 시험: vitest `tabs.test.tsx`는 트리거의 `focus-visible:` 변형이 정확히 `outline-2`·`outline-offset-2`·`outline-kt-focus`
  셋이고 ring 유틸·`transition-all`이 없음을 본다. Playwright `admin-shell.spec.ts` 탭 포커스 검사에 테두리 색 불변을 더했다.
- Map admin OpenAPI 변경 없음. 배포하지 않았다(부모 통합 회전).

## 2026-11-21 — T-READ-11 검색 접기 대표 판정이 hashed SubPlan으로 뒤집힌 회귀("부산 맛집" 382→575 ms)

- 증상: n150 prod "부산 맛집" 서버 p50이 기준선(T-READ-01) 382 ms에서 575 ms로 올랐다. 코드 변경이 아니라 계획 변경이다.
- 원인(읽기 전용 EXPLAIN ANALYZE): `dedup_ordered`의 MCST 판정 `EXISTS (…)`를 Postgres가 `ANY`로 바꿔 hashed SubPlan
  대안을 함께 만들고, `source_links`/`source_entities` autoanalyze 뒤 hashed 쪽을 골랐다 — 질의마다 MCST primary
  88,526행 전부로 해시를 지었다(~176 ms). 실제로 판정이 필요한 행은 무리가 둘 이상인 소수다.
- 고침: 판정을 상관 스칼라 부분질의 `(SELECT true … LIMIT 1) IS NOT NULL`(`_SEARCH_DEDUP_DEMOTED_PRIMARY_SQL`)로 —
  LIMIT 스칼라 부분질의는 hashed SubPlan이 될 수 없어 행마다 `source_links` 인덱스로 찍는다. 읽기 전용 실측:
  부산 맛집 585 → 383 ms(같은 51행), 서울 맛집 144 → 157 ms(+13, 수용). OpenAPI·migration 변화 없음.
- 시험: 종전 `EXISTS`로 되돌린 SQL과 같은 행·같은 순서(통합), 판정 SubPlan이 hashed가 아님(계획 모양, 통합).
  함정: pg18 `EXPLAIN (FORMAT JSON)`의 `Subplan Name`에는 "hashed"가 없다 — hashed는 그 SubPlan을 참조하는 식에만
  `(hashed SubPlan N)`으로 찍힌다. 이름만 보던 첫 판은 종전 `EXISTS`에도 초록이었다(n150에서 빨개지게 해 보고 발견).
  고친 판은 VERBOSE 식 참조를 보며, 종전 `EXISTS`는 이 시드에서도 hashed로 계획되어 빨개진다.

## 2026-11-21 — CI 통합 job 35% 정체(6시간 취소)의 원인: nearby 동등성 시험의 통계 공백 + 강제 계획 실행

- 증상: `pytest integration (PostGIS, pg18)`이 `01b602e3`(#1523)부터 35% 줄 뒤에 멈춰 6시간 뒤 취소(run
  44632917554·44667945938, 그리고 다음 push로 취소된 44806776288도 같은 자리에서 1시간 45분 정체). 통과한
  런도 같은 구간(전체 1,815건 중 649~720번)이 **17~23분** 걸렸다 — #1520(T-READ-09, `2e58b828`)부터. 그 전
  (#1519·454)은 1.5분. 즉 #1522(455 trigger·병렬 집계)가 아니라 #1520이 들인
  `tests/integration/test_features_nearby_equivalence.py`가 출처다. #1523은 우연히 겹쳤다.
- 재현(n150, CI와 같은 한 세션 전량, `--durations`, 60초마다 `pg_stat_activity`·`pg_locks` 스냅숏): KNN 시험
  581초, coord page walk 543초, target walk 166초 — 이 셋이 CI의 17~23분이다. 정체 동안 **대기 잠금은 0건**,
  backend는 `active`로 CPU를 썼다 — lock wait·deadlock이 아니다.
- 원인: 그 시험의 `_seed`가 provider 계보 표(`source_links`·`source_entities`·`source_entity_heads`·
  `source_records`)와 `feature_notices`에 1천여 행씩 넣고 `features`만 ANALYZE했다. 세션 DB에서 그 표들은
  한 번도 분석되지 않아(`reltuples = -1`) planner가 행 수를 1로 본다. 그래서 공개 notice 감산 subplan을 색인
  조건 없는 중첩 루프(`pk_source_entity_heads`를 filter로 66만 번 훑기)로 풀었고, 같은 파일의 앞 시험들이
  남긴 상태에서 **행 11개 page 한 문장이 130초**(2.9억 buffer hit)였다(기본 planner 설정, EXPLAIN ANALYZE 실측).
  KNN 시험은 거기에 `enable_seqscan/bitmapscan = off`를 걸고 그 강제 계획을 **실행**했다 — 모든 표의 접근
  경로가 비틀린 계획이라 n150에서 문장 하나 4분+, CI에서는 끝나지 않았다. 비용이 앞 시험이 남긴 표 상태에
  따라 세제곱으로 커져 간헐적이었다.
- 고침: ① `_seed`가 쓴 표 전부를 ANALYZE(transaction 안 ANALYZE는 자기 미commit 행을 센다). ② KNN 시험은
  강제 스위치 아래 계획을 세우기만 하고(실행 안 함) "KNN scan 바로 위가 `Limit`"으로 조기 정지를 본다 —
  후보의 `FETCH FIRST … WITH TIES`를 지우면 빨개지는 것을 확인했다. ③ CI 통합 job에 시험 하나 600초
  (`pytest-timeout`, thread 방식 — 이름과 stack을 찍고 끝낸다)와 job 90분 상한, 수동 PostGIS workflow도 같은
  시험 상한. 결과(n150): coord walk 543→4.3초, target 166→4.1초, KNN 581→0.7초.
- 제품 SQL은 바꾸지 않았다 — 운영 DB는 통계가 있다. 같은 모양(행마다 도는 notice 감산)이 통계 없는 표에서
  무너진다는 것은 시험 시드가 큰 표를 새로 채울 때 함께 ANALYZE해야 한다는 뜻이다.
- 이 절로 journal이 225,297 B가 되어 §8 경계를 넘었다 — 2026-10-24의 완전한 절 23개를
  [journal-2026-10i.md](archive/journal-2026-10i.md)로 원문 그대로 옮겼다(상대 링크만 재기준화, 옮긴 조각과
  원래 구간 바이트 일치 확인). live에는 제목 stub을 남겼다.

## 2026-11-21 — C7 prod GREEN(t1121b, Map `24ffd5a2`) — 네 spec 전부 통과

- 결과: runner rc=0, lane 잔여 없음(audit rc=0), evidence `run-20261120T230130Z-3626497`. spec별 —
  `ops-c7-read-auth` 7/7, `poi-cache-targets-write` @c7-causal 2/2, `ops-c7-update-request-write` 2/2,
  `ops-c7-schedule-write` 2/2. 마지막 GREEN(`bafec797`, 10-03) 이후 첫 GREEN이다.
- 이번 회차에서 고친 것: #1524(파이프라인 "새로고침" 둘 — 공통 Dagster 패널), #1525·#1526(logout 순서가
  acde3726부터 "성공 응답 뒤 close(1000)" — 관측점을 close 호출 기록으로), 그리고 **운영 설정** 하나 — C7의
  `/root/.d2-dagster-basic-auth`가 2026-10-01 값이라 gateway가 401을 냈다(소유자가 10-24 Dagster UI 비밀번호를
  바꿈). 현재 `.env`의 `KOR_TRAVEL_DAGSTER_UI_PASSWORD`로 다시 썼다(root 0600 한 줄, 옛 파일은 `.bak-<UTC>`).
  Dagster UI 비밀번호를 바꾸면 이 파일도 같이 바꿔야 한다.
- 복구: BLOCKED 네 번(t1120b·t1120c·t1121a·t1121b) 모두 runbook §4로 — journal·sentinel을 root 전용
  `/root/c7-recovery-<tag>-<UTC>/`로 복제·SHA-256 기록, 읽기 전용 검증(C7 소유 target 0, schedule RUNNING,
  활성 실행 0) 뒤 runtime·BLOCKED를 그 디렉터리로 **이동**(삭제 없음). 운영 쓰기는 매번 target `restored`.
- 회전: t1120c(`db8497f2`)·t1121a(`9663598b`)·t1121b(`24ffd5a2`), 모두 chain17 + freeze, D1·D2 GREEN, PinVi `716781d0` 그대로.
- 남은 것: main CI의 `pytest integration (PostGIS, pg18)`이 `01b602e3`(#1523)부터 35% 지점에서 6시간 멈춘다
  (#1522 `c5bae138`까지는 통과, #1523은 Python 변경 없음 — 간헐 hang 추정, 원인 미규명). #1524~#1526은 그 위에서 병합했다.

## 2026-11-21 — C7 t1121a: logout 관측점을 `close()` 호출 기록으로(#1525 방식은 page 평가가 막힘)

- #1525(t1121a, Map `9663598b`) 뒤에도 `LAST: 실제 로그아웃` 1건 실패(38.4초, 나머지 6건 GREEN, target `restored`).
  #1525는 /login 문서 이동을 `page.route`로 붙잡고 그 사이 옛 문서에서 close code를 읽으려 했는데, **문서 이동을 붙잡은
  동안에는 page 평가가 진행되지 않는다**(자체 세션 probe: close 대기 5초 timeout, redirect 미완).
- 붙잡지 않으면: logout 응답 200 뒤 24 ms에 /login 문서가 commit되어 close handshake가 끝나기 전에 문서가 바뀐다 —
  JS `close` 이벤트도 Playwright `close` 이벤트도 옛 문서에서 나지 않는다. 결정적인 사실은 앱이 redirect **전에 동기로**
  `close(1000)`을 부른다는 것.
- 고침: init script가 `WebSocket.prototype.close`의 ops live 호출을 같은 탭 sessionStorage에 남기고(click 전 비움),
  /login 도착 뒤 읽는다. 단언은 logout 응답 ok·close 호출 code 1000·|호출−응답| ≤ 2초·ticket/socket 재생성 없음.
  자체 세션 probe로 동일 기제 확인(close 호출 1000, 응답과 -2 ms, 31초 동안 재연결 0).

## 2026-11-21 — C7 t1120c: read-auth 6/7, 마지막 logout 시험은 spec의 순서 가정이 낡음

- #1524 배포(t1120c, Map `db8497f2`) 뒤 C7 `ops-c7-read-auth` 7건 중 6건 통과(count/state·4401·4408 복구·rotation·
  projection 복원 모두 GREEN), `LAST: 실제 로그아웃` 1건이 7.2초에 실패. 운영 쓰기는 target 하나가 `restored`로 끝났다.
- 원인: `acde3726`(2026-10-05)이 로그아웃 순서를 "socket close → logout POST"에서 "logout POST **성공 뒤**
  `publishAdminLogout`(close 1000) → /login"으로 바꿨다(실패한 logout은 live를 유지하고 재시도). spec은 logout
  **응답을 붙잡고** close를 기다려 교착 → 5초 뒤 route handler throw. 마지막 C7 GREEN(`bafec797`, 10-03)은 그 이전이다.
- 고침(spec만): logout 요청은 건드리지 않고 `/login` 문서 이동을 잠깐 붙잡아 옛 문서에서 close code 1000을 읽는다.
  단언은 logout 응답 ok·redirect 전 close 1000·응답 뒤 close 지연 ≤ 2초·ticket/socket 재생성 없음.

## 2026-11-20 — C7 `ops-c7-read-auth` 첫 시험 5초 실패: 파이프라인 화면의 "새로고침" 둘

- t1120b(Map `01b602e3`) C7 첫 시험이 5.06초에 실패했고 나머지는 serial이라 건너뛰었다(journal 모두 `*_pending`, 운영 쓰기 없음).
  기대 시간 상한(15초)보다 짧아 재시도 없는 실패, 즉 strict locator 위반이다.
- 운영 UI에 읽기 전용 Playwright probe(C7 실행 이미지, 로그인·화면 이동·GET 새로고침만)로 재현: 데이터셋 요약·딥링크·
  파이프라인 h1은 모두 통과, `/ops/pipeline`에서 `getByRole("button", { name: "새로고침", exact: true })`가 **2개** —
  상단 바 동작과 실행 탭의 공통 Dagster 운영 패널(`@kor-travel/ui` DagsterOperations, `data-slot="dagster-operations-refresh"`).
- 그 패널은 2026-10-05 `acde3726`에서 들어왔고 마지막 C7 GREEN은 그 전(`bafec797`, 10-03)이라 이번이 그 뒤 첫 C7이었다.
  #1523(공통 AdminShell)의 원인이 아니다. 고침: spec의 새로고침 세 곳을 공통 셸 `data-slot="admin-shell-actions"` 안으로
  한정(`shellRefreshButton`). probe로 두 화면 모두 1개·enabled 확인.
- 남은 일: C7 lane은 BLOCKED 그대로(runbook §4 복구는 소유자), 다음 회전에서 C7 재실행.

## 2026-11-19 — 관리자 프런트 공통 AdminShell(ui 0.2.3) 채택과 버튼 테두리(FS-7.8)

- `@kor-travel/ui` 0.2.1→0.2.3·tokens 0.1.2→0.1.4(common #70·#71, main pack `0e2a3f5a`, SRI는 원장과 같음)를
  vendor하고 guard·`common-ref`를 `d644632e`로 올렸다. toast는 Map이 쓰지 않아 받지 않았다. 0.2.2의 VirtualTable
  변경은 바깥 `min-w-0` 한 줄이다.
- 자체 rail·헤더 셸(`components/admin-shell.tsx`)을 공통 `AdminShell`+`AppMenu`로 바꿨다. lg 이상은 좌측 rail(접힘 키
  `kor-travel-map:sidebar-collapsed`, 기존 "1"/"0" 유지), 그 아래는 상단 바 메뉴 버튼 → 좌측 drawer다(예전엔 메뉴가
  상단 가로 띠로 펼쳐졌다). 맨 위는 한 줄(약 48px) 상단 바: h1 "영역 - 페이지"(영역 = nav 그룹, 홈은 "개요"), 페이지
  설명은 같은 줄에 작게(말줄임, 전체 문장은 title), 동작은 오른쪽 — md 미만에서는 라벨을 숨긴 아이콘 버튼
  (`ShellActionLabel`, 접근성 이름 유지). 워드마크 옆 "admin" 같은 앱 설명은 지웠고 breadcrumbs(2화면)는 상단 바에
  들어가지 않아 없앴다(같은 목적지가 동작 버튼에 있다). 여러 값 요약(`meta`: 백업 저장소·데이터셋 상태)은 본문 맨 위 한 줄.
- nav 정본을 `lib/admin-nav.ts`로 분리하고 페이지 metadata를 "영역 - 페이지 | kor-travel-map"으로 맞췄다. 공통
  `formatAdminTitle`은 `"use client"` 모듈이라 서버 metadata에서 부를 수 없어 같은 규칙을 로컬에 두고 시험으로 둘을 묶었다.
- 버튼 테두리 원인: Map `buttonInteractionClasses`의 **조건 없는 `outline-solid`**. 0.2.1 공통 recipe의
  `outline-none`을 이기려고 붙였는데, twMerge가 `outline-none`을 지운 자리에서 `outline-style: solid`가 상시로 남아
  모든 버튼에 기본 폭(medium = 3px) currentColor outline이 그려졌고, 포커스 때는 그 위에 `focus-visible:border-ring`
  색 테두리까지 겹쳤다. 0.2.3 공통 recipe가 focus를 outline 2px·offset 2px(`--kt-focus`)로 직접 내므로 Map 덧대기
  (`outline-solid`·`focus-visible:outline-*`·`ring-0`)를 모두 지우고 disabled 도달성(`disabled:opacity-100
  disabled:pointer-events-auto`)만 남겼다. globals.css에는 unlayered 버튼 상태 규칙이 없었다(`@layer base`의
  `:focus-visible` 하나와 `font: inherit`만). 옛 `.map-common-menu[data-collapsed]` 접힘 CSS는 AppMenu `compact`로 대체.
- 시험: vitest `admin-shell.test.tsx`(제목 형식·설명·meta·help·nav 21·접힘 키 형식·drawer 열고 링크로 닫힘),
  `admin-nav.test.ts`(공통 함수와 같은 문자열·영역 유도·문서 제목), `button.test.tsx`(7변형 모두 focus outline 한 벌·상시
  outline·ring 없음). Playwright `e2e/admin-shell.spec.ts`(PC 1280·모바일 390: 상단 바 한 줄·작은 설명·문서 제목, 모바일
  drawer 열기·닫기 버튼·메뉴 이동 뒤 닫힘·좌측 x=0·폭 ≤ 280, 쉴 때 outline 없음·Tab 2px 하나·누를 때 테두리 불변,
  모바일 아이콘 동작), `home-nav.spec.ts` 뷰포트 시험을 rail/drawer 기준으로 갱신.
- Map admin OpenAPI 변경 없음. 배포하지 않았다(부모 통합 회전).

## 2026-11-19 — T-READ-10 후속: 좁은 집계 표(alembic 455), T-101 재개

- 소유자 지시(2026-11-19): "전국 시도·전 종류 1,214 → 705 ms, 추가 개선", 목표 p50 < 300 ms. 같은 날 "사전집계도 허용" —
  **T-101 제외(2026-09-07)를 해제**했다. 제외 원문: "하지 않는다. 재개하려면 목표 SLO 정의와, exact-viewport(ADR-073
  accepted 계약) vs region-total 의미 택일이 선행한다 — 후자는 ADR 개정과 PinVi 소비자 계약 변경을 함께 부른다."
  이번 구현은 region-total이 아니라 exact-viewport를 그대로 지키므로 ADR-073·PinVi 계약을 건드리지 않는다.
- 후보 실측(n150 합성 42만 행, 반복을 교차해 잰 p50, 454 기준 약 700 ms):
  - 병렬 집계 — 공개 notice 감산 fragment(상관 subquery)가 scan을 parallel restricted로 묶는다. fragment는 notice가
    아닌 행에서 항상 참이라 notice 몫을 떼면 `Gather → Partial HashAggregate`가 된다. 단독으로 716 → 476 ms, point-only
    266 → 144 ms. 남은 비용은 route 5.8만 행의 `features` PK 조인과 넓은 route heap.
  - (b) 좁은 집계 표 + 병렬 — **채택.** 255 ms(아래).
  - single-pass(features 한 번 + geometry hash join) 611 ms, `parallel_*_cost` 조정·`max_parallel_workers_per_gather` 3 —
    이득 없음(기본값으로 병렬 계획이 나온다). work_mem — 묶음 20~3,500개라 HashAggregate가 기본 64 MB 안에 든다.
  - (a) 데이터 버전 캐시 — 버리지 않았지만 하지 않았다: 집계 결과는 `features`·subtype·`source_links`(provider 필터)·속성
    표·notice(시각) 모두에 달려 값싼 무효화 버전이 없고, harness가 재는 SQL을 줄이지 못한다. 좁은 표로 목표에 닿았다.
  - region rollup(지역별 사전 합계) — 좁은 표로 255 ms에 닿아 더 얹지 않았다(부분 포함 지역의 정확 계산·합계 drift 관리
    비용이 크다).
- 구현: `feature.feature_cluster_points`(Feature당 한 행: kind·category·지역 코드·coord·공개 3축 곱 `public`, route/area
  대표점·정확 범위, 범위 사각형 생성 컬럼) + AFTER ROW trigger 셋(`features` INSERT/관련 열 UPDATE/DELETE,
  route/area INSERT/`geom` UPDATE/DELETE). 각 trigger는 자기 몫 열만 upsert — core와 geometry를 두 transaction이 동시에
  바꿔도 둘 다 남는다. 집계는 (1) notice 아닌 point + bbox 안 route/area(병렬) (2) bbox를 가로지르는 route/area(실제
  geometry, MATERIALIZED) (3) notice(공개 view + fragment)로 묶어 (개수, 좌표 개수, 경도 합, 위도 합)을 합친다.
- 반영 시점: **동기식(지연 0)** — 쓰기 transaction 안에서 이미 맞는다. `tests/integration/test_cluster_points_sync.py`가
  좌표·지역 코드·분류·공개 3축·geometry 갱신/삭제/재삽입·Feature 삭제(cascade)마다 좁은 표 = migration backfill 식,
  집계 = 종전 SQL을 확인한다.
- 실측(n150 합성, 15회 교차 p50; 종전 → 454 → 455):

  | 질의 | 종전 | 454 | 455 |
  |---|---|---|---|
  | 전국 sido 전 kind | 1,297 ms | 711 ms | **255 ms** |
  | 전국 sido point-only | — | 254 ms | **107 ms** |
  | 수도권 시군구 전 kind / point-only | 146 / — ms | 128 / 92 ms | 66 / 37 ms |
  | 서울 읍면동 전 kind / point-only | 106 / — ms | 65 / 92 ms | 39 / 29 ms |

  전국 255 ms 중 약 140 ms는 합성 데이터의 bbox를 가로지르는 route 32개(2만 점짜리 포함)의 실제 교차 계산이다 — prod는
  전국 bbox를 가로지르는 route/area가 4개(2026-11-19 읽기 전용 조회)라 더 낮을 것으로 본다. 동등성: 개수 일치, 평균 좌표
  차 최대 2e-12도.
- 쓰기 영향(n150 합성, 같은 문장을 trigger 켜고/끄고, transaction rollback, 2회): 좌표를 바꾸는 50,000행 UPDATE 7.0~7.4 →
  10.2~10.9 s(+약 40%), 집계와 무관한 열만 바꾸는 50,000행 UPDATE 7.4~7.8 → 7.1~8.1 s(차이 없음 — trigger가 바로 돌아간다),
  INSERT 20,000행 2.2~2.6 → 2.7~2.9 s(+약 10~30%).
- HOT(T-READ-07): `features`에 열·색인을 더하지 않았다. 위 UPDATE 모두 trigger 유무와 관계없이 HOT 0(종전에도 0 —
  `updated_at` 색인). 큐레이션 해시: `features`·subtype 행이 바뀌지 않고 새 표는 어떤 `to_jsonb` 입력에도 없다.
- migration 455(합성 42만 행, tmpfs): 표·함수·trigger 수 ms, backfill 2.1 s, GiST 두 개 0.8 s, ANALYZE 0.4 s. 크기 92 MB
  (heap 58 MB). trigger 생성의 `SHARE ROW EXCLUSIVE`가 commit까지 세 표의 쓰기를 막는다 — prod(디스크)는 10~20 s로 본다.
  적재를 멈춘 뒤 배포한다.
- 적대 리뷰(1회): High 없음. Medium — 상태 전이(features → subtype → 새 표)와 geometry 갱신(subtype → 새 표)의 잠금 순서
  역전으로 deadlock 가능 → `features` trigger 이름을 `trg_features_zz_cluster_point`로 두어 subtype 동기화 뒤에 돌게
  고쳤다. notice·분류 필터·backfill 결합 시험 부족 → 보강. 남긴 Low: SERIALIZABLE 도메인 명령과 같은 Feature의 동시
  geometry 갱신이 새 표 행에서 40001을 낼 수 있다(재시도 대상), area 대표점은 쓰기 때 저장되므로 GEOS 판올림 뒤 새로 계산한
  값과 마지막 자리가 다를 수 있다(454의 route와 같다). TRUNCATE는 문장 trigger로, 복제 역할(`session_replication_role =
  replica`)은 trigger `ENABLE ALWAYS`로 덮었다(CI 통합 런에서 정리 도우미가 남긴 어긋남으로 드러났다). trigger 함수의 PUBLIC
  실행권은 걷었다(런타임 SECURITY DEFINER preflight). `ALTER TABLE … DISABLE TRIGGER`로 이름을 지목해 끄는 경로만 남는다.
- 배포하지 않았다(소유자 묶음 회전).

## 2026-11-19 — T-READ-09 100 km nearby: LATERAL을 page 뒤로, 거리순은 KNN

- 진단(prod `map-api` 컨테이너 안 읽기 전용 트랜잭션, `jit=off`, 몇 회만): "100km nearby"(서울시청, place, 51행) 5.4초 중
  **5.0초가 primary source LATERAL**이었다 — 반경 안 201,401행마다 `source_links→source_entities→provider_datasets→heads→
  records` 5단 join + 정렬을 돌고 나서 51행을 잘랐다. 반경 scan 자체는 0.27초.
- 고친 것(`feature_repo._nearby_sql`, 좌표·by-target 공용):
  1. primary source LATERAL은 `LIMIT`로 잘린 page 행에만 붙인다. provider 필터는 같은 선택 규칙의 상관 subquery(필터가
     있을 때만 돈다).
  2. 거리순 page는 GiST KNN이다. `distance_m`을 `<->`로 계산한다 — PostGIS 3.6의 `<->`(`geometry_distance_centroid`)는
     `ST_Distance`와 **같은 C 함수**(prosrc `ST_Distance`)라 값이 같다. KNN은 정렬 키가 하나일 때만 생기므로(PG18) 후보
     subquery를 `ORDER BY distance_m FETCH FIRST (:limit_plus_one) ROWS WITH TIES`로 자르고 바깥에서 `(distance_m,
     feature_id)`로 다시 정렬한다. WITH TIES가 n번째 거리와 같은 행을 모두 남겨 동률 tiebreak가 종전과 같다.
  3. 반경 술어는 `ST_DWithin` 대신 그것이 펼쳐지는 `&& ST_Expand` + `<-> <= 반경`으로 쓴다. 종전 계획은 `ST_DWithin`
     filter 뒤 20만 행을 27행으로 추정했다(펼친 술어는 50,814행 — 실측 201,401에 훨씬 가깝다). 추정이 틀리면 planner가
     KNN과 bitmap을 잘못 견준다. 두 술어가 갈리는 (행, 반경) 쌍은 prod 133만 쌍 중 0,
     통합 시험(경계 반경 포함)도 0.
  - 시행착오: 정렬 키 둘로는 KNN path가 안 생겼고, 후보에 상한이 없으면 바깥 LIMIT이 정렬 너머로 안 전해져 custom plan이
    전 행 bitmap+정렬(377 ms)을 골랐다(generic plan만 KNN 5 ms).
- prod 읽기 전용 EXPLAIN(t1118e, 다른 작업의 I/O가 겹친 창이라 종전 SQL은 기준선보다 느리게 나왔다): 새 SQL "100km nearby"
  p50 **4.5 ms**(종전 기준선 5,200 ms), 100 km 전 kind 4.2, event 57.7, provider 필터 168, 속성 필터 143, route 37.7,
  5 km 4.1(종전 1,107), 1 km 4.0(종전 189), 300 m 3.9(종전 16.6), 100 km 갱신순 3.8, **이름순 1,248**(종전 ≈ 9초 — 반경 안 전
  행 정렬이라 남는다). prepared statement 10회(custom→generic) 14~16 ms(왕복 포함).
- 동등성: `tests/integration/test_features_nearby_equivalence.py`(종전 SQL oracle, page walk 전체)와 prod 읽기 전용 대조
  6묶음 13 page가 전부 같았다. 회귀 가드: page 행 수 이하의 LATERAL loops, KNN 순서 scan 가능, `<->`=`ST_Distance` 함수
  동일성, 구조 unit 시험. harness `matched_rows`는 KNN 상한도 함께 뗀다.
- 운영 배포는 하지 않았다(소유자의 Map 회전에 싣는다). OpenAPI 변화 없음.

## 2026-11-19 — T-READ-10 저배율 집계 단축(alembic 454 + HashAggregate)

- 진단(운영 `map-api` 컨테이너 안, 읽기 전용 transaction·`jit=off`, `EXPLAIN (ANALYZE, BUFFERS)` 몇 번): 전국 sido 전 kind
  집계 1.6 s 중 geometry 후보 CTE 0.68 s — route geometry 5.8만 개(평균 118점, 표 232 MB)를 요청마다 풀어
  `ST_Intersects`·`ST_XMin`…·`ST_PointOnSurface`를 계산하고, 그 5.8만 행을 `pk_features`로 하나씩 조인(0.17 s)한다.
  point arm은 GiST 순서 heap 읽기 34만 행(0.4~0.7 s), 그 뒤 40만 행 **정렬**(GroupAggregate)이 0.1~0.2 s. 지역 코드는
  이미 `features`에 저장돼 있다 — "질의 때 지역 배정"은 원인이 아니었다.
- 수정: ① route geometry STORED 생성 컬럼 다섯(`marker_point`·`geom_xmin`…, 종전 요청 시 식과 같은 식). bbox 안에
  완전히 든 route는 geometry를 풀지 않고 `ST_Intersects`도 건너뛴다(포함 ⇒ 교차). area는 열을 달지 않았다
  (`to_jsonb(area_row)`가 큐레이션 입력 해시에 통째 들어가 해시가 바뀐다, 422행이라 요청 때 계산해도 작다).
  ② 집계 문장 동안만 `enable_sort = off`(`set_config(..., true)` 후 직전 값 복원) — HashAggregate.
- 기각한 것(같은 n150 합성 DB, 반복 교차 p50): `features (feature_id) INCLUDE (kind, category, 코드 셋, coord)` 덮개 색인
  — 조인이 index-only가 되지만 이득 1~6%(911 → 903 ms)라 색인 하나(약 45 MB·쓰기 증폭)를 더할 값이 없다. 시도 키 덮개
  색인 — planner가 고르지 않았다. 한 번에 훑는(single-pass LEFT JOIN) 변형 — 더 느렸다(1.6 s). 지역 묶음 `COLLATE "C"`
  — 정렬은 빨라지지만 HashAggregate보다 작다. 사전 집계·rollup 표 — T-101(2026-09-07 소유자 제외).
- 실측(n150, 합성 42만 행 = place 35만·route 5.77만(평균 129점)·area 422·event 1.5천, tmpfs PG18, 반복 10회 교차, p50):
  전국 sido 전 kind **1,214 → 705 ms**(−42%), 같은 bbox point-only 397 → 250 ms(−37%), 수도권 시군구 전 kind
  145 → 124 ms·point-only 100 → 85 ms, 서울 읍면동 전 kind 90 → 64 ms·point-only 119 → 91 ms. 처음 목표
  "전 kind < 300 ms"는 닿지 않는다(point-only 기준선부터 365 ms) — acceptance 목표를 800 ms/300 ms로 적었다.
- 동등성: `tests/integration/test_cluster_rollup_equivalence.py`가 종전 SQL 사본과 3단위 × bbox 3 × kind 필터 4를 비교한다
  (변에 닿는 route·1e-7도 넘는 route·MBR만 겹치는 route·bbox를 가로지르는 route·구멍 난 area·비공개·코드 없음 포함, geom
  UPDATE 뒤 한 번 더, 요청 경로 함수도). 개수는 정확히 같고 평균 좌표는 1e-9도 안(계획이 바뀌면 float 합 순서만 다르다).
  bench DB에서도 시도·시군구·읍면동 개수 일치, 좌표 차 1e-12도 안팎.
- 다시 쓰기 비용: 합성 route 5.77만 행·153 MB에서 `ALTER TABLE … ADD COLUMN … STORED` 5.1 s(tmpfs, 같은 표 `VACUUM FULL`
  4.7 s). prod에서 다섯 식만 계산하는 읽기 전용 dry run(운영 `map-api` 컨테이너, 병렬 3)이 7.6 s였다(단일 프로세스면
  약 22 s, NULL 결과 0) — 다시 쓰기·색인 재구축을 더해 prod는 30~60 s `ACCESS EXCLUSIVE`로 본다. 그 동안 route/area를 읽는
  요청이 기다린다.
  migration은 `lock_timeout` 5 s·`statement_timeout` 300 s, route 적재가 돌면 실패하고 다시 돌리면 된다. `features`(42만 행)는
  건드리지 않는다(backfill 없음 — 생성 컬럼이 다시 쓰기 중에 채워진다).
- 배포하지 않았다(소유자의 묶음 회전). 운영 반영 뒤 harness로 acceptance를 닫는다.

## 2026-11-19 — T-READ-01 읽기 기준선(조용한 창·적재 중)과 판정

- 소유자 승인(2026-11-19 KST 아침, 예정 창 대신 지금)으로 운영 `map-api` 컨테이너 안에서 harness
  (`--skip-seed --iterations 30`, `jit=off`·`statement_timeout` 30 s·읽기 전용)와 probe(`--iterations 30`)를 돌렸다.
  generation **t1118e**(Map `8e90e56e`). 보고서 [`reports/2026-11-19-read-baseline.md`](reports/2026-11-19-read-baseline.md),
  원자료 `reports/2026-11-19-read-baseline/{quiet,loaded}/`.
  - 적재 중 run(22:37~22:45Z): harness 도중 공용 Dagster run 4개(PinVi telegram planner, transport highway incidents,
    weather current, weather daily summaries)가 시작돼 probe-2와 겹쳤다. PSI io avg60 최대 1.70.
  - 조용한 창 run(22:47~22:54Z): 공용 Dagster schedule·sensor 69개 정지, active run 0, PSI 0.00~0.17. 계획 §8.1의
    30분 사전 관측은 하지 않았다(두 run 내내 PSI < 5%).
- 판정(두 창 같음): `T-READ-05` **채택 안 함**(부산 맛집 전처리 9.53/382.54 ms = 2.5%. 서울 맛집 23.78/143.94 = 16.5%는
  절대 24 ms라 기록만), `T-READ-06` **채택**(이름 정규화 비중 부산 37%·서울 56%, 상수화 변형 matched 1~5행 차이라
  근사값). `T-READ-07`은 14일 간격 스냅샷이 필요하고 첫 스냅샷을 아직 찍지 않았다.
- 새 발견: "100km nearby" 조용 p50 5,200 ms·p95 5,369 ms — 공개 `/v1/features/nearby`(반경 ≤ 100 km)는 `T-READ-03`
  마감 4.5초에 걸려 503이 된다 → `T-READ-09`. "전국 low-zoom cluster(sido, 전 kind)" p50 1,231 ms·p95 1,311 ms →
  `T-READ-10`. 소유자가 `T-READ-06`·`09`·`10` 구현을 승인했고 다른 에이전트가 병렬로 진행 중이다.
- `T-READ-02` 마지막 항목: 2026-11-18 운영 `map-api` 로그(T-READ-02가 실린 t1118a 이후, 지금 t1118e)에
  `slow_request route=/v1/features/in-bounds … duration_ms=6996` 줄들이 있었다 — 닫는다.
- 이관: `T-READ-01`·`02`·`05` → `tasks-done.md`.

## 2026-11-18 — 운영 회전 t1118a·t1118e(T-READ-02·03·04·08 운영 반영)

- **t1118a**(n150 prod, green): Map `7dc2af78` + PinVi `c21d9c5e`. Map 쪽에 `T-READ-08`(alembic 453, `feature.features`
  표 단위 autovacuum)·`T-READ-02`(느린 요청 로그·pool 지표)·frontend Node 26.13.1(#1511, guard ref `0dec954`)이 실렸다.
  D1 40/40, D2 11/11, rankprobe hit@1 35/44·hit@8 41/44.
- **t1118d**(실패, 운영 불변): 후보 빌드에서 pinvi-web BuildKit이 `frontend grpc server closed unexpectedly`로 죽었다.
  활성화 전 단계라 런타임은 t1118a 그대로였다.
- **t1118e**(n150 prod, green): Map `8e90e56e` + PinVi `0a1d90c7`. `T-READ-03` 공개 읽기 요청 마감 4.5초(#1515)와
  `T-READ-04` 교통 `near-batch`(Map #1516 / PinVi #784 재vendor + client)를 한 pair 회전으로 냈고, PinVi #785도 함께
  실렸다. D1 40/40, D2 11/11, rankprobe는 t1118a와 같다(hit@1 35/44·hit@8 41/44).
  배포 뒤 live e2e — desktop 298/299(SRCH-043 flaky, 재실행 2/2 통과), mobile 164/167(CORE-014·015·016이
  `ERR_NAME_NOT_RESOLVED` DNS 순간 장애로 실패, 재실행 통과), firefox core green.
- acceptance: `T-READ-03` 마지막 항목(운영 PinVi가 `T-READ-PIN-04` 머지 commit `c0090296`을 포함 — t1118a의
  `c21d9c5e`, 그 뒤 t1118e로 Map 반영; 두 generation을 여기 적음)과 `T-READ-04` 마지막 항목(PinVi #784 머지 뒤 한 pair
  회전 t1118e)을 닫았다. `T-READ-02`의 "운영 로그에서 1초 넘는 요청 줄 확인"은 아직 적지 않았다(다음 확인 때).
  `T-READ-05`·`06`·`07`은 그대로 조용한 창의 기준선(`T-READ-01`)을 기다린다. `T-READ-08` ③(적재 24시간 뒤 all-visible)도
  측정 창 몫이다.
- 알려진 문제(Map 원인 아님): 2026-11-17부터 `weather_state_forecast_short`가 3시간마다 실패한다. kor-travel-weather
  `/v1/service/exports/forecasts`가 503 `EXPORT_TEMPORARILY_UNAVAILABLE`를 돌려준다. weather 쪽(Codex 담당) 문제이고,
  Map은 실패 시 아무것도 쓰지 않는다(직전 상태 유지).

## 2026-11-18 — T-READ-04: 교통 묶음 근처 조회(`near-batch`) — PinVi 재vendor와 함께 머지

- `POST /v1/service/transport/{fuel-stations,highway-incidents}/near-batch`(service 표면, 같은
  `require_service_token`). 본문 `points[]`(1~60)·`radius_m`(≤ 50 km)·`limit`(≤ 500, 기본 100), 넘으면 422.
  `ValkeyStateStore.nearby_many`가 포인터 `GET` → meta `HGETALL`+점마다 `GEOSEARCH … WITHDIST COUNT limit+1`
  pipeline 하나 → 라우터의 `HMGET` 한 번. 점 수와 무관하게 왕복 셋, 한 세대. id마다 가장 가까운 거리만 남겨
  (거리, id)순으로 자르고 `truncated`는 기존 근처 조회와 같은 뜻이다. Valkey 장애·적재 전은 기존 route와 같은 503.
- **spec이 바뀐다** — service·full OpenAPI(admin `openapi.json`·`openapi.service.json`)에 route 둘과
  `NearBatchRequest`·`NearBatchPoint`가 더해진다(user 불변). 그래서 **머지하지 않았다**: 머지하면 다음 Map 회전부터
  PinVi 재vendor가 먼저 있어야 해서 `T-READ-02`·`08`의 Map 단독 회전이 막힌다. 순서는 계획 §8.1 그대로 — 이 PR 머지
  → PinVi `T-READ-PIN-01` ③(재vendor + `near-batch` client + 405 fallback) 머지 → Map+PinVi 한 pair 회전.
- 머지 준비(같은 날): main(#1509~#1515)을 합쳤다. 빨갛던 `test_consumer_rollout_shape`는 T-VN-41 pending
  receipt의 `map_service_openapi_sha256`이 현재 `openapi.service.json` sha와 같아야 한다는 단언이었다 —
  첫 판은 T-VN-40만 재핀하고 41(service 전용 receipt)을 빠뜨렸다. 41의 Map service 지문을 새 spec으로 옮기고
  blocking_reason에 한 문장을 더했다. PinVi vendor 지문과 pending 상태는 그대로다(격리 paired 검증 전 승격 없음).
  PinVi `T-READ-PIN-01` ③ PR과 둘 다 CI green일 때 Map → PinVi 순으로 머지하고, 배포는 한 pair 회전이다.
  이 회전에는 main에 먼저 머지된 `T-READ-02`·`03`·`08`(alembic 453)도 함께 실린다.

## 2026-11-18 — T-READ-03: 공개 읽기 요청 마감(머지, 다음 Map 회전에 실린다)

- `perf/t-read-03-public-read-deadline`(T-READ-02 위). PinVi `T-READ-PIN-04`(Map의 503 `READ_TIMEOUT`·`POOL_BUSY`를
  다시 보내지 않음, PinVi #777, 머지 commit `c0090296`)가 운영에 반영된 것을 확인하고 머지했다 — 운영 회전 `t1118a`
  (Map `7dc2af78` + PinVi `c21d9c5e`, green). PinVi `c21d9c5e`는 `c0090296`을 포함한다(GitHub compare: ahead 4, behind 0).
  T-READ-03 자체의 운영 반영 generation은 그 Map 회전 때 여기에 덧붙인다(acceptance 마지막 항목).
- 새 의존성 셋(`api/db.py`)이 옛 의존성을 **감싼다** — `get_public_read_session`(← `get_session`),
  `get_public_read_snapshot_session`·`get_public_read_slow_snapshot_session`(← `get_read_snapshot_session`). 격리 수준·세션
  수명은 옛 의존성이 그대로 정한다. 감싸는 쪽은 **DB에 닿지 않는다**(422로 끝나는 요청은 연결을 꺼내지 않는다) — 마감을
  `session.info`에 싣고, 그 요청의 pool 체크아웃 상한(min(pool 대기 2초, 남은 예산))을 ContextVar로 걸고, 세션
  `after_begin`에서 남은 시간 − 0.3초(바닥 250 ms)를 그 transaction의 `statement_timeout`으로 건다. 체크아웃 상한은
  `TimedAsyncQueuePool`이 읽어 짧게 기다리고 넘으면 503 `POOL_BUSY`(예산이 먼저면 `READ_TIMEOUT`) — 요청을 취소하지
  않으므로 연결이 새지 않는다(첫 판의 `asyncio.timeout` 방식은 의존성에서 연결을 미리 꺼내 422 시험 7건을 깼다). 시계는
  T-READ-02의 `request.state.started_monotonic`. 옛 의존성·엔진 `pool_timeout`·ADR-112 `transaction_limits`는 그대로.
- `infra/public_read_budget.py`: 마감이 없는 세션(Dagster·CLI·admin)에는 아무것도 보내지 않는다. `search_features`는
  마감이 있으면 `SET LOCAL` 둘을 `set_config` 한 문장(+ `statement_timeout`)으로 보내고 본 질의·개수 질의 앞에서 다시
  건다. 마감이 없으면 종전 그대로(문장 수 불변).
- 오류: 공개 예산 표시가 있는 요청의 57014 → 503 `READ_TIMEOUT`(표시 없는 57014는 종전처럼 500). batch route의
  `except SQLAlchemyError`는 표시가 있는 57014를 다시 던진다. 새 응답 선언·schema·enum 없음 — OpenAPI 불변.
- 적용 route(옛 → 새): bbox·in-bounds·nearby·categories·providers 둘·beaches 목록·beach markers·festival markers·
  curations collections·place-attributes는 `get_session` → `get_public_read_session`. search·nearby/by-target·상세·
  contained-features·price·price/snapshot·batch·beach 상세·festival 상세·curations(목록·collection 상세·feature)는
  `get_read_snapshot_session` → `get_public_read_snapshot_session`. festivals/monthly는 → `…_slow_…`. 배선은 단위 시험이
  표로 고정한다(범위 밖 route가 새 의존성을 쓰면 빨강).
- 관리 화면: `/v1/admin/features/in-bounds`(범위 밖)를 쓰고, 공개 route 중 price·contained-features는 client timeout
  없이 부른다 — 그 둘도 4.5초에서 끊긴다(위험 ③).
- 시험: 단위(배선 표·예산 계산), 통합(PostGIS — 문장 둘 요청 마감, pool 고갈 `POOL_BUSY`·누수 없음·`get_session` route는
  종전처럼 대기, 긴 예산, 예산 0, batch 57014, 마감 없는 `search_features`의 `statement_timeout` 불변, 실제 검색 route).

## 2026-11-18 — 공통 guard 호출을 T-029 커밋으로(Common T-417)

- `.github/workflows/common-frontend-policy.yml`의 호출 SHA와 `common-ref`를 `55a921b` → `0dec9543c8c8730ce7b05837f2fbe6c31d4ede65`(Common T-029 병합, 공통 Node 축 26.13.1)로 같이 올렸다. 새 guard는 정책 세 파일과 Node/npm 축을 이 ref에서 읽고, 도구 규칙(`check_node_toolchain`)을 더 돌린다.
- 도구 규칙 입력을 채웠다: `toolchain-manifests`(루트·`map-marker-react`·`kor-travel-map-user-client`), `node-dockerfiles`(`docker/frontend.Dockerfile`). C7 live e2e 이미지는 생산 이미지가 아니라 넣지 않았다.
- 새 검사기가 frontend 이미지에서 걸어 고친 것: `apt-get`(ca-certificates·git) RUN 삭제 — lock에 git 의존성이 없고 Node가 CA를 내장한다; `npm ci --workspaces --include=optional` → `--engine-strict`(optional은 기본 포함이라 설치 트리는 같다); runner의 `groupadd`/`useradd`(`nextjs`) 대신 이미지 내장 비root `node` 사용자(uid 1000). compose에 frontend 볼륨·`user:` 지정이 없어 영향 없음.
- `.nvmrc`·`engines`는 ADR-124(#1507)로 이미 26.13.1이라 이번 축에서 그대로 통과한다(T-024 읽기 전용 실행의 FAIL 두 줄 해소). 의존성·산출물 대조도 같은 ref로 통과(로컬 재현, Node 26.13.1).
- 기존 검증 스크립트와의 겹침: `verify-npm-tree.mjs`(설치 트리 `npm ls` problems 0)·`verify-next-sharp.mjs`(Sharp ABI 실변환)는 설치 결과를 보고, 공통 도구 규칙은 선언·이미지·npm 명령 형식만 정적으로 본다. 겹치지 않으므로 둘 다 남긴다.
- 검증: 공통 검사기 로컬 PASS, 관련 단위 테스트 5개 파일(실패 13건은 node_modules 없는 체크아웃의 dotenv validator 등 환경 — main 기준선과 같은 13건). frontend·docker-images·공통 정책은 PR CI. n150 게이트 `NOT_RUN`(CI 우선).

## 2026-11-18 — dev 포함 npm audit 게이트 한시 완화(GHSA-fc5q-39xc-vjpf)

- 2026-11-17T15:56Z picomatch ReDoS advisory 범위가 `<= 4.0.7`(최신)로 넓어져 frontend 워크플로의
  `npm high 취약점 gate (dev 포함)`이 main과 모든 PR에서 빨갰다. 패치가 없고 picomatch는 dev 도구
  (vite·vitest·tinyglobby·fast-glob/micromatch·@typescript-eslint)로만 들어온다. `audit:high`(`--omit=dev`)는 0건.
- §10.6 2번 절차대로 dev 단계만 완화했다. `audit:*` 스크립트는 그대로 두고, CI 스텝과
  `verify-all-gates.sh`가 새 `audit:dev:known`(`scripts/audit-dev-known-advisories.mjs`)을 돈다 — high 이상 근원
  advisory가 이 하나뿐일 때만 통과, 다른 advisory는 계속 막는다. 테스트가 목록을 이 하나로 고정하고
  목록 밖 high·critical·읽기 실패를 빨갛게 확인한다. `|| true` 거부 단언은 유지.
- 다시 조일 조건(패치된 picomatch를 lockfile·`overrides`로 소비)은 [§10.6](dev-environment.md)에 적었다.

## 2026-11-18 — 읽기 성능 Map 작업: 소유자 결정 적용 결과(문서 전용)

- 머지: `T-READ-08` autovacuum 문턱(alembic 453, #1509), `T-READ-02` 느린 요청 로그·pool 지표(#1510), `T-READ-01` 기준선
  도구(#1512, 실행은 측정 창). 셋 다 Map 회전(spec 불변)으로 나간다 — 배포는 하지 않았다.
- 브랜치만(머지 안 함):
  - `perf/t-read-03-public-read-deadline` — 공개 읽기 요청 마감. PinVi `T-READ-PIN-04`가 머지·**운영 반영**된 것을 확인한
    뒤 머지·배포한다(그 전에는 PinVi가 503 `READ_TIMEOUT`을 세 번 다시 보낸다). 독립 적대 리뷰 1회 반영.
  - `perf/t-read-04-transport-near-batch` — `POST /v1/service/transport/{dataset}/near-batch`. 덧붙이기만 하는 route라 기존
    소비자와 호환되지만 **service·full OpenAPI가 바뀐다**. 머지하면 그 뒤 Map 회전은 PinVi 재vendor 없이 pair gate를 통과하지
    못한다 — 위 둘(08·02)을 Map 단독 회전으로 낼 수 있게 PinVi `T-READ-PIN-01` ③(재vendor + near-batch client + 405 fallback)이
    준비될 때 머지하고 한 pair 회전으로 낸다.
- 대기(측정 뒤, 결정 1):
  - `T-READ-05` — 채택 판정이 측정(전처리 두 질의가 검색 시간의 5% 이상)이다. 코드로 보이는 이득은 따뜻할 때 수 ms로
    추정되고(F-07), 바꾸면 지역 이름 선택(표본 → 최빈값)과 문턱 3만 근처의 좁음/넓음 판정이 달라질 수 있으며 새 refresh에
    기댄다. 측정 없이 이득이 분명하지 않다.
  - `T-READ-06` — 묵은 키 허용은 정해졌지만(결정 3) 채택 판정(이름 정규화 비중 30%)과 되돌림 기준(p50 40%)이 측정이다.
    40만 행 표·refresh·평가 묶음까지 큰 변경이라 측정 전에 하지 않는다.
  - `T-READ-07` — 지울 색인은 14일 간격 두 스냅샷과 읽는 경로로 정한다. 3.6일 창의 "탐색 0"은 근거가 약하고(§4.1) 지운
    색인은 되살리는 비용이 크다. fillfactor 90도 적재 전후 측정으로 정한다.
- 운영 쪽 관측의 남은 몫(Map 코드 밖): 지표 켜기·token(Manager `T-READ-MGR-03`), scrape(`T-READ-MGR-02`), PG
  `pg_stat_statements`·느린 질의 로그(`T-READ-MGR-01` — **공용 PG 재생성 창** 필요).

## 2026-11-18 — T-READ-01: 읽기 기준선 도구(실행은 측정 창에서)

- 소유자 결정(2026-11-18)에 따라 **도구만** 넣었다. 운영 DB·운영 API에서 돌리지 않았다 — 조용한 측정 창은 소유자가
  따로 잡는다.
- `scripts/perf_tier2_release_harness.py`: 연결을 운영 API처럼 `jit=off` + `statement_timeout` 30초로
  (`HARNESS_SERVER_SETTINGS`), `--output <파일>`(`.safe.json`, DSN 없음, 사용한 연결 설정을 함께 적는다), viewport
  6 → 13개(지역 검색 "부산 맛집"·"서울 맛집", 수도권 시군구 집계 zoom 10, 서울시청 읍면동 집계 zoom 12·13 — PinVi 기본
  kind·500건, 서울 개별 행 500건 zoom 14, 상세 1건). 지역 검색은 운영과 같은 `_resolve_search_region` →
  `_search_region_arms` → `_search_region_params` → `_search_score_sql`로 SQL과 인자를 만들고, 전처리 셋(별칭·지역
  표본·지역 행 수)을 따로 잰다. 이름 정규화 비중은 **빼고 잰다** — `compacted`·`hits`의 식을 원래 열·상수로 바꾼
  harness 전용 변형의 p50으로 (i − ii) / i(`region_search[].name_normalization.share`). 비교 키를 모두 같은 상수로
  두면 뒤의 접기(`ST_ClusterDBSCAN` partition)가 후보 전부를 한 무리로 묶어 비용이 달라지므로 비교 키는 정규화하지
  않은 원래 열로 뒀다. 운영 SQL 모양이 바뀌면 변형 생성이 추측하지 않고 실패한다.
- 지역 검색 viewport의 최소 반환 행은 0이다(fixture가 그 지역을 모르면 빈 결과다 — 보고서의 `returned_rows`와
  `region_resolved`가 보여 준다). 다른 새 viewport는 1행 이상이어야 성공 보고서를 낸다(종전 fail-closed 그대로).
- 새 `scripts/read_path_probe.py`: HTTP만(표준 `urllib`, DB·`kortravelmap` import 없음 — 시험). PinVi 모양 요청
  9종(in-bounds zoom 7·10·12·13·14, 검색 셋, 상세 1건)을 30회씩 보내 `meta.duration_ms`와 왕복 시간 p50·p95, status,
  묶음 전후 PSI io `some avg60`을 적는다. service token은 `--token-file` 또는 `KOR_TRAVEL_MAP_PROBE_SERVICE_TOKEN`에서
  읽어 헤더로만 보내고 출력·파일에 쓰지 않는다(시험). loopback이 아닌 대상은 보고서에 `<non-loopback>`으로만 적는다.
- 남은 해제 조건(acceptance `T-READ-01` 둘째~여섯째)은 측정 창의 실행과 보고서다.

## 2026-11-18 — T-READ-02: 요청 도착 시각·느린 요청 로그·pool 대기 지표

- 소유자 결정(2026-11-18)에 따라 측정 없이 가치가 분명한 관측 코드로 진행했다(계획 F-03 — 운영 Map에는 읽기 지연을 볼
  수단이 없다).
- 미들웨어(http 미들웨어 중 가장 바깥)가 `request.state.started_monotonic`을 적고(`T-READ-03`의 요청 마감 기준),
  요청별 DB 누산기(`api/request_timing.py`)를 ContextVar로 건다. cursor 이벤트는 이제 **지표 flag와 무관하게** engine에
  걸려 문장 수·DB 시간을 그 누산기에 더한다. 추가 DB 왕복은 없다(통합 시험 — handler가 보낸 2문장이 그대로 2).
- 느린 요청 로그: `KOR_TRAVEL_MAP_API_SLOW_REQUEST_LOG_MS`(기본 1000, 0이면 끔) 이상이면 WARNING 한 줄 —
  route template·status·`duration_ms`·`db_statements`·`db_ms`·`pool_waits`·`pool_wait_ms`·request id. query string·
  header·좌표는 쓰지 않고, client가 보낸 request id는 `[A-Za-z0-9._:-]{1,64}`가 아니면 `-`로 쓴다.
- pool: `make_async_engine`에 `poolclass` 인자(기본 None = 종전). API engine은 `TimedAsyncQueuePool`(`_do_get`만 감싸
  시간을 잰다 — 크기·overflow·timeout 판정은 부모 그대로). `/metrics`에 `kor_travel_map_db_pool_wait_seconds`
  histogram과 `kor_travel_map_db_pool_checked_out`·`_overflow` gauge(scrape 때 `pool.checkedout()`·`overflow()`).
  세션 의존성은 바꾸지 않았다 — pool 크기 1에서 공개 key 인증 세션 → 읽기 snapshot 세션이 차례로 동작한다(통합 시험).
- OpenAPI 불변(미들웨어·`include_in_schema=False`). Map 회전(spec 불변)으로 나간다. 운영에서 지표를 켜는 것은 Manager
  `T-READ-MGR-03`, 긁는 것은 `T-READ-MGR-02`, PG 쪽 관측(`pg_stat_statements`·느린 질의 로그)은 공용 PG 재생성 창이
  필요한 `T-READ-MGR-01`이다 — Map 코드로 할 수 있는 몫은 이 PR이 전부다.
- 배포는 이 PR에서 하지 않았다. acceptance 마지막 항목(운영 로그의 1초 넘는 요청 줄)은 배포 뒤다.

## 2026-11-18 — T-READ-08: `feature.features` autovacuum 문턱(alembic 453)

- 소유자 결정(2026-11-18, 계획 "소유자 결정" 절)에 따라 측정 없이 개선이 분명한 작업으로 진행했다. 근거는 이미 실측이다
  (2026-11-17 §4.1·F-14 — 통계 창 동안 autovacuum 0회, dead 약 6.3만, all-visible 58%, reloptions 없음).
  acceptance ①의 "설정 전" 수치는 그 실측으로 대신하고, ③(적재 24시간 뒤 all-visible 0.95·`Heap Fetches` 1% 미만)은
  소유자가 잡을 측정 창에서 잰다 — 그때까지 이 작업은 열린 채다.
- alembic `453_features_autovacuum`: `ALTER TABLE feature.features SET (autovacuum_vacuum_scale_factor = 0.02,
  autovacuum_vacuum_insert_scale_factor = 0.05, autovacuum_analyze_scale_factor = 0.02)`(계획 제안값) + receipt head CHECK.
  forward-only, 마지막 문장 `SET ROLE ktm_feature_schema_owner`.
- 배포 영향: catalog만 바꾼다(표 재작성 없음 — autovacuum storage parameter는 PostgreSQL이 다시 쓰지 않는다). 잠금은 `SHARE UPDATE EXCLUSIVE`라 읽기·적재
  쓰기를 막지 않는다. 그 표에 autovacuum이 돌고 있으면 PG가 `deadlock_timeout` 뒤 취소하므로 그 ALTER만 `lock_timeout`
  5초다(수동 VACUUM·ANALYZE 중이면 5초 뒤 실패 — 재시도). 배포 직후 새 문턱(dead 약 8.9천)을 넘어 있으므로 그 표의
  autovacuum이 한 번 돈다 — heap 약 379 MB·색인 약 720 MB를 비용 상한으로 천천히 훑는다. 그 동안 n150 디스크 I/O가 는다.
- 배포는 이 PR에서 하지 않았다(Map 회전, spec 불변).

## 2026-11-18 — 읽기 성능 계획: 소유자 결정 기록(문서 전용)

- 소유자 결정 셋을 [계획](reports/2026-11-17-read-performance-plan.md) "소유자 결정 (2026-11-18)" 절에 적었다 — ① 코드만 보고도
  개선이 분명한 작업만 지금 하고, 가치가 새 측정에 달린 작업은 소유자가 따로 잡을 조용한 창까지 기다린다(그때까지 운영에서
  측정 job 금지). ② Map과 PinVi는 병렬(PinVi는 다른 에이전트). ③ `T-READ-06`은 refresh 전까지 옛 사전 계산 키로 순위를
  매기는 것을 허용한다 — acceptance `T-READ-06` 셋째 항목을 닫았다.
- 코드·운영 변경 없음.

## 2026-11-17 — 정확 Node 26.13.1 핀(ADR-124, Common T-416 채택)

- 소유자 결정(2026-11-17): Common T-416 "추천안 대로 node는 최신버전으로". 질의 당시 값 22.23.1 대신 nodejs.org 색인의 최신 LTS 줄(26 Lithium) 최신 patch **26.13.1**로 고정했다. 가장 새 항목 `v27.0.0-alpha`는 alpha라 제외. npm은 공통 축 12.0.1 유지(26.13.1 동봉 npm은 11.20.0).
- 루트 `.nvmrc` 신설, 루트·관리자 frontend `engines.node` 정확 `26.13.1`(lock의 두 항목 포함), CI `node-version`, `docker/frontend.Dockerfile`의 `node:26.13.1-bookworm-slim` digest.
- live e2e 실행 이미지(`docker/c7-playwright.Dockerfile`): Playwright base의 Node는 apt major 판이라 정확 `engines` + `engine-strict`에서 `npm ci`가 거절된다. 같은 digest의 공식 이미지에서 `node`만 `/usr/local/bin`으로 복사했다.
- guard 호출(`55a921b`)은 그대로다. 그 판은 `engines`를 읽지 않는다. 공통 축이 26.13.1이 되는 Common T-029 뒤에 T-417로 옮긴다.
- 검증: 관련 단위 테스트 6개 파일 96건 로컬 통과(`test_frontend_dependency_security`·`test_ci_workflows`·`test_c7_prod_live_runner_contract`·`test_dockerfile_workspace_manifest_coverage`·`test_ci_builds_production_dockerfiles`·`test_tvn34c_n150_fresh_live_runner`). frontend build·docker-images는 PR CI. n150 게이트·live e2e는 `NOT_RUN`(prod 배포·e2e 진행 중이라 n150 변경 금지).

## 2026-11-17 — Common 공통화 재조사 계획의 Map 포인터(문서 전용)

- 소유자 요청으로 kor-travel-common이 다섯 저장소를 다시 조사해 계획을 냈다(Common `docs/plan/commonization-plan-2026-11-17.md`, 적대 리뷰 2회 반영). Map 조사 기준은 `f1788da9`.
- Map 몫은 여섯이다: Common `T-480b`(API compose healthcheck를 `kortravelcommon.http_health` exec 형식으로, 선행 없음),
  `T-418`(`components/ui/*` 순수 재수출 shim 제거, 선행 없음), `T-416`(정확 Node/npm 핀 채택 여부 결정 — 소유자에게 질의됐고 답 대기),
  `T-417`(guard 호출 SHA·도구 규칙 이관, `T-416`이 채택일 때), `T-419`(Common `T-025`의 ui·tokens patch 릴리스 당일 재vendor — 그날 옛 guard에 남아 있을 때만),
  `T-415`(선택형 패키지 `@kor-travel/admin-kit` 채택, Common `T-221` 뒤. `T-416` 결정을 기다리지 않는다. 옛 guard면 `T-419` 뒤).
- `docs/tasks.md`에 `T-COMMON-PLAN-20261117` 한 줄, `docs/tasks-acceptance.md`에 같은 이름의 절을 뒀다. 수용 기준 본문은 Common이 소유한다.
- 코드 변경 없음. 진행 중인 작업과 다음 한 작업은 바뀌지 않는다.

## 2026-11-17 — 읽기 성능 계획(Map·weather·transport)

- 소유자 요청으로 세 서비스의 읽기 경로를 코드와 운영 관측으로 검토해 [계획](reports/2026-11-17-read-performance-plan.md)을 썼다. 코드·설정·운영 변경
  없음. 기준 commit은 Map `f1788da9`·weather `e68f16a7`·transport `60095379`·PinVi `b1605949`·Manager `31d56e4e`.
- 측정 창(03:31~05:14Z, 배포·e2e 중, 읽기 전용): n150 PSI io `full` avg10 63%, Map API 프로세스 VmSwap 154 MB(RSS
  14 MB), 운영 Map 지표 꺼짐·PG 느린 질의 로그와 `pg_stat_statements` 없음. PinVi `/metrics`로 `/features/in-bounds`
  38건 중 503이 15건, 상류를 부르지 않는 PinVi route 둘이 평균 1.63초·6.53초. bbox 색인 탐색당 평균 11.7만 색인 행.
  checkpointer write 시간이 버퍼당 약 48 ms. e2e가 끝나지 않아 조용한 호스트의 기준선과 PinVi `app.api_call_log`
  전수 집계는 하지 않았다 — `T-READ-01`·`T-READ-PIN-06`의 일이다.
- odroid(읽기 전용): CPU idle 0%(Dagster run 작업), PG 데이터가 있는 NVMe 남은 공간 1.9 GB — 소유자에게 전달됐다.
- 적대 리뷰 2회 반영. 1회차: `T-READ-03`을 요청 마감 예산·공개 전용 의존성으로 다시 쓰고 PinVi의 재시도 금지
  (`T-READ-PIN-04`)를 선행으로 뒀다. 2회차: Map과 PinVi는 OpenAPI hash가 같아야 회전하므로 spec을 바꾸는
  `T-READ-04`를 "Map 머지 → PinVi 재vendor 머지 → 한 pair 회전"으로 고쳤고 `T-READ-03`은 spec 불변을 요구 사항으로
  했다. PinVi의 요청당 비용·동시 호출 상한(교통·날씨)을 0단계로 올렸고, autovacuum(`T-READ-08`)과 디스크 쓰기 주체
  (`T-READ-MGR-06`)를 더했다. 작업은 30개(Map 8·PinVi 7·Manager 7·weather 4·transport 4)이고 계획 §8이 단계 순이다.
- 원장: `T-READ-01`~`08`. **해제 조건은 acceptance의 같은 ID 절이 소유한다.** 자리를 내려고 닫힌 절 둘
  (`T-VN-M02-TRUNCATE-FENCE`·`T-VN-M05-VERIFY-RECEIPT`, 둘 다 tasks-done에 완료 기록)을
  `scripts/archive_task_ledger_section.py --apply`로 `docs/archive/`에 옮겼다. 도구 검산 통과 — 체크박스 176건·175건이
  두 파일에 그대로, 원장 223,003 → 211,173 bytes. 본문은 도구가 옮긴 그대로다.
- weather·transport·PinVi·Manager `docs/tasks.md`에는 이 계획을 가리키는 한 줄을 둔다(각 저장소 브랜치
  `docs/read-performance-plan-20261117`).

## 2026-11-17 — 관리자 프런트 공통 후보12 채택(ui 0.2.1·tokens 0.1.2·vworld-map-web 1.0.4)

- kor-travel-common #57·#58(동결 `97f8ed98`)이 정책 정본을 올렸다. 공통 guard는 고정 ref와 무관하게 common **main**의 정책·정본을 읽으므로, 옛 산출물로는 guard가 실패한다.
- `packages/kor-travel-map-admin/frontend/vendor`의 ui 0.2.0→0.2.1·tokens 0.1.1→0.1.2·vworld-map-web 1.0.3→1.0.4(Firefox·Safari 바탕지도 누락 수정, maplibre-vworld-react #33)·vworld-map-rn 1.0.1→1.0.2(사용하지 않는 원장 항목, 정본과 맞춤)를 바꿨다. `common-artifacts.json`은 중앙 원장 값으로 맞췄고, lock은 npm 12.0.1 lock-only로 해당 3항목만 갱신했다.
- guard·common-ref는 `55a921b` 그대로 둔다. `97f8ed98`의 guard는 정확 Node/npm 도구 규칙(root `.nvmrc`=22.23.1, `engines.node` 정확값, common ADR-018)도 검사하는데 Map root는 범위(`^22.22.2 || ^24.15.0 || >=26.0.0`)를 선언하고 `.nvmrc`가 없어 실패한다(CI 실측). 그 이관은 engine-strict 아래 개발 Node를 22.23.1로 고정하는 별도 결정이다.
- ui·tokens는 내장 정책만 바뀌어 화면·CSS 변화가 없다. `VWorldMapHandle` 구현이 없어 rn 1.0.2의 `paddingPx` 확장은 해당 없다.

## 2026-11-17 — 공개 월별 축제 bbox 필터(PinVi 추천 여행 주변 축제)

- `GET /v1/public/festivals/monthly`에 선택 bbox(`min_lon`/`min_lat`/`max_lon`/`max_lat`, 4값 함께·일부만이면 422).
  목록과 `months` count 모두 `coord && ST_MakeEnvelope(…, 4326)`(GiST, 변환 없음 — ADR-012)로 좁히고 시도·시군구와 AND.
  map-markers와 같은 술어 조각(`_PUBLIC_FESTIVAL_BBOX_WHERE_SQL`)을 공유한다. 페이징은 기존 keyset cursor 그대로.
- 동기: PinVi `/notice-plans/{id}/highlights`가 시도 첫 50건만 읽어 바쁜 달에 근처 축제를 놓쳤다. user·full OpenAPI
  additive 변경(service 불변) — PinVi user 재vendor. 배포는 PinVi와 함께(PinVi는 옛 Map에서도 응답 좌표로 다시 거른다).

## 2026-11-16 — 북카페 재적재가 기존 행을 바꾸지 못한 원인: 재투영 scope 누락

- 증상: #1501 배포(t1116d) 뒤 `feature_place_mcst_culture_job` run `78380ace` SUCCESS인데 '카페 에무' 등이
  `01040000`/`museum` 그대로.
- 운영 실측(읽기 전용): dataset 50 `mcst_cafe_bookstores_csv` head 1,059건 전부 11:14Z에 관측 전진(run이 처리함),
  현재 record hash는 10-23 것 그대로 → `became_current` 거짓 → 본문 미기록. 활성 1,054건 `01040000`, 원본이 바뀐
  5건만 `02020000`. base 소유자는 dataset 50 자신이고 override 없음.
- 원인: 같은 원본 재투영은 `_CATEGORY_REPROJECTION_SCOPES`에 든 dataset만 한다. #1501이 그 scope를 빠뜨렸다.
- 수정: scope에 `mcst_cafe_bookstores_csv` 추가 + `_FIXED_FEATURE_CATEGORIES` ⊂ scope 단위 검사 + 통합 재투영
  검사에 북카페 형태 추가. prod 반영은 배포 뒤 북카페 dataset 재적재 한 번.

## 2026-11-16 — MCST 북카페를 카페로 표시

- 소유자 결정: `cafe_bookstores_csv`(북카페) 행의 표시 분류를 01040000 문화시설 → 02020000 카페.
- 목록 분류 `spec.category`는 feature_id seed라 그대로 두고 `_structured_category`의 고정 표시 분류로만 바꾼다.
  ID를 바꾸면 재적재가 새 행을 만들고 기존 행이 고아로 남는다. 회귀 검사 `test_cafe_bookstore_is_cafe_but_keeps_list_seeded_feature_id`.
- prod 반영은 배포 뒤 MCST `cafe_bookstores_csv` 재적재가 필요하다.

## 2026-11-16 — SRCH-002 "안동장" 첫 행은 Map 순위가 아니다

- PinVi live e2e(20261112-125734) SRCH-002: 서울 화면에서 "안동하회마을" 첫 행이 "안동장". prod Map(451) 직접 실측은 안동하회마을 1위(rank 10000108, 품음 단계 1·목적지 일치), 서울 중식당 안동장은 trigram만(0.22, 단계 2) 24위였다.
- 원인은 PinVi `region_biased_items`: bbox 없이 전국 40건을 받아 화면 안 행을 최대 limit//2개 앞으로 당긴다 — 일치 단계를 모르므로 유사도만 행이 이름 일치를 넘는다. Map은 q+bbox를 단계 안 가중으로 이미 처리한다(서울 bbox로도 안동하회마을 1위). 고칠 곳은 PinVi(bbox를 Map에 넘기고 클라이언트 재정렬 제거).
- Map 쪽은 그 계약을 회귀 검사로 고정: `test_bbox_never_lifts_a_similarity_only_row_over_a_name_match`.
- 분류 라벨: "카페 에무"=MCST 북카페 CSV 데이터셋 고정 분류 01040000(문화시설, 정책), 캠핑장=MOIS 유원시설 인허가 "수원산 오토캠핑장 트램펄린" 01010400(데이터 그대로 맞음). 롯데호텔 서울·김포국제공항은 main(#1499+452)로 숙박·공항이 첫 행임을 prod DB에 main 코드로 확인.

## 2026-11-12 — 접기 대표 회귀(#1495 후속)

- 배포 뒤 rankprobe: 접기 대표를 순위로만 골라 관광 그룹 0의 MCST 촬영지 행(01000000)이 MOIS 호텔 행을 숨겼다. 대표 = (구체 분류, 비MCST, 순위), 자리는 무리 최솟값. 원천 조회는 둘 이상 무리에만.

## 2026-11-12 — D2 fixture가 Feature 쓰기 gate를 긴 대기로 먼저 잡는다

- t1112b(Map aa38c30a) D2는 spec 2/2 통과 뒤 helper `purge`가 55P03(lock timeout)으로 죽어 `purge-failed` BLOCKED.
  gate 함수가 세션 `lock_timeout` 0을 1초로 바꿔 잡는데, 같은 시각 큐 적재(krforest 산사태 notice)가 쓰기 단계에서 gate를 쥐고 있었다.
  UI(#1496)·검색(#1481) 회귀 아님. lane은 runbook §6 `recover`(identity 일치)로 정리(잔여 TVN36 1건 purge), D2 재실행 GREEN.
- 고침: fixture `seed`·`cleanup`·`purge`가 DB를 건드리기 전에 `execute_with_lock_wait`로 gate를 600초 상한으로 먼저 잡는다.
  뒤의 procedure 획득은 같은 transaction 재진입이다. 회귀 검사 `tests/unit/test_d2_fixture_gate_lock_wait.py`(수정 전 red 확인). 다음 회전에 실린다.

## 2026-11-11 — 예보 단기 전량 ReadTimeout 원인·page size

- 단기 위치 약 1,450곳이 limit 2,000 페이지 하나에 들어 요청 하나가 artifact 전부(cold 약 1,174초)를 읽다 300초 timeout. 예보 page size 200으로 나눔. 초단기 상한 600→1,800초. 초단기 808건 거부는 weather 원천 coverage였다.

## 2026-11-12 — 검색 3단계 main 병합과 C11 검증 보존

- 검토된720과 upstream5742b45의 이력을 merge로 보존했다. incoming 코드·검사16개는 main 원문 그대로다.
- frontend/root package·lock·vendor·C11 Scope2 payload는720과 동일하여 D286/286·unit440·Doctor0 증거를 재사용한다.
- backend 검색·SQL·migration·archive 단위104PASS. Dagster 대상은 로컬 redis 의존성 누락으로 수집불가 원시를 보존했고 새 정확 HEAD CI로 확인한다. 실제 DB/Dagster 작업은 실행하지 않았다.

## 2026-11-12 — C11 D의 정렬 버튼 회귀 검사 보강

- C11 새 이미지 D에서 정렬1건이 원 실행/재시도 모두 옛 로컬 bg-brand 클래스 단언으로 실패했다.
  원286검사·실패/trace/report를 taskroot validation/c11-map-weather-20261112/에 보존한다.
- 공통 Button은 bg-primary를 쓰고 Map의 primary는 기존 brand 토큰에 연결된다.
  해당 검사만 aria-pressed·공통 variant·실제 brand 배경색과 비선택 대비를 함께 확인하도록 보강한다.
  정렬 GET/cursor 단언·286 inventory·retry/timeout·앱 runtime·lock/vendor는 유지한다.
- 부모 batch1 frozen6b 이후 테스트1파일/이 기록만 별도 delta다. 수정 후 전체 D를 새 source로 재검증한다.
  첫 D285PASS/1FAIL을 최종 성공으로 집계하지 않는다. Weather 새 build/20+5도 같은 슬롯2에서 이어 실행한다.

## 2026-11-12 — main 검색 2단계 병합과 C11 runtime 기준 보존

- origin/main cb38c33b40d3b041a0b6df3fb50f340d1c98839a의 검색 순위2단계 변경을 merge한다.
  기존925/e4/f55/C11 f569 commit은 재작성하지 않는다. 문서 충돌2개는 incoming 새 절과 기존 이력/보관 인덱스를 함께 보존했다.
- 비문서9개는 incoming 원문과 동일하고 frontend 전체·root package/lock/vendor는 f56976ec9adf7482e66299195aea0cd381eca667와 같다.
  유입 category/feature repository/속성 SQL 및 archive 링크 단위123PASS. DB/수집기 lifecycle·실제 migration은 실행하지 않았다.
- C11의 전체440·Doctor0·lint/type·local/external canonical guard·npm peer0을 n150 f569 source로 확인했고,
  새 production 이미지의 정식D286 strict/전체runner cleanup과 Weather20+5는 같은 슬롯2에서 진행 중이다.
  이 merge에서 UI를 바꾸지 않았으므로 frontend 전체를 다시 설치/빌드하지 않는다. 원 리뷰/CI delta는 별도 재확인한다.

## 2026-11-12 — 검색 순위 3단계(검색 인지도, alembic 451)

- 1차 설계(이웃 300 m 안 이름 포함 행의 원천)는 prod 여주 846행에 59 s — 쌍마다 정규화. 같은 이름 해시 결합 + 국가유산 이름 낱말 해시 결합으로 바꿔 전체 34만 행 5.3 s(읽기 전용 실측). 분포: 0(MOIS 단독) 195,651 · 1 95,401 · 2~6 약 5만 · 7~9 94. 신륵사(여주) 6, (제천) 4.

## 2026-11-12 — 검색 순위 2단계(실효 그룹·중복 접기)

- 상위 8개의 25%가 같은 장소 반복(MCST 4종·TourAPI·표준데이터). 첫 접기는 행 쌍 반조인(`OR NOT EXISTS`)이라 후보 제곱 — "강화 펜션" 44 s. 대표 거리 창 함수 → 적대 리뷰(휴게소 상·하행 접힘, 다른 도시 무리 미접힘) 뒤 키별 DBSCAN 무리 + feature_id 해시 반조인.

## 2026-11-12 — C11 정본과 FocusScope fix2 채택

integration-11-review 단일pack의 원장7개·vendor7개를 동일 bytes로 동기화한다.
공통 producer a35481349d6747b4f13b958ae64d9c0bbd0b5413,
FocusScope source1752a539c8d5ae57961a0fa2702d2573d48fefe7의
1.3.1+kortravel.fix.2를 runtime file 직접 의존성과 root override로 연결한다.
Lightning CSS fix.4는 dev 필수이며 지도9a bytes를 유지한다. RN은 vendor/원장에만 두고 웹에 설치하지 않는다.
중앙 workflow 실행 코드는55a921b55d248106cbe320e7f5305f3d3cdb60fe를 유지한다.
C10 checkpoint·원925/e4·원 A/B와 전후 실패 로그를 보존한다.
n150 슬롯2에서 기존 cache를 재사용해 명시 file 설치/실제 UI94+tokens25+Scope15 bytes,
외부 C11 canonical guard 및 최종 frontend gate를 검증 중이다.
검증 완료·독립2리뷰·CI·merge·부모 go 전까지 배포하지 않는다. DB/API/RustFS/Dagster lifecycle 변경 없음.

## 2026-11-12 — A 검토의 공통 Button variant/size 전달 수정

- 원A의 A-CONS-P2-02를 같은 SSR 대조로 재현했다. ghost/link/outline·icon-xs metadata가
  default로 남고 ghost/link에 primary 채움이 남았다. Common 직접 호출은 정상이다.
- variant/size를 공통 primitive로 전달하고 로컬 전체 CVA 색상/크기 recipe는 공통 정본에 위임했다.
  Map에는 focus outline·disabled 설명 도달성 정책만 남겼다. loading root/라벨/포커스·접근성 이름과
  활성화 차단은 유지한다. Link용 buttonVariants도 같은 공통 크기를 사용한다.
- 새 회귀8개는 수정 전6FAIL/2PASS, 수정 후8PASS. 기존adapter21개를 포함해29PASS,
  세 파일 타입·scoped lint PASS, 실제 Map source 전체 Doctor325files 진단0이다.
  기존 Geo 도구/동일 c9 Common Button 원문을 읽기 재사용한 경량 fixture임을 구분한다.
- b102의 GitHub Python3.11/3.12/3.13 unit+lint 단계는 모두 PASS를 확인했다.
  전체 API/Dagster job 완료 및 중앙 정책 PASS와 혼동하지 않는다.
- C10은 metadata/hash checkpoint만 유지한다. disabled fieldset Scope fix2의 C11과 부모 n150 슬롯 전까지
  Map/Weather heavy 설치/build/browser는 보류한다. C11에서 실제 Map 기존432+새8 전체·Doctor/build/
  D286 strict+cleanup을 확인하며, 현재29개를 전체440개 성공으로 집계하지 않는다.
- taskroot validation/map-A-button-closure-20261112/에 before/after SSR·8개·21개·type/lint/Doctor를 보존한다.
  원A/B raw와925/e4/b102 이력은 그대로 두고 원 reviewer closure용 별도 delta를 제공한다.

## 2026-11-12 — B 검토의 CI 계약·문서 크기 실패 수정

- e4 CI와 같은7개 실패를 원 단언 그대로 재현했다. 원시 job 로그와 before7FAIL을
  taskroot validation/map-B-closure-20261112/에 보존한다. 원925/e4·B원문은 수정하지 않는다.
- verify-all-gates에 공통 의존성 명령을 실제 mirror하고 기본 npm/고정 npm의 workspace script를
  같은 감사 규칙으로 읽는다. 명령 삭제·workspace 바꿔치기 변이도 검출한다. 면제는 추가하지 않았다.
- root override 계약은 정본의 CSS와 추후 C10 FocusScope만 명시적으로 direct file/override/모든 lock copy와
  대조한다. 미등록 override·stock 중첩 copy·SRI/선언 drift는 거부한다. package/lock/vendor는 아직 불변이다.
- Playwright runner 계약은 frontend 선언 버전과 immutable64자리 digest를 대조한다.
  Geo 안내 문장은 제품 literal을 유지하며 파서가 포매터 줄바꿈을 읽고 식/문구 drift는 검출한다.
- 관련7개 모듈90PASS(정상/변이 대조군 포함). 전체 backend unit은 기존 WSL venv의
  common/redis/pyshp/timeout plugin 누락으로 collection10오류다. 원시 로그를 보존하고 정확 HEAD CI에서 재검증한다.
- 오래된 완전한 절을 journal-2026-10g/resume-2026-09e에 원문 그대로 보관하고 인덱스/링크를 남겼다.
  옮긴 절을 되넣어 기존 문서가 byte-exact로 재구성됨을 확인했다. 한도225280은 바꾸지 않았다.
- C10은 다음 별도 후보 채택 단계다. n150 heavy 슬롯은 부모 배정 대기이며
  공통·UI runtime·lock/vendor 재포장·운영 API/DB/Dagster lifecycle은 수행하지 않았다.

## 과거 기록 아카이브

> 현행 작업 창(2026-10-01~) 이전 기록은 아래로 분리했다. 검색은
> `rg <패턴> docs/archive/` 로 한다. 새 엔트리는 항상 이 파일 상단에 추가한다.

| 파일 | 기간 | 엔트리 | 크기 |
| --- | --- | --- | --- |
| [journal-2026-11a.md](archive/journal-2026-11a.md) | 2026-11-02 ~ 2026-11-12 | 59건 | 43713 bytes |
| [journal-2026-10k.md](archive/journal-2026-10k.md) | 2026-10-14 ~ 2026-10-24 | 70건 | 22613 bytes |
| [journal-2026-10j.md](archive/journal-2026-10j.md) | 2026-10-24 ~ 2026-10-28 | 91건 | 66211 bytes |
| [journal-2026-10i.md](archive/journal-2026-10i.md) | 2026-10-24 | 23건 | 24611 bytes |
| [journal-2026-10h.md](archive/journal-2026-10h.md) | 2026-10-22 ~ 2026-10-24 | 15건 | 27854 bytes |
| [journal-2026-10g.md](archive/journal-2026-10g.md) | 2026-10-14 ~ 2026-10-22 | 19건 | 47365 bytes |
| [`journal-2026-10f.md`](archive/journal-2026-10f.md) | 2026-10-13 | 3건 | 23787 bytes |
| [`journal-2026-10e.md`](archive/journal-2026-10e.md) | 2026-10-13 | 2건 | 21540 bytes |
| [`journal-2026-10d.md`](archive/journal-2026-10d.md) | 2026-10-13 | 2건 | 7200 bytes |
| [`journal-2026-10c.md`](archive/journal-2026-10c.md) | 2026-10-01 ~ 2026-10-12 | 28건 | 53974 bytes |
| [`journal-2026-10b.md`](archive/journal-2026-10b.md) | 2026-10-01 | 1건 | 6 KB |
| [`journal-2026-10a.md`](archive/journal-2026-10a.md) | 2026-10-01 | 1건 | 6 KB |
| [`journal-2026-09h.md`](archive/journal-2026-09h.md) | 2026-09-30 | 1건 | 4 KB |
| [`journal-2026-09g.md`](archive/journal-2026-09g.md) | 2026-09-28 ~ 2026-09-29 | 6건 | 22 KB |
| [`journal-2026-09f.md`](archive/journal-2026-09f.md) | 2026-09-26 ~ 2026-09-27 | 14건 | 31 KB |
| [`journal-2026-09e.md`](archive/journal-2026-09e.md) | 2026-09-20 ~ 2026-09-25 | 8건 | 27 KB |
| [`journal-2026-09d.md`](archive/journal-2026-09d.md) | 2026-09-16 ~ 2026-09-19 | 7건 | 22 KB |
| [`journal-2026-09c.md`](archive/journal-2026-09c.md) | 2026-09-14 ~ 2026-09-15 | 8건 | 22 KB |
| [`journal-2026-09b.md`](archive/journal-2026-09b.md) | 2026-09-11 ~ 2026-09-13 | 5건 | 26 KB |
| [`journal-2026-09a.md`](archive/journal-2026-09a.md) | 2026-09-01 ~ 2026-09-10 | 23건 | 84 KB |
| [`journal-2026-08d.md`](archive/journal-2026-08d.md) | 2026-08-29 ~ 2026-08-31 | 14건 | 25 KB |
| [`journal-2026-08c.md`](archive/journal-2026-08c.md) | 2026-08-28 ~ 2026-08-28 | 21건 | 20 KB |
| [`journal-2026-08a.md`](archive/journal-2026-08a.md) | 2026-08-14 ~ 2026-08-27 | 124건 | 200 KB |
| [`journal-2026-08b.md`](archive/journal-2026-08b.md) | 2026-08-01 ~ 2026-08-14 | 89건 | 166 KB |
| [`journal-2026-07c.md`](archive/journal-2026-07c.md) | 2026-07-26 ~ 2026-07-31 | 60건 | 167 KB |
| [`journal-2026-07a.md`](archive/journal-2026-07a.md) | 2026-07-13 ~ 2026-07-24 | 115건  | 219 KB |
| [`journal-2026-07b.md`](archive/journal-2026-07b.md) | 2026-07-01 ~ 2026-07-12 | 28건   | 45 KB  |
| [`journal-2026-06a.md`](archive/journal-2026-06a.md) | 2026-06-10 ~ 2026-06-30 | 172건  | 219 KB |
| [`journal-2026-06b.md`](archive/journal-2026-06b.md) | 2026-06-02 ~ 2026-06-10 | 179건  | 220 KB |
| [`journal-2026-06c.md`](archive/journal-2026-06c.md) | 2026-06-01 ~ 2026-06-02 | 36건   | 53 KB  |
| [`journal-2026-05a.md`](archive/journal-2026-05a.md) | 2026-05-24 ~ 2026-05-31 | 90건   | 218 KB |
| [`journal-2026-05b.md`](archive/journal-2026-05b.md) | 2026-05-24 ~ 2026-05-24 | 3건    | 7 KB   |


### Rest432 후속: 실제 원자성 및 공식 스키마

- 실제 원자성11개 PASS: 오류·취소 전체 rollback/동일 plan 복구/성공 commit 응답경계 SDK0.
  초기quota3행·사용량0/guard33 단언과 정확 시험 DB·볼륨 정리를 확인했다. Rest215·두 writer는 미완이다.
- 정본 package graph 누락1F28P를 공식 generator로 수정하고29P, 두 명 검토 후 반영했다.
- 별도 fresh 공식 schema432 생성·재비교1P27.459초, dump a55cf046. 예상2추가/5변경만이며
  역치환은 기존431 전체 bytes exact다. startup ACL/metadata 및 최종 CI/live·배포는 진행 중이다.


### 2026-11-04 — #1448 중간 구현
- #643/#1444 최신 본문·댓글을 다시 읽었다. 추가 변경 없음. WSL 검증·머지만 수행한다.
- python-mcst-api PR #20 merge SHA로 consumer pin을 갱신했다.
- MCST 적재 직후 dataset별 causal seal을 완료하고, 재시도에서 done member는 재적재하지 않는다.
- fetch/load 실패를 dataset별로 모으고 성공 member에는 실패 attempt를 쓰지 않는다.
- WSL MCST 단위 22건·변경 source mypy 통과. 실제 PG·UI·두 독립 리뷰·최종 CI는 진행 중이다.


### 2026-11-04 — #1448 선택 경계·실제 PG/UI 보완
- 두 독립 예비 적대 리뷰의 범위 밖 적재(P1), 비선택·비활성 필수 resolve, 일시 DB/SDK 네트워크 재시도, SDK 코드명, UI 원인 누락을 수정했다.
- frozen ID만 표시 key로 연결하고 변환·적재 전에 선택 집합을 적용한다. 완료·중복·외부 callback 거부와 완료 command 실패를 구분한다.
- MCST root 상세에 하위 작업 이벤트를 시간순 cursor로 합쳐 실패 원인·작업 이동을 제공한다. cursor는 child 포함 여부에도 묶이며 기존 다른 조회는 유지한다.
- dataset 이벤트에도 기존 payload를 전달하는 additive admin API 필드를 추가했다. 진단 UI는 허용한 code/phase/reason/retryable만 렌더링한다.
- 실제 PG wrapper 12/13 및 좁힌 manifest·비선택 비활성 회귀 2건, 관련 lifecycle/ops PG 54건, 관련 API 198건, targeted Dagster 112건을 통과했다.
- 실제 공식 keyless golf CSV를 Map 기본 factory로 1행 제한 조회(14열·필수7열)했다. MockTransport SDK 승인·CAPTCHA·메타·네트워크·ZIP 모호성·HTML 오류를 별도로 검증했다.
- 실제 WSL PG/API/Next/Chromium에서 관리자 로그인·12/1 요약·원인·하위 작업 응답 후 이동 4흐름 통과. root/child 스크린샷을 직접 검사했다. 원본 API 응답 대체 없음.
- WSL 폐쇄 포트가 reject 대신 drop되는 경우를 허용하도록 fail-closed 테스트의 psycopg OperationalError 하위 ConnectionTimeout 표기를 보완했다. 제품 연결 정책은 그대로다.
- 전체 API 1,600건·main unit/lint 3,643건·frontend 418건, frontend type/lint를 통과했다. 이후 최종 head의 전체 CI·두 독립 재리뷰를 진행한다.


### 2026-11-04 — #1448 최종 타입 경계 보완
- CI strict API mypy에서 조건부 kwargs의 bool dict 추론 오류를 확인했다. 같은 조건을 명시적 bool 인자로 전달하도록 보완했다.
- API 72개·Dagster 38개 파일 strict mypy 및 pipeline API 162개를 다시 통과했다. 최종 CI는 새 head에서 확인한다.


### 2026-11-04 — #1448 최종 적대 리뷰 보완
- 앞선 영구 수집 실패와 후속 완료 기록의 일시 실패를 함께 보존한다. 아직 loop에 도달하지 않은 fetch 실패도 집계하며 영구 실패가 하나라도 있으면 전체 재시도는 닫힌다.
- 원문 예외 연쇄를 억제하고 실제 Dagster 오류 직렬화에서 sentinel 미노출을 확인했다. dataset 순서 두 경우 모두 양성 통과, 직전 구현은 새 단언 2건 모두 실패했다.
- SDK 승인·quota 경계·MCST 회귀·schedule fail-closed 114건 통과. 실제 PostgreSQL 전체 1,624건 통과·기존 조건부 skip14. 실제 wrapper/narrow 2건과 관련 lifecycle/ops54건 포함.
- 최신 source로 실제 WSL PG/API/Next/Chromium 5흐름을 재검증했다. root/child 작업 이동은 실제 child 응답과 event job ID까지 대조했고 dataset 이력에서도 같은 원인을 확인했다. API 응답 대체 없음. 스크린샷 직접 검사 및 소유 스택 종료.
- additive admin payload 변경에 맞춰 OpenAPI baseline과 기존 pending consumer receipt의 SHA만 재핀했다. pending 상태·배포 차단 사유는 보존하며 운영 검증을 완료로 바꾸지 않았다.
- provider 원본은 immutable pin SHA를 읽어 표면 manifest --check를 통과했다. 기존 형제 checkout은 읽기만 했고 수정하지 않았다. 계약·표면 검사 43건 통과.
- 최종 head의 두 독립 재리뷰와 CI 후에만 머지한다. 운영 접근·배포·테스트 없음.

## 2026-11-12 — origin/main 병합·925c 리뷰 기준 보존

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-12 — c9 정식 D 전체 runner·cleanup exit0 확정

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-12 — c9 정책 검사기와 동일 runtime 산출물 동기화

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-12 — c8 동일 산출물 채택과 정식 D 정리 gate 재검증

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-11 — Map 정식D 브라우저286통과·Docker 후행 정리 인계

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-11 — Map 전체 브라우저 통과와 checkpoint gate 정렬

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-11 — Map 두 번째 checkpoint285/286와 마지막 fixture 정렬

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-11 — 후보6 브라우저 회귀와 fixture 보완

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-11 — common 후보6와 키 없는 지도 public mapStyle 복구

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-11 — 관리자 common Radix/VirtualTable·지도 public API 통합 후보

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-12 — 검색 순위 1단계(alembic 450)

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-11 — ADR-122 개정: weather 멤버십 digest·clock epoch

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — ADR-122 weather 예보 증분 적재

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — 박물관·관광지도 공개 파일

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-11 — 영문 괄호 이름 검색·대피소 現 표식

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-11 — 촬영지 미분류 회귀(dataset 48)

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — 축제 원천 TourAPI 단독(449)

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — 주차장 키 403 → 공개 파일

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — #1475 admin 부분 검색 3~12 s

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-11 — #1468 A R4 전환 실행기

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — #1468 A R1·R3 구현·R2 운영 dry-run

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — 운영 검색 점검(#1476~#1478)

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — 휴양림 ↔ MOIS 숙박은 휴양림 master

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — #1468 D 국가유산 행사 회차 묶음

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — #1468 B·C dedup 재가동·원천 겹침 쌍

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — #1459 TourAPI 문화시설(14)·레포츠(28)

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — ADR-121 accepted (소유자 결정)

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — #1459 여행지 검색 별칭(444)·분류 override 준비

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-10 — #1468 A MCST 테마 목록 속성화 설계(ADR-121)

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-09 — KNPS 대피소 공식 원본 확인과 핀 상향

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-09 — MOIS 숙박 우선 적재·상호 정규화

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-09 — #1459 TourAPI 관광지 적재 경로

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-09 — 전통시장·특화거리 공개 파일 원천(키 없음)

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-09 — #1459 지역 검색·좌표 결측 fallback

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-09 — #1459 전통시장 표준데이터 적재 경로

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-09 — #1459 휴게소·철도역·여객선 항구·공항 검색(ADR-120)

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-07 — Valkey 상태 쓰기 일시 실패 재시도

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-07 — 통합 테스트 PG 비내구·tmpfs

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-07 — #1455 저배율 in-bounds cluster 집계

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-07 — KNPS 대피소 미적재 후속

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-06 — #1450 Option A: KNPS 보호지역 지정 allowlist

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-06 — #1450 KNPS dataset별 schedule·운영 1회 적재

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-05 — #668 명령 조정 첫 구현·실패 우선 검증

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-05 — Pinvi #668 명령 조정 계약 착수

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-04 — #1444 묶음(#1445~#1448) 리뷰 보완

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-04 — MCST 승인 복구·데이터셋별 적재 완료 보존 착수 (#1441/#1442)

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-04 — 실제 분류 UI 검증·성능 하네스 파라미터 보완

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-04 — 실제 MCST 분류 형식·공백 별칭 보완

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-04 — Feature 품질 최종 WSL 검증

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-04 — 적대적 리뷰의 회차 비교/관리자 보정 충돌 수정

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-04 — #1438/#1439 현재 원본 재투영·품질 전이 검증

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-04 — #1439 행사 분류·격리·회차 병합 경계

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-04 — #1438 구조화된 시설 분류 회귀

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-03 — PinVi #643 관리자 조회 연계 (#648/#651)

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-04 — #1438·#1439·#1443 Feature 분류·행사·검색 순위 묶음 착수

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-04 — Pinvi #643 과거 날씨 요약·오래된 정보 표시 묶음 착수

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-03 — weather_state 503 페이지 재시도

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-02 — feature 검색 순위·별칭(alembic 436)·주차장 표시 이름

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-11-02 — weather_state 하한·W5 상한 실측 조정

[완전한 원문](archive/journal-2026-11a.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — run-status sensor tick 실패로 cursor 엿새 정지(#1434)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — ADR-117: SH 스냅샷·스칼라 정책 경로 퇴역(alembic 435)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — T-PG18-CI: prod coord_5179 PROJ 7→9 drift 검사 clean

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — T-PG18-CI: CI·compose를 PG18 공용 digest 한 lane으로(ADR-118, #1431)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — #1426의 main 병합 뒤 resume 크기 경계 복구

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — #1426의 main 충돌·기존 통합 회귀 호환 교정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-28 — 현재 배포·원51복구·공개 UI13 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — typed stale 복구 코드의 최종 CI·후보UI·정상 머지

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — Codex PR 통합 리뷰의 비잠금 항목(WI-5~11)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — alpine 관찰자 cold-array codec 경계 최소 교정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 실제 제품16·후보UI14 뒤 head oracle 빈줄1개 교정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — typed reset 실제 제품16 통과, CI 계약 교정 중

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 첫 제품 PG14PASS/2FAIL 보존과 canonical head 교정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — typed reset scope 권한을3열로 제한하고 통합17개 수집

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — typed bound reset 통합 source16개와 순수142개

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 새 typed reset의 순수 경계138개 통과

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 실제 stale→rollback→live READY reset 거부 재현과 첫 제품 경계

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — bound 재현의 strict Geo 입력 연결만 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — bound snapshot 첫 재현은 baseline setup timeout으로 미도달

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — bound snapshot stale 뒤 live lease 재계획 경계 조사

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — Common 최신 제품 공식 pair 배포·공개 UI13 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 동시 쓰기 제한 시험 두 PR의 최종 CI·정상 병합

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — snapshot OS worker pair 최종 CI·정상 병합 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 공유 Feature의 동일 artifact 재계획 실제 PG 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 공유 Feature 첫 실제 PG의 xid8 관찰 bind 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — 공유 Feature의 동일 artifact 재계획 시험 착수

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — snapshot OS worker pair의 제한 실제 PG 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — Codex PR 통합 리뷰의 비잠금 항목(WI-5~11)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — Codex PR 리뷰 정리: tracking 장부는 L만, 단건 writer는 regime 진입(434)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-27 — kor-travel-common 최신(`aa232ad5`) 반영: 브랜치 `chore/common-latest-map`

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 제한 단위의 최종 CI·배포·공개 UI 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — byte quota 최종 CI 실패와 문자열 선검사 비용 보강

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest 중복 검증 제거의 PG·후보 UI 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest 최종 두 PostGIS 시간초과 보강 중

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest reader 제품 PG 통과와 로그아웃 이동 경합 보강

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest reader 조회에 한정한 JIT 비활성화 초안

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 최종 CI 실패와 최소 수정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 추가 물리 경합·후보 UI 수용과 CI 잔여 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 설계 누락 경합·계측 시험 보강

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 quota/GC·복구 재검증 통과

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 실제215·두 writer 검증

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — 431 reader 배포·공개 UI·원 일정 복원 완료

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 선택 A 구현 첫 checkpoint

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 · Rest431 최종 CI와 main 반영 정산

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 · Rest431 최종 제품과 격리 후보 추가 인수

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 · Map/PinVi 배포·공개 읽기·일정 복원 정산

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest432 단일 export 영속 재관측 설계 초안

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest431 CI의 unordered presence 비교 결함 수정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest431 관리 직접SQL 음성 실제 수용

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest431 실제215 fit와 최종 공식 golden

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest431 원64 비용 계량과 A1 source

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 — Rest431 통합 source와 실제 lab 준비

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 430 복구 후보 실제 UI와 CI 비교 기준 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — Rest431 reader 미호출 source

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 휴게소431 명시 profile 설계·계량 경계

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 430 복구 후보 실제 UI와 CI 비교 기준 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 휴게소431 명시 profile 설계·계량 경계

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-26 · expired reset applying holder의 정본 fixture 회귀

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 · 전용 읽기 동결 소비 계약 정렬

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 · Feature read/create 중복 자격 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 · PinVi admin Feature 전용 읽기

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 snapshot 잔여 fixture 실제 확인

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — PostGIS 추적 fixture 정리

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 430 복구 후보 실제 UI와 CI 비교 기준 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 430 전체 PG gate 첫 원인 수정 준비

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 공항 snapshot 원자적 후처리 구현 중

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 · cancellation 원 backend cleanup 후보

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 API task 취소·pool 경계 시험 소스

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 비활성 strict SH guard429 owned 검증

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 인덱스 metadata 반사 표현식과 실제 검사 정산

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — capture 권한 인벤토리 CI 정정

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 제한된 현재집합 capture(428, 구현 중)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 공항427 key/index 보강

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 공항427 SQL/decoder source

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 공항 reader Geo 계약(427, 부분)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 가격 추이 본문 읽기 Low 3건(#1365 리뷰 후속)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 현행 기록 크기 경계 재분리

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 공개 provider patch P-first(426)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — Provider base UPDATE-first 후보(425, 미수용)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — tracking P→L prefix(424, 부분)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — Place projection 예산 검사 추출

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 첫 동시 수집 후보 설계(미구현)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — EX context 단일 조회(423)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — scalar batch 내부 실행 단계 분리

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 전체 snapshot 동시 쓰기·복구 설계(미구현)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — Heritage bounded evidence reader 입력 계약(부분)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — SH 운영 후보 크기 실측

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — Geo stamp SQL writer 권한 경계(421)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — 실제 SH 수집 연결의 설계 초안(A4)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-25 — main 419 보존과 EX 적재 연결 420 재검증

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

## 2026-10-24 — 제한 primary place의 명시 EX 전체 적재(A3 checkpoint)

[완전한 원문](archive/journal-2026-10j.md)은 크기 상한에 따라 분리했다.

[과거 기록 아카이브로](#과거-기록-아카이브)
