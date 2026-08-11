"""offline upload 적재 advisory lock 키의 직렬화 단위 회귀.

``load_offline_upload``의 docstring은 "같은 provider/dataset/scope 단위는 advisory
lock으로 직렬화한다"고 진술한다. 그 진술을 지키는 것은 ``_advisory_key`` 하나인데,
그 함수에서 ``sync_scope`` 성분을 지우는 변이가 ``tests/unit`` 전체와
``tests/integration`` 전체를 통과했다(라운드 12 M-1 실측). 어느 게이트도 직렬화
단위를 보지 않았다는 뜻이라 이 파일을 넣는다.

키는 ``ops.offline_uploads`` 행이 아니라 **프로세스 간 계약**이다. 같은 ``import:``
namespace를 ``cli/mutex.py``·``mois.py``가 함께 쓰므로(둘은
``import:<provider>:<dataset_key>`` 꼴), 키 문자열 모양이 조용히 바뀌면 어느 워커가
서로 직렬화되는지가 함께 바뀐다. 그래서 문자열 자체도 못박는다.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from kortravelmap.infra.advisory_lock import advisory_lock_key
from kortravelmap.infra.offline_upload_repo import OfflineUpload
from kortravelmap.offline_upload import _advisory_key

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 8, 11, tzinfo=UTC)

_UPLOAD = OfflineUpload(
    upload_id="00000000-0000-0000-0000-000000000001",
    provider_dataset_id=41,
    sync_scope="dataset_wide",
    operation_key="offline_fixture_offline_jsonl_refresh",
    original_filename="features.jsonl",
    storage_backend="s3",
    storage_key="offline/advisory/features.jsonl",
    byte_size=3,
    checksum_sha256="a" * 64,
    detected_format="jsonl",
    detected_encoding="utf-8",
    status="uploaded",
    validation_job_id=None,
    load_job_id=None,
    created_by="pytest",
    created_at=_NOW,
    updated_at=_NOW,
)


def test_advisory_key_serializes_by_dataset_and_scope() -> None:
    """직렬화 단위는 (provider_dataset_id, sync_scope)다 — 양방향으로 못박는다."""

    same_membership = replace(
        _UPLOAD,
        upload_id="00000000-0000-0000-0000-000000000002",
        storage_key="offline/advisory/other.jsonl",
        checksum_sha256="b" * 64,
    )
    other_scope = replace(_UPLOAD, sync_scope="region:11")
    other_dataset = replace(_UPLOAD, provider_dataset_id=42)

    # 같은 membership의 다른 행은 **같은** 키여야 한다. upload_id/checksum이 키에
    # 섞이면 같은 (dataset, scope)에 두 적재가 동시에 들어온다.
    assert _advisory_key(_UPLOAD) == _advisory_key(same_membership)
    # scope가 다르면 **다른** 키여야 한다. scope 성분을 빼면 서로 무관한 scope의
    # 적재가 한 줄로 묶여 직렬화 단위가 dataset 전체로 넓어진다.
    assert _advisory_key(_UPLOAD) != _advisory_key(other_scope)
    assert _advisory_key(_UPLOAD) != _advisory_key(other_dataset)


def test_advisory_key_distinctness_survives_int64_hashing() -> None:
    """Postgres에 가는 것은 문자열이 아니라 int64다 — 그 축에서도 갈라져야 한다."""

    other_scope = replace(_UPLOAD, sync_scope="region:11")
    other_dataset = replace(_UPLOAD, provider_dataset_id=42)

    assert advisory_lock_key(_advisory_key(_UPLOAD)) != advisory_lock_key(
        _advisory_key(other_scope)
    )
    assert advisory_lock_key(_advisory_key(_UPLOAD)) != advisory_lock_key(
        _advisory_key(other_dataset)
    )


def test_advisory_key_string_shape_is_a_cross_process_contract() -> None:
    """키 문자열 모양은 ``import:`` namespace를 함께 쓰는 쪽과의 계약이다."""

    assert _advisory_key(_UPLOAD) == "import:41:dataset_wide"
