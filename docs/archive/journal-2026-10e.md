# journal 아카이브 — 2026-10-13 (e)

> live journal이 220 KiB 경계를 넘어 가장 오래된 완전한 절 둘을 분리했다(docs/tasks-rule.md §8). 두 절에 상대 링크가 없어 본문은 바꾸지 않았다. 읽기 전용 이력이다.

## 2026-10-13 — geo·transport 호스트 odroid 이전(Track 2) Map 쪽 문서: 브랜치 `docs/adr-110-geo-transport-on-odroid`

문서만 바뀐 PR(doc-only, origin/main `f7affea8` 위). Track 2 설계(geo·weather·transport 세 스택과 그 PG를 odroid로,
포트·이름 동일·host만 n150 → odroid; 3차 적대 리뷰·2026-10-13 odroid 실측 반영본)에서 **Map 저장소가
책임지는 것**만 ADR-110(proposed, 미구현)으로 옮기고 `T-MAP-01`·`T-MAP-02`를 열었다. 코드·`.env.example`·compose·
CHANGELOG·OpenAPI·테스트는 건드리지 않았다. 호스트 플립 자체는 Manager ADR-58·geo ADR-070·transport ADR-014의 일이다.

- **결정 요약(ADR-110).** (1) Map 저장소는 값을 바꾸지 않는다 — geo·transport origin의 정본은 오늘 Manager compose
  기본값 + root `.env`(geo 기본값은 Map 서비스 **4곳** `:1582,1723,1813,1920`·transport는 code-server `:1732-1733`,
  @08a515e; registry `hosts:` 파생은 Manager ADR-58 R2 — 오늘 registry에 host 필드 없음, 그 뒤 `.env` URL 재정의는
  validate 거부); 플립 뒤 `ensure map`은 Map target 전 서비스 재생성(옛 값 든 컨테이너 0개 게이트);
  `.env.example:198,234`는 standalone 값(주석은 T-MAP-02 코드 PR). (2) UI 재빌드
  없음 — BFF `/api/geo`는 런타임 `KOR_TRAVEL_GEO_INTERNAL_URL` 우선(`route.ts:3-6`), 빌드 인자는 공개 host라 변경 0
  (설계 §14-10은 열린 결정 1 — 설계는 추천 없이 두 선택지). (3) 장애 의미가 RST → timeout으로 바뀐다 — geo 10 s·
  transport 30 s 단일 timeout(`settings.py:159-164,537-542`)을 `httpx.Timeout(<기존>, connect=<connect 필드>)`(기본값이
  read·write·pool을 덮는다 — `Timeout(connect=, read=)` 둘만은 httpx 0.28.1에서 ValueError)으로 팩토리
  하나씩(geo `geocoding.py`·transport `_transport_connection` 옆)으로 분리(T-MAP-02, 코드 후속; **geo 8곳·transport
  3곳** — geo 8곳 중 `admin_issues.py:276,306`은 timeout 인자 없음(httpx 기본 5 s), `dagster/offline_uploads.py:50-53`·
  `cli/main.py:447`은 10.0 하드코딩이라 settings를 읽지 않는다; 적용 범위는 lint로 효과 결박), 회로차단은 Map에
  두지 않음(배치 호출이라 run 실패가 곧 신호; PinVi만), transport ±30 min 시계 검사는 fail-closed 유지. (4) geo
  공개 키는 **오늘도 대조된다** — 이전으로 바뀌는 것 없음(geo 면제는 admin 프록시 컨텍스트만, `security.py:154-170`;
  Map은 `X-KTG-API-Key`만 보냄 `geocoding.py:1289`; 08-13 401 사고가 저장소 안 증거). 위험은 geo 재적재로
  `public_api_keys`가 비는 것뿐 → 키 재발급·root `.env` 재적용·컨테이너 전부 재생성·키 경로 200이 플립 9단계 필수
  (외부 추적). VWorld 폴백은 Map #979 가드와 충돌해 채택 불가(열린 결정 3은 '추천 없음·(나)만 가능'). `9-전` curl은
  선택적 smoke로 격하. (5) transport export allow-list에 n150 LAN 주소 `/32`(transport 쪽 변경; XFF 불가). (6) ADR-109 amend(109 상단에 역포인터 한 줄) — `GEO_HEAVY_POOL`
  유지·근거만 'n150 디스크 대기' → 'odroid geo CPU 보호'; 센서·재지오코딩은 LAN 키 경로(RTT 9.7 ms, 전량 ≈2.5 h+
  추정); odroid 풀로드 뒤 플립 시 전량 재계획 **수용을 추천**(소유자 결정 대기 — 열린 결정 2, 대안은 운영자 UI skip;
  수용이면 mv_refresh 다음 날·야간 창 밖; dump 복원이면 0). (7) 전환 절차에서 Map이 하는 일은 단계 1·5·9-전·9·drill·11
  (설계 §11.2 발췌; 2~4b·8a/8b는 외부 단계로 Map이 확인할 선행 효과만 — odroid plane healthy·`targets validate`
  host·시계 동기) — 게이트는 효과(n150 피호출자 stop 상태에서 export 1회·키 경로 200·peer = n150 LAN 주소 로그·MOIS run
  예산 10 % 안 FAILURE — 유도: 첫 chunk 500행 ÷ 동시성 2 × connect 2 s ≈ ≤502 s, 10 s면 ≈2,502 s로 10 % 초과).
