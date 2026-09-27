# journal 아카이브 — 2026-08-29 ~ 2026-08-31

> live `docs/journal.md`에서 분리한 과거 기록(docs/tasks-rule.md §8). 읽기 전용 이력이다.

## 2026-08-31 — M05 rebuild 두 번째 벽: permit evidence의 반쪽 head-인지

#1128로 sealed builder를 고치고 pinset을 재회전(Map 58158472)해 rebuild를 다시
돌렸더니 이번엔 API/Dagster `up`에서 전멸했다 — 컨테이너 로그의 원문은 "final
permit fresh finalize generation is invalid". permit 실물과 레포 계약을 나란히
대조해 확정했다: receipts 블록은 이미 head 인지("root 너머에서는 봉인 digest가
서술하는 상태가 존재하지 않는다")로 고쳐져 있는데, **operation evidence 블록만
pre/post catalog를 봉인 계약과 무조건 대조**하고 있었다. head 302의 fresh 실측
(pre fc32b351/post 00800ab7)은 300 시절 봉인값(5d39c2b2/e7fbf7e7)과 다를 수밖에
없다 — 이전 green permit들(head 300)은 정확히 봉인값과 일치했다.

#1129가 receipts와 같은 원리로 정렬한다: root 너머에서는 post를 receipts의
observed catalog와 교차 결박하고 pre는 well-formed digest만 요구. 적대 리뷰
2인(opus·xhigh) 모두 approve — 반영: 사용 지점 `_require_sha256`(순서 의존 제거),
주석의 앵커를 실제(Manager의 pre==직전 post 결박 + `_verify_database`의 live
재관측)로 교정, malformed pre 음성 테스트 추가. 리뷰가 남긴 후속 과제: head별
destination catalog 재컷으로 봉인 대조 복원, Manager 쪽 동일 교차 검사 대칭.

단위 fixture가 아티팩트 값으로 evidence를 만들어 이 결함을 못 보던 것도 고쳤다
— beyond-root 현실(봉인값 ≠ 실측)을 그대로 모델링하는 테스트가 이제 원본 코드를
정확히 1건 실패시킨다.

## 2026-08-31 — M05 activation rebuild 실패의 근본원인: wheel에 안 실린 package-data

Manager main(5f70770d)을 trusted release로 설치하고 pinset을 원자 회전(Map 13407ba9
· PinVi e0750505)한 뒤 `run-pinned-rebuild-once`를 돌렸더니 `application_builder`
단계 prejournal 실패(수리된 phase-scoped 기계 덕에 pinset은 안 탔다). envelope은
stage만 말하므로, sealed builder를 수동 재현(digitie 권한, 로그 캡처)해 원문을 얻었다:
**"candidate image installed runtime tree가 sealed Git archive와 다르다"** — expected
/observed manifest를 직접 재생성·diff하니 정확히 한 줄, `providers/_provider_surface.json`.

689aecce(Protocol 결박 게이트)가 이 JSON을 `src/kortravelmap/providers/`에 추가했지만
`[tool.setuptools.package-data]`에 등록하지 않아 wheel에서 빠졌다. sealed 게이트는
소스 트리 **전 파일**을 기대하고 이미지에선 `.py`/`.json`/`py.typed`만 관측하므로,
이 클래스(미선언 package-data / 비가시 확장자 / 데이터 전용 디렉터리)는 PR CI 전부
green인 채 Manager rebuild에서만 터진다 — "오랜 기간 진전 없음"을 만들던 late-failure
패턴 그 자체다. #1128이 package-data 한 줄 + 정적 lint 3종
(`tests/lint/test_sealed_runtime_tree_ship.py`)으로 클래스 전체를 PR 시점으로 끌어온다.
negative case 실측: 수정 전 pyproject로 되돌리면 정확히 그 lint 1건만 실패한다.

## 2026-08-31 — 적대 리뷰 2인(opus·xhigh)의 16건 실측 발견과 수리

두 리뷰어가 전부 **실행으로** 검증했다(n150 실 DB probe, 뮤테이션 주입, TestClient).
CONFIRMED HIGH 2건이 특히 무거웠다.

- **F1 부팅 실패**: 302의 recorder EXECUTE grant가 ADR-090 preflight의 exact-set을
  깨서 head=302 DB에서 API가 기동 불가였다(compose는 preflight 강제). 격리 live
  green이 이 게이트를 통과한 증거가 아니었다 — 스택이 preflight를 안 켰던 것.
  db.py 허용 목록에 recorder를 추가했다.
- **F2 kill-switch 우회**: import preview/commit이 단건 manual 생성의
  kill-switch·전용 token을 우회했다. 조건부 가드(assert_manual_feature_create_for_import)
  + BFF의 import 경로 token 부착(구성 시)으로 닫았다.
- **H1/H2/F3 재수렴**: '이미 반영된 manual 행이 든 CSV는 영구 재commit 불가(원문
  DB 메시지 409)' + '완결성 검사가 이전 batch의 item으로도 통과' — 재수렴 설계로
  해소: 같은 typed payload면 이전 child linkage를 재사용(reused=true), linkage 없는
  동일 identity/payload 변경은 원인을 말하는 오류. coverage 가드가 no-op 발급을
  중단시킨다. 통합 테스트가 재수렴(동일 child 재사용, linkage 1개 유지)을 실 DB로
  검증한다.
