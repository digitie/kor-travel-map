# ADR-044: 관련 라이브러리 로컬(`F:\dev\` / `~/dev/`) 우선 조회 + 데이터 정합성 책임은 각 라이브러리

- **상태**: accepted (2026-05-28)
- **날짜**: 2026-05-28
- **결정자**: 사용자

### 컨텍스트

본 라이브러리는 형제 `python-*-api` provider 라이브러리들(`python-kma-api`,
`python-opinet-api`, `python-krex-api`, `python-datagokr-api`, `python-
visitkorea-api`, `python-knps-api`, ... + `maplibre-vworld-js`)을 참조한다
(Protocol shape 확인 / API 스펙 조사 / 디버그 live loader wiring 등). 이들은
모두 같은 개발 머신의 `F:\dev\` (WSL: `~/dev/`) 아래 **로컬에 체크아웃**되어
있다.

PR#53 작업 중 실제 사고가 발생: 디버그 ETL live loader 조사에서 `python-
datagokr-api`를 **GitHub API로만 확인**(404 → private/미존재로 오판)하여
"repo 부재, wiring 불가"로 잘못 보류했다. 그러나 `F:\dev\python-datagokr-api`
는 로컬에 멀쩡히 존재했다. 같은 맥락에서 OpiNet product code 매핑(K015/C004)이
본 lib와 upstream `python-opinet-api`가 **불일치**했는데, 어느 쪽이 정답인지의
1차 근거는 provider 라이브러리(+공식 API 스펙)였다.

### 결정

**1. 관련 라이브러리는 로컬 `F:\dev\` (WSL `~/dev/`)를 먼저 탐색한다.**
- provider 라이브러리 / 형제 라이브러리의 client·model·codes·스펙을 확인할
  때는 **로컬 체크아웃을 1차 source**로 본다 (`F:\dev\python-*-api/src/...`).
- GitHub 원격 fetch(`raw.githubusercontent`/`gh api`)는 **로컬에 없을 때만**
  fallback. GitHub 404/private는 "존재하지 않음"의 근거가 **아니다** — 먼저
  로컬을 본다.
- AI 에이전트(Claude/Codex/Antigravity)도 동일 — `Glob`/`Read`로 `F:\dev\`
  로컬을 먼저 조회한 뒤에야 원격 조사로 넘어간다.

**2. 데이터 정합성(코드 매핑 / 필드 의미 / 단위 / 분류값)의 1차 책임은 각
provider 라이브러리에 있다.**
- 예: OpiNet 제품코드(B027/D047/...)의 의미·매핑은 `python-opinet-api`가
  authoritative. 본 lib는 그 정의를 **신뢰·미러**한다.
- 본 lib에서 불일치를 발견하면 **provider 라이브러리(+공식 API 스펙)를 기준**
  으로 정렬하고, 필요 시 해당 라이브러리에 **직접 PR로 수정**한다 (maplibre-
  vworld-js 양방향 PR 패턴, ADR-025 2차 보강과 동일 정신).
- 본 lib는 provider별 의미를 재정의·재해석하지 않는다 — 변환(정규화)만 한다
  (ADR-006 wrapper 금지 정신의 연장).

### 근거

- 로컬 우선 조회: 정확(실제 설치 버전과 일치) + 빠름(네트워크 X) + private repo
  접근 문제 회피. GitHub 404 오판 같은 사고 방지.
- 데이터 정합성 책임 분계: provider 라이브러리가 원천 API와 1:1로 마주하므로
  코드·의미의 single source of truth. 본 lib가 독자 매핑을 들고 있으면 drift
  (PR#53 K015/C004 사고)가 재발.

### 결과 (긍정)

- provider 스펙 조사가 정확·신속. 디버그 live loader wiring 시 로컬 client를
  근거로 faithful하게 매핑.
- 데이터 정합성 버그의 책임 소재가 명확 — provider 라이브러리에서 고치면 본
  lib + TripMate 전체가 일관.

### 결과 (부정)

- 로컬 체크아웃이 stale할 수 있음 → 정기 `git pull` 필요(개발 환경 책임).
- provider 라이브러리에 PR을 보내야 하는 경우 round-trip 비용.

### 후속

- `AGENTS.md` — 에이전트 운영 룰에 "관련 라이브러리 로컬 우선 조회" 추가.
- `CLAUDE.md` §4 — `F:\dev\` 형제 repo 목록 + 우선 조회 룰 명시.
- `docs/architecture/provider-contract.md` — 데이터 정합성 책임 = 각 라이브러리 절 추가.
- `docs/dev-environment.md` — `F:\dev\` provider 라이브러리 로컬 레이아웃.
