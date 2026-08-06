"""typed subtype 분해 ① — 배타 arc + place subtype (T-VN-35A, ADR-085).

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

subtype이 단일 정본이 된다
--------------------------

core ``detail`` JSONB는 이 체인의 마지막(0086)에서 **제거된다** — subtype이
kind별 값의 유일한 정본이고, 응답이 요구하는 ``detail``은 0086이 만드는
``feature.features_detailed`` 뷰가 subtype에서 조립한다. 이중 쓰기·drift
관측이라는 우회 복잡도가 존재하지 않는다(ADR-085 결정 4).

0084는 그 체인의 첫 단계라 이 시점에는 core ``detail``이 아직 살아 있고,
backfill이 그것을 읽어 typed 컬럼을 채운다.

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

revision: str = "0085_feature_place_subtype"
down_revision: str | Sequence[str] | None = "0084_c6c_cancel_probe_fixtures"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def preflight_or_raise(label: str, probe_sql: str, remedy: str) -> None:
    """이관 불가 행을 **feature_id와 함께** 알리고 멈춘다.

    ``NOT NULL``/CHECK가 알아서 막아주긴 하지만, 그때 나오는 진단은
    ``null value in column "place_kind" violates not-null constraint``처럼
    **어느 행인지 말해주지 않는다**. api-entrypoint가 기동 때 upgrade를 돌리는
    구조(NEW-5)에서 그 실패는 곧 컨테이너 crash-loop이고, 운영자는 어디를
    고쳐야 하는지 알 수 없다. 선점검은 공짜고 진단을 행 단위로 만든다.

    조용히 건너뛰지 않는 이유: 건너뛴 행은 뒤이은 ``DROP COLUMN detail``로
    **복구 불가능하게** 사라진다(downgrade도 subtype에서 역조립하므로 되살릴
    수 없다). 실패는 되돌릴 수 있고 소실은 되돌릴 수 없다.
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
        "place rows without detail->>'place_kind' cannot become feature_places rows",
        "SELECT feature_id FROM feature.features "
        "WHERE kind = 'place' AND detail->>'place_kind' IS NULL",
        "Set a place_kind on these rows (PlaceDetail.place_kind is required), "
        "then re-run the upgrade.",
    )
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
    # detail JSONB → typed 컬럼.
    #
    # 자유 문자열이 들어올 수 있는 **선택** 필드는 방어적으로 판정한다
    # (license_date의 비-ISO 값은 NULL). 반면 **필수** 필드(place_kind)는
    # sentinel로 덮지 않고 그대로 넣는다 — NOT NULL 제약이 결측을 fail-close로
    # 잡는 편이 'unknown'이라는 가짜 값으로 "없음"과 "unknown이라는 값"을
    # 뭉개는 것보다 낫다. prod 실측: place_kind 729,972/729,972 존재.
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
            f.detail->>'place_kind',
            COALESCE(
                (
                    -- ``PlaceDetail.phones``는 max_length=3이고 writer도 3개로
                    -- 자른다 — backfill이 더 담으면 DTO가 말하는 것과 다른 행이
                    -- 다음 upsert까지 남는다.
                    SELECT array_agg(value #>> '{}')
                    FROM (
                        SELECT value
                        FROM jsonb_array_elements(f.detail->'phones') WITH ORDINALITY
                             AS t(value, ord)
                        WHERE jsonb_typeof(value) = 'string'
                        ORDER BY ord
                        LIMIT 3
                    ) AS capped
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
    # ``idx_features_opening_hours_keyset``만 subtype 컬럼 인덱스로 이관한다.
    #
    # ``idx_features_yt_channel_id``/``_playlist_id``(ADR-061)는 **이관하지
    # 않는다** — 둘 다 죽은 인덱스였음이 실측으로 드러났다:
    #
    # 1. 인덱스 식은 ``detail #>> '{kor_travel_concierge,youtube,channel_id}'``
    #    였는데 그 경로에 값이 있는 행은 prod에 **0건**이다. concierge가 쓰는
    #    실제 위치는 ``detail.payload.kor_travel_concierge…``(1,481행)다.
    # 2. 경로를 고쳐도 쓰이지 않는다. 이 값을 술어로 읽는 유일한 질의는
    #    curation source rule의 ``detail_selector``인데, 경로가 **런타임 값**
    #    (``ARRAY(SELECT jsonb_array_elements_text(...))``)이라 어떤 고정 식
    #    인덱스도 매칭될 수 없다. 나머지 참조는 전부 SELECT 목록의 추출이다.
    #
    # 죽은 인덱스를 경로만 바꿔 되살리면 73만 행에 쓰기 비용만 남는다. 상수
    # 경로로 조회하는 질의가 실제로 생기면 그때 만든다.
    op.execute(
        """
        CREATE INDEX idx_feature_places_opening_hours
            ON feature.feature_places (feature_id)
            WHERE business_hours IS NOT NULL
        """
    )


def downgrade() -> None:
    # 이 시점에는 core detail이 아직 정본이다(0086 downgrade가 이미 역조립해
    # 되돌려 놓았다) — 따라서 테이블만 지우면 무손실 복귀다.
    op.execute("DROP TABLE IF EXISTS feature.feature_places")
    op.execute(
        "ALTER TABLE feature.features DROP CONSTRAINT IF EXISTS uq_features_identity_kind"
    )
