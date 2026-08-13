"""Feature core와 typed subtype의 code-level read projection.

T-VN-34C 이후 private SQL view는 남기지 않는다. public view는 migration이 소유하고,
non-public/admin/curation reader는 이 명시 join/column fragment로 같은 typed subtype
정본을 직접 조립한다. 이 모듈은 view alias나 legacy state/provenance를 제공하지 않는다.
"""

from __future__ import annotations

from typing import Final

__all__ = ["TYPED_FEATURE_DETAIL_COLUMNS_SQL", "typed_feature_detail_joins_sql"]


# ``f``는 callers가 core Feature relation에 붙이는 고정 alias다. typed subtype에
# 없는 price/weather는 빈 detail, route/area는 각 subtype geometry를 반환한다.
TYPED_FEATURE_DETAIL_COLUMNS_SQL: Final[str] = """
    COALESCE(r.geom, a.geom) AS geom,
    COALESCE(
        CASE f.kind
            WHEN 'place' THEN CASE WHEN p.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                'feature_id', f.feature_id,
                'place_kind', p.place_kind,
                'phones', to_jsonb(p.phones),
                'biz_number', p.biz_number,
                'license_date', to_jsonb(p.license_date),
                'business_hours', p.business_hours,
                'facility_info', p.facility_info,
                'reviews_link', p.reviews_link,
                'payload', p.payload
            ) END
            WHEN 'event' THEN CASE WHEN e.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                'feature_id', f.feature_id,
                'event_kind', e.event_kind,
                'starts_on', to_jsonb(e.starts_on),
                'ends_on', to_jsonb(e.ends_on),
                'timezone', e.timezone,
                'opening_hours', e.opening_hours,
                'venue_name', e.venue_name,
                'tel', e.tel,
                'content_id', e.content_id,
                'content_type_id', e.content_type_id,
                'area_code', e.area_code,
                'sigungu_code', e.sigungu_code,
                'payload', e.payload
            ) END
            WHEN 'notice' THEN CASE WHEN n.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                'feature_id', f.feature_id,
                'notice_type', n.notice_type,
                'severity', n.severity,
                'valid_start_time', to_jsonb(to_char(
                    n.valid_start_time AT TIME ZONE 'Asia/Seoul',
                    CASE WHEN EXTRACT(microsecond FROM n.valid_start_time)::bigint % 1000000 = 0
                         THEN 'YYYY-MM-DD\"T\"HH24:MI:SS\"+09:00\"'
                         ELSE 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+09:00\"' END
                )),
                'valid_end_time', to_jsonb(to_char(
                    n.valid_end_time AT TIME ZONE 'Asia/Seoul',
                    CASE WHEN EXTRACT(microsecond FROM n.valid_end_time)::bigint % 1000000 = 0
                         THEN 'YYYY-MM-DD\"T\"HH24:MI:SS\"+09:00\"'
                         ELSE 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"+09:00\"' END
                )),
                'source_agency', n.source_agency,
                'officer_name', n.officer_name,
                'payload', n.payload
            ) END
            WHEN 'route' THEN CASE WHEN r.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                'feature_id', f.feature_id,
                'route_type', r.route_type,
                'geometry_source', r.geometry_source,
                'geometry_status', r.geometry_status,
                'total_distance_meters', to_jsonb(r.total_distance_meters::text),
                'expected_duration_minutes', r.expected_duration_minutes,
                'difficulty', r.difficulty,
                'begin_name', r.begin_name,
                'begin_address', r.begin_address,
                'end_name', r.end_name,
                'end_address', r.end_address,
                'payload', r.payload
            ) END
            WHEN 'area' THEN CASE WHEN a.feature_id IS NULL THEN NULL ELSE jsonb_build_object(
                'feature_id', f.feature_id,
                'area_kind', a.area_kind,
                'boundary_source', a.boundary_source,
                'area_square_meters', to_jsonb(a.area_square_meters::text),
                'regulation_scope', a.regulation_scope,
                'administrative_office', a.administrative_office,
                'description', a.description,
                'payload', a.payload
            ) END
        END,
        '{}'::jsonb
    ) AS detail
"""


def typed_feature_detail_joins_sql(core_alias: str = "f") -> str:
    """``feature.features`` alias에 subtype을 명시 LEFT JOIN한다.

    Alias는 repository가 정적으로 공급하는 SQL identifier만 허용해 fragment를
    조합하는 reader가 injection boundary를 새로 만들지 않게 한다.
    """

    if not core_alias.isidentifier():
        raise ValueError("feature core alias must be a SQL identifier")
    return f"""
LEFT JOIN feature.feature_places AS p ON p.feature_id = {core_alias}.feature_id
LEFT JOIN feature.feature_events AS e ON e.feature_id = {core_alias}.feature_id
LEFT JOIN feature.feature_notices AS n ON n.feature_id = {core_alias}.feature_id
LEFT JOIN feature.feature_routes AS r ON r.feature_id = {core_alias}.feature_id
LEFT JOIN feature.feature_areas AS a ON a.feature_id = {core_alias}.feature_id
"""
