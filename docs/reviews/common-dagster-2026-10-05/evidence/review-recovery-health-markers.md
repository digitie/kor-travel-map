# Common marker guarded / Map / PinVi 최종 독립 FULL 연속 리뷰

작성일: 2026-10-05
판정: **FULL 연속 PASS — H07·H08 CLOSED**. 새 source blocker를 발견하지 않았다. 실제 운영 CI/rebuild/live 완료 판정은 아니다.

## 고정 입력·검토 독립성

manifest `map-pinvi-health-markers-reviewed-manifest.json`
SHA256 `3a001debb93c6656ca99bcaecea7ddcc083cdc2f6520168ca01963e3a1683a13`

| 저장소 | base | candidate | 전체 검증 파일 |
| --- | --- | --- | --- |
| Common | 7dc1d6dda955b9b836cb3f24d6fd5bcd37fabe52 | a960bdb114d99a2ac1b9608a77b240635806e551 | 35 |
| Map | a46d7b92c0e727805348e20d60fe188592e16477 | 1ba6ef4c52f64200e3bc3e9a4fee1dd5f8d4e77e | 61 |
| PinVi | 07cfef222c56d7e648c81b017aa8ffe4ccd1c386 | 2a36e8973bb163c68f1a778a0c1215fa8e9d02d4 | 15 |

본인 source archive는 `/home/digitie/.cache/recovery-review-health-markers-fixed-a960bdb/{common,map,pinvi}`다. WSL Ubuntu-26.04 Linux Git exact source archive를 사용하여 manifest SHA와 **111개 모든 blob SHA**, 각 base→candidate 전체 변경 경로 집합을 직접 검증해 일치했다. metadata용 peer 보존 blob은 hash만 계산했고 원문 내용을 읽지 않았다.

제품/기존 설치/사람 dirty checkout/운영 서비스에 쓰지 않았다. 본인 ext4 archive·wheel·isolated venv·임시 test/probe와 이 보고서만 작성했다. N150/외부 DB 접속·commit·push·peer 새 결과 열람 없음. AGENTS/SKILL/Linux·책임 경계와 요청의 read-only 범위를 유지했다.

검증 JSON `independent-verification.json` SHA256:
`a8ad6b35734438577c955e7f099bf7f2bcbb88ee9a456142b24cd3cd75ebda31`

## 전체 source delta·기존 FULL 연결

Common99→a960의 전체 delta는 journal/resume/가이드 §10/health source/health tests의 5파일이다. 제품 수정은 installed generated protobuf·JSON 응답 schema를 검증하는 helper의 mapping marker guard다.

Mapb972→1ba6의 전체 delta는 journal/API pyproject/Dagster pyproject의 3파일이다. 두 Common Git pin을 같은 a960으로 변경하며 [http]/[dagster] extra는 유지한다. PinVi2a36은 그대로다.

Common의 기존 HTTP/Dagster core, pyproject/uv.lock은 본인 검증 완료1f8과 byte 동일임을 직접 assertion으로 확인했다. Map production API/Dagster Python/UI/spec/locks/snapshot·DB·owned run·runtime tags·executor, standalone argv/probe CLI/entrypoint seal/network/storage 설정도 이전 후보와 같다. 이전 base 대비 manifest가 포함하는 기존 HTTP와 59/61개의 소비자 source 전체 범위는 기존 독립 FULL 제품·fixture·main·frontend·standalone 리뷰와 byte 동일성으로 연결했다.

기존 소비자 FULL1517 PASS 및 Map fixture6건, PinVi frontend 검토는 unchanged source 증거로 재사용한다. 이번에 새로 직접 실행한 Common전체160/Mapseal10은 아래 별도로 기록하며 기존1517을 신규 합계에 더하지 않는다.

## H07·H08 closure 및 metadata profile

H07은 pointer null/UnknownPointer/executable_path[]/entry_point123이 실제 Dagster deserialize에서는 거부되지만 health/CLI가 통과한 결함이었다. 새 helper의 typed pointer·nullable metadata 검사로 모두 False/exit1이 된다.

H08은 versions 및 pointer dictionary의 reserved marker key가 표면 타입 검사를 우회한 결함이었다. 새 코드의 marker 집합은 다음과 같다.

```text
__class__
__enum__
__set__
__frozenset__
__mapping_items__
```

