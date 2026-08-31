# journal.md — 작업 일지 (역시간순)

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

## 2026-08-28 — M05 `82850711…` terminal 보존과 runtime setup 진단

Map `35a433173dbd42c096ef08adceb1ae3c142444b4`·PinVi
`fed16a5c0f6e78ee32306b3733a7dc1c8a5641f9`·Manager
`eed1920186b5cb61182a955a6281e49230b80a84`·pinset
`8285071126a58e4807a035753261b0d1f0f4e713fa5934e9d1efa7cbf16f3af9`는 필수 CI와 exact-head
전문 적대 재리뷰 두 건의 GO 뒤 trusted `ktdctl pin rotate-pair`로 결박했다. 새 source의 단발
`run-pinned-rebuild-once`와 registry/public generation `match` gate를 통과한 뒤, 새 root-owned
leaf의 n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. exact unconditional terminal entry의
공개 고정 phase는 `runtime_setup`이다.

따라서 pair rotation·source materialization·Map/PinVi HTTP 계약 이전의 isolated runtime 준비 경계가
후속 Docker Manager 보정 범위다. HTTP·container·환경·output leaf·private receipt 원문은 열거나
보관하지 않았고, 이 pinset·source pair·Manager source·output leaf는 재실행하지 않는다. 후속 Manager는
setup 내부의 안전한 세부 경계만 공개 phase로 분리하고 raw exception은 기록하지 않는다. 이 문서의 merge
revision을 PinVi `admin`·`full` provenance에 다시 결박한 새 pair만 다음 one-shot 후보가 될 수 있다.

## 2026-08-28 — M05 `5592a1d4…` terminal 보존과 phase 수렴 보정

Map `757623973c2e6c082b78332fa25c278ef94f9bab`·PinVi
`358f607a039ffab2dabaadc2eddfc19a7e126f5c`·Manager
`a4d60d16650926c0ac5e5b9a3703c14797259ab4`·pinset
`5592a1d4d98d6757b6a5390a7283b64dc1302abb93ab2dc3b58ef1aed84066c0`는 모든 CI와
전문 적대 재리뷰 두 건의 GO 뒤 trusted `ktdctl pin rotate-pair`로 결박했다. 새 source의
`run-pinned-rebuild-once`와 registry/public generation `match` gate를 통과한 뒤, 새 root-owned
leaf의 n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 terminal이었고 root
registry의 exact unconditional entry는 원문 없이 고정 phase `driver_contract_failed`만 공개한다.

HTTP·container·환경·output leaf 원문은 열지 않았으며, 이 pinset·source pair·Manager source·output
leaf는 재실행하지 않는다. 후속 Manager는 unexpected ordinary exception을 무조건 generic phase로
덮어쓰지 않고, 이미 추적 중인 allowlist phase로만 수렴시켜 raw detail 없이 다음 immutable candidate의
수정 범위를 좁힌다. 이 문서의 merge revision은 PinVi `admin`·`full` provenance에 다시 결박한다.

## 2026-08-28 — M05 `5ad3b08c…` terminal 보존과 안전 phase 진단

Map `053904cebdb004ef1376c0c4cf0255efb02e5ba3`·PinVi
`1b29bfea86af92ad8fd946b967fe6cce331c797f`·Manager
`8f41a9bd797440bc867462da70be0d2dddf085f7`·pinset
`5ad3b08c762db115efe113f2254bea415e674d09677c47e28ba6c197b37bafe0`는 trusted `ktdctl
pin rotate-pair`, `run-pinned-rebuild-once`, registry/public generation `match` gate 뒤 n150 isolated
M04/M05 launcher를 정확히 한 번 실행해 root registry의 exact unconditional terminal entry로 차단됐다.
HTTP·container·환경·output leaf 원문은 열지 않았고 해당 source pair·Manager source·output leaf는 재실행하지
않는다.

후속 Manager `a4d60d1…`은 terminal registry의 공개 reason에 raw detail을 쓰지 않고 allowlist fixed phase만
남긴다. 이 Map 기록 revision을 새 PinVi `admin`·`full` provenance와 함께 다시 결박하고, Manager·PinVi CI와
exact-head 전문 적대 리뷰 두 건이 GO인 fresh pair만 다음 one-shot 실행권을 가진다.

