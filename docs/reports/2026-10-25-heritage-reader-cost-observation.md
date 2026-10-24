# 422 reader의 작은 SDK fixture 비용·관찰 메모리 결과

2026-10-25. source checkpoint `635fe9fb80dd4ea576b3d25b4ecfebae10cfdf80`(실행 SQL은3bfa와 동일), 감사 runner d430db6042b100f15fe8be66e0bc6059a568175369d3928cd7a847a843c09a55. 두 source 리뷰 뒤 1회만 실행했고50.59초에 종료했다. 제품·정책·운영값 변경과 추가 PG 재실행은0이다.

## 실제 범위

핀된 SDK53파일과 공개 Heritage converter로 만든 synthetic 정상3shape를 정본 legacy loader/identity claim/shadow/cutover로 저장했다. 고정64target template을 닫은 뒤 history0/10,000의 새 DB clone을 각각 만들었다. 10,000은 같은 dataset의 **관련 없는 새 current entity/head/record 묶음**이며, 동일 entity의 과거 version10,000개나 실제 전국 수집 데이터가 아니다. 정본 source SQL3개·chunk128로 추가하고 세 관계를 같은 방식으로 ANALYZE했다. 원64target의12관계 row hash와 source2370개 blob/mode·SDK53 전후는 같았다.

총54회 공개 reader 관찰은 양 history의1/3/8개×3회=18회와 prefix N1부터 최초 budget 실패까지의36회다. 반복 관찰을54개의 독립 입력 또는 새 pytest54개로 세지 않는다. 양쪽 모두 N1–17은 성공하고 **N18에서 처음 known budget_exceeded/items[]**였다. 이 값은 고정 raw/base 크기의 이 fixture에만 해당하며, 일반 reader의18개 제한이나 운영 dataset 수용량이 아니다. binary/encoded 중 어느 내부 guard가 먼저 반환했는지 이 원장만으로 추가 추정하지 않는다.

## 공개 호출 비용

3개 표본의 median이며 client의 read-only/timeout/role 확인·Python decode·관찰 overhead를 포함한다. client statement는 각5개로 SD 내부 SQL 개수가 아니다. PG CPU는 container CPU counter 차이로 background PG 비용도 포함한다. 첫 history0/N1 cold 호출은 wall67.160ms·PG54.914core-ms였고 숨기지 않았다.

| 무관 current 묶음 | target | wall median ms | PG CPU median core-ms |
| --- | ---: | ---: | ---: |
|0|1|17.763|10.548|
|0|3|30.897|23.194|
|0|8|79.869|66.978|
|10,000|1|22.405|16.026|
|10,000|3|38.365|30.190|
|10,000|8|93.337|79.317|

이는 한 owned lab의3표본 관찰이며 개선 비율·통계적 보장·ARM/운영 collector CPU 성과가 아니다. setup 약20.09초의10,000행 준비 비용은 reader 표본과 분리했다.

## plan 관찰

실제 service 공개 SD outer EXPLAIN은 양쪽 모두 Result 노드였다(6.198/12.297ms). 이것으로 함수 내부 계획을 추정하지 않는다. 별도로 실제 SD owner에서 exact source CASE SELECT를 직접 EXPLAIN한 **standalone mirror**는 다음과 같았다.

| source CASE mirror | history0 /10,000 execution ms | 관찰 node와 filter |
| --- | ---: | --- |
|source_entities|0.754 /2.383|Limit→Seq Scan, 제외63 /10,063행|
|source_entity_heads|0.138 /0.984|Limit→Seq Scan, 제외63 /10,063행|
|source_records|0.095 /2.427|Limit→Seq Scan, 제외63 /10,063행|

이 세 plan에는 Index 노드가 없었다. canonical index를 없앤 실험이 아니며 trigger·guard·plan_cache_mode·auto_explain 설정을 바꾸지 않았다. mirror는 PL/pgSQL SPI의 실제 nested/generic-cache 계획과 같은 증거가 아니고, 그 실행 시간을 공개 호출 시간에서 빼거나 더해 원인을 확정하지 않는다. 무관 current 묶음을 추가했을 때 scan/filter 비용이 함께 관찰됐다는 범위로 한정한다.

## 메모리와 정리 한계

양 history positive18회만의 최대 관찰값은 Python RSS183,386,112B/container441,573,376B였다. threshold를 포함한 전체54회에서는 각각183,681,024B/443,629,568B였다. container 값은 PG 전체·bootstrap/setup·검증·cache를 포함한다.20ms 주기 목표의 협력적 sampler는 동기 decode 사이의 순간 peak를 놓칠 수 있고 자체 overhead도 포함한다. Docker lifecycle max_usage는 이번 cgroup에서 모두null이므로 실제 lifecycle peak 값은 확보하지 못했다. cgroup peak를 reset하거나 이를 hard memory bound로 주장하지 않았다.

create 응답 직후 exactCID receipt를 fsync했고, canonical fixture finally와 부모 exactreceipt cleanup 뒤 정확 CID NotFound/UUID0을 확인했다. 두 clone은 backend0 뒤 제거했고 고유 source archive도 삭제했다. 이는 감사 도구의 정리 근거이며 제품 worker의 create/commit 불확실성 복구 보장이 아니다.

raw result SHA2563bb15cda8ff01b08450c02f76ee39eedf2c31ceb0a12f583c8913e763d57d939, outer645e31f0f14d4ff65def46086aa48da9a36dbeb25fe6fe61c1080a9ba935f172. 실제 약247k의 전체 source history, 큰 snapshot의 전체30초/원자 적용, SH collector/worker 동시성·재시작·운영 전파는 여전히 미증명이다.
