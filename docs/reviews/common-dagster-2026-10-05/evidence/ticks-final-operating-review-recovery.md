# 최종 Map·PinVi 운영 배포 독립 읽기 전용 검증

작성: 2026-10-06 KST. 판정: **PASS — 실제 committed rebuild·runtime·byte inheritance 증거 범위**. UI/domain 수용 및 새 이미지의 native fault 실행을 이 판정에 포함하지 않는다.

## 고정 제품과 receipt

Common `a960bdb114d99a2ac1b9608a77b240635806e551`, Map `1a3c4673790f51daa1a2f5ccf803d4e31673bad6`, PinVi `0058369c778f8c3357ee393e12e3447d7975cc1f`.

| 읽은 원본 JSON | SHA256 |
| --- | --- |
| map-pinvi-operating-runtime-ticks-attestation.json | `8d998cecf435d270b704b5bb20912004d3143ce89b62a0dbe3710cefd737db99` |
| map-pinvi-rebuild-ticks.json | `21c0fc746d5916b74ecd557e8682d6a02cdd5a067058e30b08e60b37de3d0261` |
| map-native-final-byte-inheritance.json | `72c7f9ee69486695327ddd6a964d5f33f97f59f0f710cfdb637135ca3e0278d7` |

세 파일 status PASS와 서로 연결하는 원본 hash를 확인했다. 증거를 복사/덮어쓰거나 성공 receipt를 새로 생성하지 않았다. Peer 리뷰 원문은 읽지 않았다.

## 본인이 직접 확인한 실제 상태

이미 정적·적대 검토한 runtime helper SHA256 `73c52d16a845db00c7eef0edd2a4522e30f7d20a1fcc354453fb8d2f9549d21b`의 remote 프로그램만 AST로 추출했다. 파일 쓰기를 하는 outer main을 호출하지 않고 읽기 전용 SSH로 실행했다. 실제 반환 canonical dictionary가 저장된 새 attestation과 **정확히 같았다**.

- 현재 deploy는 committed이며 run ID `b1ad9ddd-a32d-4568-97f8-c965bb6ddcd5`, pinset `7b0e2febd36a889e22acb070df16182cfad8d9d42a6ef62c01caa15bd3524021`다.
- actual deploy bytes SHA256 `2198f4e2846179c75fd80f635c4d8c5f382fc04bac4533227517cc0206717a4d`와 root 소유·0700 디렉터리/0600 파일·symlink/metadata 경계를 조회 끝에 재검증했다.
- installed Manager revision은 `e2a1a5b42fec207fc6c5e0638c652de04e5694d4`다. 저장된 source의 recorded_at은 2026-10-05T19:17:00+00:00이며, 이는 본인의 조회 시각을 뜻하지 않는다.
- 6개 컨테이너 모두 실제 running/healthy이고 image ID·source revision이 committed deploy와 일치했다.
- Map API installed query hash는 `fce5e6d13f217860e3a1b022dd2f9c3656502c01b47ea87212991efcd27d8d3a`로 immutable 제품과 같다. HTTP/GraphQL wrapper 및 Dagster definitions의 설치 hash도 immutable Git blob에 일치했다. 부모가 제공한 결과를 그대로 PASS로 합산하지 않고 실제로 다시 읽은 결과다.
- installed Common commit은 Map API/Dagster a960, PinVi API 1f8e339, PinVi Dagster 73e3ff8이다. Common HTTP hash `cbb6d44f...`, Dagster hash `ee1bce42...`, health hash `5edaab3a...`가 해당 정본과 같다. 모든 컨테이너가 a960을 설치했다고 주장하지 않는다.
- Map Common child-health CLI도 실제 PASS였다. 공유 Dagster DB는 read-only 연결로 실제 head `29b539ebc72a`를 확인했다. Map `404_transport_provider_identity`와 PinVi `20260917_0102`는 committed deploy/result가 선언하는 application head다. 이 두 도메인 DB에 별도 SQL을 실행한 것으로 주장하지 않는다.

