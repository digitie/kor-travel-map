# 공항 최종 입력의 한정 typed codec

## 범위와 소유권

이 checkpoint는 `619a6d4f121c24521fb6fcbec17274081641082f`에서 분리한 새
`infra/provider_snapshot_artifact.py`, 그 unit, 이 보고서만 소유한다. 기존 DTO,
converter, 공통 예산 함수, SQL/권한/DB/control/파일 저장 경로는 바꾸지 않았다.
기존 심볼과 signature를 변경하지 않는 신규 파일이므로 AGENTS.md의 Codegraph
영향도 생략 조건에 해당한다. 별도 PR은 만들지 않고 전체 동시 쓰기 단위에 합성한다.

이 codec의 성공은 최종 typed 입력의 복원 가능성이다. 원천 전체 EOF, DB 재검증,
Geo 증거의 권한, collector 준비, SH apply, 취소·복구나 운영 수용을 뜻하지 않는다.
파일 내용의 출처/무변조 binding은 Root가 소유한 별도 control 경계가 담당한다.
명시 pins가 같다는 것만으로 실제 코드/SDK 출처가 증명되지는 않는다.

## 고정 계약

`encode_provider_snapshot_artifact(bundles, geo, pins=...)`는 bytes를 반환하고,
`decode_provider_snapshot_artifact(raw, expected_pins=...)`는 독립적인
`DecodedSnapshotArtifact(bundles, geo, native_input_digest)`를 반환한다.
파일·환경·Git·DB 조회, HTTP, SDK 재호출, pickle, 임의 class 경로 로드는 없다.

Envelope는 `version=1`, `domain=airport-prepared-typed-v1`, `pins`,
`native_input_digest`, `bundles`, `geo`의 정확한 여섯 키다. pins는 호출자가 전달한
code revision 40hex, SDK inventory SHA256 64hex, provider/dataset/entity,
normalizer revision, Geo/clock domain, 기존 `native-full-refresh-v1` domain이다.
각 값은 decode의 명시 기대값과 정확히 같아야 한다. provider 계층을 import하거나
새 public SDK façade를 만들지 않는다.

Airport `FeatureBundle` tuple와 `GeoLoadContext|None`만 첫 지원 범위다.
정본 공항 raw의 정확한 일곱 string/null 키, place/airport, primary/unexpired source,
source key/payload hash, `core.name` presence 및 고정 normalizer pin을 확인한다.
공통 bounded full snapshot 검사를 재사용한다. retire 옵션은 기존 공항 준비 경계의
`retire_geometryless_areas=True`로 고정한다. 다른 dataset 적격성을 추측하지 않는다.

## 값과 필드 존재의 보존

모든 선언 필드의 실제 값을 저장하며 default factory 시각도 생략하지 않는다.
모델마다 `model_fields_set`을 따로 보존한다. decode는 완전한 필드 집합을 확인한 뒤
bottom-up 정본 `model_validate(strict=True)`를 실행하고, 검증한 값의 fieldset만 복원한다.
복원값을 다시 인코딩한 전체 canonical bytes가 원 bytes와 같아야 한다. default 시각을
다시 생성하거나 `exclude_unset`으로 실제 기본값을 잃어버리지 않는다.

고정 모델 열한 종류와 enum 다섯 종류의 class identity만 허용한다. Decimal은 원문
표기를 통해 exponent/sign/trailing zeros를 보존하고, datetime은 aware ISO 값과
UTC/KST/고정 offset·이름 및 fold를 보존한다. list/tuple/set/frozenset 경계를 구분한다.
Any 내부에서도 int/float/bool/null, Decimal/datetime과 집합·tuple 차이를 보존한다.
임의 timezone, 외부 모델/serializer, URL, 날짜형 licence, business hours, file/admin/
geo-attempt 및 비어 있지 않은 raw refs/review 링크는 첫 범위에서 미지원이다.

원본 caller는 encode 동안 가변 입력을 독점 소유한다. decode 결과의 tuple/frozen
결과 dataclass 안 DTO는 여전히 가변이다. 후속 await 중 독점 소유 규율은 남는다.
Geo observed set의 원 live alias는 공유하지 않고 독립된 snapshot을 만든다.
`None`, 빈 set, 빈 frozenset 및 실제 token 집합의 구분은 보존한다.

## 예산과 거부

DTO와 Geo 고정 필드를 합친 원천에 공통 1 MiB/깊이64/노드8192 예산을 먼저 적용한다.
외부 serializer/model_dump 또는 원천 hash보다 먼저 실행하며, pins는 deepcopy 없이
고정 필드를 직접 검사한다. 제한 뒤에만 한정 타입의 wire 값을 만들고 JSON streaming
encoder로 envelope/fieldset/tag를 포함한 전체 UTF8 출력도 1 MiB에서 중단한다.
수량은 비어 있지 않은 tuple, 최대2730이며 그 수량까지 성공한다는 주장은 아니다.

decode는 JSON 객체를 만들기 전에 bytes1 MiB, strict UTF8, 컨테이너 깊이64 및
wire node8192를 검사한다. 중복 JSON 키, NaN/Infinity, extra/unknown model/tag,
비정규 canonical 표현, 모든 pin/domain 불일치를 거부한다. 모델 내부의 중복 dict key,
중복 집합 원소, 잘못된 fieldset/누락 필드도 허용하지 않는다.

