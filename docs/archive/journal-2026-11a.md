# journal 아카이브 — 2026-11 (a)

[현행 기록](../journal.md)에서 docs/tasks-rule.md §8에 따라 완전한 절을 원문 그대로 분리했다. 읽기 전용 이력이다. 상대 링크만 `docs/archive/` 기준으로 다시 맞췄다.

## 2026-11-12 — origin/main 병합·925c 리뷰 기준 보존

- 기존 리뷰 commit925c48c74는 재작성하지 않고 origin/main41de16d을 merge한다.
  충돌한 CHANGELOG/journal/resume3개는 양쪽 기록을 모두 남겼다.
- main의 검색 지역 별칭·낱말 덮기 SQL/cursor v6·alembic450과 관련 테스트12개 제품/검사 파일은
  incoming 원문과 일치한다. frontend 전체·root package/lock·vendor는925c와 동일하다.
- 검색/SQL/forward-only 마이그레이션/속성 SQL 단위4개 파일171개 통과,
  유입 Python 파일 ruff와 application migration graph --check 통과.
  DB/API/Dagster lifecycle이나 실제 migration은 실행하지 않았다.
- 부모 workflow는925c에서 이미 커밋·push했다. 원A/B는925c immutable 기준으로 계속하고
  이번 merge-only delta는 별도 재검토한다. common49와 후속 C10/FocusScope 산출물 정책은
  부모/Harvey 소유이며 이번 병합에서 common/산출물은 수정하지 않는다.
- 남은 gate는 정확 merge HEAD CI·delta recheck·최종 release freeze·main merge/부모 go다.
  Map UI-only 배포는 공식 Manager pin/receipt 승격 경로 확정 후에만 진행한다.
  증거는 taskroot validation/map-merge-20261112/에 보존한다.

## 2026-11-12 — c9 정식 D 전체 runner·cleanup exit0 확정

- exact e3ea216c128c3e7ef5346b17db6d4ec3fd5272a0의 새 production 이미지로
  정식 D286/286·flake0·skip0·strict inventory 일치를 확인했다.
- 전체 runner passed/exit0/issues[]이며 독립 exact 조회도 소유 container/network/image 잔존0이다.
  과거 후보6 cleanup exit2와 c8 unit431/1 원시 로그는 그대로 보존했다.
- c9 전체 unit432, reporter/cleanup37, lint/type, Doctor324files 진단0, guard/canonical,
  npm tree/NextSharp/CSS 공개 API 모두 통과했다. 전체 unit은 worker2로 실행했다.
- 사용5개 artifact·원장·lock은 최신 integration-9-review와 일치한다.
  UI/tokens installed checker byte 일치도 확인했다. 후속 commit은 문서만 갱신한다.
- 원시 증거와 프로세스·정리 증거는 taskroot validation/map,
  최종 인계는 AGENT-HANDOFF-codex-map-weather.md다.
  부모 중앙 workflow는 보존·제외하고 독립2리뷰/CI/merge/부모 go 뒤 UI 배포한다.

## 2026-11-12 — c9 정책 검사기와 동일 runtime 산출물 동기화

- integration-9-review의 사용5개 vendor/원장/lock SHA512를 대조했다.
  UI·tokens의 이전 c8과 다른 archive member는 check-dependencies.mjs 하나씩뿐이다.
  runtime·CSS bytes와 core/web/Lightning CSS fix.4는 그대로다.
- explicit npm12 lock-only 설치로 같은 파일명 UI/tokens의 integrity를 갱신했다.
  실제 설치·guard·Doctor·fresh286 D와 cleanup exit0는 n150 전용 cached checkout에서 확인한다.
- c8 단위검사431통과/1실패 원시 로그를 보존했다. 수동중복판정의 실패 안내 대기를 재검증하며
  실패/skip 허용이나 타임아웃 완화 없이 원인을 확인한다. 부모 중앙 workflow는 제외·보존한다.

## 2026-11-12 — c8 동일 산출물 채택과 정식 D 정리 gate 재검증

- 공통670a753의 integration-8-review UI/tokens와 동일 core/web, Lightning CSS fix.4를
  원장 SHA512 대조 후 채택했다. root/frontend 직접 dev 의존성과 root $lightningcss override를 연결했다.
- 같은 파일명의 이전 UI/tokens integrity가 npm 기본 lock-only에 남아 명시 package install로 갱신했다.
  WSL Map node_modules는 만들지 않고 실제 설치/검증은 n150 기존 전용 checkout을 재사용한다.
- Docker 지연 삭제는 최대5분의 제한된 부재 재조회로 확인한다. 소유 label/ID 검사는 유지하고
  성공한 빈 조회만 인정한다. CLI close 뒤 stdout을 판정하며 남은 예산을 각 조회 timeout에 전달한다.
- 정식 D 전체286개와 모든 gate는 후속 결과를 원시 로그와 함께 기록한다. 부모 workflow는 제외·보존한다.

## 2026-11-11 — Map 정식D 브라우저286통과·Docker 후행 정리 인계

- exact9d187a61d에서 D 브라우저286/286·flake0·manifest일치, Playwright child exit0.
  runner는 n150 Docker removing 지연으로 cleanup_container_remaining exit2였다.
  후행 exact 조회에서 소유 container/network/image 잔존0과 worker/runner 종료를 확인했다.
- unit427·reporter32·lint/type/build33routes·Doctor322files0·최신 localcanonical 통과.
  원시exit2는 보존하고 인프라 gate 재확인은 부모 CI에 인계한다.
- 부모소유 workflow는 커밋에서 제외·보존. 최종pack/foundation CI/독립2리뷰/merge/부모go 뒤 배포한다.
  [검증·실제배포계획](../reports/common-unification-20261111.md), taskroot의 전용handoff/리뷰패킷 참조.

## 2026-11-11 — Map 전체 브라우저 통과와 checkpoint gate 정렬

- exact1ce5a1148에서 286/286 통과·flake0을 확인했다. A는 과거 실패 재현 단계이므로
  성공 상태를 거부했다. 기존 manifest도 284개에 머물러 실제286개 inventory와 달랐다.
- 실패·skip 허용 목록은 빈 상태로 유지하고 관측한286개 identity hash만 재고정했다.
  정식 성공 checkpoint D로 다시 검증한다.