본인 read-only installed Dagster1.13.24 serdes `_unpack_value` 구현에서 이 5개가 실제 typed decoder marker임을 직접 확인했다. versions와 pointer mapping 양쪽에 marker key가 있으면 reject한다. ordinary repository name 전체의 `__` prefix를 거부하는 방식이 아니므로 정상 default `__repository__`는 유지된다. JSON duplicate object key도 기존 object_pairs_hook가 거부한다.

지원 profile은 실제 ModuleCodePointer/FileCodePointer/PackageCodePointer 및 문서의 plain nullable metadata다. field·working_directory·executable/entry/image·version 문자열·plain JSON context를 검증한다. 실제 Dagster가 deserialize할 수 있는 CustomPointer와 stateful DefsStateInfo도 현 profile에서는 의도적으로 False/exit1이며, 가이드가 해당 location 채택 전에 profile 확장·버전 고정·positive/negative 회귀를 요구한다. 임의 Dagster serdes 대체물이나 모든 location 지원으로 설명하지 않는다.

생성 protobuf schema를 복제하거나 Dagster 전체를 import하지 않는다. installed distribution의 generated file로 실제 wire를 decode한다. public 함수는 loopback Health4초 + child ListRepositories4초, logical receive4MiB/channel context cleanup을 유지하며 오류 원문을 stdout에 내보내지 않는다. 이 predicate는 repository load/RPC/schema 상태이며 실제 DB/worker/job 성공 증거는 아니다. Map standalone unhealthy가 PID1 종료·자동 재시작을 뜻하지 않는다는 경계도 문서에 유지한다.

## 직접 actual serializer·wire·installed CLI 검사

새 wheel을 own venv에 설치했다. Python3.13.14 / Dagster1.13.24 read-only runtime에서 실제 `serialize_value(ListRepositoriesResponse)` control을 만들고 본인 ephemeral loopback gRPC가 actual generated protobuf로 반환했다. public `code_server_is_healthy`와 own installed `python -I -m kortravelcommon.dagster_health <port>`를 함께 실행했다. CLI는 PYTHONPATH로 source를 삽입한 대역이 아니라 own wheel을 설치한 실제 -I module 실행이다.

본인 matrix23건 기대값 assertion을 직접 확인했다. 모든 CLI stdout/stderr는 비어 있다.

| matrix | 공개 health | actual CLI |
| --- | --- | --- |
| module/default __repository__ | True | exit0 |
| 실제 FileCodePointer 정상 | True | exit0 |
| 실제 PackageCodePointer 정상 | True | exit0 |
| H07 pointer null | False | exit1 |
| H07 UnknownPointer | False | exit1 |
| H07 executable_path=[] | False | exit1 |
| H07 entry_point=123 | False | exit1 |
| actual valid CustomPointer, unsupported | False | exit1 |
| actual valid DefsStateInfo, unsupported | False | exit1 |
| H08 versions __class__ / __enum__ | False | exit1 |
| H08 pointer mapping __class__ / __enum__ (value valid pointer) | False | exit1 |
| 5 markers × versions/pointer mappings 10건 | False | exit1 |

앞선 H07/H08 반례와 일반화한 10종 marker grid를 함께 검사했으므로 일부 marker case가 중복된다. matrix23건을 pytest23개로 합산하지 않는다. positive3 control과 unsupported2 및 negative18의 기대 결과가 모두 일치한다. 실제 Dagster deserializer의 positive/negative 비교 결과도 evidence에 남겼다.

가이드 §10의 marker 목록·default repository 허용·supported/unsupported 범위와 실제 결과가 일치했다. 현재 제품에는 stateful/custom location을 사용한다는 source 변경이 없다. Dagster≥1.9 전체 버전 matrix 및 actual operating module location 재검증은 별도 운영 범위이며 본인 NOT_RUN다.

## 직접 pytest·wheel·검증 결과

own new wheel/venv에서 Common Python 전체를 직접 실행했다.

```bash
TMPDIR=/home/digitie/.cache \
PYTHONPATH=/home/digitie/.cache/recovery-review-health-markers-fixed-a960bdb/common/packages/py/kor-travel-common/src \
/home/digitie/.cache/recovery-review-health-markers-fixed-a960bdb/cli-venv/bin/python -m pytest \
  /home/digitie/.cache/recovery-review-health-markers-fixed-a960bdb/common/packages/py/kor-travel-common/tests \
  -q -p no:cacheprovider
```

