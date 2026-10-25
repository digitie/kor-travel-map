# RestArea snapshot pure codec — 실험 profile 구현

## 현재 범위

수용된 [431 설계](2026-10-25-rest-area-snapshot-profile.md)를 Root1411
`7f40e95b98233b0885c263e2e3c90736a114702c` 위로 상속했다. 새 pure Rest codec과
기존 Airport의 exact-type 선검사/wire 스캔 공유만 구현했다. SQL·reader·등록·collector
분기·권한·운영 flag 변경0이다. J가 별도 소유한431 reader/Geo 증거와 이 codec는
아직 연결하지 않았으며 운영 휴게소215 fit/DB 적격성·전체 동시 worker를 수용하지 않는다.

## 고정 profile과 보존 범위

| 구분 | Airport 기존값 | Rest 실험 후보 |
| --- | ---: | ---: |
| 최대 item | 2730 | 256 |
| whole typed node | 8192 | 65,536 |
| 선검사 source byte 모델 | 1MiB | 2MiB |
| wire token | 8192 | 131,072 |
| wire 전체 bytes | 1MiB | 1MiB |
| source/wire depth | 64 | 64 |

Rest 후보는 코드 내부의 두 고정 enum profile 중 하나다. caller가 arbitrary domain/
상한/whitelist를 전달하거나 globals를 바꾸는 경로가 없다. Rest의 각 행은 기존
Place whitelist·1MiB/8192 guard도 그대로 통과해야 하며, 기존 `bounded_full_snapshot`과
native `_artifact_digest`의1MiB 검사는 유지했다. source2MiB는 durable payload2MiB나
기존 정본 native 지문 한도 확대를 뜻하지 않는다. 실제 PG/RSS·입력 계량 전 운영값은 미확정이다.

공통 private `_snapshot_artifact_codec.py`에는 exact-type preflight와 wire scanner 및
동일한11 DTO/5 enum class registry만 옮겼다. Airport의 `_preflight(values)`와
`_guard_wire(raw)`는 기존 signature·고정 Airport wrapper를 유지한다. 잘못된 UTF8의
UnicodeError 전파도 유지하며 나머지 class/함수 본문·공개 signature·상한은 그대로다.
원 `_snapshot`의 preflight→common budget→pack→hash 순서와 기존 sentinel patch 회귀도 유지했다.
Rest는 기존 domain-free pack/unpack/stream JSON·pin/decoded DTO·정본 native digest를 재사용한다.
기존 심볼 signature 변경이 없어 AGENTS.md의 신규 private helper/기존 signature 불변
Codegraph 생략 예외를 적용했다. production 소비자는 기존 공개 encode/decode/pin DTO를 사용한다.

## Rest exact 계약

공개 pure 함수는 `encode_rest_area_snapshot_artifact`와
`decode_rest_area_snapshot_artifact`, 실패는 `UnsupportedRestAreaSnapshotArtifact`다.
원 `SnapshotArtifactPins` 구조를 재사용하되 scope는 provider=`kor-travel-transport`,
dataset=`transport_rest_areas`, entity=`rest_area`,
normalizer=`transport-rest-area-name-phones-v1`, Geo=`transport-rest-area-geo-v1`,
clock=`aware-clock-preserved-v1`, native=`native-full-refresh-v1`에 고정한다.
wire domain은 `rest-area-prepared-typed-v1`이며 version1/정확6개 envelope key를 쓴다.
코드 revision40hex/SDK inventory64hex도 exact expected pins와 일치해야 한다.
이 값은 caller가 검증한 pin이며 코드/SDK 출처 자체를 증명하지 않는다.

정본 `TransportRestArea`→기존 converter/native adapter의 최종 FeatureBundle tuple과
GeoLoadContext를 저장한다. raw7/name+phones presence·null/공백 전화의 명시 `[]`,
원 payload hash/source/link/identity, 전체 모델 fieldset/default clock·Any datetime/Decimal,
Geo None/empty set/frozenset 차이를 보존한다. model JSON을 새 기본값으로 재검증하지 않고
모든 값을 명시 복원한 뒤 원 fields_set을 복구한다. 별도 객체로 decode하므로 caller 입력과 alias하지 않는다.
원본 가변 DTO는 encode 동안 caller가 독점 소유해야 한다.

