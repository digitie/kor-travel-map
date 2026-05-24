# agent-guide.md — 에이전트 작업·문서화 가이드

이 문서는 AI 에이전트가 본 저장소에서 작업할 때의 행동 지침이다. `AGENTS.md`,
`SKILL.md`와 함께 읽는다.

## 1. 첫 5분 진입 프로토콜

새 세션이 들어오면 이 순서로 컨텍스트를 확보한다:

1. `README.md` — 정체성, 빠른 시작, 문서 지도
2. `SKILL.md` — DO NOT 룰, 도메인 어휘
3. `docs/architecture.md` 목차 — 의존 방향, 데이터 흐름
4. `docs/resume.md` — "다음 한 작업"
5. `docs/journal.md` 최신 3건 — 직전 컨텍스트
6. 관련 ADR (`docs/decisions.md`)
7. 직결 docs (provider 추가면 `docs/provider-contract.md` 등)

5~10분 안에 위 7개를 훑으면 거의 모든 작업의 정합성 판단이 가능하다.

## 2. 결정·기록 4종 (필수 유지)

| 파일 | 역할 | 갱신 시점 |
|------|------|----------|
| `docs/decisions.md` | ADR 누적 | 결정이 발생할 때마다 |
| `docs/resume.md` | 진척도 + "다음 한 작업" | 작업 마무리마다 |
| `docs/journal.md` | 작업 로그 (역시간순 append) | 작업 끝낼 때마다 |
| `docs/tasks.md` | 백로그 | 작업 추가/완료/포기 시 |

코드/문서를 바꿨는데 위 4개 중 하나도 갱신되지 않았다면 그 PR은 불완전하다.

## 3. ADR 작성 규약

번호: `ADR-NNN` 연번.

```markdown
## ADR-NNN: <결정 요약>

- 상태: proposed | accepted | superseded by ADR-XXX
- 날짜: YYYY-MM-DD
- 결정자: <agent | human> 또는 둘 모두

### 컨텍스트
무엇이 문제였고 왜 결정이 필요했는지.

### 결정
무엇을 하기로 했는지. 구체적으로.

### 근거
왜 이 결정인지. 대안과의 비교.

### 결과 (긍정)
- ...

### 결과 (부정)
- ...

### 후속
- 어떤 코드/문서/테스트가 변경되어야 하는지.
```

결정이 뒤집힐 때:
- 새 ADR을 추가하고
- 옛 ADR의 상태를 `superseded by ADR-XXX`로 표시
- **옛 ADR 본문은 지우지 않는다** — 결정 이력을 남긴다.

## 4. journal.md 엔트리 형식

역시간순으로 위에서 아래로 append. 가장 위가 가장 최근.

```markdown
## 2026-05-25 14:30 (claude)
**작업**: ADR-020 추가 (캐시 전략 결정)
**변경 파일**:
- docs/decisions.md (ADR-020 추가)
- docs/performance.md §9 갱신
- docs/resume.md 진척도 갱신
**결정**: 라이브러리 in-memory 캐시 도입하지 않음, 호출자 책임
**발견**: TripMate는 Redis를 이미 가지고 있어 외부 캐시는 자연스럽다
**다음**: 코드 작성 단계 진입 전 ADR-020 사용자 확인 받기
```

`작업/변경/결정/발견/다음` 5개 필드를 유지. 빈 필드는 생략 가능.

## 5. resume.md 형식

```markdown
# resume.md

## 현재 상태
v2 설계 단계. 코드 작성 금지. 문서/계약/ADR만.

## 다음 한 작업
ADR-006 후속 — `docs/provider-contract.md`에 wrapper 금지 예시 보강.

## 진척도
- [x] AGENTS.md / README / SKILL / CLAUDE
- [x] docs/architecture, decisions(ADR-001~019), data-model
- [x] docs/performance, test-strategy, backend-package, agent-guide
- [ ] docs/feature-model (v1에서 가져와 v2 기준으로 정리)
- [ ] docs/provider-contract (v1 + ADR-006 통합)
- [ ] docs/external-apis (provider별 키 발급/호출 정책)
- [ ] docs/dev-environment + windows-reinstall-recovery
- [ ] docs/tasks, resume, journal 초기 엔트리
- [ ] 코드 작성 단계 진입 검토

## 다음 ADR 후보
- ADR-020: 캐시 전략
- ADR-021: 디버그 API OpenAPI 정책
- ADR-022: 단위 테스트 coverage 단계적 상향 계획

## 차단 사유 / 결정 대기
- (없음)
```

## 6. tasks.md 형식

```markdown
# tasks.md — 백로그

## 진행 중
- [ ] T-001 — docs/feature-model.md 작성 (담당: claude, 시작: 2026-05-25)

## 다음 (우선순위 순)
- [ ] T-002 — docs/provider-contract.md
- [ ] T-003 — docs/external-apis.md
- [ ] T-004 — pyproject.toml provider 의존성 git URL 핀 (코드 단계)

## 완료
- [x] T-000 — git v1 보존 + main orphan 재시작 (완료: 2026-05-24)

## 보류
- [ ] T-100 — 디버그 UI Next.js 패키지 분리 (v3 후보)
```

