# KNPS 대피소 공식 원천 확인·재적재 인계

## 담당과 적용 범위

Codex는 WSL 수정·검증·머지를, Claude Code는 공식 원천 확인과 운영 배포·적재·최종 UI를 담당한다. 이 문서는 운영 완료 증거가 아니다. 공급자 변경은 [python-knps-api PR18](https://github.com/digitie/python-knps-api/pull/18), 소비자는 [Map PR1454](https://github.com/digitie/kor-travel-map/pull/1454)다. Map pyproject의 실제 병합 SHA와 geo extra가 실행 이미지에 포함되는지 확인한다.

이미 머지된 Map1452/1453과 운영 결과를 보존한다. 화장실325·야영장36·문화자원554·국립공원 경계21건은 Claude Code의 Map1450 댓글 기록이며 이번 Codex 운영 재확인 수치가 아니다. 보호지역은 여행 지정 allowlist·해상 역지오 실패 drop 정책을 유지한다. 위험지역 POINT와 일반명 선형시설은 미적재이며 새 적재 대상으로 되돌리지 않는다.

## 공식 원천 검증 결과 (2026-11-09, Claude Code)

아래 1~4 절차를 끝냈다. 결과는 python-knps-api `docs/knps-api.md` "공식 원천 확인" 절과 PR19가 정본이다.

- 기존 카탈로그 URL `FILE_000000000377005`는 2013년 중첩 SHP 8건(한라산 7·오대산 1)이었다. PR18이 정상 처리하지만 중청·장터목·세석이 없다.
- 포털 현재 배포본 `FILE_000000003681543`(_20230928, SHA256 `3c73d523…cdfc9`): 평면 SHP 22 Point, CPG UTF-8, PRJ EPSG:5186, 전역 ID 없음(로컬 `순번`). PR18은 DBF 필드명 10 bytes 잘림으로 이 파일을 거부했고 PR19(`3b89895`)가 고쳤다. 카탈로그는 verified.
- source_id는 `shp:<sha256>`(멤버 경로+순번)이다. KNPS point loader는 snapshot에서 빠진 행을 retire하지 않는다. 운영 provider_dataset 57에는 기존 행이 없었다(identity 0).
- Map 핀은 PR19 병합 SHA로 올렸고 공식 fixture가 public client→Map 변환 22 place를 고정한다.

## 공식 원천 검증 (원래 절차)

1. 제공자가 현재 배포하는 knps_shelters artifact의 SHA256·다운로드 시각·바깥/중첩 ZIP 멤버명을 기록한다. 테스트의 합성 DBF 필드나 EPSG:5179를 공식 사실로 쓰지 않는다.
2. 실제 Point/PointZ/PointM 레이어의 ID_CD·이름 필드·중복 ID·활성/삭제 행·NULL geometry·PRJ·CPG를 확인한다. Polygon 부지는 place로 변환하지 않는다. 전역 ID는 보존하고 로컬 ID만 멤버 범위를 쓴다.
3. PRJ가 없거나 해석 불가하면 추정 CRS를 강제로 넣지 않는다. 좌표계·인코딩·시설 이름의 공식 근거를 먼저 확보한다. 이 작업에서 catalog는 needs_verification으로 남겼으며, 실제 증거 후 공급자 catalog 상태를 별도로 갱신한다.
4. 실제 public read_place_records 결과의 시설 수·고유 source_id·유효 WGS84·한글 이름과 raw provenance를 대조한다. parser 성공만으로 Map 적재·지리적 주소 검증 성공을 선언하지 않는다. ZIP/행 구조가 다르면 source 오류를 보존하고 python-knps-api17에 증거를 추가한다.

## Map preview·실행·완료 증거

1. 운영 provider catalog에서 provider=python-knps-api, dataset_key=knps_shelters의 실제 dataset을 찾는다. 환경별 숫자 ID를 하드코딩하지 않는다.
2. provider_dataset 요청의 partition_key=dataset_wide, job_name=feature_place_knps_points_job으로 preview한다. 확정 실행 manifest에 해당 dataset 하나만 있고 visitor_centers·다른 dataset이 섞이지 않는지 확인한다.
3. 기존 운영 사전 점검 뒤 같은 요청을 실행한다. 빈 run_config로 job을 직접 실행하면 기본 dataset이 선택될 수 있으므로 요청·schedule의 dataset 결박을 유지한다. 실행 활성화나 부하 제한을 우회하지 않는다.
4. request/job/Dagster run ID와 원천 수·변환/skip/적재 수·실패 원인을 연결한다. 이름 누락·잘못된 주소·빈 결과를 정상 적재로 바꾸지 않는다. Point에 대한 기존 주소 검증은 완화하지 않았다.
5. provider identity 기준 shelter 수와 검색·in-bounds의 place/category03080100·mountain_shelter·shelter marker를 확인한다. 같은 source의 재실행은 시설 중복을 만들지 않아야 한다. 같은 ID의 좌표만 갱신한 원천은 새 raw hash/source version과 같은 시설 identity로 반영돼야 한다.
6. Pinvi 실제 검색·지도 선택·상세 UI와 화장실·야영장·문화자원·국립공원 경계의 기존 동작을 확인한다. Polygon 부지와 미적재 위험·선형시설이 노출되지 않아야 한다. 팔레트·기존 분류 정책은 변경하지 않았다.
7. 성공한 dataset별 schedule만 선택해 실행 설정과 execution_scopes를 확인하고 운영 주기로 활성화한다. 새 schedule의 기본 STOPPED와 실제 활성 상태는 구분한다. 전체 KNPS schedule을 한꺼번에 켜지 않는다.

공식 fixture 검증과 실제 운영 적재·최종 UI가 끝난 뒤 python-knps-api17과 T-KNPS-DATA-GAPS의 남은 체크를 갱신한다. source/consumer 머지, WSL 합성 회귀·격리 DB·브라우저 성공은 운영 완료와 별도로 기록한다.