**160 passed in171.26s**. health65는 이160에 포함되며 별도로 더하지 않는다. 기존 Dagster SQLite recovery·slow event/cursor/checkpoint 및 HTTP actual transport·deadline/cancel/cleanup 회귀도 함께 재실행했다. instance/HTTP fixture는 own local SQLite/loopback/MockTransport이며 운영 연결을 하지 않는다.

현재 Map seal·standalone focused source 회귀도 own archive에서 직접 다시 실행했다:
**10 passed,277 deselected in0.88s**.

```bash
PYTHONPATH=<fixed Common src>:<own Map src>:<own API src>:<own Dagster src> \
TMPDIR=/home/digitie/.cache \
/home/digitie/.cache/map-common-recovery-venv/bin/python -m pytest \
  /home/digitie/.cache/recovery-review-health-markers-fixed-a960bdb/map/tests/unit/test_docker_dagster_runtime.py \
  -q -k "standalone_compose_code_server or production_code_server" -p no:cacheprovider
```

이번 직접 pytest 총계는 **170 PASS**다. shell entrypoint 검증의 application preflight는 disposable stub임을 유지하고 실제 PG preflight라고 주장하지 않는다.

새 health source+test Ruff PASS. `uv build --wheel --offline` PASS. own without-pip venv에 wheel만 --no-deps 설치한 core-only 검사에서 optional Dagster/grpc를 import하지 않았고 missing optional deps 호출은 False였다. 그 뒤 actual CLI 검사용 read-only runtime site-packages 참조를 own .pth에만 추가했다. 기존 runtime을 변경하지 않았다. wheel에 health module과 py.typed가 들어 있음을 직접 확인했다. 설치 Dagster1.13.24 metadata에 grpcio/health-checking/protobuf 의존이 있어 [dagster] extra 계약과 연결된다.

proof files는 위 own archive 상위 경로에 보존했다.

| 파일 | SHA256 |
| --- | --- |
| independent-common-full-tests.log | 5b8ca3f91a415868d48aecba1daae3c822cebfd520b3664496e598efbcd4db79 |
| independent-map-seal-tests.log | 69ea23d07c5c6c171ec9fe5ea9ff26945e4b11bc4586f16a33dde6ed3ea1a816 |
| independent-schema-profile-probe.py | 1273bffc7b599c578f0f74172fb341566fe147329ed453060202feda2883c867 |
| independent-schema-profile-evidence.json | 14037ea59936c8835d030f17aec512ae7f02f0b51b4df56f2b3a44725a0308cb |
| wheels/kor_travel_common-0.1.0.dev0-py3-none-any.whl | 14f4326ecd8a2e3972bd00314157e0553b5b8b2d358577bf5eb66a56b990b3e7 |

## 기존 원문 보존·실행 경계·최종 판단

이전 두 BLOCK 원문을 다시 hash 확인하고 그대로 보존했다.

- e0 H07 BLOCK `map-pinvi-health-closure-review-recovery.md`: `120d648715c2ec5cb6e57d8c0621c37f6efcb260757994bd6688d0ac106b0c65`
- 99 H08 BLOCK `map-pinvi-health-schema-review-recovery.md`: `25a3d220683644e49af5370844da95da4c589fae62d99d7d01f11254880bc0f8`
- 그 앞 standalone PASS 원문: `9ce737a67c38a273e6866f8c2c99a50e56f9616ce13af6bd0673b9ffee27753a`

새 journal/resume는 이전146과 새65를 다른 source 증거로 분리하고 새 FULL/CI/live가 남았다고 기록한다. 부모의 root65/full160 진행 결과는 본인 직접170과 혼합하지 않았다. immutable archive와 실제 own test 결과로 판정했다.

NOT_RUN: 새 exact CI/Docker build·operating image attestation·paired rotation/rebuild/live, actual N150/PG/domain SQL/shared daemon·code-server reload/native fault recovery·브라우저 E2E·운영 mutation·merge. 실제 loopback schema fixture를 production Dagster load 검증으로 확대하지 않았다. old operating6 healthy는 부모 참고이며 본인 운영 확인이 아니다.

최종 **FULL 연속 PASS**, H07/H08 **CLOSED**, 새 source blocker 없음. 실제 소비자 이미지·native shared runtime·live gate는 별도로 완료해야 한다.
