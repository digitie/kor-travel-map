# 개발 환경 셋업 (Windows Git + WSL 실행 기준)

본 문서는 `python-krtour-map`(`krtour.map`)을 PC에서 개발할 때 필요한 시스템
의존성과 셋업 순서를 정리한다. **Windows NTFS worktree를 Git 원본으로 두고,
테스트/실행 시 WSL ext4 샌드박스로 복사한다**는
정책(`AGENTS.md` §"개발 환경 정책 (PC, WSL)", `SKILL.md` §"개발 환경 (PC,
WSL)", `README.md` §"개발 환경 (PC, WSL)")을 전제로 한다. 형제 라이브러리
(`python-kraddr-geo`/`python-kraddr-base`/`python-knps-api` 등)와 동일.

## 1. 권장 호스트

- Windows 11 + WSL2 Ubuntu 24.04
- WSL2 `.wslconfig` (`%UserProfile%\.wslconfig`):
  ```
  [wsl2]
  memory=12GB
  processors=8
  swap=8GB
  localhostForwarding=true
  ```
- Docker Desktop with WSL2 backend (Linux 컨테이너)

## 2. 파일 위치 정책

| 종류 | 위치 |
|------|------|
| 코드/git/.venv | NTFS — `F:\dev\python-krtour-map\` |
| 데이터 (`data/`) | NTFS — `F:\dev\python-krtour-map\data\` (또는 별도 외장) |
| 산출물 (`artifacts/`) | NTFS (백업 자동 sync) |
| 테스트 실행/샌드박스 | WSL ext4 — `~/dev/python-krtour-map/` (또는 `~/sandbox/python-krtour-map/`) |

### 2.1 테스트 시 WSL ext4 복사 정책

코드는 NTFS 드라이브(`F:\dev\python-krtour-map`)에서 형상관리와 일반 편집이
이루어진다. `git status`, 브랜치 전환, 커밋, PR 준비는 Windows Git(`git.exe`)
기준으로 수행한다. PostGIS testcontainers나 Linux native CLI가 필요한
통합/e2e 테스트 수행 시에는 소스코드를 WSL 내의 ext4 디렉토리로 복사(`rsync`)하여
실행한다.

agent별 worktree (`F:\dev\python-krtour-map-codex` / `F:\dev\python-krtour-map-claude` / `F:\dev\python-krtour-map-antigravity`)에서도 동일하게 NTFS 소스 기준으로 git 브랜치를 운영합니다.

### 2.2 NTFS → ext4 동기 (rsync)

테스트 및 빌드를 실행하기 전 NTFS에서 수정한 변경분을 WSL ext4 디렉토리에 동기화합니다:

```bash
# WSL 셸에서 실행
rsync -a --delete \
  --exclude .git --exclude .venv \
  --exclude __pycache__ --exclude .mypy_cache --exclude .pytest_cache \
  --exclude data --exclude artifacts \
  /mnt/f/dev/python-krtour-map/ \
  ~/dev/python-krtour-map/
