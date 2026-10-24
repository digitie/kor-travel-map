# ADR115 API 읽기 snapshot inventory 및 구현 경계

기준은 `2a53dce7cabfa594ce2a699550ae5dafe78b37ad`다. T-CWRITE01/04 중 다중 SELECT의 읽기 경계만 소유한다. 실제 동시 쓰기/잠금 세분화·정책 활성화·migration·운영 배포를 완료했다고 주장하지 않는다.

기본 `get_session`은 READ COMMITTED이고 auth/쓰기·lease가 공유한다. 이를 일괄 변경하지 않고 새 `get_read_snapshot_session`이 독립 세션에서 **최초 데이터 SELECT 전** read-only REPEATABLE READ를 설정한다. 이미 시작된 트랜잭션의 isolation 변경은 없다. 모든 repo 호출과 응답 조립까지 같은 세션이며 별도 HTTP page 간 snapshot은 약속하지 않는다.

## 다중 SQL 순수 reader — 구현 대상

| router | handler | 실제 조회 호출 경계 |
|---|---|---|
| `admin_features.py` | `get_admin_feature_price` | `resolve_feature_ref_or_error, _admin_feature_exists_or_404, price_repo.build_price_card` |
| `admin_features.py` | `get_feature_creation_provenance_route` | `resolve_feature_ref_or_error, get_admin_manual_feature_provenance` |
| `admin_features.py` | `get_feature_detail_route` | `resolve_feature_ref_or_error, get_admin_feature_detail, curation_repo.list_curation_items_by_feature_ids` |
| `admin_features.py` | `get_feature_revision_route` | `resolve_feature_ref_or_error, get_feature_row_revision` |
| `admin_features.py` | `list_feature_state_transitions_route` | `resolve_feature_ref_or_error, get_feature_row_revision, list_admin_feature_state_transitions` |
| `curations.py` | `get_admin_curation_collection` | `curation_repo.get_curation_collection` |
| `curations.py` | `get_admin_curation_import_batch` | `curation_repo.get_curation_import_batch` |
| `curations.py` | `get_public_curation_collection` | `curation_repo.get_curation_collection` |
| `curations.py` | `get_public_feature_curations` | `resolve_feature_ref_or_error, curation_repo.get_feature_curation_group` |
| `curations.py` | `list_admin_curation_quarantine_items` | `curation_repo.list_curation_quarantine_items` |
| `curations.py` | `list_admin_theme_candidate_transitions` | `curation_candidate_repo.list_theme_candidate_transitions, curation_candidate_repo.get_theme_candidate` |
| `curations.py` | `list_admin_theme_candidates` | `curation_candidate_repo.list_theme_candidates, feature_identity.canonical_feature_id_for_filter` |
| `curations.py` | `list_public_curation_groups` | `curation_repo.list_feature_curation_groups` |
| `dedup_review.py` | `get_review_detail` | `get_dedup_review_detail` |
| `dedup_review.py` | `list_reviews` | `list_dedup_reviews, feature_identity.legacy_id_for_filter` |
| `enrichment_review.py` | `get_review_detail` | `get_enrichment_review_detail` |
| `enrichment_review.py` | `list_reviews` | `list_enrichment_reviews, feature_identity.legacy_id_for_filter` |
| `features.py` | `get_area_contained_features` | `resolve_feature_ref_or_error, _public_feature_row_or_404, feature_repo.features_contained_in_area` |
| `features.py` | `get_feature` | `resolve_feature_ref_or_error, _public_feature_row_or_404, curation_repo.list_curation_items_by_feature_ids` |
| `features.py` | `get_feature_observation_history` | `resolve_feature_ref_or_error, observation_repo.get_observation_history` |
| `features.py` | `get_feature_price` | `resolve_feature_ref_or_error, _public_feature_row_or_404, price_repo.build_price_card` |
| `features.py` | `get_feature_price_snapshot` | `resolve_feature_ref_or_error, _public_feature_row_or_404, price_repo.build_price_snapshot` |
| `features.py` | `get_feature_sources` | `resolve_feature_ref_or_error, observation_repo.get_current_observations` |
| `features.py` | `get_features_batch` | `feature_identity.resolve_feature_identities_bulk, feature_repo.get_service_feature_batch_items` |
| `features.py` | `list_features_nearby_by_target` | `get_poi_cache_target_by_key, feature_repo.features_nearby_poi_cache_target` |
| `features.py` | `search_public_features` | `feature_repo.search_features` |
| `public_views.py` | `get_public_beach` | `resolve_feature_ref_or_error, public_views_repo.get_public_beach` |
| `public_views.py` | `get_public_festival` | `resolve_feature_ref_or_error, public_views_repo.get_public_festival` |
| `public_views.py` | `list_public_festivals_monthly` | `public_views_repo.list_public_festivals_monthly` |

`price_repo._build_price_card`는 current/history 두 SELECT, admin detail은 본문/files/전이 등 여러 SELECT, dedup/enrichment 목록은 count/items, 상세는 review와 참조 Feature를 분리 조회한다. curation collection/group/import/quarantine은 metadata/count/item 또는 Feature 보조 조회를 분리한다. festival monthly는 count/items가 분리된다. 단일 SQL의 내부 CTE·window는 이미 statement snapshot이므로 그대로다.

## 분류하여 기존 경계를 유지하는 경로

- features bbox/bounds/nearby, admin bbox/list, curated theme/source/rule, curation service snapshot/cutover export: 해당 reader는 한 business SELECT로 조립한다. 쓰기나 세분화가 필요하지 않다.
- curation list/단일 item/candidate 등 단일 SELECT 경로는 그대로다. 선택적 identity 필터가 추가 SQL을 하는 `list_admin_theme_candidates`는 위 대상이다.
- auth, mutation POST/PUT/PATCH/DELETE, GET lease/ack/stream과 read/write 혼합 서비스는 `get_session` 및 기존 transaction을 유지한다. 운영/파일/로그/외부 HTTP 관측은 Feature snapshot과 같은 시점이라고 약속하지 않는다.
- admin files/issues, cache target streams, feature request/reference reconciliation, ops dataset/pipeline 등은 전체 API inventory의 추가 분류 대상으로 남아 있다. 이 PR의 위 범위만으로 전체 T-CWRITE01/04 완료를 표시하지 않는다.

## 검증 계획 및 상태

독립 두 PG 세션의 writer commit을 실제 repo SELECT 사이에 주입하여 identity/body, target/nearby, price current/history, admin 또는 curation count/items의 old/old 또는 new/new를 확인한다. read-only/RR 실제 SHOW, 예외 rollback·pool 반환, 기존 mutation 세션의 쓰기 가능성을 별도 검증한다. 구현/단위/PG/CI/두 리뷰/운영 수용은 각 gate 결과를 나누어 기록한다. 현재 실제 운영 호출은 0회며 모든 gate는 진행 중이다.
