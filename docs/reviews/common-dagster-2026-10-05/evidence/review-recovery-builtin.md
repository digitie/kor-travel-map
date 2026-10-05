# Common·Map·PinVi builtin frontend 독립 FULL 연속 리뷰 원문

작성: 2026-10-06 / 독립 리뷰 A(복구·DB·메모리·격리). 판정: **소스 FULL 연속 PASS**.
새 Dockerfile 변경에서 신규 blocker를 발견하지 않았다. 이 판정은 실제 새 이미지 빌드 성공, 운영 재구축 성공 또는 live E2E 성공을 뜻하지 않는다. 해당 새 후보의 운영 gate는 **NOT_RUN**이다.

## 고정 대상과 소유 범위

| 저장소 | 기준 | 고정 후보 | 전체 delta 파일 |
| --- | --- | --- | --- |
| Common | 7dc1d6dda955b9b836cb3f24d6fd5bcd37fabe52 | a960bdb114d99a2ac1b9608a77b240635806e551 | 35 |
| Map | a46d7b92c0e727805348e20d60fe188592e16477 | 1ba6ef4c52f64200e3bc3e9a4fee1dd5f8d4e77e | 61 |
| PinVi | 07cfef222c56d7e648c81b017aa8ffe4ccd1c386 | 0058369c778f8c3357ee393e12e3447d7975cc1f | 15 |

Immutable manifest: map-pinvi-builtin-reviewed-manifest.json.
직접 계산한 SHA256: 954edf0fe117091c4d39c9fbe1e4d797981c73ade359f74eaeb0d67184dbe866.
총 111개 blob SHA와 각 저장소 base→candidate 전체 diff 경로 집합이 manifest와 정확히 일치했다.

Linux Git archive 기반 본인 사본만 사용했다. Common·Map은 이전 동일 고정 commit 사본을 재사용했고 후보 SHA가 동일함을 먼저 확인했다. PinVi는 새 후보에서 별도 archive를 생성했다.
- Common: /home/digitie/.cache/recovery-review-health-markers-fixed-a960bdb/common
- Map: /home/digitie/.cache/recovery-review-health-markers-fixed-a960bdb/map
- PinVi: /home/digitie/.cache/recovery-review-builtin-fixed-0058369/pinvi

제품/운영/기존 runtime에 쓰지 않았다. N150에 접속하지 않았고 기존 daemon/DB/Docker builder를 실행하지 않았다. peer 원문/판정은 읽지 않았다. 이번에 작성한 파일은 이 새 보고서뿐이다.

## 이번 직접 검사와 변경 범위

PinVi 2a36e8973bb163c68f1a778a0c1215fa8e9d02d4→0058369c778f8c3357ee393e12e3447d7975cc1f 전체 Git diff는 정확히 3개 파일이다.

1. apps/api/Dockerfile: 기존 외부 #syntax 지시자와 설명 두 줄을 builtin frontend 설명 두 줄로 대체.
2. apps/etl/Dockerfile: 동일 변경.
3. docs/journal.md: 이전 실제 ETL frontend 실패, 기존 6개 서비스 유지, 변경 목적 및 후속 검증 범위를 기록.

두 Dockerfile의 첫 두 줄 이후 전체 내용이 byte 동일하다는 assertion을 직접 수행했다. 두 줄 변경 외 모든 tracked 파일에 diff가 없다는 전체 Git 비교로 앱/Python/ETL/UI/lock/Common pin/M05/provenance 계약의 동일성을 확인했다. Common·Map은 이전 후보와 commit 자체가 같다. README/가이드/테스트/문서를 포함한 111개 전체 범위는 이전 FULL 검토와 이번 전 blob 재확인으로 연속해서 커버한다.

API·ETL Dockerfile 전체를 직접 읽었다. 사용 명령은 ARG, CMD, COPY, ENV, EXPOSE, FROM, HEALTHCHECK, LABEL, RUN, WORKDIR이다. ETL의 COPY --from=uv는 표준 multi-stage copy이며 두 파일에 COPY --parents, RUN --mount/--device/--security 같은 labs 기능은 없다. 기본 이미지 digest, uv digest, 작업 디렉터리, provenance validation, dependency export/install, healthcheck와 entrypoint는 그대로다.

web Dockerfile의 #syntax=docker/dockerfile:1.7.1-labs@sha256:b99fecfe00268a8b556fad7d9c37ee25d716ae08a5d7320e6d51c4dd83246894 및 COPY --parents는 그대로 유지됐다. API·ETL 변경을 web까지 확대하지 않았음을 확인했다.

후보의 scripts/infra/.github/workflows 및 세 Dockerfile에서 BUILDKIT_SYNTAX, syntax=, labs 명령, build args와 buildx/build-push-action을 검색했다. 해당 범위에 BUILDKIT_SYNTAX 주입은 없었다. ETL CI는 정상 docker build --file apps/etl/Dockerfile과 PINVI_BUILD_ENVIRONMENT/PINVI_SOURCE_REVISION 인자를 사용한다. compose API·ETL build args에도 frontend override는 없다. 공개 wrapper도 읽기 전용으로 검토했다.

본인 검증 기록:
- /home/digitie/.cache/recovery-review-builtin-fixed-0058369/independent-verification.json
- SHA256: 73208d339f5e0dc7241e32596115a13c598b1425b99ad6b914830c23da1c0a01

