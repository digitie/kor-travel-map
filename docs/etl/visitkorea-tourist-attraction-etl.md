# visitkorea-tourist-attraction-etl.md — TourAPI 관광지·문화시설·레포츠 → place (#1459)

한국관광공사 국문 관광정보 서비스(KorService2, 공공데이터포털 15101578 "한국관광공사_국문
관광정보 서비스_GW") `areaBasedList2`의 **관광지(12)·문화시설(14)·레포츠(28)** 를 1차 place
Feature로 적재한다(14·28은 2026-11-10 추가 — 한 dataset·한 snapshot, migration 없음). 축제(`searchFestival2`, `visitkorea_festival_events`)는 표준데이터 1차의 enrichment지만
이 dataset은 Feature를 직접 만든다.

| 항목 | 값 |
|---|---|
| provider / dataset_key | `python-visitkorea-api` / `visitkorea_tourist_attractions` |
| 변환 | `kortravelmap.providers.visitkorea_attractions.tourapi_attractions_to_bundles` |
| fetcher | `fetch_visitkorea_tourist_attractions`(목록 12→14→28) · `fetch_visitkorea_attraction_details` |
| asset / job | `feature_place_visitkorea_tourist_attractions` / `…_job` |
| schedule | `feature_place_visitkorea_tourist_attractions_daily_schedule` `45 4 * * *` KST, 기본 STOPPED |
| migration | `441_tourapi_attraction_dataset` (dataset·refresh/preview·dataset_wide scope) |
| 자연키 | TourAPI `contentid` |
| 은퇴 | `retire_absent_from_snapshot` — 목록에서 빠진 관광지는 다음 적재에서 은퇴 |

## 1. 실측(2026-11-09, 운영 키, Map code-server 컨테이너)

- 운영 data.go.kr 키로 `areaBasedList2`·`detailCommon2`·`lclsSystmCode2`가 200이다(활용신청 됨).
- 관광지 `totalCount` 12,560. `arrange` A/C/D/Q 모두 같은 수(KorService2의 Q는 이미지 필터가 아니다).
  1,000행 페이지가 허용된다 — 한 sweep 13호출.
- 1,000행 표본: 좌표 결측 0, 법정동 시도·시군구 코드(`lDongRegnCd`·`lDongSignguCd`) 결측 0,
  **`cat1~3` 1,000행 모두 비어 있음**, 공공누리 Type1 492 · Type3 508.
- #1459 누락 목록 대조: 고군산군도(4065077)·부산타워(1277679)·광안대교(128164)·아부오름(1351320)·
  영남알프스 얼음골케이블카(2629010)·사천바다 케이블카(2606216)·성판악(126436)·동래온천
  노천족욕탕(128706)·반월도·박지도(578024, 퍼플섬)는 관광지(12)다. **산막이옛길(28 레포츠)·
  태권도원·국립세종도서관(14 문화시설)은 관광지가 아니다** — 2026-11-10에 14·28을 더해 채운다
  (산막이옛길 1948361 LS011900, 태권도원 1904335 VE090400, 국립세종도서관 1896898 VE090300).
- 문화시설(14) 2,753건(3호출)·레포츠(28) 3,717건(4호출), 둘 다 좌표 결측 0. 합계 19,030건·목록 20호출.
  레포츠의 52%(1,948건)는 숙박 분류 캠핑장(AC05)이다.

## 2. 필드 대응

| TourAPI | Map |
|---|---|
| `title` | `Feature.name` |
| `mapx`/`mapy`(WGS84) | `Feature.coord`(0·범위 밖은 None) |
| `addr1` | 도로명(`…로/길 N` 꼴) 또는 지번 → `Address.road`/`legal`; `addr2` → `facility_info.address_detail` |
| 역지오코딩 | `bjd_code`·`sigungu_code`·`sido_code`·행정동 |
| `lDongRegnCd`+`lDongSignguCd` | 역지오코딩·주소 해석이 모두 실패할 때만 5자리 `sigungu_code` |
| `zipcode` | 역지오코딩 우편번호가 없을 때만(5자리일 때) |
| `tel` | `PlaceDetail.phones` |
| `lclsSystm1~3` | `Feature.category`(§3) |
| `firstimage`/`firstimage2` | `facility_info.image_url`/`thumbnail_url` + `file_sources`(primary/thumbnail) |
| `cpyrhtDivCd` | `facility_info.license`(공공누리 유형) + `attribution`="한국관광공사" |
| `detailCommon2.overview` | `facility_info.overview`(`<br>`→줄바꿈, 태그·entity 제거) |
| `detailCommon2.homepage` | `facility_info.homepage_url`(anchor의 첫 http(s) URL) |

`raw_data` 키는 `TourItem` 필드 이름 그대로다(시각은 ISO) — replay가 `TourItem.model_validate`로
되살린다(`tests/lint/test_replay_raw_is_a_record_snapshot.py`).

## 3. 분류 대응(신 분류체계 lclsSystm → Map)

KorService2 목록은 옛 `cat1~3`을 비워 주므로 2025 신 분류체계로 정한다. 찾는 순서는
3단계 표 → (NA0201~0204는 강·호수) → 2단계 표 → 1단계 표 → `01000000 관광`.

| lclsSystm | TourAPI 이름 | Map |
|---|---|---|
| NA010100·NA010400·NA010500 | 산·오름·봉우리 / 계곡 / 약수터 | `01020100` 산·계곡 |
| NA010200 | 숲 | `01020103` 산림욕장 |
| NA010300·NA030100 | 폭포 / 동굴 | `01020400` 폭포·동굴 |
| NA020100~NA020400·NA030400 | 강·호수·저수지·연못·늪 / 생태습지 | `01020200` 강·호수 |
| NA02 그 밖(섬·염전·항구·해안절경) | | `01020300` 해안·섬 |
| NA020900 | 해변·해수욕장 | `01050100` 해수욕장 |
| NA040100 / NA040200·NA040300 | 국립 / 도립·군립공원 | `01020101` / `01020102` |
| NA040600 | 자연휴양림 | `03030000` 자연휴양림(krforest와 같은 자리) |
| NA040700 | 수목원·정원 | `01030000` 수목원·식물원 |
| NA03·NA04·NA05 그 밖 | 자연생태·지질공원·기타 | `01020000` 자연경관 |
| HS010100·HS010800 | 고궁 / 고분·능 | `01070200` 궁궐·왕릉 |
| HS010400~HS010600 | 고택·생가·민속마을 | `01070400` 한옥·민속마을 |
| HS030100·EX040100·EX040200 | 불교 / 템플스테이 / 사찰문화체험 | `01070100` 전통사찰 |
| HS01·HS02·HS04 그 밖 | 사적·성곽·유물·안보관광 | `01070300` 사적·기념물 |
| HS011200·HS0302~0304 | 기타역사유적 / 기타 종교성지 | `01070000` 국가유산 |
| VE010200 | 타워·전망대 | `01050300` 전망대 |
| VE010400 / VE03 | 분수 / 도시공원 | `01050200` 공원·광장 |
| VE010700 | 댐 | `01020200` 강·호수 |
| VE010800 | 등대 | `01050400` 등대 |
| VE020100~VE020400 | 테마파크·워터파크·동물원·수족관 | `01010100`·`01010200`·`01010301`·`01010302` |
| VE02 그 밖 | | `01010000` 테마파크 |
| VE040300 | 둘레길 | `01080500` 트레킹·둘레길 |
| VE050200 | 리조트 | `03020000` 리조트 |
| VE060100 / VE060200 | 공연장 / 영화관 | `01040300` / `01040400` |
| VE070100·VE070200·VE070500 / VE070600 | 박물관·기념관·과학관 / 미술관 | `01040100` / `01040200` |
| VE090100·VE090200 / VE090300 | 문화원 / 도서관 | `01040600` / `01040500` |
| VE020500·VE06~VE09 그 밖 | 천문대·전시관·컨벤션·교육시설 | `01040000` 문화시설 |
| VE10 | 레저스포츠시설 | `01080400` 레저스포츠 |
| VE11 | 교통시설(공항·기차역·여객선·휴게소·지하철·터미널) | **적재하지 않는다** — `kor-travel-transport`가 정본이라 중복 place가 된다 |
| VE01·VE04·VE05·VE12 그 밖 | 건물·다리·골목·마을·관광단지·기타 | `01000000` 관광 |
| EX050100 / EX050200 / EX05 그 밖 | 온천·스파 / 찜질방 / 웰니스 | `04010000` / `04020000` / `04030000` |
| EX070100 | 유람선·잠수함 | `01080300` 관광유람선 |
| EX01·EX02·EX03·EX07 | 전통·공예·농산어촌·기타 체험 | `01080000` 액티비티 |
| EX06 | 산업관광 | `01000000` 관광 |

관광지(12) 목록에 실제로 오는 코드는 NA·HS·EX 전부와 VE01~VE05·VE020500이다(공식 신분류체계
연계 정의서; 2026-11-09 1,000행 표본에서 VE11 1행). VE06~VE10·VE12는 문화시설(14), LS·AC·VE10은
레포츠(28)에서 온다.

### 3.1 문화시설(14)·레포츠(28) 추가분 (2026-11-10 실측 분포)

| 타입 | lclsSystm | 건수 | Map |
|---|---|---:|---|
| 14 | VE070100 박물관 / VE070200 기념관 / VE070500 과학관 | 584 / 155 / 57 | `01040100` 박물관 |
| 14 | VE070600 미술관·화랑 | 355 | `01040200` 미술관·갤러리 |
| 14 | VE060100 공연장 / VE060200 영화관 | 350 / 19 | `01040300` / `01040400` |
| 14 | VE090300 도서관(국립세종도서관) | 232 | `01040500` 도서관 |
| 14 | VE090100·VE090200 문화원 | 181 | `01040600` 지방문화원 |
| 14 | VE070300 전시관·VE070400 컨벤션·VE090400 문화전수시설(태권도원)·VE090600 학교·VE120300 기타문화시설·VE120100 서점 | 513·21·38·8·154·53 | `01040000` 문화시설 |
| 14 | VE02·VE03·VE10 등 소수 | 33 | §3 표대로 |
| 28 | LS010400 골프 | 231 | `01080100` 골프장 |
| 28 | LS011900 기타육상레저(끝의 괄호·`N코스/구간`·입구를 떼고 `…길`·올레·트레킹·탐방로·산책로·코스로 끝나면 트레킹, 자전거길 제외) | 482 | `01080500` 트레킹·둘레길 / `01080400` |
| 28 | 그 밖의 LS(스키·승마·낚시·수영·래프팅·패러글라이딩 등) | 854 | `01080400` 레저스포츠 |
| 28 | VE100100·VE100200 경기장·스포츠센터 | 193 | `01080400` 레저스포츠 |
| 28 | AC050100 일반야영장 / AC050200 오토캠핑장 | 1,408 / 285 | `03060000` 캠핑장 / `03060100` 오토캠핑장 |
| 28 | AC050300 카라반 / AC050400 글램핑장 | 67 / 188 | `03060202` / `03060201` |
| 28 | AC030100 펜션 / VE050200 리조트 / 그 밖의 VE | 2 / 3 / 4 | `03050000` / `03020000` / §3 표대로 |

`place_kind`는 타입별로 `tourapi_attraction`(12)·`tourapi_culture_facility`(14)·`tourapi_leisure`(28)다.

정본은 코드(`TOURAPI_LCLS3_CATEGORY`·`TOURAPI_LCLS2_CATEGORY`·`TOURAPI_LCLS1_CATEGORY`)이고
`tests/unit/test_providers_visitkorea_attractions.py`가 대표 행과 카탈로그 존재를 고정한다.

## 4. 상세와 일일 한도

data.go.kr 한도는 **오퍼레이션당** 1,000/일이다(`docs/etl/upstream-quota.md` §2). 목록은 13호출이지만
`detailCommon2`는 항목마다 1호출이라 1만 2천 건을 하루에 받을 수 없다.

- run마다 상세 예산 `VISITKOREA_ATTRACTION_DETAIL_BUDGET = 600`(한도의 60%).
- 저장 `raw_data`의 `modified_time`이 목록과 같고 `overview`가 `None`이 아니면 저장 상세를 이어 쓴다.
  받았으나 비어 있는 상세는 `""`로 저장한다(`None`=아직 받지 않음).
- 필요 항목은 **수정된 것 먼저**, 한 번도 받지 않은 것 다음, 각각 contentid 순. 예산 밖의 수정 항목은
  낡은 상세를 이어 쓰지 않는다(이어 쓰면 다음 run이 최신으로 오인한다).
- `failure_kind`가 `rate_limit`/`auth`이거나 쿼터 소진이면 그 자리에서 멈추고, 그 밖의 실패는 그
  항목만 건너뛴다(연속 20회면 멈춤). 상세가 없어도 적재는 계속된다.
- 원천이 상세 없음(`failure_kind="no_data"`)으로 답하면 `("", "")`로 저장한다 — 매 run 다시 묻지 않는다.
- **step 재시도(`retry_number > 0`)는 상세를 받지 않는다.** 받은 상세는 적재가 커밋돼야 남으므로,
  재시도마다 받으면 한 run이 한도를 넘긴다. 최악 sweep은 그래서 600(60%)이다.
- 첫 적재는 상세 600건, 이후 매일 600건씩 — 19,030건이라 약 32일이면 전량이 채워진다(관광지 1만 2천만이면 21일). 매일 도는 경우의 최선값이다.
- 알려진 낭비: 주소 검증에서 버려져 active가 되지 못한 행은 저장 상세가 없어 매 run 다시 고른다(소수).

## 5. 목록 완전성

- `arrange=D`(생성일순). 수정일순은 순회 중 수정된 행을 다른 페이지로 옮긴다.
- 페이지마다 받은 `totalCount`가 한 번이라도 다르면(순회 중 등록·삭제) 실패한다 — 밀린 목록은 경계
  행 하나를 빠뜨릴 수 있고 그 행이 은퇴한다. 고유 contentid 수가 선언보다 적어도 실패한다
  (`VisitKoreaAttractionSnapshotIncomplete`). **타입마다** 0행이거나 응답에 `totalCount`가 없어도
  실패한다 — 원천은 "없음"을 빈 페이지로 주고, provider는 빠진 totalCount를 받은 행 수로 채운다.
  어느 타입이든 실패하면 run 전체가 은퇴 적재 전에 멈춘다. 순회 중 타입이 바뀐 행(14→12 등)은 드물게
  하루 은퇴했다 다음 run에 되살아난다.
- 같은 contentid가 두 번 오면 변환기가 하나만 남긴다(payload hash가 작은 쪽).
- 주소 검증은 `drop` 모드다 — 역지오코딩이 법정동을 못 내는 행(해상 등대 등)만 버리고 기록한다. strict면 한 행이 run 전체를 되감는다. 버린 행은 snapshot에서 빠져 은퇴하므로, 좌표는 있는데 법정동이
  빈 행이 `max(30, 전체의 1%)`를 넘으면 geo 장애로 보고 적재 전에 실패한다(`_ensure_geo_resolved_enough`).

## 6. 중복(dedup)

기본 dedup pair(`DEFAULT_DEDUP_SCOPE_PAIRS`)에 TourAPI 쌍을 더했다(14·28 확장 뒤 13개): 국가유산(0107)↔
krheritage, 자연경관(0102)↔KNPS, 수목원·휴양림↔krforest, 해수욕장↔khoa, 전체↔관광지·박물관 표준데이터,
전체↔MCST 관광·문화·국가유산·자연명소 범주, 관광사업체·유원·문화·사찰·궤도·유람선↔MOIS, 골프장↔MOIS 골프장,
캠핑장(0306)↔MOIS·MCST·KNPS 캠핑장, 골프장↔MCST 골프장(체육시설 01080400은 MOIS 쪽이 너무 커서 제외).
관광지 표준데이터 쌍은 숙박(03)·레포츠 액티비티(0108)를 왼쪽에서 뺀다. TourAPI 쌍은 모두 13개. 양쪽 scope 상한은 40,000(기본 5,000이면 최근 갱신분만 비교된다).

비교는 O(left×right) 순수 Python이라 `core.dedup`에 **판정을 바꾸지 않는 가지치기**를 더했다 — 이름이
완전히 같다고 쳐도 수동 검토 임계값(0.65)에 못 미치는 쌍(범주가 다르고 28 m 밖)은 이름 유사도를 부르지
않는다. 이름 정규화는 캐시한다. 자동 병합은 공용 임계값 0.85 이상(이름·거리·범주가 모두 강할 때)만이고
나머지는 `manual_review` 큐다.

## 7. 라이선스

TourAPI 이용 시 출처(한국관광공사)를 표시해야 하고, 콘텐츠마다 공공누리 유형이 붙는다(Type1 출처표시,
Type3 출처표시·변경금지). Map은 이미지를 원본 URL로 참조만 하고(크롭·리사이즈 없음), 설명은 HTML
태그·entity만 걷어 낸다(문장은 손대지 않는다 — 요약·번역 없음). 유형과 출처는 `facility_info`와
각 이미지의 `file_sources[].payload`(`kogl_type`·`license`·`attribution`)에 남는다. 표시하는 쪽(PinVi)은
출처와 유형을 함께 보여야 한다.

## 8. 남은 것

- 검색 별칭 — 퍼플섬은 원천 이름이 "반월도·박지도", 사천 바다케이블카는 "사천바다 케이블카"다.
- DB 카탈로그 `display_name`은 아직 "contentTypeId 12"라고 적혀 있다(441). 표시용 이름이라 migration을
  따로 두지 않았다 — 다음 카탈로그 migration에 묶어 고친다.
- 같은 범주 dedup 쌍은 가지치기되지 않아, 이름이 같은 전국의 캠핑장이 거리와 무관하게 `manual_review`에
  오를 수 있다(공용 점수 규칙). 첫 refresh의 큐 크기와 소요 시간을 n150에서 보고 필요하면 시군구 blocking.
