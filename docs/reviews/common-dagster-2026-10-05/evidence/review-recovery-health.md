# Common health / Map / PinVi 고정 후보 독립 FULL 연속 리뷰 — 복구·DB·메모리 관점

작성일: 2026-10-05
최종 판정: **BLOCK — P2 H07 OPEN**. empty/unknown top-level 응답 방어는 개선됐으나, 정상 class 안의 손상 pointer·optional metadata를 healthy로 판정하는 공개 함수·실제 CLI 반례가 남는다. 본 보고서는 e0/6a54/2a36 고정 후보 원문이며 이후 수정 결과로 덮어쓰지 않는다.

## 고정 입력과 소유 범위

- manifest: `map-pinvi-health-reviewed-manifest.json`
- manifest SHA256: `8400965df8171f1159fa9c6695024e6582e56d9d41f3adaa1beae00d3ed7b06d`
- Common base `7dc1d6dda955b9b836cb3f24d6fd5bcd37fabe52` → candidate `e0b5e31a549bd6cb35af65d4a7573a46d2035ec9`
- Map base `a46d7b92c0e727805348e20d60fe188592e16477` → candidate `6a54a73bfbddb804ccb1abbca7842be2445a5b21`
- PinVi base `07cfef222c56d7e648c81b017aa8ffe4ccd1c386` → candidate `2a36e8973bb163c68f1a778a0c1215fa8e9d02d4`

WSL Ubuntu-26.04 Linux Git source archive를 본인 ext4 `/home/digitie/.cache/recovery-review-health-fixed-e0b5e31/{common,map,pinvi}`에 만들었다. 제품/사용자 dirty checkout/기존 설치/운영 서비스에 쓰지 않았다. 본인 archive 테스트와 own wheel/own isolated venv 및 이 새 원문만 작성했다. N150/외부 DB 접속·commit·push·peer 새 원문 열람 없음. manifest가 포함한 peer 보존 파일은 bytes hash만 계산했고 raw 내용은 읽지 않았다.

## 전체 manifest·소스 영향 검증

직접 SHA/경로 검증: **Common35 + Map61 + PinVi15 = 111개 파일 전부 일치**. 각 base→candidate의 전체 Git 변경 경로 집합도 manifest와 정확히 일치했다.

기존 Common1f8→e0 전체 delta를 검토했다. 새 제품 소스는 `dagster_health.py`와 그 테스트이며 README/가이드 §10/진행 상태·리뷰 보존 문서가 추가됐다. 기존 `http.py`, `dagster.py`, pyproject/uv.lock/py.typed는 1f8과 같다. 이전 Common HTTP/Dagster FULL 증거를 재사용할 근거이며, health의 새 schema finding과 분리한다.

기존 Map5ba→6a54 전체 delta는 다음 5개 파일이다.

```text
docker-compose.yml
docs/journal.md
packages/kor-travel-map-api/pyproject.toml
packages/kor-travel-map-dagster/pyproject.toml
tests/unit/test_docker_dagster_runtime.py
```

새 standalone probe는 `CMD python -I -m kortravelcommon.dagster_health <port>`이며, 두 Map Common Git pin을 e0로 정렬한다. API는 [http], Dagster는 [dagster] extra를 유지한다. 그 외 API/Dagster Python/UI/spec/locks, snapshot·DB·HTTP·소유권·runtime/executor 기능은 5ba와 byte 동일하다. standalone command·network·DSN·storage permit·entrypoint seal·timeout15초·자동재시작을 하지 않는 경계도 그대로다.

PinVi는 직전 2a36과 같은 commit이다. PinVi가 Common1f8 HTTP를 계속 사용하는 것은 요청의 불변 범위이며 기존 HTTP 제품 byte와 e0 HTTP byte도 같다.

검증 결과 JSON:
`/home/digitie/.cache/recovery-review-health-fixed-e0b5e31/independent-verification.json`
SHA256: `5931fc49b4e3f1c0455e62f44dc6278379d7aa32d70429b7027676008e8ed3e1`

## P2 H07 — 정상 class 내부의 손상 pointer·metadata를 healthy로 오인

경로: `packages/py/kor-travel-common/src/kortravelcommon/dagster_health.py`
위치: 49–61행 (`repository_code_pointer_dict`가 dict인지 확인한 뒤 symbol만 검증하고 True 반환).
Map 적용 위치: `docker-compose.yml`의 `dagster-code-server.healthcheck`.

`_is_loaded_reply`는 top-level `ListRepositoriesResponse`, symbol 목록·symbol class/문자열과 pointer 컨테이너가 dict인지까지 확인한다. pointer 값이 실제 CodePointer인지, optional metadata가 Dagster schema에 맞는지는 검사하지 않는다.

