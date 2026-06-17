# ADR-052: RustFS 버킷은 당분간 공유하되 prefix 소유권을 명문화하고, 추후 전용 버킷으로 분리한다

### 상태

Accepted (2026-06-10, 잠정) — `docs/reports/decisions-needed-2026-06-10.md` D-01 옵션 (b)
채택, **추후 옵션 (a)(전용 버킷 분리)로 이행 예정**.

### 배경

TripMate-agent가 미디어 원본(영상/자막/전사/프레임, 무기한 보존)을 kor-travel-map 소유
버킷(`kor-travel-map`, prefix `features/`)에 직접 저장한다. kor-travel-map의 backup/restore·
수명주기·용량 책임과 충돌 소지가 있다.

### 결정

- **당분간 공유 유지**: 단일 RustFS(S3 `12101`/console `12105`)의 `kor-travel-map` 버킷을
  공유한다.
- **prefix 소유권 명문화**: TripMate-agent가 쓰는 prefix 이하 객체의 소유·수명주기·
  복구 책임은 TripMate-agent에 있다. kor-travel-map cold backup 범위에서 해당 prefix는
  **제외**한다 (T-217e에서 architecture.md·backup 문서에 반영).
- **추후 분리**: TripMate-agent 전용 버킷으로 분리한다. 분리 시점 확정(D-10,
  2026-06-10): **TripMate-agent T-066 운영 개시(kor-travel-map 실데이터 pull 시작) 전** —
  운영 데이터가 쌓이기 전이 마이그레이션 비용 최소다. 분리 작업 주체는 TripMate-agent
  (버킷 config + 객체 이전), kor-travel-map은 backup 정책 갱신만.

### 결과

- T-217e — 공유 정책을 `docs/architecture/architecture.md` rustfs 절 + backup/restore 문서에 명문화.
- TripMate-agent 측: 분리 전까지 버킷 기본값 의존 신규 기능 보류 권고 유지 (해당 repo
  TA-04).

### Amendment (2026-06-11, 사용자 지시 — T-217e 재정의)

**RustFS 인프라는 `kor-travel-docker-manager`(`F:\dev\kor-travel-docker-manager`)가 일괄 소유·관리한다.**
kor-travel-docker-manager는 TripMate 생태계 공용 기반 서비스(단일 PostGIS 컨테이너
`kor-travel-geo-postgres` :5432 + RustFS `tripmate-rustfs` S3 :12101/console :12105)를
docker-compose + Web UI로 구동/모니터링하는 관리 소프트웨어다(해당 repo README,
`docker-compose.yml` 실측).

- **이행**: 위 결정의 "kor-travel-map 측 prefix 소유권·backup 제외 명문화"와 "전용 버킷
  분리(D-10)"는 **kor-travel-docker-manager의 RustFS 운영 범위로 이관**한다 — kor-travel-map은
  버킷/prefix·키·볼륨·수명주기를 직접 운영하지 않는 **사용자**다(kor-travel-concierge도 동일).
- **kor-travel-map 잔여 책임**: 자기 데이터(offline upload 산출물 등)의 S3 키 사용과,
  cold backup이 RustFS를 포함할 때 그 범위가 kor-travel-map 소유 객체에 한정된다는 것뿐.
  rustfs 구동/포트는 kor-travel-docker-manager 정본을 따른다(고정 포트 값 자체는 ADR-047과 동일).
- 버킷 분리 시점/방식(D-10)의 후속 결정 주체도 kor-travel-docker-manager 운영으로 위임.