## 2026-08-28 — M05 Manager isolated admission 계약 명시

PinVi의 isolated Compose 경로는 trusted Docker Manager `ktdctl`가 transaction·pinset·Manager/Map/PinVi
revision에 exact 결박해 private `0600`으로 발급한 admission receipt를 no-follow 검증할 때만
열리도록 정렬했다. 호출자 환경변수 marker, 수동 Compose, 임의 receipt는 실행 권한이 아니며
legacy marker는 거절한다. receipt 발급·주입은 Manager #256, verifier와 실행 gate는 PinVi #500의
paired 변경이고, 본 문서는 Map 소비자 계약을 같은 규율로 갱신한다. 이 문서 변경은 새 pinset이나
n150 one-shot을 만들지 않는다.

## 2026-08-28 — M05 Docker Manager 공개 generation 계약 정렬

M05의 runtime pinning·Map/PinVi pair 결박·one-shot 실행 정본을 trusted Docker Manager
`ktdctl`로 통일했다. 새 후보는 `pin rotate-pair`의 원자 회전만 사용하며, 인증된
`/api/v1/runtime-pins`와 `/api/v1/pinned-runtime/generation` 공개 사본에서 완전한 이전
committed generation 또는 registry가 Map·PinVi revision과 pinset까지 exact로 차단한 terminal
generation의 `pending_rebuild` 또는 `match`를 확인한다. 새 launcher 뒤에는
`pinset_binding=match`를 다시 요구한다. partial·malformed·phase-scoped block·drift·unknown
generation은 gate를 열지 않는다. private manifest/journal, raw launcher output, 기존 terminal
artifact는 Map이 읽지 않는다.

Map C7 attestation의 manifest v6/journal v8 exact schema·키·version은 Docker Manager 공개
generation 계약과 paired PR로만 바꾼다. 이번 동시 정렬은 journal의 3개 PinVi role extension을
포함한 16-key exact dict와 committed 상태의 catalog reset·lifecycle block 의미까지 검증한다. 이
문서 정렬 자체는 새 n150 candidate나 one-shot을 만들지 않으며, 이전 terminal pinset을 재실행하지 않는다.

## 2026-08-28 — M05 `b46743ea…` terminal 보존 후 대기

Map `6bfa47038b439845662f89524531d2ef72374c2a`·PinVi
`340717de33b3672f7da84795626c4302eddd1176`·Manager
`00c33ad79f8e43b01fe543699428701aa9733c67`·pinset
`b46743ea72d86329d9574c21cc445fb9b33fdeaad07a2704a68a91fd7a0a89fe`는 PinVi·Manager CI와 exact-head 전문 적대
리뷰 두 건의 GO, clean trusted release, atomic pair rotation과 registry/public-copy gate 뒤 n150 isolated
M04/M05 launcher를 정확히 한 번 실행했다. 권위 있는 고정 결과는
`launcher_safe_result_unavailable`이었다. HTTP 원문·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 gate는 exact unconditional terminal entry와 public copy를 확인했다. 이 candidate·source pair·Manager
source·output leaf는 절대 재실행하지 않는다. 사용자 지시에 따라 새 source·pair·pinset 생성이나 후속 n150 실행은
여기서 멈추고, 현재 terminal 기록을 보존한 채 대기한다.

## 2026-08-28 — M05 finalization receipt P1 보정

전문 data-contract 적대 재리뷰는 이전 Manager `862e8bf…`가 main `try`의 unexpected ordinary exception만
`driver_contract_failed` receipt로 수렴하고 cleanup·terminal block의 ordinary exception은 result 없이 전파할 수
있다는 P1을 확인했다. 이 문제는 terminal `41be91fe…`의 raw artifact를 열거나 재실행하지 않고 정적 경계 검토로만
발견했다.

