# ADR-085 — 후보 API image의 설치 application schema head artifact

- 상태: accepted
- 날짜: 2026-08-06
- 결정자: 사용자 · Codex

## 컨텍스트

T-VN-41F1D는 세 scoped DB를 파괴적으로 재생성한다. reset 전에 candidate Map API image가
어느 application Alembic head를 담았는지 확정하지 않으면, source checkout이나 실행 cwd의
graph를 candidate image의 사실로 잘못 증명할 수 있다. `alembic heads`는 source/runtime
설정에 의존하고 migration module import도 허용하므로 이 용도의 정적 attestation 경계가
아니다.

## 결정

API image는 `ktm-application-schema head` command를 제공한다. command는 package data로 설치된
`_application_migration_graph.json`만 Python `purelib`/`platlib` prefix에서 읽고, 단일
terminal Alembic revision을 `kor-travel-map.application-head.v1` JSON으로 출력한다.

artifact는 source `alembic/versions`의 module-top-level literal assignment를 AST로만 읽어
생성한다. 새 migration PR은 generator `--check` equality를 통과해야 한다. graph가 dynamic,
중복, orphan, cycle, zero/multiple head이면 generator와 command는 migration·DB 접속·
application import 없이 fail-closed한다. 출력 head 문법은 Docker Manager와 동일한
`^[0-9a-z][0-9a-z_.-]{0,127}$`로 고정한다.

## 근거

- candidate image에 실제 설치된 application graph가 reset 전 증명의 유일한 정본이다.
- package prefix 한정 탐색은 cwd/bind mount/sys.path decoy가 attestation을 바꾸지 못하게 한다.
- AST 생성과 CI equality는 module import side effect 없이 source와 artifact drift를 막는다.
- application migration과 Dagster metadata storage migration은 서로 다른 graph이므로,
  `ktm-dagster-storage head`와 혼용하지 않는다.

## 결과

### 긍정

- Manager는 모든 후보 schema head를 DB reset 전에 machine-readable하게 attest한다.
- 후보 image가 runtime을 시작하거나 credential을 읽지 않아도 migration 세대를 판정한다.
- branched Alembic graph를 조용히 임의 head로 선택하지 않는다.

### 부정

- application migration을 추가할 때 generated artifact 갱신이 추가된다.
- 이 command는 DB의 현재 revision이나 migration 성공을 증명하지 않는다. 해당 책임은
  candidate API one-shot migration에 남는다.

## 후속

- Docker Manager F1D-C2는 이 command의 schema/head를 candidate receipt에 함께 결박한다.
- final destructive rehearsal은 command의 정적 head와 실제 migration 후 DB revision을 따로
  대조한다.
