# ADR-076: C6c manifest v4에 Map 네 runtime image provenance를 결박한다

- 상태: accepted
- 날짜: 2026-07-19
- 결정자: human, AI agent

## 컨텍스트

C6c compatible-pair manifest v3는 Map API와 PinVi API image ID·source revision만 기록했다.
그러나 C7이 실제로 검증하는 Map runtime은 API에 더해 UI, Dagster web,
Dagster daemon이다. Compose build arg나 candidate activation에서 이 세 image가 빠지면
API만 exact commit이고 나머지는 `development`나 이전 generation인 혼합 runtime이
될 수 있다. 기존 C7 attestation은 v3 pair를 exact parse하지만 manifest와 비교하는
image는 Map API·PinVi API 두 개뿐이어서 이 혼합을 증명하지 못한다.

## 결정

docker-manager compatible-pair manifest를 version 4로 clean-cut한다. top-level은
`version`, `active`, `rollback`만 허용하고, 각 pair는 다음 9필드만 허용한다.

- `map_image_id`
- `map_ui_image_id`
- `map_dagster_image_id`
- `map_dagster_daemon_image_id`
- `map_source_revision`
- `pinvi_image_id`
- `pinvi_source_revision`
- `contract_generation`
- `recorded_at`

Map C7 attestation은 active pair의 네 Map image ID를 실제 compose runtime role와 각각
exact 비교하고, 네 image의 `org.opencontainers.image.revision`이 모두
`map_source_revision`과 같은지 확인한다. host attestation document의 version 3은
별도 계약으로 유지한다.

## 근거

- compatible pair의 rollback 단위와 C7이 실제 기동하는 runtime 단위가 같아야 한다.
- OCI revision만 비교하면 같은 source의 다른 image bytes를 구분하지 못하므로
  manifest의 immutable image ID와 revision을 모두 비교해야 한다.
- 제작 단계이고 호환성이 우선이 아니므로 v3→v4 자동 보완은 stale image를
  정상 pair로 오인할 위험보다 가치가 낮다.

## 결과(긍정)

- capture·deploy·rollback·C7 attestation이 동일한 Map 4-image transaction을 사용한다.
- API만 새 generation이고 UI/Dagster가 이전 generation인 상태를 fail-close한다.
- 운영 증거가 source commit과 role별 immutable image bytes를 함께 보존한다.

## 결과(부정)

- v3 compatible-pair manifest는 새 manager·C7 runner에서 사용할 수 없다.
- Map·docker-manager를 동일한 production cutover 단위로 배포해야 한다.

## 후속

- **완료(2026-07-26~27)**: docker-manager PR #61과 Map issue #777 구현을 병합하고,
  producer/consumer blocker가 모두 합류한 main exact commit으로 v4 capture와 n150 C7
  destructive live E2E를 통과했다.
- 후속 pair도 root-owned v4 manifest snapshot, Map 네 runtime image ID·OCI revision,
  C7 destructive live E2E를 같은 증거 단위로 검증한다. 중간 commit은 production에
  활성화하지 않는다.