Manager `00c33ad…`는 main·cleanup·terminal block의 ordinary exception을 `BaseException`과 구분해 원문 없이
동일 fixed terminal receipt로 수렴시킨다. cleanup 및 terminal block 오류 주입 회귀도 추가했다. 다음 후보는 이
terminal 기록을 포함한 새 Map revision과 새 PinVi provenance, 이 Manager source를 fresh atomic pinset으로 결박하고
CI·정확한 head 전문 적대 리뷰 두 건을 통과한 경우에만 만든다.

## 2026-08-28 — M05 `41be91fe…` safe launcher terminal 보존

Map `fa55316d858d95367b6a1ca6f17094408b543afe`·PinVi
`f9fce72fbc6ef73f3ec1700ef76995fdfc068e88`·Manager
`cd8b3054d9f49af88ef6f58e9319343c1453df27`·pinset
`41be91feb62feff039452e23a0d889c3b32c3e97e08c28e86ad0a1068ec8ad67`는 최신 CI와 exact-head 전문
적대 리뷰 두 건의 GO, trusted clean Manager release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 exit 1이었고 권위 있는 고정 결과는
`launcher_safe_result_unavailable`이었다. HTTP 원문·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 gate는 exact Map·PinVi·pinset의 unconditional terminal entry와 public copy를 확인했다. 이 candidate와
source pair·Manager source·output leaf는 절대 재실행하지 않는다. 다음 후보는 이 terminal 기록을 포함한 새 Map
revision, PinVi `admin`·`full` paired provenance revision, 예상하지 못한 ordinary driver exception도 원문 없이
`driver_contract_failed` fixed receipt로 남기는 Manager `00c33ad…` source를 새 atomic pinset으로 결박하고 최신
CI와 전문 적대 리뷰 두 건을 다시 통과한 경우에만 만들 수 있다.

## 2026-08-28 — M05 `5512ce12…` safe launcher terminal 보존

Map `73150672d26866122e231c085e9beefe81bfd776`·PinVi
`d8dc386dec7a800b83d457e1753b63f51470afc6`·Manager
`c31c8448fcade3ace84b0dbd0682328283ae20b9`·pinset
`5512ce12ca316e10404b9faf60eba8130815a4c7cdb3b91f4d8c80de1805cc8d`는 최신 CI와 exact-head 전문
적대 리뷰 두 건의 GO, trusted clean Manager release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 exit 1이었고 권위 있는 고정 결과는
`launcher_safe_result_unavailable`이었다. HTTP 원문·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 gate는 exact Map·PinVi·pinset의 unconditional terminal entry와 public copy를 확인했다. 따라서 이
candidate의 source pair·Manager source·output leaf는 절대 재실행하지 않는다. 다음 후보는 이 terminal 기록을
포함한 새 Map revision, 새 PinVi paired provenance, 새 Manager source를 새 atomic pinset으로 결박하고 최신 CI와
전문 적대 리뷰 두 건을 다시 통과한 경우에만 만들 수 있다.

## 2026-08-28 — M05 safe-result 부재 terminal 보존

Map `f90b7c28ee0a51cc5e2dce7a332e7feef9afe477`·PinVi
`fdff06ba746bf2de198fab075a356f88b9f228c9`·pinset
`fa28a6e7d7ee27b7bb6be6cd6c0a04ffc458cda329beca339a4ce6d038480381`은 최신 CI와 전문 적대
리뷰 두 건의 GO, trusted Manager `b45f54d5…` release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. launcher는 exit 1이었고 허용된 durable safe result는
없었다. 원문 HTTP·컨테이너 로그·환경값·output leaf는 읽거나 보관하지 않았다.

후속 `pin verify`는 exact pinset이 terminal로 차단됐음을 확인했다. 따라서 `fa28a6e7…`과
`a3f6a8f3…`·`22563762…`·`c700bd2e…`의 source pair·Manager revision·output leaf는 절대 재실행하지 않는다.
다음 후보는 이 terminal 기록을 포함한 새 Map revision과 새 PinVi provenance·새 Manager source를 새 atomic
pinset으로 결박하고, safe result 부재도 원문 없이 고정 분류·보존할 수 있을 때만 만들 수 있다.

## 2026-08-28 — M05 Map health terminal 보존