8192 source/wire node는 이 작은 Airport codec의 지원 한도다. kernel manifest의
8192 dependency 한도와 같은 개념이 아니다. RestArea215나 전국 입력 지원은 이번
결과로 추정하지 않으며 상한을 임의로 올리지 않는다.

## 실제 순수 검사

공개 `TransportAirport` → 기존 native converter가 만든 synthetic 공항15를 사용했다.
무Geo 입력의 envelope는 47,493 B/4,503 wire nodes, resolved Geo 입력은
49,957 B/4,769 wire nodes였다. 이 크기는 해당 synthetic 입력 한정이며 운영15건의
실측값이나 전체 입력 fit을 증명하지 않는다. default clock의 실제 값이 포함되므로
native digest는 실행마다 바뀔 수 있으나 같은 입력의 encode/decode 사이에는 같다.

신규51 unit와 기존 공통 예산/Transport native/공항 preparation77 unit를 함께 실행해
총128 PASS/3.21초였다. 별도 첫35 PASS와 후속49 PASS도 원로그로 보존한다.
공항15×Geo 유무, 모든 nested fieldset/default clock/Decimal tuple, UTC/KST/fixed
시각, Geo None/empty/container identity, source key/hash/FeatureID/presence/native
지문과 canonical byte 왕복을 검증했다. 거부 반례는 pins 전부, 중복키, NaN/Infinity,
UTF8/depth/node/byte, foreign serializer/deepcopy/timezone, 변경된 DTO extra/누락,
fieldset/URL/naive clock, 원천 합산 예산 선검사와 출력 envelope overhead를 포함한다.

초기 Ruff14/mypy5 실패는 새 파일의 형식·타입 선언 문제로 보존했고 수정했다.
독립 source 리뷰와 전체 합성 CI, 파일/control/durable 경계, operating 및 두 worker
DML 병행 수용은 아직 수행하지 않았다. PG·운영 변경은 0이다.

## e2b6 source 리뷰의 P2와 선검사 보완

e2b6의 첫 독립 리뷰에서 Any payload에 들어간 미지원 `Mapping.items()`가 공통
예산 검사 중 먼저 호출되어 RuntimeError로 탈출하는 반례가 나왔다. J의 공개 encode
재현과 첫 checkpoint/HOLD 원장을 보존한다. 처음51 unit가 통과했다는 사실을 이
경계의 수용으로 재해석하지 않는다.

수정은 common budget/pack/hash보다 먼저 실행하는 iterative exact-type 선검사다.
허용 모델의 정확한 class·builtin dict/fieldset·선언 키를 확인하고, builtin container만
순회한다. 외부 Mapping 및 dict/str/int/list/set subclass의 hook은 호출하지 않는다.
Geo의 고정 필드도 같은 전체 source 예산에 포함한다. 문자열 UTF8/JSON escape 비용은
거대한 직렬화 복사 없이 문자별로 선누적하며, self reference도 깊이64 또는 node8192에서
유한 중단한다. 기존 codec/validator/digest 본문과 상한은 그대로다.

신규10개 public 거부 반례는 foreign hook 호출0 및 common budget/pack/hash 미진입을
함께 단언한다. 기존51+신규10 및 관련77을 합쳐138 PASS/3.79초였다. 실제 converter
15 왕복을 함께 재실행했다. 외부 source/DB/control 및 운영 배선은 여전히 없으며,
수정 source의 두 독립 gate가 닫히기 전 전체 수용은 미완이다.

동일 선검사의 추가 자체 점검에서 `__pydantic_extra__` truthiness도 외부 hook을
부를 수 있어 정확히 `None`만 허용하도록 바꿨다. 정본 모델의 기본 extra 저장소는
모두 `None`이다. 새 public 반례1개를 더해 최종139 PASS/3.32초(신규62+관련77)이며
이전138 결과는 별도 source 세대 기록으로 보존한다.

## builtin timezone 이름 예산의 추가 P2

c2a5의 별도 J public 반례에서 exact builtin timezone도 임의 길이 이름을 보관한다는
예산 누락을 확인했다. datetime의 고정128비용만으로는 그 이름을 wire에 복사하기 전
차단하지 못했다. c2a5/HOLD와 기존 반례는 보존한다.

선검사는 builtin timezone의 이름을 exact str·최대128자로 먼저 제한하고, 전체 source
문자열 UTF8/escape 예산에도 직접 누적한다. decoder의 기존 이름128 한도와 같으며
상한을 늘리지 않는다. ZoneInfo key도 exact str인 고정 Asia/Seoul만 허용한다.
초대형 이름/str subclass 이름/잘못된 surrogate 세 public 반례에서 common budget,
pack, hash 진입과 외부 name hook이 모두0임을 확인했다. 정상UTC/KST/fixed offset
및 실제 converter15 왕복을 포함해 최종142 PASS/3.48초(신규65+관련77)였다.
독립 최종 source gate·DB/control 연결과 operating 수용은 여전히 별도다.
