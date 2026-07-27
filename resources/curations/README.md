# 큐레이션 공식 목록 데이터

이 디렉터리는 관리자 UI의 수동 입력·CSV 업로드와 실데이터 검증에 사용하는 공식 목록 원본을 보관한다.
모든 Markdown 문서와 CSV 설명은 한국어로 작성하며 CSV 파일은 UTF-8, 쉼표 구분 형식이다.

## 파일

- `template.csv`: 업로드 양식의 헤더만 포함한다.
- `korean-tourism-100-2023-2024.csv`: 공식 선정 100개를 기존 Feature 연결 기준으로
  펼친 membership 110행.
- `korean-tourism-100-2025-2026.csv`: 공식 선정 100개를 기존 Feature 연결 기준으로
  펼친 membership 114행.
- `heritage-visit-campaign.csv`: 국가유산 방문 캠페인 10개 길의 기본·플러스 거점 membership 85개.
- `arboretum-garden-stamp-tour-2026.csv`: 2026 수목원·정원 스탬프투어 운영기관 72개.
- `lighthouse-stamp-tour.csv`: 등대 스탬프투어 시즌 1~6의 105개 stamp point.
- `manifest.json`: 행 수, 공식 출처와 SHA-256 검증값.

## 열 규칙

`collection_key`, `theme_slug`, `edition_key`, `source_item_key`,
`source_component_key`는 기계 식별자다.
`title`과 `place_name`은 공식 표기를 보존한다. `feature_id`는 2026-07-13 prod DB를
읽기 전용으로 조회해 동일 장소라고 안전하게 확정한 경우에만 채웠다.
`address_hint`도 공식 목록에서 개별 주소를 확정하지 않은 경우 비워 둔다.
`metadata_json`은 CSV 셀 안의 JSON 객체이며 복합 관광지, 플러스 거점, 박물관 stamp point 같은 원문 구조를 보존한다.

공식 선정 462개는 복합 장소의 다중 Feature 연결을 펼쳐 총 486행이다. 이 중
217행은 기존 `feature_id`와 연결했고 269행은 비워 두었다. 빈 항목도 import 시
DB에 미연결 공식 item으로 저장되므로 목록 원문은 손실되지 않는다. 인접 항구·식당을
등대로 오인하는 식의 저신뢰 매칭은 하지 않았다. 매칭 신뢰도와 검토 근거는 각 행의
`metadata_json.feature_match_*`에 기록한다.

한국관광 100선에서 `&`로 결합된 선정지는 공식적으로 한 항목이다. 기존 DB에서 여러
구성 장소를 확인한 경우 같은 `source_item_key`를 유지한 채 Feature별 행으로 펼친다.
`source_component_key`는 이때 각 membership을 Feature 연결과 독립적으로 식별한다.
단일 membership은 `primary`, 복수 membership은 기존 공식 순서에 따라
`component-01`, `component-02`처럼 부여한다. 따라서 Feature가 아직 없거나 나중에
다른 Feature로 재연결되어도 같은 component의 운영 상태와 감사 이력이 유지된다.
국가유산 방문 캠페인은 다른 길 또는 하위 코스에 중복되는 membership을 제거하지 않는다.
등대 스탬프투어에는 국립수산과학관, 국립해양생물자원관, 국립해양박물관이 stamp point로 포함된다.
등대 시설 항목의 `metadata_json.suggested_category`는 새 place 카테고리
`01050400`(`관광 > 자연명소 > 등대`)을 사용한다. 박물관 등 비등대 stamp point에는
이 값을 넣지 않는다.

## 공식 출처

- 한국관광 100선: https://korean.visitkorea.or.kr/other/other_list.do?otdid=622bcd99-84fa-11e8-8165-020027310001
- 국가유산 방문 캠페인: https://www.kh.or.kr/visit/kor/html/static/10way.do?key=2407110024
- 수목원·정원 스탬프투어: https://www.koagi.or.kr/www/user/bbs/BD_selectBbs.do?q_bbsDocNo=A00000000604421koagi&q_bbsSn=1001
- 등대 스탬프투어: https://www.lighthouse-museum.or.kr/sea/passport
