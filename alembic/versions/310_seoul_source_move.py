"""서울 책방의 curated source 메타를 옮긴 원천에 맞춘다.

Revision ID: 310_seoul_source_move
Revises: 309_t39_feature_id_rekey

## 왜 코드가 아니라 마이그레이션인가

`feature.curated_sources`는 **ETL이 갱신하지 않는다.** 이 행은 baseline seed가
넣은 그대로 남고, admin UI와 공개 curation API가 그 값을 읽어 사용자에게 보여
준다(`api/routers/curated.py`, `api/routers/curations.py`). 그래서 원천이 옮겨
가면 이 행도 함께 옮겨야 하는데, seed는 봉인된 baseline이라 고치는 자리가 아니다
— 조정기가 맞춰야 하는 쪽이다.

## 무엇이 어긋나 있었나 (2026-09-19 적대 리뷰)

서울 책방 행은 다음을 들고 있었다.

- `source_url='https://www.data.go.kr/data/15084328/fileData.do'` — 2026-09-18에
  **404 `등록되지 않은 서비스 입니다`**로 사라진 바로 그 주소다.
- `update_cycle='one_time'` — 이제 월간 schedule이 다시 켜졌다.
- `row_count=555` — 새 원천 실측은 606이다.
- `freshness_note='서울 열린데이터광장 원천 서비스 종료 안내 노출'` —
  **옮겨 간 바로 그 포털을 "종료"라고 말한다.** 뜻이 반대로 뒤집혔다.

마지막 항목이 이 마이그레이션의 이유다. 틀린 URL은 클릭하면 404로 드러나지만,
뒤집힌 문장은 **운영자가 읽고 잘못된 결론을 내린다.**

## 왜 UPDATE 하나가 아니라 revision까지 올리는가

이 표는 `row_revision`/`observation_revision`으로 낙관적 동시성을 건다. 값만
바꾸고 revision을 그대로 두면 이 행을 읽어 둔 쪽이 **바뀐 줄 모른다.** 커맨드
프로시저(`feature.update_curated_source_command`)를 쓰지 않는 이유는 그쪽이
SERIALIZABLE + 실행자 롤을 요구해 마이그레이션 경로에서 쓸 수 없기 때문이다 —
그래서 그 프로시저가 하는 일(값 + 두 revision + `updated_at`)을 여기서 그대로 한다.

## `RESET ROLE`을 하지 않는다

이 저장소의 마이그레이션은 전부 `SET ROLE ktm_feature_schema_owner`를 **켠 채로
끝난다.** 그 상태에서 alembic이 자기 `UPDATE alembic_version`을 내기 때문이다 —
접속 로그인 롤에는 그 표의 UPDATE 권한이 없다. 롤을 되돌리면 본문이 다 성공한 뒤
**버전 기록에서** `permission denied for table alembic_version`으로 죽는다.

이 규약은 어디에도 적혀 있지 않았고, 2026-09-19에 이 마이그레이션이 그것을 깨서
통합 검사 1,080건이 같은 원인으로 무너졌다. `tests/lint/test_migrations_keep_the_
schema_owner_role.py`가 이제 그것을 센다.

## receipt head CHECK를 함께 넓힌다

``ops.application_schema_operation_receipts``의 ``destination_head`` CHECK는 **graph의
모든 revision**을 열거한다. 현재 head만 넣으면 중간 revision으로 설치된 DB에서
``ADD CONSTRAINT`` 자체가 실패해 배포가 도중에 멈춘다 —
``tests/lint/test_receipt_head_check_covers_the_graph_head.py``가 그것을 센다.

## 행이 없으면 조용히 지나간다

`provider_dataset_id`로 찾는다. seed 이전 상태나 dataset을 지운 환경에서는 대상이
없고, 그때 실패할 이유가 없다 — 이 마이그레이션이 고치는 것은 **있는 행의
내용**이지 행의 존재가 아니다. 다만 **몇 행을 고쳤는지 로그에 남긴다**: 0행으로
지나간 것과 고친 것을 나중에 구분할 수 있어야 한다.
"""

from __future__ import annotations

import logging
from typing import Final

import sqlalchemy as sa

from alembic import op

#: **32자 이하여야 한다** — `public.alembic_version.version_num`이 `varchar(32)`다.
revision: Final[str] = "310_seoul_source_move"
down_revision: Final[str] = "309_t39_feature_id_rekey"
branch_labels: None = None
depends_on: None = None

_LOGGER: Final = logging.getLogger("alembic.runtime.migration")

#: 옮겨 간 원천. 서울 열린데이터광장 OA-21062(`TbSlibBookstoreInfo`).
_NEW_URL: Final = "https://data.seoul.go.kr/dataList/OA-21062/S/1/datasetView.do"

#: 2026-09-19 라이브 `list_total_count`.
_NEW_ROW_COUNT: Final = 606

_NEW_NOTE: Final = (
    "2026-09-18 data.go.kr odcloud 자동변환 API가 404 `등록되지 않은 서비스 "
    "입니다`로 사라져 원천을 서울 열린데이터광장 OA-21062"
    "(서비스명 TbSlibBookstoreInfo)로 옮겼다. 2026-09-19 라이브 606건 확인. "
    "dataset_key와 provider 이름은 레지스트리 신원이라 그대로 둔다."
)

