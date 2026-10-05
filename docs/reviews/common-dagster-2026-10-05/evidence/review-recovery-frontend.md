# Map / PinVi Docker frontend 고정 후보 독립 연속 FULL 리뷰 — 복구·DB·메모리 관점

작성일: 2026-10-05
판정: **FULL 연속 PASS**. 새 차이에서 merge를 막는 결함을 발견하지 않았다. 실제 새 후보 CI·Docker rebuild·운영 live 성공을 의미하는 판정은 아니다.

## 고정 입력과 독립성

- manifest: `map-pinvi-frontend-reviewed-manifest.json`
- manifest SHA256: `ee1ca0f4f5c1e6ebc196ecf42668f3ae7a82133059f0037143bd40e0a3647c01`
- Map base: `0342034f020cc07af2094f216456f64e45e39ed2`
- Map candidate: `c4d62a793ba69a60543fafda7442b3ba2c019ad1`
- PinVi base: `07cfef222c56d7e648c81b017aa8ffe4ccd1c386`
- PinVi candidate: `2a36e8973bb163c68f1a778a0c1215fa8e9d02d4`
- Common HTTP 제품: `1f8e339c7c79f86f8952b0d4c326ab4dae56bee8`

Linux Git의 exact candidate source archive를 본인 ext4 경로 `/home/digitie/.cache/recovery-review-frontend-fixed-2a36e89/{map,pinvi}`에 만들었다. 사람의 dirty checkout에서 소스·설정·설치를 변경하지 않았다. N150/DB/운영 Docker에 접속하지 않았고, 제품 실행·commit·push·peer 원문 열람을 하지 않았다. 이번 Weather 쓰기는 이 보고서 하나뿐이다. 기존 PinVi AGENTS/SKILL의 Linux·책임 경계와 Docker runbook을 적용했으며, 이번 요청의 읽기 전용 범위를 우선했다.

## manifest 전체 범위와 byte 동일성

직접 수행한 검증:

1. manifest 원본 SHA256 일치.
2. Map 59개 / PinVi 15개 모든 manifest 파일 SHA256을 본인 source archive에서 재계산하여 일치.
3. 각 repo의 `git diff --name-only BASE CANDIDATE` 전체 경로 집합과 manifest 경로 집합이 정확히 일치. 추가·누락 경로 없음.
4. 이전 PinVi `aa265cf1c3917b9d0e89316d06c35678d23757c2`에서 새 후보까지 전체 Git diff 경로는 `apps/api/Dockerfile`, `apps/etl/Dockerfile`, `docs/journal.md` 세 개뿐.
5. 두 Dockerfile의 새 첫 줄과 새 설명 주석을 제외한 나머지 모든 instruction/comment 줄은 이전 aa와 같음을 직접 assertion으로 확인. API/ETL/web 첫 syntax 줄이 정확히 동일.
6. Map은 직전 FULL 연속 PASS 후보 c4와 같은 commit. PinVi Python/API/ETL/UI/locks/Common Git pin/M05 provenance 및 나머지 모든 tracked 파일은 aa와 byte 동일. 새 Docker frontend 해석기의 선택만 변경되므로 새 빌드 산출물 자체가 byte 동일하다고 주장하지 않는다.

독립 검증 결과: `/home/digitie/.cache/recovery-review-frontend-fixed-2a36e89/independent-verification.json`
SHA256: `c66c161eb0e96c0a31f2baeb679b7e37d59c8ed40ea27f338aacfe55674fac89`

수행한 핵심 명령은 WSL Ubuntu-26.04에서 다음과 같다.

```bash
sha256sum /mnt/f/dev/kor-travel-weather/.playwright-mcp/map-pinvi-frontend-reviewed-manifest.json
git -C /mnt/f/dev/pinvi-codex diff aa265cf1c3917b9d0e89316d06c35678d23757c2 2a36e8973bb163c68f1a778a0c1215fa8e9d02d4 --stat
git -C /mnt/f/dev/pinvi-codex diff aa265cf1c3917b9d0e89316d06c35678d23757c2 2a36e8973bb163c68f1a778a0c1215fa8e9d02d4 -- apps/api/Dockerfile apps/etl/Dockerfile docs/journal.md
```

archive/전체 검증은 Python 표준라이브러리 `subprocess.check_output(["git", "-C", root, "archive", "--format=tar", candidate])`, `tarfile.extractall(..., filter="data")`, `hashlib.sha256(read_bytes())`와 경로 집합 assertion으로 수행했다. Python 실행기는 읽기 재사용한 `/home/digitie/.cache/map-common-recovery-venv/bin/python`이다.

## 새 Dockerfile delta 독립 검토

두 파일 첫 줄은 다음의 고정 참조로 바뀌었다.

```dockerfile
# syntax=docker/dockerfile:1.7.1-labs@sha256:b99fecfe00268a8b556fad7d9c37ee25d716ae08a5d7320e6d51c4dd83246894
```

지시자가 첫 줄에 있고 뒤에 한국어 설명 주석을 추가했으므로 parser directive 위치를 훼손하지 않는다. 기존 web의 동일 digest를 API/ETL로 확장한다. API/ETL의 FROM/base digest, ARG/provenance 검증, ENV, apt Git 의존성, COPY 경로, pip/uv 설치, Common 의존 계약, workspace/instance COPY, HEALTHCHECK, CMD는 그대로다. 따라서 이전 R01 Git 설치 / R02 Hatch direct-reference / R03 request client disposal / R05 repository shape·identity closure를 되돌리지 않는다. Map R04/R06도 동일 소스에 유지된다.

