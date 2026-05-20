# Feature files and RustFS

이미지, 문서, provider 첨부파일 같은 바이너리 데이터는 RustFS에 저장한다. feature DB에는
파일 자체를 넣지 않고, RustFS 객체를 찾기 위한 메타데이터만 저장한다.

## 저장 원칙

- storage backend는 `rustfs`를 canonical 값으로 사용한다.
- feature 하나에는 여러 이미지/파일이 붙을 수 있으므로 1:N 관계인 `feature_files`를 사용한다.
- `features.detail`에는 provider 원문에서 온 이미지 URL을 참고용으로 남길 수 있지만, 앱에서 사용할 파일은 `feature_files`의 RustFS object metadata를 기준으로 조회한다.
- TripMate는 RustFS client/resource, bucket, 공개 URL 정책, transaction commit/rollback을 주입한다.
- 다운로드, checksum, object key 생성, RustFS 업로드, `FeatureFile` DTO 생성은 이 라이브러리의 helper를 사용한다.

## DTO

`FeatureFile` 핵심 필드:

- `file_id`: feature id, RustFS bucket/object key 기반 deterministic id
- `feature_id`: 연결된 feature
- `file_type`: `image`, `video`, `audio`, `document`, `file`
- `storage_backend`: `rustfs`
- `bucket`, `object_key`: RustFS 객체 위치
- `source_url`: provider가 준 원본 URL
- `public_url`: 공개/프록시 URL이 있을 때만 저장
- `content_type`, `byte_size`, `checksum_sha256`
- `width`, `height`: 이미지 크기를 알 수 있을 때 저장
- `role`: `primary`, `thumbnail`, `gallery` 등
- `display_order`: 한 feature 안의 표시 순서
- `provider`, `dataset_key`, `source_record_key`: source trace 연결
- `payload`: provider별 부가 메타데이터

## RustFS 업로드 helper

`RustfsFileStore`는 S3-compatible `put_object` client를 받아 사용한다. Boto3-style keyword call과
MinIO-style positional call을 모두 지원한다.

```python
from krtour_map.files import FeatureFileSource, RustfsFileStore, upload_feature_file_sources_to_rustfs

store = RustfsFileStore(
    client=rustfs_client,
    bucket="tripmate-media",
    prefix="feature-files",
    public_base_url="https://media.example.com",
)

files = upload_feature_file_sources_to_rustfs(
    store,
    [
        FeatureFileSource(
            feature_id=feature_id,
            source_url="https://cdn.example.com/festival.jpg",
            role="primary",
            display_order=0,
            provider="python-visitkorea-api",
            dataset_key="visitkorea_festival_events",
            source_record_key=source_record_key,
        )
    ],
)
```

## VisitKorea festival images

VisitKorea festival ETL은 `first_image`, `first_image2`를 `FeatureFileSource`로 추출한다.
DB 적재 시 `RustfsFileStore`를 넘기면 이미지를 다운로드해서 RustFS에 올린 뒤 `feature_files`에
metadata를 저장한다.

Korea Heritage ETL은 `python-krheritage-api`의 media model 관례를 이 라이브러리로 가져와
`MediaImage.image_url`, `MediaVideo.video_url`, `Narration.audio_url`, `fileUrl`/PDF류 문서를
각각 `image`, `video`, `audio`, `document` `FeatureFileSource`로 변환한다. provider 라이브러리는
RustFS 업로드를 소유하지 않고 typed media URL과 raw payload만 제공한다.

```python
from krtour_map.events import VisitKoreaFestivalLoadResources, load_visitkorea_festival_events

resources = VisitKoreaFestivalLoadResources(
    client=visitkorea_client,
    session=feature_session,
    rustfs_store=rustfs_store,
)
result = load_visitkorea_festival_events(resources, run)
```

RustFS resource를 넘기지 않으면 이미지 URL은 수집 결과의 `feature_file_sources`에만 남고,
`feature_files` row는 생성하지 않는다. 운영 ETL에서는 RustFS resource를 주입하는 것을 기본으로 한다.

## RustFS config and debug UI

`krtour_map.rustfs`는 TripMate와 공유할 수 있는 설정/presign/list helper를 제공한다.
기본 bucket은 TripMate 로컬 compose와 같은 `tripmate-media`다.

설정 파일 기본 경로:

```text
.krtour-map/rustfs.toml
```

주요 env:

```bash
KRTOUR_MAP_RUSTFS_ENDPOINT_URL=http://127.0.0.1:19000
KRTOUR_MAP_RUSTFS_PUBLIC_ENDPOINT_URL=http://127.0.0.1:19000
KRTOUR_MAP_RUSTFS_CONSOLE_URL=http://127.0.0.1:19001
KRTOUR_MAP_RUSTFS_BUCKET=tripmate-media
KRTOUR_MAP_RUSTFS_ACCESS_KEY_ID=tripmate-dev-access
KRTOUR_MAP_RUSTFS_SECRET_ACCESS_KEY=tripmate-dev-secret-change-me
```

`TRIPMATE_RUSTFS_*`, `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY`도 fallback으로 읽는다.
로컬 Debug UI(`http://localhost:8600`)는 설정 파일을 수정하고, signed S3 list call로 bucket
object 목록을 확인하며, RustFS console 링크를 노출한다.

로컬 RustFS는 다음 compose로 실행한다.

```bash
docker compose -f docker/rustfs/docker-compose.yml up -d rustfs rustfs-init
```
