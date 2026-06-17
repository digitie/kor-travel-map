# ADR-056: T-108 운영 배포 자동화 — N150/Odroid 병행 multi-platform build

### 상태

Accepted (2026-06-13) — pinvi `T-108` 운영 배포 자동화 항목을 kor-travel-map
독립 프로그램 운영 범위로 이식하되, 사용자 재지시에 따라 streaming replication은
하지 않는다.

### 배경

pinvi의 `T-108` 원문은 "운영 배포 자동화 (Sprint 6) — Odroid M1S + N150 16GB 양쪽.
multi-platform Docker 빌드 + 두 노드 streaming replication"이다. kor-travel-map은
ADR-045 이후 TripMate와 분리된 독립 프로그램이고, API/frontend/Dagster/Postgres/RustFS
운영 묶음을 자체적으로 검증해야 한다. 따라서 TripMate 제품 task를 그대로 실행할 수는
없다. 2026-06-13 사용자 추가 지시로 이 저장소에서는 streaming replication을 제외하고,
kor-travel-map이 직접 책임지는 multi-platform Docker build 산출물만 정본화한다.

### 결정

- Docker image는 `linux/amd64`(N150 16GB)와 `linux/arm64`(Odroid M1S)를 같은 tag로
  buildx 빌드한다. 표준 entrypoint는 `scripts/docker-buildx.sh` / `npm run
  docker:buildx`다.
- 기본 registry image 이름은 `ghcr.io/digitie/kor-travel-map-api`,
  `ghcr.io/digitie/kor-travel-map-admin`, `ghcr.io/digitie/kor-travel-map-dagster`다.
  Dagster webserver와 daemon은 같은 image를 쓴다.
- Postgres streaming replication은 하지 않는다. 자동 failover, VIP/DNS 전환,
  RustFS 다중 노드 복제도 이번 ADR 범위 밖이다.
- 운영 DB 복구성은 기존 cold backup/restore와 hot-swap restore 훈련으로 확인한다.
- RustFS 공유 인프라는 ADR-052 amendment처럼 `kor-travel-docker-manager` 정본을 따른다.
  자체 RustFS를 쓰는 배포는 cold backup/restore 훈련으로 복구성을 확인한다.

### 근거

- 같은 image tag가 amd64/arm64 manifest를 모두 포함해야 N150과 Odroid 사이에서 배포
  절차가 갈라지지 않는다.
- 이 저장소의 운영 자동화는 kor-travel-map image와 local compose 경계에 집중한다.
  DB HA는 실제 운영 토폴로지가 확정된 뒤 별도 결정으로 다루는 편이 낫다.

### 결과

- `docs/deploy.md`와 `docs/runbooks/docker-app.md`가 T-108 양 노드 image build 절차의
  정본이다.
- CI/로컬 unit test는 buildx script, env 예시, runbook 문구를 회귀 검사한다.
- 실제 운영 failover 자동화, VIP/DNS 전환, Postgres streaming replication,
  RustFS active-active/replication은 별도 후속 task가 생길 때 다룬다.
