"""typed subtype 분해 ① — 배타 arc + place subtype (T-VN-35A, ADR-084).

무엇을 만드나
-------------

1. ``uq_features_identity_kind (feature_id, kind)`` — subtype 배타 arc의 참조
   대상. 이것만으로는 아무 것도 강제하지 않고, subtype의 복합 FK가 참조할 수
   있게 만드는 전제다.
2. ``feature.feature_places`` — place 전용 typed 컬럼(dto ``PlaceDetail``의
   DB 대응물) + 배타 arc FK + identity 사본 FK.

배타 arc가 강제하는 것 (35B "혼합 kind row 거부"의 선언적 구현)
---------------------------------------------------------------

- subtype 행은 ``kind = 'place'`` 상수 CHECK를 갖고 ``(feature_id, kind)``로
  core를 참조한다. core의 kind는 단일 값이므로 **한 feature는 최대 한 개의
  subtype 테이블에만 존재**한다(다른 kind의 subtype INSERT는 FK 위반).
- subtype 행이 있는 동안 **core ``kind`` 변경이 FK 위반으로 막힌다**. 현재
  provider upsert의 ``kind = EXCLUDED.kind``가 kind를 조용히 바꿀 수 있던
  구멍(실측 확인)이 DB 계약으로 닫힌다. prod 실측: ``feature_versions``
  731,766행 중 kind 전이 이력 **0건** — 기존 운영을 깨지 않는다.
- ``(feature_id, feature_uuid)`` 복합 FK는 0083 ``feature_aliases``와 같은
  identity 사본 일치 계약이다(CASCADE — core 행이 지워지면 subtype도 소멸).

shadow 단계 — ``detail``은 유지한다
-----------------------------------

core ``detail`` JSONB를 이 단계에서 **제거하지 않는다**. 응답 계약이 그대로
노출하고(FeatureDetailResponse.detail·PinVi 소비), 제거는 T-VN-39 removal
manifest 소관이다(33C/34C/38C와 같은 규약). subtype은 typed 사본이며 writer가
같은 트랜잭션에서 둘 다 갱신하고, drift는 관측(``count_subtype_drift``)이 0을
고정한다. 롤백도 이 성질 덕에 안전하다 — reader만 되돌리면 된다.

backfill 실행 시간 (실측)
-------------------------

prod 복원본(729,972 place 행)에서 ``INSERT … SELECT`` **11.1초**, 사본 FK 추가
2.9초, 인덱스 3종 0.3초 — 합계 ~15초. api-entrypoint healthcheck 창(start_period
20s + 10s×20 = 220s, NEW-5 런북)에 여유가 크므로 분할·수동 선실행이 불필요하다.

단일 트랜잭션이다(0083 선례 — autocommit_block 중간 커밋은 재시도 불가한
반쪽 상태를 만든다). 실패하면 통째로 되돌아간다.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0084_feature_place_subtype"
down_revision: str | Sequence[str] | None = "0083_nonderived_uuid_generator"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE feature.features
          ADD CONSTRAINT uq_features_identity_kind UNIQUE (feature_id, kind)
        """
    )
    op.execute(
        """
        CREATE TABLE feature.feature_places (
            feature_id varchar NOT NULL,
            feature_uuid uuid NOT NULL,
            kind varchar NOT NULL,
            place_kind varchar NOT NULL,
            phones text[] NOT NULL DEFAULT '{}'::text[],
            biz_number varchar,
            license_date date,
            business_hours jsonb,
            facility_info jsonb NOT NULL DEFAULT '{}'::jsonb,
            reviews_link jsonb NOT NULL DEFAULT '{}'::jsonb,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT pk_feature_places PRIMARY KEY (feature_id),
            CONSTRAINT ck_feature_places_kind CHECK (kind = 'place'),
            CONSTRAINT fk_feature_places_feature_kind
                FOREIGN KEY (feature_id, kind)
                REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE,
            CONSTRAINT fk_feature_places_identity_pair
                FOREIGN KEY (feature_id, feature_uuid)
                REFERENCES feature.features (feature_id, feature_uuid)
                ON DELETE CASCADE
        )
        """
    )
    # detail JSONB → typed 컬럼. 자유 문자열이 들어올 수 있는 필드는 방어적으로
    # 판정한다(license_date의 비-ISO 값은 NULL — backfill이 통째로 실패하는 것보다
    # drift 관측이 잡아내게 두는 편이 안전하다).
    op.execute(
        """
        INSERT INTO feature.feature_places (
            feature_id, feature_uuid, kind, place_kind, phones, biz_number,
            license_date, business_hours, facility_info, reviews_link, payload
        )
        SELECT
            f.feature_id,
            f.feature_uuid,
            f.kind,
            COALESCE(f.detail->>'place_kind', 'unknown'),
            COALESCE(
                (
                    SELECT array_agg(value #>> '{}')
                    FROM jsonb_array_elements(f.detail->'phones')
                ),
                '{}'::text[]
            ),
            f.detail->>'biz_number',
            CASE
                WHEN f.detail->>'license_date' ~ '^\\d{4}-\\d{2}-\\d{2}$'
                THEN (f.detail->>'license_date')::date
            END,
            CASE
                WHEN jsonb_typeof(f.detail->'business_hours') = 'object'
                THEN f.detail->'business_hours'
            END,
            COALESCE(f.detail->'facility_info', '{}'::jsonb),
            COALESCE(f.detail->'reviews_link', '{}'::jsonb),
            COALESCE(f.detail->'payload', '{}'::jsonb)
        FROM feature.features AS f
        WHERE f.kind = 'place'
        """
    )
    # detail 표현식 인덱스 3종을 subtype 컬럼 인덱스로 이관한다(core 쪽 원본은
    # detail을 유지하는 동안 함께 남긴다 — T-VN-39에서 detail과 같이 정리).
    op.execute(
        """
        CREATE INDEX idx_feature_places_opening_hours
            ON feature.feature_places (feature_id)
            WHERE business_hours IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_feature_places_yt_channel
            ON feature.feature_places
               ((payload #>> '{kor_travel_concierge,youtube,channel_id}'))
            WHERE (payload #>> '{kor_travel_concierge,youtube,channel_id}') IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE INDEX idx_feature_places_yt_playlist
            ON feature.feature_places
               ((payload #>> '{kor_travel_concierge,youtube,playlist_id}'))
            WHERE (payload #>> '{kor_travel_concierge,youtube,playlist_id}') IS NOT NULL
        """
    )


def downgrade() -> None:
    # subtype은 shadow 사본이라 무손실 복귀다 — core detail이 정본을 계속 갖고
    # 있으므로 테이블만 지우면 된다.
    op.execute("DROP TABLE IF EXISTS feature.feature_places")
    op.execute(
        "ALTER TABLE feature.features DROP CONSTRAINT IF EXISTS uq_features_identity_kind"
    )