- **H3 recorder 교차검증**: FK 일곱을 전부 만족하는 '교차된' linkage가 통과하던
  것을 5축(행번호↔receipt·plan payload digest·decision 종류·item↔feature·부모
  actor) fail-close로 봉인.
- **H4/F4 집계**: fresh 생성이 updated로 계상되던 것을 inserted로 보정(preview와
  정합). **F5**: manual 행이 'unmatched/미연결로 남습니다'로 통보되던 것을
  valid→imported(+resolved UUID)로. **F6**: manual_children.feature_id의 legacy
  `f_*` 노출(신규 live spec이 그걸 못박고 있었다)을 UUID 정본 + reused·
  terminal_status로 교체. **F7**: import child origin의 거짓 principal — CHECK
  widen + writer CASE. **F9**: 좌표 서비스 범위(124~132/33~39.5)를 preview가 반환.
  **F10/F11**: 자기참조 단언 실질화, manual_children 라우터 계약 테스트(뮤테이션
  M2 검출). L7은 NOT VALID+VALIDATE로.
- 부수 발견: **충돌 PR은 pull_request 워크플로가 조용히 0건**이다(merge ref 생성
  불가) — #1127이 CI 침묵의 원인이었고 리베이스로 해소했다.

수리 후: mypy --strict core/api·lint-imports·ruff green, M03 통합 3/3(재수렴 포함),
격리 live acceptance 2/2(수리된 계약 — token 가드·UUID 뷰·inserted 보정 실측).

## 2026-08-31 — M03 격리 live acceptance green + 잠복 500 수리

사상 첫 manual-create live harness가 n150 격리 스택(302 head)에서 완주했다:
UI CSV 업로드 → preview(201) → commit(200, `manual_children` 확정값) → admin REST에서
생성 Feature 관측. 전제 두 가지를 실측으로 확인했다 — (1) theme/source는 retained
catalog에 선존재해야 한다(import는 catalog를 만들지 않고 preview가 422 fail-close),
(2) Idempotency-Key는 BFF가 허용 목록으로 전달한다.

acceptance가 최초로 노출한 **잠복 결함**: feature 상세 라우트가 curation item을
`AdminCurationItemView.model_validate(item, from_attributes=True)`로 직검증해
CurationItem에 없는 `command_etag`(그리고 int `row_revision`) 때문에 **curation이
달린 모든 feature 상세가 500**이었다. 기존 테스트가 전부 빈 tuple을 mock해 숨어
있었다. curations 라우터의 `_admin_item_view`(정본)로 교체하고, 실제 item을 실은
회귀 테스트를 추가했다.

## 2026-08-31 — M03 302: import 행별 manual Feature child 발급 완주 (실 DB green)

`301`이 만든 linkage 표를 실제로 채우는 쓰기 계약 셋을 `302`로 확장하고, repo·route를
결선해 통합 테스트가 실 PostGIS에서 완주했다.

- **CSV**: `manual_feature_category`(8자리) typed 열 추가 — writer가 category를
  요구하는데 item 인자에 원천이 없다. 이름은 `place_name`이 소유(비면 preview 거절).
  typed payload가 {kind, category, coord}로 확장돼 child identity에 category가 결박.
