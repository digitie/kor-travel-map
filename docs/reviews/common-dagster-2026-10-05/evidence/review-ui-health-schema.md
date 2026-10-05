<!-- SPDX-License-Identifier: GPL-3.0-or-later -->
<!-- SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie) -->

# Common·Map·PinVi nested health schema 독립 리뷰 B

**FULL BLOCK. J-HEALTH-SCHEMA-P2-01(P2) OPEN.** 정상 module/file/package와 요청된 null/미등록 pointer·executable[]·entry123은 기대대로 처리된다. 그러나 metadata 사전의 예약 typed key를 Dagster가 거절하는데 CLI는 정상으로 판정하는 잔여 결함을 실제 설치 wheel에서 독립 재현했다. 이전 원문은 수정하지 않았다.

## 고정 범위·격리·시간

- 실행 ID: J-HEALTH-SCHEMA-FULL-20261005-99d8-b972-2a36.
- UTC: 2026-10-05T13:12:53.384098+00:00 ~ 2026-10-05T13:16:13.663129+00:00.
- Common base7dc1d6dda955b9b836cb3f24d6fd5bcd37fabe52 → actual99d8b920438ee06eeaceb9b1240b1c48f2a62eab.
- Map basea46d7b92c0e727805348e20d60fe188592e16477 → actualb9722fd67b03798d63f2b955c445f1347ceeef8c.
- PinVi base07cfef222c56d7e648c81b017aa8ffe4ccd1c386 → actual2a36e8973bb163c68f1a778a0c1215fa8e9d02d4.
- Manifest map-pinvi-health-schema-reviewed-manifest.json SHA256 b7c34eaffadfa3d4b58e435a9c4be9c36df7780c8fa339a476ae89be470e09cc.
- 전체 Common35/Map61/PinVi15의111blob SHA256와 각 base→candidate 변경 목록을 Git 고정 객체에서 직접 대조해 모두 일치했다. docs/reviews/**는 내용 열람 없이 digest만 확인했다. 타 리뷰 원문·통합 판정을 참조하지 않았다.
- Common 고정 Git archive SHA256 9f17b18f77fa11dcb9a8eccf29f6e6125b07b1eebba46a9e4da13d0bf823620b. Scratch /home/digitie/.cache/james-map-pinvi-health-schema-20261005.
- Python3.13.14/Dagster1.13.24. 자체 archive/wheel/venv·loopback gRPC fixture만 사용했다. 외부 venv의 third-party 의존성은 읽기만 하며 제품 소스·설치·dirty 원본·DB·운영 서비스는 변경하지 않았다.

## FULL 판정과 기존 증거 재사용

공개 Python API와 runbook §10 변경이므로 Common AGENTS/agent-workflow의 비면제 FULL 대상이라고 작성자와 별도로 판단했다. Light/문서 면제를 적용하지 않는다. 원본 보존/disposition 전용 closure 예외는 이번 runtime·공용 가이드 변경을 면제하지 않는다.

Common e0b5→99d8의 health 모듈·테스트·가이드 변경을 직접 읽었다. Map6a54→b972는 API/ETL 두 Common pin과 journal뿐이다. 기존 HTTP/Dagster 복구/UI/tokens 및 Map API/UI/auth/OpenAPI/Compose bytes는 Git 비교에서 불변이고 PinVi도 동일 객체다. 따라서 이전 본인 FULL 직접 검증은 해당 불변 영역에만 재사용한다. 전체111 manifest 및 변경 목록 검증과 새 delta 직접 검토를 결합한 FULL 연속 리뷰이며, 모든 기존 테스트를 재실행했다는 뜻은 아니다. 이전 원문 map-pinvi-health-closure-review-ui.md SHA256 5fd22822c971ebf2a3130aecd718238ce1f2674414ebf15cd474cea64c91b039도 불변 확인했다.

## EXECUTED

1. 고정 Common health 테스트 **51 PASS, 1.56초**. PYTHONPATH는 본인 고정 archive이며 -I subprocess는 이번 wheel을 설치한 본인 venv Python을 실행한다.
2. 고정 archive wheel offline build/no-deps 설치 성공. wheel SHA256 13e4ece706b2525f99e509b5f36da358b0778959475277ab3420704b663203f3. 기존 third-party 경로를 읽기 전용 재사용한 것이므로 registry clean extra install이라고 집계하지 않는다.
3. 추가 직접 CLI probe: native serdes가 허용한 module/file/package pointer + nullable metadata/평문 container context 세 종류 모두 exit0. null pointer, unknown pointer, 잘못된 working directory, class 배열, executable 배열, entry 숫자/boolean, typed context, infinite context, numeric version, stateful metadata, unknown top field 12종 모두 exit1. stdout/stderr는 모두 비었다.
4. Native가 허용하는 DefsStateInfo 객체도 별도로 확인한 뒤 CLI exit1을 관찰했다. 이는 §10에서 명시한 미지원 profile 경계에 해당한다.
5. 아래 예약 키 2종은 native deserialize에서 각각 DeserializationError, 실제 동일 wheel CLI는 각각 exit0으로 재현됐다. 이를 PASS 테스트로 해석하지 않는다. Probe의 expected0은 결함 관찰값을 고정하기 위한 assert이다.
6. 실제 -I import origin이 본인 설치 wheel이며 Dagster root import가 없는 것을 확인했다.

## J-HEALTH-SCHEMA-P2-01 — P2 OPEN

**위치:** packages/py/kor-travel-common/src/kortravelcommon/dagster_health.py:96~99 및 :122~123.

**실패 형태:** 두 metadata 사전에서 values 타입만 검증하고 사전 자체의 reserved serdes key를 검증하지 않는다. 따라서 일반 dict처럼 보이는 payload를 native serdes가 typed object로 해석하며 거절하는 경우에도 health는 정상이다.

**최소 반례:** 유효한 native ListRepositoriesResponse를 JSON으로 만든 뒤 다음 두 필드 중 하나만 교체한다.

- repository_code_pointer_dict = {"__class__": {"__class__": "ModuleCodePointer", "module": "jobs", "fn_name": "defs", "working_directory": null}}
- dagster_library_versions = {"__class__": "UnknownVersionObject"}

두 payload 모두 실제 Dagster deserialize_value(payload, ListRepositoriesResponse)에서 DeserializationError. 같은 JSON을 설치된 Dagster ListRepositoriesReply protobuf로 감싸 본인 실제 loopback gRPC에서 반환하면 CLI python -I -m kortravelcommon.dagster_health는 exit0이다. 각각 0.099초/0.127초, 출력은 비었다.

**영향:** 현재 가이드의 typed/custom metadata fail-closed 보증과 정상 repository metadata 판정이 어긋난다. 자식 metadata를 native 소비자가 사용할 수 없어도 Docker health는 healthy로 남아 복구 판단을 잘못할 수 있다. 이전 substring 결함은 고쳤지만 이 유형까지 closure됐다고 볼 수 없다.

**최소 수정/폐쇄 조건:** 일반 metadata 사전에서 Dagster typed-key namespace를 명시적으로 거절하라. Pointer 객체 자체의 허용 __class__와 일반 mapping의 금지 key를 구분해야 한다. 두 반례 및 정상 module/file/package 실제 installed CLI 회귀, 유지되는 loopback·4초·4MiB·cleanup·no-heavy-import를 새 고정 후보에서 확인해야 한다.

**재현:** /home/digitie/.cache/james-map-pinvi-health-schema-20261005/cli-venv/bin/python /home/digitie/.cache/james-map-pinvi-health-schema-20261005/reserved-key-cli-probe.py.
Probe SHA256 a137ca5b731e949bca7a4efc61a2648c502f03c71fb26542370aefbabaa154dc; 결과 reserved-key-cli-result.txt SHA256 98265d4fb3749674c4ecd3a68607da9f8cf84b57a6ef26e359e4c88b0263ed70. 본인 fixture는 ephemeral loopback port만 쓰며 finally에서 server/executor를 닫는다.

## 기존 disposition·지원 경계

J-STANDALONE-P2-01(P2)은 기존 빈 reply/{} 거절과 정상 응답 허용 수정이 유지되어 FIXED이다. 본인 기존 consumer·HTTP findings도 byte불변 범위에 기존 FIXED를 유지한다. 새 P2는 그 disposition을 덮어쓰지 않는다.

표준 module/file/package만 지원하고 stateful/custom/unknown metadata를 미지원으로 명시한 선택 자체는 현재 Map module location의 최소 health 계약으로 정당하다. 임의 Dagster serdes 대체물이라고 주장하지 않고 version/profile 확장 전에 native positive/negative 검증을 요구하는 점도 적절하다. 다만 현재 구현이 위 reserved mapping을 거절하지 못하므로 “typed metadata를 정상으로 추측하지 않는다”는 보증은 아직 충족하지 못한다. 새로운 타입을 모두 정상 처리하도록 범위를 넓히는 방식으로 이 finding을 닫으면 안 된다.

## NOT_RUN

새 CI/운영 pair Docker 재구축/live E2E, production Dagster proxy+child 실제 기동, native job 실패/회수/재시도, floor1.9·다중버전, 전체146/139 및 전체 Map/PinVi 회귀 독립 재실행, clean network extras install은 미실행이다. Root 수행 수치를 본인 실행에 합산하지 않았다. 실제 CLI RPC는 본인 fixture이고 운영 실행이 아니다.

**최종: FULL BLOCK — J-HEALTH-SCHEMA-P2-01 OPEN.**
