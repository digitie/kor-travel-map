# #1459 분류 override 3건 (회전 뒤 관리자 작업)

원천 업종이 비어 있어 provider 재투영으로는 고칠 수 없는 행이다(MCST 미디어 명소 `TYPE=""` → #1447 뒤 미분류).
admin field-override는 재적재에도 남는다(`feature.apply_provider_feature_field_patch`가 활성 override 필드를 건너뛴다).
**코드 변경 없음 — 운영 데이터 작업이다.** 회전(배포) 뒤 MCST 재적재가 끝난 다음에 한다.

| feature_id | 이름 | 지금 | 바꿀 값 |
|---|---|---|---|
| `01a1692f-42b3-7e37-9c50-3767c5e91ad8` | 성심당 본점 | `01000000` | `02011000`(식음 > 음식점 > 베이커리) |
| `01a1692b-dcca-760d-9cab-e2adbedc044b` | 그랜드 워커힐 서울 | `01000000` | `03010100`(숙박 > 호텔 > 관광호텔) |
| `01a1692e-993f-743d-ad05-0ebe7460dcdc` | 명우네수구레국밥 | `01000000` | `02010100`(식음 > 음식점 > 한식) |

2026-11-10 prod 읽기 전용 확인: 셋 다 `active`, `row_revision` 51·2·2(재적재 뒤 바뀐다 — 작업 직전에 다시 읽는다).

## 절차 (Feature마다)

1. 현재 `row_revision`을 읽는다 — **`GET /v1/admin/features/{feature_id}/revision`**의 `ETag`(strong, 예: `"76"`).
   상세 `GET /v1/admin/features/{feature_id}`에는 `ETag` 헤더가 없다 — 그 값을 쓰면 `If-Match`가 비어
   428 `PRECONDITION_REQUIRED`다(2026-11-11 운영 적용에서 실측, admin acceptance spec도 `/revision`을 쓴다).
2. `POST /v1/admin/features/{feature_id}/field-overrides`
   - 헤더: `If-Match: <ETag>`, `Idempotency-Key: <새 UUID>`, admin proxy 헤더(`X-Kor-Travel-Map-Admin-Proxy-Secret`, `X-Kor-Travel-Map-Actor`) — admin UI 컨테이너 안에서 보낸다.
   - 본문: `{"reason_code": "source_data_error", "values": {"core.category": "<바꿀 값>"}}`
3. 응답 200과 새 `ETag`를 확인하고, `GET`으로 `category`가 바뀐 것을 본다.

412면 `row_revision`이 바뀐 것이다 — 1부터 다시. 428이면 `If-Match`가 빠졌다(1의 경로 확인).

**적용 기록(2026-11-11, Map 4bd3059d):** MCST 재적재(run `3dd49343`) 뒤 세 행 모두 `00000000`이었다(#1447의 `TYPE=""` →
미분류가 첫 성공 재투영에서 반영). `/revision` ETag `"3"`·`"76"`·`"3"`로 셋 다 200, 재조회 category
`02011000`·`03010100`·`02010100` 확인. 되돌리기는 `POST …/field-overrides/revoke`
`{"reason_code": "…", "field_paths": ["core.category"]}`(같은 `If-Match`·`Idempotency-Key`·proxy 헤더가
필요하다. 최신 provider 값으로 돌아간다).
