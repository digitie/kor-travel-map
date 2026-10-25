# Transport 저장 projection 순수 진단

공항과 휴게소의 저장 raw7을 기존 `TransportAirport`/`TransportRestArea`로 복원하고
정본 `airports_to_bundles`/`rest_areas_to_bundles`를 직접 재호출한다. 기존 converter,
HTTP parser, 공개 client 서명은 바꾸지 않는다. 공통 `within_place_projection_budget`를
재사용하며 Heritage private 함수나 다른 serializer 계약을 가져오지 않는다.

## 지원 범위

새 순수 entry만 공항 `core.name`, 휴게소 `core.name`·`place.phones` presence를
각각 새 normalizer revision으로 명시한다. 휴게소 전화의 null·빈 문자열·공백은
기존 converter 결과인 `[]`를 명시 공급한다. 기존 전화 정규화가 보존하는 비정형
내선 문자열을 임의로 삭제하지 않는다. 원 legacy converter 출력에는 새 presence를
덧붙이지 않는다. old409/unknown normalizer의 저장 행을 새 revision으로 승격하지 않는다.

저장 projection은 두 종류 모두 정확한 7개 string/null 필드만 받는다. 좌표는 ASCII
128자 이내·쌍·유한·범위를 검사하고 float 복원 뒤 실제 converter의 raw/hash/key/identity
전체 roundtrip 일치를 요구한다. 소수 정밀도·표기 변화도 조용히 받아들이지 않는다.
휴게소 자연키는 기존 공개 `rest_area_natural_key(item)`와 converter가 검증한다.
원 export의 생략된 시설 flag·collection·upstream 원문을 raw7에서 복원했다고 주장하지 않는다.

초기 적격성은 **동일 raw 재관측**만이다. 이름·전화만 달라져도 현재 Geo reuse 계약상
`changed_raw_requires_ex`다. identity·facility·주소·기타 typed 의미도 전체 비교에 남긴다.
비교에서 뺀 것은 Feature/SourceLink의 생성 감사 시각과 SourceRecord 관측/적재 시각뿐이다.
link record key와 Feature/detail alias는 분리하지 않고 명시 대조한다. 과거 관측은 거부한다.

Geo 증거가 없으면 부적격이다. 좌표가 있으면 명시한 resolved token 쌍·주소·stamp 지문,
좌표가 없으면 명시 `not_requested`가 필요하며 old/new 전체가 같아야 한다. 이 객체는
호출자가 제공한 순수 비교 값이다. 실제 stamp/current head/epoch/claim/field clock/R1·R2/
모든 role link closure/retire0/권한·잠금은 DB transaction에서 별도로 증명해야 한다.
반환값은 언제나 `collector_ready=False`, `requires_database_verification=True`다.

## 예산과 검증

직렬화 전에 정본 DTO class 한정 공통 1MiB·8192노드·깊이64 검사를 수행한다.
외부 BaseModel serializer는 실행하지 않는다. 호출자는 await 동안 입력 및 내부 가변
객체를 독점 소유해야 한다. 임의 Python 코드를 sandbox하거나 입력 생성 메모리·peak RSS를
제한한다는 뜻은 아니다. 단일 행 진단은 duplicate-key/전체 EOF/manifest 검증을 대신하지 않는다.

최초 자체 시험은 자연키 helper를 잘못 호출해11 FAIL/24 PASS였다. 정본 signature에 맞춘
뒤에는 비정형 전화가 보존된다는 기존 계약을 잘못 기대한1 FAIL/34 PASS를 별도 보존했다.
제품 converter를 바꾸지 않고 시험 기대를 정정했다. 새41개와 기존 converter/parser·공통 budget16·provider inventory3의 합집합 결과를
확인했다. 원117 PASS(1.80초) 뒤 ignored flag 타입 부정1개를 추가한 최종 실행은
121 PASS(1.58초)다.
이 결과는 SDK/HTTP/DB/reader/EX baseline/worker/SH 활성화/운영 동시쓰기 증거가 아니다.

신규 module과 신규 호출만 추가한 영향도 예외다. 기존 두 converter·Transport dataclass·
공통 budget 본문 및 모든 기존 서명은 원본 그대로이며 public DTO/OpenAPI 변경도 없다.
수정 전 호출 경계는 두 기존 converter와 공통 pure helper로 한정해 직접 확인했다.
Codegraph 실행 성공이나 전체 collector 안전성으로 표시하지 않는다. 실제 reader·DB/bootstrap·
collector 배선은 다음 단계이며 이번 PR에 없다. 전체15/215 입력의 예산·적격성도 미확인이다.

## 독립 리뷰의 Decimal 경계 수정

짧은 finite 좌표 `1e999999999`와 음수의 양축 반례는 기존 `abs(Decimal)`에서
실행 문맥의 Overflow를 일으켰다. public 진단 경로의 수정 전4 FAIL(1.57초)을 보존하고
범위 검사 한 곳만 문맥 독립 `copy_abs()` 비교로 바꿨다. 포괄 예외 허용이나 입력
범위 확장은 없다. 새4개와 기존41개는45 PASS(1.32초), 앞121 합집합은 별도 세대다.
DB/HTTP/reader/collector 증거가 추가된 것은 아니다.
