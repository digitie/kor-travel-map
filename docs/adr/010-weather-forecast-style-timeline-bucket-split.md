# ADR-010: weather — `forecast_style` + `timeline_bucket` 분리

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: Claude (v1 산출물 채택)
- **컨텍스트**: provider별 weather는 성격(nowcast/observed/index/advisory)과
  KMA식 조회 축(ultra_short/short/mid)이 직교한다. 한 컬럼에 합치면 조회
  복잡도가 폭발한다.
- **결정**:
  - `forecast_style ∈ {nowcast, ultra_short, short, mid, observed, index, advisory}`
  - `timeline_bucket ∈ {ultra_short, short, mid}` (조회 축, 분류 결과)
  - unique key에는 `forecast_style`만 포함, `timeline_bucket`은 제외.
- **근거**: v1 산출물 검증됨.
- **결과 (긍정)**: provider 다양성을 흡수 가능.
- **결과 (부정)**: 새 provider 추가 시 두 축 매핑 결정 필요 → ADR로 박는다.
- **후속**: `docs/etl/weather-feature-normalization.md`에 provider별 매핑 표 유지.