- **302 migration**: (1) writer operation 검사를 child operation까지 확장,
  (2) apply가 manual 행 item upsert를 건너뛰고(EXCLUDED.feature_id=NULL이 writer의
  feature 결박을 지우는 경로 차단) 행별 좌표(o_row_receipts)를 반환하며 manual 행의
  decision을 accepted/manual_feature_child로 기록(종전 분기면 'revoked'로 강등됐다),
  (3) linkage 전용 SECURITY DEFINER 기록기(ops, 소유권은 임시 스키마 CREATE grant로
  command owner에 이전), (4) match_basis·receipt head CHECK 확장. 프로시저 본문은
  baseline에서 기계 파생한 sidecar — diff가 수정 지점만 보이고 downgrade가 원본
  바이트로 복원된다.
- **repo/route**: 결정적 child identity(§6.2)로 lock→claim→writer→apply→linkage→
  child result를 한 SERIALIZABLE transaction에 배선. manual 행은 command 경로
  전용(가드), 부분 성공 없음. 부모 응답에 ordered `manual_children` — 요청 JSON이
  아니라 transaction 확정값에서 구성. OpenAPI 재생성.
- **검증**: 신규 통합 테스트가 child command identity·feature/origin·linkage 5축·
  decision 종류·item feature 결박 생존·child terminal result를 실 DB에서 확인.
  mypy --strict core/api green, 통합 회귀(dict 동등 단언 4곳) 반영.
## 2026-08-31 — 적대 리뷰 라운드2: 원장 게이트 3종을 파싱 정본 위에 재작성

라운드1 게이트는 각자 다른 구멍을 갖고 있었다 — 삭제 게이트는 diff 줄 정규식이라
bold/들여쓰기/fence를 못 봤고(R2-S3/S6), coverage 게이트의 covered()는 substring이라
부모 섹션의 산문 언급으로 우회됐고(R2-S2), 사이즈 게이트는 이름 열거라 그 사각지대에서
`tasks-done.md`가 374KB까지 자랐다(R2-S8).

수리: (1) `scripts/task_ledger_lint.py` — fence/HTML 주석 제외·malformed 표기
fail-closed·bold/backtick 허용 ID 추출을 가진 **파싱 단일 정본**. 게이트 전부 이걸
import한다. (2) 삭제 게이트는 diff 줄이 아니라 **base/HEAD 전체 파일의 체크박스 집합
비교**로 전환 — tasks.md 삭제는 done의 `[x]` 실질 엔트리(stub 거부, 40자), acceptance
삭제는 추가 줄의 ID 명시(삭제 근거)를 요구하고, `tasks-acceptance.md`도 감시한다(R2-S7).
push 이벤트 base는 `github.event.before` 우선(all-zero면 origin/main 폴백, R2-S11).
(3) covered()는 정확-토큰 + **list 항목 선언**만 인정(연속 들여쓰기 줄 포함) — 산문
언급·부정문은 덮임이 아니다. (4) 사이즈 게이트는 `docs/**/*.md` rglob. `tasks-done.md`는
2026-08 live + 아카이브 2샤드로 분리했다. (5) journal 훅은 당월 shard + 추가 줄>0만
기록으로 인정(R2-S10). (6) 배리어 덮임 주장은 실제 메커니즘 이름(B2↔pinned-release
OpenAPI blob SHA, B3↔pinset_sha256 equality)으로 정밀화하고(R1-S7), 귀속 부기 B4/C3의
체크박스를 해제했다(R1-S11 — `[x]`는 "기준 충족"으로 읽힌다).

검증: 뮤테이션 4종(무이관 삭제·미언급 기준 삭제·fence 은닉·malformed 표기)과 coverage
뮤테이션 3종(헤딩 제거·산문 언급·list 선언)을 실제로 주입해 전부 잡히는 것을 확인했다.

## 2026-08-31 — 정체 근본원인 감사와 채택 개선 (5-agent 워크플로우)

분석 3인(타임라인 포렌식 / 결박 전수 / 트레드밀 구조) + 적대 리뷰 2인이 진단 4건을
반박하고 완화안 4건을 기각한 뒤 남은 것만 채택했다. 정본은
`docs/reports/map-stall-root-cause-2026-08-31.md` — 기각 처방 9건도 §5에 남겨 재제안을
막는다.