Map `bbb29d17751aa0ece0b76f3c8724a0073aa9dafc`·PinVi `663e21b4fdc2a4fc5e51a07f7a7532282aaa5423`·
pinset `c700bd2ec2d2c181e60c1dd99a13022ff8a2ce30bb19de3bb871806be80ee1ef`은 최신 CI와 전문 적대
리뷰 두 건의 GO, trusted Manager `4a6e1b0…` release, atomic pair rotation과 registry/public-copy 검증 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. durable safe result는 `map_health_http_failed`이고
cleanup은 통과했다. HTTP 원문·컨테이너 로그·환경값은 읽거나 보관하지 않았다.

driver는 이 pinset을 root registry에 조건 없이 terminal 차단했고 이후 `pin verify`가 재실행 불가를 확인했다.
`a3f6a8f3…`·`22563762…`·`c700bd2e…`의 source pair·Manager revision·output leaf는 절대 재실행하지 않는다.
다음 후보는 이 terminal 기록을 포함한 새 Map revision과 새 PinVi provenance·새 Manager source를 새 atomic
pinset으로 결박한 경우에만 만들 수 있다.

## 2026-08-28 — M05 HTTP terminal 보존과 단계 고정 분류 보정

Map `b8d108bd…`·PinVi `50c875f5…`·pinset `22563762…`은 root registry/public-copy gate를 통과한 뒤
n150 isolated M04/M05 launcher를 정확히 한 번 실행했다. durable result의 고정 분류는
`runtime_http_failed`였고 cleanup은 통과했다. raw HTTP 응답·컨테이너 로그·환경 출력은 읽지 않으며,
동일 pinset·Manager source·output leaf는 어떤 사유로도 재실행하지 않는다. root registry는 이
candidate를 같은 고정 분류로 즉시 terminal 차단했다.

Manager #253은 다음 fresh candidate에서 HTTP 실패를 호출 단계별 허용 enum으로만 기록하도록 보정한다.
새 Map 기록 revision과 PinVi `admin`·`full` paired provenance revision을 atomic `pin rotate-pair`로 함께
회전하고, CI·전문 적대 재리뷰 두 건·registry/public-copy gate가 모두 정합할 때만 새 root-owned
output leaf에서 M04/M05 live E2E를 정확히 한 번 실행한다.

## 2026-08-28 — M05 installed-wheel preflight terminal 보존과 새 pair 조건

Map `e6c08e25…`·PinVi `932fb140…`·pinset `a3f6a8f3…`의 isolated launcher는 trusted release 검증 뒤,
installed wheel의 project-root 계산이 runtime registry보다 먼저 실패해 종료했다. Docker·Compose·DB·driver
ledger 전이었지만 단회 실행권은 이미 사용됐으므로, Manager root registry는 이를 `launcher_preflight` terminal
evidence로 차단했다. 같은 pinset·Manager source·output leaf는 어떤 사유로도 재실행하지 않는다.

Manager #253은 trusted venv의 `python -I`가 `sys.prefix`로 canonical `/opt` root를 인식해 external registry와
public copy를 선택하도록 보정했고 전문 적대 재리뷰 두 건의 GO를 받았다. 다음 candidate는 이 Map 기록 revision과
PinVi 후속 provenance revision을 atomic pair rotation으로 새 pinset에 결박한 뒤, CI와 registry/public-copy gate를
다시 통과해야만 n150 M04/M05 isolated E2E를 정확히 한 번 실행할 수 있다.

## 2026-08-28 — M05 atomic pair rotation과 ledger 선행 gate 반영

Manager 전문 보안 재리뷰는 terminal seed에서 Map·PinVi를 role별로 회전하면 intermediate pinset이
one-shot ledger를 소비할 수 있음을 P1으로 확인했다. Manager PR #253 source `02cc8de…`는 terminal current의
single-role 회전을 거부하고 `pin rotate-pair`의 단일 registry replace로 두 source를 함께 회전한다.
M05 launcher도 source pair preflight 뒤에만 ledger를 claim한다.