- Docker 정리 CLI 1초 제한 때문에 제거 확인이 실패했다. 소유권·ID·잔존 검사는 유지하고
  명령 제한을30초로 늘려 지연된 daemon 응답을 기다린다. 운영 자원은 수정하지 않는다.

## 2026-11-11 — Map 두 번째 checkpoint285/286와 마지막 fixture 정렬

- 지도/탭 포커스/History/초안 복원은 통과했다. 남은1개는 orphan run의 summary fixture누락이다.
- summary/list/detail에 같은 실패 run을 넣고 공통 상세 버튼 이름으로 검사한다.
  e2e 타입/lint/spec로딩 통과. 앱runtime source변경은없다.
- 부모소유 common-frontend-policy.yml은제외·보존, localcanonical은최신외부policy와원장으로통과.

## 2026-11-11 — 후보6 브라우저 회귀와 fixture 보완

- 첫 checkpoint230통과/56실패를 보존했다. 지도 public mapStyle 복구는 브라우저에서 확인됐다.
- 지도/URL 탭을 Enter·Space 확정으로 지정하고 중복 History 기록을 막았다.
  Alert data-variant와 Radix data-state 검사, canonical transport/Dagster 조회 fixture를 보완했다.
- unit427/427·lint/type/Doctor0/guard 재통과. exact 후속 checkpoint 결과를 별도로 기록한다.

## 2026-11-11 — common 후보6와 키 없는 지도 public mapStyle 복구

- common `a14301c` / upstream `9a7a348`의 동일 tgz·원장을 설치했다. core는 1.0.1로
  갱신하고 1.0.0 활성 참조·vendor를 제거했다. 라이선스/NOTICE/src 동봉 원본 bytes를 보존했다.
- Map wrapper는 빈 키·공백·CHANGE_ME에 모듈 상수 style을 전달하고 실제 키는 upstream 기본 style을 쓴다.
  자체 지도 생성자·가짜 키·비공개 소스 import는 추가하지 않았다.
- 자동완성 기존 2건과 형태 회귀 6건을 포함한 unit427/427, lint/type/build33routes/Doctor0/
  AST·원장 guard/npm tree/NextSharp 통과. n150 exact checkpoint와 최종 freeze/review/CI는 후속 gate다.
- [후보6 검증 기록](../reports/common-unification-20261111.md), [산출물 출처](../third-party-common.md).

## 2026-11-11 — 관리자 common Radix/VirtualTable·지도 public API 통합 후보

- 모든 admin 표를 common VirtualTable로 연결하고 Radix primitive/검색 Popover를 채택했다.
  최신 exact 의존성, Zod/RHF/Zustand/Pretendard 실제 사용과 CI AST/무결성·Doctor gate를 적용했다.
- candidate5 lint/type/build/guard/Doctor 진단 0. unit 419/421 통과, common LoginForm 자동완성
  2건은 부모 수정 요청. 최종 freeze·n150 격리 e2e·독립 리뷰·CI/merge/부모 go 전 배포하지 않는다.
- [구현·검증·배포 계획](../reports/common-unification-20261111.md), [ADR-123](../adr/123-common-admin-ui.md).

## 2026-11-12 — 검색 순위 1단계(alembic 450)

- 11-11 e2e의 "일반 질의에서 기대 행이 밀림"을 prod 읽기 전용으로 재현: 10건 중 다수는 기대값 문제였고, 진짜 결함은 영종 별칭(옛 중구)·분류 낱말 tail 일치·붙여 쓴 나머지("서프카페")·인천공항 별칭 부재. 44질의 평가 hit@1 39→40(450 적용 시 41). 적대 리뷰 반영: 한 글자 낱말 제외, 닻·긴 나머지는 문자·숫자 수로 판정.

## 2026-11-11 — ADR-122 개정: weather 멤버십 digest·clock epoch

- 세대마다 멤버십 장부(만료 묶음 유지)를 두고 증분 뒤 weather digest와 비교, 다르면 전량. 전량도 못 보는 미래 시각 없는 행이 있으면 검증 불가 사슬로 표시해 하루 주기에 맡긴다. epoch 바뀌면 전량.

## 2026-11-10 — ADR-122 weather 예보 증분 적재

- 단기·외부 전량이 odroid eMMC cold 1,174·674초라 run이 ReadTimeout. since 증분을 지금 Valkey 세대에 병합(기준 세대 CAS), cursor는 세대 meta. since엔 tombstone이 없어 24시간마다 전량. migration 없음.

## 2026-11-10 — 박물관·관광지도 공개 파일

- 박물관 403·관광지 00, 둘 다 파일로. 파일 행에 INSTT_CODE(기관 코드, 박물관 215·관광지 164개)가 실려 키가 지자체로 뭉칠 뻔했다(리뷰 HIGH) — 세 표준 dataset 키에서 instt_code 제외.

## 2026-11-11 — 영문 괄호 이름 검색·대피소 現 표식

- 별칭 행 대신 검색 SQL이 끝 라틴 괄호에서 한글·영문 이름을 떼어 이름 일치로 본다(migration 없음). 짧은 한글+긴 괄호는 후보도 못 돼 ILIKE 팔 추가. knps-api a472a37 핀; 같은 raw 재적재가 이름을 안 고쳐 고친 이름을 해시에 넣었다.

## 2026-11-11 — 촬영지 미분류 회귀(dataset 48)

- 원인은 #1480이 아니라 5fcb015(11-04 "실제 MCST 분류 반영")다. 테마 목록의 업종 없는 행을 미분류로 내렸고, 촬영지 CSV는 TYPE이 8,803/8,803 비어 있다. 11-10 재적재(같은 원천 head 재투영)가 처음으로 그것을 운영에 반영했다. 촬영지 fallback을 목록 분류(관광 Tier 1)로 — 캠핑 목록과 같다. 운영 복구는 핫픽스 회전 뒤 dataset 48 재적재(손 SQL 없음).

## 2026-11-10 — 축제 원천 TourAPI 단독(449)

- 소유자: 표준데이터 축제 아예 쓰지 않음(키 403). TourAPI searchFestival2가 1차 event(879건, 좌표 100%). 449가 표준축제·보강 op 끄고 비활성, 1,296건 퇴역. PinVi 참조는 삭제된 시험 여행뿐(M05 없음). detailCommon2는 관광지 600+축제 300.

## 2026-11-10 — 주차장 키 403 → 공개 파일

