# 문서 정합성 감사 — 2026-06-06 (claude)

이 문서는 사용자 지시("최신 코드 기준으로 문서 전체를 꼼꼼히 읽고 논리적으로 맞지
않는 부분 / Task 등 문서 불일치 / 빠진 부분 / 보강할 부분을 정리")에 따른 **별도
감사 리포트**다. 발견 항목은 `T-DA-NN`(Docs Audit), 사용자 의사결정 항목은
`DA-D-NN`으로 번호를 매겼다. **`tasks.md`로 병합하기 쉽도록** 기존 `T-RV-NN`
백로그 섹션과 같은 체크박스/들여쓰기 포맷을 따른다(§6 병합 가이드 참조).

- **기준 커밋**: `origin/main` = `59a04e8`(PR#225, T-RV-23 offline upload
  idempotency)까지 merged.
- **검증 방식**: 문서 주장(claim)을 코드 ground truth(`.env.example`,
  `docker-compose.yml`, `alembic/versions/*`, `src/krtour/map/*`, `git log`)와
  대조. 단순 인용이 아니라 실제 값을 확인했다.
- **감사 범위(정직성)**: entry/정책 문서(CLAUDE/AGENTS/SKILL/README),
  계획 문서(tasks/resume/journal tail/sprints), `decisions.md`(ADR-001~047 전수
  스캔 + 핵심 ADR 정독), architecture/data-model/category/frontend 클러스터를
  **정독+ground truth 대조**했다. 각 provider `*-etl.md` 본문과
  `openapi-admin-contract.md`의 endpoint↔구현 1:1 대조는 **이번 범위에서
  표본 점검만** 했고, 전수 대조는 `tasks.md` T-212a/T-212c(전체점검 inventory /
  API contract 정리)에 이미 스코프되어 있으므로 그쪽으로 위임한다(→ T-DA-11).

---

## 0. 처리 결과 (사용자 결정 반영, 2026-06-06)

- **DA-D-01 = (A) 포인터로 대체** — `CLAUDE.md §2`, `AGENTS.md "코드 작성 단계"`,
  `sprints/README.md "현 위치"`에서 PR 번호/스프린트 완료여부 서술을 제거하고
  `resume.md`+`tasks.md` 포인터로 대체. 불변 사실(ADR/포트/버전)만 유지. ✅ 적용.
- **DA-D-02 = (A) 한 PR로 전부** — 감사 리포트 + 무쟁점 수정(T-DA-02/03/06) +
  상태 블록(T-DA-01/04/05) + LOW(T-DA-07~10)을 본 PR에 모두 반영. ✅ 적용.
- **category §4 = 표까지 완성** — 확인 결과 `category.md §4.2` 트리는 이미 ADR-027
  3건(`03.08`/`03.08.01`/`03.08.02`)을 포함한 **144행 완성 상태**였고, `§4.3` 통계도
  이미 144였다. 실제 문제는 §3.1/§3.4/§4 헤더/§4.4/§8의 **개수 라벨만 "141"로
  stale**한 것이라, 라벨을 144로 통일했다(데이터 행 추가 불필요). ✅ 적용.

> 따라서 본 리포트의 T-DA-01~10/12는 모두 **본 PR에서 반영 완료**다.
>
> **외부 노출 API 점검 추가(사용자 요청, §8)**: 생성 spec(`openapi.json` 35 path /
> `openapi.user.json` 7 path) ↔ contract 대조로 T-DA-13~17 + DA-D-03/04를 추가했다.
> - **DA-D-03 = 전면 통일** — 모든 admin 응답 `{data, meta}` 표준. 본 PR은 contract
>   §3.1에 표준+현행예외 명시(문서). 코드 전환(T-DA-15/16)은 **별도 PR**.
> - **DA-D-04 = T-212 묶음** — `/admin/issues`(T-DA-13) 미구현은 contract §4·§4.1에
>   "미구현(계획)" 배지(문서). 구현은 T-212b/c.
> - T-DA-14/17(문서 표기)은 본 PR 반영 완료.

---

## 1. 요약 (severity별)

| ID | sev | 한 줄 | 정본(ground truth) |
|----|-----|-------|--------------------|
| T-DA-01 | HIGH | CLAUDE.md §2 "현 단계" 전체가 stale (PR#149 / Sprint4 완료·Sprint5 진입준비) | main=PR#225, ADR-045 standalone 대부분 구현됨 |
| T-DA-02 | HIGH | CLAUDE.md §2 geocoding 로컬 포트 `8888` | `.env.example:58` = **12201** |
| T-DA-03 | HIGH | CLAUDE.md ADR 현황 "001~046 / 다음 ADR-047" | `decisions.md` = **001~047 / 다음 048** |
| T-DA-04 | MED | AGENTS.md "코드 작성 단계"(406~437) stale (Sprint4 완료 / PR#156) | 동일 drift |
| T-DA-05 | MED | sprints/README.md "현 위치"(14~21) stale (PR#149 / Sprint5 🟡 진입준비) | Sprint5/ADR-045 작업 대부분 완료 |
| T-DA-06 | MED | category 개수 "141건" 표기 | 코드 = **144** (`PLACE_CATEGORY_DEFINITIONS`) |
| T-DA-07 | LOW | architecture.md 의존체인 다이어그램에서 `category` 계층 누락 | ADR-023 = `category → dto → …` |
| T-DA-08 | LOW | decisions.md ADR-025 본문 "Next.js 15"/"port 8610"에 supersede 교차참조 없음 | 현재 = Next.js 16(ADR-036) / 포트 12305(ADR-047) |
| T-DA-09 | LOW | decisions.md ADR-002 본문 의존체인이 `api`(폐기) 포함·`category` 누락 | ADR-020/023 반영 안 됨 |
| T-DA-10 | LOW | decisions.md ADR-036 제목이 `v0.1.0` (본문 amendment는 v0.1.2 반영) | 현재 핀 = v0.1.2 |
| T-DA-11 | INFO | openapi-admin-contract ↔ 구현 endpoint 전수 대조 미수행 | T-212a/T-212c로 위임 |
| T-DA-12 | MED | CLAUDE.md §5 "전체 **22개** 룰은 SKILL.md §4" | SKILL.md §4 = **26개** 룰 |

> **2차 스윕 추가분(SKILL.md)**: T-DA-01/03 적용 후 grep 재확인에서 `SKILL.md`도
> 같은 drift를 들고 있었다 — §8 line 289 "001~046 / 다음 047"(→ 001~047/048, T-DA-03
> 동일), §9 "코드 작성 단계" 상태 블록(PR#149/Sprint4 완료, T-DA-01 동일 → 포인터
> 대체), §4 DO NOT 룰 개수 26 vs CLAUDE.md "22"(T-DA-12). 모두 본 PR에서 반영.

**의사결정 필요**: `DA-D-01`(상태 블록 drift 정책), `DA-D-02`(이번 PR에서
무쟁점 수정까지 적용할지) — §5.

---

## 2. HIGH

- [ ] **T-DA-01** — `CLAUDE.md` §2 "현 단계" 블록 전면 stale.
  - **위치**: `CLAUDE.md` §2 ("**v2 Sprint 4 (4a+4b) 완료 / Sprint 5 + ADR-045
    독립 프로그램화 진입 준비**" ~ "2026-06-02 현재 main은 PR#149까지 머지됨" ~
    "다음 작업: ADR-045 독립 프로그램화 …").
  - **근거**: `git log origin/main` = PR#225까지 merged. ADR-045 standalone은
    이미 대부분 구현 완료 — Docker compose/고정 포트(T-209a/c), 독립 Dagster
    asset/schedule/sensor(T-208a~i), feature update 큐/scope resolver/admin
    REST(T-205~T-207), offline upload(T-208g~i), batch gate(T-200), 운영 게이트
    (T-202~T-204), PR#153~#179 리뷰 백로그(T-RV-01~28, 37a~e) 모두 closed.
    Phase 2 정합성도 F4~F7 구현됨(F8 + dry-run report만 잔여, `resume.md` 최상단).
  - **조치**: §2를 현재 상태로 갱신하되, **PR 번호/스프린트 완료 여부를 본문에
    하드코딩하지 말고** `docs/resume.md`(단일 진척) + `docs/tasks.md`(백로그)를
    가리키게 한다 → `DA-D-01` 결정에 따름.

- [ ] **T-DA-02** — `CLAUDE.md` §2 geocoding 로컬 기본 포트 `8888` stale.
  - **위치**: `CLAUDE.md` §2 "geocoding 정본: kraddr-geo REST(v2 …), 로컬 기본
    `http://127.0.0.1:8888`".
  - **근거**: `.env.example:58` `KRTOUR_MAP_KRADDR_GEO_BASE_URL=http://127.0.0.1:12201`,
    `:32` `KRTOUR_MAP_ADMIN_KRADDR_GEO_BASE_URL=http://127.0.0.1:12201`.
    `tasks.md` 체크포인트 #4, `AGENTS.md`, `journal.md:1151`("기본값에서 이전
    `8888` 표기를 제거")도 모두 **12201**. CLAUDE.md만 누락된 sweep 잔재.
  - **조치**: `8888` → `http://127.0.0.1:12201`.

- [ ] **T-DA-03** — `CLAUDE.md` ADR 현황/다음 번호 stale.
  - **위치**: `CLAUDE.md` §2 ("ADR 현황: **001~046 모두 accepted** … 다음 후보
    번호 = **ADR-047**") + §5 말미("ADR-047 …")의 번호 가정.
  - **근거**: `docs/decisions.md`에 **ADR-047**(standalone 고정 포트)까지 accepted
    본문 존재. `AGENTS.md:51-52`("001~047 전부 … 다음 후보 번호는 ADR-048"),
    `tasks.md:829`("001~047 accepted. 다음 후보 번호 = ADR-048")와도 어긋남.
  - **조치**: CLAUDE.md를 "001~047 accepted / 다음 후보 = ADR-048"로 정정하고
    ADR-047(고정 포트)·ADR-046(shim 금지+kraddr-geo v2 통일) 한 줄 요약 추가.

---

## 3. MED

- [ ] **T-DA-04** — `AGENTS.md` "코드 작성 단계" 블록 stale (T-DA-01과 동일 drift).
  - **위치**: `AGENTS.md` lines 406~437 ("Sprint 1~4(4a+4b)는 완료 … 2026-06-02
    현재 main은 **PR#156**(Docker/고정 포트 표준화)까지 머지된 상태다", "**현재
    상태 (2026-06-02)**" 목록, "**다음 단계**: 독립 Dagster queue/schedule/sensor
    …").
  - **근거**: 위 작업들은 이미 구현 완료(T-208d schedule, T-208e sensor 등).
    main=PR#225.
  - **조치**: 블록을 현재로 갱신하거나 `resume.md`/`tasks.md` 포인터로 축약 →
    `DA-D-01`. (단, AGENTS.md 상단의 식별자 표·DO NOT 22룰·포트/버전은 이미 최신.)

- [ ] **T-DA-05** — `docs/sprints/README.md` "현 위치" 블록 stale.
  - **위치**: `sprints/README.md:14-21` ("**현 위치 (2026-06-02)**: … PR#149까지
    merged …") + 표 Sprint 5 상태 "🟡 진입 준비".
  - **근거**: Sprint 5/ADR-045 작업 대부분 완료(§T-DA-01 근거). PR#149 stale.
  - **조치**: "현 위치" 블록을 `resume.md` 포인터로 축약(또는 갱신), Sprint 5
    상태를 "🟢 진행 중(Phase 2 F8/dry-run + ADR-045 잔여 T-201b/T-209b/T-212만 잔여)"
    수준으로 정정 → `DA-D-01`.

- [ ] **T-DA-06** — category 개수 표기 "141건" vs 코드 144건.
  - **위치**: `docs/category.md:115` ("## 4. Tier 1~4 카탈로그 (**141건** 전체)"),
    `:118` ("총 **141건** = sentinel 1 + …"); `docs/debug-ui-package.md:446`
    ("전체 **141건**은 docs/category.md §4"); `docs/decisions.md:1019` (ADR-030
    근거 "Tier 1~4 PlaceCategoryCode 카탈로그 (**141건**)").
  - **근거**: 코드 권위값 = **144**. `python -c "from krtour.map.category import
    PLACE_CATEGORY_DEFINITIONS, PlaceCategoryCode; print(len(PLACE_CATEGORY_DEFINITIONS),
    len(list(PlaceCategoryCode)))"` → `144 144`. `journal.md:5044-5049`도 "144건 =
    141(kraddr-base) + ADR-027 3건". `decisions.md:1559`(ADR-027)는 이미 "144건".
  - **조치**: 위 "141건" 표기를 **144건**으로 정정(필요 시 "= 141 base +
    ADR-027 3"). **단** `category.md §4` 카탈로그 표가 실제로 141행만 가지고
    있으면 ADR-027 3행(예: `LODGING_MOUNTAIN_SHELTER` 등) 추가 필요 여부를 함께
    확인 → `DA-D-02` 범위.

---

## 4. LOW (역사 기록 보존 원칙과 충돌하지 않는 선에서)

> `decisions.md` 상단 원칙: "결정이 뒤집힐 때도 이전 기록은 지우지 않고
> `superseded by ADR-XXX`로 표시". 아래 LOW 항목은 본문을 바꾸기보다 **한 줄
> 교차참조**를 더하는 방향을 권한다.

- [ ] **T-DA-07** — `architecture.md` 큰그림 다이어그램의 의존체인에 `category`
  누락. `:54` "dto → core → infra → providers → client → cli" → ADR-023 정본은
  `category → dto → core → infra → providers → client → cli`. §2 본문도 함께 확인.
- [ ] **T-DA-08** — `decisions.md` ADR-025 본문이 "Next.js 15"(`:702`)·"`next dev
  --port 8610`"(`:769`)을 현행처럼 서술. 역사 기록은 유지하되 각 위치에 "→ 현재
  기준: Next.js 16(ADR-036 amendment 2026-05-31) / 포트 12305(ADR-047)" 한 줄 추가
  권장.
- [ ] **T-DA-09** — `decisions.md` ADR-002 본문 의존체인(`:40` "dto → core → infra
  → providers → client → **api/cli**")이 `api`(ADR-020으로 폐기)를 포함하고
  `category`(ADR-023)를 누락. ADR-002 결과/후속 절에 "체인은 ADR-020(api 제거)/
  ADR-023(category 추가)로 갱신됨" 한 줄 추가 권장.
- [ ] **T-DA-10** — `decisions.md` ADR-036 **제목**이 "… 분리 + **v0.1.0**".
  본문에 v0.1.2 amendment(`:1892`)가 이미 있으므로 제목만 stale. 제목에
  "(현행 핀 v0.1.2 — amendment 2026-05-31 참조)" 보강 권장(선택).

---

## 5. 의사결정 필요 (DA-D)

- **DA-D-01 — entry/정책 문서의 "현 단계/현 위치" 상태 블록 drift 정책.**
  CLAUDE.md §2, AGENTS.md "코드 작성 단계", sprints/README "현 위치"가 **각각 다른
  stale PR 번호(149/156/149)** 를 하드코딩하고 있어 반복적으로 어긋난다(구조적
  drift 원인). 선택지:
  - **(A) 권장** — 세 문서에서 PR 번호·스프린트 완료여부 등 "현재 진척" 서술을
    제거하고 `docs/resume.md`(단일 진척) + `docs/tasks.md`(백로그)를 가리키는 한
    줄 포인터로 대체. → drift class 자체를 없앤다. ADR/포트/버전 같은 **불변
    사실**은 본문 유지.
  - **(B)** — 블록은 유지하되 지금 #225 기준으로 갱신 + `AGENTS.md` 작업 후
    체크리스트에 "현 단계 블록 갱신" 항목 추가(갱신 책임 명시).
  - **(C)** — 지금 값만 갱신(추가 정책 없음). 다음 drift는 다시 발생.

- **DA-D-02 — 이번 작업의 적용 범위/순서.**
  사용자 플로우는 "감사 리포트 → 의사결정 → 그에 따라 문서 업데이트 → PR/머지".
  무쟁점 수정(T-DA-02 포트, T-DA-03 ADR 번호, T-DA-06 category 144)은 사실
  오류라 결정이 불필요하다. 선택지:
  - **(A) 권장** — 이 감사 리포트 + 무쟁점 수정(T-DA-02/03/06, 그리고 DA-D-01
    선택에 따른 T-DA-01/04/05)을 **한 PR**로 묶어 머지. LOW(T-DA-07~10)는 같은
    PR에 포함하거나 후속.
  - **(B)** — 감사 리포트만 먼저 PR/머지하고, 수정은 결정 확정 후 후속 PR.
  - category.md §4 카탈로그가 141행만 있으면 3행 추가가 **데이터 작업**이므로,
    그 부분만 T-DA-06b로 분리해 후속 처리할지 함께 결정.

---

## 6. tasks.md 병합 가이드

- 본 리포트의 §2~§4 항목은 `tasks.md`의 "## 코드 리뷰 후속 백로그(PR#153~#179)"
  T-RV 섹션과 **동일 포맷**(`- [ ] **T-DA-NN** … 위치/근거/조치`)이다. 그대로
  `tasks.md`에 새 섹션 **"## 문서 정합성 백로그 (T-DA, 2026-06-06)"** 로 붙이고,
  완료 시 `~~취소선~~` + `✅`로 마감하면 된다(T-RV 관례와 동일).
- 정본 상세는 본 리포트가 갖고, `tasks.md`에는 한 줄 요약 + 본 파일 링크만 두는
  방식(T-RV가 `pr-153-179-review-2026-06-04.md`를 정본으로 두는 패턴)을 권장.
- `DA-D-NN` 결정은 확정 시 해당 ADR/문서에 반영하고, 새 정책이면 ADR-048
  후보로 승격 가능(DA-D-01 (A) 채택 시 "진척 상태의 단일 정본은 resume.md/
  tasks.md" 라는 경량 규칙이라 ADR까지는 불필요할 수 있음).

## 7. 확인했지만 정상이라 조치 불필요(혼동 방지용 기록)

- `coord_precision_digits`(T-RV-16)는 `data-model.md`/`postgres-schema.md`/
  `performance.md`/`poi-cache-update-targets.md`에 **이미 반영**됨. 누락 아님.
- `tripmate-integration.md`는 상단에 **ADR-045 supersede 배너**가 이미 있음.
- `architecture.md` 큰그림은 Docker 독립 프로그램 + OpenAPI 모델로 **최신**.
- 포트 `8087`/`8610`은 `journal.md`/`docs/reports/*`(역사 로그)와 ADR-025/047
  (superseded 맥락)에만 남아 있고 **현행 실행 문서에는 12301/12305 사용** — 정상.
- alembic 마이그레이션은 `0001`~`0016`까지 실제 존재(0016 = offline upload
  idempotency). 문서가 인용한 0007/0008/0009/0011/0012 등과 일치.
- `.env.example` 포트(API 12301 / web 12305 / Dagster 12302 / Postgres 5432 /
  kraddr-geo 12201 / RustFS 12101·12105)는 ADR-047 및 `AGENTS.md` 식별자 표와 일치.

---

## 8. 외부 노출 API 일관성/완결성 점검 (2026-06-06 추가, 사용자 요청)

기준: 생성 산출물 `packages/krtour-map-admin/openapi.json`(admin 전체, **35 path**)
+ `openapi.user.json`(TripMate/user subset, **7 path**)을 정본으로,
`docs/openapi-admin-contract.md` + `docs/tripmate-rest-api.md`와 대조했다.

### 8.1 빠진 기능 (문서엔 있으나 미구현)

- [ ] **T-DA-13** (MED, **missing feature**) — `/admin/issues` 운영 API 전부 미구현.
  - **근거**: `openapi-admin-contract.md §4.1`(125~152)이 `GET /admin/issues`,
    `GET /admin/issues/{issue_key}`, `PATCH /admin/issues/{issue_key}`(`resolve`/
    `ignore`/`reopen`/`retry_geocode`/`retry_reverse_geocode`/
    `apply_kraddr_geo_address`/`manual_override`)를 **"필수 엔드포인트"**로 명세하지만,
    `openapi.json` 35 path에 `/admin/issues*`가 **없다**(라우터 파일도 없음). 읽기 측
    `GET /ops/consistency/issues`만 존재.
  - **영향**: ADR-046의 핵심인 **주소/좌표 정합성 이슈를 운영자가 admin UI에서 수동
    처리**(재지오코딩/override/채택/ignore)하는 write/action 경로가 통째로 비어 있다.
    정합성 검사(F5~F7)는 `ops.data_integrity_violations`에 이슈를 *쌓지만*, 그걸
    *해소*하는 API가 없다. ADR-046 결정 §4 "결측/불일치는 admin issue로 수동 처리"가
    미이행.
  - **조치**: `/admin/issues` 라우터 구현을 별도 task로 신설(또는 `T-212c`에 명시
    편입)하고, 그 전까지 contract 문서에 **"미구현(계획)"** 배지를 단다.

- [ ] **T-DA-14** (LOW, doc 불일치) — `admin-providers` `/admin/providers`가 contract
  §4 tag 표(106줄)에 캐비엇 없이 올라 있으나 **미구현**(T-207b 사용자 결정으로 취소,
  `feature-update-requests`의 `provider_dataset` scope로 대체). 같은 문서 513줄은
  이 취소를 설명하지만 §4 표는 그대로 → 표 행에 "(미구현 — T-207b 취소)" 표기.

### 8.2 일관성 (응답 셰입)

생성 spec에서 실측한 셰입 분포:

- **list 응답이 두 갈래로 갈림**:
  - `{data, meta}`(envelope, cursor는 meta): `/admin/dedup-review`,
    `/admin/features`, `/features/search`, `/features/nearby/by-target`,
    `/ops/consistency/{issues,reports}`, `/ops/import-jobs` (7)
  - `{count, items, next_cursor}`(flat): `/admin/feature-update-requests`,
    `/admin/offline-uploads`, `/admin/poi-cache-targets` (3)
  - `{count, items}`(cursor 없음, 의도된 admin-compat): `/features` (1)
- **단건/detail 응답도 갈림**: `/features/{id}` = `{data, meta}`,
  `/ops/import-jobs/{job_id}` = `{data}`(meta 없음), 나머지 단건
  (`/admin/feature-update-requests/{id}`, `/admin/offline-uploads/{id}`,
  `/admin/poi-cache-targets/{id}`, `/ops/dagster/summary`, `/ops/metrics`,
  `/debug/mois-license/{id}`) = **bare object**.
- **mutation(POST/PATCH/PUT)은 일관**되게 `{data, meta}`다 — 양호.

- [ ] **T-DA-15** (MED, API consistency) — list 응답 셰입 이원화
  (`{data,meta}` vs `{count,items,next_cursor}`). 외부에 노출되는 단일 OpenAPI
  계약 안에서 페이지네이션 표면이 둘로 갈려 client(특히 generated TS type)가
  resource마다 다른 모양을 다뤄야 한다. → 표준 envelope로 통일(DA-D-03).
- [ ] **T-DA-16** (MED, API consistency) — 단건 응답 envelope 불일치. **특히
  user subset 영향**: `openapi.user.json` 7 path 중 `/admin/feature-update-requests/
  {request_id}`만 **bare object**이고 나머지(`/features/*`, `/tripmate/features/batch`)는
  `{data, meta}` → TripMate에 노출되는 사용자 API 안에서 단건만 모양이 다르다. →
  통일(DA-D-03).
- **T-DA-17** (INFO) — `openapi-admin-contract.md`가 구현/미구현 endpoint를 한 표에
  섞어 제시한다. `T-212c` 정리 시 endpoint별 상태(구현/계획) 표기를 권장.

### 8.3 의사결정 (확정, 2026-06-06)

- **DA-D-03 = 전면 통일** — 모든 admin 성공 응답을 `{data, meta}`로 통일(list는
  `meta.next_cursor`+`count`). 본 문서 PR에는 **목표 표준을 contract §3.1에 명시**하고
  현행 예외 목록을 적었다. 실제 코드 전환(3 flat list + 6 bare 단건 + admin frontend
  hook + `openapi.*.json` 재생성)은 **별도 코드 PR**로 진행 — T-DA-15/16.
- **DA-D-04 = T-212 묶음** — `/admin/issues`(T-DA-13)는 admin UI 이슈 승인/거절
  화면(T-212b)과 write/action API(T-212c)를 함께 구현. 본 PR에서는 contract §4 표와
  §4.1에 **"미구현(계획)" 배지**만 반영했다.

> 본 문서 PR 반영분: contract §3.1(표준 + 현행 예외), §4 표·§4.1(미구현 배지),
> T-DA-14 doc 표기. **코드 변경(T-DA-15/16 envelope 통일, T-DA-13 /admin/issues
> 구현)은 후속 PR**.
</content>
</invoke>