**판정: 정체는 livelock이 아니라 반복 단가의 발산이다.** 한 사이클(pair 회전 + 단발
rebuild + one-shot 실행)의 산출이 terminal phase enum 1개였고, terminal 27개 중
acceptance 본문 도달은 0건 — 후보 예산 전부가 인프라 단계에서 소진됐다. 단가를 만든 세
인자: 관측 결핍(`ports: !reset` 한 줄이 4개 candidate를 태움) × 무조건 소각(phase-scoped
기계가 있는데 배선 안 됨) × 값/상태 고정(head 리터럴 17곳, 봉인 digest 3지점).

이 저장소의 채택분:

- **배리어 B1~B3 삭제**(I-3, STRENGTHENED) — 같은 문단의 실행 시점 exact-equality가
  셋을 정확히 덮는다. B4는 유지 — env/compose/role·ACL 표면은 런타임 대조가 안 덮는다.
- **동일 사건 중복 부기 접기**(I-6) — MAP-HEALTH-TRANSPORT B4·ADMISSION-TERMINAL C3를
  ACTIVATION A3로 귀속, 두 task 완료 이관. 열린 task 25 → 21.
- **원장 게이트 3종**(I-7) — 체크박스 삭제 게이트(선례: 6d671ef1 평면화 다음 날 완료
  처리), live journal(568KB)/resume(376KB) 분리 + 220KB 게이트를 live에도, archive
  shard 기입 인정.

Manager 쪽 채택분(I-1/I-2/I-4/I-5/I-8/I-9)은 Manager PR #278, PinVi 쪽(I-10)은
PinVi #505가 소유한다.
||||||| parent of 09d018d8 (docs: M03 302 완주 기록과 다음 작업(격리 live acceptance))

## 2026-08-31 — head 값 고정을 걷어내고, `301`이 왜 아직 못 올라가는지 실증했다

`T-VN-M03`의 linkage migration을 올리자 무너진 것은 테스트 스냅샷이 아니라 **배포
계약**이었다. `application_head = "300"`이 Map 6곳 + Manager 11곳에 리터럴로 박혀 있었고,
같은 값의 사본이 서로 일치한다는 것을 아무것도 강제하지 않았다.

**head를 파생값으로.** `application_schema_head()`가 migration graph에서 단일 head를
유도하고 head가 0개거나 2개 이상이면 fail-close한다. 배포 executable 넷 + `env.py` +
`api-entrypoint.sh` + `dagster-storage-migrate.py` + `run-admin-stack.sh`가 읽는다. `300`은
`BASELINE_ROOT_REVISION`으로 이름을 따로 받아 남는다 — head가 아니라 역사적 좌표다.

닫은 잠복 파손: `env.py`의 fresh 설치 facet 검증이 head가 움직이면 **조용히 꺼지던** 조건,
`api-entrypoint.sh`의 프로덕션 기동 차단, `dagster-storage-migrate.py`의 DB 판정 arm,
`run-admin-stack.sh`가 자기 DB를 거절하던 자리.

### `301`은 왜 아직 못 올라가는가 — 통합 실행이 실증했다

PostGIS 통합 6건 실패 중 둘이 결정적이다. sealed baseline(`alembic/baseline/*.sha256`)은
`300` 시점의 물리 catalog와 `alembic_version` facet을 고정하는데, **세 지점이 live DB를 그
digest와 exact 대조한다** — fresh installer `:940`, finalize `:418`, final-permit `:602`.

facet 계약 SQL은 조건에 `alembic_version = ARRAY['300']`을 담은 **단일 boolean**이라 head가
움직이면 언제나 `mismatch` 한 값만 낸다. 옮겨갈 digest가 존재하지 않는다.

내가 먼저 넣었던 우회 — facet 대조를 건너뛰고 baseline digest를 receipt에 그대로 적기 —
는 **실패를 downstream으로 미룰 뿐이었다.** finalize와 final-permit이 같은 digest와 다시
대조하므로, fresh 설치가 통과해도 프로덕션 API/Dagster 컨테이너가 기동을 거부한다. 이
결함은 내가 만들었고 적대 리뷰가 잡았다.