- 운영 키가 주차장·박물관 Open API에서 403(관광지는 00). 주차장 파일 18,994행·고유 17,878, prod 키 17,986 중 17,875 일치(은퇴 경로 아님). 박물관·관광지는 다음 PR.

## 2026-11-10 — #1475 admin 부분 검색 3~12 s

- 원인: lower(name) keyset을 36만 행 걸으며 행마다 ILIKE, all은 raw_data 505 MB 전 스캔. 447 비부분 trigram 6개로 후보 id를 먼저 모으고(≤2,000) 넘치면 종전 훑기. raw_data 검색 제거. D2 run_id 6~12 s→약 50 ms.

## 2026-11-11 — #1468 A R4 전환 실행기

- 실행기 `ktmctl mcst-theme-transition`(계획 파일 sha 확인, batch = transaction 하나, protocol EX), 장부 `ops.mcst_theme_transition_batches`·`_items`, M05 사건 출처 일반화(`origin_kind` + 출처별 생성 열 FK, payload 모양 그대로 — PinVi 재vendor 불필요).
- 적대 리뷰 반영: batch 정체에 크기 포함, error 하나면 batch 되감고 멈춤, 사건 writer가 장부를 command·전이·병합 이력과 대조, 퇴역 master 병합 거부, 대상 quality 확인, 패자의 열린 dedup 검토 행 닫기, before_state에 대상 link·curation 행 전체.
- 표본(규칙 고치기 전): 대부분 목록 ≈100%, 레저활동·촬영지·반려 collapse가 낮았다(부속 시설 `…3관`·`…야영장`, 번호 동, 100m 넘는 한쪽 지점). 이름 쌍 거절 규칙을 더하고 표본은 회전 뒤 다시 뽑는다.

## 2026-11-10 — #1468 A R1·R3 구현·R2 운영 dry-run

- 붙임 엔진(owner·sticky·redirected·matched·created·ambiguous·unresolved), 전환 계획기 `ktmctl mcst-theme-plan`, migration 446, 속성 필터·응답·catalog·판정 조회 API.
- R2(운영 읽기 전용, 리뷰 반영 뒤 3분): MCST 88,007 → retire 20,396·attach 7,501·collapse 7,073·keep 51,064·ambiguous 1,973(대부분 비MCST master끼리 동점 — B dedup 뒤 줄어든다). PinVi 참조 1,020행(161 Feature, 전부 attach/collapse — rebind 가능).
- 첫 계획 질의가 `publication_state IN (...)` 때문에 부분 GiST 색인을 못 써 30분 넘게 돌아 취소했다(색인 조건 그대로 쓰도록 고침). tier 2 동점을 ambiguous로 보던 규칙이 ambiguous의 3/4를 만들었다.
- 적대 리뷰 반영: 강등은 MCST link만(MOIS 승자 판정 회귀), 부재 가드 강화, 비병합 퇴역은 owner로, 빈 snapshot 손실 가드, 계획기의 비MCST master 제외·사슬 collapse 차단·물려받은 attach 분류 재확인.

## 2026-11-10 — 운영 검색 점검(#1476~#1478)

