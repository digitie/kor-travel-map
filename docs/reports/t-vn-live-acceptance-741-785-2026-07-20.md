# T-VN-04A·58 n150 targeted live 인수 설계

## 1. 목적과 실행 경계

이 문서는 issue #741과 #785의 마지막 완료 조건인 production live UI 증거를
독립 Playwright lane으로 고정한다. 두 이슈의 API·UI 구현은 이미 `main`에 병합됐고,
이번 변경은 운영 데이터를 소유권 없이 빌리거나 strict C7 복구 경계를 넓히지 않는다.

- strict `T-ADM-C7` runner에는 feature mutation을 추가하지 않는다.
- 새 lane은 `E2E_ADMIN_FEATURE_ACCEPTANCE_WRITE=1`을 별도로 요구하고 serial 1-worker로만
  실행한다.
- 상태 marker와 correction write fixture는 실행별 고유 `user_request::...` feature ID와
  사유를 사용한다. weather/price kind fixture는 admin change API가 place/event만 허용하므로
  별도 fixture helper가 고유 ID로 직접 만들되, mutation 전 root-owned journal에 ID와 복구
  단계를 기록한다.
- 각 browser 시나리오는 `try/finally`에서 서버의 **현재 raw strong ETag**를 다시 읽은 뒤
  DELETE 변경 요청을 만들고 승인한다. cleanup의 조회·요청·승인·삭제 확인 중 하나라도
  실패하면 원래 테스트 결과와 무관하게 실패한다.
- 운영의 기존 Feature는 수정하지 않는다. 테스트가 만든 pending 요청도 실패 경로에서
  reject 또는 approve-delete 순서로 종결한다.
- fixed state root의 `BLOCKED.json`은 Playwright container가 시작되기 전에 만들어진다.
  journal은 `run_id`와 그 값에서 결정적으로 파생한 owned Feature ID 6개를 함께 기록한다.
  정상 cleanup·residual audit·evidence 보존이 모두 끝난 뒤에만 제거한다. SIGKILL 등으로
  남으면 같은 `run_id`의 recovery-only 실행 없이는 새 run을 거부한다.
- executor image와 실행 중인 Map API/UI image의 source revision이 같은 exact commit이고 두
  runtime이 모두 healthy인지 mutation 전에 fail-close로 확인한다.
- runner/helper/state helper는 고정 root snapshot의 exact 4-file set, ancestor ownership/mode, manifest
  commit과 SHA256을 통과해야 한다. executor create/start/wait/remove phase는 raw container
  identity 대신 SHA256만 durable journal에 남긴다.
- Playwright는 기존 C7 origin guard·redacted reporter를 재사용해 response/error text, URL,
  run/Feature ID, trace, screenshot을 evidence에 남기지 않는다.

## 2. #785 stale correction 인수 시나리오

하나의 owned `place` Feature를 add 요청과 승인으로 만든 뒤 다음 순서를 실제 browser UI와
admin BFF/API에 걸쳐 검증한다.

1. 변경 요청 UI가 `/revision`과 detail을 읽어 같은 revision의 basis를 만들 때 응답 header의
   raw `ETag`를 캡처한다.
2. 이름 필드에 사용자의 dirty draft를 입력한다.
3. 별도 admin API 호출이 같은 baseline `If-Match`로 경쟁 update 요청을 만들고 이를 승인해
   Feature revision을 전진시킨다.
4. UI submit request가 최초 basis의 raw `ETag`를 그대로 `If-Match`로 보냈음을 wire에서
   단언하고, 서버의 `412 Precondition Failed`를 확인한다.
5. 412 뒤 dirty 입력값과 conflict 안내가 유지되고, 자동 refetch/retry로 mutation이 더
   발생하지 않음을 확인한다.
6. 운영자가 명시적으로 `최신값 다시 불러오기`를 눌러야만 경쟁 update 값과 새 basis가
   적용됨을 확인한다.
7. cleanup은 새 current ETag로 delete 요청을 만들고 승인해 `status=deleted`까지 확인한다.

경쟁 update는 단순 row revision 조작이 아니라 실제 승인된 변경 요청이어야 한다. 그래야
correction UI, review/apply path, row-revision trigger의 결합을 함께 증명한다.

## 3. #741 비공개 Feature 인수 시나리오

`draft`·`inactive`·`hidden` 상태별 owned `place` Feature 세 건을 add 요청과 승인으로 만든다.
각 상태에서 다음을 확인한다.

- admin `GET /v1/admin/features/in-bounds`의 exact status 조회에는 owned Feature가 포함된다.
- public detail과 public in-bounds에는 포함되지 않아 active-only predicate가 넓어지지 않는다.
- `/features` 운영 지도에서 `place`와 exact status 필터를 선택하고 충분히 확대한 뒤 owned
  marker의 accessible name과 선택 상세의 상태를 실제 DOM에서 확인한다.

admin API가 만들 수 없는 `weather`·`price` kind는 전용 fixture helper가 hidden owned Feature와
최소 1개 metric/history row를 transaction으로 만든다. runner는 helper 호출 전에 두 ID를
root-owned journal과 `BLOCKED.json`에 기록한다. browser는 각 Feature의 admin card 200·target
identity·non-empty row, kind별 UI panel의 non-error DOM을 확인하고 public detail/card/bbox는
404 또는 미포함임을 함께 단언한다. 정상·오류 cleanup은 child value row와 owned Feature를
transaction으로 물리 삭제한다. 삭제 전에는 ID뿐 아니라 `data_origin`·kind·name ownership
fingerprint와 value fingerprint도 확인한다. 삭제 뒤에는 `pg_catalog.pg_constraint`에서 찾은
모든 `feature.features(feature_id)` FK reference가 0인지 확인하며, recovery-only도 같은 exact
ID 외에는 건드리지 않고 seed/add/correction write를 거부한다.

## 4. 실패와 복구 불변식

- setup 중 일부 add만 승인된 경우에도 기록된 모든 owned ID를 역순 cleanup한다.
- stale UI PATCH가 예상과 달리 200을 반환하거나 pending request를 남기면 cleanup 전에 해당
  요청을 조회·종결하고 테스트를 실패시킨다.
- `412` 이후 최신 ETag를 추측하거나 JS number로 재구성하지 않는다.
- cleanup은 최초 ETag나 테스트 메모리의 revision을 재사용하지 않는다. 직전 `/revision`
  응답 header를 그대로 사용한다.
- 기존 Feature를 빌리지 않으므로 원복 body snapshot이나 provider 재적재에 기대지 않는다.
- normal failure는 best-effort가 아니라 recovery-only browser cleanup과 DB fixture cleanup의
  결과를 각각 journal에 남기고 residual이 있으면 `BLOCKED.json`을 유지한다. SIGKILL 뒤 수동
  recovery도 같은 순서를 실행하며 성공 전 새 run을 시작하지 않는다.

## 5. 검증 순서

1. docs-first commit과 draft PR을 먼저 공개한다.
2. exact 구현 head를 단일 적대 리뷰어가 검토한다.
3. P0~P3가 없다는 승인을 받은 뒤에만 TypeScript·mocked/static gate를 실행한다.
4. CI green과 배포 exact revision을 확인한 뒤 WSL에서 SSH로 n150에 접속해 official
   Playwright image로 targeted lane을 1-worker 실행한다.
5. owned ID 전부가 `deleted`이고 public projection에 남지 않았음을 확인한 증거를 이슈에
   남긴 뒤 #741·#785를 닫는다.
