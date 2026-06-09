# 데이터 재적재 안전성 검증 — 충돌·결측·엎어쓰기 (2026-06-10)

> 목적: provider/offline 재적재(reload) 시 **(1)충돌(conflict) (2)결측(missing) (3)엎어쓰기
> (overwrite)** 이슈가 없는지 코드 레벨로 검증하고, 사용자 데이터 버전 모델(요건: v0,v1,v2,
> v3… 단조 증가 + 디폴트=최신)과의 정합을 확인한다. 기준: `origin/main` `HEAD` (#317 v0/v1
> 모델 포함). 인용은 실제 SQL/가드 코드 + `file:line`.

---

## 0. 한눈에 — 판정

| 영역 | 판정 | 근거 |
|------|------|------|
| **엎어쓰기(overwrite)** | ✅ 안전 | `_UPSERT_FEATURE_SQL` 전 컬럼이 `data_origin='user_request' AND data_version>0`이면 기존값 보존. source_record는 `DO NOTHING`. |
| **결측(missing)** | ✅ 안전 | snapshot cleanup이 `data_origin<>'user_request'` + `deleted_at IS NULL`만 soft-delete. cursor는 실패 시 미전진. |
| **충돌(conflict, 동시성)** | ✅ 안전 | feature/link `ON CONFLICT` + offline/import advisory lock + dedup queue `pending`만 갱신. |
| **dedup merge 영속성** | ⚠️ **F-1 (Medium)** | merge가 loser를 soft-delete만 하고 **재활성화 가드 미설정** → provider 재적재가 loser를 되살려 **중복 재생성**. |
| **버전 모델** | ⚠️ **F-2 (요건 gap)** | 현재 **binary v0/v1**(write가 `version=1` 하드코딩). 사용자 요건 **단조 v0,v1,v2,v3… + 디폴트=최신** 미충족. |

→ **즉각적 데이터 손실 위험은 없다**(엎어쓰기/결측은 가드됨). 단 **F-1(merge 후 중복 부활)**과
**F-2(버전 단조화)**는 후속 보강 대상.

---

## 1. 재적재 경로 개요

- **provider reload**: Dagster asset → `fetch_*`(provider client) → `*_to_bundles`(transform) →
  `feature_repo.load_bundles`(feature/source_record/source_link upsert) → (bulk면)
  `soft_delete_features_not_in_snapshot`. incremental(MOIS Step B)은 `provider_sync_state` cursor.
- **offline upload**: `POST /admin/offline-uploads`(저장+checksum) → `.../load`(advisory lock +
  `load_job_id` preclaim → `load_bundles`).