실행 명령 유형: wsl -d Ubuntu-26.04 -- bash -lc 아래 git archive, git diff --name-only/full diff, Python hashlib/manifest 경로 집합 및 Docker body equality assertions, rg, Dockerfile/workflow/compose/journal source read. 현재 후보에서 Docker build 또는 broad pytest는 실행하지 않았다. 설명/지시자만 바뀐 이 delta에 중복 broad test를 추가하지 않았다.

## frontend override와 재현성 경계

#syntax를 지정하지 않은 BuildKit Dockerfile은 builder에 포함된 frontend를 사용한다. 또한 BUILDKIT_SYNTAX build argument로 외부 frontend를 선택할 수 있다. 따라서 이 변경은 저장소 기본 실행에서 불필요한 외부 frontend 실행을 제거하지만, 외부 호출자가 override를 주는 경우까지 차단하지는 않는다. 근거: [Docker frontend 공식 문서](https://docs.docker.com/build/buildkit/frontend/), [Dockerfile syntax 공식 문서](https://docs.docker.com/reference/dockerfile/#syntax).

첫 두 줄은 일반 주석이다. 그 다음 실제 Dockerfile 명령은 표준 기능이며, 현재 확인한 저장소 build 경로에는 외부 frontend override가 없다. 새로운 source blocker는 없다.

builtin frontend 버전은 실제 Engine/BuildKit 환경에 종속된다. 이번 변경으로 builder 버전 독립성, hermetic build 또는 이미지 output byte 동일성이 확보됐다고 판단하지 않는다. 후속 실제 빌드 증거에는 Engine/BuildKit 및 사용하는 경우 buildx 버전, 실제 CLI/args와 BUILDKIT_SYNTAX override 유무, 고정 source SHA 및 산출 image ID를 기록해야 frontend 선택과 동작을 재현할 수 있다. 외부 DockerManager/운영 builder의 실제 버전·CLI·환경은 본인 NOT_RUN 범위이다. README/주석/journal의 builder-version 증거 필요 설명은 이 경계에 맞는다.

## 이전 독립 검증 재사용과 closure

이전 marker FULL 원문은 변경하지 않았으며 SHA256도 다시 확인했다.
- map-pinvi-health-markers-review-recovery.md: 7040e3726b33f61b94295602bbde566befee55e3403f16f99f149162a6ba2b2d
- 이전 BLOCK map-pinvi-health-schema-review-recovery.md: 25a3d220683644e49af5370844da95da4c589fae62d99d7d01f11254880bc0f8

Common a960/Map1ba가 동일하므로 이전 본인 직접 Common 전체 160 PASS와 Map CLI seal 10 PASS(총 pytest 170), 실제 installed wheel/core-only import와 실제 generated protobuf/loopback/installed -I CLI profile 23건의 증거를 그대로 재사용한다. 23 profile 사례는 pytest 개수와 별도이다. H07의 4개 malformed typed profile와 H08의 versions/pointer map reserved 5 marker는 fail-closed이고 정상 module/file/package 및 기본 __repository__ profile은 통과했다. unsupported custom/stateful typed metadata는 명시적 거부 범위다.

또한 제품 기능 byte 동일성으로 이전 e4/aa 계열 본인 직접 1517 PASS, snapshot 8종 batch100/SQLite pool1 atomic seal·dedup·rollback, actual configured executor/run tags, HTTP identity/cap/deadline/cancel/cleanup, required repository collection/selector identity 검증, PinVi wheel 계약 및 native Dagster definitions import 증거를 재사용한다. request-scoped integration fixture 직접 6개 lifetime/예외/cancel 검증과 canonical assertion 유지 검사는 이후 byte 동일성으로 이어진다. 이 수치는 과거 수행 시점의 증거이며 이번 후보에서 다시 실행한 결과 또는 새 합산 PASS로 표시하지 않는다.

기존 제품 finding R01–R06 및 Common H07/H08 closure는 유지된다. 이번 frontend 변경은 Python/API/복구/DB/메모리/HTTP/core/health 계약을 바꾸지 않는다. 이번 delta에서 신규 finding은 없다.

## 실행·미실행 및 최종 판정

본인 직접 수행: 고정 manifest SHA와 전체 111 blob/path 검증, 전체 3-file delta 확인, API·ETL 전체 body byte equality, 명령/옵션 계약과 override 검색, 문서 claims 경계 확인, 이전 본인 raw hash 불변 확인, 공식 Docker primary docs 확인.

본인 NOT_RUN: 새 Docker 이미지 build/frontend 실행, 실제 builder version 측정, CI 실행, PG/domain SQL, 운영 회전/guarded rebuild, 새 N150 native fault probe 및 live/browser E2E. 외부 custom caller가 BUILDKIT_SYNTAX를 넣는 실제 시나리오도 실행하지 않았다.

작성자 전달 증거는 독립 실행으로 합산하지 않는다. root는 이전 pinned b99 frontend로 실제 ETL gRPC server closed 재실패와 기존 6개 서비스 정상 유지, 새 preflight disk FAIL 및 새 후보 운영 build NOT_RUN을 전달했다. 이후 새 PinVi source CI 9 PASS와 Common 8/Map 10 기존 PASS도 전달했다. 본인은 해당 CI나 운영 로그를 실행·검증한 것으로 주장하지 않는다. 이전 source PASS를 새 이미지 성공으로 바꾸지 않았다.

최종: 전체 111파일 **소스 FULL 연속 PASS**. 새 builtin frontend 선택은 검토한 표준 명령과 저장소 호출 계약에 부합한다. 실제 새 후보 build·재구축·live 성공 판정은 별도 증거가 확보될 때까지 **NOT_RUN**으로 유지한다.