따라서 Map `e6c08e25…`·PinVi `932fb140…`의 final `a3f6a8f3…`만 새 candidate가 된다. invalid pair,
intermediate state, static image digest 추측, 과거 terminal candidate 재실행은 여전히 허용하지 않는다.

## 2026-08-28 — M05 Docker Manager runtime pin registry 반영

Docker Manager #251은 Map·PinVi revision과 terminal pinset lifecycle의 정본을 source 상수에서
trusted release 밖 root-owned runtime pin registry로 옮겼다. Map `e6c08e25…`와 PinVi
`932fb140…`은 추적되는 seed를 편집하지 않고 host에서 `pin init` 뒤 atomic `pin rotate-pair`로
`a3f6a8f3…` candidate를 만든다. `cbb577d3…` seed는 terminal historical evidence로 보존한다.

새 candidate는 `pin verify`의 registry·공개 사본 gate, root-owned Manager provenance, PinVi pair의
source/OpenAPI/image identity가 모두 맞을 때만 한 번 실행한다. intermediate state, static image digest
추측, 과거 terminal candidate 재실행은 허용하지 않는다.

## 2026-08-28 — M05 PostGIS baseline digest source 병합

Map PR #1099는 `e6c08e2598a6f8b6fda605be271e8d384213de58`로 병합됐다. Compose `postgres`는
application `300` baseline reference의 immutable PostGIS digest를 직접 사용하고, unit gate는 reference의
repository·image ID와 Compose 값을 exact 비교한다. 전문 적대 리뷰 두 건은 P0/P1 없이 GO했고 lint,
OpenAPI, fixture replay, Python 3.11/3.12/3.13 및 PostGIS 통합 CI가 모두 통과했다.

기존 `29fbcdd…` terminal candidate는 그대로 보존하고 재실행하지 않는다. 다음 단계는 이 병합 revision의
 paired application candidate를 PinVi `admin`·`full` provenance에 결박한 뒤 Manager runtime pin registry를
 회전하는 것이다.
그 새 candidate만 n150 isolated M04/M05 live E2E를 정확히 한 번 실행할 수 있다.

## 2026-08-28 — M05 fresh baseline PostGIS image drift 원인 확정

`29fbcdd…` isolated candidate는 `baseline_reference_invalid`로 terminal 처리됐고 재실행하지 않는다.
원문 Docker log·stderr·환경값은 읽지 않았다. exact Map `9c64e862…`의
`application-reference.json`, manifest sidecar, 그리고 tracked baseline artifact를 정적으로 재검증한
결과, 이전에 기록한 `application-seed.sql` 불일치는 없었으며 모든 declared digest가 실제 bytes와
일치했다. 따라서 그 주장은 철회한다.

n150의 읽기 전용 image identity 확인에서는 Map Compose의 부동 `postgis/postgis:16-3.5-alpine`
태그가 baseline reference가 결박한 immutable PostGIS image와 달랐다. 이 baseline은 catalog receipt를
exact image identity에 결박하므로, 새 fresh DB가 다른 image에서 생성되면 receipt mismatch로
fail-close하는 것이 정상이다. Map Compose를 baseline reference digest에 직접 고정하고, committed
Map revision을 PinVi pair·Manager pinset에 재결박한 새 candidate만 실행한다.

## 2026-08-28 — `c1ad5a3e…` root-owned one-shot committed

PinVi `41a36ee6…`·Map `9c64e862…`의 `c1ad5a3e…` candidate는 exact Manager trusted release에서
root-owned structured launcher로 정확히 한 번 실행돼 `committed` 됐다. durable result는 generation
`8eedf171…`, Map application `300`, Map Dagster `29b539ebc72a`, PinVi `20260824_0101`을 확인한다.
이제 이 immutable pair에서만 isolated M04 승인·Map `rebind`·PinVi terminal receipt/ACK과 signed M05
activation attestation을 실행한다.

## 2026-08-28 — M05 provenance 재결박과 새 one-shot candidate