**실제 wire·공개 함수·isolated CLI 재현:** Dagster1.13.24의 `serialize_value(ListRepositoriesResponse(...))`로 만든 정상 control을 출발점으로 한 필드만 바꿨다. 실제 `ListRepositoriesReply` protobuf에 담아 본인 loopback gRPC server가 proxy health SERVING 뒤 반환한다. 같은 JSON을 설치 Dagster `deserialize_value(..., ListRepositoriesResponse)`로 읽어 반례의 schema 오류를 비교했다.

| 사례 | 변경 필드 | Dagster 판정 | 공개 health | 실제 -I -m CLI exit |
| --- | --- | --- | --- | --- |
| 정상 control | 실제 ModuleCodePointer·정상 metadata | 허용 | True | 0 |
| 손상 pointer 값 | repository_code_pointer_dict={"repo": null} | CheckError | **True** | **0** |
| unknown pointer class | repository_code_pointer_dict={"repo": {"__class__": "UnknownPointer"}} | DeserializationError | **True** | **0** |
| 손상 executable | executable_path=[] | ParameterCheckError | **True** | **0** |
| 손상 entry point | entry_point=123 | ParameterCheckError | **True** | **0** |
| empty wire control | protobuf bytes 없음 | 거부 | False | 1 |

모든 CLI는 own build wheel을 own venv에 설치한 뒤 `python -I -m kortravelcommon.dagster_health <ephemeral-loopback-port>`로 실제 실행했다. 기존 테스트용 PYTHONPATH 우회로 실행한 CLI가 아니다. 의존성은 read-only 기존 Dagster runtime의 site-packages를 own venv의 .pth로 참조했다. 정상/오류 결과 stdout·stderr는 모두 비어 있어 비밀 출력 문제는 보이지 않는다.

영향: Dagster가 deserialize할 수 없는 응답에서도 Map standalone 컨테이너 healthcheck가 exit0을 반환한다. healthy 표시를 저장소 load 성공의 신호로 사용하는 operator·후속 검증이 오류 상태를 정상으로 오인할 수 있다. 이 공격은 자체 synthetic wire 응답에서의 프로토콜 방어 재현이며, 실제 운영 Dagster가 이 손상 응답을 반환했다고 주장하지 않는다. 의도한 fail-closed schema 계약을 만족하지 못하므로 이번 새 후보를 BLOCK한다.

수정 권고: Dagster 전체 import를 피하는 경계를 유지하되, 지원하는 module/file/package CodePointer entries와 optional metadata 타입을 검증하고 unknown/지원하지 않는 typed metadata는 fail-closed한다. 현재 생성 protobuf 파일을 계속 사용하고 wire schema는 복제하지 않는다. 정상 empty symbol list 허용 계약을 유지하면서 위 4종 실제 CLI 회귀를 추가한다. 정상 class 이름만으로 healthy를 결정하지 않는다.

재현 스크립트:
`/home/digitie/.cache/recovery-review-health-fixed-e0b5e31/independent-health-schema-probe.py`
SHA256: `3628cb9092324631ce08b153f0b20bb45437c01fd3a9ff068497b979426b8019`

실행:

```bash
PYTHONPATH=/home/digitie/.cache/recovery-review-health-fixed-e0b5e31/common/packages/py/kor-travel-common/src \
/home/digitie/.cache/map-common-recovery-venv/bin/python \
/home/digitie/.cache/recovery-review-health-fixed-e0b5e31/independent-health-schema-probe.py
```

결과 JSON SHA256:
`28cff71c97d81638e1890cbba68c3d96d91e9b0fdab1a0f53192595323a71480`
파일: `independent-health-schema-counterexamples.json` (같은 own archive 상위 경로).

## 직접 통과한 회귀·closure·메모리/정리 경계

새 Common health 테스트를 exact own source에서 직접 실행했다:
**25 passed in 0.70s**. 실제 protobuf/loopback 응답, malformed/unknown top-level class·empty/corrupt wire, symbol 타입, duplicate JSON 필드, invalid port, 4MiB cap 및 channel context cleanup·각 RPC timeout4 설정, 별도 subprocess NoDagsterImport 테스트를 포함한다.

Map focused source·seal 테스트도 다시 실행했다:
**10 passed, 277 deselected in 0.97s**.
현재 exact Common CLI argv와 standalone code-server start/production seal의 허용·거부 경계를 검사했다. shell preflight는 own stub이며 실제 DB preflight 성공으로 확대하지 않는다.

이번 직접 pytest 합계는 **35 PASS**이며 부모의 Common120/Map381/문서604는 본인 PASS로 합산하지 않는다.