```

`data/`와 `.git`은 NTFS가 원본(Source of Truth)이므로 sync에서 제외합니다.

### 2.3 `scripts/*.sh` 실행 셸

루트 `package.json`의 운영 스크립트(`docker:build`, `docker:up`, `docker:backup`,
`admin:stack`, `ports:stop`)는 모두 `bash scripts/*.sh`를 호출한다. 이 파일들은
`#!/usr/bin/env bash`, `source`, Bash array, `BASH_SOURCE`를 전제로 하므로
Windows PowerShell에서 `.sh` 파일을 직접 실행하지 않는다.

표준 실행 위치:

- **WSL 셸**: 권장 경로. Docker Desktop WSL2 backend, WSL Node/npm, Linux optional
  dependency와 가장 잘 맞는다.
- **Git Bash**: Windows에서 npm script만 실행해야 할 때의 보조 경로. `bash`가
  `PATH`에 있어야 하며, Docker Desktop CLI가 같은 셸에서 보여야 한다.
- **PowerShell**: Playwright e2e처럼 Windows에서 실행해야 하는 명령만 사용한다.
  Docker/admin stack 스크립트는 PowerShell에서 직접 호출하지 말고 WSL 또는 Git Bash
  셸에서 실행한다.

예:

```bash
# WSL 셸
cd /mnt/f/dev/python-krtour-map-codex
npm run docker:build
```

```powershell
# PowerShell에서 WSL 셸로 넘길 때
wsl bash -lc "cd /mnt/f/dev/python-krtour-map-codex && npm run docker:build"
```

## 3. 초기 셋업 (코드 작성 단계 진입 시)

```bash
# 1) Windows NTFS 개발 디렉토리에서 메인 repo 클론
cd F:\dev
git clone https://github.com/digitie/python-krtour-map.git
cd python-krtour-map

# 2) WSL ext4에 테스트/실행 전용 sandbox 디렉토리 확보 및 복사
wsl mkdir -p ~/dev
wsl rsync -a --delete --exclude .git --exclude .venv /mnt/f/dev/python-krtour-map/ ~/dev/python-krtour-map/

# 3) WSL 셸로 전환 후 시스템 의존성 셋업 (GeoPandas/loaders용)
sudo apt update
sudo apt install -y \
  build-essential \
  libpq-dev \
  libgdal-dev gdal-bin \
  libgeos-dev libproj-dev libspatialindex-dev \
  python3-dev

# 4) WSL 내 가상환경 셋업 (uv 권장)
curl -LsSf https://astral.sh/uv/install.sh | sh
cd ~/dev/python-krtour-map
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e ".[dev,api,geo,providers]"

# 시스템 GDAL과 Python GDAL 버전 매치
uv pip install "gdal==$(gdal-config --version)"

# .env
cp .env.example .env
$EDITOR .env

# data 링크
ln -s /mnt/f/dev/python-krtour-map/data data

# Alembic upgrade (스키마 적용 - 설정한 외부 DB에 반영)
alembic upgrade head

# 단위 테스트 (DB 불필요)
pytest tests/unit -q

# 통합 테스트 (DB 필요)
pytest tests/integration -q
```

## 4. PostgreSQL 및 RustFS 인프라 설정

python-krtour-map 에서 rustfs, postgresql 등 인프라는 python-kraddr-geo가 아니라 어딘가에서 잘 동작하는 db, bucket 에 접속하여 활용하며, 그러기 위해서는 설정을 이 프로젝트에 잘 저장해두고 써야 합니다.

## 5. 스키마 초기화 (수동)

Alembic 사용 전에 schema 부트스트랩:

```sql
CREATE SCHEMA IF NOT EXISTS feature;
CREATE SCHEMA IF NOT EXISTS provider_sync;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS x_extension;

CREATE EXTENSION IF NOT EXISTS postgis           SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS postgis_topology  SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS pg_trgm           SCHEMA x_extension;
CREATE EXTENSION IF NOT EXISTS pgcrypto          SCHEMA x_extension;

ALTER DATABASE krtour_map SET search_path = public, x_extension;
```

이 후 Alembic이 schema-aware migration을 적용한다.

## 6. IDE / 편집기

- VS Code + Remote-WSL extension 권장
- `python.defaultInterpreterPath = .venv/bin/python`
- `editor.formatOnSave = true` + ruff
- mypy strict이 IDE에 통합되어 있어야 즉시 피드백.

## 7. provider 라이브러리 로컬 개발 + 로컬 우선 조회 (ADR-044)

모든 형제 `python-*-api` provider 라이브러리 + `maplibre-vworld-js`는 본 repo의
**형제로 `~/dev/` (NTFS: `F:\dev\`) 아래 로컬 체크아웃**되어 있다:

```
~/dev/   (= F:\dev\)
├── python-krtour-map/          # 본 repo
├── python-kma-api/             # 기상청 (단기/초단기/중기/특보)
├── python-opinet-api/          # 한국석유공사 유가
├── python-krex-api/            # 한국도로공사 휴게소
├── python-datagokr-api/        # data.go.kr 표준데이터 (축제 등)
├── python-visitkorea-api/      # VisitKorea TourAPI
├── python-knps-api/            # 국립공원공단
├── python-krheritage-api/      # 국가유산청
├── python-mois-api/            # 행정안전부 인허가
├── python-airkorea-api/ python-krforest-api/ python-khoa-api/ …
├── python-kraddr-geo/  python-kraddr-base/   # 주소/지오코딩
└── maplibre-vworld-js/         # frontend VWorld 지도
```

**조회 룰 (ADR-044)**: provider client·model·codes·스펙 확인은 **로컬을 먼저**
(`Glob`/`Read` on `F:\dev\python-*-api/src/...`). GitHub 원격 fetch는 로컬에
없을 때만 fallback — GitHub 404/private는 "미존재" 근거가 아니다. **데이터
정합성(코드/필드/단위 의미)의 1차 책임은 각 provider 라이브러리** — 본 lib는
신뢰·미러하고 불일치 시 그 라이브러리 기준으로 정렬(+필요 시 upstream PR).

git URL + commit sha 핀 + 동시 개발(editable install):

```bash
# 예: opinet 동시 개발
cd ~/dev/python-krtour-map
uv pip install -e ../python-opinet-api
```

`-e`는 editable install. 작업이 끝나면 commit sha로 다시 핀 (`pyproject.toml`
`providers` extra). 로컬 체크아웃은 stale 가능 → 조회 전 `git pull` 권장.

## 8. 단위 vs 통합 테스트 분리

```bash
# 단위만 (DB 불필요, 빠름)
pytest tests/unit -q

# 통합 (testcontainers 사용 — Docker 필요)
pytest tests/integration -q

# fixture replay (외부 API 호출 없음)
pytest tests/fixtures -q

# 전체
pytest -q

# 느린 테스트만 (nightly용)
pytest -m slow -q
```

### 8.1 디버그 UI Playwright e2e — **서버는 WSL, Playwright는 Windows**

debug UI(`packages/krtour-map-admin`)의 Playwright e2e는 **하이브리드
토폴로지**로 실행한다:

| 구성요소 | 실행 위치 | 명령 |
|----------|-----------|------|
| backend (FastAPI) | **WSL ext4** | `.venv/bin/uvicorn krtour.map_admin.app:create_app --factory --port 9011` |
| frontend (Next.js) | **WSL ext4** | `npm run start` (`next start :9012`) |
| **Playwright (chromium)** | **Windows** | `cd packages\krtour-map-admin\frontend; npm run e2e` |

Frontend 실행(`npm run dev`/`npm run start`)은 WSL 고정이다. Windows에서는 frontend
서버를 띄우지 않고, e2e 검증용 Playwright만 실행한다.
실행 전 WSL 셸에서 `which node`/`which npm`이 `/home/.../.nvm/...` 같은 WSL 경로를
가리키는지 확인한다. `/mnt/c/Program Files/nodejs/...`가 나오면 Windows Node가
섞인 상태라 Linux optional native dependency(`@next/swc`, `lightningcss` 등)가
틀어질 수 있으므로 WSL nvm Node를 먼저 활성화한다.

WSL2 `localhostForwarding=true`로 Windows의 `http://127.0.0.1:9012` /
`:9011` 요청이 WSL 서버에 도달한다. `playwright.config.ts`는 `webServer`를
두지 않으므로 서버 2개는 미리 WSL에 떠 있어야 한다.
단, Windows에서 과거에 띄운 Node 서버가 `127.0.0.1:9012`을 점유하고 있으면
Playwright가 WSL 서버가 아니라 stale Windows 서버를 본다. e2e 전 Windows에서
`netstat -ano | findstr :9012` → `Get-Process -Id <PID>`로 `ProcessName`이
`wslrelay`인지 확인한다. `node`(`C:\Program Files\nodejs\node.exe`)면 해당 PID를
종료하고 WSL frontend를 다시 띄운다.

> **왜 Playwright만 Windows인가**: WSL Ubuntu에는 chromium 구동에 필요한
> system lib(`libasound.so.2` 등)가 없고 `sudo`가 비밀번호를 요구해 WSL 내
> `playwright install-deps` 자동 설치가 불가하다. Windows에는 node + chromium이
> 이미 갖춰져 있다. 따라서 **pytest(단위/통합)는 WSL, Playwright e2e는
> Windows**가 표준이다. (WSL에서 굳이 돌리려면 `sudo apt-get install -y
> libasound2t64 libnss3 libnspr4 …` 또는 `npx playwright install-deps`를 수동
> 실행해야 하나, 권장 경로는 Windows 실행.)

자세히는 `packages/krtour-map-admin/frontend/README.md` §"e2e (Playwright)"
+ `frontend/playwright.config.ts` 상단 주석.

### 8.2 디버그 UI 서버 기동 실패 시 1회 점검표

같은 명령을 여러 번 재시도하지 말고 아래 순서로 확인한다. 반복 실패 패턴과 복구법은
`docs/runbooks/agent-failure-patterns.md` §F가 정본이다.

1. WSL Node 확인:
   ```bash
   command -v node
   command -v npm
   ```
   `/mnt/c/Program Files/nodejs/...`가 나오면 Windows Node가 섞인 상태다.
   `~/.nvm/nvm.sh`를 source하고 WSL Node를 활성화한다.
2. Linux optional dependency 확인:
   ```bash
   npm install -w packages/krtour-map-admin/frontend --include=optional
   ```
3. Next lockfile 권한 에러가 있으면 `.next`를 지운다:
   ```bash
   rm -rf packages/krtour-map-admin/frontend/.next
   ```
4. `0.0.0.0` 바인드가 필요하면 hardcoded `npm run dev` script 대신 명시 실행:
   ```bash
   cd packages/krtour-map-admin/frontend
   npx next dev --port 9012 --hostname 0.0.0.0
   ```
5. 백그라운드 실행 시에는 `setsid -f bash -lc '... nvm use ... exec npx next ...'`
   형태를 사용하고, unquoted `env PATH=...$PATH`를 쓰지 않는다.
6. 성공 보고 전 검증:
   ```bash
   ss -ltnp | rg ':(9011|9012)\b'
   curl -fsS http://127.0.0.1:9011/debug/health
   curl -fsS -I http://127.0.0.1:9012/ | sed -n '1,8p'
   ```

## 9. lint / type

Sprint 5부터 local commit에는 `.pre-commit-config.yaml`을 사용한다. hook 설치는
Git metadata가 있는 NTFS worktree에서 **Windows Git/Git Bash 기준**으로 실행한다.
WSL `/mnt/f/...` 경로에서 WSL `git`으로 실행하면 worktree를 repo로 인식하지 못할 수
있고, WSL ext4 rsync sandbox는 `.git`을 제외하므로 설치 대상이 아니다.

Git Bash 또는 Windows shell에서 pre-commit CLI가 보이는 상태로 다음을 한 번 실행한다.

```bash
pre-commit install
```

hook은 staged `src/` 또는 `tests/` 계열 변경에 대해 `docs/journal.md` 갱신을 요구하고,
Python 코드 변경 시 `ruff format --check`, `mypy --strict`, `lint-imports`를 실행한다.
의도적으로 journal gate를 한 번 우회할 때만 다음처럼 명시한다.

```bash
BYPASS=1 git commit -m "..."
```

staged 파일 기준으로 hook을 수동 검증할 때는 다음을 사용한다.

```bash
pre-commit run
```

WSL에서 hook 내부 static gate만 검증할 때는 repo-local runner를 직접 호출한다.

```bash
bash scripts/run-precommit-check.sh ruff-format tests/unit/test_pre_commit_config.py
bash scripts/run-precommit-check.sh mypy
bash scripts/run-precommit-check.sh lint-imports
```

현재 main 전체는 아직 `pre-commit run --all-files`의 ruff format 기준으로 정리된 상태가
아니므로, all-files 리포맷은 별도 PR로만 진행한다. `T-202` hook은 충돌을 줄이기 위해
commit에 포함된 Python 파일만 format check한다.

개별 명령은 다음과 같다.

```bash
ruff check .                    # 코드 스타일 + 일부 오류
ruff format .                   # 포매팅
mypy --strict src/krtour/map    # 타입
lint-imports                    # 의존 계층 검증
```

위 네 가지가 모두 통과해야 PR commit 가능.

## 10. troubleshooting

### 10.1 `psycopg2` import 에러

`psycopg`(v3)와 다름. `pyproject.toml`은 `psycopg[binary,pool]>=3.2`만 사용.
v2(`psycopg2`) 의존성이 들어왔다면 제거.

### 10.2 `function st_makepoint(...) does not exist`

PostGIS extension이 `x_extension` schema에 있는데 `search_path`에 없는 경우.
DSN에 `?options=-csearch_path=public,x_extension` 추가 또는 session에서
`SET search_path` 실행.

### 10.3 testcontainers Docker 권한

Linux에서 `docker.sock` 권한 필요:
```bash
sudo usermod -aG docker $USER
newgrp docker
```

### 10.4 NTFS data 접근 느림

`/mnt/f/...`은 9p 프로토콜이라 random IO가 매우 느리다. 대용량 SHP는 NTFS에
두되, 처리 중간 cache는 ext4 `/tmp`로.

### 10.5 GeoPandas + GDAL 버전 불일치

```bash
gdal-config --version           # 시스템 GDAL
uv pip show gdal                # Python GDAL
# 두 버전이 다르면 segfault. uv pip install "gdal==$(gdal-config --version)"
```

## 11. 운영 환경 정보 (참고)

운영 환경(Odroid M1S, ARM64)에 대한 상세 임계값은 SPEC V8 v8_0이 정한다.
`AGENTS.md` §17의 표가 발췌본. 라이브러리는 운영 환경 결정을 직접 내리지 않고,
TripMate가 주입한 settings(`KRTOUR_MAP_*`)에 따라 동작한다.

## 12. 작업 흐름 요약

```
1. ~/dev/python-krtour-map에서 작업
2. 변경 → 단위 테스트 → ruff → mypy → lint-imports
3. PostGIS 컨테이너 띄워 통합 테스트
4. journal.md + resume.md 갱신
5. ADR 필요하면 추가
6. git commit
7. rsync 또는 git push (NTFS는 자동 sync 안 됨)
```