- **user edit**: `POST/PATCH/DELETE /v1/admin/features`(#317) → `features` effective row를
  `data_origin='user_request', data_version=1`로 갱신 + `feature_versions` snapshot.

---

## 2. 엎어쓰기 (overwrite) — ✅ 안전

`src/krtour/map/infra/feature_repo.py` `_UPSERT_FEATURE_SQL` `ON CONFLICT (feature_id) DO UPDATE`:
**모든 컬럼**(name/category/coord/address/detail/marker/status/deleted_at/…)이 다음 형태다.

```sql
name = CASE
  WHEN features.data_origin = 'user_request' AND features.data_version > 0
  THEN features.name        -- 사용자 편집 보존
  ELSE EXCLUDED.name        -- provider만 갱신
END,
... (전 컬럼 동일 패턴) ...
data_version = CASE
  WHEN features.data_origin = 'user_request' AND features.data_version > 0
  THEN features.data_version ELSE 0 END
```

- **provider 재적재가 사용자 편집 feature(`user_request`, v>0)를 절대 안 덮는다.** 가드 조건이
  `data_version > 0`이라 **v1뿐 아니라 v2,v3…도 보존**(단조 버전 호환).
- `status`/`deleted_at`은 추가로 `ops.feature_overrides`(`prevent_provider_reactivation`) 가드도 받음
  — 운영자 deactivate한 provider feature를 재활성화 안 함(`admin_feature_repo._UPSERT_STATUS_OVERRIDE_SQL`).
- `source_records`: `ON CONFLICT (source_record_key) DO NOTHING` — 원천 이력 불변(ADR-017).
- `source_links`: `ON CONFLICT (feature_id, source_record_key) DO UPDATE`(role/confidence/primary 갱신).

---

## 3. 결측 (missing) — ✅ 안전

`feature_repo._SOFT_DELETE_NOT_IN_SNAPSHOT_SQL`(bulk 재적재 후 snapshot에서 빠진 feature 정리):

```sql
UPDATE feature.features AS f
SET status = 'inactive', deleted_at = now(), updated_at = now()
WHERE f.deleted_at IS NULL
  AND COALESCE(f.data_origin, 'provider') <> 'user_request'   -- ★ 사용자 feature 제외
  AND f.feature_id IN (
    SELECT sl.feature_id FROM provider_sync.source_links sl
    JOIN provider_sync.source_records sr ON sr.source_record_key = sl.source_record_key
    WHERE sl.is_primary_source AND sr.provider=:provider AND sr.dataset_key=:dataset_key
      AND sr.source_entity_type=:source_entity_type
      AND NOT (sr.source_entity_id = ANY(:keys)))
```

- 재적재에서 안 오는 feature는 **hard delete가 아니라 soft-delete**(`inactive`+`deleted_at`, ADR-017).
- **사용자 생성/편집 feature는 `data_origin<>'user_request'` 필터로 제외** → 절대 안 지워짐.
- **이미 삭제된 feature는 `deleted_at IS NULL`로 제외** → 재처리/되살림 없음.
- **incremental cursor**(`sync_state_repo`): 적재 실패 시 cursor **미전진**(`record_sync_failure`) →
  다음 실행이 같은 범위 재개 → 누락 방지.
- consistency **F1**(`consistency.py`): `source_links` 없는 orphan `source_record` 탐지(ETL 누수 감지).

---

## 4. 충돌 (conflict, 동시성/중복) — ✅ 대부분 안전

- **feature/link upsert**: `ON CONFLICT` 결정적(위 §2).
- **offline upload load**: `try_advisory_lock(f"import:{provider}:{dataset}:{scope}")` + `load_job_id`
  preclaim → 같은 scope 동시 적재 직렬화, 2번째 시도는 `acquired=False`(무적재). checksum 재검증.
- **import job claim**: `FOR UPDATE SKIP LOCKED`(`jobs_repo`) — row 경합 회피.
- **dedup_review_queue**: `ON CONFLICT (feature_id_a, feature_id_b) DO UPDATE ... WHERE status='pending'`
  → 재스캔이 **결정 완료(accepted/rejected/merged/ignored) 행을 덮지 않음**(`dedup_repo`).
- **dedup merge**: `advisory_lock(f"dedup-merge:{review_key}")`로 직렬화(`dedup_review` router).

---

## 5. 발견사항 (findings)

### F-1 [Medium] dedup merge가 비영속 — 재적재가 loser를 되살려 중복 재생성
`merge_repo`는 병합 시 (1) loser source_link를 master로 이동, (2) **loser feature를 soft-delete**
(`status='deleted'`+`deleted_at`), (3) `feature_merge_history` 1행 INSERT 만 한다. **loser에
`feature_overrides`(prevent_provider_reactivation)를 만들지 않고**, `load_bundles`도
`feature_merge_history`를 참조하지 않는다.

- loser는 `data_origin='provider', data_version=0` → §2 가드 미적용.
- 해당 provider 재적재 시 loser의 source entity가 다시 와서 **동일 `make_feature_id` 결정적
  feature_id로 ON CONFLICT upsert** → `deleted_at←NULL`, `status←active`로 **부활** + source_link
  재생성 → master와 같은 원천을 가진 **중복 feature 재출현**.
- **영향**: 재적재마다 merge가 무효화될 수 있고, dedup 재스캔이 같은 쌍을 다시 큐잉(운영 부담).
- **권장**: 다음 중 하나 — (a) merge 시 loser에 `prevent_provider_reactivation` override 생성,
  (b) `load_bundles`가 `feature_merge_history`(loser→master)를 조회해 loser upsert를 master로
  redirect하거나 skip, (c) merge된 entity를 source 측에서 제외. (a)가 기존 override 가드와 가장
  일관적이고 변경 최소.

### F-2 [요건 gap] 버전 모델이 binary(v0/v1) — 사용자 요건은 단조(v0,v1,v2,v3… + 디폴트=최신)
현재 #317 구현:
- `feature.features.data_version` = **Integer, CHECK `>= 0`** (스키마는 단조 호환).
- 그러나 **write가 `data_version = 1` 하드코딩**(`admin_feature_repo` create/patch/delete L802/898/918),
  `feature_versions`도 `version=1` 고정 + `ON CONFLICT (feature_id, version) DO UPDATE` →
  **2차 편집이 v1 snapshot을 덮어씀(v2 없음)**. 즉 사용자 편집 히스토리가 1버전으로 collapse.
- effective row(`features`)는 항상 단일 user 버전 = 사실상 "최신"이지만, **버전 번호가 증가하지
  않아** "v0,v1,v2,v3 단조"와 "버전별 히스토리"를 만족하지 못한다.

**중요**: 재적재 가드(§2)는 이미 `data_version > 0` 조건이라 **단조화해도 그대로 동작**(v2,v3…도
보존). 즉 **읽기/보호 측은 호환**, **쓰기 측만 보강**하면 된다.

**권장 변경(후속 task)**:
1. 편집 시 `next = COALESCE((SELECT MAX(version) FROM feature.feature_versions WHERE feature_id=:fid),0)+1`.
2. `feature_versions`는 ON CONFLICT 없이 **새 version row INSERT**(provider v0 + user v1,v2,v3… 전 이력 보존).
3. `features.data_version = next`(effective = 항상 latest), `data_origin='user_request'`.
4. provider 재적재 가드(`> 0`)·snapshot cleanup(`<>'user_request'`)은 변경 불필요.
5. (선택) 버전 조회 API(`GET /v1/admin/features/{id}/versions`)·diff·revert.

---

## 6. 잔여 주의 (비차단)

- **offline upload 파일 중복**: storage 레벨 unique 없음 — 같은 파일 재업로드는 새 `upload_id`.
  load 멱등은 advisory lock + checksum이 담당하나, **중복 업로드 자체**는 `ops.offline_uploads`
  checksum으로 운영자가 사전 판별 필요.
- **F5~F8 consistency 미구현**(`consistency.py` Phase 2) — 재적재 후 cross-provider 결측/중복
  자동 감지는 T-212e/후속에서 보강.

---

## 7. 결론

재적재의 **충돌·결측·엎어쓰기 기본 안전망은 갖춰져 있다**(v0/v1 가드 + soft-delete + advisory
lock + ON CONFLICT 규약). 실질 보강 2건:
- **F-1**: dedup merge 영속화(재적재 부활 차단).
- **F-2**: 사용자 버전 단조화(v0,v1,v2,v3… + 디폴트=최신) — 스키마는 이미 호환, 쓰기 로직만 보강.

*작성: Claude (2026-06-10). 기준 `origin/main`. 코드 인용은 실제 SQL/가드.*
