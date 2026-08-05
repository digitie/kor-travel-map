"""typed subtype 분해 ② — event·notice subtype (T-VN-35B, ADR-084).

0084와 같은 배타 arc 패턴(kind 상수 CHECK + ``(feature_id, kind)`` 복합 FK +
identity 사본 FK)을 event/notice에 적용하고, **시간 불변식을 DB 계약으로
승격**한다:

- ``ck_feature_events_period`` — ``starts_on <= ends_on``.
- ``ck_feature_notices_validity`` — ``valid_start_time <= valid_end_time``.
  현재는 DTO(Python)만 검사하고 DB는 임의 JSONB를 받는다(admin update 경로의
  ``detail = CAST(:detail AS jsonb)``는 shape 검증이 없다 — 실측).
- ``ck_feature_notices_severity`` — 0~5 범위.

35D의 실익이 여기서 나온다: notice read 필터가 쓰던
``detail->>'valid_end_time'`` 문자열 파싱(+ 비-ISO 값 방어용
``pg_input_is_valid`` cast)이 typed ``timestamptz`` 비교로 바뀐다.

backfill 대상은 event 1,246 + notice 145행(prod 실측)으로 즉시 끝난다.
비-ISO 시각 문자열은 NULL로 남기고 drift 관측이 잡는다(0084와 같은 규약).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0085_event_notice_subtypes"
down_revision: str | Sequence[str] | None = "0084_feature_place_subtype"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE feature.feature_events (
            feature_id varchar NOT NULL,
            feature_uuid uuid NOT NULL,
            kind varchar NOT NULL,
            event_kind varchar NOT NULL,
            starts_on date,
            ends_on date,
            timezone varchar NOT NULL DEFAULT 'Asia/Seoul',
            opening_hours jsonb,
            venue_name varchar,
            tel varchar,
            content_id varchar,
            content_type_id varchar,
            area_code varchar,
            sigungu_code varchar,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT pk_feature_events PRIMARY KEY (feature_id),
            CONSTRAINT ck_feature_events_kind CHECK (kind = 'event'),
            CONSTRAINT ck_feature_events_period
                CHECK (starts_on IS NULL OR ends_on IS NULL OR starts_on <= ends_on),
            CONSTRAINT fk_feature_events_feature_kind
                FOREIGN KEY (feature_id, kind)
                REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE,
            CONSTRAINT fk_feature_events_identity_pair
                FOREIGN KEY (feature_id, feature_uuid)
                REFERENCES feature.features (feature_id, feature_uuid)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        INSERT INTO feature.feature_events (
            feature_id, feature_uuid, kind, event_kind, starts_on, ends_on,
            timezone, opening_hours, venue_name, tel, content_id,
            content_type_id, area_code, sigungu_code, payload
        )
        SELECT
            f.feature_id,
            f.feature_uuid,
            f.kind,
            f.detail->>'event_kind',
            CASE
                WHEN f.detail->>'starts_on' ~ '^\\d{4}-\\d{2}-\\d{2}$'
                THEN (f.detail->>'starts_on')::date
            END,
            CASE
                WHEN f.detail->>'ends_on' ~ '^\\d{4}-\\d{2}-\\d{2}$'
                THEN (f.detail->>'ends_on')::date
            END,
            COALESCE(NULLIF(f.detail->>'timezone', ''), 'Asia/Seoul'),
            CASE
                WHEN jsonb_typeof(f.detail->'opening_hours') = 'object'
                THEN f.detail->'opening_hours'
            END,
            f.detail->>'venue_name',
            f.detail->>'tel',
            f.detail->>'content_id',
            f.detail->>'content_type_id',
            f.detail->>'area_code',
            f.detail->>'sigungu_code',
            COALESCE(f.detail->'payload', '{}'::jsonb)
        FROM feature.features AS f
        WHERE f.kind = 'event'
        """
    )
    # starts_on > ends_on인 기존 행이 있으면 CHECK 추가가 실패한다 — 그런 행은
    # DTO 검증을 통과한 적이 없으므로 정상 세계에서 0건이다. 실패하면 데이터
    # 결함이 드러난 것이므로 마이그레이션이 멈추는 편이 옳다(fail-close).
    op.execute(
        """
        CREATE INDEX idx_feature_events_period
            ON feature.feature_events (ends_on, starts_on)
            WHERE ends_on IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE feature.feature_notices (
            feature_id varchar NOT NULL,
            feature_uuid uuid NOT NULL,
            kind varchar NOT NULL,
            notice_type varchar NOT NULL,
            severity smallint,
            valid_start_time timestamptz,
            valid_end_time timestamptz,
            source_agency varchar,
            officer_name varchar,
            payload jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT pk_feature_notices PRIMARY KEY (feature_id),
            CONSTRAINT ck_feature_notices_kind CHECK (kind = 'notice'),
            CONSTRAINT ck_feature_notices_validity
                CHECK (
                    valid_start_time IS NULL
                    OR valid_end_time IS NULL
                    OR valid_start_time <= valid_end_time
                ),
            CONSTRAINT ck_feature_notices_severity
                CHECK (severity IS NULL OR severity BETWEEN 0 AND 5),
            CONSTRAINT fk_feature_notices_feature_kind
                FOREIGN KEY (feature_id, kind)
                REFERENCES feature.features (feature_id, kind) ON DELETE CASCADE,
            CONSTRAINT fk_feature_notices_identity_pair
                FOREIGN KEY (feature_id, feature_uuid)
                REFERENCES feature.features (feature_id, feature_uuid)
                ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        INSERT INTO feature.feature_notices (
            feature_id, feature_uuid, kind, notice_type, severity,
            valid_start_time, valid_end_time, source_agency, officer_name, payload
        )
        SELECT
            f.feature_id,
            f.feature_uuid,
            f.kind,
            f.detail->>'notice_type',
            CASE
                WHEN f.detail->>'severity' ~ '^[0-5]$'
                THEN (f.detail->>'severity')::smallint
            END,
            CASE
                WHEN pg_input_is_valid(f.detail->>'valid_start_time', 'timestamptz')
                THEN (f.detail->>'valid_start_time')::timestamptz
            END,
            CASE
                WHEN pg_input_is_valid(f.detail->>'valid_end_time', 'timestamptz')
                THEN (f.detail->>'valid_end_time')::timestamptz
            END,
            f.detail->>'source_agency',
            f.detail->>'officer_name',
            COALESCE(f.detail->'payload', '{}'::jsonb)
        FROM feature.features AS f
        WHERE f.kind = 'notice'
        """
    )
    op.execute(
        """
        CREATE INDEX idx_feature_notices_validity
            ON feature.feature_notices (valid_end_time, valid_start_time)
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS feature.feature_notices")
    op.execute("DROP TABLE IF EXISTS feature.feature_events")