- **odroid 상태(FB §A3, 03:4xZ).** WSL 직접 ssh·NOPASSWD sudo·docker 그룹·NTP 수동 동기 **완료**; timesyncd 부팅
  사이클 drop-in·compose v2/buildx·방화벽·fstab bind·swapfile **미완** — ADR 컨텍스트 7에 완료/미완을 그대로 적었다.
- **설계와 달리 쓴 것(head `f7affea8` 재확인).** `docker/frontend.Dockerfile` 빌드 인자는 `:56`이 아니라 `:57`(ARG)·
  `:62`(ENV); `kor_travel_geo_preflight_required`는 `:164-176`이 아니라 `:165-176`, transport base URL은 `:509-519`
  (초고의 `:165-177`·`:509-520`은 한 줄 초과 — 1차 리뷰 정정); MOIS 동시성 `:364-374`, 예산 `:388-`; transport 시계
  검사는 `kor_travel_transport.py:104`(`INCIDENT_SET_MAX_AGE` 30 min)·`:435-452`(설계 `:441-453`). geo client 생성
  지점은 설계에 없던 file:line을 더한 것인데 초고의 "4곳"이 틀렸다 — 1차 리뷰(HIGH)가 `admin_issues.py:276,306`(timeout
  없음)·`dagster/offline_uploads.py:50-53`·`cli/main.py:447`(10.0 하드코딩)을 찾아 **8곳**으로 고쳤고, 팩토리 자리
  (`geocoding.py` 지역 import / `_transport_connection` 옆)와 lint 결박을 적었다. 설계 §9.1의 Map 행은 connect 분리만
  요구하므로 회로차단은 Map 결정에서 명시적으로 뺐다(ADR-110 결정 3·열린 결정 4). weather는 Map이 호출하지 않아
  (ADR-105) 범위 밖임을 한 줄로 못박았다. 설계 T-MAP-01의 `.env.example` 주석은 이 PR이 `.env.example`을 금지하므로
  T-MAP-02 코드 PR로 옮겼다. 설계 정본 파일은 세션 scratchpad라 ADR 본문을 정본으로 선언하고 §는 출처 표기로 낮췄다.
  **설계 §9.1 키 행·§5.6 ⑥의 "geo 키는 loopback 면제라 검증된 적 없다"는 틀렸다** — geo 면제는 admin 프록시
  컨텍스트(CIDR+proxy secret+actor/roles)만이고 Map 호출은 오늘도 대조된다(ADR 컨텍스트 4에서 정정, geo ADR-070
  작성자에게 전달). **T-MAP-02 착수 순서**를 설계 §13의 MGR → MAP 사슬에서 분리해 병렬을 제안했다(코드 의존 없음 —
  열린 결정 6, 소유자 확인; 선행 T-GR-00-LEDGER·`geocoding.py` T-GR-01 공유). **LAN 주소 리터럴은 쓰지 않았다** —
  `scripts/check_prod_redaction.py`(#508, `lint.yml`·pre-commit)가 docs의 사설 IP를 거부해 호스트 이름(`n150`·`odroid`)
  으로 썼다(설계·지시문은 호스트를 LAN 주소 끝자리로 적지만 여기서는 조각도 쓰지 않는다).
- **1차 리뷰 반영(2건, 19 finding).** 전부 반영: timesyncd 상태를 §A3(수동 동기 완료·drop-in 미완)로, §14-19를
  '수용 추천 + 열린 결정 2'로, CLAUDE.md의 'Manager registry 정본'을 '오늘은 compose 기본값 + root `.env`(registry
  파생은 ADR-58 계획)'·'값 없음'을 'standalone 값'으로, ADR-109에 amend 역포인터를, 제목 3곳 통일(connect 분리 포함),
  열린 결정 1의 추천 출처 표기, 'Map만 끊긴다' → 'n150 consumer', T-MAP-02 동반 문구에 `settings.py:509-519` 설명,
  T-MAP-01 종결 소유자(T-GR-00-LEDGER/T-MAP-02 PR), 'CI 대기 없이' → 'lint.yml 초록 뒤(소유자 지시)', T-GR-00-LEDGER
  수치 갱신.
