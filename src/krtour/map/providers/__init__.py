"""``krtour.map.providers`` — provider별 raw → DTO 변환 모듈.

각 provider 라이브러리(``python-*-api``)의 typed model을 본 라이브러리의
``FeatureBundle``로 정규화하는 **순수 함수 namespace**. wrapper/adapter/
gateway 신규 생성 금지 (ADR-006).

**Sprint 2~5에서 provider별 모듈 점진 추가** — ADR-034 9단계 순서:

| Sprint | provider 모듈 |
|--------|--------------|
| 2 | ``visitkorea`` / ``kma`` / ``airkorea`` / ``krforest_weather`` |
|   | / ``khoa_weather`` / ``opinet`` / ``krex`` |
| 3 | ``knps`` (14 dataset) / ``krforest_trails`` / ``krheritage`` |
| 4 | ``mois`` (4단계 lifecycle) |
| 5 | ``krforest`` (휴양림/수목원) / ``standard_data`` (5종) |

ADR 참조
--------
- ADR-006 — provider wrapper/adapter 금지 (public client 직접 사용)
- ADR-024 — canonical provider name (``python-mois-api``, ``python-knps-api``,
  등)
- ADR-034 — 구현 9단계 순서
"""

from __future__ import annotations

__all__: list[str] = []
# Sprint 2~5에서 provider별 채워질 예정. 본 PR#17은 PEP 420 namespace 박음.