우회를 걷어내고 **fail-close**로 바꿨다 — head가 baseline root를 넘어서면 fresh 설치가
거부된다. `301`은 계약을 baseline 너머로 확장하는 작업과 **함께** 올라가야 하므로
`chain/301-carrier`에 분리해 보존한다.

부수 확인: `on_version_apply` 봉인이 `0236 → 300` handoff에서도 불렸다. handoff는 stamp
직후 아직 runtime GRANT를 주지 않았고 facet SQL이 그 ACL을 요구하므로 반드시 mismatch였다
— handoff는 GRANT 뒤에 스스로 같은 facet을 대조하므로 중복이자 파손이었다. 봉인을 fresh
설치로 한정했다. handoff fixture도 baseline root에서 멈추게 했다 — head까지 올린 DB는
실제 `0236` source를 재현하지 못한다.

### 게이트: "비교에 쓰였나"에서 "존재하나"로

스캔을 `docker/` 넷 → 여섯 → 82개로 넓혔는데도 적대 리뷰가 **실행으로 열네 가지**를
우회했다. `iterdir()`이 한 단계만 훑고, 확장자 `.py`/`.sh`만 열고, SQL 주석용
`startswith("--")`가 CLI 장옵션 줄을 통째로 건너뛰고, 비교 토큰 목록이 있었다.

결정적인 것은 마지막이다 — **리터럴과 비교를 다른 줄에 두는 것은 우회가 아니라 그냥
평범한 코드다.** `EXPECTED_HEAD="300"` 다음 줄에 `!= "$EXPECTED_HEAD"`를 쓰면 어느 줄에도
"리터럴 + 비교"가 없다. 그러니 "비교에 쓰였나"를 묻는 규칙은 원리적으로 완결될 수 없다.

묻는 것을 바꿨다 — **리터럴이 존재하나.** 존재만 보면 토큰 목록도, 줄 단위 문맥도,
포매터 reflow도 무관해진다. 훑는 대상도 `rglob` + 텍스트로 읽히는 모든 파일로 바꿔
Dockerfile·compose·확장자 없는 실행 스크립트가 전부 들어온다. 정당한 baseline root
언급만 파일 단위로 **사유와 함께** 면제하고, 죽은 면제·불필요한 면제도 실패다.

Manager 쪽도 같은 규칙으로 바꿨다. 거기서는 `--wait-timeout "300"` 때문에 파일 단위 면제를
뒀다가 그 면제가 곧바로 우회 통로가 됐고(상수 둘을 나란히 두면 통과), **초 단위 인자를
정수 상수로** 바꿔 면제 자체를 없앴다 — head는 revision 문자열이라 형이 다르다.

우회 형태를 하나씩 되짚어 확인했다: CLI 장옵션 · 변수 경유 · 하위 디렉터리 · Dockerfile
`ENV` · 멤버십 튜플 · 확장자 없는 스크립트 · compose · Manager 새 모듈 · `services/` 밖 —
전부 걸리고, 파생값만 쓰는 대조군은 통과한다. Manager `.env.example`에 오래 죽은 head
`0084_c6c_cancel_probe_fixtures`가 실제로 박혀 있던 것도 이때 드러나 제거했다.

## 2026-08-30 — provider 핀 전수 동기화와 Protocol 적합성 게이트

형제 `python-*-api` 18개를 핀↔HEAD로 전수 대조했다. 핀 11개를 올리고 **2개는 의도적으로
보류**했다. datagokr는 검증 실패 행을 조용히 건너뛰게 되면서 동시에 종료 조건에서
`reached_known_end` 논리곱을 지웠고, krheritage는 `page * size >= total`을 짧은 페이지
휴리스틱으로 바꿨다. 둘 다 Map이 provider `iter_all()`에 위임하는 경로라 본 저장소의
페이지네이션 보호가 닿지 않는다. 정본 수정은 provider 쪽 total 기반 종료 복구다(ADR-044).
같은 감사를 받은 krforest·visitkorea는 `has_next_page`를 써서 안전함을 확인했다.

