# kor-travel-map

`kor-travel-map`은 대한민국 국내 여행 데이터를 수집해 하나의 `Feature` 계약으로
정규화하고, PostgreSQL/PostGIS에 저장한 뒤 REST/OpenAPI로 제공하는 독립 데이터
프로그램이다. 내부 Python 라이브러리(`kortravelmap`)와 운영용 API/backend, admin UI를
같은 monorepo에서 관리한다.

v1 구현은 `v1` 브랜치에 보존되어 있고, main은 v2 재시작 이후의 현재 구현이다. 과거
산출물 요약은 루트의 `kor-travel-map-spec.docx`에 남아 있다.

## 현재 운영 모델

- Docker 독립 프로그램으로 실행하며 DB와 Dagster metadata DB를 PinVi와 공유하지 않는다.
- 외부 소비자는 DB나 Python package를 직접 import하지 않고 OpenAPI HTTP 계약으로 호출한다.
- 메인 패키지 `src/kortravelmap/`은 async 내부 라이브러리이며 FastAPI/Uvicorn에 의존하지 않는다.
- REST/OpenAPI backend는 `packages/kor-travel-map-api/`, admin UI는
  `packages/kor-travel-map-admin/frontend/`가 소유한다.
- provider 입력은 공공 `python-*-api` client와 형제 앱 `kor-travel-concierge` REST export를
  사용한다. provider wrapper/adapter/gateway는 새로 만들지 않는다.

식별자 전체 표는 [`AGENTS.md`](AGENTS.md) §식별자가 정본이다.

| 항목 | 값 |
|------|----|
| PyPI distribution | `kor-travel-map` |
| Python import | `import kortravelmap as ktm` 또는 `from kortravelmap import ...` |
| CLI | `ktmctl` |
| env prefix | `KOR_TRAVEL_MAP_*` |
| 기본 DB | `kor_travel_map` |
| Dagster metadata DB | `kor_travel_map_dagster` |

## 책임 범위

`kor-travel-map`이 맡는 일:

- 여행 지도 객체 `Feature` 7종: `place`, `event`, `notice`, `price`, `weather`, `route`, `area`
- 결정적 `feature_id`와 provider 원천 `SourceRecord`/`SourceLink`
- provider model을 `FeatureBundle`, `WeatherValue`, `PriceValue`, `FeatureFile`로 정규화
- PostgreSQL/PostGIS schema, Alembic migration, raw SQL repository
- RustFS/MinIO 등 S3 호환 객체 저장소에 이미지/문서 메타데이터 연결
- 독립 Dagster provider sync, feature update queue, consistency job
- 내부망 전제 admin/debug/ops REST API와 Next.js admin UI

`kor-travel-map`이 맡지 않는 일:

- PinVi 사용자, 여행계획, POI 도메인
- PinVi DB migration, PinVi DB FK, PinVi 라우터 또는 사용자 UI
- 외부 공개 인증/권한 시스템
- provider client 위 단순 전달용 wrapper, adapter, facade

경계와 cross-repo 계약은 [`docs/integration-map.md`](docs/integration-map.md)와
[`docs/architecture/architecture.md`](docs/architecture/architecture.md)를 우선한다.

## 빠른 시작

PC 개발 환경의 원칙은 간단하다. 브랜치 전환, 커밋, push 같은 순수 Git 명령은 Windows
Git으로 실행하고, 파일 조회·수정·테스트·lint·build·Docker·`gh`는 WSL의
`/mnt/f/dev/kor-travel-map-<agent>` 경로에서 실행한다. 자세한 절차는
[`docs/dev-environment.md`](docs/dev-environment.md)와
[`docs/runbooks/agent-workflow.md`](docs/runbooks/agent-workflow.md)를 본다.

```bash
# Windows PowerShell: Git 상태 확인
git.exe -C F:/dev/kor-travel-map-codex status

# WSL: Git 외 작업 기본 위치
cd /mnt/f/dev/kor-travel-map-codex
ln -sfn /mnt/f/dev/kor-travel-map/data data

# 메인 라이브러리 설치
uv venv
uv pip install -e ".[dev,geo,providers]"

# PostgreSQL + PostGIS
docker compose up -d postgres
alembic upgrade head

# REST API 별도 패키지
uv pip install -e packages/kor-travel-map-api
uvicorn kortravelmap.api.app:app --host 127.0.0.1 --port 12701
```

Admin frontend는 WSL Node/npm으로 실행한다. Windows Node/npm은 사용하지 않는다.

```bash
cd /mnt/f/dev/kor-travel-map-codex/packages/kor-travel-map-admin/frontend
which node npm              # /home/.../.nvm/... 경로여야 함
cp .env.example .env.local  # NEXT_PUBLIC_VWORLD_API_KEY 설정
npm install
npm run dev                 # http://127.0.0.1:12705
```

Playwright e2e만 Windows 호스트 브라우저에서 실행한다. 서버는 WSL에서 띄운 상태를
사용한다.

## 저장소 구조

