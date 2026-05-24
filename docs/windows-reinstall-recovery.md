# windows-reinstall-recovery.md — Windows 재설치 / WSL 초기화 / 새 PC 인수

`python-kraddr-geo`의 동명 문서 패턴을 본 저장소에 맞춰 수정한 버전이다. Windows
재설치, WSL distro export/import, 새 PC로 환경 이전, Codex/Claude 새 세션이
인수받는 시나리오를 다룬다.

## 1. 영속 상태 우선순위

가장 안전한 데이터부터:

1. **Git commit + GitHub PR branch** — push가 끝났으면 가장 안전.
2. **GitHub PR 설명/코멘트** — handoff 노트 공유.
3. **`docs/resume.md`, `docs/journal.md`** — git에 함께 push되어 있어야 함.
4. **로컬 백업의 `data/`, `.env`, provider API 키** — NTFS 또는 외장.
5. **Codex/Claude 로컬 설정·세션 캐시** — 가장 휘발성.

## 2. Git에 안 들어가는 자료 (백업 대상)

- 원천 데이터 (NTFS `data/`):
  - MOIS localdata zip / SQLite
  - 국가유산청 GIS SHP/SHX/DBF
  - 산림청 SHP
  - 표준데이터 캐시
  - kraddr-geo의 도로명주소 전자지도 PDF/ZIP
- `.env` 파일 (권한 600, 절대 git X)
- systemd `EnvironmentFile` (운영 노드)
- provider API 키:
  - `KMA_API_KEY`
  - `VISITKOREA_SERVICE_KEY`
  - `KRHERITAGE_API_KEY`
  - `OPINET_API_KEY`
  - `DATAGOKR_API_KEY` (+ `DATA_GO_KR_SERVICE_KEY`, `PUBLIC_DATA_SERVICE_KEY`, `SERVICE_KEY`)
  - `KAKAO_LOCAL_REST_API_KEY`, `NAVER_SEARCH_CLIENT_*`, `GOOGLE_PLACES_API_KEY`
- 객체 저장소 자격 (`KRTOUR_MAP_OBJECT_STORE_*`)
- Docker volume dump (`pgdata`, `miniodata`) — 의미 있는 상태일 때만:
  ```bash
  docker run --rm -v krtour-pgdata:/data -v $PWD/backup:/backup alpine \
    tar czf /backup/pgdata-$(date +%F).tar.gz -C /data .
  ```
- WSL distro export:
  ```powershell
  wsl --export Ubuntu D:\backup\wsl-ubuntu-2026-05-25.tar
  # 복원: wsl --import Ubuntu D:\wsl\ubuntu D:\backup\wsl-ubuntu-2026-05-25.tar
  ```

## 3. 재설치 후 새 세션이 읽을 문서 순서

1. `AGENTS.md` — 지시 우선순위
2. `README.md` — 정체성
3. `SKILL.md` — DO NOT
4. `docs/resume.md` — 다음 한 작업
5. `docs/journal.md` 최신 3건
6. 관련 ADR
7. PR description / 코멘트 (handoff 노트)

5분 안에 위를 훑으면 직전 컨텍스트 80%는 복구된다.

## 4. PR 코멘트 handoff 표준 포맷

다음 포맷으로 PR에 핸드오프 노트를 남긴다 (사람/에이전트 인수인계 모두 동일):

```markdown
## 재설치/세션 재개용 handoff

- **브랜치**: `feature/T-005-features-repo`
- **마지막 커밋**: `08205ab` (Preserve v1 work)
- **현재 상태**: ADR-009 ~ ADR-013 추가, docs/data-model.md 작성 완료.
  코드 작성 단계 진입 전 마지막 도큐먼트 검토 중.
- **검증**:
  - `git diff --check`
  - `python -m compileall src tests`  (코드 단계 진입 후)
  - `pytest tests/unit -q`             (코드 단계 진입 후)
- **다음 명령**:
  - `PLAN_ONLY=1 bash scripts/check_indexes.sh` (사용자 검토 대기)
  - 사용자 승인 후 `alembic upgrade head`
- **금지선**:
  - 운영 DB에 직접 ALTER 금지 — Alembic migration 필수
  - data/ 디렉토리에 새 파일 commit 금지
- **참고 문서**:
  - `docs/data-model.md` §11 ID 생성 규약
  - `docs/decisions.md` ADR-009 ~ ADR-013
  - `docs/test-strategy.md` §4 통합 테스트
```

