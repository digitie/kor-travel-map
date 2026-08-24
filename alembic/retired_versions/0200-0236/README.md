# `0200`~`0236` retired migration cohort

이 디렉터리는 `0200_schema_baseline`부터
`0236_tvn41s_compaction_drained`까지의 과거 active Alembic source를 감사·원인 분석용으로
보존한다. 이 파일들은 normal `alembic.ini`의 `version_locations`, active
`alembic/versions/`, final API/Dagster runtime image에 포함되지 않는다.

`300_schema_baseline`이 유일한 active root다. 이전 snapshot restore, historical migration
replay, downgrade, 이 cohort를 임시 `version_locations`에 넣는 transition은 지원하지
않는다. `0236 → 300`은 archive를 load하지 않는 exact one-shot `stamp --purge` handoff만
허용한다.

`manifest.sha256`은 cohort source의 byte-pinned inventory다. source를 수정하거나 새 file을
넣으면 normal graph와 섞지 말고 별도 감사 결정을 거쳐 manifest와 regression test를 함께
갱신해야 한다.
