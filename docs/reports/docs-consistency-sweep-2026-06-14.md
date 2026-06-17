# 문서 정합성 스윕 — 2026-06-14 (claude)

사용자 지시("문서 정합성 스윕")에 따른 **후속 감사 리포트**다. 직전 정본
감사 [`docs-consistency-audit-2026-06-06.md`](docs-consistency-audit-2026-06-06.md)
(T-DA-01~17, 모두 적용 완료)의 연속이며, 발견 번호는 `T-DA-18`부터 매겼다.
사용자 의사결정 항목은 직전 관례대로 `DA-D-NN`을 잇는다.

- **기준 커밋**: `origin/main` = `b6fda93`(#437 krex 자연키 정정 머지 후).
- **검증 방식**: 문서 claim을 코드/형제 repo ground truth와 대조 — `.env.example`,
  `src/kortravelmap/settings.py`, `docs/decisions.md`,
  `F:/dev/kor-travel-docker-manager/.env.example`(고정 포트 owner),
  `F:/dev/kor-travel-concierge/.env.example`, `git ls-files`/`git log`. 단순 인용이
  아니라 실제 값을 확인했다. 5개 차원 병렬 감사(① 상태 drift ② ADR 원장 ③ 포트·
  식별자 ④ 끊어진 링크 ⑤ 교차 주장·완결성) + 종합.
- **범위/정직성**: **현행·정본 운영 문서만** 수정 대상. `docs/journal.md`와 dated
  `docs/reports/*.md`는 역사 기록으로 보존(끊어진 링크만 점검). `decisions.md`는
  역사 보존 원칙상 본문 재작성 없이 **교차참조만** 더했다.

---

## 1. 요약 (severity별)

| ID | sev | 한 줄 | 정본(ground truth) | 상태 |
|----|-----|-------|--------------------|------|
| T-DA-18 | HIGH | `resume.md` 3개 정본 섹션(현재 상태/다음 한 작업/열린 작업 요약)이 **완료된 T-225**를 즉시·유일 잔여로 표기 | T-225·T-229 모두 closed(`tasks-done.md`), 잔여 = `T-229-buildx` | ✅ 적용 |
| T-DA-19 | MED | `sprints/README.md` Sprint5 상태 셀 + anti-drift note가 "`T-225`만 남음" | 동일 closure, 잔여 = `T-229-buildx`(`tasks.md`) | ✅ 적용 |
| T-DA-20 | MED | `SKILL.md:298` 진입 순서 "ADR 001~049 / 다음 050" (7건 stale, 같은 파일 §1 표와 모순) | `decisions.md` 최상위 = ADR-056 / 다음 057 | ✅ 적용 |
| T-DA-21 | HIGH | `integration-map.md` concierge "API 12401 · web 9042" — **12401은 docker-manager Prometheus** (host 포트 1개를 2시스템에 배정) | concierge = API 12601 / MCP 12602 / web 12605 | ✅ 적용 |
| T-DA-22 | MED | `runbooks/docker-app.md:55` offline upload bucket 기본 "`krtour-uploads`" (같은 파일 L189와 모순) | `settings.py:97` 기본 `kor-travel-map-uploads` | ✅ 적용 |
| T-DA-23 | LOW | spec docx 죽은 참조 — CLAUDE/README/SKILL이 `kor-travel-map-spec.docx` 인용하나 추적 파일은 구명 | 추적 = `kor-travel-map-spec.docx` (ADR-054 clean-cut에서 파일만 누락) | ✅ rename (DA-D-05=A) |
| T-DA-24 | LOW | `AGENTS.md:411` 체크리스트 `scripts/export_openapi.py` 경로 stale | ADR-055 분리 후 `packages/kor-travel-map-api/scripts/export_openapi.py` | ✅ 적용 |
| T-DA-25 | INFO | `decisions.md` ADR-035 본문에 ADR-045 부분 supersede **역참조 없음** (003/029는 있음) | 상태줄에 한 줄 교차참조 추가 | ✅ 적용 |
| T-DA-26 | INFO | ADR 원장 무결성 스캔 — 001~056 연속, 갭/중복 없음 (028/029 물리 순서만 어긋남, 갭 아님) | 조치 불필요(혼동 방지 기록) | — |

> 구조적 원인: T-DA-18/19/20은 모두 **"완료 시점에 정본 섹션을 동기화하지 못한"**
> 동일 drift class(직전 DA-D-01과 동근). `tasks.md`는 이미 정확했고(`T-229-buildx`
> 단일 항목), `resume.md` 하단 정본 섹션·`sprints/README.md`·`SKILL.md` 한 줄만
> 뒤처졌다. 정본 진척은 `resume.md`/`tasks.md`가 갖는다는 규칙은 유지되나, 그
> *내용*이 lag한 사례다.

---

## 2. HIGH

- [x] **T-DA-18** — `resume.md` 정본 섹션 3곳이 완료된 T-225를 가리킴.
  - **위치**: §현재 상태("즉시 실행 가능한 남은 큰 트랙은 T-225 하나다"), §다음 한
    작업("### T-225 — T-212e closure 재검증" 블록 전체), §열린 작업 요약 → 즉시
    ("- `T-225` …").
  - **근거**: T-225 closed `6f4c747`(PR#435, 2026-06-13), T-229 closed
    `33875e3`(PR#436, 2026-06-14) — 둘 다 `tasks-done.md`에 `[x]`. 본 저장소 잔여 =
    `T-229-buildx`(arm64, `GITHUB_TOKEN` 배포환경)뿐(`tasks.md:16-19,44-55`).
    `resume.md` **자신의** 2026-06-14 최상단 메모도 이미 그렇게 적고 있다.
  - **조치(적용)**: 3개 섹션을 `T-229-buildx` 기준으로 정정. §고정 기준값(L131-146)은
    이미 정확해 손대지 않음.

- [x] **T-DA-21** — `integration-map.md` kor-travel-concierge 포트 오기 + 충돌.
  - **위치**: §1 시스템·포트 표(concierge 행), §2 데이터 흐름 다이어그램.
  - **근거**: concierge 고정 host 포트 = API 12601 / MCP 12602 / Web 12605 —
    `F:/dev/kor-travel-concierge/.env.example`(`API_HOST_PORT=12601` …) + 포트 owner
    `F:/dev/kor-travel-docker-manager/.env.example`(`KOR_TRAVEL_CONCIERGE_API_PORT=12601`,
    `_MCP_PORT=12602`, `_UI_PORT=12605`)에서 확인. 기존 "12401"은 같은 표(L23/L43)의
    docker-manager **Prometheus** 포트와 충돌. "9042"는 현행 근거 없음.
  - **조치(적용)**: 표·다이어그램 모두 12601(+MCP 12602/web 12605)로 정정.

## 3. MED

- [x] **T-DA-19** — `sprints/README.md` Sprint5 상태/anti-drift note가 T-225 하드코딩.
  근거: T-DA-18과 동일 closure. 같은 파일 L14-15가 "진척 정본은 resume/tasks"라고
  선언하면서 L12/L20에 stale 상태를 박아 자기모순. 조치: `T-229-buildx`로 정정 +
  정본 포인터 유지.
- [x] **T-DA-20** — `SKILL.md:298` "ADR 001~049 / 다음 050". 근거: `decisions.md`
  최상위 헤더 `## ADR-056`(Accepted 2026-06-13), 다음 057. CLAUDE.md:46 /
  AGENTS.md:61-62 / README.md:17 / SKILL.md §1 표(L61)는 이미 001~056. 직전 적용된
  T-DA-03과 동일 class인데 이 한 줄만 sweep에서 누락. 조치: 001~056 / 057로 정정.
- [x] **T-DA-22** — `runbooks/docker-app.md:55` offline bucket 기본 `krtour-uploads`.
  근거: `settings.py:97` `default="kor-travel-map-uploads"` + `.env.example` 일치.
  같은 runbook L189는 이미 정명 사용(내부 모순). 조치: `kor-travel-map-uploads`로 정정.

## 4. LOW (역사 보존 원칙과 충돌 없는 선)

- [x] **T-DA-23** — spec docx 죽은 참조. CLAUDE.md:70 / README.md:30 / SKILL.md:320이
  `kor-travel-map-spec.docx`를 인용하나 `git ls-files '*.docx'` = `kor-travel-map-spec.docx`
  단 하나(인용명 0매치). ADR-054가 `kor-travel-map`을 정체성으로 박았으므로 파일
  rename이 intent-정합. **DA-D-05 = (A) rename 채택** → `git mv kor-travel-map-spec.docx
  kor-travel-map-spec.docx`(3개 참조 일괄 해소, git 이력 보존).
- [x] **T-DA-24** — `AGENTS.md:411` `scripts/export_openapi.py` 경로 stale. ADR-055 API
  패키지 분리 후 실제 위치 = `packages/kor-travel-map-api/scripts/export_openapi.py`
  (root `scripts/`에 없음, `git ls-files` 확인). 다른 문서(debug-ui-package/openapi-
  admin-contract/decisions)는 이미 패키지 경로. 조치: 경로 정정.

## 5. INFO

- [x] **T-DA-25** — `decisions.md` ADR-035 상태줄에 ADR-045 부분 supersede 역참조
  추가(본문 재작성 아님). ADR-045(`:2452`)는 "ADR-035의 debug-ui 범위 표현 일부"
  supersede를 선언하나 ADR-035에는 역참조가 없었다(003/029는 있음). 역사 보존
  원칙상 **상태줄 한 줄 교차참조만** 더함.
- **T-DA-26** — ADR 원장 갭/중복 스캔 결과 **clean**: `## ADR-0NN` 헤더 56개,
  001~056 연속, 갭/중복 없음. 파일 내 'proposed'는 템플릿 범례(`:1766`) 1건뿐.
  ADR-028/029 본문이 물리적으로 순서 뒤바뀐 것은 파일 배치 quirk이지 번호 갭이
  아니다(향후 스윕 오탐 방지용 기록). 조치 불필요.

---

## 6. 확인했지만 정상이라 조치 불필요 (혼동 방지 기록)

- **포트 baseline 전부 정합**: API 12701 / admin 12705 / Dagster 12702 / RustFS
  12101·12105 / kor-travel-geo 12501 / Postgres 5432 — `.env.example`·`docker-compose.yml`·
  CLAUDE.md·AGENTS.md·integration-map.md·SKILL.md·deploy.md·dev-environment.md·
  resume.md(§고정 기준값) 일치. 현행 문서에 구 123xx/122xx **앱** 포트 잔재 없음.
- `deploy.md`/`integration-map.md`의 12301(cAdvisor)·12401(Prometheus)·12205(Grafana)는
  docker-manager **관측 스택** 포트로 정상(owner `.env.example` 확인) — 앱 포트 아님.
- **ADR 카운트 정합**: CLAUDE.md:46·AGENTS.md:61-62·README.md:17·SKILL.md §1 표 모두
  "001~056 / 다음 057"로 `decisions.md`와 일치(SKILL.md:298 한 줄만 stale였음 → T-DA-20).
- **supersede 양방향 기록**: 045→003·029→043·049/050→053은 양쪽에 역참조 존재.
  ADR-035만 누락이었다(→ T-DA-25).
- **DA-D-01 anti-drift 정책 유지**: CLAUDE.md §2·AGENTS.md §9·SKILL.md §9·README.md는
  resume/tasks 포인터를 쓰고 불변 기준값만 박았다 — stale PR#/스프린트 완료 서술이
  재유입되지 않았다.
- `tasks.md`는 현행·내부정합(인덱스 L16-19 ↔ 상세 L44-56, 둘 다 `T-229-buildx` 단일
  open `[ ]`; 현재 상태 prose에 T-225/T-229 완료 명시) — **수정 없음**.
- `tasks-done.md`에 T-225/T-229 `[x]` 정상 아카이브.
- coverage gate `fail_under=80`(ADR-032) = `pyproject.toml`; frontend 핀 Next.js ^16 /
  React ^19 / `maplibre-vworld-js#v0.1.3`(ADR-036) = `package.json`; provider 9단계
  (ADR-034) = CLAUDE.md ↔ sprints/README ↔ decisions; geocoding `POST /v2/{reverse,
  geocode}` @ `127.0.0.1:12501` = 전 문서 일치(구 8888 없음). SKILL.md "26개 룰" =
  CLAUDE.md — 모두 정상.
- 패키지/정체성 값 정합: 배포명 `kor-travel-map`, import root `kortravelmap`, API
  `kor-travel-map-api`(`kortravelmap.api`), admin `kor-travel-map-admin`, CLI `ktmctl`,
  env prefix `KOR_TRAVEL_MAP_*`, DB `kor_travel_map`/`kor_travel_map_dagster`.
- `resume.md`/`tasks.md`가 참조하는 report 링크 전부 disk에서 resolve. README 문서
  지도/runbooks 인덱스 링크 모두 resolve.
- `integration-map.md`의 "krtour Dagster" 류 **이름-only** 언급(L30/33/50)은 같은
  문서 L12-14 전환기 명칭 note가 커버 — 포트/계약 drift 아니라 보존(별도 naming
  후속에서 정리 가능).
- `journal.md`/dated `reports/*.md`의 과거 closure·구 포트 서술은 역사 기록 —
  비-조치.

---

## 7. 의사결정 (DA-D)

- **DA-D-05 (확정, 2026-06-14) = (A) 파일 rename** — `kor-travel-map-spec.docx` →
  `kor-travel-map-spec.docx`(T-DA-23). 3개 entry 문서가 이미 쓰는 canonical 이름 +
  ADR-054 정체성에 맞춤. 본 PR 반영.
- **DA-D-06 (참고) — concierge 포트 발행 전 maintainer 교차확인 권장(T-DA-21).**
  in-repo 값(12601/12602/12605)은 두 `.env.example`에서 확정적이고 기존 12401은
  Prometheus 충돌로 **명백한 오류**라 정정은 결정 불요. 다만 integration-map은
  cross-repo 정본 지도이므로, concierge 측과 최종 포트만 분기 점검(`runbooks/
  cross-repo-audit-checklist.md`)으로 재확인하면 좋다.

## 8. tasks.md 병합 가이드

T-DA-18~26은 **전부 사실 정정(또는 INFO)** 이라 본 PR에서 반영 완료 — `tasks.md`에
새 백로그 항목으로 남길 것은 없다(직전 T-DA-01~17와 동일 처리). 본 리포트가 정본
기록이고, 후속 추적이 필요한 잔여 작업은 기존 `T-229-buildx` 하나뿐이다.
