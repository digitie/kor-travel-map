# python-krtour-map-debug-ui

`python-krtour-map`용 로컬 전용 디버그 웹 UI다.

```bash
python -m krtour_map_debug_ui.server
```

프론트엔드 기본 주소는 <http://localhost:8600>이고 로컬 JSON API 기본 주소는
<http://localhost:8601/api/debug>이다. 운영 사용자가 디버그 웹 진입점 없이
`python-krtour-map`만 설치할 수 있도록, 이 패키지는 핵심 feature 계약 패키지와 의도적으로
분리되어 있다.
