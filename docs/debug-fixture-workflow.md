# Debug fixture workflow

첨부 문서 `rest_api_debug_ui_fixture_testcase_final.docx`의 기준을 이 라이브러리에 맞게 정리한 문서입니다.

## 결론

Web UI는 테스트 코드를 직접 생성하는 도구가 아니라 fixture JSON 생성기입니다. pytest는 공통 runner를 통해 `tests/fixtures/**/*.json`을 읽고 replay 기반 회귀 테스트를 수행합니다.

## 패키지 분리

```text
python-krtour-map/
  src/krtour_map/
    parser.py
    processor.py
    debug.py
    fixtures.py
  tests/
    fixtures/
    runners.py
    test_generated_fixtures.py

krtour-map-debug-ui/
  app.py
  fixture_writer.py
  preset_store.py
  history_store.py
```

`python-krtour-map`은 Streamlit에 의존하지 않습니다. Debug UI는 wheel 또는 editable install된 라이브러리를 import해서 사용합니다.

## DebugRun

`DebugRun`에는 입력, 요청, 응답, parsed, processed, trace, error를 모두 담습니다.

```python
from krtour_map.debug import DebugRun

run = DebugRun(
    function="feature_summary",
    input={"provider": "python-opinet-api"},
    request={"method": "GET", "url": "..."},
    response={"status_code": 200, "body": raw},
    parsed=feature,
    processed=summary,
    trace=["parsed feature", "summarized feature"],
)
payload = run.to_fixture_payload()
```

## Fixture 포맷

기본 위치:

```text
tests/fixtures/{function_name}/{case_name}.json
```

필드:

- `name`
- `function`
- `description`
- `input`
- `request`
- `response`
- `parsed`
- `processed`
- `assertion`
- `meta`

`api_key`, `Authorization`, `serviceKey`, `access_token`, `refresh_token` 등 민감정보는 저장 전에 `<REDACTED>`로 마스킹합니다.

## Assertion mode

현재 구현:

- `snapshot`: processed 전체 비교. `exclude_fields` 적용
- `schema_only`: parser/processor 성공만 확인
- `required_fields`: dotted path 기반 필드 존재 확인
- `count`: 결과 개수 비교

후속 후보:

- custom assertion registry
- diff UI
- markdown report export
- batch replay UI

## pytest runner

테스트 코드를 케이스마다 생성하지 않습니다.

```python
from krtour_map.fixtures import load_fixture, replay_fixture
from tests.runners import RUNNERS

def test_generated_fixture(path):
    replay_fixture(load_fixture(path), RUNNERS)
```

외부 API를 호출하는 live test는 기본 pytest 경로에 넣지 않습니다.
