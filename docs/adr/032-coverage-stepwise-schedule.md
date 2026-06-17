# ADR-032: Coverage 단계적 상향 일정 (Sprint 1 → Sprint 5)

- **상태**: accepted (T-014 Sprint 1 진입과 동시 확정, 2026-05-25)
- **날짜**: 2026-05-25
- **결정자**: claude 제안 + 사용자 결정 (2026-05-29 승인 확정)
- **컨텍스트**: `docs/test-strategy.md §2`에 최종 coverage 목표(core 90% /
  infra 80% / providers 70% / client 80% / api 70% / dto 100% / 전체 80%
  branch)가 박혀 있고 "단계적으로 상향"이라고만 표기. 실제 schedule이 박혀
  있지 않으면 매 PR마다 "이번엔 얼마?" 협상 → CI fail 빈도와 PR 사이클 시간
  늘어남.

- **결정 (Sprint별 `fail_under` schedule)**:

  | Sprint | 전체 (branch) | `core/` | `providers/` | `infra/client/api/` | 비고 |
  |--------|---------------|---------|--------------|---------------------|------|
  | Sprint 1 (scaffolding) | 50% | 60% | 50% | 50% | 코드 자체가 적음 — bar 형식적 |
  | Sprint 2 (core + 첫 provider 4건) | 65% | 75% | 55% | 60% | core 우선 |
  | Sprint 3 (provider 절반 + infra) | 75% | 85% | 65% | 70% | provider 확장 |
  | Sprint 4 (integrity + edge cases) | **80%** | **90%** | **70%** | **80%** | 목표치 도달 |
  | Sprint 5 (operational entry) | 유지 + 회귀 방지 | 유지 | 유지 | 유지 | 신규 코드만 incremental check |

  - `pyproject.toml`의 `[tool.coverage.report] fail_under`를 Sprint별 PR로
    상향 (한 줄 변경 + journal 엔트리).
  - 단계 상향 PR은 항상 **coverage gap 해소 PR과 묶음** — gap을 먼저 채운
    후 bar를 올린다 (반대 순서는 PR이 red로 시작).
  - `dto/` 100% branch는 **Sprint 2부터 항상 강제** (Pydantic validator는
    line 수 적고 critical).

- **근거**:
  - **초기 강제는 prototype iteration 방해**: 첫 PR이 80% 강제면 5줄 추가에
    mock 30줄 — 의미 없는 snapshot 남발.
  - **마지막 spurt는 실효성 없음**: 마지막 Sprint에 몰아 채우면 happy path
    snapshot만 늘고 edge case 누락.
  - **bar가 박혀 있으면 협상 0회**: 매 PR이 "이번 sprint의 bar를 넘었나"만
    확인.
  - **dto는 예외**: line이 적고 validator branch가 곧 비즈니스 룰 — 처음부터
    100% 강제가 합리적.

- **결과 (긍정)**:
  - 단계별 quality gate가 명시적 → PR review 협상 비용 0.
  - Sprint 4에 목표 도달 → Sprint 5는 운영 진입 + 회귀 방지에 집중 가능.
  - 단계 상향 PR이 항상 gap 해소 PR과 묶이므로 red main 0회.

- **결과 (부정)**:
  - Sprint 일정이 변동되면 schedule도 변동 — 본 ADR을 update하는 부담.
  - Sprint 1의 50% bar는 형식적이라 "왜 있는가" 비판 가능 → 본 ADR이 "초기
    bar는 형식이지만 단계 상향의 anchor 역할"이라고 명기.

- **후속**:
  - `docs/test-strategy.md §2`에 본 ADR 링크 + Sprint별 표 그대로 옮김.
  - 코드 작성 단계 진입 결정(T-014) PR에 본 ADR을 묶어 `proposed` →
    `accepted` 전환 + Sprint 일정 확정.
  - 단계 상향 PR template: "Sprint N coverage bar 상향 + gap 해소".
