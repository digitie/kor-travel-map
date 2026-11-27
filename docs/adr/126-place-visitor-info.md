# ADR-126 — place 방문 안내는 typed `PlaceVisitorInfo` 하나로 모으고, TourAPI 상세는 오퍼레이션별 예산으로 점진 백필한다

- 상태: proposed (2026-11-27, 구현 PR과 함께. 배포 뒤 첫 백필 run의 op별 수신 수·채움률을 실측하면 accepted)
- 날짜: 2026-11-27
- 결정자: Claude(설계·구현), 소유자 승인("권장안 대로" — 상세 콘텐츠 소스 조사 보고서 §5의 3·4·5순위)
- 관계: ADR-018(자유 dict 금지)을 `facility_info` 안의 방문 안내까지 넓힌다. ADR-006(provider public client 직접
  사용)·ADR-044(provider 로컬 우선)를 그대로 따른다. migration 없음.

## 컨텍스트

- PinVi 상세 카드에 이용시간·휴무·주차·요금·이미지·무장애·반려동물이 없다. 원천은 이미 있다.
  - TourAPI(KorService2) `detailIntro2`(유형마다 접미사가 다른 이용시간·휴무·주차·요금 필드), `detailImage2`(추가
    이미지 + 공공누리 유형 `cpyrhtDivCd`), `detailPetTour2`(반려동물), 무장애 `KorWithService2/detailWithTour2`.
    `python-visitkorea-api`가 전부 감싼다(핀 `151ef90`).
  - 국가유산청 `SearchKindOpenapiDt`의 설명문 `content` — Map은 이미 이 상세를 건마다 부르면서 `content`를 버렸다.
  - 박물관·미술관 표준데이터의 관람시간·휴관·관람료·소개·교통, 휴양림 표준데이터의 입장료·주요시설·수용인원·숙박 —
    변환기가 버렸다.
- TourAPI 개발계정 한도는 **오퍼레이션마다** 하루 1,000이다. 관광지·문화시설·레포츠는 약 1만 8천 건이다.
- `PlaceDetail.facility_info`는 provider별 자유 dict다. 새 필드를 거기에 흩으면 원천마다 이름이 갈라지고(ADR-018이
  막으려던 것), 새 DB 컬럼을 만들면 DB 쪽 protocol 함수(`_425`~`_431` 등) 전부를 바꿔야 한다.

## 결정

1. **typed 모델 하나.** `kortravelmap.dto.PlaceVisitorInfo`(`extra="forbid"`)가 원천 무관 방문 안내다 —
   `description`·`usage_hours`·`rest_days`·`parking`·`fee_text`·`fees[]`·`discount`·`reservation`·`inquiry`·
   `transport`·`facilities`·`capacity`·`accommodation_available`·`pet_note`·`parking_fee`·`images[]`·`accessibility[]`·
   `pet_policy`, 그리고 `source`·`attribution`·`reference_date`. 소비자는 모르는 enum 값·필드를 무시한다
   (원천이 늘면 값이 더해진다). 배지는 원문을 해석하지 않고 `accessibility`가 비지 않음·`pet_policy` 있음으로
   판단한다. "없음"은 자리표시로 지우지 않는다(휴무 "없음"·주차 "없음"은 뜻이 있다).
2. **저장 위치는 `facility_info["visitor_info"]`.** `PlaceDetail`의 validator가 그 키를 `PlaceVisitorInfo`로
   검증·정규화한다(맞지 않으면 `ValidationError`, 출처뿐인 빈 안내는 키째 뺀다). `facility_info`는 DB에서 통째
   jsonb라 **DB 컬럼·protocol 함수·migration이 바뀌지 않는다.**
3. **원문 그대로.** 태그·HTML entity·공백만 정리한다. 요약·재작성·번역 없음. 박물관 평일·공휴일 시각은
   `business_hours`(요일 구간)로 바꾸지 않는다 — "공휴일"은 요일이 아니다. `HH:MM`으로 맞춘 한 줄 원문이다.
4. **이미지 라이선스는 이미지마다, fail-closed.** `PlaceImage.license`(`ContentLicense`)는 공공누리 유형 0~4가
   있어야 한다. `derivatives_allowed`·`commercial_allowed`는 유형에서 결정된다(3·4유형 → 변경 금지). 유형을 모르는
   이미지는 담지 않는다. 원본 URL만 참조하고 Map은 썸네일을 만들지 않는다.
5. **국가유산 이미지는 담지 않는다.** 이미지 API `SearchImageOpenapi`의 `imageNuri` 값(`B/F`·`D/F` — 2026-11-27
   실호출)이 어떤 공공누리 유형인지 국가유산청 문서로 확인하지 못했다. 저작권정책은 "공공누리 마크가 붙은 저작물만
   자유이용"이다. 코드표가 확인되고 provider가 typed `images()`를 내면 그때 담는다. 설명문은 담는다
   (출처 "국가유산청, www.khs.go.kr", 소유자 지시). 설명문 텍스트의 공공누리 유형 표기도 Open API 쪽에서는
   확인하지 못했다(국가유산청 보도자료 텍스트는 제1유형) — 근거 확인은 후속이고, 확인 결과가 다르면 설명문도
   같은 fail-closed로 뺀다. provider가 이미 태그를 걷고 entity를 푼 본문이라 Map은 다시 정리하지 않는다
   (다시 걸면 `<삼국유사>` 같은 꺾쇠가 지워진다).
