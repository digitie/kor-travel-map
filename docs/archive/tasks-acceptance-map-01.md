# tasks-acceptance 아카이브 — `T-MAP-01` (완료)

> `T-MAP-01`의 해제 조건 원문이다. 절은 닫혔고, live 문서
> [`../tasks-acceptance.md`](../tasks-acceptance.md)가 220 KiB(225,280 bytes)
> 상한에 닿아 `docs/tasks-rule.md` §8대로 분리했다(2026-10-16).
>
> **본문은 바이트 단위로 보존했다** — 옮기기만 했고 한 글자도 고치지 않았다
> (파일 끝 빈 줄만 하나로 정규화).
>
> **분리 전에 쟀다.** `scripts/archive_task_ledger_section.py`가 확인한 것:
> 이 절의 fence 마커 0개(짝), 시작·끝 경계 모두
> fence 밖, 그리고 옮긴 뒤 두 파일의 `parse_checkboxes` 결과 합이 옮기기 전과
> **다중집합으로 같음**. 2026-09-13에 제목 기준으로 원장을 통째로 쪼개려다
> 되돌린 적이 있는데, 그때 깨진 것이 바로 이 성질이다.
>
> 과거 검색은 `rg <패턴> docs/archive/`.

## T-MAP-01

2026-10-13 Track 2 설계(geo·weather·transport의 odroid 이전)에서 열었다. 접두사 `T-MAP-`는 임시다(ADR-110 열린
결정 5; 소유자가 `T-NNN` 정식화를 고르면 `T-MAP-01`·`02`를 재번호하되 journal·acceptance 참조도 함께). 문서만
바꾸는 PR이다 — 브랜치 `docs/adr-110-geo-transport-on-odroid`(origin/main `f7affea8`에서).

- 만든/고친 것: `docs/adr/110-geo-transport-hosts-move-to-odroid.md`(proposed), `docs/adr/README.md`(다음 후보 111,
  110 행), `docs/integration-map.md` §1(geo·transport 행 '계획: 호스트 odroid' + Manager ADR-58 포인터)·§2(LAN
  화살표·timeout)·§3(transport export 행 allow-list)·§4(geocoding 행 핀 금지 재확인), `CLAUDE.md` geocoding 정본 줄,
  `docs/tasks.md`·이 절·journal·resume.
- 하지 않은 것(범위 밖, 금지): `src`·`packages`·`alembic`·`tests`·`.env.example`·`docker/**`·CHANGELOG·`openapi.json`.
  `.env.example:198,234`의 standalone 주석은 T-MAP-02 코드 PR에 싣는다.
- 해제 조건: 문서 lint(`tests/unit/test_docs_archive_links.py` 225,280 B 상한 포함·`tests/lint/test_task_ledger_conventions.py`·
  `scripts/check_task_ledger_deletions.py`·`scripts/check_prod_redaction.py` #508 — docs에 사설 IP 리터럴 0건, 호스트는
  이름으로) 초록 + ADR README 카운터 연속(109 → 110 → 다음 111) + 인용 file:line이
  head에 존재(`settings.py:150,159-164,165-176,364-374,388,509-519,537-542`; `route.ts:3-6`; `frontend.Dockerfile:57,62`;
  `kor_travel_transport.py:104,435-452`; `assets.py:184`; geo client 8곳 `resources.py:1073-1076`·`app.py:709-712`·
  `feature_update_service.py:527`·`api/routers/offline_uploads.py:1482`·`admin_issues.py:276,306`·
  `dagster/offline_uploads.py:50-53`·`cli/main.py:447`) + 머지(doc-only — 소유자 지시(2026-07-28 이후 반복)로 pytest
  세션은 생략하되 `lint.yml` 초록 뒤; CLAUDE.md §5-1의 "CI green"은 doc-only PR에서 lint.yml로 충족한다).
- 종결 소유자: `[x]` 전환·`tasks-done.md` 이관은 머지가 조건이라 이 PR 안에서 할 수 없다 — **T-GR-00-LEDGER**가
  단일 소유다(§T-GR-00-LEDGER 마지막 문장; T-MAP-02는 T-GR-00-LEDGER를 선행으로 두므로 닫을 경우가 없다 — '또는'은
  두 PR이 서로 상대가 했다고 믿는 구멍이라 쓰지 않는다. T-GR-00 선례).
- 설계와 달리 쓴 것: `frontend.Dockerfile` 인용을 `:56` → `:57`(ARG)·`:62`(ENV)로, preflight를 `:164-176` → `:165-176`로
  정정(1차 리뷰가 초고의 `:165-177`·`:509-520` 한 줄 초과를 잡았다); geo client 생성 지점은 설계의 암묵 "4곳"이 아니라
  **8곳**(1차 리뷰 HIGH — `admin_issues.py` 2곳은 timeout 인자 없음, `dagster/offline_uploads.py`·`cli/main.py`는
  `10.0` 하드코딩); Map에는 회로차단을 두지 않는다(ADR-110 결정 3 — 설계 §9.1의 Map 행은 connect 분리만 요구한다);
  설계 §14-19(전량 재계획 수용 vs 운영자 skip)는 결정이 아니라 추천으로 적고 열린 결정 2에 올렸다; 설계 §9.1·§5.6 ⑥의
  "geo 키는 loopback 면제라 검증된 적 없다"는 **틀려서** 정정했다(geo 면제는 admin 프록시 컨텍스트만 — geo
  `security.py:154-170`; Map 호출은 오늘도 대조된다, 08-13 사고 `settings.py:168-171`; ADR-110 컨텍스트 4·결정 4·열린
  결정 3 — 2차 리뷰); LAN 주소 리터럴은 `scripts/check_prod_redaction.py`(#508) 때문에 호스트 이름으로 썼다; T-MAP-02
  착수 순서는 설계 §13 사슬과 달리 병렬을 **제안**만 하고 열린 결정 6으로 올렸다.