- **2차 리뷰 반영(2건, 17 finding — 전부 반영).** HIGH 2: geo 키 전제 정정(위; 결정 4를 '재적재 시 키 소실'로 축소,
  `9-전` curl을 선택 smoke로, integration-map·resume·acceptance 동일), `#508` redaction guard 실측 11 hit EXIT=1 →
  IP 리터럴 전부 호스트 이름/placeholder로(EXIT=0 재확인). MED: (가) VWorld 폴백 '추천' 철회(Map #979 가드
  `test_geo_key_provenance:493,506`·`test_compose_geo_key_resolution:143`·`test_deploy_automation:382`와 충돌 → 열린
  결정 3 '추천 없음·(나)만'); `12501:12501` publish 인용 삭제(host network에서 `ports:` 무효 — 실제는
  `KTG_API_HOST: 0.0.0.0` Manager compose `:1089`@08a515e); T-MAP-02 의존을 '선행 없음'에서 'T-GR-00-LEDGER 선행 +
  T-GR-01과 `geocoding.py` 공유(늦은 PR 리베이스)'로 + 열린 결정 6; MockTransport 픽스처 삭제(항진명제 — backlog
  포화 서버만); T-MAP-02 해제를 '(1)(2)(3) 초록 + 머지 + 4a 전 배포'로 한정하고 curl·drill을 종결 조건에서 뺌. LOW:
  lint를 '`timeout=`이 팩토리 호출'로(settings float 직접 전달도 빨강), '설계 파일 보존은 T-MGR-07 몫' 삭제, 교차
  ADR 번호에 '(계획, 미작성)', CLAUDE.md를 한 문장으로, Manager sha 드리프트(origin/main `094d3976`, transport 줄
  `:1736` 부근) 주석, integration-map §2의 file:line·'8곳 중 4곳' 복제 삭제(ADR 포인터만), ADR-110 `## 후속` 절 추가.
  범위 목록 밖 수정 1건: `docs/adr/109-geo-release-regeocode.md` amended-by 3줄(역포인터).