6. **TourAPI 상세 = 오퍼레이션별 점진 백필.**
   - op 네 개(`intro`·`images`·`pet`·`accessibility`)마다 하루 예산이 설정값이다
     (`KOR_TRAVEL_MAP_VISITKOREA_DETAIL_{INTRO,IMAGE,PET,ACCESSIBILITY}_DAILY_BUDGET`, 기본 900 = 개발계정 1,000 − 수동
     조회 몫 100). 운영계정 증설 뒤 env만 올린다. 관광지 run은 하루 한 번이라 run 예산 = 하루 예산이다. 축제는 이 넷을
     쓰지 않는다(`detailCommon2`뿐).
   - 받은 값은 `raw_data["tourapi_detail_ops"][op] = {modified_time, data}`로 남는다. 다음 run은 목록
     `modified_time`이 같은 op을 다시 받지 않는다. 빈 값은 "받았으나 원천에 없음"이다.
   - 우선순위: 큐레이션 포함(+10) + 검색 인지도(`feature_search_prominence` 0~9) 점수 → 낡은 것 먼저 → 관광지(12) →
     문화시설(14) → 레포츠(28) → contentid. PinVi 여행 일정의 장소별 신호는 Map에 없다 — 큐레이션 포함이 가장 가까운
     신호다. 점수를 못 읽으면 경고 후 점수 없이 진행한다.
   - 낡은 op 값(목록 수정 시각이 바뀜)은 다시 받을 때까지 그대로 보인다. 목록 수정 시각은 아무 필드 편집에도 바뀌므로
     받기 전에 지우면 맞는 안내까지 사라진다. 그 op은 우선 다시 받는다.
   - 한 op이 한도·인증 실패로 멈춰도 다른 op은 계속한다. replay와 step 재시도는 받지 않는다(저장값만 이어 쓴다).
   - **하루 상한은 KST 날짜별 장부로 지킨다**(Dagster instance KV `kor_travel_map/tourapi_detail_calls/<op>/<날짜>`). 호출 전에
     예약하므로 재실행·수동 launch·적재 실패 run도 센다. 장부가 없는 실행(큐 runner의 직접 context)은 상세를 받지 않는다
     (fail-closed — 상세는 schedule run이 채운다). `detailCommon2`(관광지 850·축제 50, 하루 900)도 같은 장부다.
     하루 상한·run 예산은 전부 env(빈 값 = 코드 기본값)라 운영계정 증설은 설정 변경뿐이다.
   - 무장애·반려동물은 그 서비스 `areaBasedList2`(별도 오퍼레이션, 제목순) 목록에 든 contentid만 묻고 상세도 같은 서비스
     (`KorWithService2/detailWithTour2`·`KorPetTourService2/detailPetTour2`)에서 받는다 — 각 서비스 활용신청이 따로 필요하다. contentid가 국문 서비스와
     같다는 전제는 배포 뒤 표본으로 확인한다. 목록 실패면 그 op만 이번 run 쉰다.
   - TourAPI 관광지 `overview`·대표 이미지(`firstimage`, 목록 공공누리 유형)도 `description`·`images[0]`에 싣는다(정본 하나).
     `facility_info.overview`·`image_url` 평면 키는 기존 소비자가 옮길 때까지 남는다. 축제는 저장을 바꾸지 않고 공개 읽기에서
     `payload`의 소개·대표 이미지를 `visitor_info`로 투영한다 — 저장값이 아니라 ETag에 투영 판을 섞는다. 서비스 목록에서
     빠진 관광지의 옛 무장애·반려동물 값은 남는다(후속: 빠지면 숨김).
7. **공개 API는 typed 필드 하나.** `GET /v1/features/{id}` 응답에 `visitor_info: PlaceVisitorInfo | null`을 더하고,
   같은 값을 `detail.facility_info`에서는 뺀다(정본 하나). 저장값이 모델에 맞지 않으면 500 대신 `null`이다.

## 결과

- 긍정: 원천 넷의 방문 안내가 한 계약으로 나간다. DB 변경 없이 typed 검증이 쓰기 경계(`PlaceDetail`)에 걸린다.
  한도는 설정 한 줄로 올라간다.
- 부정: `facility_info` 안 키 하나에 대한 typed 검증이라 DB 수준 제약은 없다(쓰기는 전부 `PlaceDetail`을 지나므로
  검증 실익은 같다). 운영자 override 단위가 `place.facility_info` 열 전체라, 운영자가 그 열을 고친 feature는
  방문 안내도 그 시점 값으로 굳는다(provider 갱신이 막힌다 — 기존 `overview`와 같은 성질). 하위 키 override는
  후속이다. 박물관 raw에 새로 더한 키는 값이 없으면 넣지 않는다 — 이 기능 전 저장 원본의 replay hash가 같아야
  한다. 개발계정이면 op마다 1만 8,894건 ÷ 900 ≈ 21일이 걸린다. 무장애·반려동물 서비스는 서비스키에 따로
  활용신청이 있어야 한다(없으면 첫 호출에서 그 op만 멈춘다).
- 후속: 국가유산 `imageNuri` 코드표 확인 + `python-krheritage-api` typed `images()`; TourAPI 운영계정 증설 뒤 예산 상향;
  기존 국가유산 대표 이미지(`file_sources`, 라이선스 없음)의 표시 정책.
