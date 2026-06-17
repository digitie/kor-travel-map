# ADR-050: concierge provider export의 철회 라이프사이클을 inactive 전환으로 처리한다

### 상태

Accepted (2026-06-10) — ADR-049 보강, provider identity/name은 ADR-053으로 superseded.
배경은 `docs/reports/service-completeness-review-2026-06-10.md`
§4 C-4 · §5 R-3/R-4, 의사결정 `docs/reports/decisions-needed-2026-06-10.md` D-03/D-04/D-05.

### 결정

1. **철회 라이프사이클**: kor-travel-map은 concierge provider export의 `reject`/`tombstone`
   operation을 skip으로 끝내지 않고 해당 feature의 **inactive 전환**(+사유 기록)으로
   처리한다 — MOIS Step C(폐업→inactive)와 동형 (T-217b). 1단계로 skip 건수 WARN/admin
   이슈 노출을 선행할 수 있다.
2. **fetcher 경로**: kor-travel-map fetcher는 `/api/v1/features/snapshot`·
   `/api/v1/features/changes`를 소비한다. 계약(스키마·cursor·operation)의 정본은 공급
   측(provider) 문서이며, 본 repo는 소비 측 기대치(`{items, has_more, next_cursor}`,
   `X-API-Key`, env 키)만 요약한다 — ADR-044 관행(데이터 정합성 1차 책임 = 공급 측)과 일치.

### 근거

- skip-only 처리는 철회된 후보를 feature로 영구 잔존시켜 데이터 품질을 해친다.
- 계약 정본을 공급 측에 두면(ADR-044) 본 repo는 미러·소비만 하면 되고 drift가 준다.

### 결과

- kor-travel-map: T-217a(fetcher 경로 정렬) + T-217b(inactive 전환).
- inactive 전환된 feature의 외부 경계(OpenAPI) 응답 정책 확정(D-12, 2026-06-10):
  batch/단건 read에서 **`found`에 포함하되 status(inactive)를 노출**한다 — `missing`
  처리하면 "삭제됨"과 "철회됨"을 구분할 수 없다. 기존 admin deactivate read 정책과
  동일해야 하며, T-217b에서 일관성 검증을 포함한다.