- **3차 리뷰 반영(2건, 17 finding — 전부 반영, 기각 0).** HIGH 1: T-MAP-02의 유일한 코드 사양
  `httpx.Timeout(connect=2.0, read=…)`이 httpx 0.28.1에서 `ValueError`(worktree에서 실행 재확인) → ADR 결정 3·tasks·
  acceptance를 `httpx.Timeout(<기존>, connect=<connect 필드>)`(기본값이 read·write·pool을 덮는다)로, acceptance (1)에
  `write == pool == read` 단언 추가. MED 5: geo base URL이 Manager compose의 Map 서비스 **4곳**(api·code-server·dagster·
  daemon `:1582,1723,1813,1920`@08a515e — 로컬 Manager 체크아웃 `git show`로 두 ref 모두 확인)에 주입되는데 `:1582` 하나만
  적고 단계 9를 'cs·API 재생성'이라 쓴 것을 '전 서비스 재생성 + 옛 값 든 컨테이너 0개 게이트'로 통일(결정 1·4(a)·7);
  결정 7 표에 '2~4b(외부)'·'8a/8b(외부)' 행을 넣어 단계 5·9의 선행 조건(odroid plane healthy·`targets validate`
  host·`timedatectl` synchronized·풀로드/mv_refresh/키 정책 완료)을 결박; 단계 9의 '센서 계획 1건' 게이트를 열린 결정
  2(풀로드+수용 / dump 복원이면 0건 / T-GR-05 미배포면 해당 없음)로 분기; 교차 ADR 셋을 '미작성'에서 '**proposed·병렬
  PR 미머지**'로(로컬 체크아웃 `ktdm-t2docs`·`geo-t2docs`·`transport-t2docs`에 본문 존재, origin/main에는 없음 — 6곳);
  transport env 파일을 계획 이름 `.env.prod`가 아니라 오늘 이름 `.env.server14`(transport `README.md:123-124`)로 적고
  `.env.prod`는 ADR-014 개명 계획으로. LOW 11: backlog 포화 레시피를 '사전 connect ≥3건으로 큐를 채운 뒤 측정, Linux
  전제, non-routable 주소 금지'로; 잔존 `.13`/`.14` 조각(journal (7)·acceptance T-MAP-01)을 호스트 이름으로; T-MAP-01
  종결 소유자를 T-GR-00-LEDGER 단일로(tasks·acceptance·resume); 'T-GR-01과 같은 client 생성 지점' → '같은 모듈, 충돌
  범위는 import·새 함수 자리뿐'; drill 10 % 유도식(prefetch는 예외를 삼키고 `geocoding.py:430-432`, 실시간 조회가
  `GeoRequestError`를 전파해 첫 chunk에서 FAILURE — ≤502 s vs 10 s면 2,502 s); ADR-58 R2 뒤 `.env` URL 재정의가
  validate에서 **거부**됨을 컨텍스트 1·결정 1·integration-map·CLAUDE.md에 명시하고 "후속"에 표식 교체 세 시점을 둠;
  결정 6 셋째 bullet의 'skip 쓰지 않는다/대안은 skip' 모순을 조건부 문장으로; `up{host="odroid"}`에 'ADR-58 파생물
  계획, 오늘 Prometheus에 host 라벨 없음' 표식; 저장소 밖 메모리 파일 인용을 `integration-map.md` §4 포인터로.
- **원장.** `tasks.md`에 `T-MAP-01`·`02`(접두사 임시, ADR-110 열린 결정 5), `tasks-acceptance.md`에 두 절
  (`tests/lint/test_task_ledger_conventions.py`가 열린 task마다 절을 요구한다). `journal.md`는 이 항목 포함 약 224 KB로
  상한 225,280 B 아래라 아카이브 분리는 하지 않았다 — 여유 ≈1.3 KB라 다음 경계 분리(`T-GR-00-LEDGER`)는 어느 PR보다
  먼저다.
