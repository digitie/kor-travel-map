# ADR-082: cache-target writer-drain은 Map durable control plane이 소유한다

- 상태: accepted
- 날짜: 2026-08-04
- 결정자: human, Codex

## 컨텍스트

Docker Manager의 cache-target diagnostic/cutover는 writer stop 직전 DB in-flight count와
Map Dagster run count를 한 번만 읽었다. 그 사이 Dagster schedule/sensor daemon이 새 run을
생성할 수 있어 writer fence가 안정된 경계가 아니었다. process-local `finally`의 writer
restart도 crash/new diagnostic ID 뒤의 원래 instigation 상태를 증명하며 복원하지 못한다.

기존 admin/ops schedule/cancel REST와 cache-target 4-role credential registry는 일반 운영
표면 또는 data-plane consumer contract다. 이것을 Docker Manager의 private drain에 재사용하면
권한이 확대되고 journal/recovery 증적이 분리된다.

## 결정

Map application DB `ops` schema에 durable writer-drain lease, instigation snapshot, owned run
result relation을 추가한다. Map API image의 private typed command만 이 상태를 mutate하며,
Manager는 frozen Compose one-shot runner로 그 command를 호출한다. public REST/OpenAPI와
기존 token registry에는 새 endpoint/token/scope를 추가하지 않는다.

Manager journal은 `writers_draining`과 `writers_drained` phase, opaque lease ID, secret-free
receipt SHA-256만 보존한다. `begin → attest → restore`는 owner UUID와 prior receipt digest로
idempotent하며, Map은 pause → bounded grace → one-shot terminal cancel → final zero attest를
소유한다. recovery는 Map Dagster daemon을 열기 전에 exact previous instigation state를
복원·attest한다.

## 근거

state snapshot과 terminal-cancel result는 Map의 Dagster domain에 속하고, Map DB에 durable하게
있어야 process crash·Manager journal archive·new ID가 생겨도 동일 owner를 복구할 수 있다.
Manager가 기존 Compose `stop` capability를 일반화하거나 Map의 external GraphQL을 호출하면
least privilege와 secret-redaction을 보장할 수 없다.

## 결과

긍정적으로 writer fence 이전의 producer race와 crash recovery가 명시적 상태기계가 되며,
diagnostic과 cutover가 같은 primitive를 재사용한다. intermediate development data는 보존하지
않고 재적재할 수 있다.

부정적으로 Map application DB migration, private runner, isolated fake Dagster fixture와
Manager journal/Compose orchestration 변경이 모두 필요하다. final schema backup/restore
rehearsal은 여전히 별도 필수 gate다.

## 후속

- T-VN-41D/Manager T-049F에서 schema, command, journal, isolated rehearsal을 함께 구현한다.
- final production 검증은 이 격리 task의 범위 밖이며 별도 승인 없이는 수행하지 않는다.