- 역·공항 1위가 MCST 촬영지·영상 후보 01000000이었다(그룹 0 < 1). 고유 이름 목적지의 이름 일치를 그룹 0으로, 시장도 목적지 그룹으로. 일반철도 행은 operator가 비어 지하철역(174). 여수엑스포는 transport 좌표 null(transport#179). 504는 PinVi 도달 전.

## 2026-11-10 — 휴양림 ↔ MOIS 숙박은 휴양림 master

- 소유자 결정: 산림청 자연휴양림 dataset 보정 55(MOIS 50 위). #1472 뒤 이 쌍은 MOIS가 이겼다. 수목원 115쌍도 그대로 휴양림 master.

## 2026-11-10 — #1468 D 국가유산 행사 회차 묶음

- prod 5,286행=행사 1,316개(같은 행사가 seqNo를 바꿔 반복, 좌표 0). 행사명·단체·지역·장소로 묶고 회차는 payload에. 좌표는 같은 시군구 동명 장소 Feature(310개, 23.6%)→번지 정지오코딩. 옛 키는 retire, PinVi 참조 0.

## 2026-11-10 — #1468 B·C dedup 재가동·원천 겹침 쌍

- prod 병합 0건: master 선정이 좌표→updated_at→원천이라 원천 순위가 사실상 안 쓰였다. 원천을 updated_at 앞으로, 표준데이터 35·MCST 20·YouTube 5, dataset 보정(KNPS 문화자원·수목원·산림청 등산로 40).
- 쌍 3개: 캠핑 MOIS↔KNPS·휴양림=수목원(이름 일치)·등산로↔KNPS 탐방로(선형 겹침). MCST 쌍 4개는 ADR-121 attach로 넘김. 반경 blocking·DB 반경 읽기. 기본 schedule RUNNING. migration 없음.

## 2026-11-10 — #1459 TourAPI 문화시설(14)·레포츠(28)

- 같은 dataset·snapshot에 14(2,753)·28(3,717)을 더했다. 레포츠 52%가 캠핑장(AC05)이라 0306으로, LS011900 중 '…길'은 트레킹. 상세 예산 600 유지 → 전량 약 32일. migration 없음.

## 2026-11-10 — ADR-121 accepted (소유자 결정)

- D1=b(master 없는 속성 행은 목록 무관 MCST 장소 하나, master 생기면 병합), D2(반려 업종 약 20,396 미적재·기존 Feature는 R4 퇴역), D3(촬영지는 큐레이션 `media-places` 후보→운영자 승격·공개).
- 설계 단순화: 공용 식별 namespace를 버리고 tier 2 붙임 + 기존 목록 앵커 + 병합 이력 redirect로 같은 효과. 부재 처리는 enrichment link만(primary 부재 퇴역은 현행 유지). 수렴 병합은 적재 밖 계획·executor.

## 2026-11-10 — #1459 여행지 검색 별칭(444)·분류 override 준비

- 별칭 7행(리움·리움미술관·수성못·김포공항·퍼플섬·사천바다케이블카·사천케이블카). 정본 이름은 prod 읽기 전용과 TourAPI searchKeyword2로 확인했다. 퍼플섬·케이블카는 #1465 적재 뒤에 닿는다.
- 분류 override 3건은 코드가 아니라 운영 작업이다 — docs/runbooks/1459-category-overrides.md.

## 2026-11-10 — #1468 A MCST 테마 목록 속성화 설계(ADR-121)

- 운영 읽기 전용 실측: MCST active 88,007. 겹침의 대부분은 MCST끼리(무장애↔가족 약 8천), 속성 목록의 비MCST master 일치는 4~13%(업종 master 미적재). 반려 목록의 20,396은 약국·용품·병원·미용 업종.
- 설계: 속성은 source link에서 유도(catalog 2표 + 붙임 판정표), 적재 시점 붙임 규칙 `theme-attach-v1`, 목록 무관 식별 namespace, `attribute` 필터·응답 필드, 전환 계획표·M05 사건 출처 일반화, PinVi 재vendor 순서. 적대 리뷰 2인 반영. 소유자 결정 D1(master 없는 속성 행: 보류 vs MCST 장소 유지)·D2·D3 대기.

## 2026-11-09 — KNPS 대피소 공식 원본 확인과 핀 상향

- 공식 원본을 직접 받았다. 기존 카탈로그 URL(FILE_000000000377005)은 2013년 중첩 SHP 8건(한라산 7·오대산 1)뿐이라 중청·장터목·세석이 없었다. 포털 현재 배포본은 FILE_000000003681543(_20230928): 평면 SHP 22건, UTF-8, EPSG:5186.
- PR18 파서는 현재 배포본을 DBF 필드명 10 bytes 잘림(`시설물\xeb`)으로 거부했다. provider PR19가 잘린 끝만 제거·대피소 전용 필드(시설물명/위치.주소/순번)·전부 이름 없음 시 실패·카탈로그 갱신을 했다.
- Map은 핀만 올리고 공식 fixture로 public client→Map 변환 회귀를 고정했다(22 place, 03080100/mountain_shelter, 중청 좌표). 주소·tel은 Map이 쓰지 않는다(역지오).
- source_id가 2013 ID_CD에서 순번 기반 `shp:` hash로 바뀐다. KNPS point loader는 snapshot에서 빠진 행을 retire하지 않지만(리뷰 지적), 운영 knps_shelters(provider_dataset 57)는 identity 0·03080100 feature 0이라 남을 옛 행이 없다(읽기 전용 확인).

## 2026-11-09 — MOIS 숙박 우선 적재·상호 정규화

- 감사: 12/42종만 적재. 업종을 숙박→관광→레저→대량 식음 순으로, 상호의 법인 표기를 걷고(442 통칭 별칭), 숙박 계열 세 업종의 같은 시설은 lodgings 하나로, 좌표 없는 행은 geo 정지오코딩. 업종 선택 run은 다른 업종을 은퇴시키지 않음을 확인.

## 2026-11-09 — #1459 TourAPI 관광지 적재 경로

- 운영 키로 KorService2가 200, 관광지 12,560건. 목록 cat1~3이 비어 신 분류 lclsSystm으로 매핑했다. 상세는 오퍼레이션당 1,000/일이라 run 예산 600·저장값 재사용. 산막이옛길(28)·태권도원·세종도서관(14)은 관광지가 아니다.

## 2026-11-09 — 전통시장·특화거리 공개 파일 원천(키 없음)

- 소유자: 두 표준데이터 파일은 활용신청 없이 받는다. 포털 공개 경로(`download/columList.json`→`standard.json`)를 provider PR#24 `9922dd2`로 넣었다(미머지 PR#22 주차장과 같은 경로·검산 + CP949/BOM·기형 행 거부). 실측 1,393·274행.
- Map: 두 fetcher를 키 없는 파일로, 선언 미달·0행 실패, 특화거리도 snapshot 은퇴·공용 정지오코더, 특화거리 disabled 해제. migration 없음.

## 2026-11-09 — #1459 지역 검색·좌표 결측 fallback

- prod: 좌표 없는 공개 행 24,863건(9 dataset). 번지 주소가 있는 축제·주차장·국가유산 2,313건은 asset이 reverse만 넘긴 탓이다.
- 지역 토큰→시군구 순위 자리(해석 19 ms, 질의 warm 10~250 ms), 번지 주소 정지오코딩, 좌표 없는 행 검색 제외, concierge 해수욕장 검증.

## 2026-11-09 — #1459 전통시장 표준데이터 적재 경로

- 원천은 공공데이터포털 15012894(소상공인시장진흥공단, 연간) 표준 Open API `tn_pubr_public_trdit_mrkt_api`다. 필드명은 공식 명세, 단위 fixture는 같은 페이지 미리보기 실제 행이다. provider PR#23(`649fa1a`)로 `traditional_market`을 더했다.
- Map: category `05.07 전통시장`(category.md §12), 자연키 `시장명::시도시군구`, 좌표 없으면 도로명→지번 정지오코딩, snapshot 은퇴(0행은 실패), MOIS 대규모점포·관광지 dedup pair, migration 439, 월간 schedule(STOPPED).
- 적대 리뷰 A: 부분 snapshot(2페이지 빈 응답)이 시장 400곳을 은퇴시킬 수 있어 선언 건수 미달을 실패로 바꿨다. 주소 편집에 흔들리던 키를 시군구까지로 줄였다.
- 운영 키는 이 API(그리고 기존 특화거리)에 활용신청이 없어 HTTP 403이다(박물관은 200). 적재 전에 소유자가 활용신청해야 한다.

## 2026-11-09 — #1459 휴게소·철도역·여객선 항구·공항 검색(ADR-120)

- prod 읽기 전용: 휴게소 place 215·공항 15는 이미 있으나 휴게소 이름이 "강릉(인천)"꼴이고, 공항은 관광 그룹이 이름 일치보다 앞서 "설해원(양양국제공항)"에 밀렸다. 역·항구 transport place는 0(T3 export는 운영 503, 꺼짐).
- 휴게소·역·항구 표시 이름, 역 노선 묶음(500 m), dataset 둘(438), 분류 06060000, 목적지 이름 일치 순위(cursor v4).

## 2026-11-07 — Valkey 상태 쓰기 일시 실패 재시도

- n150 sda flush 대기로 weather_state_daily_summaries가 step 재시도 3회 모두 `세대 쓰기 실패: TimeoutError`(2 s)로 죽었다. step 재시도는 원천을 다시 받아 같은 자리에서 또 죽는다. 세대 묶음·meta·포인터 교체·잠금 해제를 그 자리에서 3회(1·2·4 s) 다시 한다. 응답만 잃은 교체는 CAS가 이 세대를 돌려주면 성공으로 본다.

## 2026-11-07 — 통합 테스트 PG 비내구·tmpfs

- n150 sda flush 포화의 최상위 기록자가 test gate PG(fsync on)였다. 모든 테스트 cluster를 `_disposable_pg.make_nondurable`로 fsync·synchronous_commit·full_page_writes off + `/var/lib/postgresql` tmpfs(기본 3g, `KTM_TEST_PG_TMPFS_SIZE`)로 띄운다. unit 가드·서버 효과 검사 추가.

## 2026-11-07 — #1455 저배율 in-bounds cluster 집계

- prod 읽기 전용 EXPLAIN: 전국 bbox route/area cluster가 `feature_id = ANY(5.8만 배열)` 선형 대조와 view geom 산출식 3중 평가로 15~30 s, PinVi 기본 kind도 쓰지 않는 등산로 후보를 매번 계산했다.
- point/geometry arm UNION ALL·대표점 1회·bbox 내부 geometry는 교차 생략·point-only 변형. 군집 수·개수 동일(좌표 차 ≤8e-6°).
- prod SQL: z7 PinVi 2.9→0.25 s, route/area 12~15→1.0~1.3 s. 22 s 느린 요청 중에도 작은 요청은 0.010 s라 단일 worker가 막히지 않는다(async DB).

## 2026-11-07 — KNPS 대피소 미적재 후속

- 사용자가 다른 미적재 KNPS로 범위를 확대했다. Claude Code의1452/1453과 완료된1회 적재·정책 결정을 먼저 읽고 대피소 upstream17만 남았음을 확인했다.
- source draft18과 Map draft1454를 먼저 만들었다. 구 공급자2676c74의 실제 public ZIP 파싱 실패3건, 첫 수정88f의 전역ID 불일치4건을 소비자에서 재현했다. source 보안·지리 리뷰 지적은 provider에서 보완하고 소비자 wrapper는 추가하지 않는다.
- geo 선택 의존성을 명시하며 핀 생성기·프로토콜 검사도 extras를 읽게 했다. CI 설치와 로컬 unit 게이트는 pyproject의 단일 KNPS 요구사항을 사용한다. 연결 회귀42개가 통과했다.
- 운영/SSH/provider live 호출은 없고 공식 fixture 검증과 운영 재적재는 Claude Code에게 남긴다.

## 2026-11-06 — #1450 Option A: KNPS 보호지역 지정 allowlist

- 보호지역은 여행 관련 지정만 DESIG_ENG 표로 category를 준다(국립공원 중복 제외). 역지오 실패 행은 drop으로 센다.
- 위험지역(POINT)·선형시설(일반명)은 싣지 않고 schedule도 없다. 대피소는 knps-api#17.

## 2026-11-06 — #1450 KNPS dataset별 schedule·운영 1회 적재

- 원인: KNPS job은 dataset 5개를 묶는데 월간 schedule은 노브 dataset 하나만 돌렸다. 운영 갱신 요청으로 경계 21·화장실 325·야영장 36·문화자원 554건을 적재했다.
- 남은 넷(선형 이름 없음·위험 POINT·보호 해상 134 역지오 실패·대피소 ZIP)은 T-KNPS-DATA-GAPS.

## 2026-11-05 — #668 명령 조정 첫 구현·실패 우선 검증

- draft1451을 먼저 만들고 새 API 부재1실패, 기존PATCH 지문의 생략/명시NULL 충돌1실패를 확인했다.
- 동일actor/op/key 잠금에서 부재 claim+terminal409를 커밋하고 늦은 원래 요청을 막는다. 처리중 claim은 pending, 검증한 terminal은 completed로 반환한다. expected_actor는 인증 context와 비교만 하며 권한 선택에 쓰지 않는다.
- PATCH에만presence 보존 지문v2를 적용한다.437은기존v1을수정하지않고1/2를허용한다. 원래PATCH와조정 모두버전검사를먼저해과거v1을자동확정하지않는다. 다른명령v1은유지한다.
- API관련단위29·실제HTTP/auth/PostgreSQL 핵심1개·mypy247파일을통과했다. 초기라우팅정책미등록과바뀐helper테스트signature2건은보완했다. 아직경합/권한/과거지문/실패확장·OpenAPI·두최종리뷰·전체CI·머지는남아있다.
- 운영접근/배포/시험은없고최종prod는Claude Code담당이다.

## 2026-11-05 — Pinvi #668 명령 조정 계약 착수

- Pinvi#667/PR681(cb3b2f6)을 두 최종 리뷰·CI15성공·WSL 실제UI/RustFS 검증 후 병합했다. 다음은#668이며 최신Map mainad75031에서 시작한다.
- 단순 부재 조회는 늦은 옛 명령을 막지 못하므로 actor/operation/key 잠금 아래 영구 중단 결과와 기존 terminal/pending을 구분한다. Pinvi는 해제 후 새 승인 attempt 키를 써야 한다.
- 설계·검증 계획은 docs/execplan/pinvi-668-feature-command-reconciliation.md. draft먼저/자주push, WSL·두 독립 리뷰·CI 후 소유자Map부터 머지한다. 운영 접근·배포·시험은 없고 최종prod는Claude Code 담당이다.

## 2026-11-04 — #1444 묶음(#1445~#1448) 리뷰 보완

- f88b0759(운영)..dd0238c3를 두 독립 적대적 리뷰(데이터·적재 / API·계약)로 다시 봤다. 마이그레이션 추가 없음(head 436), ST_Transform 없음.
- 운영 원본 읽기 전용 모의: MCST 반려동물 20,396건·촬영지 8,803건이 미분류로 옮겨 간다. 행사 85건(KHA 장소 없음 82·종료일 없음 1, 축제 기간 없음 2)이 재적재 때 격리된다. 운영에 KHA fallback 키 행은 0건이다.
- 하회마을·고씨동굴은 운영 Map 검색(현행·신규 코드 모두)에서 이미 별칭 대상이 1위다. #1443의 4위 관측은 Map 순위로 재현되지 않았다.
- 고친 것: 회차 비교는 겹치지 않는 기간만 different(장소·종료일 차이는 검토), KHA fallback 종료일 변경 적재, MOIS 업태 필드의 무관 슬러그 해시 변동 제거, MCST 미도달 dataset 재시도 표기, 변경 장부·검색 테스트 대조군. 모두 수정 전 실패를 확인했다.
- journal이 220 KiB를 넘어 가장 오래된 2026-10-13 절 셋을 `archive/journal-2026-10f.md`로 바이트 그대로 옮겼다(tasks-rule §8).
- 남긴 것: 행사 품질 격리의 자동 해제는 소유자 결정(T-EVENT-QUARANTINE-RELEASE). admin OpenAPI digest가 바뀌었으므로 회전 전 PinVi 재vendor가 필요하다.

## 2026-11-04 — MCST 승인 복구·데이터셋별 적재 완료 보존 착수 (#1441/#1442)

- 최신 Pinvi #643 본문/댓글과 Map #1444를 다시 읽었다. 남은 Map #1441/#1442를 같은 소비자 PR로 처리한다.
- 공급자 python-mcst-api #20을 00a78df로 병합했다. 두 최종 전문 적대적 리뷰·전체 CI·WSL 오프라인 113개/14 subtest 및 공식 공개 골프장 키 없는 live가 통과했다. 실제 SDK가 541행·14열을 읽었고 원문 CSV는 커밋하지 않았다.
- Map은 공급자 핀을 실제 병합 커밋으로 올리고 기존 요청 계측 세션과 승인 경로의 호환성을 확인한다.
- 각 데이터셋 load가 커밋되면 기존 frozen membership과 인과적 seal로 즉시 완료한다. 늦은 다른 fetch/load 실패로 완료 결과를 되돌리지 않고 재시도는 이미 완료된 membership을 다시 적재하지 않는다.
- 전체 run 실패 사실은 보존하고 실제 성공/실패와 원인·진척을 데이터셋별로 표시한다. 다른 provider의 완료 정책이나 보호된 baseline을 바꾸지 않는다.
- 초안 PR을 먼저 만들고 실패 우선·실제 PG runtime·운영 화면의 로컬 UI·두 독립 전문 적대적 리뷰와 최종 CI 뒤 병합한다. 운영 접속·배포·검증은 하지 않는다.

## 2026-11-04 — 실제 분류 UI 검증·성능 하네스 파라미터 보완

- Map 5fcb015 → Pinvi 5048156 → Chromium 실제 UI 13항목을 통과했다. 공개 CSV의 실제 열·분류 tuple을 재현한 fixture로 호텔·카페·펜션·박물관, TYPE이 빈 촬영지의 미분류, 공백이 다른 국가유산 우선 순위와 행사 상세를 확인했다. 이름·주소·좌표는 테스트 값이며 원문 CSV를 저장소에 넣지 않았다.
- 배경 타일만 고정했고 제품 HTTP mock·dependency override는 없다. 모든 소유 서버·테스트 DB 컨테이너를 종료했다.
- 두 독립 전문 리뷰어가 제품 5fcb015에서 잔여 P0/P1/P2 없음으로 판정했다.
- 전체 단위 검사에서 성능 하네스의 새 alias_compact bind 누락 1개를 발견했다(나머지 3,642 통과·조건부 6 skip). 하네스 3곳을 보완하고 관련 17개·Ruff·main mypy 174파일을 통과했다. 전체 단위·PG·최종 CI를 이어간다.

## 2026-11-04 — 실제 MCST 분류 형식·공백 별칭 보완

- 공개 공식 CSV 5종을 다시 확인했다. 촬영지 원천은 CATEGORY가 없고 TYPE도 비어 있어 물리 업종을 확정할 수 없었다. 혼합 시설에서 불명·충돌은 미분류로 표시하고, 알려진 캠핑 전용 원천은 캠핑 분류를 유지한다. 이름·브랜드로 추정하지 않는다.
- 실제 반려동반여행/펜션·박물관·미술관·문예회관, 반려동물식당카페/카페·식당, 공원·전시/기념관 등 구조화된 값을 반영한다. 촬영 매체 FORMAT을 업종으로 사용하지 않는다. 기존 식별자·원문·색상은 유지한다.
- 별칭의 공백 차이로 국가유산이 테마 원천보다 뒤에 나오는 두 경우를 재현했다. 기존 GIN 후보에서 원래 이름 정규화 일치로 순위를 계산하며 목록·총계·페이지 이동을 함께 검증한다. 순위 의미 변경으로 cursor v3를 사용한다.
- 새 실제 형식 회귀는 수정 전 11개 단언 실패, 공백 별칭은 2개 실패였다. 수정 후 관련 단위 123개·PG 33개를 통과했다. 별도 PG에 비일치 1만 행을 넣은 실제 SQL의 기본 실행계획에서 GIN 사용·features 전체 스캔 없음, 실행 6.855ms를 확인했다(운영 성능 수치가 아니다).
- 이전 15b75fe/222e521 리뷰·전체 테스트로 이번 추가 변경을 승인하지 않는다. 새 독립 전문 적대적 리뷰 두 명·WSL 전체 관련 검사·실제 UI·최종 CI를 진행한다.
- Pinvi #643 최신 본문에 추가된 #663 상세 카드 지연도 후속 범위에 포함했다. 운영 접속·배포·검증은 하지 않는다.

## 2026-11-04 — Feature 품질 최종 WSL 검증

- 제품 15b75fe의 독립 전문 적대적 리뷰 A/B 모두 잔여 P0/P1/P2 없음이다.
- 최종 WSL 전체 PG 통합 1,617개 통과·조건부 14개 skip(743.78초), 전체 unit/lint 3,631개 통과·조건부 6개 skip, 관련 API 48개를 통과했다. API 카테고리 회귀의 이전 145개 고정값을 146개로 맞추고 행사 path·star 아이콘을 명시적으로 검증했다. 이 보완에는 제품 코드 변경이 없다.
- 실제 Map 15b75fe → Pinvi 80593b4 → Chromium UI 11항목을 통과했다. 별도 테스트 DB·정상 앱 lifespan·실제 HTTP를 사용했고 배경 raster 타일만 고정했다. 제품 API mock·dependency override는 없다. 행사 기간·장소 모달, 업종 라벨 5종, 격리 행 공개 제외를 확인하고 소유 fixture 서버·컨테이너를 종료했다.
- 관련 안전 결과는 소비자 PR #662의 `docs/reviews/pinvi-1439-event-local-live.json`에 보존한다. 최종 테스트/문서 커밋의 exact HEAD 리뷰와 CI 후 Map → Pinvi 순서로 병합한다. 운영 접속·배포·검증은 하지 않았다.

## 2026-11-04 — 적대적 리뷰의 회차 비교/관리자 보정 충돌 수정

- 두 최종 리뷰어가 KHA fallback guard의 effective 값 비교를 지적했다. 동일 원문이 관리자 보정 때문에 거부되거나, 반대로 보정값과 같은 다른 원천 회차가 통과할 수 있었다.
- 해당 source entity 소유의 provider base로 회차를 비교한다. 품질 격리는 기존대로 override가 반영된 표시값을 사용한다.
- b19d08b의 실제 guard 본문을 실행한 음성 대조에서 관리자 장소 보완 뒤 동일 원문·연락처만 변경한 원문 재수집, 관리자 종료일 보정이 다른 회차를 가리는 경우 등 3개 실패·정상 대조 1개를 확인했다. 수정 후 재투영·ACL·회차 실제 runtime PG 18개를 통과했다.
- 기존 전체 PG는 리뷰 보완을 위해 434개 통과·5개 조건부 skip 시점에 중단했다. 최종 소스로 전체 PG 및 두 exact HEAD 리뷰·CI를 다시 진행한다.

## 2026-11-04 — #1438/#1439 현재 원본 재투영·품질 전이 검증

- 현재 primary 원본의 명시적 7개 dataset만 분류·marker base를 재투영한다. 소유 원천이 다른 base·override·주소·상세·팔레트·퇴역 상태를 보존하고 두 번째 실행은 무변경이다.
- 실제 Dagster 역할의 base 조회 권한 누락을 재현했다. protected table의 DML 금지는 유지하고 필요한 5열 SELECT만 허용한다. 436 catalog marker 이전의 봉인 baseline은 그대로 두며 열 권한 drift를 reconcile에서 제거한다. 열 제한은 행 제한이 아니며 내부 공통 runtime에 적용된다.
- KHA fallback 동일 키의 다른 기간 유입을 실제 PG에서 재현·거부하고 rollback 뒤 기존 원문/head/base/표시 보존을 확인했다. 기존 행사 격리는 override가 반영된 표시 정보를 사용하고 자동 해제하지 않는다.
- 전체 unit/lint 3,631개·조건부 skip 6개, main 174개 파일 mypy, import-linter 4계약, CI 범위 Ruff 및 OpenAPI all-profile drift 검사를 통과했다. 분류/ACL/검색 PG 28개, 확장 재투영/ACL 거부·반복 reconcile PG 15개를 통과했다. 새 repair·merge guard를 끈 음성 대조는 5개 단언 실패·오류 0개였다.
- 별칭 전국 검색은 현행 migration 436 seed와 source 순위가 WSL 실제 PG에서 기대 순서를 만족했다. 운영 결과와의 차이는 최종 Claude Code 검증 시 alias seed·원천 분류·배포 revision을 확인해야 한다. 운영 접근·배포는 수행하지 않았다.
- 초안 #1447에서 두 독립 전문 적대적 최종 리뷰와 전체 PG/CI를 이어간다. Pinvi 정본 행사 필드 투영은 별도 소비자 PR에서 연결한다.

## 2026-11-04 — #1439 행사 분류·격리·회차 병합 경계

- 축제·행사 category `01090000`(star)를 추가하고 기존 legacy seed·자연키·팔레트를 유지한다. 신규 행사 필수 정보 누락은 원문을 보존해 격리한다.
- 단위 수정 전 8개 회차 오판 단언 실패·정상 2개 통과를 확인했고, 수정 후 관련 145개와 6개 소스 타입 검사를 통과했다. 실제 PG18 runtime 역할의 직접 병합·거부 시 상태/이력 불변·DB 후보 날짜 전파·기존 오케스트레이션 관련 16개도 통과했다.
- 동일 raw head의 기존 분류 재투영·기존 행사 품질 전이·별칭 검색 검증은 초안 #1447에서 이어간다. 아직 완료나 병합을 선언하지 않는다.

## 2026-11-04 — #1438 구조화된 시설 분류 회귀

- MCST 혼합 시설 4종·캠핑 CSV의 CATEGORY1/2/3로 업종을 결정하며, 불명·충돌은 기존 fallback을 유지한다. 이름·브랜드로 업종을 추정하지 않는다.
- MOIS는 기존 승격 업종의 명시적 업태만 세분화하고 세 분류 근거를 새 원본에 보존한다. legacy ID seed·자연키·팔레트는 유지하며, payload hash 사전 계산과 실제 변환을 일치시킨다.
- 수정 전 MCST 9개·MOIS 11개 단언 실패를 재현했다. 원본 동일 head의 기존 행 재투영, 행사 정합성, 검색 실제 PG 검증은 같은 초안 #1447에서 이어간다.
- 운영 접근·배포는 하지 않는다. 완료 표시는 두 독립 적대적 리뷰·WSL 및 CI 후에만 갱신한다.

## 2026-11-03 — PinVi #643 관리자 조회 연계 (#648/#651)

## 2026-11-04 — #1438·#1439·#1443 Feature 분류·행사·검색 순위 묶음 착수

- Pinvi #643 최신 본문과 댓글의 Map #1444 연결을 다시 읽고, #1441·#1442·#1443도 전체 범위에 반영했다. #1443은 분류·행사와 같은 Feature 품질 묶음에 포함하며 CSV 파싱·데이터셋 완료 상태(#1441·#1442)는 후속 별도 묶음으로 진행한다.
- 구조화된 원천 분류를 provider 범위에서 정규화하고 기존 UUID·자연키·legacy seed를 보존한다. 행사 필수 정보·회차 정합성과 동명 다른 회차 오병합 방지, 별칭·전국 검색 순위를 실패 우선 fixture로 검증한다.
- Pinvi의 정본 행사 필드 투영은 소비자 연결에서 확인한다. 운영 8건이 실제 중복인지 판정하거나 임의 병합하지 않는다. 동일 원본 재투영·두 번 실행의 멱등성과 override·퇴역 상태 보존도 검증한다.
- 초안 PR 우선·수시 원격 커밋·독립 전문 적대적 리뷰 두 명·WSL 및 CI 후 순차 일반 병합한다. 운영 접속·배포·검증은 사용자 지시에 따라 수행하지 않는다.


## 2026-11-04 — Pinvi #643 과거 날씨 요약·오래된 정보 표시 묶음 착수

- Geo 주소 검색 PR #622의 CI·두 독립 리뷰·WSL 검증과 병합을 마쳤다. 다음은 Map #1440과 Pinvi #642의 날씨 품질 묶음이다.
- Map은 가까운 요약 후보에 표본이 없을 때 유효한 다음 후보를 가리는 경로를 수정한다. 기존 부분별 상태·선택 출처·신선도·전날 비교를 보존하고 실제 Valkey 왕복을 검증한다.
- Pinvi의 카드 stale 전파·배지는 소비자 저장소에서 처리한다. 사용자 지시에 따라 초안 PR을 먼저 만들고 두 독립 적대적 리뷰, WSL 검증과 CI 후 병합하며 운영 접속·배포·검증은 하지 않는다.


**작업**: 한국어 관리자 Feature 검색에 이름·주소·ID만 검색하는 명시적 범위를 추가하고,
중복 검토 목록을 기존 ops read principal로 조회할 명시적 읽기 경계를 제공한다.
기존 operator 쓰기 권한을 public/service token으로 확장하지 않는다.
**검증**: 기존 희소 질의는 원천 48건을 한 번 읽었다. 제한 범위는 비일치 후보의 원천 접근 0과 현재 원천·기본 전체 검색·페이지 이동을 WSL PG18로 검증한다. 2026-11-04 WSL 관련 API·권한·PG18 회귀 154개와 main/API mypy, CI 범위 ruff, import-linter 4계약을 통과했다. 전체 unit/lint 3,587개 통과(조건부 6개 건너뜀). 리뷰의 OpenAPI token+scope AND 조건 누락을 보완하고 관련 계약·인증 53개를 통과했다. 독립 리뷰어 두 명의 최종 소스 검토에 차단 사항이 없다. 생성 frontend 타입 누락을 CI에서 발견해 재생성하고 drift 검사를 통과했다. 전체 API 1,596개·coverage 77.90%(기준 70%)를 통과했다.
전체 통합 CI는 1,589개 통과·14개 건너뜀·신규 테스트 1개 실패였다. 선행 잠금 테스트가 커밋한 주소 행과의
간섭을 WSL에서 같은 순서로 재현했다. 테스트별 고유 이름·주소로 격리한 뒤 관련 11개를 통과했다.
리뷰의 음성 대조가 행별 이름으로 인한 동률 cursor 검증 약화를 찾아, 페이지 테스트 세 행은 같은 전용 이름을 유지한다.
API 구현·스펙은 보존하며 전체 통합 검증·최종 CI를 다시 진행한다.
운영 배포·테스트는 사용자 지시대로 Claude Code가 최종 담당한다.
**이전**: PinVi PR #659(d6e0ddc)로 관리자 제안 큐 세 항목을 머지했다.
**다음**: Map 읽기 변경 머지 후 PinVi 소비자 경로·오류 표시를 연결하고 남은 데이터·지도·날씨·알림을 진행한다.

## 2026-11-03 — weather_state 503 페이지 재시도

weather 503(읽기 경합 `EXPORT_TEMPORARILY_UNAVAILABLE`·이전 `EXPORT_NOT_READY`·code 없음)은 그 페이지만 같은
cursor로 최대 3번 다시 묻는다(5·10·20초, `Retry-After` 우선; 대기+가장 긴 요청이 run 상한 −60초 안, 순회당 대기 합
60초, run 재시도 예산 공유). 소진하면 종전처럼 step 재시도.

## 2026-11-02 — feature 검색 순위·별칭(alembic 436)·주차장 표시 이름

PinVi live e2e(봉화·영주·안동)에서 "하회마을"이 서울 음식점 셋, "고씨동굴"이 고씨네·단양 고수동굴, "도산서원"이
주차장·미디어 명소를 국가유산보다 먼저 냈다(prod 읽기 전용 실측). 소유자 "권장안 대로".

- 순위 `rank`: 일치 단계(별칭 → 이름이 검색어를 품음 → 유사도) → bbox 안 → 분류 그룹 → 이름 일치(첫 낱말 지역명을
  뗀 일치 포함 — "안동 도산서원") → Tier 1만 있는 코드 뒤. q와 함께 온 bbox는 가중(필터 아님). cursor v2(keyset에
  rank, 상한 21911). 별칭 팔은 trigram GIN `=`로 BitmapOr(prod 35 ms).
- 분류 그룹은 Tier 1 표 + 교통 목적지 접두 예외: 관광 0 → 숙박·온천·기차역·지하철역·휴게소·공항 1 → 식음 2 →
  그 밖 3. 리뷰 2인이 "서울역" 역이 "롯데리아 서울역점"보다 뒤인 것을 짚었고, 3번째 리뷰가 정류장 전체·의료까지
  올린 것은 소유자 순서를 넘는다고 짚어 기차·지하철역·휴게소·공항만 남겼다. 관광 부분 일치는 여전히 앞이고, 의료는
  맨 뒤라 "서울대병원점" 음식점이 "서울대병원"보다 앞선다(소유자 판단 대상).
- 이름 비교 키는 보이는 이름(주차장 표시 이름)에서, NFC·Python `isspace` 공백 집합 제거·소문자로 만든다. SQL은
  `translate`로 같은 집합을 지운다(PG `\s`는 NBSP를 놓친다). 양쪽 다 소문자 뒤 다시 NFC(자모·결합 부호). 436 CHECK도
  같은 집합. 지역명 tail은 앞뒤 공백을 걷고 집합 어느 문자에서든 자른다. tier-2 하네스 bind 누락도 고쳤다.
- 436 `feature.feature_search_aliases`: 정규화 검색어 → Feature **이름**(id는 환경·재적재마다 달라 migration이 못 심는다).
- 주차장 표시 이름은 응답 모델 before-validator — 저장 값·ETag·OpenAPI 불변. backlog: T-HERITAGE-ENRICH·T-DEDUP-MEDIA-HERITAGE.
- 이 절을 더하자 journal이 220 KiB를 넘어 가장 오래된 2026-10-13 두 절을 `archive/journal-2026-10e.md`(머리말 포함
  21,540 B)로 옮겼다(§8, 본문 그대로·상대 링크 없음). resume도 같은 이유로 가장 오래된 네 절을
  `archive/resume-2026-09b.md`로 옮겼다.

## 2026-11-02 — weather_state 하한·W5 상한 실측 조정

단기 하한 1,000곳·90%→250곳·65%, W5 상한 900→2,700초. 근거는 resume 같은 날.
