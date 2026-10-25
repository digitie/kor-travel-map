# Place projection 사전 예산 검사 추출

## 범위

작은 Transport pair의 [수용된 설계](2026-10-25-transport-small-native-pair-design.md)에 앞서
국가유산에서 사용하던 순수 예산 검사만 `core/feature_projection.py`로 옮겼다.
기존 `_within_comparison_budget(values)`는 같은 signature의 wrapper로 남긴다.
`_meaning`, raw13 복원, provider presence, normalizer, Geo·lineage·적격성 판정은 바꾸지 않는다.
Transport converter/reader/DB/collector 연결이나 운영 활성화는 이번 범위가 아니다.

## 동작 보존

이동 전후 함수 본문은 이름·위치만 다르며 본문 전체 byte와 AST가 같다.
허용 정본 DTO class identity 9개, node8192/depth64/전체 byte1MiB, Enum.value의 같은 예산,
공식 BaseModel iterator·미선언 field 거부와 외부 serializer 실행 전 거부를 유지한다.
기존 caller의 고정 입력 tuple 계약을 넓히는 범용 serializer API가 아니다.
새 공통 모듈을 package root API로 export하지 않는다.
다른 Heritage 함수·클래스 AST와 `_meaning` 본문도 그대로다.

새 파일과 기존 signature를 보존하는 wrapper 추출이므로 `AGENTS.md`의
신규 파일·signature 불변 영향도 예외에 해당한다. 실제 caller는
`assess_heritage_name_refresh`이며 provider 쪽 helper/HTTP facade inventory 예외를 추가하지 않았다.
의존 방향은 기존 `providers → core → dto`다. codegraph의 실행 정확성 검증으로 보고하지 않는다.

## 실제 확인

- 새 순수16개와 기존 Heritage 적격성·선택 SDK 계약·converter98개 합집합114 PASS(2.42초), skip0.
  SDK는 기존 read-only 고정 target을 사용했고 public model/service fixture만 호출했다. 외부 HTTP0.
- 새 검사는 node8191/8192, depth64/65, JSON quote를 포함한 byte 경계,
  canonical PlaceDetail의 model_dump 미호출, 외부 serializer·미선언 field,
  과대 Enum 문자열/배열/mapping, 비유한 수와 순환 입력의 거부를 확인한다.
- Ruff3파일 PASS, strict mypy2파일 PASS, import 계약4개 PASS.
- provider inventory/자연키·프로토콜·문서 충돌 관련 정적41 PASS/기존 optional sibling checkout1 skip(4.97초).
  provider pin은 바꾸지 않았고 이 skip을 PASS에 합산하지 않는다.

사전 walk는 기존 caller가 이미 가진 객체의 할당량이나 실제 process peak를 제한한다는 뜻이 아니다.
SQL·migration·권한·API/UI 변경0, 실제 PG/worker/ARM/큰 입력·whole capture/RC/durable 수용0이다.
두 독립 소스 리뷰와 정확한 최종 CI는 아직 대기한다. 큰 pair의 evidence budget 적합성도 미완이다.
