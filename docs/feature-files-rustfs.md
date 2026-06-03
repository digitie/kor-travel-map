# feature-files-rustfs.md — feature 파일과 S3 호환 객체 저장소

본 문서는 feature에 첨부되는 이미지/문서/오디오/비디오 바이너리 처리 방식이다.
S3 호환 객체 저장소(RustFS 1차, MinIO/Ceph/AWS S3/Cloudflare R2 swap, ADR-015)에
저장하고 `feature_files` 1:N table에 metadata만 저장.

## 1. 원칙

- **바이너리는 DB에 직접 저장 X**. JSONB에 base64 인코딩 금지.
- 모든 이미지/문서/오디오/비디오 → S3 호환 객체 저장소 + `feature_files`
  메타데이터.
- backend swap 자유 — 라이브러리는 boto3 호환 API만 사용 (ADR-015).
- 1 feature : N files (대표 이미지 + 썸네일 + 갤러리).

## 2. 데이터 모델

### 2.1 `FeatureFile` DTO

```python
class FeatureFile(BaseModel):
    file_id: str                              # make_feature_file_id(feature_id, bucket, object_key)
    feature_id: str
    file_type: Literal["image", "video", "audio", "document", "file"]
    storage_backend: str = "s3"               # 'rustfs' / 's3' / 'minio' 등
    bucket: str
    object_key: str
    source_url: str | None = None             # 원본 provider URL (참고용)
    public_url: str | None = None             # 외부 공개 URL (CDN 등)
    content_type: str | None = None           # MIME
    byte_size: int | None = None
    checksum_sha256: str | None = None
    width: int | None = None                  # 이미지/비디오만
    height: int | None = None
    role: Literal["primary", "thumbnail", "gallery"] = "gallery"
    display_order: int = 0
    alt_text: str | None = None
    provider: str | None = None               # 출처 provider canonical name
    dataset_key: str | None = None
    source_record_key: str | None = None      # FK SET NULL
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=kst_now)
    updated_at: datetime = Field(default_factory=kst_now)
```

### 2.2 `FeatureFileSource` DTO (업로드 입력)

provider 변환 함수가 만드는 임시 DTO. 아직 다운로드/업로드 전.

```python
class FeatureFileSource(BaseModel):
    feature_id: str
    source_url: str                           # provider가 준 원본 URL
    role: Literal["primary", "thumbnail", "gallery"] = "gallery"
    display_order: int = 0
    file_type: Literal["image", "video", "audio", "document", "file"] = "image"
    content_type: str | None = None
    alt_text: str | None = None
    provider: str | None = None
    dataset_key: str | None = None
    source_record_key: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
```

## 3. 적재 흐름

```
provider 응답 (URL만)
    ↓
provider 변환 함수
    ↓ FeatureFileSource (downloaded=False)
    ↓
upload_feature_file_sources_to_rustfs(store, sources)
    ↓ 1. URL 다운로드 (httpx)
    ↓ 2. checksum 계산
    ↓ 3. object_key 결정 (deterministic)
    ↓ 4. 객체 저장소 PUT (boto3)
    ↓ 5. FeatureFile DTO 생성
    ↓
DB load (feature_files insert/upsert)
```

## 4. object_key 명명 규약

deterministic, 같은 입력 → 같은 key (idempotent upload):

```
{prefix}/{provider_short}/{feature_id_prefix}/{feature_id}/{role}-{display_order}-{checksum8}.{ext}
```

예:
```
features/visitkorea/f_1111000000_e/f_1111000000_e_abc123/primary-0-d2a4f1e7.jpg
```

- `prefix`: `features` (settings.object_store_prefix)
- `provider_short`: provider canonical name 단축형 (visitkorea, mois, ...)
- `feature_id_prefix`: feature_id의 앞 12자 (디렉토리 분산)
- `feature_id`: 전체 feature_id
- `role`-`display_order`: 동일 feature의 여러 파일 구분
- `checksum8`: SHA-256 앞 8자 — 같은 URL 재다운로드 시 동일 (idempotent)
- `ext`: content_type에서 추론 (`.jpg`, `.png`, `.mp4`, `.pdf`, ...)

