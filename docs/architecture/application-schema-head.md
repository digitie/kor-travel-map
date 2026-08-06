# 후보 Map application schema head artifact

## 목적

T-VN-41F1D의 파괴적 DB 재생성 전에는 후보 Map API 이미지가 담은 application Alembic
graph의 정확한 단일 head를 먼저 증명해야 한다. source checkout의 SHA, 현재 작업 디렉터리,
`alembic heads`의 실행 환경, 이미 존재하는 DB revision은 이 증명의 정본이 아니다.

## 명령 계약

후보 API 이미지는 다음 읽기 전용 명령을 제공한다.

```text
ktm-application-schema head
```

성공 stdout은 정확히 한 줄의 compact JSON이다.

```json
{"schema":"kor-travel-map.application-head.v1","head":"<single-alembic-revision>"}
```

인자는 `head` 하나만 허용한다. 실패는 exit code `1`과 stderr의 다음 안정된 JSON으로
표현한다. credential, DSN, source path, Alembic traceback은 출력하지 않는다.

```json
{"schema":"kor-travel-map.application-head-error.v1","code":"<stable-code>"}
```

## 정본과 검증

`src/kortravelmap/_application_migration_graph.json`은 package data로 후보 API 이미지에
설치되는 불변 graph artifact다. `ktm-application-schema`는 Python `purelib`/`platlib`
설치 prefix 아래의 이 파일 하나만 읽는다. 따라서 cwd, bind mount, `sys.path`, 환경변수,
DB와 application/Alembic module import가 head 판정에 영향을 줄 수 없다.

artifact의 source는 `alembic/versions/*.py`의 module-top-level `revision`과
`down_revision` literal AST다. `scripts/generate_application_migration_graph.py`는 migration
module을 import·실행하지 않으며 dynamic assignment, 중복 revision, unknown parent를
fail-closed한다. 명령도 graph의 root가 하나이고 모든 revision이 root에서 도달 가능하며
terminal head가 정확히 하나일 때만 성공한다.

새 application migration을 추가할 때는 다음을 함께 실행해 artifact를 갱신·검증한다.

```text
python scripts/generate_application_migration_graph.py --write
python scripts/generate_application_migration_graph.py --check
```

unit regression은 checked-in artifact와 AST source의 동등성, cwd decoy 무시, top-level side
effect 미실행, zero/multiple/unknown/cyclic head fail-close를 고정한다.

## F1D 순서

Docker Manager는 후보 API 이미지에서 이 명령과 `ktm-dagster-storage head`, PinVi의
동등한 정적 head 명령을 모두 성공시킨 뒤에만 reset intent를 durable하게 기록하고 세
scoped DB를 재생성한다. 이 명령은 migration을 실행하거나 runtime을 시작하지 않는다.
실제 Map application migration의 소유자는 후보 API 이미지의 one-shot startup이며, Dagster
storage migration은 별도 `ktm-dagster-storage migrate` one-shot이 소유한다.
