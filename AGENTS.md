# AGENTS.md

## 역할

이 저장소는 TripMate의 지도 feature/source/weather/price 계약을 제공하는 하부 라이브러리입니다. 작업 전에 이 파일과 `README.md`, `docs/provider-contract.md`를 먼저 확인합니다.

## 지시 우선순위

1. 사용자 요청
2. 이 `AGENTS.md`
3. `docs/` 문서
4. `README.md`
5. 기존 코드와 테스트
6. 최소한의, 되돌릴 수 있는 가정

## Provider API 사용 원칙

- 외부 API 관련 작업은 다른 구현보다 먼저 wrapper/adapter/gateway 지양 원칙을 확인하고 문서/코드에 반영한 뒤 진행합니다.
- `python-krtour-map`은 provider 호출 wrapper가 아닙니다. 안정된 `python-*-api` public client와 typed model에서 나온 결과를 feature/source/weather/price 계약으로 정리합니다.
- 부족한 endpoint, typed model, pagination, cursor, exception, raw payload 보존 규칙은 TripMate나 이 저장소에 임시 facade를 만들지 않고 해당 `python-*-api` 저장소에서 먼저 안정화합니다.
- 단순 전달용 `KmaWrapper`, `VWorldAdapter`, `OpiNetGateway` 같은 계층을 만들지 않습니다.
- 필요한 경계는 provider model을 `Feature`, `SourceRecord`, `WeatherValue`, `PriceValue`로 바꾸는 순수 함수와 저장소 repository까지입니다.

## 검증

```bash
python -m ruff check .
python -m pytest
python -m compileall src tests
```