## 5. `RustfsFileStore` (S3 호환 wrapper)

```python
@dataclass
class RustfsFileStore:
    s3_client: Any                            # boto3.client('s3') 호환
    bucket: str
    prefix: str = "features"
    public_base_url: str | None = None        # http://cdn.example.com/krtour-map
    
    async def upload(self, object_key: str, body: bytes, *,
                     content_type: str | None = None) -> dict:
        """boto3 put_object 호출. 동기지만 asyncio.to_thread로 감싸 반환."""
        return await asyncio.to_thread(
            self.s3_client.put_object,
            Bucket=self.bucket, Key=object_key, Body=body,
            ContentType=content_type or "application/octet-stream",
        )
    
    def public_url(self, object_key: str) -> str | None:
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{object_key}"
        return None
```

backend swap: `s3_client`만 다른 endpoint로 교체.
- RustFS: `endpoint_url="http://127.0.0.1:9003"` (로컬 표준 S3 API 포트)
- MinIO: `endpoint_url="http://minio:9000"`
- AWS S3: 기본 endpoint
- Cloudflare R2: `endpoint_url="https://<account>.r2.cloudflarestorage.com"`

## 6. upload helper

```python
async def upload_feature_file_sources_to_rustfs(
    store: RustfsFileStore,
    sources: Iterable[FeatureFileSource],
    *,
    http_client: httpx.AsyncClient | None = None,
    timeout_seconds: int = 30,
    chunk_size: int = 1024 * 1024,           # 1 MiB
) -> list[FeatureFile]:
    """downloaded URL → checksum → upload → FeatureFile."""
    
    files: list[FeatureFile] = []
    async with (http_client or httpx.AsyncClient(timeout=timeout_seconds)) as client:
        for src in sources:
            # 1. 다운로드
            response = await client.get(src.source_url)
            response.raise_for_status()
            body = response.content
            
            # 2. 메타 계산
            checksum = hashlib.sha256(body).hexdigest()
            content_type = src.content_type or response.headers.get("Content-Type")
            ext = _extension_for_content(content_type)
            width, height = _probe_image_dims(body, content_type)
            
            # 3. object_key
            object_key = _make_object_key(
                prefix=store.prefix,
                provider=src.provider,
                feature_id=src.feature_id,
                role=src.role, display_order=src.display_order,
                checksum=checksum, ext=ext,
            )
            
            # 4. upload (idempotent — 같은 checksum이면 같은 key)
            await store.upload(object_key, body, content_type=content_type)
            
            # 5. metadata
            file = FeatureFile(
                file_id=make_feature_file_id(src.feature_id, store.bucket, object_key),
                feature_id=src.feature_id,
                file_type=src.file_type,
                storage_backend="rustfs",      # ADR-015 — 'rustfs' 또는 's3' 표준값
                bucket=store.bucket,
                object_key=object_key,
                source_url=src.source_url,
                public_url=store.public_url(object_key),
                content_type=content_type,
                byte_size=len(body),
                checksum_sha256=checksum,
                width=width, height=height,
                role=src.role,
                display_order=src.display_order,
                alt_text=src.alt_text,
                provider=src.provider,
                dataset_key=src.dataset_key,
                source_record_key=src.source_record_key,
                payload=src.payload,
            )
            files.append(file)
    return files
```

## 7. provider별 적재 패턴

### 7.1 VisitKorea (단일/대표/썸네일)

```python
def visitkorea_festival_to_file_sources(item, *, feature_id, source_record_key) -> list[FeatureFileSource]:
    sources = []
    if item.first_image:
        sources.append(FeatureFileSource(
            feature_id=feature_id, source_url=item.first_image,
            role="primary", display_order=0,
            provider="python-visitkorea-api",
            dataset_key="visitkorea_festival_events",
            source_record_key=source_record_key,
        ))
    if item.first_image2 and item.first_image2 != item.first_image:
        sources.append(FeatureFileSource(
            feature_id=feature_id, source_url=item.first_image2,
            role="thumbnail", display_order=1,
            provider="python-visitkorea-api",
            dataset_key="visitkorea_festival_events",
            source_record_key=source_record_key,
        ))
    return sources
```

