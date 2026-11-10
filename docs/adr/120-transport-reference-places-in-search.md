# ADR-120 — transport 기준정보(휴게소·철도역·항구·공항)는 검색되는 Map place로 둔다

상태: 제안·구현 PR (2026-11-09, Map #1459 후속). 첫 적재 실측 뒤 accepted로 올린다.
부분 대체: ADR-114 결정 7의 ②단계(장소 퇴역) 가운데 **휴게소·공항 place 퇴역을 취소**한다.
주유소 place 퇴역 여부는 그대로 열린 결정이다.

## 배경

2026-11-08 PinVi 여행 시나리오 검증(#1459 §2)에서 운영 `GET /search`가 교통 거점을 거의 찾지
못했다. 2026-11-09 읽기 전용 실측(prod alembic 437)은 이렇다.

- **휴게소**: `transport_rest_areas` place 215건(transport `/rest-areas` 215건과 같다)이 이미 있다.
  그러나 이름이 data.go.kr 표기 그대로 "강릉(인천)"·"행담도"라 "강릉휴게소"를 찾으면 이름이
  검색어를 품지 않는다 — trigram만으로는 "대관령쌈밥"·"대관령약국"과 같은 단계에서 다툰다.
- **공항**: `transport_airports` place 15건이 있다(krairport 원천 place는 404 이후 0건 — 같은
  공항의 두 번째 Feature는 없다). "양양국제공항" 1위는 관광 분류(01000000) "설해원(양양국제공항)"
  이었다. 436 순위는 분류 그룹(관광 0 → 공항 1)이 이름 일치보다 앞이라, 이름이 정확히 같은
  공항이 이름을 품기만 한 관광 행을 넘지 못했다.
- **철도역·여객선 터미널**: transport 출처 Feature가 없다. 역은 MCST·영상 후보에서 온 관광 분류
  몇 개뿐이다. transport에는 T3 저변동 기준정보 export(`/v1/service/exports/rail-stations`,
  `/ferry-ports`, transport ADR-013·`docs/map-{rail,ferry}-reference-export.md`)가 있다.
  운영 transport는 아직 `TRANSPORT_MAP_CURRENT_ENABLED=false`라 두 경로가 503이다.

소유자 방향(2026-11-09): Map이 이미 소비하는 transport 자료로 휴게소·기차역·여객터미널·공항
검색을 채운다. transport 쪽 변경·배포는 Codex 몫이고 이 결정은 Map 쪽만 다룬다.

ADR-114는 transport의 **현재값**(유가·돌발)을 Valkey로 옮기고 PG transport Feature를 퇴역하기로
했다. 그러나 Valkey 표면에는 이름 검색이 없고(결정 7 이행의 소비자 확인), 장소는 현재값이
아니라 **기준정보**다. 검색·근처·상세는 PG Feature에서만 나온다.

## 결정

1. **장소는 PG place Feature다.** 휴게소·공항(기존)과 철도역·항구(신규)는 transport가 정본인
   저변동 기준정보이고 Map 검색·in-bounds·상세의 대상이다. ADR-114 결정 7 ②단계의 휴게소·공항
   place 퇴역은 취소한다. 현재값(유가·돌발·주차)은 계속 Valkey다.
2. **새 dataset 둘**(migration `438_transport_reference_places`, provider `kor-travel-transport`,
   `source_kind=internal`): `transport_rail_stations`·`transport_ferry_ports`. job·schedule·큐
   handler·fixture preview는 기존 transport place와 같은 모양이다. schedule은 주 1회(월 04:30·
   04:40 KST)이고 모든 Map schedule처럼 기본 STOPPED다 — transport가 export를 켠 뒤 운영이 첫
   적재를 돌리고 켠다. operation은 켜 둔다: 그 전에 큐(geo 릴리스 계획·갱신 요청)가 job을 부르면
   503 retryable 실패로 아무것도 적재·퇴역하지 않는다(소음은 받아들인다).
3. **계약은 런타임 검증으로 지킨다**(내부 소비자 — 핀·vendoring 없음). Map은 T3 envelope을
   엄격히 읽는다: 페이지마다 같은 `snapshot_id`·`total_count`, `meta.item_count` = 그 페이지 행 수,
   끝에서 행 합계 = `total_count`, 0건 아님, cursor 순환 없음, 200 본문의 `source_status=failed`·
   `source_collected_at` 부재는 계약 위반. `stale`은 transport가 내는 **마지막 완결 성공 집합**이라
   받아들이고 경고만 남긴다(저변동 기준정보 — 옛 집합 그대로이므로 지울 것을 새로 만들지 않는다).
   503(꺼짐·완결 성공 없음)과 410(snapshot 만료)은 아무것도 적재·퇴역하지 않는 retryable 실패다.
4. **퇴역은 완전 snapshot reconcile이다**(`authoritative_snapshot_complete=True`,
   `retire_absent_from_snapshot=True` — 등산로·둘레길과 같은 경로). transport가 빼면 다음 성공
   적재가 그 Feature를 퇴역한다. 빈 집합은 위 3의 0건 거부로 막는다. 페이지 도중 snapshot이
   만료(410)되면 첫 페이지부터 한 번 다시 읽고, 옛 snapshot 페이지와 섞지 않는다.
5. **철도역은 역마다 하나다.** 원천(KRIC dataset 1294)은 운영기관·노선마다 한 행이다. 이름 키
   (공백 제거·끝의 "역" 제거)가 같고 묶음의 어느 구성원에서든 500 m 안이면 같은 역으로 묶는다.
   행은 transport 자연키 순으로 본다 — 입력 순서와 무관하다. Feature 자연키는 anchor의 transport
   자연키(`|` → `::`, ADR-009)이고, anchor는 **이미 적재된 Feature의 자연키인 구성원**(없으면
   자연키가 가장 작은 구성원)이다 — 환승역에 노선이 새로 생겨도 역 Feature가 다시 주조되지 않는다. 좌표 없는 행은 Feature를
   만들지 않는다(#1459 §4). 묶음에 국가철도 운영사(한국철도공사·코레일·에스알) 노선이 있으면
   기차역(06030300), 아니면 지하철역(06030200)이다. transport `source`가 KRIC 일반철도 목록
   (`kric_general_portal` — 운영기관을 비워 낸다)인 행도 국가철도다(2026-11-10 개정: 부산역·강릉역 등
   174역이 지하철역이었다).
6. **항구는 항구마다 하나**이고 자연키는 transport 자연키(`{source}:{port_id}`)다. 새 분류
   `06060000 교통 > 여객선터미널`(maki `ferry`)을 둔다. 좌표가 없는 항구(transport가 가이드라인
   한 점·범위 밖을 null로 낸다)는 Feature를 만들지 않는다.
7. **표시 이름을 저장한다.** 휴게소 "강릉(인천)" → "강릉휴게소(인천방향)", "행담도" →
   "행담도휴게소"; 역 "중앙" → "중앙역"; 항구 "백령도" → "백령도 여객선터미널"(이미 항·터미널·
   선착장을 말하면 그대로). 원천 이름은 raw와 자연키에 남는다. 휴게소는 표시 이름을 payload에
   실어(`display_name`) 다음 적재가 215건 이름을 한 번 다시 쓴다 — 같은 payload는 적재가 건너뛴다.
8. **주소는 Map geo 역지오코딩이다**(다른 transport place와 같다). T3 `admin`은 모양만 검사한다.
9. **검색 순위에 "목적지 이름 일치" 자리를 더한다**(`/v1/features/search`, cursor v4). 순서는
   일치 단계 → bbox → **목적지 이름 일치** → 분류 그룹 → 이름 일치 → 분류 구체성. 목적지는 검색
   그룹 `SEARCH_DESTINATION_GROUP_MAX`(=1) 이하 — 관광·숙박·온천·역·휴게소·공항·여객선터미널이다.
   이름 **전체**가 검색어와 같은 목적지는 분류 그룹보다 앞이다("양양국제공항" → 공항, "서울역" →
   역이 "서울역사박물관"보다 앞). 첫 낱말을 뗀 일치("안동 도산서원")는 관광(그룹 0)에만 이 자리를
   준다 — 숙박 "신라스테이 해운대"가 "해운대"로 "해운대해수욕장" 앞에 서지 않는다. 이름이 정확히
   같은 목적지끼리는 분류 그룹이 가른다. 식음·주차처럼 목적지가 아닌 분류의 이름 일치는 종전대로
   그룹 뒤에서만 가른다 — "하회마을"이라는 서울 음식점이 관광지보다 앞서지 않는다(436 결정 유지).
   **개정(2026-11-10 운영 점검)**: 고유 이름 목적지(역·휴게소·공항·여객선터미널, 그리고 전통시장
   05070000 — 시장도 검색 그룹 1로 올렸다)의 이름 일치는 관광과 같은 그룹 0으로 본다
   (`destination_exact_search_group`). 그래서 같은 이름의 Tier 1만 있는 관광 행(MCST 촬영지·영상
   후보·관광지 표준의 `01000000`)과는 분류 구체성이 가르고 역·공항·시장 자체가 앞이다. 원안은 그
   중복을 결정 10의 dedup 검토에 맡겼지만 운영 병합은 0건이었고 "서울역"·"김포국제공항"·"자갈치시장"
   1위가 관광 행이었다. 숙박은 예외가 아니다(관광지 이름을 쓴 숙소는 그 관광지 뒤).
10. **중복**: 같은 dataset 안은 5·6이 막는다. 다른 출처(MCST·영상 후보의 "서울역" 관광 행 등)와는
    자동 병합하지 않는다 — 기존 cross-provider dedup 검토 큐(ADR-016)가 다룬다. 공항은 transport가
    유일한 원천이라(krairport 원천 0건) 병합할 대상이 없다.

## 결과 — 잃는 것·남는 것

- KRIC 1294는 **도시·광역철도**다. 지하철·광역 노선에 걸친 역(서울·청량리·남춘천·대전·동대구·
  광주송정 등)은 채워지지만, 일반·고속철도에만 있는 역(전주·순천·익산·여수엑스포·신경주·안동·
  단양 등)은 transport에 원천이 없어 여전히 빠진다 — transport 쪽 원천 추가가 필요하다(Codex).
- transport의 `ferry_terminal_references`(터미널 이름·주소, 좌표 없음)는 export가 없다. 이번은
  항구(`/ferry-ports`)만이다. 버스터미널(`/bus-terminals`)은 범위 밖이다(후속).
- 철도역 anchor 행 자체가 원천에서 빠지면(운영기관·노선·역번호·역명이 바뀌면) 그 역은 새 자연키로
  다시 주조된다(옛 Feature 퇴역 + 새 Feature). 노선 추가로는 바뀌지 않는다.
- 분류는 운영기관으로 가른다 — 한국철도공사가 운영하는 수도권 전철 역(선릉·구로 등)도 기차역이다.
  검색 그룹은 둘 다 1이라 순위에는 영향이 없다.
- Valkey 휴게소 상태(`/v1/service/transport/rest-areas`)도 같은 표시 이름을 낸다(스키마 불변).
- 검색 cursor v3은 배포 뒤 VERSION_UNSUPPORTED다(순위 값의 뜻이 바뀌었다).

## 기각한 대안

- **Valkey 상태에 이름 검색 추가** — 검색·근처·상세가 PG와 Valkey 두 표면으로 갈린다. 장소는
  기준정보이고 PG Feature가 정본 표면이다.
- **노선마다 Feature 하나** — "서울역"이 네 번 나온다(#1459 §7 "부속 시설이 위에 온다"와 같은 부류).
- **이름 일치를 분류 그룹 앞으로 통째로 이동** — 이름이 같은 음식점이 관광지를 넘는다(436이 막은
  사례가 되살아난다). 통합 테스트가 이를 고정한다.
- **휴게소·역 별칭(`feature_search_aliases`)으로 해결** — 215+역 수만큼 행을 손으로 둬야 하고
  원천이 바뀌면 낡는다. 표시 이름은 규칙 하나다.

## 이행

PR(이 결정) 머지 → 배포(alembic 438, 카탈로그 행만) → 휴게소 job 1회(이름 215건 갱신) → transport가
`TRANSPORT_MAP_CURRENT_ENABLED`·철도/해운 기준정보 수집을 켠 뒤 철도역·항구 job 1회 → schedule
start. PinVi 재vendor는 필요 없다(admin/service OpenAPI 불변).