`030b12fc…`은 Map `9c64e862…` 및 committed API/UI image identity를 사용한 generation으로 보존하며 재실행하지
않는다. `6269138f…`은 durable journal/manifest를 남기지 못한 pre-journal 단회 시도로 보존하며 raw stderr를 읽거나
재실행하지 않는다. `53d4639f…`은 installed launcher execute bit 미보존으로 admission 이전에 끝났고 durable output·ledger·raw stderr가 없어 재시도하지 않는다. PinVi `41a36ee6…`은 M05 attestation pair와 이 실행 경계를 기록하고, Manager `c1ad5a3e…`는
그 exact PinVi/Map source와 canonical hash를 고정한다. 다음 official rebuild는 installer가 executable로 보존한 root-owned structured result launcher로
이 새 pinset에서 단 한 번이며, 성공한 committed generation만
isolated M04/M05 live mutating E2E와 signed activation attestation에 사용한다.

## 2026-08-28 — M05 scoped cleanup generation committed

Manager `519edd9…`, PinVi `69a5ac65…`, Map `9c64e862…`의 `030b12fc…` pinset은 trusted n150 release에서
official `rebuild-pinned --confirm --json`을 정확히 한 번 실행해 committed 됐다. seven-runtime generation과 Map
application `300`·Map Dagster·PinVi `20260824_0101` schema head를 고정 필드만으로 확인했다. historical candidate와
원문 stderr·DB catalog 값은 읽거나 재사용하지 않았다. 다음 단계는 같은 immutable pair의 isolated M04/M05 live
mutating E2E와 activation attestation이며, 성공 전 두 코드 PR은 병합하지 않는다.

## 2026-08-28 — M05 v2 permit scoped external membership cleanup

사용자의 완주 지시에 따라 target 밖 stale membership 철회는 Manager root-owned v2 permit의 exact
`revoke_external_memberships` scope로만 허용한다. permit은 transaction·pinset·PinVi DB identity에 결박되고, PinVi는
legacy permit 또는 다른 scope를 reset 전에 거부한다. PostGIS 회귀는 target→external·external→target 두 방향 모두에서
target membership만 제거되고 external role은 보존됨을 확인한다. Manager `519edd9…`, PinVi `69a5ac65…`, Map
`9c64e862…`의 `030b12fc…`만 다음 n150 official candidate다.

## 과거 기록 아카이브

> 현행 작업 창(2026-08-28~) 이전 기록은 아래로 분리했다. 검색은
> `rg <패턴> docs/archive/` 로 한다. 새 엔트리는 항상 이 파일 상단에 추가한다.

| 파일 | 기간 | 엔트리 | 크기 |
| --- | --- | --- | --- |
| [`journal-2026-08a.md`](archive/journal-2026-08a.md) | 2026-08-14 ~ 2026-08-27 | 124건 | 200 KB |
| [`journal-2026-08b.md`](archive/journal-2026-08b.md) | 2026-08-01 ~ 2026-08-14 | 89건 | 166 KB |
| [`journal-2026-07c.md`](archive/journal-2026-07c.md) | 2026-07-26 ~ 2026-07-31 | 60건 | 167 KB |
| [`journal-2026-07a.md`](archive/journal-2026-07a.md) | 2026-07-13 ~ 2026-07-24 | 115건  | 219 KB |
| [`journal-2026-07b.md`](archive/journal-2026-07b.md) | 2026-07-01 ~ 2026-07-12 | 28건   | 45 KB  |
| [`journal-2026-06a.md`](archive/journal-2026-06a.md) | 2026-06-10 ~ 2026-06-30 | 172건  | 219 KB |
| [`journal-2026-06b.md`](archive/journal-2026-06b.md) | 2026-06-02 ~ 2026-06-10 | 179건  | 220 KB |
| [`journal-2026-06c.md`](archive/journal-2026-06c.md) | 2026-06-01 ~ 2026-06-02 | 36건   | 53 KB  |
| [`journal-2026-05a.md`](archive/journal-2026-05a.md) | 2026-05-24 ~ 2026-05-31 | 90건   | 218 KB |
| [`journal-2026-05b.md`](archive/journal-2026-05b.md) | 2026-05-24 ~ 2026-05-24 | 3건    | 7 KB   |