### 7.2 국가유산 (multi-type)

```python
def krheritage_to_file_sources(item, *, feature_id, source_record_key) -> list[FeatureFileSource]:
    sources = []
    for i, media in enumerate(item.images or []):
        sources.append(FeatureFileSource(
            feature_id=feature_id, source_url=media.image_url,
            role="primary" if i == 0 else "gallery",
            display_order=i, file_type="image",
            alt_text=media.image_description,
            provider="python-krheritage-api",
            dataset_key="krheritage_heritage_features",
            source_record_key=source_record_key,
        ))
    for v in item.videos or []:
        sources.append(FeatureFileSource(
            feature_id=feature_id, source_url=v.video_url,
            role="gallery", display_order=len(sources),
            file_type="video",
            provider="python-krheritage-api",
            dataset_key="krheritage_heritage_features",
            source_record_key=source_record_key,
        ))
    for a in item.narrations or []:
        sources.append(FeatureFileSource(
            feature_id=feature_id, source_url=a.audio_url,
            file_type="audio",
            role="gallery", display_order=len(sources),
            provider="python-krheritage-api",
            dataset_key="krheritage_heritage_features",
            source_record_key=source_record_key,
        ))
    for doc in item.files or []:
        if doc.file_url.lower().endswith(".pdf"):
            sources.append(FeatureFileSource(
                feature_id=feature_id, source_url=doc.file_url,
                file_type="document", content_type="application/pdf",
                role="gallery", display_order=len(sources),
                provider="python-krheritage-api",
                dataset_key="krheritage_heritage_features",
                source_record_key=source_record_key,
            ))
    return sources
```

### 7.3 KHOA beach (옵션)

```python
def khoa_beach_to_file_sources(item, *, feature_id, source_record_key) -> list[FeatureFileSource]:
    if not item.beach_img or not item.beach_img.startswith(("http://", "https://")):
        return []                              # 상대 경로/파일명만은 payload에만
    return [FeatureFileSource(
        feature_id=feature_id, source_url=item.beach_img,
        role="primary", display_order=0,
        provider="python-khoa-api",
        dataset_key="khoa_oceans_beach_info",
        source_record_key=source_record_key,
    )]
```

## 8. settings

```
KRTOUR_MAP_OBJECT_STORE_ENDPOINT_URL=http://127.0.0.1:9003
KRTOUR_MAP_OBJECT_STORE_BUCKET=krtour-map
KRTOUR_MAP_OBJECT_STORE_REGION=us-east-1
KRTOUR_MAP_OBJECT_STORE_ACCESS_KEY_ID=...
KRTOUR_MAP_OBJECT_STORE_SECRET_ACCESS_KEY=...
KRTOUR_MAP_OBJECT_STORE_PUBLIC_BASE_URL=http://127.0.0.1:9003/krtour-map
KRTOUR_MAP_OBJECT_STORE_PREFIX=features
KRTOUR_MAP_OFFLINE_UPLOAD_BUCKET=krtour-uploads
KRTOUR_MAP_OFFLINE_UPLOAD_PREFIX=offline-uploads
KRTOUR_MAP_DOCKER_OBJECT_STORE_ENDPOINT_URL=http://rustfs:9000
```

로컬 RustFS 표준 포트는 S3 API `9003`, console `9004`다. MinIO 호환 테스트
컨테이너를 쓸 때만 MinIO 기본 `9000`/`9001` 예시를 따른다.

v1 fallback chain (`TRIPMATE_RUSTFS_*`, `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY`)도
optional 지원 (마이그레이션 편의).

## 9. 로컬 실행 (RustFS Docker)

```bash
npm run docker:up
# 또는
docker compose up -d --build postgres rustfs rustfs-init api frontend dagster
```