[Docker 공식 frontend 계약](https://docs.docker.com/build/buildkit/frontend/)을 직접 읽었다. 첫 줄 `syntax`에 image tag+digest 참조를 쓸 수 있고, labs 특정 버전으로 해석기를 고정하는 형태와 부합한다. 이번 검토는 해당 registry digest를 다운로드하거나 빌드하여 바이너리를 확인하지 않았다. 명령줄 `BUILDKIT_SYNTAX`로 별도 frontend를 override하지 않는 표준 빌드 경로를 전제로 한다.

새 journal은 API 첫 시도와 ETL retry1의 frontend gRPC 실패, web의 기존 pinned frontend 성공을 구분하며, digest 정렬이 gRPC 종료의 단일 근본 원인이라고 확정하지 않는다. 운영 전환/live/merge가 미완료라는 기록도 이번 검증 범위와 맞는다. 부모의 provenance/pair 102 PASS는 참고 정보이며 본인이 실행한 PASS로 합산하지 않는다.

새 차이 발견 blocker: **없음**. frontend 수정에 대한 실제 빌드 호환성은 후속 CI/rebuild에서 확인해야 한다.

## 이전 FULL 증거 재사용 범위

원문 hash를 이번에도 직접 다시 확인했다. 아래 기존 원문은 편집하지 않았다.

| 원문 | SHA256 |
| --- | --- |
| 초기 BLOCK map-pinvi-final-review-recovery.md | fb4d433b97c344eeac7e500f214ef9d98909984354ab84bda02c3e4bcc0ab58c |
| postfix BLOCK map-pinvi-postfix-review-recovery.md | 8ed2bc7f78ec0dee76c36d02b9fb002870acfd6a29b6dd24a5371188d09fbd14 |
| 제품 FULL PASS map-pinvi-final-closure-review-recovery.md | e60fc4115dde0c64b8650dfe416e08efab28f9bbed20f278a4d750e8fe73b6b4 |
| fixture 연속 PASS map-pinvi-integration-closure-review-recovery.md | 522af1fd9537c62f19cb80e8913decc492bbb1bf5ea70dd379fecec65547ecb3 |
| main 문서 연속 PASS map-pinvi-latest-main-closure-review-recovery.md | 3879bda0dabdc8b2d5636afa984bf1d999fb19fbe6d1259de2cf1a19846a3dcf |

기존 제품 FULL 단계에서 직접 수행한 Map API/Dagster focused 1287 PASS, Map provider/core 184 PASS, PinVi API/contract 46 PASS, 합계 1517 PASS를 동일 기능 소스에 대한 유효한 증거로 재사용한다. 이번에 새로 pytest를 실행하거나 1517을 추가 PASS로 중복 집계하지 않았다.

기존 직접 공격은 snapshot 8종 배치 100/최종 atomic seal/재수집 dedup/late failure rollback, pool1 로컬 SQLite·Fake SQL 경계, configured executor actual cap, run runtime/retry tags, active merge·owned repository identity, bounded HTTP 압축/응답 크기/실제 loopback transport, cancellation·cleanup 원예외 보존, PinVi request client disposal·패키지 metadata를 포함한다. 이전 native autoload 검증도 변경 없는 Dagster source에 연결된다. asset STEP RetryPolicy 3회와 RUN retry0은 서로 다른 계약이며 기존 보고서의 구분을 유지한다.

24de fixture 단계의 별도 6건 직접 검사(실제 HTTPX MockTransport/Starlette Request.state/production middleware: 정상·ValueError·CancelledError에서 요청별 새 client 및 exactly-once close, 기본 외부 HTTP transport 차단)는 변경 없는 Map fixture에 재사용한다. canonical projection 기존 310 assertion과 추가 1 assertion을 보존했다는 AST 검사도 그대로 유효하다. 이 6건은 DB integration 전체 실행을 뜻하지 않는다.

## 직접 수행 / NOT_RUN 경계와 최종 판정

직접 수행: exact source archive, manifest SHA 및 74개 전체 파일 hash, 전체 base delta 경로 검증, aa→새 후보 전체 3파일 검토, 두 Dockerfile instruction byte 동일성/기존 web frontend 동일성 assertion, Docker 공식 syntax 문서 확인, 기존 다섯 원문 hash 불변 확인.

이번 새 pytest 실행: 없음. 앞선 1517 PASS 및 fixture 6건은 명시적으로 재사용한 본인 증거다.

NOT_RUN: 새 candidate CI, Docker pull/build 및 N150 guarded rebuild, operating image attestation, actual shared Dagster daemon/PG/domain SQL, browser live/E2E, 운영 mutation/merge. 별도 native fault 하니스 읽기 전용 검토는 이 제품 FULL 테스트 합계에 넣지 않았다. 부모의 CI10 PASS/paired build 실패·retry 및 102 tests는 본인 수행으로 집계하지 않았다.

전체 manifest 변경 범위는 기존 독립 FULL 제품 리뷰와 byte 동일성으로 연결하고, 새 두 Dockerfile과 journal을 직접 검토했다. 최종 **FULL 연속 PASS**를 기록하되, 실제 새 frontend를 이용한 빌드·운영/live gate는 아직 완료되지 않았다.