- **미결 소유자 결정**: ADR-110 열린 결정 6건(BFF 경로 §14-10·geo 적재 방식 §14-8 + 재계획 수용/skip §14-19·키 정책
  §14-21(재적재 시점의 일)·회로차단·task 접두사·T-MAP-02 착수 순서) + 외부: geo가 실제로 odroid로 가는지(설계 §3.2
  조건 3·§14-12 — 미달이면 ADR-110 geo 절은 발효하지 않는다).

## 2026-10-13 — geo 릴리스 재지오코딩 설계: 브랜치 `docs/adr-109-geo-release-regeocode`

문서만 바뀐 PR(doc-only). geo 주소 데이터셋 릴리스 → Map 반영 설계(Track 1, 2차 적대 리뷰 2명 반영)를 ADR-109
(proposed, 미구현)와 `docs/etl/address-geocoding.md`(코딩용 상세)로 옮기고 구현 task `T-GR-00`~`08`을 열었다.
코드·마이그레이션·OpenAPI·CHANGELOG는 건드리지 않았다.

- **결정 요약(ADR-109).** 스탬프는 별도 표 `feature.feature_geocode_stamps`(outcome `called|geocoded|not_called`
  셋 — 좌표 유무가 아니라 호출자의 `geo_applied` run 신호로 정한다; price/notice asset은 스탬프 없음). 현재 토큰은
  run 단위(`kor_travel_geo_dataset` resource; 실패 시 None = 오늘과 동일, fail-to-current). 재지오코딩은 새 엔진이
  아니라 적재 경로의 unchanged-skip 보강: stale 분기 + 값 동일 무쓰기(**override 열은 비교에서 제외**) + 빈 답
  가드(행: 저장 값 non-NULL인데 새 값 전부 None → 무쓰기·무스탬프·finding; run: MOIS의 비율 가드 공통화) +
  geo-release run 한정 timeout 1회 재시도(ADR-108 예외). 기동은 센서 → 전용 job RunRequest(큐 아님; 큐 worker run이
  있으면 Skip). 계획 identity `plan_id` + `(data_token, plan_seq)`(A→B→A도 다시 돈다), 항목은
  `provider_dataset_operations` DB 정본 + KNPS dataset별 run_config, run_key에 `plan_seq/dataset/attempt_seq`, MOIS
  `budget_exhausted`는 done이 아니라 이어 달리기(`mois_load_continuation_decision` 재사용), 완료 분모에서 skipped
  dataset 제외, 완료 시 `same_sigungu` 링크 재동기화. 쿼터 민감 dataset(MOIS·datagokr·standard_data)은
  `source_records.raw_data` replay 모드. concierge payload 토큰은 run 토큰과 같을 때만 신뢰하고 Map
  `raw_payload_hash`에서는 제외. admin API는 admin 프로필만(PinVi admin 스냅샷 재vendor 선행), 슬래시 동사.
- **설계와 달리 쓴 것(head `c4d17343` 재확인).** `client/__init__.py` 인용을 `load_feature_bundles` :1058·
  `find_unchanged_active_source_entities` :1081·`load_feature_bundles_reobserving` :1104·`find_fresh_open_findings`
  :2654로 정정(설계는 1008/1031/1054/2604); `apply_kor_travel_geo_address`는 `admin_issues.py:576`(설계 :546-662);
  `sync_poi_cache_target_feature_links`는 `poi_cache_target_repo.py:862`(설계 :48); `AdminEvidence`는
  `dto/admin_evidence.py:72`(`reverse_attempted` :102). 나머지 file:line은 일치했다. ADR-108에는 "건별 재시도 없음"
  문장이 없어 재시도 예외 각주를 §2(선조회 실패 뒤 실시간 1회) 아래에 달았다. runbook
  `docs/runbooks/geo-release-regeocode.md`·admin 화면 체크리스트 행은 구현 PR(T-GR-07/06) 몫으로 미뤘다.