`HeritageDetail.manager` 삭제가 mypy·import-linter·단위 테스트를 모두 green으로 통과한 채
live에서만 터진 이유를 구조로 정리했다. 45개 Protocol의 실모델 결박이 docstring 산문에만
있었고, `cast(Any, ...)` 지연 로드라 정적 검사가 보지 못하며, provider extra가 CI에 설치된
적이 없고, 단위 테스트는 자체 fake를 쓴다. 핀된 SHA에서 provider 표면을 뽑아 굳히는
manifest와 기계가 읽는 결박 선언표를 도입해 CI가 provider 설치 없이 실제 표면을 보게 했다.

Dagster 페이지네이션 6곳의 `len(items) < num_of_rows` 종료 조건을 공용 헬퍼로 옮겼다.
`total_count`가 권위이고 짧은 페이지는 그것이 없을 때만 쓰는 대체 휴리스틱이며, "짧은
페이지인데 아직 다 못 받았다"는 계속 + 경고다. krex/airkorea처럼 끝을 **예외로** 알리는
provider를 위해 `end_of_pages` 훅을 뒀다.

kma `to_grid`가 격자 범위 밖에서 `ValueError`를 던지게 됐다. 한국 영토 극단점 9개를 실제
투영해 전부 격자 안임을 확인했으므로, 격자 밖 좌표는 국외 지점이 아니라 좌표 데이터
오류다. 건너뛰지 않고 typed `KmaWeatherGridCoordinateInvalid`로 실패시킨다.

적대 리뷰 2명이 내가 만든 회귀 둘(khoa 절단, krex 종료 예외)과 내 게이트의 구멍 둘
(mcst 미검사, 상속 Protocol 멤버 미검사)을 찾았다. 전부 실증 후 반영했다.

n150 CI-parity 게이트에서 하위 패키지 테스트가 체크아웃이 아니라 venv 편집형 설치가
가리키는 `/tmp/ktm-lint`(다른 커밋)를 import해 온 것을 실측으로 확인했다. `-c pyproject.toml`로
루트 config를 강제해 고쳤다 — 그 전 판정은 테스트 대상이 아닌 트리에 대한 것이었다.

## 2026-08-29 — Manager-aware M05 execution identity 계약 착수

Map/PinVi v5 source pinset이 Manager revision을 digest에 넣지 않아, Manager의 terminal 보정을 배포해도 같은 source
pair가 이미 terminal pinset으로 막히는 구조를 확인했다. source revision이나 문서 merge로 이를 우회하면 CI·리뷰·one-shot을
불필요하게 소비하고 historical evidence의 의미도 흔들린다.

후속은 Docker Manager `ktdctl`의 v6 execution identity로 분리한다. canonical execution input은 v5 source pinset,
canonical Manager repository URL, trusted installer Manager revision이며, Manager revision은 user-controlled CLI/환경값을
받지 않는다. Map attestation은 새 execution identity를 exact 대조하고, v5 terminal evidence는 legacy audit으로 보존한다.
문서-only merge는 즉시 병합하지만 runtime tuple/pinset을 바꾸지 않는다. raw E2E forensic은 gitignored local 파일에서만 보관한다.

## 2026-08-29 — M05 Map health transport 반복 terminal의 범위 확정

`9b6eab1e…`는 Map `86d38d46…`·PinVi `3b9d6026…`·Manager `1dbd7cc…`를 Docker Manager trusted
`ktdctl`로 pair 결박하고 rebuild/public generation `match` 뒤 M04/M05 E2E를 정확히 한 번 실행한 결과다.
root registry의 terminal phase는 `map_health_transport_failed`, cleanup은 성공이었다. 같은 phase가
`41be91fe…`·`5512ce12…`·`b46743ea…`에서 반복됐으며 모두 PinVi runtime과 M04/M05 business flow 전에
종료했다. 따라서 이 네 후보는 PinVi consumer/provenance 오류가 아니라 Map API container health 이후 host
loopback publish transport 경계의 반복 failure로 분류한다.

Manager `bc99ce1…`은 이 경계의 일시 경합만 동일 candidate 안에서 1초 간격 최대 6회 흡수한다. HTTP status와
응답 계약 오류는 즉시 terminal로 유지한다. Map은 runtime source의 문서 전용 업데이트를 즉시 병합하되, CI와
전문 적대 리뷰를 다시 소비해야 하는 새 candidate는 Manager/PinVi의 실제 입력 변경 뒤에만 만든다.

