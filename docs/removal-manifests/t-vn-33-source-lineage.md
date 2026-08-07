# T-VN-33C source lineage legacy removal manifest

- 상태: T-VN-33 final schema에서 물리 삭제
- 물리 삭제 task: T-VN-33C
- 작성일: 2026-08-06

이 문서는 T-VN-33C가 final schema에서 삭제한 legacy source-lineage 객체의 전수
목록이다. 서비스 전 단계에서는 intermediate data·downgrade를 보전하지 않는다.
따라서 normal reader·writer·DTO의 참조가 0임을 static gate로 확인한 뒤 동일 PR의
0091 migration(`_drop_legacy_columns`)에서 삭제하고, 새 DB는 ETL 재실행으로 만든다.

## 1. 제거 대상 DB 객체

| 관계 | legacy 열·제약·index | 대체 정본 | C fence |
|---|---|---|---|
| `provider_sync.source_entities` | `provider`, `dataset_key`, `current_source_record_key`; `uq_source_entities_identity`; `fk_source_entities_current_record`; `idx_source_entities_current_record` | `provider_dataset_id` FK + `uq_source_entities_provider_identity`, `source_entity_heads` | 새 writer의 legacy 열 write 거부, normal reader의 current pointer 조인 거부 |
| `provider_sync.source_records` | `provider`, `dataset_key`, `source_entity_type`, `source_entity_id`, `source_version`, `raw_name`, `raw_address`, `raw_longitude`, `raw_latitude`, `last_seen_at`, `expires_at`; `uq_source_records`; `idx_source_records_provider_dataset_entity`; `idx_source_records_last_seen_at_brin`; `idx_source_records_expires_at`; legacy `idx_source_records_entity_history` | entity FK + immutable raw snapshot, `source_entity_heads.observed_at/expires_at`, 새 history index | 새 writer의 모든 legacy 열 write 거부, `UPDATE` 전체 거부 |
| `provider_sync.source_links` | `is_primary_source`; boolean predicate `idx_source_links_primary` | `source_role='primary'` predicate index | boolean 직접 write 거부, normal reader의 boolean predicate 거부 |

## 2. cutover implementation의 필수 산출물

1. Alembic C revision은 raw record immutable trigger와 dataset active guard를 적용한 뒤
   위 legacy 열·제약·index를 물리 삭제한다.
2. source lineage normal reader는
   `source_entities → provider_datasets`, `source_entity_heads → source_records`,
   `source_links.source_role`만 사용한다. 이 목록의 legacy 열은 migration forensic
   preflight와 T-VN-39 제거만 읽을 수 있다.
3. static legacy-reader gate의 production source 허용 목록은 historical migration,
   이 manifest와 migration fixture뿐이다. provider input DTO의 raw source 값은 storage
   열이 아니라 `raw_data` envelope 안에만 남길 수 있으며 SQL column reference는 허용하지 않는다.
4. 구현 때 제거·대체한 repository/query는 아래 inventory의 각 파일에서 0건이어야 한다.
   신규 파일 또는 동적 SQL은 query test가 same legacy identifier를 차단한다.

## 3. repository/query inventory

다음은 2026-08-06 baseline의 normal path다. T-VN-33B는 모두 정규 조인으로 전환한다.

- `src/kortravelmap/infra/feature_repo.py`
- `src/kortravelmap/infra/observation_repo.py`
- `src/kortravelmap/infra/admin_feature_repo.py`
- `src/kortravelmap/infra/curated_repo.py`
- `src/kortravelmap/infra/dedup_refresh_repo.py`
- `src/kortravelmap/infra/public_views_repo.py`
- `src/kortravelmap/infra/scope_repo.py`
- `src/kortravelmap/infra/weather_repo.py`
- `src/kortravelmap/infra/merge_repo.py`
- `src/kortravelmap/infra/consistency.py`
- `src/kortravelmap/infra/enrichment_review_repo.py`
- `packages/kor-travel-map-api/src/kortravelmap/api/routers/admin_features.py`
- `packages/kor-travel-map-api/src/kortravelmap/api/routers/admin_issues.py`
- `packages/kor-travel-map-api/src/kortravelmap/api/routers/dedup_review.py`
- `packages/kor-travel-map-api/src/kortravelmap/api/routers/features.py`

## 4. T-VN-33 acceptance

- manifest의 모든 column/constraint/index가 0091 뒤 물리적으로 존재하지 않는다.
- production source static gate와 catalog query에서 forbidden identifier가 0건이다.
- final-schema 새 DB에서 ETL 재실행으로 data를 만들고 source record/history/head/link
  integrity와 active guard를 다시 검증한다. 이전 DB data 보존 또는 downgrade는 acceptance
  조건이 아니다.
