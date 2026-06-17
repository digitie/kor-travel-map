# ADR-050: TripMate-agent feature export 계약을 보강한다 — 경로 중립화·정본 위치·노출 정책·철회 라이프사이클

### 상태

Accepted (2026-06-10) — ADR-049 보강, provider identity/name은 ADR-053으로 superseded.
배경은 `docs/reports/service-completeness-review-2026-06-10.md`
§4 C-4 · §5 R-3/R-4, 의사결정 `docs/reports/decisions-needed-2026-06-10.md` D-03/D-04/D-05.

### 결정

1. **경로 중립화**: export 경로는 `/api/v1/features/snapshot`·`/api/v1/features/changes`다.
   REST path에 특정 downstream 이름(`krtour`)을 넣지 않는다 (ADR-049 표기 보정).
   kor-travel-map fetcher의 현재 하드코딩 `/api/v1/features/*`는 TripMate-agent
   T-066 배포와 동시에 정렬한다 (T-217a).
2. **계약 정본 위치**: export 계약(스키마·cursor·operation)의 정본은 **TripMate-agent
   repo의 독립 계약 문서**(`docs/feature-export-api.md`류)다. 본 repo는
   `docs/architecture/rest-api.md` 계열에서 링크 + 소비 측 기대치(`{items, has_more, next_cursor}`,
   `X-API-Key`, env 키)만 요약한다. ADR-044 관행(데이터 정합성 1차 책임 = 공급 측)과 일치.
3. **노출 정책**: TripMate-agent는 **검수 통과 후보만 export**한다
   (`matched`/`user_corrected`; `needs_review`/`ignored` 제외). 검수 후 철회는
   `reject` operation으로 증분 export한다.
4. **철회 라이프사이클**: kor-travel-map은 `reject`/`tombstone` operation을 skip으로
   끝내지 않고 해당 feature의 **inactive 전환**(+사유 기록)으로 처리한다 — MOIS
   Step C(폐업→inactive)와 동형 (T-217b). 1단계로 skip 건수 WARN/admin 이슈 노출을
   선행할 수 있다.

### 근거

- path에 소비자 이름이 박히면 공급 API가 1:1 전용이 되어 확장(다른 소비자)이 막힌다.
- 계획 문서(`youtube-feature-pipeline-plan.md`)는 완료 후 동결되므로 계약 정본으로 부적합.
- 검수 전 후보가 일반 feature와 동급 노출되면 사용자 신뢰도 구분이 불가능하다.
- skip-only 처리는 철회된 후보를 feature로 영구 잔존시켜 데이터 품질을 해친다.

### 결과

- kor-travel-map: T-217a(fetcher 경로 정렬, T-066 배포와 동시) + T-217b(inactive 전환).
- TripMate-agent: T-066 구현 시 본 ADR 준수 — 상세 체크리스트는 해당 repo
  `docs/cross-repo-consistency-actions-2026-06-10.md` TA-01~03.
- inactive 전환된 feature의 소비자 응답 정책 확정(D-12, 2026-06-10): batch/단건
  read에서 **`found`에 포함하되 status(inactive)를 노출**한다 — `missing` 처리하면
  "삭제됨"과 "철회됨"을 구분할 수 없다. 기존 admin deactivate read 정책과 동일해야
  하며, T-217b에서 일관성 검증을 포함한다.