## 2026-08-29 — M05 반복 후보 억제와 Docker Manager 단일 mutation 경계

사소한 문서 정정이 Map/PinVi provenance와 pinset을 재결박해 CI·전문 리뷰·one-shot을 반복 소비하지 않도록,
runtime source tuple을 candidate 형성 시 동결하는 규율을 정했다. 이후 문서 전용 PR은 즉시 병합해 동결된
candidate를 참조만 하며, 코드·Compose·계약·빌드 입력을 바꿀 때만 새 candidate를 만든다.

pinning·pair 결박·public-copy·rollback·rebuild/E2E는 Docker Manager `ktdctl` 단일 경계에서 수행한다. Manager
`03a3300…`은 모든 runtime pin mutation을 active global mutation과 직렬화하고, 검증된 launcher inherited-lock
terminal fallback 외 외부 write를 거절한다. n150 또는 terminal candidate의 원문 artifact는 건드리지 않았다.

## 2026-08-29 — M05 `3d8d63e1…` 제어면 terminal 보존

Map `0cb126fc5537f29fd3385a89faadde909649c30c`·PinVi
`9372137edf28ecaf1db2adfa9d956fe99d371e8a`·Manager
`712ae8c9acccf02c4e0015116d3c6e070ba7ca71`·pinset
`3d8d63e18dc61c34dc19b465d0b969799ba5d14f0701a19d7dd865232db6fb5b`은 clean trusted release,
root 원자 `ktdctl pin rotate-pair`, 공개 registry·generation `pending_rebuild` gate 뒤 새 root-owned
pinned rebuild를 정확히 한 번 시작했다. 원격 호출의 즉시 종료 상태로 완료를 판정하지 않고, raw leaf를
열지 않은 채 root-global mutation lock 해제 후 공개 `pin verify`를 확인했을 때 generation은 `match`였다.

다만 lock 보유 중 이미 exact pair의 unconditional terminal block이 root registry에 기록돼 이 후보는
M04/M05 launcher를 실행하지 않는다. 이는 runtime 계약의 terminal phase가 아니라 제어면 완료 판정의
실패이며, 해당 pinset·source pair·Manager source·rebuild leaf를 재실행하지 않는다. 후속 후보는 반드시
lock 해제와 공개 exact-pair/generation gate를 먼저 확인한다. 외부 root `pin block`은 active global mutation에서
코드로 거절하며 trusted launcher의 inherited-lock fallback만 예외다. HTTP·container·환경·output leaf·private
receipt 원문은 열거나 보관하지 않았다.

## 2026-08-29 — M05 `7035b0b1…` terminal 보존과 admission 경계

Map `3916ebfd601d97166c55dadfec938c3eeed6bc45`·PinVi
`73870e52fe6e02d02096a2a2dc82346f09be9a3c`·Manager
`291bd161a36e580003ef99dedafd77ee5d400a7e`·pinset
`7035b0b1c62f22fa2f1b93858a0b97de60082d4698966693705f365bd66eb639`는 모든 CI와 exact-head 전문
적대 재리뷰 두 건의 GO 뒤 clean trusted Manager release, 원자 `ktdctl pin rotate-pair`, 단발 pinned
rebuild, 공개 generation `match` gate를 통과했다. 새 root-owned leaf의 n150 isolated M04/M05 launcher는
정확히 한 번 실행됐고, root registry의 exact unconditional terminal entry가 공개한 raw-free fixed phase는
`runtime_setup_admission`이다.

HTTP·container·환경·output leaf·private receipt 원문은 열거나 보관하지 않았으며, 이 pinset·source pair·
Manager source·두 one-shot leaf는 재실행하지 않는다. 이 결과는 runtime setup 전체가 아니라 Manager가 private
admission을 만들고 PinVi가 no-follow로 검증하는 경계로 다음 immutable source 보정 범위를 좁힌다. 이 문서의
merge revision을 PinVi admin·full provenance에 재결박하고, admission 경계를 raw detail 없이 검증·분류하는 새
Manager source의 CI와 exact-head 전문 적대 재리뷰 두 건이 GO일 때만 다음 pair를 만든다.