exact-type 선검사가 외부 Mapping/모델 serializer/str·int subclass/불가 timezone hook보다 먼저다.
whole count/source byte/node/depth가 초과하면 pack/hash를 부르지 않는다. wire byte/token/depth는
JSON 객체 생성 전에 검사한다. duplicate key/NaN/비UTF8/extra/domain·pin·digest drift와
불일치 identity/hash/link, mixed/duplicate source는 전행 거부하며 일부 결과는 반환하지 않는다.
자연키의 원 정규화/converter·신선한 DB Geo/lineage/현재 정책 의미 권위는 재구현하지 않는다.
후속 reader/assessment가 그 의미와 unchanged raw 재사용을 실제 DB 증거로 검증해야 한다.

## 순수 검증과 수치

최종 codec/Rest/Airport observation/postprocess 합집합 **231 PASS/24.19초, skip0**다.
그중 기존 Airport codec65, 신규 Rest60이며 나머지는 기존 observation71/postprocess35다.
선행 Airport 추출만65 PASS/4.18초와 초기 Rest57 PASS/10.44초를 별도 로그로 보존했다.
최종 Ruff4 source/test PASS, mypy strict 설정3 source PASS, import 계약4 kept/0 broken을 확인했다. 문서·task·링크18 PASS/2.91초다.
SQL·PG·새 collector 실행은0이다.

synthetic215의 실제 정본 converter→encode→decode→재encode를 별도 프로세스에서 계량했다.
전체 fieldset/typed 값·원시각·키·hash·Geo가 같고 canonical byte 재encode가 같았다.

| Geo | 실제 wire bytes | 작업 CPU초 | wall초 | 전체 프로세스 RSS high-water KiB |
| --- | ---: | ---: | ---: | ---: |
| None | 697,315 | 2.613 | 2.614 | 139,092 |
| resolved | 726,779 | 3.511 | 3.511 | 140,752 |

위 RSS에는 import/프로세스 전체가 포함되고 작업은 encode 한 번이 아닌 변환·decode·재encode까지다.
운영 raw/전체 서비스 peak·PG CPU/RSS·apply 비용으로 확대하지 않는다. 기존 설계의
733,671B는 다른 synthetic framing 계량이고 이번 값은 실제 lossless codec 출력이다.
둘 모두 실제 운영215 payload가 같은 크기라는 뜻이 아니다.

## 남은 수용

두 독립 source 리뷰와 최종 CI가 미완이다. Rest reader의 실제 bounded metadata/encoded
A/B CPU/RSS/plan·운영 승인 RO 입력 fit, EX baseline/정본2scalar lineage와 나머지23 의미,
Geo proof, 명시 등록/관측/후처리/runtime, 주간 GC/quota·취소/unknown commit·두 worker DML
중첩·공유 Feature 정합은 별도 후속이다. 원 Airport opt-in/DB/동작은 변경하지 않았다.
430의 apply/result와 후처리/child seal/root 별도 TX를 상위 whole finalseal 한 commit 완료로 세지 않는다.

## 원장

| 원장 | SHA-256 |
| --- | --- |
| `map-rest431-codec-final-r2.log` | `34437f6f7ec556efdbd375c8b96543b7f4e79f4b0e31f5924228d2f1f8db5759` |
| `map-rest431-codec-final-r2.xml` | `16e86f61158388f286e9207928dfd759a873b54fa4b366c430b03214ba611d80` |
| `map-rest431-codec-215-unresolved-proof.json` | `e94e16e75706493664fa86cb39403745fadf5dbc03c461feeee17aeab4906830` |
| `map-rest431-codec-215-resolved-proof.json` | `81a88fab5876c57fb469e072f92148e3158c15efe7462ed9a0f2139ceafa1e26` |
| `map-rest431-codec-r1-mypy.log` | `8228fcc5ce46d42d01caf3cd941f4e9c5f2bcc372bb5b147a2f0572d2dd675a8` |
| `map-rest431-codec-final-r2-ruff.log` | `82b3e6a6c090a57601d22943bd23fca9218d1031dbe5a7b754092f9a156b4f18` |
| `map-rest431-codec-r3-imports.log` | `e129837597ef56483313d1c75c1cd2c0e80991c40f2e053d027c6c09991429e6` |
| `map-rest431-codec-r1-preservation-source-proof.json` | `957db3d0a753e8bccb925eae4981c3b71396e85fad1350ba367e68ec1cc8aa98` |
