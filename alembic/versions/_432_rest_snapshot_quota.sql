-- 실제215 typed 입력·context와 결과/후처리 각4KiB 예약을 근거로 한 Rest 한정 정책이다.
-- snapshot 행수이며 source 항목수와 다르다. global/Airport 한도·기존 사용량은 바꾸지 않는다.
-- 정확 active Rest DS가 없으면 row를 만들지 않아 등록의 미설정53000을 유지한다.
INSERT INTO ops.provider_snapshot_quota_limits(quota_key,max_bytes,max_rows)
SELECT provider_dataset_id,8388608,16 FROM provider_sync.provider_datasets
WHERE provider='kor-travel-transport' AND dataset_key='transport_rest_areas' AND is_active;