- **T-GR-00 원장 분리.** `tasks-acceptance.md` 216,950 B(상한 225,280)에서 `scripts/archive_task_ledger_section.py`로
  닫힌 절 7개(`T-VN-41F1D-D1`·`-E`·`T-VN-M01`·`T-VN-M04`·`T-VN-39`·`T-VN-DAGSTER-STORAGE`·`T-VN-QUOTA-ARITHMETIC`)를
  `docs/archive/tasks-acceptance-*.md`로 옮겼다(166,931 B; 매 이동 다중집합 검산 통과, 상대 링크가 있는 절 셋은
  도구가 거절해 두었다). T-GR 절 9개와 1차 리뷰 반영을 더해 **1차 리뷰 반영 뒤 실측** 185,189 B(§T-GR-00
  실측 줄과 같은 값). 설계 §11 T-GR-00이 요구한 잔여 바이트: `journal.md` 208,660 B(이 항목 포함, HEAD 202,686)·
  `tasks-done.md` 200,699 B — 둘 다 규약 §8 분리 기준(200 KB 근접)을 이미 넘어 PR-1 전 doc-only 분리를 선행
  조건으로 적었다(이 PR 범위 밖).
- **1차 적대 리뷰(2명) 반영.** (HIGH) `address-geocoding.md` §1 "현재 사실" 표를 변환 **함수** 단위로 다시 썼다 —
  `address_resolver=`를 받는 모듈은 7개(mois·standard_data·datagokr_file_data·krforest·krheritage·opinet·krex(미사용))이고
  khoa·krairport·mcst·krforest·datagokr·standard_data·opinet은 geo에서 코드+일부 필드만 취해 자기 `Address`를
  조립하며(knps·krforest route·krheritage만 geo `Address` 그대로), Dagster asset·큐 runner는 어느 것도 `address_resolver=`를
  넘기지 않는다(`assets.py` 0건 → asset 경로 `geo_applied.geocode`는 전부 False) — 호출자 표를 추가했다. (MED)
  outcome 판정에 평가 순서를 박았다(①스탬프 없음 ②MOIS evidence ③reverse 시도 → `called` ④geocode → `geocoded`
  ⑤`not_called`); concierge 좌표 행은 payload 코드를 썼어도 `called`(geo가 채운 빈칸이 비교 대상 — 설계 §6.3의
  `not_called` 정정). geo 의존 유도의 런타임 정본은 `core/feature_operation.py` `GEO_DEPENDENT_OPERATION_KEYS`
  상수 + pool lint AST 유도와의 집합 동등(`/detect`는 API 프로세스라 `kortravelmap.dagster`를 import할 수 없다).
  빈 답 비율 가드는 상수·계산만 공유하고 MOIS는 ADR-108 §3a-2 degraded(실패 아님) 유지. ADR-109 열린 결정에
  11(전용 job vs 큐)·12(`raw_payload_hash` 토큰 제외)·13(범위 밖 drift 백로그)을 더하고 8에 backfill 전 배포 Skip
  승인을 합쳤다; 결정별 영향 조문 표를 §T-GR-00에 두고 timeout 재시도 옵션을 T-GR-01 → T-GR-05로 옮겼다(T-GR-01은
  결정 비의존). 포인터 메모(ADR-108·mois etl·integration-map)에서 복제된 상수(상한 12·5 min·21,600 s)와 Skip 규칙
  본문을 빼 ADR-109 결정 5만 가리키게 했고, `address-geocoding.md` §5도 코딩용 이름만 남겼다. (LOW) README 표에
  ADR-107 행 추가, T-GR-07의 `rg` 조건을 append-only 원장 제외로 한정, runbook 배포 순서에 Manager concierge lane
  추가, `address.py:63-119`·`geocoding.py:935`·`definitions.py:113-120` 정정, 머리말의 head sha를 날짜 기준으로.