bucket 자동 생성 (`rustfs-init` 컨테이너가 `mc mb --ignore-existing` 호출):
`krtour-map`(feature files)과 `krtour-uploads`(offline upload 원본). 또는 RustFS
console (`http://127.0.0.1:9004`)에서 수동 생성.

대안: MinIO testcontainer (`testcontainers-python`의 `MinioContainer`).

## 10. presigned URL (옵션)

업로드 시간이 길거나 클라이언트가 직접 업로드해야 하는 경우 (UI에서 사용자가
업로드 등 — v2 1차 범위 외):

```python
def make_presigned_upload(self, object_key: str, expires_in: int = 3600) -> str:
    return self.s3_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": self.bucket, "Key": object_key},
        ExpiresIn=expires_in,
    )
```

CDN 또는 외부 클라이언트 업로드 시점에 결정. 본 라이브러리는 일단 서버측
업로드만.

## 11. CDN / public URL

`KRTOUR_MAP_OBJECT_STORE_PUBLIC_BASE_URL`을 CDN URL로 설정하면 frontend가
직접 그 URL로 이미지 로드:
```
https://cdn.tripmate.example.com/krtour-map/features/visitkorea/f_.../primary-0-d2a4f1e7.jpg
```

unset이면 `public_url=None` → frontend가 직접 객체 저장소 endpoint 접근
(개발 환경만).

## 12. 다운로드 / 재시도 / 타임아웃

provider 응답에서 image URL이 만료되거나 404 가능:

```python
async def upload_with_retry(client, src, store, *, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await _do_upload(client, src, store)
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (404, 410):
                # 영구 실패 — skip
                return None
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)
```

영구 실패는 `data_integrity_violations`에 `violation_type='media_download_failed'`
기록.

## 13. 정합성 검토

`ops.feature_consistency_reports` (T-201) 케이스:
- `M1`: `feature_files`에 등록된 object_key가 실제 bucket에 존재하는가
- `M2`: `checksum_sha256`이 실제 객체와 일치하는가 (샘플링)
- `M3`: 같은 `feature_id`에 `role='primary'` 1개 초과 (정상 = 0 or 1)
- `M4`: `display_order` 중복 (같은 feature 내)

일 1회 검사 + admin UI 노출.

## 14. 보관 정책

- 객체는 feature가 살아 있는 동안 유지.
- feature soft-delete (`status='deleted'`) → 객체 삭제는 별도 purge job (운영자
  결정, ADR-017 보관 정책과 동기).
- 30일 grace period 권장 (사용자 복구 요청 대비).

## 15. 보안

- bucket policy: public read 옵션 (CDN 사용 시) 또는 private + presigned URL.
- access_key / secret_key는 `SecretStr`. 로그/Sentry 노출 X.
- RustFS console (`http://127.0.0.1:9004`)은 인증 필요 + 내부망만.

## 16. 테스트

- 단위: Fake S3 client (in-memory dict)로 upload + checksum + object_key
  결정성 검증.
- 통합: MinIO testcontainer로 실제 PUT/GET.
- 부하 (nightly): 1000 이미지 동시 업로드 + 평균 latency 측정.

## 17. v1 → v2 변경

- import: `krtour_map.files` → `krtour.map.files`, `krtour_map.rustfs` →
  `krtour.map.rustfs`.
- async-only: upload 헬퍼는 `async def`.
- backend 추상화 강화: `storage_backend`가 `'rustfs'`/`'s3'`/`'minio'` 등 자유
  값 허용 (v1은 `'rustfs'`만 허용). ADR-015 미러.
- env prefix: `KRTOUR_MAP_RUSTFS_*` 유지 (호환) + 새 `KRTOUR_MAP_OBJECT_STORE_*`
  alias 추가.

## 18. 운영 체크리스트

- [ ] 객체 저장소 healthcheck (`client.healthz()` 포함)
- [ ] bucket 존재 + bucket policy 확인
- [ ] CDN URL public_base_url 설정 (운영)
- [ ] 디스크 사용량 모니터링 (RustFS volume)
- [ ] 백업 정책 (rclone + 외부 백업)
- [ ] 정합성 검사 M1~M4 일 1회 (T-201 활성화 시)
