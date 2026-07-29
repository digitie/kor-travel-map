# ADR-079: OpenAPI digest를 compatible-pair manifest에 핀하지 않는다

- 상태: accepted
- 날짜: 2026-07-29
- 결정자: human, AI agent
- 관계: [ADR-076](076-c6c-manifest-v4-map-runtime-provenance.md)의 manifest v4를 **유지**한다.
  #812가 제안한 v5 승격(`map_openapi_sha256` 필드 추가)을 기각한 기록이다.

## 컨텍스트

#812(T-VN-H07C)는 "배포 compatible-pair에 pinned OpenAPI SHA를 요구"하자고 제안했다.
의도는 **배포된 페어가 어떤 REST 계약을 제공하는지**를 배포 게이트에 고정하는 것이었다.

설계·구현을 실제로 완료한 뒤(양 저장소 브랜치, 테스트 baseline 동일) 적대 리뷰 2명이 두 가지를
독립적으로 실증했고, 그 결과 제안을 기각한다.

## 결정

**compatible-pair manifest는 v4를 유지한다.** `map_openapi_sha256` 필드를 추가하지 않는다.

### 근거 1 — 추가되는 탐지력이 없다

제안된 필드는 `map_source_revision`의 **순수 함수**다(그 커밋에 체크인된
`openapi-sha256.json` blob의 sha256). 그런데 C7 attestation은 이미

- `active.map_source_revision` == 운영자가 제시한 expected commit, 그리고
- **배포된 모든 이미지**의 `org.opencontainers.image.revision` 라벨 == 같은 commit

을 강제한다. OpenAPI가 바뀌려면 반드시 Map 커밋이 바뀌고, 그 커밋은 **이미 게이트되고 있다.**
어떤 소비자도 이 digest를 독립적으로 유도한 값과 비교하지 않으며(형식 검사만 한다), 따라서
"OpenAPI를 바꾼 배포가 재-capture 없이 통과한다"는 시나리오는 애초에 존재하지 않는다.

digest가 실질적 탐지력을 가지려면 **manifest와 독립적으로 유도된 값**과 대조해야 한다
(예: 빌드 시 이미지 OCI 라벨에 구워 attestation이 라벨↔manifest를 비교). 그 방안은 전 이미지
재빌드와 배포 순서 조율을 요구하는데, revision이 이미 같은 것을 보장하므로 이득이 불분명하다.

### 근거 2 — 운영 마이그레이션 비용이 실재하고 크다

manifest는 단일 버전만 허용하고 canonical 파일명에 버전이 박혀 있다. v5로 올리면 살아 있는
v4 설치에서:

1. ktdctl 업그레이드 즉시 `c6c_state_paths`가 존재하지 않는 `compatible-pair-v5.json`을 가리켜
   **rollback이 무력화**된다(프로덕션은 계속 돌지만 되돌릴 수 없다).
2. 안내대로 capture하면 v4 sibling 때문에 fail-close된다.
3. v4를 지우면(=실행 중 pair의 유일한 기록 파기) capture가 digest 계산에서 실패한다 —
   `openapi-sha256.json` blob은 최근 커밋에서 처음 생겼으므로 **기존 프로덕션 이미지의
   revision에는 존재하지 않는다**.

즉 기존 운영 pair는 v5로 capture할 수 없고, 운영자는 manifest 없는 상태에 갇힌다. 탐지력 이득이
0인 변경에 이 비용을 치를 이유가 없다.

## 후속 감사 개정 (#881)

PR #882의 “per-surface digest manifest는 소비자 freshness에 쓰인다”는 전제도 후속 감사에서
사실이 아닌 것으로 확인했다. PinVi `contract-pin-consistency`는 Map 핀 commit을 체크아웃해
user spec bytes와 admin subset을 직접 비교하며 `openapi-sha256.json`을 읽지 않는다.
소비자 없는 파생 산출물은 추가 탐지력이 없고 spec 변경마다 함께 갱신해야 하는 반복만 만들므로
Map의 digest 파일·생성·검사 코드를 제거한다. 이 개정은 compatible-pair v4 유지 결정을
바꾸지 않는다.

## 결과

- ADR-076의 manifest v4가 계속 정본이다. 배포 경로·운영 문서·런북은 변경 없다.
- 배포된 페어의 OpenAPI 계약은 `map_source_revision` + 이미지 OCI revision 라벨로 계속 결박된다.
- 소비자 측 계약 드리프트는 PinVi가 핀 commit의 spec/subset을 직접 비교하는 vendored
  스냅샷 게이트가 담당한다(H07B/H07D).
- admin/user OpenAPI를 바꾸는 task는 두 spec 재생성 + 실제 소비자 스냅샷 재-vendor를
  완료 조건으로 갖는다. 별도 digest 갱신과 compatible-pair 재-capture는 해당 없다.

## 교훈

구현을 마친 뒤에야 "이 값이 기존 게이트 대비 무엇을 더 잡는가"라는 질문이 제기됐다. 새 필드를
계약에 추가할 때는 **독립적으로 유도된 값과 대조되는지**를 먼저 확인한다 — 대조 상대가 없으면
형식 검사만 남고, 그것은 탐지력이 아니라 스키마 비용이다.