- **2차 리뷰(2명) 반영 — HIGH 2·MED 8·LOW 11, 기각 0.** (HIGH) 빈 답 가드(행)의 판정 집합에서 provider 원문
  `address.road/legal/admin`을 빼고 geo에서만 오는 집합 G(`sido_name/sigungu_name/admin_dong_code/road_name_code/zipcode`
  + payload 코드 없을 때의 두 코드 열)로 고정했다 — `legal`을 넣으면 krheritage(`:483`)·standard_data(`:296-297`)·
  concierge(`:548`)에서 가드가 영구히 열리지 않는다(T-GR-03 의도적 빨강 (1)에 세 픽스처 명시). MOIS replay 제외
  술어를 **스탬프** `reverse_outcome='not_called'`(unchanged CTE와 같은 술어, 별도 코드 없음)로 박았다 — `raw_data`
  기준이면 스탬프 없는 payload-bjd 행이 `coverage.unstamped`에 남아 완료 판정이 불가능해진다(열린 결정 8의
  선채움은 시간 단축용 "선택"으로 근거 정정). (MED) concierge 토큰 전달 경로(`kor_travel_concierge_items_to_bundles(…,
  current_data_token=)` additive kwarg, 호출처 `assets.py:1508`)를 T-GR-03에; 비-MOIS 비율 가드 분자·분모를
  `GeoCallStats.empty['reverse']`/`calls['reverse']`로 고정(T-GR-01, 현재는 전송 실패만 센다 `:1140-1146`);
  `data_token=None`인 `DatasetRef`도 fail-to-current(스탬프 쓰지도 덮지도 않음 — 두 토큰 열 NOT NULL, NULL 스탬프
  없음); journal·tasks-done 분리를 `T-GR-00-LEDGER`로 독립(T-GR-01 의존); ADR-108 각주·§4 행에 "열린 결정 6 승인 전 미적용"
  표기; timeout 재시도 판별자를 `trigger_kind=sensor`(MOIS 이어 달리기 run에도 붙는다, `mois_chunked_load.py:1071-1075`)
  에서 run 태그 `kor_travel_map.geo_release_plan_id`로 교체(RunRequest 태그에 추가); 값 동일 비교 "7개"→6개,
  `FeatureAddressSnapshot`(`:104-117`)에 `road_name_code`·`admin_dong_code` 추가를 T-GR-03에; pool lint AST 유도의
  현재 동작(키워드 존재만·asset 이름·같은 모듈만)을 사실대로 적고 T-GR-04가 별도 술어 `_passes_geo_callable`+job 매핑을
  더하도록(pool 술어 불변, 과결박 회피). (LOW) 판정 ②를 결과 기준(`geocode_attempted and bjd_code`)으로 ④와 통일하고
  geocode 실패 행은 `not_called`(열린 결정 1 부류); "chunk 단위 판정"→"행별 evidence, chunk commit bulk";
  `_reverse_geocoder(context)` 22→20곳; `has_active_feature_override` 정의 `:5147`/masking 호출 `:829-883`;
  `apply_provider_feature_field_patch`는 프로시저(`:677`); rest_areas `:533-`; `mois.py:685`/`:827`; API validation job
  (`offline_uploads.py:1503`, 적재 없음) 호출자 표 행; Manager lane 단계는 concierge ADR-49 소속 명시; T-GR-02의
  T-GR-03 결박 항목에 "(T-GR-03 뒤)" 표시; concierge payload 코드 행 `not_called`→`called` 변경을 ADR 결정 6(a)에
  "설계와 다른 점"으로 드러냄. 2차 반영 뒤 최종 실측: `tasks-acceptance.md` 189,627 B · `journal.md` ≈ 211.5 KB ·
  ADR-109 31,807 B · `address-geocoding.md` 31,218 B(전부 225,280 B 아래).
- **미결 소유자 결정**: ADR-109 "열린 결정" 13건(task 접두사 `T-GR-` 임시 포함).