```text
src/kortravelmap/                  메인 Python 패키지, FastAPI 의존 없음
  category/                        category model과 mapping
  dto/                             Pydantic v2 DTO
  core/                            순수 도메인 로직, ids, scoring, validation
  infra/                           SQLAlchemy mapping, raw SQL repository, storage
  providers/                       provider raw/typed model -> DTO 변환
  client.py                        AsyncKorTravelMapClient
  cli/                             ktmctl CLI

packages/kor-travel-map-api/       FastAPI REST/OpenAPI backend
packages/kor-travel-map-admin/     Next.js admin frontend
alembic/                           DB migration
sql/                               schema/helper SQL
tests/                             unit, integration, e2e, fixture replay
docs/                              architecture, ADR, runbook, ETL, task 기록
data/                              원천/대용량 데이터, git 제외
```

메인 패키지 의존 방향은 `category → dto → core → infra → geocoding → providers →
client → cli` 한 방향이며 `import-linter`가 강제한다. `kortravelmap.api`는 별도
distribution의 HTTP projection이다.

## 핵심 개발 규칙

- `main`에 직접 push하지 않는다. 모든 변경은 feature branch와 PR로 처리한다.
- `kor_travel_map` flat import나 호환 shim을 만들지 않는다. import root는 `kortravelmap` 하나다.
- provider wrapper/adapter/facade를 만들지 않고 안정된 `python-*-api` public client를 직접 쓴다.
- 공간 쿼리 술어에서 `ST_Transform`을 쓰지 않는다. 반경 검색은 meter 좌표 `coord_5179` 기준이다.
- DTO/schema/API 계약 변경은 OpenAPI export와 admin/user schema drift를 함께 확인한다.
- Markdown/RST 문서는 한국어로 작성한다. 코드 식별자, API 필드, 명령어, URL은 원문을 유지한다.

전체 DO NOT 목록은 [`SKILL.md`](SKILL.md) §4와 [`AGENTS.md`](AGENTS.md)를 본다.

## 검증

기본 게이트는 WSL에서 실행한다.

```bash
cd /mnt/f/dev/kor-travel-map-codex
.venv/bin/ruff check .
.venv/bin/mypy --strict src
.venv/bin/lint-imports
.venv/bin/python -m pytest -q
```

라우터, DTO, OpenAPI schema를 바꿨다면 다음도 확인한다.

```bash
python packages/kor-travel-map-api/scripts/export_openapi.py --profile all
python packages/kor-travel-map-api/scripts/export_openapi.py --profile all --check
```

로컬 green은 CI green을 대체하지 않는다. PR 머지는 GitHub Actions의 `ci`, `lint`,
`openapi` workflow가 모두 통과하고 review approval을 받은 뒤에만 한다.

## 문서 길찾기

처음 들어오면 아래 순서로 보면 된다.

- [`AGENTS.md`](AGENTS.md): 에이전트 지시 우선순위, 식별자, 작업 후 체크리스트
- [`SKILL.md`](SKILL.md): 저장소 작업 매뉴얼, DO NOT, 도메인 어휘
- [`docs/runbooks/`](docs/runbooks/): 표준 1-PR 흐름과 반복 실패 패턴
- [`docs/resume.md`](docs/resume.md): 현재 상태와 다음 한 작업
- [`docs/tasks.md`](docs/tasks.md): 진행/예정 백로그
- [`docs/journal.md`](docs/journal.md): 역시간순 작업 일지

설계와 계약:

- [`docs/architecture/architecture.md`](docs/architecture/architecture.md): 전체 구조와 의존 방향
- [`docs/architecture/data-model.md`](docs/architecture/data-model.md): PostgreSQL/PostGIS data model
- [`docs/architecture/rest-api.md`](docs/architecture/rest-api.md): REST API 계약
- [`docs/architecture/provider-contract.md`](docs/architecture/provider-contract.md): provider 사용 원칙과 카탈로그
- [`docs/architecture/performance.md`](docs/architecture/performance.md): 공간 쿼리, index, bulk 성능 규칙
- [`docs/test-strategy.md`](docs/test-strategy.md): 테스트 구조와 커버리지 목표
- [`docs/adr/README.md`](docs/adr/README.md): ADR 색인, 현재 ADR-001~059 accepted

운영과 배포:

- [`docs/dev-environment.md`](docs/dev-environment.md): Windows Git + WSL 실행 환경
- [`docs/deploy.md`](docs/deploy.md): Docker 운영 배포
- [`docs/runbooks/docker-app.md`](docs/runbooks/docker-app.md): Docker app runbook
- [`docs/backup-restore.md`](docs/backup-restore.md): 백업과 복원
- [`docs/codegraph-worktree.md`](docs/codegraph-worktree.md): agent worktree와 codegraph

Provider/ETL 문서는 [`docs/etl/`](docs/etl/) 아래에 provider별로 둔다. Sprint 이력은
[`docs/sprints/README.md`](docs/sprints/README.md), 패키지 이름 전환 정본은
[`docs/package-identity-rename.md`](docs/package-identity-rename.md)를 본다.

## 라이선스

GPL-3.0-or-later. 자세한 내용은 [`LICENSE`](LICENSE)를 본다.

저장소에 포함된 소스 코드와 문서에만 적용된다. provider 원천 데이터와 API 응답은
각 기관 이용약관과 저작권을 따른다.
