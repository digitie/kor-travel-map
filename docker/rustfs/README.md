# RustFS local compose

`python-krtour-map`의 feature file ETL과 Debug UI smoke test용 RustFS 구성이다.
TripMate와 같은 bucket 기본값인 `tripmate-media`를 사용한다.

```bash
cd /home/digitie/dev/python-krtour-map
docker compose -f docker/rustfs/docker-compose.yml up -d rustfs rustfs-init
```

기본 주소:

- S3 API: `http://127.0.0.1:19000`
- Console: `http://127.0.0.1:19001`
- Bucket: `tripmate-media`

Debug UI는 `http://localhost:8600`에서 RustFS 설정을 읽고 저장하며, 파일 목록은
백엔드 `http://localhost:8601/api/debug`의 signed S3 list call을 통해 확인한다.