#: 되돌릴 때 쓸 seed 원본 값.
_OLD_URL: Final = "https://www.data.go.kr/data/15084328/fileData.do"
_OLD_ROW_COUNT: Final = 555
_OLD_NOTE: Final = "서울 열린데이터광장 원천 서비스 종료 안내 노출"

_DATASET_KEY: Final = "datagokr_seoul_bookstores"


#: 값을 SQL 문자열에 넣지 않고 bind parameter로 넘긴다.
#:
#: 이 저장소의 마이그레이션은 대부분 `op.execute(<문자열>)`인데, 그것들은 값이 아니라
#: DDL이다. 여기는 사람이 읽는 문장(`freshness_note`)을 넣으므로 인용 규칙을 손으로
#: 지키지 않는다 — `sa.text`가 드라이버의 paramstyle까지 함께 처리한다.
_UPDATE = sa.text(
    """
    UPDATE feature.curated_sources AS source
       SET source_url = :url,
           update_cycle = :cycle,
           row_count = :row_count,
           freshness_note = :note,
           row_revision = source.row_revision + 1,
           observation_revision = source.observation_revision + 1,
           updated_at = now()
      FROM provider_sync.provider_datasets AS dataset
     WHERE dataset.provider_dataset_id = source.provider_dataset_id
       AND dataset.dataset_key = :dataset_key
    """
)


def _apply(*, url: str, cycle: str, row_count: int, note: str) -> None:
    result = op.get_bind().execute(
        _UPDATE,
        {
            "url": url,
            "cycle": cycle,
            "row_count": row_count,
            "note": note,
            "dataset_key": _DATASET_KEY,
        },
    )
    _LOGGER.info(
        "310_seoul_source_move: curated_sources %s행 갱신 (dataset_key=%s)",
        result.rowcount,
        _DATASET_KEY,
    )


#: receipt head CHECK 갱신. **graph의 모든 revision을 열거한다.**
_RECEIPT_HEAD_WIDEN: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals', '305_m05_relitigation_fence',"
    " '306_m02_manual_feature_purge', '307_m02_truncate_fence',"
    " '308_t39_provider_identities', '309_t39_feature_id_rekey',"
    " '310_seoul_source_move'))"
)

_UPGRADE_STATEMENTS: Final[tuple[str, ...]] = (
    "SET ROLE ktm_feature_schema_owner",
    _RECEIPT_HEAD_WIDEN,
)


def upgrade() -> None:
    # `SET ROLE`을 먼저 열고 **UPDATE까지 그 안에서** 한다. `feature.curated_sources`의
    # 소유자가 `ktm_feature_schema_owner`이고, migrator 롤에 그 표의 UPDATE 권한이
    # 있다고 가정하지 않는다 — 이 저장소의 롤은 전부 `rolinherit=false`다.
    #
    # **`RESET ROLE`을 하지 않는다.** 이 저장소의 마이그레이션은 전부 `SET ROLE
    # ktm_feature_schema_owner`를 켠 채로 끝나고, 그 상태에서 alembic이 자기
    # `UPDATE alembic_version`을 낸다. 접속 로그인 롤에는 그 표의 UPDATE 권한이
    # 없으므로, 롤을 되돌리면 마이그레이션 본문이 다 성공한 뒤 **버전 기록에서**
    # `permission denied for table alembic_version`으로 죽는다(2026-09-19 CI 실측 —
    # 통합 1,080건이 같은 원인으로 무너졌다).
    for statement in _UPGRADE_STATEMENTS:
        op.execute(statement)
    _apply(url=_NEW_URL, cycle="monthly", row_count=_NEW_ROW_COUNT, note=_NEW_NOTE)


_RECEIPT_HEAD_NARROW: Final[str] = (
    "ALTER TABLE ops.application_schema_operation_receipts"
    " DROP CONSTRAINT ck_application_schema_operation_receipts_head,"
    " ADD CONSTRAINT ck_application_schema_operation_receipts_head"
    " CHECK (destination_head IN ('300', '301_m03_import_children',"
    " '302_m03_child_issuance', '303_m05_payload_hash_domain',"
    " '304_m05_detector_manuals', '305_m05_relitigation_fence',"
    " '306_m02_manual_feature_purge', '307_m02_truncate_fence',"
    " '308_t39_provider_identities', '309_t39_feature_id_rekey'))"
)


def downgrade() -> None:
    # 되돌리면 **죽은 URL과 뒤집힌 문장이 돌아온다.** 그것이 맞다 — downgrade는
    # 이전 상태를 복원하는 것이지 더 나은 상태를 만드는 것이 아니다.
    op.execute("SET ROLE ktm_feature_schema_owner")
    op.execute(_RECEIPT_HEAD_NARROW)
    _apply(url=_OLD_URL, cycle="one_time", row_count=_OLD_ROW_COUNT, note=_OLD_NOTE)
    # upgrade와 같은 이유로 롤을 되돌리지 않는다.
