# WSL kraddr.geo 디버그 UI 메모

`python-kraddr-geo` 또는 `python-krtour-map`에서 이 provider를 검증할 때는 WSL 안에서
Linux 실행 파일을 사용하고, host binding을 명시해서 로컬 지오코딩 디버그 스택을 실행한다.

```bash
cd /mnt/f/dev/pykraddr
KRADDR_GEO_SPATIALITE_PATH=/mnt/f/dev/pykraddr/.codex_tmp/debug-kraddr.sqlite \
  .venv/bin/python -m uvicorn kraddr_geo_api.main:app \
  --app-dir backend --host 0.0.0.0 --port 3011

cd /mnt/f/dev/pykraddr/web
PATH=/mnt/f/dev/pykraddr/.wsl-node/node-v22.21.1-linux-x64/bin:$PATH \
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:3011 \
  npm run dev -- --hostname 0.0.0.0 --port 3010
```

WSL 내부에서는 `http://127.0.0.1:3010`을 사용한다. Windows에서는 먼저
`http://localhost:3010`을 시도하고, localhost forwarding이 동작하지 않으면
`hostname -I`로 확인한 WSL 주소를 사용한다.

이 흐름에서는 WSL에서 Windows `node.exe`/`npx`를 사용하지 않는다. pykraddr 저장소의
`.wsl-node` Linux Node 경로가 검증된 경로다. 2026-05-20 기준 warm smoke 실행은
1행짜리 디버그 DB에서 웹 페이지 약 100ms, `/addresses` 약 29ms,
`/reverse-geocode` 약 24ms였다.