별도 본인 actual loopback gRPC 추가 공격:

| 사례 | 공개 함수 | wall time |
| --- | --- | --- |
| NOT_SERVING | False | 0.008초 |
| ListRepositories 4.5초 정체 | False | 4.005초 |
| 4MiB+1 응답 | False | 0.006초 |

server/channel는 각 own 테스트 범위에서 정리했고 외부 접속 없음. cap/deadline 증거 SHA256:
`b0568003dd2603592df52de06dd85cf09d27b806b0937b1c8e3f275d9e23278f`
파일: `independent-health-deadline-cap.json`.

빈/손상 wire·JSON·중복 필드/top-level unknown class를 통과시키던 기존 substring 경계는 CLOSED로 확인했다. 새 helper는 실제 설치 Dagster generated protobuf를 파일로 직접 읽어 wire를 decode하고 `grpc.max_receive_message_length=4MiB`를 적용하며 with-channel cleanup을 보장한다. Dagster full import 회피는 제공 회귀를 직접 실행해 확인했다. H07은 그 뒤 nested/optional schema의 별도 잔여 결함이다.

core-only wheel도 직접 검사했다. own source에서 `uv build --wheel --offline` 성공, own without-pip venv에 wheel만 --no-deps 설치한 상태에서 health module import가 Dagster/grpc를 import하지 않고, optional deps가 없을 때 public 함수는 False였다. 해당 core-only 검사 후에만 actual CLI wire 검사를 위해 own venv에 read-only runtime 참조를 추가했다. 기존 설치는 변경하지 않았다.

wheel SHA256:
`cb5ffca95e2b51df9b0c0c37893ed4a231153ba822ebe36865296915c8f1092e`
파일: `wheels/kor_travel_common-0.1.0.dev0-py3-none-any.whl`.

pytest 로그 SHA256:
- `independent-common-health-tests.log`: `bb4cef053b355422423e7792985a159930cae2ef8b9a3c3fdfd7db6d53a79fb1`
- `independent-map-seal-tests.log`: `9d49388a28235338218136b0fe0a3e6671600e8c6a624ffec0aeb946c1097a99`

## 이전 FULL 증거와 문서/운영 경계

이전 Common HTTP/Dagster 제품 FULL 및 소비자 FULL1517 PASS, Map request-scoped fixture 6건, PinVi Docker frontend 검토는 변경 없는 source byte에 재사용한다. 이번에 새로 다시 실행한 것은 health25/Mapseal10 및 위 추가 wire·wheel 공격이며, 기존 합계를 신규 PASS로 중복 집계하지 않는다. R01–R06 기존 closure, batch100/8종 atomic seal·dedup·rollback·pool1 SQLite/Fake SQL·executor cap·RUN/STEP retry 구분·strict repository ownership·HTTP cancel/cleanup 경계는 동일 byte에 유지된다.

가이드 §10의 CLI 위치·[dagster] extra·4초 RPC/4MiB·15초 outer timeout·정상 empty symbol 허용·unhealthy 자동 재시작 아님·운영 NOT_RUN 표시는 명확하다. 단 malformed schema 전부 fail-closed라는 설명은 H07이 해결될 때까지 충족되지 않는다. 설치 Dagster 최소1.9부터 전체 지원 버전 matrix를 실제 실행하지 않았으며 이번 own runtime은 1.13.24다.

직전 두 원문 hash 불변을 다시 확인했다.

- standalone 원문: `9ce737a67c38a273e6866f8c2c99a50e56f9616ce13af6bd0673b9ffee27753a`
- frontend 원문: `4ac71ae6cb00e6741e0a711d40919e3abc5a7406caec1c9f019382b73f44715f`

이전 PASS/BLOCK 원문은 그대로 보존했다. 본인은 5ba 단계에서 malformed schema 전체를 검사했다고 주장한 적이 없으며, 이번 nested schema 반례를 새로운 e0 BLOCK 원문으로 분리했다.

NOT_RUN: 새 후보 CI·actual operating image attestation·rotation/rebuild/live, actual shared daemon/PG/domain SQL, 실제 code-server reload/run fault, N150 접속·브라우저 E2E·운영 mutation·merge. old operating6 healthy 및 부모의 각 gate PASS는 전달받은 참고 정보이며 본인 운영 확인으로 집계하지 않는다.

현재 immutable e0/6a54/2a36 전체 소스 리뷰는 **BLOCK(P2 H07 OPEN)**이다. 수정된 신규 immutable 후보에서 4종 실제 공개 함수·CLI 반례 closure를 다시 확인해야 한다.
