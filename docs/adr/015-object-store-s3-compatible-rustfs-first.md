# ADR-015: 객체 저장소는 S3 호환만 가정, RustFS 1차, MinIO/Ceph/R2 swap

- **상태**: accepted
- **날짜**: 2026-05-24
- **결정자**: 사용자 (SPEC V8 v8_0)
- **컨텍스트**: SPEC V8 v8_0은 RustFS(Apache 2.0, ARM64 공식 이미지)를 1차로
  선택했지만 MinIO/Ceph/AWS S3/Cloudflare R2 swap을 전제로 한다.
- **결정**: 라이브러리는 boto3 호환 S3 API만 사용한다. RustFS 고유 기능
  의존성 금지. 환경변수 `KOR_TRAVEL_MAP_OBJECT_STORE_*`로 어떤 backend든 주입
  가능.
- **근거**: SPEC V8 v8_0 + 향후 호스팅 변경 대비.
- **결과 (긍정)**: backend swap 자유. 테스트는 MinIO testcontainer로 가능.
- **결과 (부정)**: presigned URL, multipart upload, replication 같은 backend
  고유 기능 의존 금지 — 필요 시 backend 추상화 추가.
- **후속**: `infra/file_store.py`는 boto3 client만 받음. `docs/architecture/data-model.md`에
  `feature_files` 컬럼 정의.
