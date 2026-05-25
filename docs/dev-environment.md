# 개발 환경 셋업 (WSL ext4 기준)

본 문서는 `python-krtour-map`(`krtour.map`)을 PC에서 개발할 때 필요한 시스템
의존성과 셋업 순서를 정리한다. **WSL ext4에서 작업하고 NTFS의 `data/`를 참조한다**는
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
| 코드/git/.venv | WSL ext4 — `~/dev/python-krtour-map/` |
| 데이터 (`data/`) | NTFS — `/mnt/f/dev/python-krtour-map/data/` (또는 별도 외장) |
| 산출물 (`artifacts/`) | NTFS (백업 자동 sync) |
| 디버그 산출 (`.dagster/`, 디버그 export) | ext4 (작업 후 폐기 가능) |

### 2.1 NTFS data를 ext4에 link

```bash
cd ~/dev/python-krtour-map
ln -s /mnt/f/dev/python-krtour-map/data data
```

이렇게 두면 코드는 `./data/...` 상대경로로 참조하고, 실제 파일은 NTFS에 있어
WSL distro 손상에도 보존된다.

### 2.2 ext4 → NTFS 동기 (rsync)

작업이 끝나면 코드 변경분을 NTFS에 백업한다 (Windows에서 확인용):

```bash
rsync -a --delete \
  --exclude .git --exclude .venv \
  --exclude __pycache__ --exclude .mypy_cache --exclude .pytest_cache \
  --exclude data --exclude artifacts \
  ~/dev/python-krtour-map/ \
  /mnt/f/dev/python-krtour-map/
```

`data/`는 NTFS가 원본이므로 sync에서 제외한다.

## 3. 초기 셋업 (코드 작성 단계 진입 시)

```bash
# ext4 작업 디렉토리
mkdir -p ~/dev && cd ~/dev
git clone https://github.com/digitie/python-krtour-map.git
cd python-krtour-map

# 시스템 의존성 (GeoPandas/loaders용)
sudo apt update
sudo apt install -y \
  build-essential \
  libpq-dev \
  libgdal-dev gdal-bin \
  libgeos-dev libproj-dev libspatialindex-dev \
  python3-dev

# Python 환경 (uv 권장)
curl -LsSf https://astral.sh/uv/install.sh | sh
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

# PostgreSQL + PostGIS
docker compose up -d postgres
# 또는: docker run -d --name kr-postgis -p 5432:5432 -e POSTGRES_PASSWORD=changeme postgis/postgis:16-3.5-alpine

# Alembic upgrade (스키마 적용)
alembic upgrade head

# 단위 테스트 (DB 불필요)
pytest tests/unit -q

# 통합 테스트 (PostGIS 필요)
pytest tests/integration -q
```

## 4. PostgreSQL + PostGIS 컨테이너

### 4.1 단순 한 줄 docker

```bash
docker run -d --name krtour-postgis \
  -p 5432:5432 \
  -e POSTGRES_USER=krtour_map \
  -e POSTGRES_PASSWORD=changeme \
  -e POSTGRES_DB=krtour_map \
  -v krtour-pgdata:/var/lib/postgresql/data \
  postgis/postgis:16-3.5-alpine
```

DSN: `postgresql+asyncpg://krtour_map:changeme@localhost:5432/krtour_map`.

### 4.2 docker-compose

```yaml
# docker-compose.yml (코드 작성 단계에서 추가)
services:
  postgres:
    image: postgis/postgis:16-3.5-alpine
    environment:
      POSTGRES_USER: krtour_map
      POSTGRES_PASSWORD: changeme
      POSTGRES_DB: krtour_map
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: minio
      MINIO_ROOT_PASSWORD: minio123
    ports:
      - "9000:9000"
      - "9001:9001"
    volumes:
      - miniodata:/data
volumes:
  pgdata: {}
  miniodata: {}
```

### 4.3 운영 환경 (Odroid M1S)

SPEC V8 v8_0 참고. PostgreSQL 16 + PostGIS 3.5 도커 컨테이너로 동일하게
실행한다. 튜닝 임계값은 `AGENTS.md` §17 표.

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

## 7. provider 라이브러리 로컬 개발

각 `python-*-api` 라이브러리는 git URL + commit sha로 핀된다. 로컬에서 동시
개발하려면:

```bash
# kraddr-geo 동시 개발 예시
cd ~/dev
git clone https://github.com/digitie/python-kraddr-geo.git
cd python-krtour-map
uv pip install -e ../python-kraddr-geo
```

`-e`는 editable install. 작업이 끝나면 commit sha로 다시 핀 (`pyproject.toml`
`providers` extra).

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

## 9. lint / type

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
