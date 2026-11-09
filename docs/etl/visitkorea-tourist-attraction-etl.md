# visitkorea-tourist-attraction-etl.md — TourAPI 관광지 → place (#1459)

한국관광공사 국문 관광정보 서비스(KorService2, 공공데이터포털 15101578 "한국관광공사_국문
관광정보 서비스_GW") `areaBasedList2`의 **관광지(contentTypeId 12)** 를 1차 place Feature로
적재한다. 축제(`searchFestival2`, `visitkorea_festival_events`)는 표준데이터 1차의 enrichment지만
이 dataset은 Feature를 직접 만든다.

| 항목 | 값 |
|---|---|
| provider / dataset_key | `python-visitkorea-api` / `visitkorea_tourist_attractions` |
| 변환 | `kortravelmap.providers.visitkorea_attractions.tourapi_attractions_to_bundles` |
| fetcher | `fetch_visitkorea_tourist_attractions` → `VisitKoreaAttractionSource` |
| asset / job | `feature_place_visitkorea_tourist_attractions` / `…_job` |
| schedule | `feature_place_visitkorea_tourist_attractions_daily_schedule` `45 4 * * *` KST, 기본 STOPPED |
| migration | `441_visitkorea_attraction_dataset` (dataset·refresh/preview·dataset_wide scope) |
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
  태권도원·국립세종도서관(14 문화시설)은 관광지가 아니다** — 이 dataset으로는 채워지지 않는다.

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
| VE110100·VE110200·VE110400·VE110500·VE110600 | 공항·기차역·여객선·휴게소·지하철 | `06050000`·`06030300`·`06060000`·`06040100`·`06030200` |
| VE11 그 밖 | 버스터미널 | `06000000` 교통 |
| VE01·VE04·VE05·VE12 그 밖 | 건물·다리·골목·마을·관광단지·기타 | `01000000` 관광 |
| EX050100 / EX050200 / EX05 그 밖 | 온천·스파 / 찜질방 / 웰니스 | `04010000` / `04020000` / `04030000` |
| EX070100 | 유람선·잠수함 | `01080300` 관광유람선 |
| EX01·EX02·EX03·EX07 | 전통·공예·농산어촌·기타 체험 | `01080000` 액티비티 |
| EX06 | 산업관광 | `01000000` 관광 |

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
- 첫 적재는 상세 600건, 이후 매일 600건씩 — 약 21일이면 전량이 채워진다.

## 5. 목록 완전성

- `arrange=D`(생성일순). 수정일순은 순회 중 수정된 행을 다른 페이지로 옮긴다.
- 고유 contentid 수가 선언 `totalCount`(페이지마다 받은 값 중 최대)보다 적으면
  `VisitKoreaAttractionSnapshotIncomplete`로 실패한다 — 은퇴 적재 전에 멈춘다. 0행 목록도 실패.
- 같은 contentid가 두 번 오면 변환기가 하나만 남긴다(payload hash가 작은 쪽).
- 주소 검증은 `drop` 모드다 — 역지오코딩이 법정동을 못 내는 행(해상 등대 등)만 버리고 기록한다. strict면 한 행이 run 전체를 되감는다. 소실 하한(절반 넘게 버리면 실패)은 그대로다.

## 6. 중복(dedup)

기본 dedup pair(`DEFAULT_DEDUP_SCOPE_PAIRS`)에 TourAPI 관광지 쌍 8개를 더했다. 비교가
O(left×right) 순수 Python이라 **범주로 묶는다**: 국가유산(0107)↔krheritage, 자연경관(0102)↔KNPS,
수목원·휴양림↔krforest, 해수욕장↔khoa, 전체↔관광지 표준데이터, 문화시설(0104)↔박물관 표준데이터·
MCST, 관광사업체·유원·문화·사찰·궤도·유람선↔MOIS(체육시설·골프장 제외). TourAPI 쪽 scope 상한은
15,000(기본 5,000이면 최근 갱신분만 비교된다). 자동 병합은 공용 임계값 0.85 이상(이름·거리·범주가
모두 강할 때)만이고 나머지는 `manual_review` 큐다.

## 7. 라이선스

TourAPI 이용 시 출처(한국관광공사)를 표시해야 하고, 콘텐츠마다 공공누리 유형이 붙는다(Type1 출처표시,
Type3 출처표시·변경금지). Map은 이미지·설명을 원본 URL·원문 그대로 참조만 하고(크롭·리사이즈·
요약 없음) 유형과 출처를 `facility_info`에 남긴다. 표시하는 쪽(PinVi)은 그 둘을 함께 보여야 한다.

## 8. 남은 것

- 문화시설(14)·레포츠(28) — 태권도원·국립세종도서관·산막이옛길은 다른 contentTypeId다. 같은 변환기로
  dataset을 더할 수 있다(분류표는 14·28의 lclsSystm도 덮어야 한다).
- 검색 별칭 — 퍼플섬은 원천 이름이 "반월도·박지도", 사천 바다케이블카는 "사천바다 케이블카"다.