## 5. 위험한 적재 스크립트 — `PLAN_ONLY=1` 패턴

운영 데이터 적재 스크립트는 처음부터 `PLAN_ONLY=1` preflight 모드를 지원한다.
(kraddr-geo `scripts/fullload_test.sh` 패턴 미러)

```bash
#!/usr/bin/env bash
# scripts/load_provider_fixtures.sh — 예시 골격 (코드 작성 단계에서 활성화)
set -euo pipefail

PLAN_ONLY="${PLAN_ONLY:-0}"

echo "[1/5] preflight: 환경변수 확인"
test -n "${KRTOUR_MAP_PG_DSN:-}" || { echo "missing KRTOUR_MAP_PG_DSN"; exit 1; }
test -n "${KMA_API_KEY:-}" || { echo "missing KMA_API_KEY"; exit 1; }
# ...

echo "[2/5] preflight: DB 접근 확인"
psql "${KRTOUR_MAP_PG_DSN}" -c '\l' >/dev/null

echo "[3/5] preflight: 디스크 공간 확인"
df -h /var/lib/postgresql/data

if [ "$PLAN_ONLY" = "1" ]; then
  echo "PLAN_ONLY=1 → 실제 적재 생략, 종료"
  exit 0
fi

echo "[4/5] 적재 실행"
python -m krtour.map.cli import enqueue --kind visitkorea_festival_full_scan

echo "[5/5] 검증"
python -m krtour.map.cli healthz
```

새 세션이 인수받았을 때는 항상 `PLAN_ONLY=1` 먼저 실행해서 환경 점검.

## 6. 운영 노드 (Odroid) 복구

SPEC V8 v8_0 영역. 본 라이브러리는 운영 노드를 직접 관리하지 않지만, 다음 절차로
라이브러리가 동작하는지만 확인:

```bash
ssh odroid
cd /opt/tripmate
docker compose ps                    # postgres, rustfs, api, dagster 모두 healthy?
docker compose logs --tail=100 api  # 라이브러리 import 에러 없음?
docker exec -it tripmate-postgres psql -U tripmate -d tripmate \
  -c "SELECT count(*) FROM feature.features"
```

## 7. 사용자 확인이 필요한 시점

다음은 항상 사용자 확인이 필요:

- 운영 DB에 ALTER / DROP / TRUNCATE
- 운영 객체 저장소에 DELETE / replace
- provider API에 대량 호출 (분당 100건 이상)
- 운영 노드에 새 컨테이너 배포
- `.env` / API 키 회전
- main branch force-push

`AskUserQuestion` 또는 PR comment로 명시적 확인.

## 8. 데이터 보존 정책 점검 (인수 시)

ADR-017의 보관 정책이 cron/Dagster purge job으로 동작하는지 확인:

```sql
-- weather_values: 30일 이상 누적된 row가 있는가?
SELECT count(*), min(valid_at), max(valid_at)
FROM feature.feature_weather_values WHERE valid_at < now() - interval '30 days';

-- notice: 1년 이상 만료된 row가 있는가?
SELECT count(*) FROM feature.feature_notice_details d
JOIN feature.features f USING (feature_id)
WHERE f.kind='notice' AND d.valid_end_time < now() - interval '1 year';
```

count가 0이 아니면 purge job이 멈춰 있을 가능성 — TripMate Dagster asset 점검.

## 9. 새 PC로 이전 체크리스트

- [ ] WSL2 + Ubuntu 24.04 설치
- [ ] `.wslconfig` 적용
- [ ] Docker Desktop + WSL2 backend
- [ ] git clone + `.env` 복원 (외장 백업에서)
- [ ] PostGIS 컨테이너 + Alembic upgrade
- [ ] `pytest tests/unit -q` 통과
- [ ] `pytest tests/integration -q` 통과
- [ ] `lint-imports` 통과
- [ ] (선택) provider API 키로 fixture replay 통과

## 10. 핵심 메시지

영속 상태는 git이 가장 안전하고 그 다음이 NTFS, 마지막이 WSL ext4다.
**ext4가 손상되어도 코드는 git, 데이터는 NTFS에서 복구된다**.

작업을 중단할 때는 항상:
1. `git push`
2. `docs/journal.md` 엔트리
3. `docs/resume.md` "다음 한 작업" 갱신
4. (필요 시) PR comment에 handoff 노트

이 4단계만 지키면 새 세션이 어떤 PC에서든 5분 안에 이어받는다.