## 7. 변경 분류별 체크리스트

### 7.1 ADR 추가만

- [ ] `docs/decisions.md`에 추가
- [ ] `docs/journal.md` 엔트리
- [ ] `docs/resume.md` "다음 한 작업" 갱신

### 7.2 docs 신규/수정

- [ ] 한국어 산문 (코드 식별자만 영문)
- [ ] 관련 ADR 링크
- [ ] `docs/journal.md` 엔트리

### 7.3 DTO 추가/변경 (코드 단계 진입 후)

- [ ] `dto/` 모듈 + Pydantic validator
- [ ] `tests/unit/test_dto_*.py` validator branch 100%
- [ ] 관련 통합 테스트
- [ ] `docs/data-model.md` 갱신 (DDL과 동기)
- [ ] DB schema 변경 시 Alembic migration
- [ ] ADR (어느 정도 큰 변경이면)
- [ ] `docs/decisions.md` + journal + resume
- [ ] OpenAPI export 재실행

### 7.4 raw SQL 추가/변경

- [ ] `infra/*_repo.py`의 `_SQL` 상수에 추가
- [ ] `tests/integration/`에 EXPLAIN 검증 테스트 1개 이상
- [ ] 인덱스 무효화 회피 확인
- [ ] `docs/performance.md` 패턴/안티패턴 갱신 (필요 시)
- [ ] journal + resume

### 7.5 provider 추가

- [ ] `providers/<name>.py` 변환 함수 (순수)
- [ ] `tests/fixtures/<name>/` 3개+ fixture
- [ ] `tests/unit/test_providers_<name>.py`
- [ ] `tests/integration/test_load_<name>.py`
- [ ] `docs/<name>-feature-etl.md` (provider별 ETL 문서 — 표준 10섹션)
- [ ] `docs/provider-contract.md`의 provider 카탈로그 추가
- [ ] `docs/external-apis.md`에 API 키 발급/호출 정책
- [ ] ADR (필요 시 — 새 dataset_key, 새 source_role 등)
- [ ] `pyproject.toml`의 provider extra에 git URL+sha 핀
- [ ] journal + resume

## 8. 코드 작성 금지 단계 (현재)

본 단계에서는 `src/`, `tests/`, `alembic/`, `scripts/`, `sql/`에 코드를 작성하지
않는다. 허용되는 변경:

- `docs/` 신규/수정
- `AGENTS.md`, `SKILL.md`, `CLAUDE.md`, `README.md`
- `.env.example` 추가
- `pyproject.toml` 의존성 placeholder
- `.gitignore`, `.gitattributes`, `LICENSE`

코드 작성 요청이 들어오면:
1. 사용자 의도 명확화 (어떤 모듈/계층/메서드인지)
2. ADR이 필요한지 확인
3. 테스트 우선 작성 (`docs/test-strategy.md` §12 우선순위)
4. 구현
5. 통합 테스트 + EXPLAIN 검증 (DB 닿는 경우)
6. journal + resume

## 9. WSL ext4 vs NTFS 작업 흐름

- `git`, `pytest`, `ruff`, `mypy`는 WSL ext4에서.
- `data/`는 NTFS에 두고 ext4에 심볼릭 링크.
- 본 가이드 작성 동안은 NTFS 직접 작업도 임시 허용 (현 작업 위치
  `F:\dev\python-krtour-map`). 단 코드 작성 단계 진입 직전에 ext4로 옮긴다.

상세 절차는 `docs/dev-environment.md`.

## 10. 도움이 안 될 때

- 사용자 요청이 모호하면 `AskUserQuestion` 사용 (최대 4지선다 + Other).
- 코드 작성 요청이 명백히 `AGENTS.md` 규칙과 충돌하면 충돌을 명시하고 대안을
  제시.
- 모르는 도메인 어휘가 나오면 `SKILL.md` §6 검색 → 없으면 사용자에게 질의.
- 같은 결정이 두 번째로 흔들리면 ADR-NNN으로 박는다.

## 11. 다른 에이전트와의 핸드오프

세션이 중단되거나 새 에이전트가 인수받을 때 `docs/journal.md`의 가장 최근
엔트리가 핸드오프 노트 역할을 한다. 다음 단서를 모두 포함:

- 무엇을 했는지
- 무엇이 남았는지
- 어떤 결정이 보류 중인지
- 어떤 파일을 가장 먼저 봐야 하는지

PR 핸드오프 표준 포맷은 `docs/windows-reinstall-recovery.md` 참고.

## 12. 마침

이 가이드는 살아 있는 문서다. 작업하면서 빠진 룰이 발견되면 ADR과 함께 추가
하거나 `agent-guide.md`를 직접 수정한다.
