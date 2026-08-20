# ADR-097 — 수동/Provider 중복 판정과 소비자 참조 재결합을 append-only paired protocol로 둔다

- **상태**: accepted
- **날짜**: 2026-08-21
- **결정자**: human(2026-08-21 paired cutover 선택), Codex 구현안
- **관련**: ADR-063, ADR-068, ADR-074, ADR-075, ADR-081, ADR-093, T-VN-M05

## 컨텍스트

M01~M04는 provider 밖에서 만든 Feature의 identity와 origin을 불변으로 보존한다. 이후
provider가 같은 실체를 발행하면 두 Feature가 공존한다. 기존 `ops.dedup_review_queue`는
provider끼리의 일반 후보 큐다. 수동 origin을 후보 입력으로 읽지 않고, 높은 점수에는 자동
master 선정·source link 이동·loser 상태 전이를 허용하므로 M05의 안전 경계에 쓸 수 없다.

수동 Feature가 PinVi 같은 외부 소비자의 참조 대상일 수도 있다. Map DB만 병합하면 소비자는
retired identity를 계속 보관한다. 반대로 Map이 소비자 DB를 직접 갱신하면 ADR-045의 OpenAPI
경계를 깨고, 네트워크 실패와 재시도에서 어느 쪽이 적용됐는지 증명할 수 없다.

## 결정

1. M05는 기존 generic dedup 큐·`merge_from_review()`·자동 master 선정 경로를 호출하지
   않는다. `manual_provider_dedup` 전용 candidate/decision/evidence relation과 writer를
   둔다. 점수가 기존 auto threshold 이상이어도 **항상 admin 판단 후보**일 뿐 자동 병합하지
   않는다.
2. candidate와 resolution은 UPDATE/DELETE/TRUNCATE 불가 append-only 증거다. 새 provider
   source head, Feature row revision 또는 scorer fingerprint가 달라지면 종전 episode에는
   `superseded` resolution만 추가하고 새 episode를 만든다. admin의 stale 요청은 409으로
   실패하며 어떤 resolution도 쓰지 않는다.
3. 병합의 survivor는 admin request에서 명시하고 M05는 provider Feature만 허용한다. source
   link 이동, generic loser cascade, provider Feature retire는 금지한다. `merged`는 manual
   Feature를 retire하고 immutable Map reconciliation event의 `rebind` action을 낸다.
   `manual_retired`는 manual Feature만 retire하고 `detach` event를 낸다. `kept`는 Feature를
   바꾸지 않는다. 모든 판단은 `AdminBFF`가 필수이며 `merged`/`manual_retired`는 DB writer보다
   먼저 destructive kill-switch도 통과해야 한다.
4. Map은 consumer-independent service contract로 event를 pull delivery하고 principal별 ack를
   append-only로 보존한다. `event_sequence`은 global feature-curation advisory fence 안에서만
   발급·commit하여 commit-visible 순서와 같다. service principal마다 mutable operational lease와
   acked-through prefix를 두어 한 worker만 가장 이른 미ack event를 처리하게 한다. 소비자는 자기
   DB transaction 안에서 참조 rebind/detach receipt와 영향 row를 commit한 뒤에만 그 event를
   ack한다. Map은 특정 소비자 이름을 식별자·role·환경변수·route에 넣지 않는다.
5. 이 protocol은 **paired cutover**다. Map resolution writer는 consumer 재결합 service spec을
   제공하고, 첫 consumer는 동일 spec을 vendoring하여 durable worker와 isolated paired test를
   통과한 release에서만 활성화한다. old Map/PinVi live evidence는 completion으로 재사용하지
   않는다.
6. 첫 consumer에서 curation receipt에 결박된 참조, partial feature pair, correction/closure의
   비종결 target은 M05가 바꾸지 않는다. durable blocked receipt만 남기고 unacked로 유지하여
   독립 curation/correction protocol이 해소하게 한다.

## 결과

- origin과 provider lineage를 보존한 채 사람만 survivor와 reference action을 결정한다.
- Map과 소비자가 각각 실패해도 append-only event/ack/receipt로 재시도 위치를 판별할 수 있다.
- 한 principal의 delivery는 순서·단일 worker·ack prefix가 보장되므로 sequence allocation과
  transaction commit 순서가 뒤집혀 참조 mutation이 역순 적용되는 경로를 없앤다.
- provider ETL의 source link·Feature lifecycle 정본은 generic dedup merge와 섞이지 않는다.
- role/ACL, backup root, OpenAPI vendor, consumer migration, paired live evidence가 한 release
  contract가 되므로 구현 범위는 작지 않다.

## 후속

- `0231_m05_manual_provider_dedup` migration(`down_revision =
  0230_tvn_m04_feature_request_queue`; C05→M01→M04 graph 다음), 전용
  procedures/ACL/bootstrap/restore/root를 구현한다.
- Map admin list/detail/decision 및 service event/ack contract를 추가하고 OpenAPI를 재동결한다.
- 첫 consumer가 durable reference reconciliation receipt와 exact vendor를 구현한다.
- 두 전문 적대 리뷰와 isolated Map/consumer live UI E2E가 모두 통과한 뒤에만 completion
  receipt를 만든다.
