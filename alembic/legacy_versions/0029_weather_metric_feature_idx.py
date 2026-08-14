"""weather_values temp-metric 부분 인덱스 (#499 nearest-temp 성능).

Revision ID: 0029_weather_metric_feature_idx
Revises: 0028_admin_auth_keys
Create Date: 2026-06-23

``build_weather_card``의 nearest-anchor 폴백(#498/#499)은 반경 내 가장 가까운
feature 중 weather(특히 기온 ``T1H``/``TMP``)를 가진 anchor를 찾는다. 재작성된
쿼리는 GiST(``idx_features_coord_5179_gist``) 후보 우선 + ``EXISTS`` 상관
서브쿼리로 weather 보유 여부를 확인한다. 기존 인덱스
(``idx_weather_values_feature_card`` = (feature_id, forecast_style, metric_key,
valid_at DESC) + ``brin_weather_values_valid_at``)는 ``metric_key IN
('T1H','TMP')`` 단독 조건을 sargable하게 만족하지 못한다(선두 컬럼이
feature_id). EXISTS 상관 서브쿼리가 ``feature_id = f.feature_id`` 로 들어오므로
feature_id 선두 부분 인덱스로 기온 보유 anchor 판정을 인덱스 only로 좁힌다.

MIGRATION ORDERING: 본 revision은 #520(admin login proxy + geo api key)이 먼저
merge되어 head가 ``0028_admin_auth_keys``가 된 뒤로 rebase되어, 이제 그 위에 선형으로
chain한다(down_revision = ``0028_admin_auth_keys``). 더 이상 0027 sibling이 아니다.
이후 KHOA 하드닝 PR(#517)은 이 revision(``0029_weather_metric_feature_idx``) 뒤로
``0030``으로 chain해야 한다(alembic multiple-heads 회피).

PROD 적용 가이드 — 운영 ``feature_weather_values``는 historically ≈30M row라
인덱스 생성이 테이블을 장시간 잠글 수 있다. 운영에서는 마이그레이션 트랜잭션 **밖**에서
``CREATE INDEX CONCURRENTLY``로 만들어 쓰기를 막지 않는 것을 권장한다::

    CREATE INDEX CONCURRENTLY idx_weather_values_metric_feature
    ON feature.feature_weather_values (feature_id)
    WHERE metric_key IN ('T1H', 'TMP');

본 마이그레이션은 alembic 트랜잭션 안에서 실행되므로(env.py가 트랜잭션으로 감쌈)
CONCURRENTLY를 쓸 수 없어 일반 ``CREATE INDEX``로 만든다(CI/테스트 parity). 운영
대규모 테이블에는 위 CONCURRENTLY 절차를 수동 적용한 뒤 이 마이그레이션을
``alembic stamp``로 건너뛰는 것을 고려하라.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0029_weather_metric_feature_idx"
down_revision: str | Sequence[str] | None = "0028_admin_auth_keys"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # nearest-anchor EXISTS의 기온(T1H/TMP) 보유 판정용 feature_id 선두 부분 인덱스.
    op.execute(
        """
        CREATE INDEX idx_weather_values_metric_feature
        ON feature.feature_weather_values (feature_id)
        WHERE metric_key IN ('T1H', 'TMP')
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS feature.idx_weather_values_metric_feature"
    )
