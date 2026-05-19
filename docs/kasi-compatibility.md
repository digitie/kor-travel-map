# KASI API compatibility

`python-krtour-map`은 KASI 데이터를 직접 호출하는 별도 wrapper/adapter를 만들지 않고
`python-kasi-api`의 public client와 typed model을 그대로 사용한다.

KASI 연동 코드는 `python-krheritage-api`와 같은 호출 형태를 기준으로 작성한다.

```python
from kasi import AsyncKasiClient, KasiClient, PROVIDER_NAME

assert PROVIDER_NAME == "python-kasi-api"

with KasiClient(api_key=service_key) as client:
    holidays = client.holidays(sol_year=2026, sol_month=5)

async with AsyncKasiClient(api_key=service_key) as client:
    sun = await client.area_rise_set(locdate="20260507", location="서울")
```

새 ETL 코드는 `KasiClient(api_key=...)`, `AsyncKasiClient(api_key=...)`,
`KasiClient.aio(api_key=...)`, `client.config`, `Page[T]`, public Pydantic model을 사용한다.
기존 `service_key=`와 위치 인자는 하위 호환용으로만 남겨 두고, TripMate 쪽 신규 코드는
`python-krheritage-api`와 같은 `api_key=` 명명 인자 형태에 맞춘다.

선택 의존성은 다음처럼 설치한다.

```bash
pip install -e ".[kasi]"
```
