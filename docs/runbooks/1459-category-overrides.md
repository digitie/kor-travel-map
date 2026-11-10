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

1. 현재 `row_revision`을 읽는다 — `GET /v1/admin/features/{feature_id}`의 `ETag`.
2. `POST /v1/admin/features/{feature_id}/field-overrides`
   - 헤더: `If-Match: <ETag>`, `Idempotency-Key: <새 UUID>`, admin proxy 헤더(`X-Kor-Travel-Map-Admin-Proxy-Secret`, `X-Kor-Travel-Map-Actor`) — admin UI 컨테이너 안에서 보낸다.
   - 본문: `{"reason_code": "source_data_error", "values": {"core.category": "<바꿀 값>"}}`
3. 응답 200과 새 `ETag`를 확인하고, `GET`으로 `category`가 바뀐 것을 본다.

412면 `row_revision`이 바뀐 것이다 — 1부터 다시. 되돌리기는 `POST …/field-overrides/revoke`
`{"reason_code": "…", "field_paths": ["core.category"]}`(최신 provider 값으로 돌아간다).
