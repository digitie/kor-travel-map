"""typed subtype 분해 ② — event·notice subtype (T-VN-35B, ADR-084).

0084와 같은 배타 arc 패턴(kind 상수 CHECK + ``(feature_id, kind)`` 복합 FK +
identity 사본 FK)을 event/notice에 적용하고, **시간 불변식을 DB 계약으로
승격**한다:

- ``ck_feature_events_period`` — ``starts_on <= ends_on``.
- ``ck_feature_notices_severity`` — 0~5 범위. 현재는 DTO(Python)만 검사하고
  DB는 임의 JSONB를 받는다(admin update 경로의
  ``detail = CAST(:detail AS jsonb)``는 shape 검증이 없다 — 실측).

**``valid_start_time <= valid_end_time`` CHECK는 두지 않는다** (설계 판단).
그 순서를 어기는 상태가 **실재**하기 때문이다: provider가 미래 발효 공고를
공표한 뒤 발효 전에 feed에서 내리면, lifecycle이 `valid_end_time=철회시각`을
쓰면서 `end < start`가 된다(KREX notice ETL에서 실측 재현 —
`start=2026-07-13, end=2026-06-02`). 이는 "발효 전에 철회됨"이라는 정당한
사실이지 데이터 결함이 아니다. 실재하는 상태를 금지하는 제약은 nuance를
장애로 바꾼다 — 정상 ETL asset 전체가 실패했다.

`NoticeDetail`에도 순서 검증은 **없다**(실측 확인 — `_check_aware`만 있다).
없는 것이 맞다. `valid_end_time`은 "선언된 종료 예정"이 아니라 **"효력이
끝난 시각"**이고, 철회는 그 시각을 발효 전으로 앉힌다. 두 필드가 같은 축의
시작/끝이 아니므로 순서를 강제할 근거 자체가 없다. DB 층 표현은 T-VN-37A의
`tstzrange`가 맡는다 — 철회된 공고는 empty range가 되어 "효력 구간이 없다"를
정확히 표현한다. read 필터는 `valid_end_time <= now()`이므로 순서와 무관하게
옳게 동작한다(철회 즉시 숨김).

대비되는 것이 `ck_feature_events_period`다 — `EventDetail`이
`ends_on >= starts_on`을 **실제로** 강제하므로(`model_validator`, 실측 확인)
CHECK는 모든 write 경로가 이미 만족하는 불변식의 DB 표현일 뿐이다. 즉 CHECK는
"DTO 불변식이 있는 곳에만" 둔다.

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


def preflight_or_raise(label: str, probe_sql: str, remedy: str) -> None:
    """이관 불가 행을 feature_id와 함께 알리고 멈춘다 (근거는 0084의 같은 함수).

    revision 파일은 서로를 import하지 않는다 — 동결 artifact라 자기 완결이
    낫다(공유 helper가 나중에 바뀌면 과거 revision의 의미가 바뀐다).
    """
    quoted_label = label.replace("'", "''")
    quoted_remedy = remedy.replace("'", "''")
    op.execute(
        f"""
        DO $preflight$
        DECLARE
            offenders text;
            total bigint;
        BEGIN
            SELECT count(*) INTO total FROM ({probe_sql}) AS probe;
            IF total = 0 THEN
                RETURN;
            END IF;
            SELECT string_agg(feature_id, ', ' ORDER BY feature_id)
              INTO offenders
              FROM (
                  SELECT feature_id FROM ({probe_sql}) AS probe
                  ORDER BY feature_id LIMIT 20
              ) AS sample;
            RAISE EXCEPTION
                'T-VN-35 preflight: % (% row(s)); sample: %',
                '{quoted_label}', total, offenders
              USING HINT = '{quoted_remedy}';
        END
        $preflight$;
        """
    )


def upgrade() -> None:
    preflight_or_raise(
        "event rows without detail->>'event_kind' cannot become feature_events rows",
        "SELECT feature_id FROM feature.features "
        "WHERE kind = 'event' AND detail->>'event_kind' IS NULL",
        "Set an event_kind on these rows (EventDetail.event_kind is required), "
        "then re-run the upgrade.",
    )
    preflight_or_raise(
        "notice rows without detail->>'notice_type' cannot become feature_notices rows",
        "SELECT feature_id FROM feature.features "
        "WHERE kind = 'notice' AND detail->>'notice_type' IS NULL",
        "Set a notice_type on these rows (NoticeDetail.notice_type is required), "
        "then re-run the upgrade.",
    )
    # ck_feature_events_period가 걸릴 행도 같은 이유로 미리 짚는다 — EventDetail이
    # ends_on >= starts_on을 강제하므로 정상 세계엔 없지만, 검증 없는 admin
    # detail 경로가 남긴 행이 있으면 여기서 행 단위로 드러난다.
    preflight_or_raise(
        "event rows with starts_on > ends_on violate ck_feature_events_period",
        "SELECT feature_id FROM feature.features "
        "WHERE kind = 'event' "
        "AND detail->>'starts_on' ~ '^\\d{4}-\\d{2}-\\d{2}$' "
        "AND detail->>'ends_on' ~ '^\\d{4}-\\d{2}-\\d{2}$' "
        "AND (detail->>'starts_on')::date > (detail->>'ends_on')::date",
        "Fix the period on these rows (EventDetail enforces ends_on >= starts_on), "
        "then re-run the upgrade.",
    )
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
    # 공개 festival 경로는 ``starts_on``으로 범위·keyset·ORDER BY를 건다
    # (public_views_repo). 선두 컬럼이 ``ends_on``이면 그 어느 것도 못 탄다.
    # 부분 조건(``ends_on IS NOT NULL``)도 두지 않는다 — 질의가 명시적으로
    # ``ends_on IS NULL``을 포함하므로, 그 행을 빼는 인덱스는 쓸 수 없다.
    op.execute(
        """
        CREATE INDEX idx_feature_events_period
            ON feature.feature_events (starts_on, ends_on)
        """
    )

    op.execute(
        """
        CREATE INDEX idx_feature_events_opening_hours
            ON feature.feature_events (feature_id)
            WHERE opening_hours IS NOT NULL
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