| 서비스 | 실제 image ID |
| --- | --- |
| Map API | `sha256:bf1ca32aad6a83a530abfad871fa88f6019761c1d7780bfbb76469494af06e0f` |
| Map UI | `sha256:6d037af0a23cce67b6345821970d0928598e8bd9bd68a68bdad565832c51c4a4` |
| Map Dagster | `sha256:197597501a0bc06bfaa5a3ca1be3e406aca6794f59306710fb79325c10d18d07` |
| PinVi API | `sha256:af884b398f35ca1d8b954e5e997f87023bb09cda1f7b68fcd192d454c9056875` |
| PinVi Web | `sha256:1ac1a01ac5bd845bf72e04a3f96db0e6438b6095529480529af2a3361b19eec1` |
| PinVi Dagster | `sha256:21b5c3241ab76302ee39237ceed1c5bd6f8f4166b3bb5912534b07cdfe7a57a0` |

## 실제 own result와 terminal 판정

2026-10-05T19:21:22.853620+00:00의 별도 읽기에서 해당 ticks output의 실제 result.json bytes를 직접 읽었다. 원본 SHA256은 `9773684389d865874793df7b4b28f8d272ec3c14093eb10635a1a4b78af32505`이며 collector의 original_result_sha256과 같다.

원본의 키는 정확히 10개: success, returncode, resumed, outcome, transaction_id, phase, generation_sha256, pinset_sha256, schema_heads, warnings. success는 strict True, returncode는 int 0, resumed는 strict False, outcome deployed, phase committed다. transaction_id는 위 실제 deploy run ID와 일치한다. generation SHA256은 `4a635b3fd4d01fdd3c8ebdfd3fbc4d64faa3fce372b59035d21be42141ec01a4`로 실제 result와 공개된 safe result가 같음을 확인했다. 전체 generation payload를 별도로 hash 재계산한 것으로 주장하지 않는다. warnings는 list이며 count 1이고 원문 경고는 출력하지 않았다.

현재 guard와 inner unit은 모두 not-found/inactive/dead로 제거된 상태이며 시작·종료 timestamp가 비어 있다. 이 상태에서 기본 Result=success/ExecMainStatus=0을 배포 성공 증거로 사용하지 않았다. actual canonical result의 deployed/committed와 실제 current deploy·runtime을 성공 근거로 사용한다.

## Native inheritance의 의미

새 Map Dagster image를 inspect-before → importlib.metadata version → inspect-after로 별도 직접 조회했다. 두 image ID 모두 `197597...`와 일치하고 실제 Dagster version은 1.13.24다. 저장된 inheritance의 actual_version_read_fence와 정확히 같다. 제품 모듈을 import하지 않았다.

inheritance가 참조하는 이전 runtime attestation SHA256 `de4be912a7327e155c65242ee48b1bac108c03c8818431855fc33bc442701312`와 실제 native receipt SHA256 `bd31491f4bee7d2962089445d50852185e3935f625d8d5961b3f925f27ef6bf6`를 해당 기존 파일 bytes로 검증했다. 이전 native image는 `5ded0abe...`, 새 image는 `197597...`로 다르다.

이 증거는 이전 이미지에서 실행된 native 시험과 unchanged consumer Dagster/Common source·설치 버전의 연속성만 인정한다. 실제 새 이미지에서 native fault를 다시 실행했다거나, Dagster 전체 바이너리·전이 dependency bytes가 같다고 확대하지 않는다. 새로운 API query/C7의 live·domain 수용은 별도 gate다.

## 수행·미수행 경계

직접 수행: 세 새 JSON/참조 원본의 SHA·canonical field 검증, 실제 current deploy/metadata/image/health/installed source/Common commit/shared Dagster DB head 읽기, 실제 own result 원본과 strict 10-field 대조, 새 Dagster image/metadata version 전후 fence.

NOT_RUN: build·rotation·stop/restart·DB mutation·fault injection·새 native 실행·도메인 application head SQL·UI/browser/chain 수용. 현재 UI 컨테이너를 조회하거나 조작하지 않았다. API 업무 요약을 재호출하거나 제품 전체 테스트를 반복하지 않았다. 보존된 초기 실패·old receipt·본인 이전 원문을 덮어쓰지 않았다.

차단 결함 없음. 이 원문만 새로 저장했고 private IP/DSN/credential/env 원문은 기록하지 않았다.
