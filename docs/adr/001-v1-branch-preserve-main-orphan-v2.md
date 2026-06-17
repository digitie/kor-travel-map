# ADR-001: v1은 `v1` 브랜치 보존, main은 orphan v2로 재시작

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 + Claude
- **컨텍스트**: v1은 9개월 운영하면서 provider 계약, RustFS, 디버그 UI, ETL
  helper, 광범위한 docs를 축적했지만 의존 계층/테스트 전략/성능 설계가
  ad-hoc하게 추가되어 일관성을 잃었다. v1을 그대로 발전시키기보다 SPEC V8 +
  `kor-travel-geo` 디시플린에 맞춰 처음부터 다시 설계하는 게 빠르다.
- **결정**: 현재 main의 모든 commit을 `v1` 브랜치에 보존하고, main은
  `git checkout --orphan`으로 새 히스토리를 시작한다. `kor-travel-map-spec.docx`
  (저장소 루트 약 80쪽)는 v1 산출물과 SPEC V8 정합을 담은 reference로 둔다.
- **근거**:
  - v1 코드를 완전히 폐기하지 않음 — `v1` 브랜치 + spec docx로 복구 가능.
  - main은 git graph 어수선함 없이 깨끗하게 시작.
  - 새 에이전트가 main만 봐도 v2 의도가 명확.
- **결과 (긍정)**:
  - 의존 계층, 테스트, 성능 룰을 처음부터 일관되게 박을 수 있다.
  - v1의 부분 폐기/유지 결정을 ADR로 명시적으로 박는다.
- **결과 (부정)**:
  - main `git log`로는 직전 9개월 작업이 보이지 않는다 (`v1` 브랜치 참고 필요).
  - 일부 v1 코드를 v2에 가져올 때 cherry-pick 대신 재작성이 필요.
- **후속**: v2 코드 작성 시점에 v1 산출물을 ADR-006~ 와 함께 한 번에 평가.
